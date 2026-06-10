"""
rules.py
--------
Deterministic post-processing rules that compare extracted label values
against COLA application data and assign FieldResult statuses.

Design principle: no LLM calls happen here. All logic is auditable Python
that can be unit-tested without an API key.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from models import ApplicationData, FieldResult, FieldStatus

# ── Government warning ────────────────────────────────────────────────────────
# Statutory text required on all alcohol beverages sold in the US (27 CFR 16.21).
# The opening "GOVERNMENT WARNING:" must be in all caps and bold per TTB rules.
# We check the full text with normalised internal whitespace.

GOVERNMENT_WARNING_TEXT = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)

# Pre-compiled regex: matches the statutory text with any internal whitespace variation.
_WARNING_WORDS = GOVERNMENT_WARNING_TEXT.split()
_WARNING_PATTERN = re.compile(
    r"\s+".join(re.escape(w) for w in _WARNING_WORDS),
    re.IGNORECASE,
)

# The header must be EXACTLY all-caps (per Jenny Park's requirement).
_WARNING_HEADER_PATTERN = re.compile(r"^GOVERNMENT WARNING:", re.MULTILINE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace, strip punctuation."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fuzzy_ratio(a: str, b: str) -> float:
    """Return a similarity ratio between 0.0 and 1.0."""
    return SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()


def _parse_abv(text: str) -> float | None:
    """
    Extract a numeric ABV percentage from a string.
    Handles: '45%', '45% Alc./Vol.', '45% Alc./Vol. (90 Proof)', '45.0 percent'.
    Returns None if no number found.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|alc)", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _parse_proof(text: str) -> float | None:
    """
    Extract a proof value from a string, e.g. '45% Alc./Vol. (90 Proof)' -> 90.0.
    Returns None if no proof figure is present.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:°\s*)?proof", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _parse_age_years(text: str) -> float | None:
    """
    Extract an age in years from a string, e.g. 'Aged 3 Years' -> 3.0,
    'Aged 18 Months' -> 1.5. Returns None if nothing parseable.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*year", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*month", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 12.0
    return None


def _parse_ppm(text: str) -> float | None:
    """Extract a parts-per-million figure, e.g. '25 ppm' -> 25.0, '0' -> 0.0."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*ppm", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*$", text)
    if match:
        return float(match.group(1))
    return None


def _parse_volume_ml(text: str) -> float | None:
    """
    Extract a volume in mL from a string.
    Handles: '750 mL', '750ml', '750 ML', '1 L', '1.0 L', '1000 mL'.
    Always returns mL.
    """
    text_lower = text.lower().replace("\xa0", " ")
    # mL / ml
    match = re.search(r"(\d+(?:\.\d+)?)\s*ml\b", text_lower)
    if match:
        return float(match.group(1))
    # Litres
    match = re.search(r"(\d+(?:\.\d+)?)\s*l\b", text_lower)
    if match:
        return float(match.group(1)) * 1000
    return None


# ── Individual field rules ────────────────────────────────────────────────────

def check_brand_name(
    application_value: str,
    label_value: str | None,
    confidence: float,
    pass_threshold: float = 0.92,
    warning_threshold: float = 0.80,
) -> FieldResult:
    if label_value is None:
        return FieldResult(
            field_name="Brand Name",
            application_value=application_value,
            label_value=None,
            status="NOT_FOUND",
            notes="Brand name was not found on the label.",
            confidence=confidence,
        )

    ratio = _fuzzy_ratio(application_value, label_value)

    if ratio >= pass_threshold:
        status: FieldStatus = "PASS"
        notes = ""
    elif ratio >= warning_threshold:
        status = "WARNING"
        notes = (
            f"Brand names are similar but differ (similarity {ratio:.0%}). "
            f"Application: '{application_value}' / Label: '{label_value}'. "
            "Review for intentional formatting differences."
        )
    else:
        status = "FAIL"
        notes = (
            f"Brand names do not match (similarity {ratio:.0%}). "
            f"Application: '{application_value}' / Label: '{label_value}'."
        )

    return FieldResult(
        field_name="Brand Name",
        application_value=application_value,
        label_value=label_value,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_class_type(
    application_value: str,
    label_value: str | None,
    confidence: float,
) -> FieldResult:
    if label_value is None:
        return FieldResult(
            field_name="Class/Type",
            application_value=application_value,
            label_value=None,
            status="NOT_FOUND",
            notes="Class/type designation not found on the label.",
            confidence=confidence,
        )

    if _normalise(application_value) == _normalise(label_value):
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"Class/type mismatch. "
            f"Application: '{application_value}' / Label: '{label_value}'."
        )

    return FieldResult(
        field_name="Class/Type",
        application_value=application_value,
        label_value=label_value,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_alcohol_content(
    application_value: str,
    label_value: str | None,
    confidence: float,
    tolerance: float = 0.1,
) -> FieldResult:
    if label_value is None:
        return FieldResult(
            field_name="Alcohol Content",
            application_value=application_value,
            label_value=None,
            status="NOT_FOUND",
            notes="Alcohol content not found on the label.",
            confidence=confidence,
        )

    app_abv = _parse_abv(application_value)
    label_abv = _parse_abv(label_value)

    if app_abv is None or label_abv is None:
        # Fall back to normalised string comparison
        if _normalise(application_value) == _normalise(label_value):
            return FieldResult(
                field_name="Alcohol Content",
                application_value=application_value,
                label_value=label_value,
                status="PASS",
                notes="",
                confidence=confidence,
            )
        return FieldResult(
            field_name="Alcohol Content",
            application_value=application_value,
            label_value=label_value,
            status="WARNING",
            notes=(
                "Could not parse numeric ABV from one or both values for comparison. "
                f"Application: '{application_value}' / Label: '{label_value}'. Manual review recommended."
            ),
            confidence=confidence,
        )

    diff = abs(app_abv - label_abv)
    if diff <= tolerance:
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"ABV differs by {diff:.2f}%. "
            f"Application: {app_abv}% / Label: {label_abv}%."
        )

    return FieldResult(
        field_name="Alcohol Content",
        application_value=application_value,
        label_value=label_value,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_net_contents(
    application_value: str,
    label_value: str | None,
    confidence: float,
) -> FieldResult:
    if label_value is None:
        return FieldResult(
            field_name="Net Contents",
            application_value=application_value,
            label_value=None,
            status="NOT_FOUND",
            notes="Net contents not found on the label.",
            confidence=confidence,
        )

    app_ml = _parse_volume_ml(application_value)
    label_ml = _parse_volume_ml(label_value)

    if app_ml is not None and label_ml is not None:
        if abs(app_ml - label_ml) < 0.5:  # 0.5 mL tolerance for rounding
            return FieldResult(
                field_name="Net Contents",
                application_value=application_value,
                label_value=label_value,
                status="PASS",
                notes="",
                confidence=confidence,
            )
        return FieldResult(
            field_name="Net Contents",
            application_value=application_value,
            label_value=label_value,
            status="FAIL",
            notes=f"Net contents differ: {app_ml:.0f} mL (application) vs {label_ml:.0f} mL (label).",
            confidence=confidence,
        )

    # Fallback: normalised string comparison
    if _normalise(application_value) == _normalise(label_value):
        return FieldResult(
            field_name="Net Contents",
            application_value=application_value,
            label_value=label_value,
            status="PASS",
            notes="",
            confidence=confidence,
        )

    return FieldResult(
        field_name="Net Contents",
        application_value=application_value,
        label_value=label_value,
        status="FAIL",
        notes=(
            f"Net contents do not match. "
            f"Application: '{application_value}' / Label: '{label_value}'."
        ),
        confidence=confidence,
    )


def check_government_warning(
    application_value: str,
    label_value: str | None,
    confidence: float,
) -> FieldResult:
    """
    Government warning must be verbatim, including all-caps 'GOVERNMENT WARNING:' header.
    Any deviation is a FAIL with the specific issue noted.
    """
    field_name = "Government Warning"

    if label_value is None:
        return FieldResult(
            field_name=field_name,
            application_value=application_value,
            label_value=None,
            status="FAIL",
            notes="Government warning statement not found on the label. This is a mandatory field.",
            confidence=confidence,
        )

    issues: list[str] = []

    # Check 1: all-caps header
    if not _WARNING_HEADER_PATTERN.search(label_value):
        issues.append(
            "'GOVERNMENT WARNING:' header must be in all caps. "
            "Check for title case or lowercase variants."
        )

    # Check 2: full statutory text present (case-insensitive for body,
    # header checked separately above)
    if not _WARNING_PATTERN.search(label_value):
        issues.append(
            "Warning text does not match the required statutory language. "
            "Verify against 27 CFR 16.21."
        )

    if issues:
        return FieldResult(
            field_name=field_name,
            application_value=application_value,
            label_value=label_value,
            status="FAIL",
            notes=" | ".join(issues),
            confidence=confidence,
        )

    return FieldResult(
        field_name=field_name,
        application_value=application_value,
        label_value=label_value,
        status="PASS",
        notes="",
        confidence=confidence,
    )


def check_presence_only(
    field_display_name: str,
    application_value: str,
    label_value: str | None,
    confidence: float,
) -> FieldResult:
    """
    Presence-only check: just verify the field exists on the label.
    Used for bottler name/address and country of origin in prototype scope.
    """
    if label_value and label_value.strip():
        return FieldResult(
            field_name=field_display_name,
            application_value=application_value,
            label_value=label_value,
            status="PASS",
            notes="Field present on label.",
            confidence=confidence,
        )
    return FieldResult(
        field_name=field_display_name,
        application_value=application_value,
        label_value=label_value,
        status="NOT_FOUND",
        notes=f"'{field_display_name}' not visible on the label.",
        confidence=confidence,
    )


# ── Standards-of-identity rules (27 CFR Part 5) ────────────────────────────────

MINIMUM_BOTTLING_PROOF = 80.0  # 40% ABV, per 27 CFR 5.143


def check_minimum_bottling_proof(
    label_value: str | None,
    confidence: float,
) -> FieldResult:
    """27 CFR 5.143 — distilled spirits must be bottled at >= 40% ABV (80 proof)."""
    field_name = "Minimum Bottling Proof"
    requirement = "≥ 40% ABV (80 proof) per 27 CFR 5.143"

    if label_value is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=None,
            status="NOT_FOUND",
            notes="Alcohol content not found on the label; cannot verify minimum bottling proof.",
            confidence=confidence,
        )

    label_abv = _parse_abv(label_value)
    if label_abv is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=label_value,
            status="NOT_FOUND",
            notes="Could not parse a numeric ABV from the label's alcohol content.",
            confidence=confidence,
        )

    if label_abv >= 40.0:
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"Label states {label_abv}% ABV, which is below the 40% ABV (80 proof) "
            "minimum bottling proof required by 27 CFR 5.143."
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_value,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_proof_consistency(
    label_value: str | None,
    confidence: float,
    tolerance: float = 0.5,
) -> FieldResult:
    """If the label shows both a % ABV and a proof figure, proof must equal ABV * 2."""
    field_name = "Proof Consistency"
    requirement = "Proof = ABV × 2"

    if label_value is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=None,
            status="NOT_FOUND",
            notes="Alcohol content not found on the label.",
            confidence=confidence,
        )

    label_abv = _parse_abv(label_value)
    label_proof = _parse_proof(label_value)

    if label_abv is None or label_proof is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=label_value,
            status="NOT_FOUND",
            notes="Label does not show both an ABV percentage and a proof figure.",
            confidence=confidence,
        )

    expected_proof = label_abv * 2
    if abs(expected_proof - label_proof) <= tolerance:
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"Label shows {label_abv}% ABV with {label_proof} proof, but proof should "
            f"equal ABV × 2 = {expected_proof:g}."
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_value,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_bourbon_us_origin(
    class_type_label: str,
    country_label: str | None,
    confidence: float,
) -> FieldResult:
    """27 CFR 5.143(b) — 'Bourbon' may only appear on spirits distilled and aged in the USA."""
    field_name = "Bourbon — US Origin"
    requirement = "Country of origin must be USA (or absent) per 27 CFR 5.143(b)"

    us_terms = ("usa", "united states", "america")
    normalised_country = _normalise(country_label) if country_label else ""

    if not country_label or any(term in normalised_country for term in us_terms):
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"Class/type includes 'Bourbon' but the label states country of origin as "
            f"'{country_label}'. 'Bourbon' may only be used for spirits distilled and "
            "aged in the United States (27 CFR 5.143(b))."
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=country_label,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_kentucky_designation(
    class_type_label: str,
    bottler_address_label: str | None,
    confidence: float,
) -> FieldResult:
    """'Kentucky Straight Bourbon Whiskey' requires distillation/aging in Kentucky."""
    field_name = "Kentucky Designation"
    requirement = "Bottler/producer address must be in Kentucky (27 CFR 5.143(b))"

    if not bottler_address_label or not bottler_address_label.strip():
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=bottler_address_label,
            status="NOT_FOUND",
            notes="Bottler/producer address not found on the label.",
            confidence=confidence,
        )

    normalised_address = _normalise(bottler_address_label)
    if "kentucky" in normalised_address or re.search(r"\bky\b", normalised_address):
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"Class/type uses the 'Kentucky' designation, but the bottler/producer "
            f"address ('{bottler_address_label}') does not indicate Kentucky. "
            "'Kentucky' designations require distillation and aging in Kentucky "
            "(27 CFR 5.143(b))."
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=bottler_address_label,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_age_statement(
    application_age_value: str,
    label_age_value: str | None,
    confidence: float,
) -> FieldResult:
    """27 CFR 5.74 — straight whiskey aged less than 4 years must show an age statement."""
    field_name = "Age Statement"
    requirement = application_age_value

    app_age_years = _parse_age_years(application_age_value)
    if app_age_years is None or app_age_years >= 4:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=label_age_value,
            status="NOT_FOUND",
            notes="Could not determine application age, or age is 4+ years (no statement required).",
            confidence=confidence,
        )

    if label_age_value and label_age_value.strip():
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"COLA application states an age of {app_age_years:g} years (under 4 years), "
            "so an age statement is required on the label per 27 CFR 5.74, but none was found."
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_age_value,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_no_additives_for_straight(
    class_type_label: str,
    additives_label: str | None,
    confidence: float,
) -> FieldResult:
    """27 CFR 5.143, Table 1 row 5 — 'Straight' spirits allow no coloring/flavoring/blending materials."""
    field_name = "Straight — No Additives"
    requirement = "No coloring, flavoring, or blending materials permitted (27 CFR 5.143)"

    if additives_label and additives_label.strip():
        status: FieldStatus = "FAIL"
        notes = (
            f"Class/type includes 'Straight', which permits no coloring, flavoring, or "
            f"blending materials, but the label states: '{additives_label}'."
        )
    else:
        status = "PASS"
        notes = ""

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=additives_label,
        status=status,
        notes=notes,
        confidence=confidence,
    )


# ── Distilled spirits — additional rules (27 CFR Part 5) ───────────────────────

def check_bottled_in_bond(
    label_class_type: str,
    label_alcohol_content: str | None,
    label_age: str | None,
    confidence: float,
) -> FieldResult | None:
    """
    27 CFR 5.87 — "Bottled in Bond"/"Bonded" requires exactly 100 proof (50% ABV)
    and at least 4 years of aging. (Single distillery/season and bonded-warehouse
    storage cannot be verified from a label image alone.)
    """
    field_name = "Bottled in Bond"
    requirement = "Exactly 100 proof (50% ABV) and aged ≥ 4 years (27 CFR 5.87)"

    normalised = _normalise(label_class_type)
    if "bottled in bond" not in normalised and "bonded" not in normalised:
        return None

    issues: list[str] = []

    label_abv = _parse_abv(label_alcohol_content) if label_alcohol_content else None
    if label_abv is None:
        issues.append("Could not find a numeric ABV/proof to confirm the required 100 proof (50% ABV).")
    elif abs(label_abv - 50.0) > 0.1:
        issues.append(f"Label states {label_abv}% ABV, but Bottled in Bond requires exactly 50% ABV (100 proof).")

    label_age_years = _parse_age_years(label_age) if label_age else None
    if label_age_years is None:
        issues.append("No age statement found to confirm the required minimum of 4 years aging.")
    elif label_age_years < 4:
        issues.append(f"Label states an age of {label_age_years:g} years, but Bottled in Bond requires at least 4 years.")

    if issues:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=label_alcohol_content,
            status="FAIL",
            notes=" | ".join(issues),
            confidence=confidence,
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_alcohol_content,
        status="PASS",
        notes=(
            "Proof and age requirements verified. Single distillery/distilling season "
            "and bonded-warehouse storage cannot be confirmed from the label image — "
            "verify against DSP records."
        ),
        confidence=confidence,
    )


_ABV_SPELLED_OUT_PATTERN = re.compile(r"alcohol\s+by\s+volume|alc\.?\s*by\s*vol", re.IGNORECASE)
_ABV_ABBREVIATION_PATTERN = re.compile(r"\bABV\b")


def check_abv_abbreviation(
    label_alcohol_content: str | None,
    confidence: float,
) -> FieldResult:
    """
    The mandatory alcohol content statement must spell out "alcohol by volume" or
    "alc. by vol." — the bare abbreviation "ABV" is not permitted (spirits and wine).
    """
    field_name = "ABV Abbreviation"
    requirement = 'Must say "alcohol by volume" or "alc. by vol.", not "ABV"'

    if label_alcohol_content is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=None,
            status="NOT_FOUND",
            notes="Alcohol content statement not found on the label.",
            confidence=confidence,
        )

    if _ABV_ABBREVIATION_PATTERN.search(label_alcohol_content) and not _ABV_SPELLED_OUT_PATTERN.search(
        label_alcohol_content
    ):
        status: FieldStatus = "FAIL"
        notes = (
            f"Label uses the abbreviation 'ABV' ('{label_alcohol_content}'), which is not permitted "
            'in the mandatory alcohol content statement. Use "alcohol by volume" or "alc. by vol." instead.'
        )
    else:
        status = "PASS"
        notes = ""

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_alcohol_content,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_misleading_age_claim(
    application_age_value: str,
    label_age_value: str | None,
    confidence: float,
) -> FieldResult | None:
    """
    A label cannot claim an age greater than the actual (declared) age of the
    youngest distillate in the bottle.
    """
    field_name = "Age Claim Accuracy"

    app_age_years = _parse_age_years(application_age_value)
    label_age_years = _parse_age_years(label_age_value) if label_age_value else None

    if app_age_years is None or label_age_years is None:
        return None

    requirement = f"Label age claim must not exceed declared age of {app_age_years:g} years"

    if label_age_years > app_age_years + 1e-9:
        status: FieldStatus = "FAIL"
        notes = (
            f"Label claims an age of {label_age_years:g} years, but the COLA application "
            f"declares an actual (youngest distillate) age of only {app_age_years:g} years."
        )
    else:
        status = "PASS"
        notes = ""

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_age_value,
        status=status,
        notes=notes,
        confidence=confidence,
    )


# ── Cross-cutting — sulfite phrasing (wine and beer) ────────────────────────────

_SULFITE_FREE_PATTERN = re.compile(
    r"sulfite[\s-]*free|free\s+of\s+sulfites|contains?\s+no\s+sulfites",
    re.IGNORECASE,
)


def check_sulfite_free_prohibition(
    label_sulfite_statement: str | None,
    confidence: float,
) -> FieldResult | None:
    """
    "Sulfite free", "free of sulfites", and "contains no sulfites" are prohibited
    phrasings regardless of actual sulfite content.
    """
    field_name = "Sulfite-Free Claim"
    requirement = '"Sulfite free" / "contains no sulfites" claims are prohibited'

    if not label_sulfite_statement:
        return None

    if _SULFITE_FREE_PATTERN.search(label_sulfite_statement):
        status: FieldStatus = "FAIL"
        notes = (
            f"Label states '{label_sulfite_statement}'. Phrases like 'sulfite free', "
            "'free of sulfites', and 'contains no sulfites' are prohibited regardless "
            "of actual sulfite content. 'No sulfites detected' or 'less than 10 ppm' "
            "are the permitted alternatives."
        )
    else:
        status = "PASS"
        notes = ""

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_sulfite_statement,
        status=status,
        notes=notes,
        confidence=confidence,
    )


# ── Wine rules (27 CFR Part 4) ──────────────────────────────────────────────────

_SULFITE_DECLARATION_PATTERN = re.compile(r"contains?\s+sulfit", re.IGNORECASE)


def check_wine_sulfite_declaration(
    application_sulfite_ppm: str,
    label_sulfite_statement: str | None,
    confidence: float,
) -> FieldResult:
    """27 CFR 4.32(e) — wines with >= 10 ppm SO2 must declare 'Contains sulfites'."""
    field_name = "Sulfite Declaration"

    ppm = _parse_ppm(application_sulfite_ppm)
    if ppm is None:
        return FieldResult(
            field_name=field_name,
            application_value=application_sulfite_ppm,
            label_value=label_sulfite_statement,
            status="NOT_FOUND",
            notes="Could not parse a numeric sulfite level from the application.",
            confidence=confidence,
        )

    requirement = "Must state 'Contains sulfites' / 'Contains sulfiting agents' (27 CFR 4.32(e))"

    if ppm < 10:
        return FieldResult(
            field_name=field_name,
            application_value=f"{ppm:g} ppm SO2 (below 10 ppm threshold)",
            label_value=label_sulfite_statement,
            status="NOT_FOUND",
            notes="Sulfite level is below the 10 ppm threshold; no declaration is required.",
            confidence=confidence,
        )

    if label_sulfite_statement and _SULFITE_DECLARATION_PATTERN.search(label_sulfite_statement):
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"Application declares {ppm:g} ppm SO2 (>= 10 ppm), so the label must state "
            "'Contains sulfites' or 'Contains sulfiting agents', but no such statement was found."
        )

    return FieldResult(
        field_name=field_name,
        application_value=f"{ppm:g} ppm SO2",
        label_value=label_sulfite_statement,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_wine_abv_threshold(
    application_alcohol_content: str,
    label_alcohol_content: str | None,
    label_class_type: str | None,
    confidence: float,
) -> FieldResult | None:
    """
    27 CFR 4.32(b) / 4.36 — wines over 14% ABV must show a numeric alcohol content
    statement. Wines 7-14% ABV may substitute 'table wine'/'light wine' as the
    class/type. Below 7% ABV, FAA Act labeling rules don't apply.
    """
    field_name = "Wine ABV Statement"

    app_abv = _parse_abv(application_alcohol_content)
    if app_abv is None:
        return None

    if app_abv < 7:
        return FieldResult(
            field_name=field_name,
            application_value=f"{app_abv:g}% ABV",
            label_value=label_alcohol_content,
            status="NOT_FOUND",
            notes="Wine is below 7% ABV; FAA Act alcohol content labeling rules do not apply.",
            confidence=confidence,
        )

    label_abv = _parse_abv(label_alcohol_content) if label_alcohol_content else None
    normalised_class_type = _normalise(label_class_type) if label_class_type else ""
    has_table_or_light_wine = "table wine" in normalised_class_type or "light wine" in normalised_class_type

    if app_abv > 14:
        requirement = "Numeric alcohol content statement required (> 14% ABV) — 27 CFR 4.32(b)"
        if label_abv is not None:
            status: FieldStatus = "PASS"
            notes = ""
        else:
            status = "FAIL"
            notes = (
                f"Application declares {app_abv:g}% ABV (> 14%), so a numeric alcohol content "
                "statement is mandatory on the label, but none was found."
            )
    else:
        requirement = (
            "Numeric alcohol content statement, or 'table wine'/'light wine' "
            "class/type (7-14% ABV) — 27 CFR 4.32(b)/4.36"
        )
        if label_abv is not None or has_table_or_light_wine:
            status = "PASS"
            notes = ""
        else:
            status = "FAIL"
            notes = (
                f"Application declares {app_abv:g}% ABV (7-14%), so the label must show a numeric "
                "alcohol content statement or use 'table wine'/'light wine' as the class/type, "
                "but neither was found."
            )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_alcohol_content,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_table_wine_abv_tolerance(
    application_alcohol_content: str,
    label_class_type: str | None,
    confidence: float,
) -> FieldResult | None:
    """27 CFR 4.36 — if 'table wine'/'light wine' is used as the class/type, actual ABV must be 7-14%."""
    field_name = "Table Wine ABV Tolerance"

    normalised_class_type = _normalise(label_class_type) if label_class_type else ""
    if "table wine" not in normalised_class_type and "light wine" not in normalised_class_type:
        return None

    requirement = "'Table wine'/'light wine' designation requires 7-14% ABV (27 CFR 4.36)"

    app_abv = _parse_abv(application_alcohol_content)
    if app_abv is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=label_class_type,
            status="NOT_FOUND",
            notes="Could not parse a numeric ABV from the application to verify the 7-14% tolerance.",
            confidence=confidence,
        )

    if 7.0 <= app_abv <= 14.0:
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            f"Label class/type uses 'table wine'/'light wine', which requires 7-14% ABV, "
            f"but the application declares {app_abv:g}% ABV."
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_class_type,
        status=status,
        notes=notes,
        confidence=confidence,
    )


GRAPE_VARIETALS = [
    "cabernet sauvignon", "cabernet franc", "merlot", "pinot noir", "pinot grigio",
    "pinot gris", "chardonnay", "sauvignon blanc", "zinfandel", "syrah", "shiraz",
    "malbec", "riesling", "tempranillo", "sangiovese", "grenache", "viognier",
    "chenin blanc", "gewurztraminer", "barbera", "nebbiolo", "petite sirah",
]


def check_wine_appellation(
    label_class_type: str | None,
    label_vintage_year: str | None,
    label_appellation: str | None,
    confidence: float,
) -> FieldResult | None:
    """
    27 CFR 4.23/4.27 — a grape varietal class/type designation, or the presence of a
    vintage date, requires an appellation of origin on the brand label.
    """
    field_name = "Appellation of Origin"

    normalised_class_type = _normalise(label_class_type) if label_class_type else ""
    has_varietal = any(v in normalised_class_type for v in GRAPE_VARIETALS)
    has_vintage = bool(label_vintage_year and label_vintage_year.strip())

    if not has_varietal and not has_vintage:
        return None

    triggers = []
    if has_varietal:
        triggers.append("a grape varietal is used as the class/type")
    if has_vintage:
        triggers.append("a vintage date appears on the label")
    requirement = f"Appellation of origin required because {' and '.join(triggers)} (27 CFR 4.23/4.27)"

    if label_appellation and label_appellation.strip():
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = f"{requirement.capitalize()}, but no appellation of origin was found on the label."

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_appellation,
        status=status,
        notes=notes,
        confidence=confidence,
    )


_VARIETAL_PERCENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def check_wine_varietal_percentages(
    label_class_type: str | None,
    confidence: float,
) -> FieldResult | None:
    """
    27 CFR 4.23 — when two or more grape varieties are listed as the class/type
    (e.g. "Cabernet Sauvignon-Merlot"), each variety's percentage must be shown
    and must sum to 100%.
    """
    field_name = "Varietal Percentages"

    if not label_class_type:
        return None

    normalised_class_type = _normalise(label_class_type)
    matched_varietals = [v for v in GRAPE_VARIETALS if v in normalised_class_type]
    if len(matched_varietals) < 2:
        return None

    requirement = "Multi-varietal class/type must show each variety's percentage, summing to 100% (27 CFR 4.23)"
    percentages = [float(m) for m in _VARIETAL_PERCENT_PATTERN.findall(label_class_type)]

    if len(percentages) < len(matched_varietals):
        status: FieldStatus = "FAIL"
        notes = (
            f"Class/type lists multiple varieties ('{label_class_type}') but does not show "
            "a percentage for each."
        )
    elif abs(sum(percentages) - 100.0) > 0.5:
        status = "FAIL"
        notes = f"Varietal percentages in '{label_class_type}' sum to {sum(percentages):g}%, not 100%."
    else:
        status = "PASS"
        notes = ""

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_class_type,
        status=status,
        notes=notes,
        confidence=confidence,
    )


# Approved standards of fill for wine, in mL (27 CFR 4.72).
WINE_STANDARDS_OF_FILL_ML = {50, 100, 187, 200, 375, 500, 750, 1000, 1500, 3000, 4000, 4500, 6000, 9000, 12000, 15000, 18000}


def check_wine_standard_of_fill(
    label_net_contents: str | None,
    confidence: float,
) -> FieldResult:
    """27 CFR 4.72 — wine must be packaged in TTB-approved standard sizes."""
    field_name = "Standard of Fill"
    requirement = "Net contents must be a TTB-approved standard size (27 CFR 4.72)"

    if label_net_contents is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=None,
            status="NOT_FOUND",
            notes="Net contents not found on the label.",
            confidence=confidence,
        )

    label_ml = _parse_volume_ml(label_net_contents)
    if label_ml is None:
        return FieldResult(
            field_name=field_name,
            application_value=requirement,
            label_value=label_net_contents,
            status="NOT_FOUND",
            notes="Could not parse a volume from the net contents.",
            confidence=confidence,
        )

    if any(abs(label_ml - size) < 0.5 for size in WINE_STANDARDS_OF_FILL_ML):
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = f"{label_ml:g} mL is not a TTB-approved standard of fill for wine."

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_net_contents,
        status=status,
        notes=notes,
        confidence=confidence,
    )


# ── Beer / malt beverage rules (27 CFR Part 7) ──────────────────────────────────

def check_beer_conditional_abv(
    application_added_flavor_alcohol: str,
    label_alcohol_content: str | None,
    confidence: float,
) -> FieldResult | None:
    """
    Unlike spirits/wine, ABV is not mandatory on beer unless the product contains
    alcohol from added flavors or non-beverage ingredients.
    """
    field_name = "Beer ABV Statement"

    if _normalise(application_added_flavor_alcohol) != "yes":
        return None

    requirement = (
        "Numeric alcohol content statement required — product contains alcohol from "
        "added flavors/ingredients (27 CFR 7.71)"
    )

    if label_alcohol_content and _parse_abv(label_alcohol_content) is not None:
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            "Application indicates alcohol is contributed by added flavors/ingredients, "
            "which makes a numeric alcohol content statement mandatory, but none was found on the label."
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_alcohol_content,
        status=status,
        notes=notes,
        confidence=confidence,
    )


def check_color_additive_declaration(
    application_color_additives: str,
    label_color_additive_declaration: str | None,
    confidence: float,
) -> FieldResult | None:
    """27 CFR 7.63(b) — FD&C Yellow No. 5 (tartrazine) and cochineal/carmine must be declared."""
    field_name = "Color Additive Declaration"

    if not application_color_additives.strip():
        return None

    normalised_app = _normalise(application_color_additives)
    declared_terms = []
    if "yellow" in normalised_app or "tartrazine" in normalised_app:
        declared_terms.append("FD&C Yellow No. 5")
    if "cochineal" in normalised_app or "carmine" in normalised_app:
        declared_terms.append("cochineal extract/carmine")

    if not declared_terms:
        return None

    requirement = f"Must declare: {', '.join(declared_terms)} (27 CFR 7.63(b))"
    normalised_label = _normalise(label_color_additive_declaration) if label_color_additive_declaration else ""

    missing = []
    for term in declared_terms:
        key_words = re.findall(r"[a-z0-9]+", term.lower())
        if not any(w in normalised_label for w in key_words if len(w) > 3):
            missing.append(term)

    if missing:
        status: FieldStatus = "FAIL"
        notes = (
            f"Application declares {', '.join(declared_terms)}, but the label does not "
            f"declare: {', '.join(missing)}."
        )
    else:
        status = "PASS"
        notes = ""

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_color_additive_declaration,
        status=status,
        notes=notes,
        confidence=confidence,
    )


_PHENYLKETONURICS_PATTERN = re.compile(
    r"phenylketonurics\s*:?\s*contains\s+phenylalanine", re.IGNORECASE
)


def check_aspartame_declaration(
    application_aspartame_present: str,
    label_aspartame_statement: str | None,
    confidence: float,
) -> FieldResult | None:
    """27 CFR 7.63(b) — products containing aspartame must bear the phenylketonurics warning."""
    field_name = "Aspartame Declaration"

    if _normalise(application_aspartame_present) != "yes":
        return None

    requirement = 'Must state "PHENYLKETONURICS: CONTAINS PHENYLALANINE" (27 CFR 7.63(b))'

    if label_aspartame_statement and _PHENYLKETONURICS_PATTERN.search(label_aspartame_statement):
        status: FieldStatus = "PASS"
        notes = ""
    else:
        status = "FAIL"
        notes = (
            "Application indicates the product contains aspartame, which requires the "
            'statement "PHENYLKETONURICS: CONTAINS PHENYLALANINE", but it was not found on the label.'
        )

    return FieldResult(
        field_name=field_name,
        application_value=requirement,
        label_value=label_aspartame_statement,
        status=status,
        notes=notes,
        confidence=confidence,
    )


# ── Orchestrator ──────────────────────────────────────────────────────────────

def apply_rules(
    extracted: dict[str, dict],
    application: ApplicationData,
    pass_threshold: float = 0.92,
    warning_threshold: float = 0.80,
) -> list[FieldResult]:
    """
    Apply all field rules and return a list of FieldResult objects.

    `extracted` is the parsed Claude response dict keyed by field_name, e.g.:
    {
        "brand_name": {"extracted_value": "OLD TOM DISTILLERY", "confidence": 0.98, "notes": ""},
        ...
    }
    """

    def get(field: str) -> tuple[str | None, float, str]:
        """(extracted_value, confidence, notes)"""
        data = extracted.get(field, {})
        return (
            data.get("extracted_value"),
            float(data.get("confidence", 0.0)),
            data.get("notes", ""),
        )

    results: list[FieldResult] = []
    filled = application.filled_fields()

    # Brand name
    if "brand_name" in filled:
        val, conf, _ = get("brand_name")
        results.append(
            check_brand_name(filled["brand_name"], val, conf, pass_threshold, warning_threshold)
        )

    # Class/type
    if "class_type" in filled:
        val, conf, _ = get("class_type")
        results.append(check_class_type(filled["class_type"], val, conf))

    # Alcohol content
    if "alcohol_content" in filled:
        val, conf, _ = get("alcohol_content")
        results.append(check_alcohol_content(filled["alcohol_content"], val, conf))

    # Net contents
    if "net_contents" in filled:
        val, conf, _ = get("net_contents")
        results.append(check_net_contents(filled["net_contents"], val, conf))

    # Government warning — always checked if field exists in application data,
    # and also checked if the agent left it blank (we still verify presence on label).
    warning_app_val = filled.get("government_warning", GOVERNMENT_WARNING_TEXT)
    val, conf, _ = get("government_warning")
    results.append(check_government_warning(warning_app_val, val, conf))

    # Bottler name/address (presence only)
    if "bottler_name_address" in filled:
        val, conf, _ = get("bottler_name_address")
        results.append(
            check_presence_only("Bottler Name & Address", filled["bottler_name_address"], val, conf)
        )

    # Country of origin (presence only)
    if "country_of_origin" in filled:
        val, conf, _ = get("country_of_origin")
        results.append(
            check_presence_only("Country of Origin", filled["country_of_origin"], val, conf)
        )

    # ── Shared label values ─────────────────────────────────────────────────────
    label_alcohol_content, alcohol_conf, _ = get("alcohol_content")
    label_class_type, class_type_conf, _ = get("class_type")
    label_country, country_conf, _ = get("country_of_origin")
    label_bottler, bottler_conf, _ = get("bottler_name_address")
    label_age, age_conf, _ = get("age_statement")
    label_additives, additives_conf, _ = get("additives_or_flavoring")
    label_appellation, appellation_conf, _ = get("appellation_of_origin")
    label_vintage_year, vintage_conf, _ = get("vintage_year")
    label_sulfite_statement, sulfite_conf, _ = get("sulfite_statement")
    label_color_additives, color_conf, _ = get("color_additive_declaration")
    label_aspartame_statement, aspartame_conf, _ = get("aspartame_statement")
    label_net_contents, net_contents_conf, _ = get("net_contents")

    beverage_type = application.beverage_type or "distilled_spirits"

    # ABV abbreviation prohibition applies to spirits and wine.
    if beverage_type in ("distilled_spirits", "wine"):
        results.append(check_abv_abbreviation(label_alcohol_content, alcohol_conf))

    # Sulfite-free phrasing is prohibited on wine and beer regardless of content.
    if beverage_type in ("wine", "beer"):
        result = check_sulfite_free_prohibition(label_sulfite_statement, sulfite_conf)
        if result:
            results.append(result)

    if beverage_type == "distilled_spirits":
        # ── Standards-of-identity rules (27 CFR Part 5) ─────────────────────────
        results.append(check_minimum_bottling_proof(label_alcohol_content, alcohol_conf))
        results.append(check_proof_consistency(label_alcohol_content, alcohol_conf))

        normalised_label_class_type = _normalise(label_class_type) if label_class_type else ""

        if "bourbon" in normalised_label_class_type:
            results.append(check_bourbon_us_origin(label_class_type, label_country, country_conf))

        if "kentucky" in normalised_label_class_type:
            results.append(check_kentucky_designation(label_class_type, label_bottler, bottler_conf))

        if "age_statement" in filled:
            results.append(check_age_statement(filled["age_statement"], label_age, age_conf))

        if "straight" in normalised_label_class_type:
            results.append(check_no_additives_for_straight(label_class_type, label_additives, additives_conf))

        bottled_in_bond = check_bottled_in_bond(label_class_type or "", label_alcohol_content, label_age, alcohol_conf)
        if bottled_in_bond:
            results.append(bottled_in_bond)

        if "age_statement" in filled:
            misleading_age = check_misleading_age_claim(filled["age_statement"], label_age, age_conf)
            if misleading_age:
                results.append(misleading_age)

    elif beverage_type == "wine":
        # ── Wine rules (27 CFR Part 4) ──────────────────────────────────────────
        if "sulfite_ppm" in filled:
            results.append(check_wine_sulfite_declaration(filled["sulfite_ppm"], label_sulfite_statement, sulfite_conf))

        if "alcohol_content" in filled:
            abv_threshold = check_wine_abv_threshold(
                filled["alcohol_content"], label_alcohol_content, label_class_type, alcohol_conf
            )
            if abv_threshold:
                results.append(abv_threshold)

            table_wine = check_table_wine_abv_tolerance(filled["alcohol_content"], label_class_type, class_type_conf)
            if table_wine:
                results.append(table_wine)

        appellation = check_wine_appellation(label_class_type, label_vintage_year, label_appellation, appellation_conf)
        if appellation:
            results.append(appellation)

        varietal_pct = check_wine_varietal_percentages(label_class_type, class_type_conf)
        if varietal_pct:
            results.append(varietal_pct)

        results.append(check_wine_standard_of_fill(label_net_contents, net_contents_conf))

    elif beverage_type == "beer":
        # ── Beer / malt beverage rules (27 CFR Part 7) ──────────────────────────
        if "added_flavor_alcohol" in filled:
            beer_abv = check_beer_conditional_abv(filled["added_flavor_alcohol"], label_alcohol_content, alcohol_conf)
            if beer_abv:
                results.append(beer_abv)

        if "color_additives" in filled:
            color_result = check_color_additive_declaration(
                filled["color_additives"], label_color_additives, color_conf
            )
            if color_result:
                results.append(color_result)

        if "aspartame_present" in filled:
            aspartame_result = check_aspartame_declaration(
                filled["aspartame_present"], label_aspartame_statement, aspartame_conf
            )
            if aspartame_result:
                results.append(aspartame_result)

    return results
