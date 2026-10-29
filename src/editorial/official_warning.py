"""Pure, explicitly nominated warning evidence; no acquisition or approval.

The nomination comes from the operator/source adapter, separately from packet
JSON. It pins the exact current packet and original-language determination. A
packet cannot nominate itself, authenticate an issuer or certify its own language.
This boundary checks those supplied bindings, not remote source authenticity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from src.commands.schema import CommandError, utc_datetime
from src.two_bot.retry import NonRetryableError

MAX_METADATA_BYTES = 128 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_EXCERPT_BYTES = 16 * 1024
SCHEMA = "theheat.official-warning/v1"
_KEYS = frozenset({"schema", "issuer_id", "report_id", "revision", "source_url",
    "content_sha256", "issued_at", "captured_at", "valid_until", "original_language",
    "translation", "warning", "place"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SHA = re.compile(r"[a-f0-9]{64}")


class WarningHold(NonRetryableError):
    """Stable reason only; never disclose source bytes or parser diagnostics."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise WarningHold(code)


def _text(value: Any, limit: int, code: str) -> str:
    _require(type(value) is str and bool(value.strip()), code)
    try:
        _require(len(value.encode("utf-8")) <= limit
                 and all(char.isprintable() for char in value), code)
    except UnicodeError:
        raise WarningHold(code) from None
    return value


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _origin(value: Any, *, origin_only: bool = False) -> tuple[str, str, int]:
    _text(value, 2048, "warning_source_url_invalid")
    try:
        parsed = urlsplit(value)
        _require(value.isascii() and not any(char.isspace() for char in value)
                 and parsed.scheme == "https" and bool(parsed.hostname)
                 and parsed.username is None and parsed.password is None
                 and not parsed.fragment, "warning_source_url_invalid")
        if origin_only:
            _require(parsed.path in ("", "/") and not parsed.query,
                     "warning_source_url_invalid")
        port = parsed.port if parsed.port is not None else 443
        _require(port > 0, "warning_source_url_invalid")
        return parsed.scheme, parsed.hostname or "", port
    except ValueError:
        raise WarningHold("warning_source_url_invalid") from None


def _time(value: Any) -> datetime:
    try:
        return utc_datetime(value)
    except CommandError:
        raise WarningHold("warning_time_invalid") from None


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _require(key not in result, "warning_metadata_invalid")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise WarningHold("warning_metadata_invalid")


@dataclass(frozen=True)
class WarningNomination:
    """Trusted adapter input, not a JSON field or a source-authentication token.

    The adapter must independently select the known issuer/origin and current
    report revision and establish that these exact bytes are an English original.
    A client-supplied English label, translated prose, hash or reviewed flag is
    insufficient. The eventual producer must resolve this input again at each
    freshness/revision boundary rather than cache it across callbacks.
    """

    issuer_id: str
    issuer_name: str
    origin: str
    report_id: str
    revision: str
    metadata_sha256: str
    content_sha256: str
    original_language: str | None


@dataclass(frozen=True)
class WarningEvidence:
    """Immutable retained inputs, never a human review or permission to post."""

    metadata_bytes: bytes
    source_bytes: bytes
    nomination: WarningNomination

    def metadata(self) -> dict[str, Any]:
        # JSON was strictly parsed before construction. Return a new object so
        # downstream presentation cannot mutate the retained source contract.
        return json.loads(self.metadata_bytes)

    @property
    def lineage_id(self) -> str:
        identity = [self.nomination.issuer_id, _origin(self.nomination.origin, origin_only=True),
                    self.nomination.report_id]
        return "official_warning:" + _digest(json.dumps(identity, separators=(",", ":")).encode())

    @property
    def evidence_sha256(self) -> str:
        # Configured attribution affects writer facts too. Bind it along with
        # exact retained bytes, not only the packet's self-declared issuer ID.
        identity = {"schema": "theheat.warning-evidence/v1",
            "metadata_sha256": _digest(self.metadata_bytes),
            "content_sha256": _digest(self.source_bytes),
            "issuer_id": self.nomination.issuer_id,
            "issuer_name": self.nomination.issuer_name,
            "origin": _origin(self.nomination.origin, origin_only=True),
            "report_id": self.nomination.report_id,
            "revision": self.nomination.revision,
            "original_language": self.nomination.original_language}
        return _digest(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8"))


def _anchor(value: Any, raw: bytes) -> tuple[int, int, str]:
    _require(type(value) is dict and set(value) == {"start", "end", "text"},
             "warning_anchor_invalid")
    start, end, text = value["start"], value["end"], value["text"]
    _require(type(start) is int and type(end) is int
             and 0 <= start < end <= len(raw) and end - start <= MAX_EXCERPT_BYTES,
             "warning_anchor_bound")
    _require(type(text) is str and bool(text.strip()), "warning_anchor_invalid")
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        raise WarningHold("warning_anchor_invalid") from None
    _require(raw[start:end] == encoded, "warning_anchor_changed")
    return start, end, text


def validate_warning_packet(
    metadata_bytes: bytes,
    source_bytes: bytes,
    *,
    nomination: WarningNomination | None,
    now: datetime,
) -> WarningEvidence:
    """Validate one nominated current warning, without I/O or model work.

    Lengths are checked before JSON/UTF-8 parsing. A changed current nomination
    refuses the old packet, including a conflicting copy with the same revision.
    No rule infers physical occurrence, impact, translation or source authenticity.
    """
    _require(type(metadata_bytes) is bytes and 0 < len(metadata_bytes) <= MAX_METADATA_BYTES,
             "warning_metadata_bound")
    _require(type(source_bytes) is bytes and 0 < len(source_bytes) <= MAX_ARTIFACT_BYTES,
             "warning_artifact_bound")
    _require(type(nomination) is WarningNomination, "warning_nomination_required")
    assert nomination is not None  # Narrowing only; the explicit refusal is above.
    for name in ("issuer_id", "report_id", "revision"):
        value = getattr(nomination, name)
        _require(type(value) is str and _IDENTIFIER.fullmatch(value) is not None,
                 "warning_nomination_invalid")
    _text(nomination.issuer_name, 300, "warning_nomination_invalid")
    origin = _origin(nomination.origin, origin_only=True)
    for value in (nomination.metadata_sha256, nomination.content_sha256):
        _require(type(value) is str and _SHA.fullmatch(value) is not None,
                 "warning_nomination_invalid")
    _require(nomination.original_language == "en", "warning_english_original_unverified")
    _require(_digest(metadata_bytes) == nomination.metadata_sha256
             and _digest(source_bytes) == nomination.content_sha256,
             "warning_nomination_changed")
    try:
        source_bytes.decode("utf-8")
        packet = json.loads(metadata_bytes.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise WarningHold("warning_metadata_or_encoding_invalid") from None
    _require(type(packet) is dict and set(packet) == _KEYS
             and packet["schema"] == SCHEMA, "warning_metadata_invalid")
    _require(all(packet[name] == getattr(nomination, name)
                 for name in ("issuer_id", "report_id", "revision", "content_sha256")),
             "warning_nomination_changed")
    _require(_origin(packet["source_url"]) == origin, "warning_issuer_origin_changed")
    _require(packet["original_language"] == "en" and packet["translation"] is None,
             "warning_english_original_unverified")
    _require(type(now) is datetime and now.tzinfo is not None
             and now.utcoffset() == timedelta(0), "warning_clock_invalid")
    issued, captured, until = (_time(packet[name])
                               for name in ("issued_at", "captured_at", "valid_until"))
    _require(issued <= captured <= now and issued < until, "warning_time_incoherent")
    _require(now < until, "warning_expired")
    begin, end, _ = _anchor(packet["warning"], source_bytes)
    place = packet["place"]
    _require(type(place) is dict and set(place) == {"name", "country", "anchor"},
             "warning_place_invalid")
    _text(place["name"], 300, "warning_place_invalid")
    _require(type(place["country"]) is str
             and re.fullmatch(r"[A-Z]{2}", place["country"]) is not None,
             "warning_place_invalid")
    p_begin, p_end, p_text = _anchor(place["anchor"], source_bytes)
    _require(begin <= p_begin < p_end <= end and p_text == place["name"],
             "warning_place_unanchored")
    # A substring in another name is not an exact named-place mention.
    decoded = source_bytes.decode("utf-8")
    before, after = source_bytes[:p_begin].decode("utf-8"), source_bytes[p_end:].decode("utf-8")
    _require((not before or not (before[-1].isalnum() or before[-1] == "_"))
             and (not after or not (after[0].isalnum() or after[0] == "_")),
             "warning_place_unanchored")
    _require("\x00" not in decoded, "warning_source_encoding_invalid")
    return WarningEvidence(metadata_bytes, source_bytes, nomination)
