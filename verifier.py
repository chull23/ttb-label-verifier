"""
verifier.py
-----------
Core label verification service.

Responsibilities:
  - Validate the uploaded image (size, type, decodability)
  - Call the Anthropic Claude Vision API
  - Parse the JSON response into extracted field data
  - Run confidence checks (raises LowConfidenceError if image is unreadable)
  - Apply deterministic post-processing rules (rules.py)
  - Return a LabelResult

All errors are raised as typed LabelVerificationError subclasses.
"""

from __future__ import annotations

import json
import re
import time
from io import BytesIO

import anthropic
import httpx
from PIL import Image, UnidentifiedImageError

from config import settings
from exceptions import (
    APIAuthError,
    APIRateLimitError,
    APIResponseError,
    APITimeoutError,
    ImageTooLargeError,
    ImageUnreadableError,
    LowConfidenceError,
    MalformedResponseError,
    UnsupportedImageTypeError,
)
from models import ApplicationData, LabelResult
from prompt import SYSTEM_PROMPT, build_user_message, media_type_for_filename
from rules import apply_rules

# Fields that are mandatory for reliable compliance review.
# Low confidence on any of these triggers LowConfidenceError.
MANDATORY_FIELDS = {"brand_name", "alcohol_content", "government_warning"}

# Mapping from Pillow format string to accepted extension
_PILLOW_FORMAT_TO_EXT: dict[str, str] = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
}

_ACCEPTED_PILLOW_FORMATS = set(_PILLOW_FORMAT_TO_EXT.keys())


# ── Image validation ──────────────────────────────────────────────────────────

def validate_image(image_bytes: bytes, filename: str = "") -> str:
    """
    Validate image bytes and return the detected media type string.

    Raises:
        ImageTooLargeError
        UnsupportedImageTypeError
        ImageUnreadableError
    """
    max_bytes = int(settings.max_image_size_mb * 1_048_576)
    if len(image_bytes) > max_bytes:
        raise ImageTooLargeError(len(image_bytes), max_bytes)

    try:
        img = Image.open(BytesIO(image_bytes))
        fmt = img.format or ""
    except UnidentifiedImageError as exc:
        raise ImageUnreadableError(str(exc)) from exc
    except Exception as exc:
        raise ImageUnreadableError(str(exc)) from exc

    if fmt not in _ACCEPTED_PILLOW_FORMATS:
        raise UnsupportedImageTypeError(fmt or "unknown")

    return media_type_for_filename(filename) if filename else f"image/{fmt.lower()}"


# ── Claude API call ───────────────────────────────────────────────────────────

def _call_claude(image_bytes: bytes, media_type: str) -> str:
    """
    Send the image to Claude and return the raw text response.

    Raises:
        APIAuthError
        APIRateLimitError
        APITimeoutError
        APIResponseError
    """
    if not settings.anthropic_api_key:
        raise APIAuthError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=httpx.Timeout(settings.api_timeout_seconds),
    )

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_user_message(image_bytes, media_type),
                }
            ],
        )
    except anthropic.AuthenticationError as exc:
        raise APIAuthError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        raise APIRateLimitError() from exc
    except httpx.TimeoutException as exc:
        raise APITimeoutError(settings.api_timeout_seconds) from exc
    except anthropic.APIStatusError as exc:
        raise APIResponseError(exc.status_code, str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        raise APIResponseError(0, f"Connection error: {exc}") from exc

    return response.content[0].text


# ── Response parsing ──────────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict[str, dict]:
    """
    Parse Claude's JSON response into a dict keyed by field_name.

    Returns: { "brand_name": {"extracted_value": ..., "confidence": ..., "notes": ...}, ... }

    Raises:
        MalformedResponseError
    """
    # Strip markdown code fences if Claude included them despite instructions
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned, flags=re.MULTILINE)
        cleaned = cleaned.rstrip("`").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Claude sometimes prefaces the JSON with explanatory text. Try to
        # extract the first top-level {...} block and parse that instead.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise MalformedResponseError(raw)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise MalformedResponseError(raw) from exc

    if "fields" not in data or not isinstance(data["fields"], list):
        raise MalformedResponseError(raw)

    result: dict[str, dict] = {}
    for item in data["fields"]:
        if isinstance(item, dict) and "field_name" in item:
            result[item["field_name"]] = item

    return result


# ── Confidence check ──────────────────────────────────────────────────────────

def _check_confidence(extracted: dict[str, dict]) -> None:
    """
    Raise LowConfidenceError if any mandatory field has low confidence.

    Raises:
        LowConfidenceError
    """
    threshold = settings.confidence_threshold
    low_fields = [
        field
        for field in MANDATORY_FIELDS
        if float(extracted.get(field, {}).get("confidence", 0.0)) < threshold
        and extracted.get(field, {}).get("extracted_value") is not None
    ]
    if low_fields:
        display = [f.replace("_", " ").title() for f in low_fields]
        raise LowConfidenceError(display)


# ── Public API ────────────────────────────────────────────────────────────────

def verify_label(
    image_bytes: bytes,
    application: ApplicationData,
    filename: str = "",
) -> LabelResult:
    """
    Verify a single label image against the COLA application data.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        application:  ApplicationData from the sidebar form.
        filename:     Original filename (used for media type detection).

    Returns:
        LabelResult with per-field results and overall status.

    Raises:
        LabelVerificationError (or any subclass) on failure.
    """
    start = time.monotonic()

    # 1. Validate image
    media_type = validate_image(image_bytes, filename)

    # 2. Call Claude
    raw = _call_claude(image_bytes, media_type)

    # 3. Parse response
    extracted = _parse_response(raw)

    # 4. Confidence check
    _check_confidence(extracted)

    # 5. Apply rules
    field_results = apply_rules(
        extracted,
        application,
        pass_threshold=settings.brand_name_pass_threshold,
        warning_threshold=settings.brand_name_warning_threshold,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return LabelResult.from_fields(
        fields=field_results,
        processing_time_ms=elapsed_ms,
        filename=filename,
    )
