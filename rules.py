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

    return results
