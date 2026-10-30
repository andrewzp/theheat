"""Milestone D: native Hot10/PM2.5 colour graphics, delegated native joint review and
manual native delivery to a fake X.

Pure Python bindings and refusals plus the real manual sender with the fake X SDK
factories (tests/gist_media_helpers.py). Renderer checks are Pillow-level; they are
not browser, native-device or hosted proof. Invented inputs only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from freezegun import freeze_time
from PIL import Image
import pytest

from src.editorial import delegated_media_review as seam
from src.editorial import revisions
from src.editorial.policy import current_editorial_policy
from src.media import gist_hazard_media as hazard, gist_media
from src.media.hot10_card import BulletinWithheld, hot10_bulletin_alt_text, render_hot10_bulletin
from tests import live_content_harness as h
from tests.gist_hazard_helpers import PM25_TEXT, SENDABLE_PM25, VARYING_PM25, pm25_bundle
from tests.gist_media_helpers import attach, install_fake_x, run_manual, saved_draft, state_for

ROOT = Path(__file__).resolve().parents[1]
CURRENT = "2026-06-08T13:00:00Z"
T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------- D1: source-bound colour graphics


def hot10_bundle(tmp_path) -> dict:
    from src.editorial import hot10_contract
    from src.two_bot.intern import build_hot10_bundle

    _cities, normals, temps = h.qualified_inputs(tmp_path, T0)
    result = hot10_contract.qualify(temps, normals, sampled=14, now=T0)
    return build_hot10_bundle(result["rows"], changes=[], event_id="hot10_2026-10-29",
                              universe=result["universe"]).to_dict()


def test_hot10_bulletin_is_a_deterministic_colour_card_from_the_retained_rows(tmp_path):
    bundle = hot10_bundle(tmp_path)
    first, second = render_hot10_bulletin(deepcopy(bundle)), render_hot10_bulletin(deepcopy(bundle))
    assert first == second and first.startswith(b"\x89PNG\r\n\x1a\n") and len(first) < 750_000
    with Image.open(BytesIO(first)) as image:
        assert (image.format, image.mode, image.size) == ("PNG", "RGB", (1200, 675))
        rgb = image.convert("RGB")
        assert rgb.getpixel((700, 112)) == (248, 113, 113)  # Leader's warm bar (above its normal).
        assert rgb.getpixel((50, 573)) == (248, 113, 113) and rgb.getpixel((350, 573)) == (96, 165, 250)  # Legend.


def test_hot10_description_is_complete_bounded_and_scoped(tmp_path):
    bundle = hot10_bundle(tmp_path)
    alt = hot10_bulletin_alt_text(bundle)
    assert len(alt) <= 1000 and len(alt.encode("utf-8")) <= 1000
    for row in bundle["raw_signal_dump"]["cities"]:
        assert f"{row['rank']}. {row['city']}, {row['country']} {row['anomaly_c']:+.1f}" in alt
    for phrase in ("12 qualified of 14 sampled cities", "local days 2026-10-29", "Warm bars are above normal",
                   "not observations, records or the world's hottest places", "Open-Meteo forecast"):
        assert phrase in alt


def test_changed_or_unreadable_bulletin_refuses_rather_than_truncating(tmp_path):
    from src.editorial.hot10_contract import row_fingerprint

    bundle = hot10_bundle(tmp_path)
    tampered = deepcopy(bundle)
    tampered["raw_signal_dump"]["cities"][2]["temp_high_c"] += 1
    with pytest.raises(BulletinWithheld, match="contract"):
        render_hot10_bulletin(tampered)
    long_name = deepcopy(bundle)
    row = long_name["raw_signal_dump"]["cities"][3]
    row["city"] = "Invented Extraordinarily Long Municipality Name"
    row["row_fingerprint"] = row_fingerprint(row)
    with pytest.raises(BulletinWithheld, match="readable width"):
        render_hot10_bulletin(long_name)


def test_legacy_card_never_attaches_to_an_automatic_send(tmp_path, monkeypatch):
    from src.orchestrator import posting

    monkeypatch.setenv("THEHEAT_HOT10_CARD_ENABLED", "1")
    bundle = hot10_bundle(tmp_path)
    draft: dict[str, Any] = {"hot10_rows": [{"rank": 1, "city": "Riyadh", "country": "Saudi Arabia",
                                             "anomaly_c": 9.2, "temp_high_c": 39.2}],
                             "review_context": {"two_bot": {"bundle": bundle}}}
    for mode in ("auto", None):
        draft["approval_binding"] = {"mode": mode} if mode else {}
        assert posting._hot10_media_for_draft(draft) == (None, None)
    draft["approval_binding"] = {"mode": "manual"}
    png, alt = posting._hot10_media_for_draft(draft)
    assert png == render_hot10_bulletin(bundle) and alt == hot10_bulletin_alt_text(bundle)


@freeze_time(CURRENT)
def test_pm25_native_card_keeps_its_legend_units_window_and_forecast_label():
    prepared = hazard.prepare_media(pm25_bundle(VARYING_PM25, **SENDABLE_PM25))
    descriptor, text = prepared["descriptor"], prepared["delivery_text"]
    assert descriptor["kind"] == hazard.PM25 and descriptor["image"]["width"] == 1200 and descriptor["image"]["height"] == 1500
    for phrase in ("model forecast", "μg/m³", "2026-06-08"):
        assert phrase in text
    assert descriptor["source"]["valid_date"] == "2026-06-08" and descriptor["source"]["timezone"] == "Asia/Kathmandu"


@pytest.mark.parametrize(("text", "held"), [
    ("Lahore's PM2.5 is forecast to average 250 µg/m³ today, per CAMS model data.", False),
    ("Lahore's PM2.5 is forecast to average 250 µg/m³ today; see the chart below.", True),
    ("Riyadh's forecast high runs 9.2°C above normal, the largest departure among 14 sampled cities (map).", True),
], ids=["text-only", "chart", "map"])
def test_text_only_automatic_copy_never_implies_an_absent_image(text, held):
    from src.editorial.automatic_text import IMPLIES_MEDIA, automatic_text_hold

    assert (automatic_text_hold(text) == IMPLIES_MEDIA) is held


# ---------------------------------------------------------------- D3: delegated native joint review


@pytest.fixture
def pm25_draft():
    with freeze_time(CURRENT):
        bundle = pm25_bundle(VARYING_PM25, **SENDABLE_PM25)
        prepared = hazard.prepare_media(bundle)
        draft = saved_draft(bundle, draft_id="invented-pm25-delegated", draft_type="air_quality_hazard",
                            text=PM25_TEXT, created_at="2026-06-08T12:30:00Z")
        attach(draft, prepared["descriptor"], at="2026-06-08T12:45:00Z")
        yield draft, prepared


def retained(tmp_path: Path, draft: dict, **receipt_changes) -> tuple[Path, Path]:
    authorization = {"schema": seam.AUTHORIZATION_SCHEMA, "scope": "one_manual_post", "draft_id": draft["id"],
                     "granted_by": "andrew", "reviewer": "codex"}
    auth_path, receipt_path = tmp_path / "authorization.json", tmp_path / "receipt.json"
    auth_path.write_text(json.dumps(authorization, sort_keys=True))
    receipt = seam.expected_receipt(draft, authorization_sha256=sha256(auth_path.read_bytes()).hexdigest())
    receipt.update(receipt_changes)
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    return auth_path, receipt_path


def test_trusted_seam_records_a_delegated_native_review_from_verified_retained_files(pm25_draft, tmp_path):
    draft, _prepared = pm25_draft
    auth_path, receipt_path = retained(tmp_path, draft)
    with freeze_time(CURRENT):
        seam.record_verified(draft, authorization_path=auth_path, receipt_path=receipt_path)
        binding = draft["review_binding"]
        assert binding["kind"] == "delegated_media" and binding["kind"] not in ("human", "human_media")
        assert binding["delegation"] == {"scope": "one_manual_post", "reviewer": "codex",
                                         "authorization_sha256": sha256(auth_path.read_bytes()).hexdigest(),
                                         "review_receipt_sha256": sha256(receipt_path.read_bytes()).hexdigest()}
        assert binding["media_sha256"] == revisions.fingerprint(draft["media_attachment"])
        assert revisions.review_is_current(draft)
        with pytest.raises(ValueError, match="model review"):
            revisions.authorize_draft(draft, "auto")  # Never automatic-image authority.
        revisions.authorize_draft(draft, "manual", "invented-delegated-intent")
        assert draft["approval_binding"]["review_binding_sha256"] == revisions.fingerprint(draft["review_binding"])


@pytest.mark.parametrize("change", [
    {"draft_id": "another-draft"}, {"text_sha256": "0" * 64}, {"media_sha256": "1" * 64}, {"alt_sha256": "2" * 64},
    {"source_sha256": "3" * 64}, {"policy_sha256": "4" * 64}, {"authorization_sha256": "5" * 64},
    {"decision": "approve_automatic"}, {"reviewer": "someone"},
], ids=lambda change: next(iter(change)))
def test_a_receipt_for_anything_else_records_nothing(pm25_draft, tmp_path, change):
    draft, _prepared = pm25_draft
    before = deepcopy(draft)
    auth_path, receipt_path = retained(tmp_path, draft, **change)
    with freeze_time(CURRENT), pytest.raises(ValueError, match="receipt"):
        seam.record_verified(draft, authorization_path=auth_path, receipt_path=receipt_path)
    assert draft == before


@pytest.mark.parametrize("authorization", [
    {"scope": "automatic"}, {"draft_id": "another-draft"}, {"granted_by": "browser"}, {"extra": True},
], ids=["scope", "draft", "grantor", "extra-field"])
def test_an_authorization_for_anything_else_records_nothing(pm25_draft, tmp_path, authorization):
    draft, _prepared = pm25_draft
    auth_path, receipt_path = retained(tmp_path, draft)
    value = {**json.loads(auth_path.read_text()), **authorization}
    auth_path.write_text(json.dumps(value))
    with freeze_time(CURRENT), pytest.raises(ValueError, match="Authorization"):
        seam.record_verified(draft, authorization_path=auth_path, receipt_path=receipt_path)
    assert "review_binding" not in draft or draft["review_binding"].get("kind") != "delegated_media"


def test_only_native_kinds_can_be_delegated():
    assert gist_media.NATIVE_KINDS == {gist_media.TEMPERATURE, *hazard.KINDS}
    assert gist_media.NATIVE_KINDS.isdisjoint(gist_media.STORE_KINDS)
    for kind in sorted(gist_media.STORE_KINDS):
        draft = {"text": PM25_TEXT, "media_attachment": {"kind": kind}}
        with pytest.raises(ValueError, match="human joint review"):
            revisions.record_delegated_joint_media_review(draft, authorization_sha256="a" * 64,
                                                          review_receipt_sha256="b" * 64)
    with pytest.raises(ValueError, match="native image"):
        revisions.record_delegated_joint_media_review({"text": PM25_TEXT}, authorization_sha256="a" * 64,
                                                      review_receipt_sha256="b" * 64)


def delegated(draft: dict, tmp_path: Path) -> dict:
    auth_path, receipt_path = retained(tmp_path, draft)
    with freeze_time(CURRENT):
        return seam.record_verified(draft, authorization_path=auth_path, receipt_path=receipt_path)


@pytest.mark.parametrize("revoke", [
    lambda d: revisions.invalidate_text(d, PM25_TEXT + " Edited."),
    lambda d: revisions.invalidate_media_attachment(d, None, at="2026-06-08T12:50:00Z"),
    lambda d: d["review_binding"]["delegation"].update(scope="many_posts"),
    lambda d: d["review_binding"].update(media_sha256="0" * 64),
    lambda d: d["review_context"]["two_bot"]["bundle"].update(when="2026-06-09"),
], ids=["text-edit", "image-removed", "scope", "image-binding", "source"])
def test_any_change_revokes_a_delegated_review(pm25_draft, tmp_path, revoke):
    draft, _prepared = pm25_draft
    delegated(draft, tmp_path)
    with freeze_time(CURRENT):
        assert revisions.review_is_current(draft)
        revoke(draft)
        assert not revisions.review_is_current(draft)


def test_python_and_javascript_agree_on_delegated_currentness(pm25_draft, tmp_path):
    node = os.environ.get("THEHEAT_TEST_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node is required for the JavaScript parity check")
    draft, _prepared = pm25_draft
    delegated(draft, tmp_path)
    cases = {"current": deepcopy(draft)}
    cases["scope"] = deepcopy(draft)
    cases["scope"]["review_binding"]["delegation"]["scope"] = "many_posts"
    cases["image"] = deepcopy(draft)
    cases["image"]["review_binding"]["media_sha256"] = "0" * 64
    cases["kind"] = deepcopy(draft)
    cases["kind"]["review_binding"]["kind"] = "delegated"
    policy = current_editorial_policy()
    with freeze_time(CURRENT):
        expected = {name: revisions.review_is_current(value) for name, value in cases.items()}
    payload = tmp_path / "cases.json"
    payload.write_text(json.dumps({"policy": policy, "cases": cases}))
    # Pin the JS media-currentness clock to the same invented instant as the Python check.
    script = ("import fs from 'node:fs'; import { reviewIsCurrent } from './lib/draft-revisions.js';"
              "const fixed = Date.parse(process.argv[2]); Date.now = () => fixed;"
              "const v = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));"
              "console.log(JSON.stringify(Object.fromEntries(Object.entries(v.cases).map(([k, d]) => [k, reviewIsCurrent(d, v.policy)]))))")
    run = subprocess.run([node, "--input-type=module", "-e", script, str(payload), CURRENT], cwd=ROOT / "dashboard",
                         env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TZ": "UTC"},
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert expected == {"current": True, "scope": False, "image": False, "kind": False}
    assert json.loads(run.stdout) == expected


# ---------------------------------------------------------------- D4: manual native delivery to a fake X


def approved(draft: dict, tmp_path: Path, intent: str = "invented-delegated-intent") -> dict:
    delegated(draft, tmp_path)
    with freeze_time(CURRENT):
        revisions.authorize_draft(draft, "manual", intent)
    draft.update(status="approved", approval_mode="manual", publish_intent_id=intent)
    return draft


def test_delegated_manual_post_sends_the_exact_reviewed_png_and_description_once(pm25_draft, tmp_path, monkeypatch):
    draft, prepared = pm25_draft
    approved(draft, tmp_path)
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    with freeze_time(CURRENT):
        run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [("upload", prepared["png"], "hot10.png"), ("alt", "98765", prepared["delivery_text"]),
                          ("create", PM25_TEXT, {"media_ids": ["98765"]})]
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed" and draft["status"] == "posted"
    assert draft["review_binding"]["kind"] == "delegated_media"
    with freeze_time(CURRENT):
        fake.posting.run_manual_tweet(state)  # A duplicate dispatch of the same intent never creates again.
    assert len(fake.calls) == 3


@pytest.mark.parametrize("failure", ["upload", "create"])
def test_a_lost_upload_or_create_stays_unknown_and_is_never_resent(pm25_draft, tmp_path, monkeypatch, failure):
    draft, _prepared = pm25_draft
    approved(draft, tmp_path)
    fake = install_fake_x(monkeypatch)
    fake.failure = failure
    state = state_for(draft)
    with freeze_time(CURRENT):
        run_manual(monkeypatch, fake, state, draft)
        first = list(fake.calls)
        fake.failure = None
        run_manual(monkeypatch, fake, state, draft)
    assert draft["publish_outcome"] == "unknown" and fake.calls == first


def test_changed_media_or_source_after_delegated_review_never_uploads(pm25_draft, tmp_path, monkeypatch):
    draft, _prepared = pm25_draft
    approved(draft, tmp_path)
    draft["review_context"]["two_bot"]["bundle"]["when"] = "2026-06-09"  # Retained source changed.
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    with freeze_time(CURRENT):
        run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [] and state["publish_ledger"] == {}
