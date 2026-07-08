"""
config.py
---------
Application settings loaded from environment variables / .env file.
All values have sensible defaults so the app runs with minimal configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get_setting(key: str, default: str = "") -> str:
    """
    Look up a setting from the environment first, then from Streamlit's
    secrets store (st.secrets), falling back to `default`.

    Streamlit Community Cloud injects values configured in the app's
    "Secrets" panel via st.secrets, not as OS environment variables.
    """
    value = os.getenv(key)
    if value is not None:
        return value

    try:
        import streamlit as st

        return str(st.secrets[key])
    except Exception:
        return default


@dataclass(frozen=True)
class Settings:
    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str
    """Required. Set ANTHROPIC_API_KEY in your .env file."""

    claude_model: str
    """Claude model to use for vision extraction."""

    api_timeout_seconds: float
    """Hard timeout for each Claude API call."""

    # ── Batch processing ──────────────────────────────────────────────────────
    max_concurrent: int
    """Maximum number of labels processed simultaneously in batch mode."""

    max_image_size_mb: float
    """Maximum uploaded image size in megabytes."""

    # ── Matching thresholds ───────────────────────────────────────────────────
    brand_name_pass_threshold: float
    """difflib ratio >= this value is a PASS (0.0–1.0)."""

    brand_name_warning_threshold: float
    """difflib ratio >= this value (but < pass threshold) is a WARNING."""

    confidence_threshold: float
    """
    Claude extraction confidence below this value on a mandatory field
    raises LowConfidenceError instead of returning a FAIL.
    """

    # ── UI ────────────────────────────────────────────────────────────────────
    app_title: str
    page_icon: str


def load_settings() -> Settings:
    """Load and validate settings from environment variables or Streamlit secrets."""
    api_key = _get_setting("ANTHROPIC_API_KEY", "")
    # We don't raise here; the UI will catch APIAuthError at call time.

    return Settings(
        anthropic_api_key=api_key,
        claude_model=_get_setting("CLAUDE_MODEL", "claude-opus-4-8"),
        api_timeout_seconds=float(_get_setting("API_TIMEOUT_SECONDS", "20")),
        max_concurrent=int(_get_setting("MAX_CONCURRENT", "5")),
        max_image_size_mb=float(_get_setting("MAX_IMAGE_SIZE_MB", "20")),
        brand_name_pass_threshold=float(_get_setting("BRAND_NAME_PASS_THRESHOLD", "0.92")),
        brand_name_warning_threshold=float(_get_setting("BRAND_NAME_WARNING_THRESHOLD", "0.80")),
        confidence_threshold=float(_get_setting("CONFIDENCE_THRESHOLD", "0.70")),
        app_title=_get_setting("APP_TITLE", "TTB Label Verifier"),
        page_icon=_get_setting("PAGE_ICON", "🏷️"),
    )


# Module-level singleton so all imports share the same object.
settings = load_settings()
