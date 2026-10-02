"""Conservative source-link formatting before candidate checks; no I/O."""

from __future__ import annotations

import re
import ipaddress
from urllib.parse import urlsplit

from src.two_bot.types import StoryBundle


CYCLONE_LINK_KINDS = frozenset({
    "cyclone_rapid_intensification", "cyclone_tier_crossing",
    "cyclone_landfall", "cyclone_basin_record",
})
_TERMINAL_DISPLAY = re.compile(
    r"(?<!\S)(?P<link>(?:https?://)?[A-Za-z0-9.-]+(?::[0-9]+)?/"
    r"[^\s?#<>\"']+(?:…|\.{3}))\s*$"
)


def _source_url(bundle: StoryBundle) -> str | None:
    facts = bundle.current_facts
    if not isinstance(facts, list):
        return None
    values = [f.get("value") for f in facts
              if isinstance(f, dict) and f.get("label") == "public_advisory_url"]
    if not values:
        return None
    urls: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return None
        urls.add(value.strip())
    if len(urls) != 1:
        return None
    url = urls.pop()
    if (re.search(r"[\s\x00-\x1f\x7f<>\"'\\]", url)
            or re.search(r"%(?![0-9A-Fa-f]{2})", url)):
        return None
    try:
        url.encode("utf-8")  # Escaped lone surrogates are not usable source URLs.
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None):
            return None
        parts.port  # Reject malformed ports without normalizing the source URL.
        if ":" in parts.hostname:
            ipaddress.IPv6Address(parts.hostname)
        elif not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.?",
            parts.hostname.encode("idna").decode("ascii"),
        ):
            return None
    except (ValueError, UnicodeError):
        return None
    return url


def format_source_link(tweet_text: str, bundle: StoryBundle) -> str:
    """Append one exact source URL when it fits, replacing only a certain display.

    No semantic editing, URL decoding, case folding or citation inference. URL
    equality uses complete whitespace-delimited tokens, never substring matching.
    An uncertain abbreviation stays intact. If replacement cannot fit, preserve
    the original text, including its whitespace. The caller checks this final text.
    """
    if bundle.signal_kind not in CYCLONE_LINK_KINDS or not tweet_text.strip():
        return tweet_text
    url = _source_url(bundle)
    if url is None or url in tweet_text.split():
        return tweet_text
    base = tweet_text.rstrip()
    match = _TERMINAL_DISPLAY.search(tweet_text)
    if match is not None:
        source = urlsplit(url)
        display = match["link"]
        display = display[:-1] if display.endswith("…") else display[:-3]
        explicit_scheme = "://" in display
        shown = urlsplit(display if explicit_scheme else "//" + display)
        if (not source.query and not source.fragment
                and (not explicit_scheme or shown.scheme == source.scheme)
                and shown.netloc.removeprefix("www.") == source.netloc.removeprefix("www.")
                and len(shown.path) > 1 and source.path.startswith(shown.path)):
            base = tweet_text[:match.start()].rstrip()
    # Keep both existing gates: raw characters and the conservative t.co allowance.
    final = f"{base}\n{url}" if base else url
    if len(base) + 1 + 23 > 280 or len(final) > 280:
        return tweet_text
    return final
