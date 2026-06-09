"""
exceptions.py
-------------
Full exception hierarchy for the TTB label verification tool.

All exceptions inherit from LabelVerificationError so the UI can catch
a single base class while still logging the specific cause.
"""


class LabelVerificationError(Exception):
    """Base class for all label verification errors."""

    def __init__(self, message: str, *, user_message: str | None = None):
        super().__init__(message)
        # user_message is the friendly string shown in the Streamlit UI.
        # Falls back to the technical message if not provided.
        self.user_message = user_message or message


# ── Image errors ──────────────────────────────────────────────────────────────

class ImageError(LabelVerificationError):
    """Base class for errors related to the uploaded image."""


class ImageTooLargeError(ImageError):
    """Image exceeds the maximum allowed file size."""

    def __init__(self, size_bytes: int, max_bytes: int):
        mb = size_bytes / 1_048_576
        max_mb = max_bytes / 1_048_576
        super().__init__(
            f"Image size {mb:.1f} MB exceeds limit of {max_mb:.0f} MB.",
            user_message=(
                f"Image is too large ({mb:.1f} MB). "
                f"Please upload a file under {max_mb:.0f} MB, or compress the photo."
            ),
        )
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes


class UnsupportedImageTypeError(ImageError):
    """Image format is not accepted."""

    ACCEPTED = ("JPG", "PNG", "WEBP")

    def __init__(self, detected_type: str):
        super().__init__(
            f"Unsupported image type: {detected_type!r}.",
            user_message=(
                f"Unsupported format ({detected_type}). "
                f"Accepted types: {', '.join(self.ACCEPTED)}."
            ),
        )
        self.detected_type = detected_type


class ImageUnreadableError(ImageError):
    """Image bytes cannot be decoded (corrupt file)."""

    def __init__(self, detail: str = ""):
        super().__init__(
            f"Could not decode image: {detail}".rstrip(": "),
            user_message=(
                "Could not read the image — the file may be corrupt. "
                "Please re-upload or try a different file."
            ),
        )


# ── API errors ────────────────────────────────────────────────────────────────

class APIError(LabelVerificationError):
    """Base class for errors communicating with the Anthropic API."""


class APITimeoutError(APIError):
    """Request to the Claude API timed out."""

    def __init__(self, timeout_seconds: float):
        super().__init__(
            f"Claude API request timed out after {timeout_seconds:.0f}s.",
            user_message=(
                "The request timed out. The service may be busy — "
                "please try again in a moment."
            ),
        )
        self.timeout_seconds = timeout_seconds


class APIRateLimitError(APIError):
    """Too many requests; API returned HTTP 429."""

    def __init__(self):
        super().__init__(
            "Anthropic API rate limit exceeded (HTTP 429).",
            user_message=(
                "Too many requests. Please wait a moment and try again."
            ),
        )


class APIAuthError(APIError):
    """API key is missing or invalid."""

    def __init__(self, detail: str = ""):
        super().__init__(
            f"API authentication failed: {detail}".rstrip(": "),
            user_message=(
                "API key not configured or invalid. "
                "Ask your administrator to set ANTHROPIC_API_KEY in the .env file."
            ),
        )


class APIResponseError(APIError):
    """API returned an unexpected HTTP status."""

    def __init__(self, status_code: int, body: str = ""):
        super().__init__(
            f"Unexpected API response: HTTP {status_code}. {body}".rstrip(),
            user_message=(
                f"The AI service returned an unexpected error (HTTP {status_code}). "
                "Please try again or contact support."
            ),
        )
        self.status_code = status_code


# ── Extraction errors ─────────────────────────────────────────────────────────

class ExtractionError(LabelVerificationError):
    """Base class for errors that occur while extracting fields from the label."""


class MalformedResponseError(ExtractionError):
    """Claude returned a response that could not be parsed as valid JSON."""

    def __init__(self, raw: str = ""):
        super().__init__(
            f"Claude response could not be parsed as JSON. Raw: {raw[:200]}",
            user_message=(
                "Unexpected response from the AI service. "
                "The label has been flagged for manual review."
            ),
        )
        self.raw = raw


class LowConfidenceError(ExtractionError):
    """
    One or more mandatory fields had confidence below the threshold.

    This means the image quality is insufficient for reliable extraction
    (glare, blur, angle) — NOT a compliance failure.
    """

    def __init__(self, low_confidence_fields: list[str]):
        fields_str = ", ".join(low_confidence_fields)
        super().__init__(
            f"Low confidence on fields: {fields_str}.",
            user_message=(
                "The image quality is too low to read confidently "
                f"({fields_str}). "
                "Please upload a clearer photo — better lighting and a straight-on angle work best."
            ),
        )
        self.low_confidence_fields = low_confidence_fields


# ── Batch errors ──────────────────────────────────────────────────────────────

class BatchError(LabelVerificationError):
    """Base class for errors that occur during batch processing."""


class PartialBatchError(BatchError):
    """
    Some labels in a batch failed; others succeeded.

    The UI should display this as a warning banner, show failed rows in the
    results table, and still allow the agent to download the successful results.
    """

    def __init__(self, failed_count: int, total_count: int):
        super().__init__(
            f"{failed_count} of {total_count} labels failed during batch processing.",
            user_message=(
                f"{failed_count} of {total_count} labels could not be processed. "
                "Successful results are shown below. "
                "Failed labels are highlighted in red — hover for the error detail."
            ),
        )
        self.failed_count = failed_count
        self.total_count = total_count
