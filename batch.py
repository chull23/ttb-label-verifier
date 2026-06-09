"""
batch.py
--------
Async batch orchestration for processing multiple label images concurrently.

Uses asyncio + the Anthropic async client with a semaphore to cap concurrency
and respect API rate limits.

The public entry point is process_batch(), which is called from app.py via
asyncio.run() or an existing event loop.
"""

from __future__ import annotations

import asyncio
import base64
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
    LabelVerificationError,
    LowConfidenceError,
    MalformedResponseError,
    PartialBatchError,
    UnsupportedImageTypeError,
)
from models import ApplicationData, LabelResult
from prompt import SYSTEM_PROMPT, build_user_message, media_type_for_filename
from rules import apply_rules
from verifier import (
    MANDATORY_FIELDS,
    _ACCEPTED_PILLOW_FORMATS,
    validate_image,
    _parse_response,
    _check_confidence,
)


# ── Async Claude call ─────────────────────────────────────────────────────────

async def _call_claude_async(
    client: anthropic.AsyncAnthropic,
    image_bytes: bytes,
    media_type: str,
) -> str:
    """Async version of the Claude API call."""
    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
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


# ── Single label (async) ──────────────────────────────────────────────────────

async def _verify_one(
    client: anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    filename: str,
    image_bytes: bytes,
    application: ApplicationData,
) -> LabelResult:
    """
    Verify a single label inside a semaphore-bounded context.
    Returns a LabelResult — either a real result or an error_result.
    """
    start = time.monotonic()

    async with semaphore:
        try:
            media_type = validate_image(image_bytes, filename)
            raw = await _call_claude_async(client, image_bytes, media_type)
            extracted = _parse_response(raw)
            _check_confidence(extracted)
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

        except LabelVerificationError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return LabelResult.error_result(
                error_message=exc.user_message,
                filename=filename,
                processing_time_ms=elapsed_ms,
            )


# ── Public batch entry point ──────────────────────────────────────────────────

async def process_batch(
    images: list[tuple[str, bytes]],
    application: ApplicationData,
    max_concurrent: int | None = None,
    progress_callback=None,
) -> list[LabelResult]:
    """
    Process a list of (filename, image_bytes) tuples concurrently.

    Args:
        images:            List of (filename, image_bytes) pairs.
        application:       COLA application data to verify against.
        max_concurrent:    Concurrency cap. Defaults to settings.max_concurrent.
        progress_callback: Optional async callable(completed: int, total: int, result: LabelResult).
                           Called after each label finishes.

    Returns:
        List of LabelResult in the same order as the input images.

    Raises:
        PartialBatchError if any label failed (results are still returned).
    """
    if not settings.anthropic_api_key:
        raise APIAuthError("ANTHROPIC_API_KEY is not set.")

    cap = max_concurrent or settings.max_concurrent
    semaphore = asyncio.Semaphore(cap)

    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=httpx.Timeout(settings.api_timeout_seconds),
    )

    total = len(images)
    results: list[LabelResult | None] = [None] * total

    async def run_one(index: int, filename: str, image_bytes: bytes) -> None:
        result = await _verify_one(client, semaphore, filename, image_bytes, application)
        results[index] = result
        if progress_callback:
            completed = sum(1 for r in results if r is not None)
            await progress_callback(completed, total, result)

    await asyncio.gather(
        *[run_one(i, name, img) for i, (name, img) in enumerate(images)]
    )

    final: list[LabelResult] = [r for r in results if r is not None]

    failed = sum(1 for r in final if r.error)
    if failed:
        raise PartialBatchError(failed_count=failed, total_count=total)

    return final
