"""
models.py
---------
Dataclasses used throughout the TTB label verification tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ── Status literals ───────────────────────────────────────────────────────────

FieldStatus = Literal["PASS", "FAIL", "WARNING", "NOT_FOUND", "NEEDS_REVIEW"]
OverallStatus = Literal["PASS", "FAIL", "WARNING", "NEEDS_REVIEW"]


# ── Core result types ─────────────────────────────────────────────────────────

@dataclass
class FieldResult:
    """Verification result for a single label field."""

    field_name: str
    """Human-readable field name, e.g. 'Brand Name'."""

    application_value: str
    """The value the applicant declared on the COLA form."""

    label_value: str | None
    """The value extracted from the label image by Claude. None if not found."""

    status: FieldStatus
    """
    PASS        — values match within tolerance
    FAIL        — values clearly do not match
    WARNING     — values are close but differ enough to flag for review
    NOT_FOUND   — the field was not visible on the label
    NEEDS_REVIEW — image quality too low to make a determination
    """

    notes: str = ""
    """Explanation shown to the agent, e.g. 'ABV differs by 0.5%'."""

    confidence: float = 1.0
    """Claude's extraction confidence (0.0–1.0). Informational; used by rules.py."""


@dataclass
class LabelResult:
    """Aggregated result for a single label image."""

    overall: OverallStatus
    """
    Derived from the worst field status:
      any FAIL       -> FAIL
      any WARNING    -> WARNING
      any NEEDS_REVIEW (and no FAIL) -> NEEDS_REVIEW
      all PASS       -> PASS
    """

    fields: list[FieldResult]
    """Per-field results in display order."""

    processing_time_ms: int
    """Wall-clock time from upload to result, in milliseconds."""

    filename: str = ""
    """Original filename; populated in batch mode."""

    error: str = ""
    """If a LabelVerificationError was caught, its user_message goes here."""

    @classmethod
    def from_fields(
        cls,
        fields: list[FieldResult],
        processing_time_ms: int,
        filename: str = "",
    ) -> "LabelResult":
        """Derive the overall status from the field results."""
        statuses = {f.status for f in fields}
        if "FAIL" in statuses:
            overall: OverallStatus = "FAIL"
        elif "WARNING" in statuses:
            overall = "WARNING"
        elif "NEEDS_REVIEW" in statuses or "NOT_FOUND" in statuses:
            overall = "NEEDS_REVIEW"
        else:
            overall = "PASS"
        return cls(
            overall=overall,
            fields=fields,
            processing_time_ms=processing_time_ms,
            filename=filename,
        )

    @classmethod
    def error_result(
        cls,
        error_message: str,
        filename: str = "",
        processing_time_ms: int = 0,
    ) -> "LabelResult":
        """Create a placeholder result for a label that could not be processed."""
        return cls(
            overall="FAIL",
            fields=[],
            processing_time_ms=processing_time_ms,
            filename=filename,
            error=error_message,
        )


# ── Application data (COLA form) ──────────────────────────────────────────────

@dataclass
class ApplicationData:
    """
    Fields from the COLA (Certificate of Label Approval) application form.
    All fields are optional strings because agents may not fill every field
    for every verification run.
    """

    brand_name: str = ""
    class_type: str = ""
    alcohol_content: str = ""
    net_contents: str = ""
    government_warning: str = ""
    bottler_name_address: str = ""
    country_of_origin: str = ""
    age_statement: str = ""

    def filled_fields(self) -> dict[str, str]:
        """Return only fields that the agent actually provided."""
        return {
            k: v
            for k, v in {
                "brand_name": self.brand_name,
                "class_type": self.class_type,
                "alcohol_content": self.alcohol_content,
                "net_contents": self.net_contents,
                "government_warning": self.government_warning,
                "bottler_name_address": self.bottler_name_address,
                "country_of_origin": self.country_of_origin,
                "age_statement": self.age_statement,
            }.items()
            if v.strip()
        }

    def has_any_data(self) -> bool:
        return bool(self.filled_fields())
