"""
tests/test_rules.py
-------------------
Unit tests for rules.py — no API calls required.
"""

import sys
import os

# Allow imports from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from rules import (
    check_brand_name,
    check_class_type,
    check_alcohol_content,
    check_net_contents,
    check_government_warning,
    GOVERNMENT_WARNING_TEXT,
)


# ── Brand name ────────────────────────────────────────────────────────────────

class TestBrandName:
    def test_exact_match(self):
        r = check_brand_name("OLD TOM DISTILLERY", "OLD TOM DISTILLERY", 1.0)
        assert r.status == "PASS"

    def test_case_difference_passes(self):
        # Dave Morrison case: STONE'S THROW vs Stone's Throw
        r = check_brand_name("STONE'S THROW", "Stone's Throw", 1.0)
        assert r.status in ("PASS", "WARNING")  # Should not be FAIL

    def test_clear_mismatch_fails(self):
        r = check_brand_name("OLD TOM DISTILLERY", "RIVER BEND SPIRITS", 1.0)
        assert r.status == "FAIL"

    def test_not_found(self):
        r = check_brand_name("OLD TOM DISTILLERY", None, 0.0)
        assert r.status == "NOT_FOUND"

    def test_close_match_is_warning(self):
        r = check_brand_name("Old Tom Distillery", "Old Tom Distilleries", 1.0)
        assert r.status == "WARNING"


# ── ABV ───────────────────────────────────────────────────────────────────────

class TestAlcoholContent:
    def test_exact_match(self):
        r = check_alcohol_content("45% Alc./Vol. (90 Proof)", "45% Alc./Vol. (90 Proof)", 1.0)
        assert r.status == "PASS"

    def test_numeric_match_different_format(self):
        r = check_alcohol_content("45%", "45% Alc./Vol.", 1.0)
        assert r.status == "PASS"

    def test_abv_mismatch_fails(self):
        r = check_alcohol_content("45%", "40%", 1.0)
        assert r.status == "FAIL"

    def test_within_tolerance_passes(self):
        # 0.05% difference is within 0.1% tolerance
        r = check_alcohol_content("45.0%", "45.05%", 1.0)
        assert r.status == "PASS"

    def test_not_found(self):
        r = check_alcohol_content("45%", None, 0.0)
        assert r.status == "NOT_FOUND"


# ── Net contents ──────────────────────────────────────────────────────────────

class TestNetContents:
    def test_exact_match(self):
        r = check_net_contents("750 mL", "750 mL", 1.0)
        assert r.status == "PASS"

    def test_case_insensitive_ml(self):
        r = check_net_contents("750 mL", "750 ML", 1.0)
        assert r.status == "PASS"

    def test_litre_conversion(self):
        r = check_net_contents("1000 mL", "1 L", 1.0)
        assert r.status == "PASS"

    def test_volume_mismatch_fails(self):
        r = check_net_contents("750 mL", "1000 mL", 1.0)
        assert r.status == "FAIL"

    def test_not_found(self):
        r = check_net_contents("750 mL", None, 0.0)
        assert r.status == "NOT_FOUND"


# ── Government warning ────────────────────────────────────────────────────────

class TestGovernmentWarning:
    def test_correct_warning_passes(self):
        r = check_government_warning(GOVERNMENT_WARNING_TEXT, GOVERNMENT_WARNING_TEXT, 1.0)
        assert r.status == "PASS"

    def test_lowercase_header_fails(self):
        bad = GOVERNMENT_WARNING_TEXT.replace("GOVERNMENT WARNING:", "Government Warning:")
        r = check_government_warning(GOVERNMENT_WARNING_TEXT, bad, 1.0)
        assert r.status == "FAIL"
        assert "all caps" in r.notes.lower()

    def test_title_case_header_fails(self):
        # Jenny Park's reported case
        bad = GOVERNMENT_WARNING_TEXT.replace("GOVERNMENT WARNING:", "Government Warning:")
        r = check_government_warning(GOVERNMENT_WARNING_TEXT, bad, 1.0)
        assert r.status == "FAIL"

    def test_missing_warning_fails(self):
        r = check_government_warning(GOVERNMENT_WARNING_TEXT, None, 0.0)
        assert r.status == "FAIL"

    def test_altered_text_fails(self):
        bad = GOVERNMENT_WARNING_TEXT.replace("birth defects", "health issues")
        r = check_government_warning(GOVERNMENT_WARNING_TEXT, bad, 1.0)
        assert r.status == "FAIL"

    def test_extra_whitespace_passes(self):
        # Minor whitespace variations should still pass
        padded = GOVERNMENT_WARNING_TEXT.replace("  ", "   ")
        r = check_government_warning(GOVERNMENT_WARNING_TEXT, padded, 1.0)
        assert r.status == "PASS"


# ── Class/type ────────────────────────────────────────────────────────────────

class TestClassType:
    def test_exact_match(self):
        r = check_class_type("Kentucky Straight Bourbon Whiskey", "Kentucky Straight Bourbon Whiskey", 1.0)
        assert r.status == "PASS"

    def test_case_insensitive(self):
        r = check_class_type("Kentucky Straight Bourbon Whiskey", "kentucky straight bourbon whiskey", 1.0)
        assert r.status == "PASS"

    def test_mismatch_fails(self):
        r = check_class_type("Kentucky Straight Bourbon Whiskey", "Tennessee Whiskey", 1.0)
        assert r.status == "FAIL"

    def test_not_found(self):
        r = check_class_type("Kentucky Straight Bourbon Whiskey", None, 0.0)
        assert r.status == "NOT_FOUND"
