"""Real pure packet boundary: explicit current nomination, no provider calls."""
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from src.editorial.official_warning import (
    MAX_ARTIFACT_BYTES, MAX_METADATA_BYTES, WarningHold, validate_warning_packet,
)
from tests.warning_helpers import NOW, WARNING, anchor, encode, nomination, packet, sha


def validate(metadata, raw, *, selected=None, now=NOW):
    encoded = encode(metadata)
    return validate_warning_packet(encoded, raw, nomination=selected or nomination(encoded, raw), now=now)


def test_exact_inputs_stay_immutable_and_returned_metadata_is_a_copy():
    metadata, raw = packet()
    encoded = encode(metadata)
    evidence = validate(metadata, raw)
    assert evidence.source_bytes == raw and evidence.metadata_bytes == encoded
    assert evidence.metadata() == metadata
    edited = evidence.metadata()
    edited["place"]["name"] = "Another Island"
    assert evidence.metadata() == metadata
    with pytest.raises(FrozenInstanceError):
        evidence.source_bytes = b"replacement"


@pytest.mark.parametrize("selected", [None, {}, {"reviewed": True}, "en"],
                         ids=["missing", "mapping", "self-reviewed", "language-label"])
def test_packet_cannot_nominate_or_authenticate_itself(selected: Any):
    metadata, raw = packet()
    with pytest.raises(WarningHold, match="^warning_nomination_required$"):
        validate_warning_packet(encode(metadata), raw, nomination=selected, now=NOW)


@pytest.mark.parametrize("field,value", [
    ("issuer_id", "another-agency"), ("report_id", "another-report"),
    ("revision", "r2"), ("content_sha256", "0" * 64), ("metadata_sha256", "0" * 64),
])
def test_new_current_nomination_holds_old_packet_even_if_source_revision_name_matches(field, value):
    metadata, raw = packet()
    selected = replace(nomination(encode(metadata), raw), **{field: value})
    with pytest.raises(WarningHold, match="^warning_nomination_changed$"):
        validate(metadata, raw, selected=selected)


@pytest.mark.parametrize("change", ["source", "metadata_whitespace", "claim", "expiry"])
def test_rehashing_self_declared_metadata_cannot_override_independent_nomination(change):
    metadata, raw = packet()
    original = nomination(encode(metadata), raw)
    if change == "source":
        raw += b"Changed revision."
        metadata["content_sha256"] = sha(raw)
    elif change == "claim":
        metadata["warning"]["text"] += " Unsupported addition."
    elif change == "expiry":
        metadata["valid_until"] = "2027-01-01T00:00:00Z"
    encoded = encode(metadata) + (b" " if change == "metadata_whitespace" else b"")
    with pytest.raises(WarningHold, match="^warning_nomination_changed$"):
        validate_warning_packet(encoded, raw, nomination=original, now=NOW)


@pytest.mark.parametrize("url", [
    "http://warnings.example.test/report", "https://warnings.example.test.evil.test/report",
    "https://warnings.example.test@evil.test/report", "https://user@warnings.example.test/report",
    "https://warnings.example.test:0/report", "https://warnings.example.test:8443/report",
    "https://warnings.example.test:bad/report", "https://warnings.example.test/report#other",
    "https://warnings.example.test/with space", "file:///private/report",
])
def test_wrong_or_ambiguous_origin_refuses_even_with_matching_declared_hashes(url):
    metadata, raw = packet()
    metadata["source_url"] = url
    with pytest.raises(WarningHold):
        validate(metadata, raw)


@pytest.mark.parametrize("language", [None, "und", "es", "en-US", "mixed", "translated"])
def test_packet_english_label_never_clears_missing_or_conflicting_original_language(language):
    metadata, raw = packet()
    selected = replace(nomination(encode(metadata), raw), original_language=language)
    with pytest.raises(WarningHold, match="^warning_english_original_unverified$"):
        validate(metadata, raw, selected=selected)


@pytest.mark.parametrize("change", ["language", "translation", "reviewed", "unexpected", "wrong_schema"])
def test_source_labels_or_unknown_contract_fields_never_promote_the_packet(change):
    metadata, raw = packet()
    if change == "language":
        metadata["original_language"] = "es"
    elif change == "translation":
        metadata["translation"] = {"status": "human_reviewed", "text": WARNING}
    elif change == "wrong_schema":
        metadata["schema"] = True
    else:
        metadata[change] = True
    with pytest.raises(WarningHold):
        validate(metadata, raw)


@pytest.mark.parametrize("field,value,reason", [
    ("issued_at", "2026-10-29T12:00:01Z", "warning_time_incoherent"),
    ("captured_at", "2026-10-29T12:00:01Z", "warning_time_incoherent"),
    ("captured_at", "2026-10-29T10:59:59Z", "warning_time_incoherent"),
    ("valid_until", "2026-10-29T11:00:00Z", "warning_time_incoherent"),
    ("valid_until", "2026-10-29T12:00:00Z", "warning_expired"),
    ("valid_until", "2026-10-29T11:59:59Z", "warning_expired"),
    ("valid_until", "2026-10-29", "warning_time_invalid"),
    ("issued_at", "2026-10-29T11:00:00", "warning_time_invalid"),
    ("issued_at", "2026-10-29T11:00:00+00:00", "warning_time_invalid"),
    ("issued_at", "2026-02-30T11:00:00Z", "warning_time_invalid"),
])
def test_clock_and_expiry_boundaries_are_explicit(field, value, reason):
    metadata, raw = packet()
    metadata[field] = value
    with pytest.raises(WarningHold, match=f"^{reason}$"):
        validate(metadata, raw)


@pytest.mark.parametrize("clock", [None, datetime(2026, 10, 29, 12),
                                    NOW.astimezone(timezone(timedelta(hours=1)))])
def test_bad_now_never_silently_uses_machine_time(clock):
    metadata, raw = packet()
    with pytest.raises(WarningHold, match="^warning_clock_invalid$"):
        validate(metadata, raw, now=clock)


def test_last_microsecond_is_valid_but_expiry_is_not_and_no_cached_validation_is_reused():
    metadata, raw = packet()
    until = datetime(2026, 10, 30, tzinfo=UTC)
    validate(metadata, raw, now=until - timedelta(microseconds=1))
    with pytest.raises(WarningHold, match="^warning_expired$"):
        validate(metadata, raw, now=until)


@pytest.mark.parametrize("change", ["bool_start", "negative", "past_end", "text", "oversize", "unknown"])
def test_invalid_byte_anchors_never_become_claims(change):
    metadata, raw = packet()
    item = metadata["warning"]
    if change == "bool_start":
        item["start"] = True
    elif change == "negative":
        item["start"] = -1
    elif change == "past_end":
        item["end"] = len(raw) + 1
    elif change == "text":
        item["text"] = "Invented claim that was never in the source."
    elif change == "oversize":
        raw += b"a" * 16385
        metadata["content_sha256"] = sha(raw)
        item["end"] = len(raw)
    else:
        item["trusted"] = True
    with pytest.raises(WarningHold):
        validate(metadata, raw)


def test_place_must_be_the_exact_named_mention_inside_the_warning():
    metadata, raw = packet()
    metadata["place"]["name"] = "Island"
    metadata["place"]["anchor"] = anchor(raw, "Island")
    validate(metadata, raw)  # Exact separate word, not a substring in another name.
    metadata["place"]["name"] = "Islandx"
    with pytest.raises(WarningHold, match="^warning_place_unanchored$"):
        validate(metadata, raw)


def test_place_mentioned_outside_warning_cannot_supply_warning_geography():
    metadata, raw = packet()
    raw = b"Another Island\n" + raw
    metadata["content_sha256"] = sha(raw)
    metadata["warning"] = anchor(raw, WARNING)
    metadata["place"] = {"name": "Another Island", "country": "ZZ",
                          "anchor": anchor(raw, "Another Island")}
    with pytest.raises(WarningHold, match="^warning_place_unanchored$"):
        validate(metadata, raw)


@pytest.mark.parametrize("field,value", [("name", " "), ("country", "zz"), ("country", None)])
def test_unknown_or_ambiguous_place_is_held(field, value):
    metadata, raw = packet()
    metadata["place"][field] = value
    with pytest.raises(WarningHold):
        validate(metadata, raw)


def test_utf8_byte_anchors_are_not_character_offsets():
    metadata, raw = packet()
    raw = "Invented é header\n".encode() + raw
    metadata["content_sha256"] = sha(raw)
    metadata["warning"] = anchor(raw, WARNING)
    metadata["place"]["anchor"] = anchor(raw, "Example Island")
    assert validate(metadata, raw).source_bytes == raw
    metadata["warning"]["start"] -= 1
    with pytest.raises(WarningHold, match="^warning_anchor_changed$"):
        validate(metadata, raw)


@pytest.mark.parametrize("kind", ["duplicate", "nan", "depth", "invalid_utf8", "array"])
def test_malformed_json_is_held_without_echoing_source(kind):
    metadata, raw = packet()
    encoded = {"duplicate": b'{"schema":1,"schema":2}', "nan": b'{"value":NaN}',
        "depth": b"[" * 2000 + b"]" * 2000, "invalid_utf8": b"\xff",
        "array": b"[]"}[kind]
    selected = replace(nomination(encode(metadata), raw), metadata_sha256=sha(encoded))
    with pytest.raises(WarningHold) as caught:
        validate_warning_packet(encoded, raw, nomination=selected, now=NOW)
    assert str(caught.value).startswith("warning_") and "INVENTED" not in str(caught.value)


@pytest.mark.parametrize("metadata,raw,code", [
    (b"", b"x", "warning_metadata_bound"),
    (b"x" * (MAX_METADATA_BYTES + 1), b"x", "warning_metadata_bound"),
    (b"{}", b"", "warning_artifact_bound"),
    (b"{}", b"x" * (MAX_ARTIFACT_BYTES + 1), "warning_artifact_bound"),
    ({}, b"x", "warning_metadata_bound"), (b"{}", "x", "warning_artifact_bound"),
], ids=["empty-metadata", "metadata-too-large", "empty-artifact", "artifact-too-large",
        "metadata-wrong-type", "artifact-wrong-type"])
def test_bounds_and_types_are_checked_before_decoding_or_nomination(metadata, raw, code):
    with pytest.raises(WarningHold, match=f"^{code}$"):
        validate_warning_packet(metadata, raw, nomination=None, now=NOW)


def test_same_revision_copy_must_match_independent_current_nomination():
    metadata, raw = packet()
    original = nomination(encode(metadata), raw)
    metadata["valid_until"] = "2026-10-30T01:00:00Z"
    conflicting = nomination(encode(metadata), raw)
    for selected, value in ((original, encode(metadata)),
                            (conflicting, encode(packet()[0]))):
        with pytest.raises(WarningHold, match="^warning_nomination_changed$"):
            validate_warning_packet(value, raw, nomination=selected, now=NOW)


def test_origin_normalization_and_revision_changes_preserve_one_report_lineage():
    metadata, raw = packet()
    evidence = validate(metadata, raw)
    selected = replace(nomination(encode(metadata), raw), origin="https://warnings.example.test:443/")
    assert validate(metadata, raw, selected=selected).lineage_id == evidence.lineage_id
    metadata["revision"] = "r2"
    revised = validate(metadata, raw)
    assert revised.lineage_id == evidence.lineage_id
    assert revised.evidence_sha256 != evidence.evidence_sha256


def test_changed_configured_attribution_changes_evidence_identity_without_relabeling_source():
    metadata, raw = packet()
    original = validate(metadata, raw)
    renamed = replace(nomination(encode(metadata), raw), issuer_name="Another configured name")
    changed = validate(metadata, raw, selected=renamed)
    assert changed.lineage_id == original.lineage_id
    assert changed.metadata_bytes == original.metadata_bytes
    assert changed.source_bytes == original.source_bytes
    assert changed.evidence_sha256 != original.evidence_sha256
