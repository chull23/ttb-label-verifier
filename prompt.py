"""
prompt.py
---------
Claude prompt templates for label field extraction.

Design principle: Claude is an extractor, not a decision-maker.
It returns structured JSON with verbatim field values and confidence scores.
All pass/fail logic lives in rules.py.
"""

from __future__ import annotations

import base64

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a data extraction assistant for the TTB (Alcohol and Tobacco Tax and Trade Bureau) label compliance review process.

Your ONLY job is to extract field values verbatim from the alcohol beverage label image provided. You do NOT make compliance decisions. You do NOT correct spelling or formatting. You do NOT infer values that are not clearly visible.

Extract these fields exactly as they appear on the label:
- brand_name
- class_type (e.g. "Kentucky Straight Bourbon Whiskey")
- alcohol_content (full string as printed, e.g. "45% Alc./Vol. (90 Proof)")
- net_contents (e.g. "750 mL")
- government_warning (the full government health warning statement, verbatim including capitalisation)
- bottler_name_address (name and address of bottler/producer/importer)
- country_of_origin (if present)

Respond with ONLY valid JSON matching this exact schema — no markdown fences, no commentary:

{
  "fields": [
    {
      "field_name": "<one of the field names above>",
      "extracted_value": "<verbatim text from label, or null if not visible>",
      "confidence": <float 0.0 to 1.0>,
      "notes": "<brief note if something unusual — e.g. 'text partially obscured by glare', otherwise empty string>"
    }
  ]
}

Rules:
1. Extract EXACTLY what is printed. Do not normalise capitalisation, punctuation, or spacing.
2. If a field is not visible or not present, set extracted_value to null and confidence to 0.0.
3. confidence reflects how clearly you can read the text: 1.0 = perfectly clear, 0.5 = partially obscured, 0.0 = cannot read.
4. Include all seven fields in your response, even if null.
"""


# ── Message builder ────────────────────────────────────────────────────────────

def build_user_message(image_bytes: bytes, media_type: str = "image/jpeg") -> list[dict]:
    """
    Build the user message for the Claude API call.

    Returns a list of content blocks (image + text instruction) suitable
    for passing directly to client.messages.create(messages=[...]).
    """
    encoded = base64.standard_b64encode(image_bytes).decode("utf-8")

    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded,
            },
        },
        {
            "type": "text",
            "text": (
                "Please extract all label fields from this alcohol beverage label image. "
                "Return only the JSON as specified in your instructions."
            ),
        },
    ]


# ── Media type helper ─────────────────────────────────────────────────────────

EXTENSION_TO_MEDIA_TYPE: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

ACCEPTED_EXTENSIONS = set(EXTENSION_TO_MEDIA_TYPE.keys())


def media_type_for_filename(filename: str) -> str:
    """Return the MIME type for a given filename, defaulting to image/jpeg."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return EXTENSION_TO_MEDIA_TYPE.get(ext, "image/jpeg")
