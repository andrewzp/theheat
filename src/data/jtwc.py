"""Joint Typhoon Warning Center tropical-cyclone advisories."""

from __future__ import annotations

from html import unescape
import re
import xml.etree.ElementTree as ET

import requests

from src.data._http import fetch_with_retry
from src.data.cyclones import (
    BasinRecordEvent,
    CycloneAdvisory,
    LandfallEvent,
    RapidIntensificationEvent,
    TierCrossingEvent,
    detect_basin_records,
    detect_landfalls,
    detect_rapid_intensification,
    detect_tier_crossings,
    parse_coordinate,
    parse_int,
)
from src.data.source_status import SourceFetchError

JTWC_RSS_URL = "https://www.metoc.navy.mil/jtwc/rss/jtwc.rss?layout=enhanced"


def fetch_active_cyclones(*, strict: bool = False) -> list[CycloneAdvisory]:
    """Fetch active JTWC tropical warnings from the public RSS feed."""

    try:
        response = fetch_with_retry(
            JTWC_RSS_URL,
            headers={
                "User-Agent": "(theheat-bot, contact@theheat.app)",
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
            timeout=30,
        )
        return parse_rss(response.text)
    except (requests.RequestException, ET.ParseError, ValueError, TypeError) as exc:
        if strict:
            raise SourceFetchError(f"JTWC fetch failed: {exc}") from exc
        return []


def parse_rss(xml_text: str) -> list[CycloneAdvisory]:
    root = ET.fromstring(xml_text)
    advisories: list[CycloneAdvisory] = []
    for item in root.findall(".//item"):
        title = _text(item, "title")
        description = _text(item, "description")
        link = _text(item, "link")
        pub_date = _text(item, "pubDate")
        if _is_no_active_item(title, description):
            continue
        product_links = _extract_links(description)
        warning_links = [
            product_link for product_link in product_links
            if _is_warning_product_link(product_link)
        ]
        if not warning_links and _looks_like_warning(title, description):
            warning_links = [link] if link.lower().endswith(".txt") else []

        if not warning_links:
            parsed = parse_warning_text(
                "\n".join(part for part in [title, description] if part),
                fallback_url=link,
                fallback_issued_at=pub_date,
            )
            if parsed is not None:
                advisories.append(parsed)
            continue

        for warning_url in warning_links:
            text = _fetch_product_text(warning_url)
            parsed = parse_warning_text(
                text or "\n".join(part for part in [title, description] if part),
                fallback_url=warning_url,
                fallback_issued_at=pub_date,
            )
            if parsed is not None:
                advisories.append(parsed)
    return advisories


def parse_warning_text(
    text: str,
    *,
    fallback_url: str = "",
    fallback_issued_at: str = "",
) -> CycloneAdvisory | None:
    clean = unescape(_strip_tags(text or ""))
    if not clean.strip():
        return None
    header = re.search(
        r"(?:TROPICAL\s+)?(?:CYCLONE|DEPRESSION|STORM|TYPHOON|SUPER TYPHOON)\s+"
        r"([A-Z0-9]{2,4})\s*\(([^)]+)\)",
        clean,
        re.IGNORECASE,
    )
    storm_id = header.group(1).upper() if header else ""
    storm_name = header.group(2).title() if header else ""
    warning_match = re.search(r"WARNING\s+NR\s+(\d+)", clean, re.IGNORECASE)
    advisory_number = warning_match.group(1) if warning_match else ""
    wind = parse_int(_regex_group(
        clean,
        r"MAX(?:IMUM)?\s+SUSTAINED(?:\s+SURFACE)?\s+WINDS?\s*(?:-|ARE ESTIMATED AT)?\s*(\d+)\s*(?:KT|KNOTS)",
    ))
    if wind is None:
        wind = parse_int(_regex_group(clean, r"(\d+)\s*KT"))
    if wind is None:
        return None
    pressure = parse_int(_regex_group(clean, r"(?:MINIMUM\s+)?CENTRAL\s+PRESSURE\s*(?:IS)?\s*(\d+)\s*MB"))
    position = re.search(
        r"(?:LOCATED\s+)?NEAR\s+(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])",
        clean,
        re.IGNORECASE,
    )
    lat = parse_coordinate("".join(position.group(1, 2))) if position else None
    lon = parse_coordinate("".join(position.group(3, 4))) if position else None
    compact_issued_at = _regex_group(clean, r"(\d{6}Z)\s+POSITION")
    issued_at = fallback_issued_at or compact_issued_at
    if not storm_id:
        storm_id = _fallback_storm_id(clean, storm_name)
    if not storm_name:
        storm_name = storm_id or "JTWC storm"

    return CycloneAdvisory(
        source="jtwc",
        storm_id=storm_id or storm_name,
        storm_name=storm_name,
        basin=_basin_from_storm_id(storm_id),
        advisory_number=advisory_number,
        issued_at=issued_at,
        wind_kt=wind,
        pressure_mb=pressure,
        lat=lat,
        lon=lon,
        classification=_classification_from_text(clean),
        public_advisory_url=fallback_url,
        advisory_text=clean[:8000],
    )


def _text(item: ET.Element, tag: str) -> str:
    child = item.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def _is_no_active_item(title: str, description: str) -> bool:
    haystack = f"{title} {description}".lower()
    return "no active tropical warnings" in haystack


def _looks_like_warning(title: str, description: str) -> bool:
    haystack = f"{title} {description}".lower()
    return "warning nr" in haystack or "max sustained" in haystack


def _extract_links(html: str) -> list[str]:
    return re.findall(r"""href=["']([^"']+)["']""", html or "", flags=re.IGNORECASE)


def _is_warning_product_link(url: str) -> bool:
    lowered = url.lower()
    if not lowered.endswith(".txt"):
        return False
    filename = lowered.rsplit("/", 1)[-1]
    # Significant-weather outlooks are not active cyclone warnings.
    if filename.startswith(("abpw", "abio", "abio10", "abpw10")):
        return False
    return True


def _fetch_product_text(url: str) -> str:
    if not url:
        return ""
    try:
        response = fetch_with_retry(
            url,
            headers={"User-Agent": "(theheat-bot, contact@theheat.app)"},
            timeout=20,
            attempts=2,
        )
        return response.text
    except requests.RequestException:
        return ""


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _regex_group(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else ""


def _fallback_storm_id(text: str, storm_name: str) -> str:
    if storm_name:
        return re.sub(r"[^A-Z0-9]+", "_", storm_name.upper()).strip("_")
    match = re.search(r"\b(\d{2}[A-Z])\b", text.upper())
    return match.group(1) if match else ""


def _classification_from_text(text: str) -> str:
    lowered = text.lower()
    if "super typhoon" in lowered:
        return "Super Typhoon"
    if "typhoon" in lowered:
        return "Typhoon"
    if "tropical storm" in lowered:
        return "Tropical Storm"
    if "tropical depression" in lowered:
        return "Tropical Depression"
    return "Tropical Cyclone"


def _basin_from_storm_id(storm_id: str) -> str:
    upper = (storm_id or "").upper()
    if upper.endswith("W"):
        return "Western Pacific"
    if upper.endswith("B") or upper.endswith("A"):
        return "North Indian Ocean"
    if upper.endswith("S") or upper.endswith("P"):
        return "Southern Hemisphere"
    if upper.endswith("C"):
        return "Central Pacific"
    if upper.endswith("E"):
        return "Eastern Pacific"
    return "JTWC basin"


__all__ = [
    "BasinRecordEvent",
    "CycloneAdvisory",
    "LandfallEvent",
    "RapidIntensificationEvent",
    "TierCrossingEvent",
    "detect_basin_records",
    "detect_landfalls",
    "detect_rapid_intensification",
    "detect_tier_crossings",
    "fetch_active_cyclones",
    "parse_rss",
    "parse_warning_text",
]
