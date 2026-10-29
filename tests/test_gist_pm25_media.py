"""PM2.5 forecast-day Gist post image on invented data only.

Deterministic Pillow chart from the existing strict adapter, a versioned bounded
X description, explicit image-path recency, and exact reviewed delivery through
the real manual sender to a fake X SDK. No source, model or platform call.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
from io import BytesIO
import json
import math
from typing import Any

from freezegun import freeze_time
from PIL import Image
import pytest

from src.data import air_quality_contract
from src.editorial import revisions
from src.media import gist_hazard_media as hazard, gist_media
from src.media.evidence_graphic import build_alt_text
from tests.gist_hazard_helpers import PM25_TEXT, SENDABLE_PM25, VARYING_PM25 as VARYING, pm25_bundle, window
from tests.gist_media_helpers import approve, attach, install_fake_x, run_manual, saved_draft, state_for

CURRENT = "2026-06-08T13:00:00Z"
TRACES: dict[str, list[Any]] = {"varying": VARYING, "flat": [150.0] * 24, "extreme": [100] * 23 + [2400], "integers": list(range(160, 184))}


@pytest.fixture(autouse=True)
def clock():
    with freeze_time(CURRENT) as frozen:
        yield frozen


@pytest.fixture(scope="module")
def prepared():
    bundle = pm25_bundle(VARYING, **SENDABLE_PM25)
    return bundle, hazard.prepare_media(bundle)


def draft_for(bundle, **changes):
    draft = saved_draft(bundle, draft_id="invented-pm25", draft_type="air_quality_hazard", text=PM25_TEXT,
                        created_at="2026-06-08T12:30:00Z")
    draft.update(changes)
    return draft


def attached(prepared):
    bundle, value = prepared
    return attach(draft_for(bundle), value["descriptor"], at="2026-06-08T12:45:00Z")


def rehash(bundle):
    """Recompute the selected-record digest after an invented mutation."""
    packet = window(bundle)
    core = {k: v for k, v in packet.items() if k != "selected_record_sha256"}
    packet["selected_record_sha256"] = hashlib.sha256(air_quality_contract._encoded(core)).hexdigest()
    return bundle


# ------------------------------------------------------------- rendering

@pytest.mark.parametrize("trace", sorted(TRACES))
def test_traces_render_deterministic_bounded_rgb_with_every_exact_value(trace):
    values = TRACES[trace]
    bundle = pm25_bundle(values)
    first, second = hazard.prepare_media(deepcopy(bundle)), hazard.prepare_media(deepcopy(bundle))
    assert first["png"] == second["png"] and first["descriptor"] == second["descriptor"]
    png = first["png"]
    assert len(png) <= 750_000 and png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(png)) as image:
        assert (image.format, image.mode, image.size) == ("PNG", "RGB", (1200, 1500))
    descriptor = first["descriptor"]
    assert len(json.dumps(descriptor, ensure_ascii=False).encode()) <= 16_384
    assert descriptor["kind"] == hazard.PM25 and descriptor["synthetic"] is False
    assert descriptor["image"] == {"mime_type": "image/png", "png_sha256": hashlib.sha256(png).hexdigest(),
                                   "byte_count": len(png), "width": 1200, "height": 1500, "mode": "RGB"}
    text = first["delivery_text"]
    assert len(text) <= 1000 and len(text.encode()) <= 1000
    assert descriptor["description"]["delivery_text"] == text
    # All 24 exact retained values in hourly order with an unambiguous local-hour key.
    samples = text.split("local time: ", 1)[1].split(". Mean", 1)[0].split("; ")
    assert samples == [f"{h:02d}:00 {json.dumps(v)}" for h, v in enumerate(values)]
    # The mean is recomputed independently with exact rational arithmetic.
    mean = float(sum(Fraction(v) for v in values) / 24)
    assert f"Mean of the 24 samples: {json.dumps(mean)} μg/m³." in text
    assert first["full_text"] == build_alt_text("pm25_forecast_day", hazard._spec(hazard.PM25, bundle, False)["evidence"])
    assert descriptor["description"]["full_sha256"] == hashlib.sha256(first["full_text"].encode()).hexdigest()


def test_chart_plots_samples_at_true_hours_on_a_zero_based_linear_axis(prepared):
    bundle, value = prepared
    top, _ticks = hazard.pm25_adapter.forecast_axis(VARYING)
    with Image.open(BytesIO(value["png"])) as image:
        pixels = image.convert("RGB")
        for hour, sample in enumerate(VARYING):
            x = 232 + hour / 23 * (1136 - 232)
            y = 1066 - sample / top * (1066 - 676)
            assert pixels.getpixel((round(x), round(y))) == (0x38, 0xBD, 0xF8), hour
        # The zero baseline is drawn at the true axis origin across the plot.
        assert pixels.getpixel((700, 1066)) == (0xB6, 0xBD, 0xCB)


def test_delivery_description_keeps_every_mandatory_qualification(prepared):
    bundle, value = prepared
    text, packet = value["delivery_text"], window(bundle)
    for phrase in ("PM2.5 model forecast", "CAMS via Open-Meteo", "not station measurements", "Kathmandu, Nepal",
                   "grid point latitude 27.75, longitude 85.25", "Local day 2026-06-08 (Asia/Kathmandu)",
                   f"UTC {packet['valid_start']} to {packet['valid_end']}", f"retrieved {packet['retrieved_at']}",
                   "not a model run time", "μg/m³", "Straight lines join samples on a zero-based axis",
                   "No station reading, personal exposure, health category or model-run certainty"):
        assert phrase in text, phrase
    for absent in ("WHO", "AQI", "unhealthy", "hazardous", "observed", "27.72", "85.32"):
        assert absent not in text, absent
    # Request coordinates/time and retention detail stay in the expanded source details.
    assert "Requested location" in value["full_text"] and packet["requested_at"] in value["full_text"]
    assert text.count("μg/m³") == 2 and text.count("Local day") == 1 and text.count(packet["date"] + " (") == 1


@pytest.mark.parametrize("zone,offset,start,end", [
    ("Asia/Kathmandu", 20700, "2026-06-07T18:15:00Z", "2026-06-08T18:15:00Z"),
    ("Asia/Kolkata", 19800, "2026-06-07T18:30:00Z", "2026-06-08T18:30:00Z"),
    ("America/St_Johns", -9000, "2026-06-08T02:30:00Z", "2026-06-09T02:30:00Z"),
])
def test_quarter_and_half_hour_zones_use_validated_utc_bounds(zone, offset, start, end):
    bundle = pm25_bundle(timezone=zone, offset=offset)
    assert (window(bundle)["valid_start"], window(bundle)["valid_end"]) == (start, end)
    value = hazard.prepare_media(bundle)
    assert f"UTC {start} to {end}" in value["delivery_text"]
    begin, finish = (datetime.fromisoformat(t.replace("Z", "+00:00")) for t in (start, end))
    micro = timedelta(microseconds=1)
    requested = datetime(2026, 6, 8, 12, 0, 1, tzinfo=timezone.utc)
    for at, code in ((begin - micro, "media_forecast_not_started"), (begin, None),
                     (finish - micro, None), (finish, "media_forecast_ended")):
        if at < requested:
            code = "media_source_future"  # a later retrieval takes precedence over day bounds
        result = hazard.currentness(hazard.PM25, bundle, at)
        assert (result[0] if result else None) == code, (zone, at)


def test_24_hour_request_age_and_future_retrieval_boundaries():
    bundle = pm25_bundle(timezone="America/Los_Angeles", offset=-25200,
                         requested_at="2026-06-08T00:30:00Z", retrieved_at="2026-06-08T00:30:02.250000Z")
    requested = datetime(2026, 6, 8, 0, 30, tzinfo=timezone.utc)
    micro = timedelta(microseconds=1)
    cases = [(requested + timedelta(seconds=2, microseconds=249_999), "media_source_future"),
             (datetime(2026, 6, 8, 6, 59, 59, tzinfo=timezone.utc), "media_forecast_not_started"),
             (datetime(2026, 6, 8, 7, 0, tzinfo=timezone.utc), None),
             (requested + timedelta(hours=24), None),
             (requested + timedelta(hours=24) + micro, "media_forecast_request_old")]
    for at, code in cases:
        result = hazard.currentness(hazard.PM25, bundle, at)
        assert (result[0] if result else None) == code, at
    with pytest.raises(hazard.MediaWithheld):
        hazard.currentness(hazard.PM25, bundle, datetime(2026, 6, 8, 12, 0))  # naive clocks refuse


# ------------------------------------------------------------- refusals

def _drop_hour(b):
    w = window(b)
    w["hours"].pop()
    w["series"]["pm2_5"]["values"].pop()


MUTATIONS = {
    "missing_hour": _drop_hour,
    "missing_value": lambda b: window(b)["series"]["pm2_5"]["values"].__setitem__(5, None),
    "negative_value": lambda b: window(b)["series"]["pm2_5"]["values"].__setitem__(5, -1),
    "unit": lambda b: window(b)["series"]["pm2_5"].__setitem__("unit", "ug/m3"),
    "timezone": lambda b: window(b).__setitem__("timezone", "Asia/Kolkata"),
    "offset": lambda b: window(b).__setitem__("utc_offset_seconds", 19800),
    "dst_day": lambda b: window(b).update(date="2026-03-29", timezone="Europe/London", utc_offset_seconds=0),
    "source_product": lambda b: window(b).__setitem__("source_product", "open-meteo-cams-europe"),
    "grid": lambda b: window(b).__setitem__("grid_location", [27.5, 85.25]),
    "mean": lambda b: b["raw_signal_dump"].__setitem__("pm25_24h_mean", 150.0),
    "tier": lambda b: b["raw_signal_dump"].__setitem__("tier", 3),
    "station_corroborated": lambda b: b["raw_signal_dump"].__setitem__("evidence_grade", "model_corroborated_by_station"),
    "related_signal": lambda b: b.__setitem__("related_signals", [{"signal_kind": "air_quality_hazard", "event_id": "x"}]),
    "extended_story": lambda b: b.__setitem__("source_extension", {"invented": True}),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
@pytest.mark.parametrize("rehashed", [False, True])
def test_source_mutations_refuse_rather_than_render(prepared, name, rehashed):
    bundle = deepcopy(prepared[0])
    MUTATIONS[name](bundle)
    if rehashed:
        rehash(bundle)
    with pytest.raises(ValueError):
        gist_media.prepare_media(bundle)
    # The saved recipe never qualifies a changed source either.
    with pytest.raises(hazard.MediaWithheld):
        hazard.validate_descriptor(prepared[1]["descriptor"], bundle)


def test_dust_story_never_routes_to_the_pm25_family(prepared):
    bundle = deepcopy(prepared[0])
    bundle["signal_kind"] = "dust_event"
    assert hazard.family_for(bundle) is None
    with pytest.raises(ValueError):
        gist_media.prepare_media(bundle)


def test_unrenderable_labels_refuse_instead_of_shrinking_or_missing_glyphs():
    for city, code in (("北京", "media_label_glyph"), ("القاهرة", "media_label_script"),
                       ("Llanfair " * 8, "media_label_overflow")):
        with pytest.raises(hazard.MediaWithheld) as refused:
            hazard.prepare_media(pm25_bundle(city=city.strip()))
        assert refused.value.code == code, city


def test_mandatory_description_that_cannot_fit_refuses_and_never_truncates(prepared):
    # Full-precision retained values: the image renders, the mandatory projection does not fit.
    long_values = [160 + i + 0.12345678901234 for i in range(24)]
    with pytest.raises(hazard.MediaWithheld) as refused:
        hazard.prepare_media(pm25_bundle(long_values))
    assert refused.value.code == "media_description_too_long"
    evidence = hazard._spec(hazard.PM25, prepared[0], False)["evidence"]
    base = hazard.delivery_text(hazard.PM25, evidence)
    location = evidence["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]["requested_location"]
    spare = 1000 - len(base.encode())
    assert len(base) < len(base.encode()) <= 1000  # μ and ³ are two UTF-8 bytes each
    for city, code in (("é" * (spare // 2 + 1), "media_description_too_long"),   # scalars fit, bytes do not
                       ("x" * (spare + 1), "media_description_too_long"),          # one byte too many
                       ("x" * (1001 - len(base)), "media_description_too_long"),   # one scalar too many
                       ("\ud800", "media_description_unicode")):                    # malformed Unicode
        changed = deepcopy(evidence)
        changed["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]["requested_location"]["city"] = location["city"] + city
        with pytest.raises(hazard.MediaWithheld) as refused:
            hazard.delivery_text(hazard.PM25, changed)
        assert refused.value.code == code
    exact = deepcopy(evidence)
    exact["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]["requested_location"]["city"] = location["city"] + "x" * spare
    assert len(hazard.delivery_text(hazard.PM25, exact).encode()) == 1000
    scalars_ok = deepcopy(evidence)
    scalars_ok["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]["requested_location"]["city"] = location["city"] + "é" * (spare // 2)
    assert len(hazard.delivery_text(hazard.PM25, scalars_ok).encode()) <= 1000


def _rehash_description(d):
    raw = d["delivery_text"].encode()
    d.update(delivery_sha256=hashlib.sha256(raw).hexdigest(), delivery_scalars=len(d["delivery_text"]), delivery_bytes=len(raw))


TAMPER = {
    "png_digest": (lambda v: v["image"].__setitem__("png_sha256", "0" * 64), "send"),
    "png_bytes": (lambda v: v["image"].__setitem__("byte_count", v["image"]["byte_count"] + 1), "send"),
    "png_oversize": (lambda v: v["image"].__setitem__("byte_count", 750_001), "validate"),
    "delivery_rehashed": (lambda v: (v["description"].__setitem__("delivery_text", v["description"]["delivery_text"].replace("CAMS", "ECMWF")), _rehash_description(v["description"])), "send"),
    "delivery_unhashed": (lambda v: v["description"].__setitem__("delivery_text", v["description"]["delivery_text"] + " "), "validate"),
    "delivery_overlong": (lambda v: (v["description"].__setitem__("delivery_text", "x" * 1001), _rehash_description(v["description"])), "validate"),
    "full_description": (lambda v: v["description"].__setitem__("full_sha256", "0" * 64), "send"),
    "derivation": (lambda v: v["description"].__setitem__("derivation", "pm25_delivery_v2"), "validate"),
    "evidence": (lambda v: v["source"].__setitem__("evidence_sha256", "0" * 64), "send"),
    "window": (lambda v: v["source"].__setitem__("window_sha256", "0" * 64), "validate"),
    "valid_end": (lambda v: v["source"].__setitem__("valid_end", "2026-06-09T18:15:00Z"), "validate"),
    "helper_pin": (lambda v: v["renderer"]["files"].__setitem__("src/media/gist_hazard_media.py", "0" * 64), "validate"),
    "font_pin": (lambda v: v["renderer"]["files"].__setitem__("src/media/fonts/DejaVuSansMono.ttf", "0" * 64), "validate"),
    "adapter_pin": (lambda v: v["renderer"]["files"].__setitem__("src/media/air_quality_graphic_adapter.py", "0" * 64), "validate"),
    "pillow": (lambda v: v["renderer"].__setitem__("pillow", "12.3.0"), "validate"),
    "layout": (lambda v: v["renderer"].__setitem__("layout", "raqm"), "validate"),
    "template_version": (lambda v: v.__setitem__("template_version", "p31-pm25-forecast-2"), "validate"),
    "unknown_key": (lambda v: v.__setitem__("url", "https://example.invalid/x.png"), "validate"),
    "source_unknown_key": (lambda v: v["source"].__setitem__("path", "/tmp/x.png"), "validate"),
    "synthetic": (lambda v: v.__setitem__("synthetic", True), "validate"),
    "nonfinite": (lambda v: v["image"].__setitem__("byte_count", float("nan")), "validate"),
    "boolean_schema": (lambda v: v.__setitem__("schema_version", True), "validate"),
}


@pytest.mark.parametrize("name", sorted(TAMPER))
def test_altered_or_rehashed_recipe_refuses_review_or_send(prepared, name, monkeypatch):
    change, stage = TAMPER[name]
    draft = attached(prepared)
    change(draft["media_attachment"])
    bundle = draft["review_context"]["two_bot"]["bundle"]
    if stage == "validate":
        with pytest.raises(ValueError):
            gist_media.validate_descriptor(draft["media_attachment"], bundle)
        assert not revisions.review_is_current(draft)
        with pytest.raises(ValueError):
            revisions.record_joint_media_review(draft)
    else:
        assert gist_media.validate_descriptor(draft["media_attachment"], bundle)
        with pytest.raises(hazard.MediaWithheld) as refused:
            gist_media.media_for_draft(draft)
        assert refused.value.code == "media_render_mismatch"
        # Even a reviewed and approved tampered recipe reaches no upload.
        approve(draft)
        fake = install_fake_x(monkeypatch)
        state = state_for(draft)
        run_manual(monkeypatch, fake, state, draft)
        assert fake.calls == [] and draft["publish_outcome"] == "not_sent"
        assert draft["post_error"].startswith("Graphic needs a new preview and joint review")


def test_changed_helper_or_missing_font_requires_new_preview_and_review(prepared, monkeypatch):
    draft = approve(attached(prepared))
    real = hazard._resource
    monkeypatch.setattr(hazard, "_resource", lambda path: real(path) + (b"#changed" if path.endswith("gist_hazard_media.py") else b""))
    assert not revisions.review_is_current(draft) and not revisions.approval_is_current(draft, "manual")
    monkeypatch.setattr(hazard, "_resource", real)
    assert revisions.approval_is_current(draft, "manual")

    def missing(path):
        if path.endswith(".ttf"):
            raise FileNotFoundError("invented missing font asset")
        return real(path)
    monkeypatch.setattr(hazard, "_resource", missing)
    assert not revisions.review_is_current(draft)
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [] and draft["status"] == "approved"


# ------------------------------------------------------------- sender

def test_reviewed_pm25_image_reaches_fake_x_with_exact_bytes_and_delivery_text(prepared, monkeypatch):
    _bundle, value = prepared
    draft = approve(attached(prepared))
    original = deepcopy(draft)
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    fake.safety.assert_called_once_with(original["text"])
    assert fake.calls == [
        ("upload", value["png"], "hot10.png"),
        ("alt", "98765", value["delivery_text"]),
        ("create", original["text"], {"media_ids": ["98765"]}),
    ]
    assert hashlib.sha256(fake.calls[0][1]).hexdigest() == original["media_attachment"]["image"]["png_sha256"]
    assert hashlib.sha256(fake.calls[1][2].encode()).hexdigest() == original["media_attachment"]["description"]["delivery_sha256"]
    saved, expected = fake.persisted[0]
    assert expected == {"expected_draft": original, "expected_publish_ledger": None}
    assert saved["publish_ledger"][draft["event_id"]]["phase"] == "submitted"
    row = state["publish_ledger"][draft["event_id"]]
    assert row["phase"] == "confirmed" and row["tweet_id"] == draft["tweet_id"] == "invented-x-receipt"
    assert draft["status"] == "posted" and draft["media_attachment"] == original["media_attachment"]
    assert "png_base64" not in json.dumps(state) and "iVBORw0KGgo" not in json.dumps(state)
    # A repeated dispatch of the same request never resends.
    fake.posting.run_manual_tweet(state)
    assert len(fake.calls) == 3 and fake.posting.post_approved(draft, state) == "failed" and len(fake.calls) == 3


@pytest.mark.parametrize("at", ["2026-06-08T18:15:00Z", "2026-06-10T13:00:00Z", "2026-06-07T12:00:00Z"])
def test_expired_or_future_forecast_is_never_sent(prepared, at, monkeypatch):
    draft = approve(attached(prepared))
    before = deepcopy(draft)
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    with freeze_time(at):
        with pytest.raises(hazard.MediaWithheld):
            gist_media.media_for_draft(draft)
        run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == []
    assert draft["publish_outcome"] == "not_sent" and "Graphic" in draft["post_error"]
    for key in ("text", "media_attachment", "review_context", "content_revision"):
        assert draft[key] == before[key]
    # Source refusal during deterministic preflight creates no phantom attempt.
    assert state["publish_ledger"] == {} and "last_publish_attempt_at" not in draft
    assert fake.persisted == []


def test_forecast_expiring_during_rendering_is_caught_immediately_before_upload(prepared, monkeypatch):
    draft = approve(attached(prepared))
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    real = hazard.prepare_media
    with freeze_time("2026-06-08T18:14:59Z") as frozen:
        def slow_render(bundle, **options):
            value = real(bundle, **options)
            frozen.move_to("2026-06-08T18:15:00Z")  # the forecast day ends while rendering
            return value
        monkeypatch.setattr(hazard, "prepare_media", slow_render)
        run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == []
    assert draft["publish_outcome"] == "not_sent" and "no longer current" in draft["post_error"]


@pytest.mark.parametrize("failure", ["upload", "alt", "create", "empty_receipt"])
def test_lost_or_failed_transport_is_unknown_and_never_resent_or_downgraded(prepared, failure, monkeypatch):
    draft = approve(attached(prepared))
    fake = install_fake_x(monkeypatch)
    fake.failure = failure
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    first = list(fake.calls)
    assert first[0][0] == "upload" and draft["publish_outcome"] == "unknown"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "unknown"
    assert all(call[0] != "create" or call[2] == {"media_ids": ["98765"]} for call in first)
    fake.failure = None
    run_manual(monkeypatch, fake, state, draft)
    assert fake.posting.post_approved(draft, state) == "failed"
    assert fake.calls == first  # no resend, no text-only or Hot10 substitute


def test_two_selected_images_and_stale_approval_never_send(prepared, monkeypatch):
    bundle, value = prepared
    draft = draft_for(bundle, hot10_rows=[{"rank": 1, "invented": True}])
    approve(attach(draft, value["descriptor"], at="2026-06-08T12:45:00Z"))
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [] and draft["publish_outcome"] == "not_sent"
    assert "one explicitly selected image" in draft["post_error"]
    stale = approve(attached(prepared))
    revisions.invalidate_text(stale, PM25_TEXT + " Edited after approval.", at="2026-06-08T12:50:00Z")
    assert not revisions.approval_is_current(stale, "manual")
    assert stale["media_attachment"] == prepared[1]["descriptor"]
    assert fake.posting.post_approved(stale, state_for(stale)) == "failed" and fake.calls == []


def test_unavailable_quote_references_leave_the_reviewed_image_untouched(prepared):
    # Existing limit: the retained PM2.5 grid fact is a list, so quote references are
    # refused for these drafts. The refusal changes nothing, including joint review.
    draft = approve(attached(prepared))
    before = deepcopy(draft)
    items = [{"claim": {"start": 0, "end": 8, "text": PM25_TEXT[:8]}, "sources": [{"pointer": "/current_facts/0"}]}]
    with pytest.raises(ValueError, match="source facts are unavailable"):
        revisions.invalidate_text(draft, draft["text"], at="2026-06-08T12:55:00Z", operator_claim_references=items)
    assert draft == before and revisions.approval_is_current(draft, "manual")
