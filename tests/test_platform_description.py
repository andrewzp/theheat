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
