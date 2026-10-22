"""Representation/fit counterexamples; invented bytes confer no scientific pass."""
from copy import deepcopy
import binascii
import struct
from uuid import uuid4
import zlib

import pytest

from src.media import platform_description as d
from src.editorial.revisions import fingerprint
from src.posting.local_delivery import SCOPE


def png(size=None):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data))
    start = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    end = chunk(b"IDAT", zlib.compress(b"\0\xff\0\0")) + chunk(b"IEND", b"")
    extra = b"" if size is None else chunk(b"tEXt", b"note\0" + b"a" * (size - len(start) - len(end) - 17))
    result = start + extra + end
    assert size is None or len(result) == size
    return result


def config():
    return dict(schema_version=2, scope=SCOPE, invented=True, instance_id=str(uuid4()),
        origin="http://127.0.0.1:3333", routes_version=1, actor="did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
        platform_profile=d.FIXTURE_PROFILE)


def record(raw=b"Complete invented description.\n", image=None, profile=None):
    image = png() if image is None else image
    profile = d.profiles(config()) if profile is None else profile
    packet = dict(packet_sha256="a" * 64, draft_binding=dict(draft_id="invented", policy_sha256="b" * 64),
        graphic_binding=dict(source="invented-only"), media=dict(alt_text=raw[:-1].decode("utf-8"),
            png_sha256=d.sha(image), byte_count=len(image), mime_type="image/png", width=1, height=1))
    return d.build(dict(decision_revision=3), packet, "c" * 64, raw, image, profile), image


@pytest.mark.parametrize("text", ["a" * 999 + "\n", "a" * 1000 + "\n", "a\r\n", "a\\n\n",
    "😀\n", "e\u0301\n", "é\n", "日本語\n", "a\n\n"],
    ids=["1000", "1001", "crlf", "literal-backslash-n", "emoji", "combining", "composed", "non-latin", "two-lf"])
def test_exact_scalar_bytes_and_terminators(text):
    raw = text.encode("utf-8")
    value, image = record(raw)
    assert value["wire"] == dict(sha256=d.sha(raw), scalar_count=len(text), byte_count=len(raw))
    assert d.validate(value, raw_alt=raw, png=image) == text
    if len(text) > 1000 or len(raw) > 1000:
        with pytest.raises(d.DescriptionError, match="platform_description_x_house_limit"):
            d.preflight(value, raw_alt=raw, png=image, expected_profiles=value["profiles"])
    else:
        assert d.preflight(value, raw_alt=raw, png=image, expected_profiles=value["profiles"]) == text


@pytest.mark.parametrize("text", ["\ud800", "\udfff", "x\udc00y"])
def test_lone_surrogate_is_not_a_scalar(text):
    with pytest.raises(d.DescriptionError, match="invalid_utf8"):
        d.text_identity(text)


def test_non_latin_house_guard_is_stricter_than_official_character_limit():
    raw = ("界" * 334 + "\n").encode()
    value, image = record(raw)
    assert value["wire"]["scalar_count"] == 335 and value["wire"]["byte_count"] == 1003
    with pytest.raises(d.DescriptionError, match="x_house_limit"):
        d.preflight(value, raw_alt=raw, png=image, expected_profiles=value["profiles"])


@pytest.mark.parametrize("size", [1_999_999, 2_000_000, 2_000_001, 2 * 1024 * 1024])
def test_actual_valid_png_decimal_boundary(size):
    raw = b"Complete invented description.\n"
    value, image = record(raw, png(size))
    assert len(image) == size
    if size > 2_000_000:
        with pytest.raises(d.DescriptionError, match="platform_image_bluesky_limit"):
            d.preflight(value, raw_alt=raw, png=image, expected_profiles=value["profiles"])
    else:
        assert d.preflight(value, raw_alt=raw, png=image, expected_profiles=value["profiles"]) == raw.decode()


def test_full_2409_ascii_refuses_without_shortening_and_legacy_x_never_qualifies():
    raw = b"a" * 2408 + b"\n"
    value, image = record(raw)
    with pytest.raises(d.DescriptionError, match="x_house_limit"):
        d.preflight(value, raw_alt=raw, png=image, expected_profiles=value["profiles"])
    short = b"Short invented description.\n"
    value, image = record(short, profile=d.profiles())
    with pytest.raises(d.DescriptionError, match="platform_api_unqualified"):
        d.preflight(value, raw_alt=short, png=image, expected_profiles=d.profiles())
    assert value["wire"]["sha256"] == d.sha(short)


@pytest.mark.parametrize("change", ["size", "bytes", "wire", "semantic", "shortened", "destinations", "profile", "target"])
def test_exact_record_and_actual_artifacts_refuse_tampering(change):
    raw = b"Complete invented description.\n"
    value, image = record(raw)
    expected_profiles = deepcopy(value["profiles"])
    if change == "size":
        value["png"]["byte_count"] -= 1
    elif change == "bytes":
        image = image[:-1] + b"X"
    elif change == "wire":
        raw = b"Shortened.\n"
    elif change == "semantic":
        value["semantic_alt_sha256"] = "f" * 64
    elif change == "shortened":
        value["derivation"] = "shortened"
    elif change in {"destinations", "profile"}:
        value["profiles"][change] = ["x"] if change == "destinations" else "invented-live-qualified"
    else:
        value["target"]["decision_revision"] += 1
    # Artifact validation still defeats recomputed false counts/derivation. A
    # target change without its approved fingerprint is independently refused.
    if change != "target":
        value["description_sha256"] = fingerprint({k:v for k,v in value.items() if k != "description_sha256"})
    with pytest.raises(d.DescriptionError):
        d.preflight(value, raw_alt=raw, png=image, expected_profiles=expected_profiles)


def test_valid_header_with_corrupt_png_body_is_not_qualified():
    raw = b"Complete invented description.\n"
    image = png()[:-12]
    value, _ = record(raw, image)
    with pytest.raises(d.DescriptionError):
        d.preflight(value, raw_alt=raw, png=image, expected_profiles=value["profiles"])


@pytest.mark.parametrize("failure", ["long", "bluesky_size", "legacy", "v1"])
def test_all_destination_failure_precedes_even_transport_construction(monkeypatch, failure):
    from src.posting import delivery_transport
    from tests.local_delivery_helpers import value
    cfg = config()
    raw = b"a" * 1000 + b"\n" if failure == "long" else b"Complete description.\n"
    image = png(2_000_001) if failure == "bluesky_size" else png()
    if failure == "legacy":
        cfg = {k:v for k,v in cfg.items() if k != "platform_profile"}
        cfg["schema_version"] = 1
    source = value(cfg, image, alt=raw.decode())
    if failure == "v1":
        source.pop("platform_description")
        source["schema_version"] = 1
    monkeypatch.setattr(delivery_transport, "_Boundary", lambda *a:pytest.fail("Transport was constructed before all-destination preflight"))
    with pytest.raises(ValueError, match="platform_"):
        delivery_transport.execute(source,"x","upload",dict(png=image,alt=raw.decode()),begin=None,observe=None,check=None)


def modis_record(*, count=4, spec=None, derivation=None):
    from src.media.evidence_graphic import build_alt_text
    from tests.fire_graphic_helpers import graphic_bundle
    from tests.test_fire_map_graphic_adapter import adapt, NEIGHBORS
    spec = spec or adapt(graphic_bundle(values=[125.75, 500.1234, 750.25, 250][:count], coordinates=NEIGHBORS[:count]))
    image = png()
    raw = (build_alt_text(spec["template"], spec["evidence"]) + "\n").encode()
    packet = dict(packet_sha256="a" * 64, draft_binding=dict(draft_id="invented", policy_sha256="b" * 64),
        graphic_binding=dict(template=spec["template"], evidence_sha256=spec["expected_evidence_sha256"]),
        media=dict(alt_text=raw[:-1].decode(), png_sha256=d.sha(image), byte_count=len(image), mime_type="image/png", width=1, height=1))
    result = d.build(dict(decision_revision=3), packet, "c" * 64, raw, image, d.profiles(config()), graphic_spec=spec, derivation=derivation)
    return result, raw, image, spec


@pytest.mark.parametrize("count,size", [(1, 922), (4, 998)])
def test_source_modis_projection_keeps_every_exact_row_and_qualification(count, size):
    value, raw, image, spec = modis_record(count=count)
    wire = d.preflight(value, raw_alt=raw, png=image, graphic_spec=spec, expected_profiles=value["profiles"])
    assert value["schema_version"] == 2 and value["derivation"] == d.MODIS_DERIVATION
    assert value["wire_text"] == wire and value["wire"] == d.text_identity(wire)
    assert len(wire) == len(wire.encode()) == size <= 1000 < len(raw)
    assert not wire.endswith("\n") and raw.endswith(b"\n")
    assert value["raw_alt_sha256"] == d.sha(raw) != value["wire"]["sha256"]
    assert value["graphic_spec_sha256"] == fingerprint(spec)
    for point in spec["evidence"]["points"]:
        assert f"{point['label']} {point['lat']},{point['lon']}/{point['frp_source']}" in wire
    for phrase in ("All confidence 91.0%, version synthetic-v1", "UTC minute, not seconds",
        "not max/severity", "not temperature/area/whole-fire intensity", "separate-fire counts",
        "scan/track/footprints unknown", "instant/overpass/incident unproven", "source quality",
        "no incident/cause/impact/location certification", "Plate carree, not distance/area",
        "Inset=location/viewport, not fire area", "absent islands do not prove water",
        "no original HTTP/source authentication/freshness/review/approval"):
        assert phrase in wire
    # Existing record version and historical raw reuse stay byte-for-byte distinct.
    old, _, _, _ = modis_record(count=count, derivation="full_raw_alt")
    assert old["schema_version"] == 1 and "wire_text" not in old
    assert d.validate(old, raw_alt=raw, png=image) == raw.decode()
    with pytest.raises(d.DescriptionError, match="x_house_limit"):
        d.preflight(old, raw_alt=raw, png=image, expected_profiles=old["profiles"])


@pytest.mark.parametrize("field", ["missing", "extra", "wire", "counts", "spec", "source", "image", "raw", "version", "boolversion", "unknown_derivation"])
def test_source_modis_record_rehash_cannot_create_projection_authority(field):
    value, raw, image, spec = modis_record()
    if field == "missing":
        value.pop("wire_text")
    elif field == "extra":
        value["operator_override"] = True
    elif field == "wire":
        value["wire_text"] = "Shortened scientifically incomplete description."
        value["wire"] = d.text_identity(value["wire_text"])
    elif field == "counts":
        value["wire"]["byte_count"] -= 1
    elif field == "spec":
        spec["expected_evidence_sha256"] = "f" * 64
    elif field == "source":
        spec["evidence"]["points"][0]["frp_source"] += 1
        spec["expected_evidence_sha256"] = fingerprint(spec["evidence"])
        value["graphic_spec_sha256"] = fingerprint(spec)
    elif field == "image":
        image = image[:-1] + b"x"
    elif field == "raw":
        raw = raw[:-2] + b"x\n"
        value["raw_alt_sha256"] = d.sha(raw)
        value["semantic_alt_sha256"] = d.sha(raw[:-1])
    elif field in {"version", "boolversion"}:
        value["schema_version"] = 3 if field == "version" else True
    else:
        value["derivation"] = "operator_shortened"
    value["description_sha256"] = fingerprint({k:v for k,v in value.items() if k != "description_sha256"})
    with pytest.raises(d.DescriptionError):
        d.preflight(value, raw_alt=raw, png=image, graphic_spec=spec, expected_profiles=value["profiles"])


@pytest.mark.parametrize("change", ["missing", "extra", "template", "nonfinite", "bool", "unknown", "source_missing"])
def test_closed_modis_spec_requires_independent_complete_scientific_reconstruction(change):
    _, _, _, spec = modis_record()
    if change == "missing":
        spec.pop("expected_evidence_sha256")
    elif change == "extra":
        spec["operator_approval"] = True
    elif change == "template":
        spec["template"] = "viirs_thermal_detection_map"
    elif change == "source_missing":
        spec["evidence"]["input_binding"]["bundles"] = []
    else:
        point = spec["evidence"]["points"][0]
        point["frp_source"] = float("inf") if change == "nonfinite" else True if change == "bool" else "unknown"
    if "evidence" in spec and change != "missing":
        try:
            spec["expected_evidence_sha256"] = fingerprint(spec["evidence"])
        except ValueError:
            pass
    with pytest.raises((d.DescriptionError, ValueError, KeyError)):
        d.modis_wire_text(spec)


def test_modis_differing_columns_precision_and_dateline_are_never_removed_to_fit():
    from tests.test_fire_map_graphic_adapter import adapt, NEIGHBORS
    from tests.fire_graphic_helpers import graphic_bundle
    from src.two_bot.intern.fire import build_fire_bundle
    from tests.fire_source_fixtures import fire_event
    from src.two_bot.types import RelatedSignal
    bundle = graphic_bundle(values=[125.75, 500.1234567890123, 750.25, 250], coordinates=NEIGHBORS)
    # A different real source field must appear in its own row, never be grouped
    # under a false shared column merely to pass the house guard.
    other = fire_event(when=__import__("datetime").datetime.fromisoformat(bundle.when.replace("Z", "+00:00")), lat=NEIGHBORS[1][0], lon=NEIGHBORS[1][1], frp=500.1234567890123, confidence=92, product="MODIS_NRT")
    related = build_fire_bundle(other)
    bundle.related_signals[0] = RelatedSignal(event_id=related.event_id, signal_kind="fire", where=related.where,
        when=related.when, headline_metric=related.headline_metric, country=related.country,
        acquisition_evidence=related.raw_signal_dump["acquisition_provenance"])
    value, raw, image, spec = modis_record(spec=adapt(bundle))
    assert "Lat,lon degrees/FRP MW/confidence %/version:" in value["wire_text"]
    assert "/500.1234567890123/92.0/synthetic-v1" in value["wire_text"]
    assert len(value["wire_text"].encode()) > 1000
    with pytest.raises(d.DescriptionError, match="x_house_limit"):
        d.preflight(value, raw_alt=raw, png=image, graphic_spec=spec, expected_profiles=value["profiles"])
    assert d.validate(value, raw_alt=raw, png=image, graphic_spec=spec) == value["wire_text"]
    dateline = adapt(graphic_bundle(values=[125.75, 500.1234, 750.25, 250], coordinates=[(35,179.9945),(35,-179.9945),(35.009,179.9945),(35.009,-179.9945)]))
    value, raw, image, spec = modis_record(spec=dateline)
    assert "Crosses dateline." in value["wire_text"]
    assert "179.9945" in value["wire_text"] and "-179.9945" in value["wire_text"]
    with pytest.raises(d.DescriptionError, match="x_house_limit"):
        d.preflight(value, raw_alt=raw, png=image, graphic_spec=spec, expected_profiles=value["profiles"])


@pytest.mark.parametrize("field", ["raw", "spec", "wire", "profile", "image", "missing_spec"])
def test_modis_mismatch_refuses_before_transport_factory(field, monkeypatch):
    from src.posting import delivery_transport
    from tests.local_delivery_helpers import value as legacy_value
    description, raw, image, spec = modis_record()
    source = legacy_value(config(), image)
    source.update(platform_description=description, alt_sha256=d.sha(raw))
    prepared = dict(alt=description["wire_text"], raw_alt=raw, png=image, graphic_spec=spec)
    if field == "raw":
        prepared["raw_alt"] = raw[:-1]
    elif field == "spec":
        prepared["graphic_spec"]["evidence"]["points"][0]["frp_source"] += 1
    elif field == "wire":
        prepared["alt"] += "changed"
    elif field == "profile":
        source["fixture"]["instance_id"] = str(uuid4())
    elif field == "image":
        prepared["png"] = image[:-1]
    else:
        prepared.pop("graphic_spec")
    monkeypatch.setattr(delivery_transport, "_Boundary", lambda *a:pytest.fail("Transport constructed before complete reconstructed MODIS preflight"))
    with pytest.raises(ValueError, match="platform_|delivery_request_content_changed"):
        delivery_transport.execute(source, "x", "upload", prepared, begin=None, observe=None, check=None)


def test_historical_raw_receipt_verifier_cannot_use_separate_raw_field_to_change_old_wire():
    from src.posting.delivery_receipts import descriptor, verify_request
    from src.commands.schema import canonical_json
    from tests.local_delivery_helpers import value as legacy_value
    image, raw = png(), "Original raw description.\n"
    source = legacy_value(config(), image, alt=raw)
    source.pop("platform_description")
    source["schema_version"] = 1
    prepared = dict(png=image, alt="Changed description.\n", raw_alt=raw.encode(), prior=dict(upload=dict(media_id="100")))
    body = canonical_json(dict(media_id="100", alt_text=dict(text=prepared["alt"]))).encode()
    with pytest.raises(ValueError, match="delivery_retained_asset_changed"):
        verify_request(source, "x", "alt", prepared, descriptor("x", "alt", "application/json", body), body)


def test_source_modis_unicode_source_version_keeps_scalars_and_bytes_distinct():
    from tests.test_fire_map_graphic_adapter import adapt
    from tests.fire_graphic_helpers import graphic_bundle
    from src.data.fire_source_contract import make_receipt, parse_record, FIRMS_PUBLIC_URL
    bundle = graphic_bundle(values=[125.75])
    raw = dict(bundle.raw_signal_dump["acquisition_provenance"]["record"], version="界" * 80)
    bundle.raw_signal_dump["acquisition_provenance"] = make_receipt(parse_record("MODIS_NRT", raw), FIRMS_PUBLIC_URL)
    value, alt, image, spec = modis_record(spec=adapt(bundle))
    assert "界" * 80 in value["wire_text"]
    assert value["wire"]["scalar_count"] <= 1000 < value["wire"]["byte_count"]
    with pytest.raises(d.DescriptionError, match="x_house_limit"):
        d.preflight(value, raw_alt=alt, png=image, graphic_spec=spec, expected_profiles=value["profiles"])


@pytest.mark.parametrize("version", ["unknown", " UNKNOWN ", "n/a", " N/A ", "na", "Na", "none", " None ", "null", " NULL ", "?", " ? "])
def test_modis_unknown_version_context_is_held_only_by_new_projection(version):
    from tests.test_fire_map_graphic_adapter import adapt
    from tests.fire_graphic_helpers import graphic_bundle
    from src.data.fire_source_contract import make_receipt, parse_record, FIRMS_PUBLIC_URL
    from src.media.evidence_graphic import validate_graphic
    bundle = graphic_bundle(values=[125.75])
    raw = dict(bundle.raw_signal_dump["acquisition_provenance"]["record"], version=version)
    bundle.raw_signal_dump["acquisition_provenance"] = make_receipt(parse_record("MODIS_NRT", raw), FIRMS_PUBLIC_URL)
    spec = adapt(bundle)
    assert validate_graphic(spec["template"], spec["evidence"], expected_evidence_sha256=spec["expected_evidence_sha256"]) == spec["evidence"]
    with pytest.raises(d.DescriptionError, match="platform_description_unqualified"):
        d.modis_wire_text(spec)
    # The upstream validator and retained old full-raw record are unchanged.
    old, alt, image, _ = modis_record(spec=spec, derivation="full_raw_alt")
    assert old["schema_version"] == 1 and d.validate(old, raw_alt=alt, png=image) == alt.decode()


@pytest.mark.parametrize("version", ["future.collection-9+NRT", "unknown-but-supported-v9", "新規v9"])
def test_modis_unfamiliar_supported_version_text_is_preserved_without_allowlist(version):
    from tests.test_fire_map_graphic_adapter import adapt
    from tests.fire_graphic_helpers import graphic_bundle
    from src.data.fire_source_contract import make_receipt, parse_record, FIRMS_PUBLIC_URL
    bundle = graphic_bundle(values=[125.75])
    raw = dict(bundle.raw_signal_dump["acquisition_provenance"]["record"], version=version)
    bundle.raw_signal_dump["acquisition_provenance"] = make_receipt(parse_record("MODIS_NRT", raw), FIRMS_PUBLIC_URL)
    value, alt, image, spec = modis_record(spec=adapt(bundle))
    assert f"version {version}." in value["wire_text"]
    assert d.preflight(value, raw_alt=alt, png=image, graphic_spec=spec, expected_profiles=value["profiles"]) == value["wire_text"]
