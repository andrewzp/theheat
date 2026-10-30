"""One NHC public advisory as typed, anchored, attributed forecast evidence.

Pure validation: no I/O, model work, approval or publication. An NHC public
advisory is not a formal warning and states no message expiry, so upstream
expiry stays explicitly unknown. A separate operator recheck deadline (at most
60 minutes after capture) and a non-future issue no more than 6 hours old bound
its use; neither is presented as a source expiry. The current-source owner must
independently re-read the fixed NHC products at every consequential boundary.

Exact bytes and hashes bind the retained evidence; they do not prove its claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
from typing import Any

from src.editorial.official_warning import MAX_ARTIFACT_BYTES, MAX_EXCERPT_BYTES, MAX_METADATA_BYTES, WarningHold

SCHEMA = "theheat.nhc-advisory/v1"
ORIGIN = "https://www.nhc.noaa.gov"
INDEX_URL = ORIGIN + "/CurrentStorms.json"
SOURCE_NAME = "NHC"
ISSUER = "National Hurricane Center"
MAX_INDEX_BYTES = MAX_METADATA_BYTES
MAX_PAGE_BYTES = MAX_ARTIFACT_BYTES
MAX_BULLETIN_BYTES = MAX_EXCERPT_BYTES
MAX_FRESHNESS_MINUTES = 60
MAX_ISSUE_AGE = timedelta(hours=6)
HAZARDS = ("RAINFALL", "WIND", "STORM SURGE", "SURF", "TORNADOES")
UPSTREAM_EXPIRY_STATUS = "not_supplied_by_source"
OPERATOR_RULE = "Operator recheck deadline, at most 60 minutes after capture; not an NHC expiry."
# Fixed civil offsets for the time zones NHC Miami uses on AT/EP public advisories.
_ZONES = {"AST": -4, "EDT": -4, "EST": -5, "CDT": -5, "CST": -6, "MDT": -6, "MST": -7,
          "PDT": -7, "PST": -8, "HST": -10, "UTC": 0, "GMT": 0}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_KINDS = ("Hurricane", "Tropical Storm", "Tropical Depression", "Subtropical Storm", "Subtropical Depression",
          "Post-Tropical Cyclone", "Potential Tropical Cyclone", "Remnants Of")
_TITLE = re.compile(r"(?P<kind>" + "|".join(re.escape(k) for k in _KINDS) + r") (?P<name>[A-Z][A-Za-z-]{1,30}"
                    r"(?: [A-Z][A-Za-z-]{1,30})?) (?:(?:Special|Intermediate) )?Advisory Number +"
                    r"(?P<number>[1-9][0-9]{0,2}[A-Z]?)")
_STORM = re.compile(r"(AL|EP)(0[1-9]|[1-4][0-9])(20[2-9][0-9])")
_BIN = re.compile(r"(AT|EP)[1-5]")
_ADVISORY = re.compile(r"[1-9][0-9]{0,2}[A-Z]?")
_PLACE = re.compile(r"[A-Z][A-Za-z.'-]*(?: [A-Za-z][A-Za-z.'-]*){0,7}")


class AdvisoryHold(WarningHold):
    """A named NHC-advisory hold; every existing warning handler treats it as a hold."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise AdvisoryHold(code)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc(value: Any, code: str = "nhc_advisory_time_invalid") -> datetime:
    _require(type(value) is str and len(value) <= 40, code)
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|\+00:00)", value)
    _require(match is not None, code)
    assert match is not None
    try:
        parsed = datetime.fromisoformat(match[1] + ("." + match[2] if match[2] else "") + "+00:00")
    except ValueError:
        raise AdvisoryHold(code) from None
    return parsed


def iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def aware_now(now: Any) -> datetime:
    _require(type(now) is datetime and now.tzinfo is not None and now.utcoffset() == timedelta(0),
             "nhc_advisory_clock_invalid")
    return now


@dataclass(frozen=True)
class AdvisoryNomination:
    """Explicit operator scope for one storm's public advisory; never a URL or host."""

    storm_id: str
    bin: str
    advisory: str
    hazard: str
    place: str
    country: str
    freshness_minutes: int

    def as_dict(self) -> dict:
        return {"storm_id": self.storm_id, "bin": self.bin, "advisory": self.advisory, "hazard": self.hazard,
                "place": self.place, "country": self.country, "freshness_minutes": self.freshness_minutes}

    @property
    def advisory_url(self) -> str:
        return f"{ORIGIN}/text/MIATCP{self.bin}.shtml"


_NOMINATION_KEYS = frozenset({"storm_id", "bin", "advisory", "hazard", "place", "country", "freshness_minutes"})


def nomination(value: Any) -> AdvisoryNomination:
    """Validate a supplied nomination object; unknown or missing fields hold."""
    _require(type(value) is dict and set(value) == _NOMINATION_KEYS, "nhc_advisory_nomination_invalid")
    storm, bin_, number = value["storm_id"], value["bin"], value["advisory"]
    _require(all(type(v) is str for v in (storm, bin_, number, value["hazard"], value["place"], value["country"])),
             "nhc_advisory_nomination_invalid")
    _require(_STORM.fullmatch(storm) is not None and _BIN.fullmatch(bin_) is not None
             and {"AL": "AT", "EP": "EP"}[storm[:2]] == bin_[:2], "nhc_advisory_nomination_invalid")
    _require(_ADVISORY.fullmatch(number) is not None and value["hazard"] in HAZARDS
             and 2 <= len(value["place"]) <= 120 and _PLACE.fullmatch(value["place"]) is not None
             and re.fullmatch(r"[A-Z]{2}", value["country"]) is not None, "nhc_advisory_nomination_invalid")
    minutes = value["freshness_minutes"]
    _require(type(minutes) is int and 1 <= minutes <= MAX_FRESHNESS_MINUTES, "nhc_advisory_freshness_invalid")
    return AdvisoryNomination(storm, bin_, number, value["hazard"], value["place"], value["country"], minutes)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in items:
        _require(key not in result, "nhc_advisory_index_invalid")
        result[key] = item
    return result


def _constant(_: str) -> None:
    raise AdvisoryHold("nhc_advisory_index_invalid")


def advisory_key(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"0*([1-9][0-9]{0,2})([A-Z]?)", value)
    _require(match is not None, "nhc_advisory_index_invalid")
    assert match is not None
    return int(match[1]), match[2]


def index_row(index_bytes: bytes, selected: AdvisoryNomination) -> dict:
    """The one current CurrentStorms row for the nominated storm, exactly as needed."""
    _require(type(index_bytes) is bytes and 0 < len(index_bytes) <= MAX_INDEX_BYTES, "nhc_advisory_index_bound")
    try:
        payload = json.loads(index_bytes.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise AdvisoryHold("nhc_advisory_index_invalid") from None
    _require(type(payload) is dict and type(payload.get("activeStorms")) is list, "nhc_advisory_format_drift")
    rows = [r for r in payload["activeStorms"] if type(r) is dict and r.get("id") == selected.storm_id.lower()]
    _require(len(rows) <= 1, "nhc_advisory_contradictory")
    _require(len(rows) == 1, "nhc_advisory_storm_not_current")
    row = rows[0]
    public: Any = row.get("publicAdvisory")
    _require(type(row.get("binNumber")) is str and type(row.get("name")) is str and type(public) is dict
             and all(type(public.get(k)) is str for k in ("advNum", "issuance", "url")), "nhc_advisory_format_drift")
    _require(row["binNumber"] == selected.bin, "nhc_advisory_contradictory")
    # The product URL is fixed by the bin; an index URL can only confirm it.
    _require(public["url"] in (selected.advisory_url, selected.advisory_url[len(ORIGIN):]),
             "nhc_advisory_index_url_mismatch")
    current, wanted = advisory_key(public["advNum"]), advisory_key(selected.advisory)
    _require(current <= wanted, "nhc_advisory_superseded")
    _require(current == wanted, "nhc_advisory_index_mismatch")
    issued = utc(public["issuance"], "nhc_advisory_format_drift")
    return {"id": row["id"], "binNumber": row["binNumber"], "name": row["name"], "advNum": public["advNum"],
            "issuance": public["issuance"], "url": public["url"], "issued_at": iso(issued)}


_PRE_OPEN = re.compile(rb"<pre(?:\s[^<>]*)?>", re.IGNORECASE)
_PRE_CLOSE = re.compile(rb"</pre\s*>", re.IGNORECASE)


def bulletin_span(page_bytes: bytes) -> tuple[int, int]:
    """Byte offsets of the single preformatted product; navigation is not evidence."""
    _require(type(page_bytes) is bytes and 0 < len(page_bytes) <= MAX_PAGE_BYTES, "nhc_advisory_page_bound")
    try:
        page_bytes.decode("utf-8")
    except UnicodeError:
        raise AdvisoryHold("nhc_advisory_encoding_invalid") from None
    opens, closes = list(_PRE_OPEN.finditer(page_bytes)), list(_PRE_CLOSE.finditer(page_bytes))
    _require(len(opens) == 1 and len(closes) == 1 and opens[0].end() < closes[0].start(), "nhc_advisory_format_drift")
    start, end = opens[0].end(), closes[0].start()
    _require(0 < end - start <= MAX_BULLETIN_BYTES, "nhc_advisory_bulletin_bound")
    return start, end


@dataclass(frozen=True)
class Bulletin:
    """Exact ASCII TCP bulletin bytes and the fields parsed from them."""

    raw: bytes
    wmo_header: str
    awips_id: str
    title: str
    storm_kind: str
    storm_name: str
    advisory: str
    atcf_id: str
    issued_at: str
    hazards: dict[str, tuple[int, int]]
    context: tuple[tuple[int, int], ...]

    def text(self, span: tuple[int, int]) -> str:
        return self.raw[span[0]:span[1]].decode("ascii")


def _lines(raw: bytes) -> list[tuple[int, int, str]]:
    rows, offset = [], 0
    for line in raw.split(b"\n"):
        rows.append((offset, offset + len(line), line.decode("ascii").rstrip(" \r")))
        offset += len(line) + 1
    return rows


def _issued(local: re.Match, summary: re.Match, wmo: re.Match) -> datetime:
    _require(local["tz"] in _ZONES and summary["tz"] == local["tz"] and summary["hhmm"] == local["hhmm"],
             "nhc_advisory_time_unsupported")
    _require(summary["ampm"] == local["ampm"], "nhc_advisory_time_contradictory")
    hhmm = int(local["hhmm"])
    hour, minute = divmod(hhmm, 100)
    _require(1 <= hour <= 12 and minute < 60, "nhc_advisory_time_invalid")
    hour = hour % 12 + (12 if local["ampm"] == "PM" else 0)
    try:
        naive = datetime(int(local["year"]), _MONTHS.index(local["mon"]) + 1, int(local["day"]), hour, minute)
    except ValueError:
        raise AdvisoryHold("nhc_advisory_time_invalid") from None
    _require(_DAYS[naive.weekday()] == local["dow"], "nhc_advisory_time_invalid")
    issued = (naive - timedelta(hours=_ZONES[local["tz"]])).replace(tzinfo=UTC)
    _require(summary["utc"] == issued.strftime("%H%M"), "nhc_advisory_time_contradictory")
    # The WMO header is the transmission time (ddhhmm), normally shortly before issue.
    day, hour, minute = int(wmo["dd"]), int(wmo["hh"]), int(wmo["mm"])
    _require(hour < 24 and minute < 60, "nhc_advisory_time_contradictory")
    sent = [datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)
            for d in (issued - timedelta(days=1), issued, issued + timedelta(days=1)) if d.day == day]
    _require(any(issued - timedelta(hours=3) <= value <= issued + timedelta(hours=1) for value in sent),
             "nhc_advisory_time_contradictory")
    return issued


_RAIN_MAP_REFERRAL = re.compile(
    rb"For a complete depiction of forecast rainfall associated with [A-Za-z -]{1,60},\r?\n"
    rb"please see the National Weather Service Storm Total Rainfall Graphic\r?\n"
    rb"available at <a href=(?P<quote>['\"])(?P<url>https://www\.hurricanes\.gov/"
    rb"graphics_(?P<bin>ep[1-5])\.shtml\?rainqpf\.)(?P=quote)>"
    rb"(?P<label>hurricanes\.gov/graphics_ep[1-5]\.shtml\?rainqpf\.)</a>"
)


def parse_bulletin(raw: bytes) -> Bulletin:
    """Strict English TCP structure; unsupported or drifting formats hold."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BULLETIN_BYTES, "nhc_advisory_bulletin_bound")
    _require(all(32 <= b < 127 or b in (10, 13) for b in raw), "nhc_advisory_encoding_invalid")
    # NHC inserts one inert rainfall-map reference outside its claim paragraphs.
    # Recognize only that exact form; never strip/normalize the retained product,
    # follow the link, or move any original byte offsets. Weather claims stay plain.
    referrals = list(_RAIN_MAP_REFERRAL.finditer(raw))
    _require(len(referrals) <= 1, "nhc_advisory_markup_in_product")
    remainder = _RAIN_MAP_REFERRAL.sub(b"", raw)
    _require(b"<" not in remainder and re.search(rb"&[A-Za-z#]", remainder) is None,
             "nhc_advisory_markup_in_product")
    for match in referrals:
        _require(match["url"][len(b"https://www."):] == match["label"]
                 and (match.start() == 0 or raw[match.start()-2:match.start()] == b"\n\n"
                      or raw[match.start()-3:match.start()] == b"\n \n")
                 and not raw[match.end():].split(b"\n", 1)[0].strip(),
                 "nhc_advisory_markup_in_product")
    lines = [row for row in _lines(raw)]
    body = [row for row in lines if row[2].strip()]
    _require(len(body) >= 8, "nhc_advisory_partial_response")
    head = [text for _, _, text in body[:7]]
    if head[0] == "000":
        head = [text for _, _, text in body[1:8]]
    wmo = re.fullmatch(r"WT(?:NT|PZ)[0-9]{2} KNHC (?P<dd>[0-9]{2})(?P<hh>[0-9]{2})(?P<mm>[0-9]{2})", head[0])
    awips = re.fullmatch(r"TCP(?P<basin>AT|EP)(?P<n>[1-5])", head[1])
    title = _TITLE.fullmatch(head[3])
    office = re.fullmatch(r"NWS National Hurricane Center Miami FL +(?P<atcf>(?:AL|EP)[0-9]{6})", head[4])
    local = re.fullmatch(r"(?P<hhmm>[0-9]{3,4}) (?P<ampm>AM|PM) (?P<tz>[A-Z]{3,4}) (?P<dow>[A-Z][a-z]{2}) "
                         r"(?P<mon>[A-Z][a-z]{2}) (?P<day>[0-9]{1,2}) (?P<year>[0-9]{4})", head[5])
    _require(None not in (wmo, awips, title, office, local) and head[2] == "BULLETIN"
             and local is not None and local["mon"] in _MONTHS and local["dow"] in _DAYS,
             "nhc_advisory_format_drift")
    assert wmo is not None and awips is not None and title is not None and office is not None and local is not None
    _require(all(match["bin"].decode().upper() == awips["basin"] + awips["n"] for match in referrals),
             "nhc_advisory_markup_in_product")
    summaries = [re.fullmatch(r"SUMMARY OF (?P<hhmm>[0-9]{3,4}) (?P<ampm>AM|PM) (?P<tz>[A-Z]{3,4})\.\.\."
                              r"(?P<utc>[0-9]{4}) UTC\.\.\.INFORMATION", text) for _, _, text in body]
    found = [m for m in summaries if m is not None]
    _require(len(found) == 1, "nhc_advisory_format_drift")
    _require(any(text == "$$" for _, _, text in body), "nhc_advisory_partial_response")
    issued = _issued(local, found[0], wmo)
    # Sections: a header line followed by a dashed underline.
    sections: dict[str, list[tuple[int, int, str]]] = {}
    current: str | None = None
    for index, row in enumerate(lines):
        nxt = lines[index + 1][2] if index + 1 < len(lines) else ""
        if row[2] and re.fullmatch(r"-{3,}", nxt) and re.fullmatch(r"[A-Z][A-Z .]+", row[2]):
            _require(row[2] not in sections, "nhc_advisory_contradictory")
            current = row[2]
            sections[current] = []
            continue
        if re.fullmatch(r"-{3,}", row[2]) or row[2] in ("$$",):
            if row[2] == "$$":
                current = None
            continue
        if current is not None:
            sections[current].append(row)
    hazards: dict[str, tuple[int, int]] = {}
    for paragraph in _paragraphs(sections.get("HAZARDS AFFECTING LAND", [])):
        start, end, text = paragraph
        key = next((k for k in HAZARDS if text.startswith(k + ":")), None)
        if key is not None:
            _require(key not in hazards, "nhc_advisory_contradictory")
            hazards[key] = (start, end)
    context: list[tuple[int, int]] = []
    for start, end, text in _paragraphs(sections.get("DISCUSSION AND OUTLOOK", [])):
        for s_start, s_end in _sentences(raw, start, end):
            sentence = raw[s_start:s_end].decode("ascii")
            if re.search(r"\b(?:weaken(?:s|ed|ing)?|dissipat(?:e|es|ed|ing|ion))\b", sentence, re.IGNORECASE):
                context.append((s_start, s_end))
    _require(office["atcf"][:2] == {"AT": "AL", "EP": "EP"}[awips["basin"]], "nhc_advisory_contradictory")
    claim_spans = [*hazards.values(), *context]
    _require(not any(match.start() < end and start < match.end()
                     for match in referrals for start, end in claim_spans), "nhc_advisory_markup_in_product")
    return Bulletin(raw=raw, wmo_header=head[0], awips_id=head[1], title=head[3], storm_kind=title["kind"],
                    storm_name=title["name"], advisory=title["number"], atcf_id=office["atcf"], issued_at=iso(issued),
                    hazards=hazards, context=tuple(context))


def _paragraphs(rows: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    result, block = [], []
    for row in [*rows, (0, 0, "")]:
        if row[2].strip():
            block.append(row)
        elif block:
            result.append((block[0][0], block[-1][1], " ".join(r[2].strip() for r in block)))
            block = []
    return result


def _sentences(raw: bytes, start: int, end: int) -> list[tuple[int, int]]:
    spans, begin = [], start
    for match in re.finditer(rb"\.(?=\s|$)", raw[start:end]):
        stop = start + match.end()
        while begin < stop and raw[begin:begin + 1].isspace():
            begin += 1
        if begin < stop:
            spans.append((begin, stop))
        begin = stop
    return spans


def place_span(bulletin: Bulletin, hazard: tuple[int, int], place: str) -> tuple[int, int]:
    """The nominated place as an exact word-bounded mention inside the hazard paragraph."""
    text = bulletin.text(hazard)
    found = [m for m in re.finditer(r"(?<![A-Za-z0-9_])" + re.escape(place) + r"(?![A-Za-z0-9_])", text)]
    _require(len(found) >= 1, "nhc_advisory_place_unanchored")
    first = found[0]
    return hazard[0] + first.start(), hazard[0] + first.end()


@dataclass(frozen=True)
class AdvisoryCapture:
    """One fixed-source read: exact HTTP bytes plus the instant they were captured."""

    index_bytes: bytes
    page_bytes: bytes
    captured_at: str


@dataclass(frozen=True)
class AdvisoryEvidence:
    """Validated current evidence; never a human review or permission to post."""

    nomination: AdvisoryNomination
    capture: AdvisoryCapture
    row: dict
    span: tuple[int, int]
    bulletin: Bulletin
    hazard: tuple[int, int]
    place: tuple[int, int]

    @property
    def deadline(self) -> datetime:
        return utc(self.capture.captured_at) + timedelta(minutes=self.nomination.freshness_minutes)

    def identity(self) -> dict:
        """What must be unchanged for a later read to be the same advisory evidence."""
        return {"storm_id": self.nomination.storm_id, "bin": self.nomination.bin,
                "advisory": self.bulletin.advisory, "issued_at": self.bulletin.issued_at,
                "bulletin_sha256": digest(self.bulletin.raw), "hazard": self.nomination.hazard,
                "hazard_span": list(self.hazard), "place": self.nomination.place,
                "country": self.nomination.country}


def check_times(issued_at: str, captured_at: str, deadline: datetime, now: datetime) -> None:
    now = aware_now(now)
    issued, captured = utc(issued_at), utc(captured_at)
    _require(issued <= captured and captured <= now, "nhc_advisory_time_incoherent")
    _require(deadline <= captured + timedelta(minutes=MAX_FRESHNESS_MINUTES), "nhc_advisory_freshness_invalid")
    _require(now - issued <= MAX_ISSUE_AGE, "nhc_advisory_issue_too_old")
    _require(now < deadline, "nhc_advisory_operator_deadline_passed")


def validate_capture(capture: AdvisoryCapture, selected: AdvisoryNomination, *, now: datetime) -> AdvisoryEvidence:
    """Validate one exact fixed-source read against the explicit nomination."""
    _require(type(capture) is AdvisoryCapture and type(selected) is AdvisoryNomination, "nhc_advisory_capture_invalid")
    row = index_row(capture.index_bytes, selected)
    start, end = bulletin_span(capture.page_bytes)
    bulletin = parse_bulletin(capture.page_bytes[start:end])
    _require(bulletin.atcf_id == selected.storm_id and bulletin.awips_id == "TCP" + selected.bin,
             "nhc_advisory_contradictory")
    _require(advisory_key(bulletin.advisory) == advisory_key(selected.advisory), "nhc_advisory_issue_mismatch")
    _require(bulletin.storm_name == row["name"], "nhc_advisory_contradictory")
    _require(row["issued_at"] == bulletin.issued_at, "nhc_advisory_issue_mismatch")
    hazard = bulletin.hazards.get(selected.hazard)
    _require(hazard is not None, "nhc_advisory_hazard_absent")
    assert hazard is not None
    evidence = AdvisoryEvidence(selected, capture, row, (start, end), bulletin, hazard,
                                place_span(bulletin, hazard, selected.place))
    check_times(bulletin.issued_at, capture.captured_at, evidence.deadline, now)
    return evidence
