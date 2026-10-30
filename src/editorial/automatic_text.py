"""The hard automatic TEXT cap: 200 Unicode scalar values, never truncation.

Counting is by Unicode scalar value (code point excluding surrogates), the same
as ``Array.from(text).length`` on a well-formed JavaScript string, so non-BMP
characters count once in both runtimes. A lone surrogate is malformed text and
holds automation. A longer otherwise-valid draft stays available for ordinary
manual review (the existing 280-character manual limit is unchanged); this cap
only withholds automatic arming and automatic sending. It never rewrites,
shortens or drops a qualifier to fit.
"""
from __future__ import annotations

import re
from typing import Any

AUTOMATIC_TEXT_MAX_SCALARS = 200
OVER_CAP = "automatic_text_over_200_scalars"
MALFORMED = "automatic_text_malformed_unicode"
IMPLIES_MEDIA = "automatic_text_implies_media"
HOLD_MESSAGES = {
    OVER_CAP: "Automatic text is limited to 200 characters; this complete draft stays available for manual review.",
    MALFORMED: "Draft text has malformed Unicode and cannot be published automatically.",
    IMPLIES_MEDIA: "Automatic posts are text only; this copy refers to an image, chart, map or table that is not sent.",
}
# Automatic posts never carry an image, so copy may not point at one (paired with automatic-text.js).
_MEDIA_REFERENCE = re.compile(
    r"\b(?:charts?|maps?|graphics?|images?|pictured|photos?|infographics?|tables?|attached|see (?:below|above))\b",
    re.IGNORECASE | re.ASCII)


def scalar_count(text: str) -> int:
    """Unicode scalar values; raises ValueError for a lone surrogate or non-string."""
    if not isinstance(text, str):
        raise ValueError("Draft text must be a string")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
        raise ValueError("Malformed Unicode text")
    return len(text)


def automatic_text_hold(text: Any) -> str | None:
    """None when the exact text may be published automatically by length; else a hold code."""
    try:
        count = scalar_count(text)
    except ValueError:
        return MALFORMED
    if count > AUTOMATIC_TEXT_MAX_SCALARS:
        return OVER_CAP
    return IMPLIES_MEDIA if _MEDIA_REFERENCE.search(text) else None


__all__ = ["AUTOMATIC_TEXT_MAX_SCALARS", "HOLD_MESSAGES", "IMPLIES_MEDIA", "MALFORMED", "OVER_CAP", "automatic_text_hold",
           "scalar_count"]
