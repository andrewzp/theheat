"""W01: Hot10 as a sealed native Gist post-image family (pure, invented inputs).

The qualified bulletin is built by the real catalogue/normals loaders, the
Open-Meteo evidence adapter, ``hot10_contract.qualify`` and the production bundle
builder (tests/gist_hazard_helpers.py). Adapter, renderer, descriptor validation,
revision/approval rules, the delegated-review seam and the manual sender run their
production code; only Gist persistence, the final safety model and the X SDK
factories are fakes (tests/gist_media_helpers.py). Pillow-level checks are not
browser, native-device or hosted proof.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from freezegun import freeze_time
from PIL import Image
import pytest

from src.editorial import delegated_media_review as seam, hot10_contract, revisions
from src.media import gist_hazard_media as hazard, gist_media
from src.media.hot10_graphic_adapter import Hot10GraphicRefused
from tests.gist_hazard_helpers import (CLOCKS, HOT10_CAPTURE, HOT10_MIXED, HOT10_MIXED_CAPTURE, TEXTS, hot10_bundle,
                                      hot10_rows)
from tests.gist_media_helpers import approve, attach, install_fake_x, run_manual, saved_draft, state_for

CURRENT, EXPIRED = CLOCKS["hot10"]
MIXED, MIXED_CAPTURE = HOT10_MIXED, HOT10_MIXED_CAPTURE


@pytest.fixture(scope="module")
def bulletin():
    return hot10_bundle()


@pytest.fixture(scope="module")
def mixed():
    return hot10_bundle(MIXED, now=MIXED_CAPTURE, sampled=640)


def resealed(bundle, mutate):
    """A changed bulletin whose row fingerprints were recomputed (a forger's best attempt)."""
    value = deepcopy(bundle)
    mutate(value["raw_signal_dump"])
    for row in value["raw_signal_dump"]["cities"]:
        row["row_fingerprint"] = hot10_contract.row_fingerprint(row)
    return value


def hot10_draft(bundle, *, draft_id="invented-hot10", created_at=CURRENT):
    draft = saved_draft(bundle, draft_id=draft_id, draft_type="hot10", text=TEXTS["hot10"], created_at=created_at)
    draft["hot10_rows"] = hot10_rows(bundle)
    return draft


# ---------------------------------------------------------------- 01.1 source-bound adapter


def test_the_bulletin_selects_the_hot10_family_and_renders_all_ten_rows(bulletin):
    assert hazard.family_for(bulletin) == hazard.HOT10 and gist_media.HOT10 in gist_media.NATIVE_KINDS
    first, second = gist_media.prepare_media(deepcopy(bulletin)), gist_media.prepare_media(deepcopy(bulletin))
    assert first["png"] == second["png"] and first["descriptor"] == second["descriptor"]
    descriptor, raw = first["descriptor"], bulletin["raw_signal_dump"]
    assert descriptor["kind"] == hazard.HOT10 and descriptor["template"] == "hot10_departure_table"
    assert descriptor["source"] == {
        "bundle_sha256": revisions.fingerprint(bulletin), "evidence_sha256": descriptor["source"]["evidence_sha256"],
        "source_product": "openmeteo-best-match-forecast-daily-v1", "baseline_product": "meteostat-normals-point-v1",
        "rows_sha256": revisions.fingerprint([row["row_fingerprint"] for row in raw["cities"]]),
        "local_days": "2026-10-29"}
    assert set(descriptor["renderer"]["files"]) == set(hazard.FAMILIES[hazard.HOT10]["files"])
    assert gist_media.validate_descriptor(descriptor, bulletin) == descriptor
    with Image.open(BytesIO(first["png"])) as image:
        assert (image.format, image.mode, image.size) == ("PNG", "RGB", (1200, 1500))
    assert sha256(first["png"]).hexdigest() == descriptor["image"]["png_sha256"]
    text = first["delivery_text"]
    assert len(text) <= 1000 and len(text.encode()) <= 1000
    for row in raw["cities"]:  # Every ranked row, its normal and its local day reach the descriptions.
        assert f"{row['rank']} {row['city']}, {row['country']} {row['anomaly_c']:+.1f}" in text
        assert f"normal {row['normal_high_c']!r} °C (1991-2020)" in first["full_text"]
        assert f"local day {row['valid_date']} ({row['timezone']}" in first["full_text"]
    for phrase in ("12 qualified of 14 sampled cities", "local day 2026-10-29", "Warm bands above normal",
                   "Not observations, records or the world's hottest places"):
        assert phrase in text
    assert first["scope"] == hot10_contract.UNIVERSE_SCOPE


def _drop(raw):
    raw["cities"].pop()


def _duplicate(raw):
    raw["cities"][9] = {**deepcopy(raw["cities"][8]), "rank": 10}


def _swap(raw):
    raw["cities"][2], raw["cities"][3] = raw["cities"][3], raw["cities"][2]
    raw["cities"][2]["rank"], raw["cities"][3]["rank"] = 3, 4


def _unit(raw):
    raw["cities"][4]["forecast"]["unit"] = "F"


def _month(raw):
    raw["cities"][6]["baseline"]["month"] = 7


def _period(raw):
    raw["cities"][6]["baseline"]["period_start"] = "unknown"


def _days(raw):
    raw["universe"]["local_days"] = ["2026-10-29", "2026-10-30"]


def _bundle_unit(raw):
    raw["evidence"]["unit"] = "K"


@pytest.mark.parametrize(("mutate", "code"), [
    (_drop, "media_hot10_slate_size"), (_duplicate, "media_hot10_duplicate_location"),
    (_swap, "media_hot10_ranking_order"), (_unit, "media_hot10_unit_unsupported"),
    (_month, "media_hot10_normal_incompatible"), (_period, "media_hot10_normal_incompatible"),
    (_days, "media_hot10_universe"), (_bundle_unit, "media_hot10_unit_unsupported"),
], ids=["missing-row", "duplicate-row", "changed-ranking", "row-unit", "normal-month", "normal-period",
        "universe-days", "bulletin-unit"])
def test_unqualified_bulletins_refuse_through_the_contract_seam(bulletin, mutate, code):
    with pytest.raises(hazard.MediaWithheld) as refused:
        gist_media.prepare_media(resealed(bulletin, mutate))
    assert refused.value.code == code


def test_a_tampered_row_without_a_new_fingerprint_refuses(bulletin):
    tampered = deepcopy(bulletin)
    tampered["raw_signal_dump"]["cities"][2]["temp_high_c"] += 1
    with pytest.raises(hazard.MediaWithheld) as refused:
        gist_media.prepare_media(tampered)
    assert refused.value.code == "media_hot10_row_fingerprint"


def test_the_adapter_refuses_a_bundle_other_than_the_one_named(bulletin):
    from src.media.hot10_graphic_adapter import hot10_graphic_spec

    with pytest.raises(Hot10GraphicRefused) as refused:
        hot10_graphic_spec(bulletin, expected_bundle_sha256="0" * 64, synthetic=False)
    assert refused.value.code == "media_source_changed"


def test_every_ranked_row_keeps_its_own_currentness_at_approval_and_send(bulletin):
    """Root's every-row repair: a stale non-leader row holds the image, never just the leader."""
    now = datetime.fromisoformat(CURRENT.replace("Z", "+00:00"))
    assert gist_media.currentness(bulletin, now=now) is None
    # Rank 2 (Baghdad, UTC+3) captured just after its local midnight: same local day, 12h01m old at 09:31Z.
    assert bulletin["raw_signal_dump"]["cities"][1]["timezone"] == "Asia/Baghdad"
    stale = resealed(bulletin, lambda raw: raw["cities"][1].update(retrieved_at="2026-10-28T21:30:00Z"))
    later = HOT10_CAPTURE + timedelta(minutes=31)
    assert hot10_contract.validate_bundle(stale) == [] and hot10_contract.current_hold(bulletin, later) is None
    assert hot10_contract.current_hold(stale, later) == "hot10_capture_stale"
    assert gist_media.currentness(stale, now=later)[0] == "media_hot10_capture_stale"
    assert gist_media.currentness(bulletin, now=datetime.fromisoformat(EXPIRED.replace("Z", "+00:00")))[0] \
        == "media_hot10_local_day_over"
    assert gist_media.currentness(bulletin, now=HOT10_CAPTURE - timedelta(hours=10))[0] == "media_hot10_not_yet_valid"
    # The render stays deterministic for later inspection; only approval and send refuse.
    assert gist_media.prepare_media(stale)["descriptor"]["kind"] == hazard.HOT10


# ---------------------------------------------------------------- 01.5 readable retained graphic


def test_long_names_both_signs_and_mixed_local_days_stay_legible_and_described(mixed):
    prepared = gist_media.prepare_media(mixed)
    raw, text = mixed["raw_signal_dump"], prepared["delivery_text"]
    assert raw["universe"]["local_days"] == ["2026-10-29", "2026-10-30"]
    assert prepared["descriptor"]["source"]["local_days"] == "2026-10-29,2026-10-30"
    assert len(text) <= 1000 and len(text.encode()) <= 1000 and "local days 2026-10-29, 2026-10-30" in text
    for row in raw["cities"]:
        day = datetime.fromisoformat(row["valid_date"])
        signed = f"{row['anomaly_c']:+.1f}"
        assert f"{row['rank']} {row['city']}, {row['country']} {signed} ({day:%b} {day.day})" in text
    assert any(row["anomaly_c"] < 0 for row in raw["cities"]) and any(row["anomaly_c"] > 0 for row in raw["cities"])
    with Image.open(BytesIO(prepared["png"])) as image:
        rgb = image.convert("RGB")
        warm, cool = (0x7C, 0x2D, 0x12), (0x1E, 0x3A, 0x8A)
        assert rgb.getpixel((1120, 230)) == warm  # Leader band reaches the right edge of the common scale.
        assert rgb.getpixel((140, 1250)) == cool  # Most negative band reaches the left edge.
        assert rgb.getpixel((80, 1350)) == warm and rgb.getpixel((490, 1350)) == cool  # Text legend swatches.


def test_an_unreadable_name_refuses_the_image_rather_than_eliding_it(bulletin):
    long_name = resealed(bulletin, lambda raw: raw["cities"][3].update(city="Invented Extraordinarily Long Municipality"))
    with pytest.raises(hazard.MediaWithheld) as refused:
        gist_media.prepare_media(long_name)
    assert refused.value.code in {"media_label_overflow", "media_label_overlap"}


def test_the_ten_longest_catalogue_names_still_fit_the_description_bound():
    rows = [("Santiago de los Caballeros", "America/Santo_Domingo", 12.4), ("Lubumbashi", "Africa/Lubumbashi", 11.0),
            ("Mbuji-Mayi", "Africa/Lubumbashi", 9.9), ("Kisangani", "Africa/Lubumbashi", 8.1),
            ("Kananga", "Africa/Lubumbashi", 3.3), ("Kolwezi", "Africa/Lubumbashi", 0.5),
            ("Bukavu", "Africa/Lubumbashi", -1.2), ("Likasi", "Africa/Lubumbashi", -7.7),
            ("Santo Domingo Oeste", "America/Santo_Domingo", -10.1), ("Santo Domingo Este", "America/Santo_Domingo", -12.9)]
    prepared = gist_media.prepare_media(hot10_bundle(rows, now=datetime(2026, 10, 29, 23, 30, tzinfo=UTC), sampled=2000))
    assert len(prepared["delivery_text"]) <= 1000 and len(prepared["delivery_text"].encode()) <= 1000


# ---------------------------------------------------------------- 01.4 joint review, sender, automatic text-only


@pytest.fixture
def attached(bulletin):
    with freeze_time(CURRENT):
        prepared = gist_media.prepare_media(bulletin)
        draft = hot10_draft(bulletin)
        attach(draft, prepared["descriptor"], at=CURRENT)
    return draft, prepared


def test_human_joint_review_then_manual_post_sends_the_exact_png_and_alt_once(attached, monkeypatch):
    draft, prepared = attached
    with freeze_time(CURRENT):
        assert revisions.project_draft(draft)["review_status"] == "media_review_required"
        with pytest.raises(ValueError, match="Joint media review"):
            revisions.record_human_review(draft)
        approve(draft)
        with pytest.raises(ValueError):
            revisions.authorize_draft(draft, "auto")  # A reviewed image never gains automatic authority.
        fake = install_fake_x(monkeypatch)
        state = state_for(draft)
        run_manual(monkeypatch, fake, state, draft)
        assert fake.calls == [("upload", prepared["png"], "hot10.png"), ("alt", "98765", prepared["delivery_text"]),
                              ("create", TEXTS["hot10"], {"media_ids": ["98765"]})]
        assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed" and draft["status"] == "posted"
        assert draft["hot10_rows"] and draft["media_attachment"] == prepared["descriptor"]
        fake.posting.run_manual_tweet(state)  # A repeated dispatch never uploads or creates again.
    assert len(fake.calls) == 3


@pytest.mark.parametrize("failure", ["upload", "alt", "create"])
def test_a_lost_upload_alt_or_create_acknowledgement_stays_unknown_and_never_resends(attached, monkeypatch, failure):
    draft, _prepared = attached
    with freeze_time(CURRENT):
        approve(draft)
        fake = install_fake_x(monkeypatch)
        fake.failure = failure
        state = state_for(draft)
        run_manual(monkeypatch, fake, state, draft)
        first = list(fake.calls)
        fake.failure = None
        run_manual(monkeypatch, fake, state, draft)
    assert draft["publish_outcome"] == "unknown" and fake.calls == first
    assert sum(1 for call in fake.calls if call[0] == "upload") == 1


def test_approval_and_send_refuse_once_any_ranked_local_day_ends(attached, monkeypatch):
    draft, _prepared = attached
    with freeze_time(CURRENT):
        approve(draft)
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    with freeze_time(EXPIRED):
        run_manual(monkeypatch, fake, state, draft)
    # The bulletin's own final boundary holds first; the image path never reaches upload.
    assert fake.calls == [] and "hot10_local_day_over" in draft["post_error"] and state["publish_ledger"] == {}


def test_a_second_image_beside_a_non_hot10_attachment_is_still_refused(attached, monkeypatch):
    """The legacy rows exemption is exactly the Hot10 family; any other attachment keeps the one-image rule."""
    from tests.gist_hazard_helpers import family_bundle

    draft, _prepared = attached
    pm25 = family_bundle("pm25")
    with freeze_time(CLOCKS["pm25"][0]):
        other = saved_draft(pm25, draft_id="invented-pm25-with-rows", draft_type="air_quality_hazard",
                            text=TEXTS["pm25"], created_at=CLOCKS["pm25"][0])
        attach(other, gist_media.prepare_media(pm25)["descriptor"], at=CLOCKS["pm25"][0])
        other["hot10_rows"] = draft["hot10_rows"]
        with pytest.raises(hazard.MediaWithheld, match="only one explicitly selected image"):
            gist_media.media_for_draft(other)


def test_automatic_sends_stay_text_only_even_with_the_legacy_card_enabled(bulletin, monkeypatch):
    from src.orchestrator import posting

    monkeypatch.setenv("THEHEAT_HOT10_CARD_ENABLED", "1")
    draft = hot10_draft(bulletin)
    draft["approval_binding"] = {"mode": "auto"}
    assert posting._hot10_media_for_draft(draft) == (None, None)


def _retained(tmp_path: Path, draft: dict) -> tuple[Path, Path]:
    authorization = {"schema": seam.AUTHORIZATION_SCHEMA, "scope": "one_manual_post", "draft_id": draft["id"],
                     "granted_by": "andrew", "reviewer": "codex"}
    auth_path, receipt_path = tmp_path / "authorization.json", tmp_path / "receipt.json"
    auth_path.write_text(json.dumps(authorization, sort_keys=True))
    receipt = seam.expected_receipt(draft, authorization_sha256=sha256(auth_path.read_bytes()).hexdigest())
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    return auth_path, receipt_path


def test_trusted_delegated_review_covers_the_exact_hot10_identities_and_sends_once(attached, tmp_path, monkeypatch):
    draft, prepared = attached
    auth_path, receipt_path = _retained(tmp_path, draft)
    receipt = json.loads(receipt_path.read_text())
    assert receipt["png_sha256"] == prepared["descriptor"]["image"]["png_sha256"]
    assert receipt["alt_sha256"] == sha256(prepared["delivery_text"].encode()).hexdigest()
    assert receipt["source_sha256"] == revisions.fingerprint(draft["review_context"]["two_bot"]["bundle"])
    with freeze_time(CURRENT):
        seam.record_verified(draft, authorization_path=auth_path, receipt_path=receipt_path)
        assert draft["review_binding"]["kind"] == "delegated_media"
        with pytest.raises(ValueError, match="model review"):
            revisions.authorize_draft(draft, "auto")
        revisions.authorize_draft(draft, "manual", "invented-delegated-hot10")
        draft.update(status="approved", approval_mode="manual", publish_intent_id="invented-delegated-hot10")
        fake = install_fake_x(monkeypatch)
        state = state_for(draft)
        run_manual(monkeypatch, fake, state, draft)
    assert [call[0] for call in fake.calls] == ["upload", "alt", "create"] and fake.calls[0][1] == prepared["png"]


@pytest.mark.parametrize("change", ["text", "row", "graphic", "source"])
def test_any_hot10_change_revokes_joint_review_and_keeps_the_previous_snapshot(attached, bulletin, change):
    draft, prepared = attached
    with freeze_time(CURRENT):
        approve(draft)
        assert revisions.approval_is_current(draft, "manual")
        if change == "text":
            revisions.invalidate_text(draft, TEXTS["hot10"] + " Revised.")
        elif change == "row":
            draft["review_context"]["two_bot"]["bundle"] = resealed(
                bulletin, lambda raw: raw["cities"][5].update(city="Invented Changed Place"))
        elif change == "graphic":
            replacement = deepcopy(prepared["descriptor"])
            replacement["description"]["delivery_text"] += " "
            revisions.invalidate_media_attachment(draft, replacement, at=CURRENT)
        else:
            replaced = hot10_bundle(now=HOT10_CAPTURE + timedelta(minutes=30))
            draft["review_context"]["two_bot"]["bundle"] = replaced
        assert not revisions.review_is_current(draft) and not revisions.approval_is_current(draft, "manual")
        if change in ("text", "graphic"):
            previous = draft["revision_history"][-1]
            assert previous["media_attachment"] == prepared["descriptor"] and previous["text"] == TEXTS["hot10"]
            assert previous["review_binding"]["kind"] == "human_media"


# ---------------------------------------------------------------- 01.6 delivered snapshot inspection


def _delivered_request(draft, **extra):
    return {"draft_id": draft["id"], "format": "png", "delivered": True,
            "expected_revision": {**revisions.draft_identity(draft), "decision_revision": revisions.decision_revision(draft)},
            "expected_policy_source_sha256": "a" * 64, "expected_preview_runtime_sha256": "b" * 64, **extra}


def _inspect(state, request):
    from src.dashboard_preview.preview import build_preview
    from src.dashboard_preview.reader import Budget

    return json.loads(build_preview(request, policy_sha="a" * 64, runtime_sha="b" * 64, read_state=lambda: state,
                                    budget=Budget()))


def test_a_delivered_post_rebuilds_its_exact_png_text_and_alt_after_the_current_draft_changes(bulletin):
    import base64

    from tests.gist_hazard_helpers import HOT10_DELIVERED_TEXT, delivered_hot10_draft, saved_state

    state = saved_state("hot10")
    draft, calls = delivered_hot10_draft(state)
    sent_png, sent_alt = calls[0][1], calls[1][2]
    first = _inspect(state, _delivered_request(draft))
    assert first["schema_version"] == 6 and first["delivered"]["text"] == HOT10_DELIVERED_TEXT
    assert base64.b64decode(first["png_base64"]) == sent_png and first["delivery_text"] == sent_alt
    assert first["delivered"]["tweet_id"] == "invented-x-receipt-invented-hot10-delivered"
    assert first["publication_approved"] is False and first["attachment"] is False
    # The current draft then changes (text and a replacement image); the receipt still names the delivered revision.
    with freeze_time(CURRENT):
        revisions.invalidate_text(draft, "Invented later revision that was never sent.")
        replacement = gist_media.prepare_media(hot10_bundle(now=HOT10_CAPTURE))["descriptor"]
        draft["review_context"]["two_bot"]["bundle"] = hot10_bundle(now=HOT10_CAPTURE)
        revisions.invalidate_media_attachment(draft, replacement, at=CURRENT)
    assert draft["status"] == "pending" and draft["media_attachment"] == replacement
    later = _inspect(state, _delivered_request(draft))
    assert base64.b64decode(later["png_base64"]) == sent_png and later["delivery_text"] == sent_alt
    assert later["delivered"]["text"] == HOT10_DELIVERED_TEXT and later["media_descriptor"] != replacement


def test_delivered_inspection_refuses_unconfirmed_changed_or_rebuilt_differently(monkeypatch):
    from src.dashboard_preview.errors import PreviewError
    from tests.gist_hazard_helpers import delivered_hot10_draft, saved_state

    state = saved_state("hot10")
    draft, _calls = delivered_hot10_draft(state)
    pending = state["drafts"][0]
    with pytest.raises(PreviewError) as refused:  # A draft with no delivery receipt is not inspectable here.
        _inspect(state, _delivered_request(pending))
    assert refused.value.code == "draft_unavailable"
    for bad in ({"delivered": False}, {"delivered": True, "retained_input_sha256": "c" * 64}):
        with pytest.raises(PreviewError) as refused:
            _inspect(state, {**_delivered_request(draft), **bad})
        assert refused.value.code == "bad_request"
    unknown = deepcopy(state)
    unknown["publish_ledger"][draft["event_id"]].update(phase="unknown", tweet_id=None)
    with pytest.raises(PreviewError) as refused:
        _inspect(unknown, _delivered_request(draft))
    assert refused.value.code == "draft_unavailable"
    original = hazard.renderer_identity
    monkeypatch.setattr(hazard, "renderer_identity", lambda kind: {**original(kind), "version": "gist-hazard-png-3"})
    with pytest.raises(PreviewError) as refused:
        _inspect(state, _delivered_request(draft))
    assert (refused.value.code, refused.value.hold) == ("media_hold", "media_renderer_changed")
