"""W10.3–10.5: store-backed image admission, cross-reader identity and restore planning (invented).

Real consumers: the deployed preview handler function ``build_preview`` (admission and the
delivered-history reader), the sender's reader ``gist_media.media_for_draft`` and the
operator CLI ``scripts/retain_gist_media.py`` in a fresh process. Invented SQLite stores;
sockets trapped; nothing is fetched, uploaded or published.
"""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from freezegun import freeze_time
import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial import revisions
from src.media import gist_assets, gist_media, gist_media_export as portable, gist_published_media as published
from src.media.gist_hazard_media import MediaWithheld
from tests import gist_published_helpers as ph
from tests.gist_store_helpers import CLOCKS, retain, saved_state

ROOT = Path(__file__).resolve().parents[2]
STORE_FAMILIES = ("crw", "radar", "cone")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*_args, **_kwargs):
        raise AssertionError("external connection trapped")
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "connect_ex", refused)
    monkeypatch.setattr(socket, "getaddrinfo", refused)
    monkeypatch.delenv(gist_assets.ENV, raising=False)


def store_at(tmp_path, name="media.sqlite3"):
    return gist_assets.SQLiteMediaStore(tmp_path / name)


def request_for(draft, **extra):
    return {"draft_id": draft["id"], "format": "png", "expected_policy_source_sha256": "a" * 64,
            "expected_preview_runtime_sha256": "b" * 64,
            "expected_revision": {**revisions.draft_identity(draft), "decision_revision": revisions.decision_revision(draft)},
            **extra}


def preview(state, store, at, **extra):
    with freeze_time(at):
        return json.loads(build_preview(request_for(state["drafts"][0], **extra), policy_sha="a" * 64, runtime_sha="b" * 64,
                                        read_state=lambda: state, budget=Budget(), store=store))


def held(state, store, at, **extra):
    with freeze_time(at), pytest.raises(PreviewError) as refused:
        build_preview(request_for(state["drafts"][0], **extra), policy_sha="a" * 64, runtime_sha="b" * 64,
                      read_state=lambda: state, budget=Budget(), store=store)
    return refused.value


# ------------------------------------------------------------------ 10.3 admission


@pytest.mark.parametrize("family", ["radar", "cone"])
@pytest.mark.parametrize("typed", ["https://www.nhc.noaa.gov/storm_graphics/AT05/AL052026_5day_cone_with_line_and_wind.png",
                                   "/private/invented/cone.png", "AL052026 advisory 12", "A" * 64])
def test_a_url_path_or_name_is_refused_before_any_store_read(family, typed, tmp_path):
    store = store_at(tmp_path)
    retain(family, store)
    state = saved_state(family)
    refused = held(state, store, CLOCKS[family][0], retained_input_sha256=typed)
    assert refused.code == "bad_request"


def _without_reuse_reference(store, tmp_path):
    """A cone manifest written straight into a store (bypassing retention) that lacks its reuse reference."""
    doc, raw, refs, receipt = ph.cone_inputs()
    scratch = store_at(tmp_path, "scratch.sqlite3")
    good = published.retain(scratch, "nhc_track_cone_v1", doc, raw, refs, receipt)
    manifest = gist_assets.get_document(scratch, good, limit=published.MAX_MANIFEST_BYTES)
    del manifest["document"]["references"]["reuse"]
    derivative = scratch.get(manifest["derivative"]["sha256"], limit=manifest["derivative"]["byte_count"])
    bad = gist_assets.encode_document(manifest)
    store.put_many([raw, derivative, receipt, refs["product"], bad])
    return portable._sha(bad)


def test_missing_rights_changed_bytes_and_claim_misalignment_hold_at_the_preview_handler(tmp_path):
    store = store_at(tmp_path)
    state, at = saved_state("cone"), CLOCKS["cone"][0]
    missing_rights = _without_reuse_reference(store, tmp_path)
    refused = held(state, store, at, retained_input_sha256=missing_rights)
    assert (refused.code, refused.hold) == ("media_hold", "media_asset_invalid")
    # A cone retained for a different advisory or storm never aligns with this draft's claim.
    for other in (ph.cone_inputs(advisory="13"), ph.cone_inputs(storm_id="AL062026")):
        doc, raw, refs, receipt = other
        try:
            sha = published.retain(store, "nhc_track_cone_v1", doc, raw, refs, receipt)
        except MediaWithheld as exc:  # Retention itself may already refuse the inconsistent input.
            assert exc.code == "media_asset_invalid"
            continue
        refused = held(state, store, at, retained_input_sha256=sha)
        assert refused.hold in ("media_context_mismatch", "media_asset_invalid")
    # A radar frame selected for the cone draft is another product: refused, not relabelled.
    radar_sha = retain("radar", store)
    assert held(state, store, at, retained_input_sha256=radar_sha).hold == "media_context_mismatch"
    # Changed bytes (one flipped byte in every stored copy of the original) hold as changed.
    good = retain("cone", store)
    assert preview(state, store, at, retained_input_sha256=good)["schema_version"] == 5
    _, raw, _, _ = ph.cone_inputs()
    data = store.path.read_bytes()
    marker = raw[:64]
    store.path.write_bytes(data.replace(marker, marker[:40] + bytes([marker[40] ^ 1]) + marker[41:]))
    assert held(state, store, at, retained_input_sha256=good).hold == "media_asset_changed"


# ------------------------------------------------------------------ 10.4 one identity across readers


def delivered_state(family, store):
    """Preview -> attachment -> confirmed receipt, then the current draft moves on (edit + removal)."""
    retained = retain(family, store)
    state = saved_state(family)
    first = preview(state, store, CLOCKS[family][0], retained_input_sha256=retained)
    draft = state["drafts"][0]
    revisions.invalidate_media_attachment(draft, first["media_descriptor"], at=CLOCKS[family][0])
    identity = revisions.draft_identity(draft)
    state["publish_ledger"] = {draft["event_id"]: {**identity, "text": draft["text"], "intent_id": "invented-intent",
                                                   "tweet_id": f"invented-x-{family}", "phase": "confirmed",
                                                   "at": CLOCKS[family][0], "confirmed_at": CLOCKS[family][0]}}
    delivered = deepcopy(draft)
    revisions.invalidate_text(draft, draft["text"] + " Later correction.", at=CLOCKS[family][1])
    revisions.invalidate_media_attachment(draft, None, at=CLOCKS[family][1])
    draft["status"] = "posted"
    return state, delivered, first


@pytest.mark.parametrize("family", STORE_FAMILIES)
def test_preview_sender_and_history_readers_share_one_immutable_identity(family, tmp_path):
    store = store_at(tmp_path)
    state, delivered, first = delivered_state(family, store)
    # History reader: after the source window, edit and image removal, the receipt-named revision rebuilds exactly.
    history = preview(state, store, "2027-01-01T00:00:00Z", delivered=True)
    assert history["schema_version"] == 6 and "posting_window" not in history
    assert history["media_descriptor"] == first["media_descriptor"] == delivered["media_attachment"]
    assert history["png_base64"] == first["png_base64"] and history["delivery_text"] == first["delivery_text"]
    assert history["delivered"] == {"tweet_id": f"invented-x-{family}", "text": delivered["text"],
                                    "content_revision": delivered["content_revision"], "confirmed_at": CLOCKS[family][0]}
    if family != "crw":
        assert history["original_base64"] == first["original_base64"]
    # Sender reader: the same reviewed identity yields the same bytes and description.
    png, description = gist_media.media_for_draft(delivered, store=store, now=gist_media_now(family))[:2]
    assert base64.b64encode(png).decode("ascii") == history["png_base64"] and description == history["delivery_text"]


def gist_media_now(family):
    from datetime import datetime
    return datetime.fromisoformat(CLOCKS[family][0].replace("Z", "+00:00"))


@pytest.mark.parametrize("family", STORE_FAMILIES)
def test_history_holds_name_the_missing_store_or_artifact_and_never_substitute(family, tmp_path):
    store = store_at(tmp_path)
    state, _, _ = delivered_state(family, store)
    assert held(state, None, "2027-01-01T00:00:00Z", delivered=True).hold == "media_store_unavailable"
    empty = store_at(tmp_path, "empty.sqlite3")
    empty.put_many([b"Invented unrelated retained blob."])  # A real, reachable store without this artifact.
    hold = held(state, empty, "2027-01-01T00:00:00Z", delivered=True).hold
    assert hold == ("media_source_packet_missing" if family == "crw" else "media_original_missing")
    # A different retained input in the store is never used for the delivered history.
    other = store_at(tmp_path, "other.sqlite3")
    if family == "cone":
        doc, raw, refs, receipt = ph.cone_inputs(legend=["Invented other legend"])
        published.retain(other, "nhc_track_cone_v1", doc, raw, refs, receipt)
        assert held(state, other, "2027-01-01T00:00:00Z", delivered=True).hold == "media_original_missing"


# ------------------------------------------------------------------ 10.5 restore plan through consumers


def planned_state(store):
    cone_sha, radar_sha = retain("cone", store), retain("radar", store)
    cone = saved_state("cone")
    with freeze_time(CLOCKS["cone"][0]):
        cone_preview = json.loads(build_preview(request_for(cone["drafts"][0], retained_input_sha256=cone_sha),
                                                policy_sha="a" * 64, runtime_sha="b" * 64, read_state=lambda: cone,
                                                budget=Budget(), store=store))
    radar = saved_state("radar")
    with freeze_time(CLOCKS["radar"][0]):
        radar_preview = json.loads(build_preview(request_for(radar["drafts"][0], retained_input_sha256=radar_sha),
                                                 policy_sha="a" * 64, runtime_sha="b" * 64, read_state=lambda: radar,
                                                 budget=Budget(), store=store))
    cone_draft, radar_draft = cone["drafts"][0], radar["drafts"][0]
    revisions.invalidate_media_attachment(cone_draft, cone_preview["media_descriptor"], at=CLOCKS["cone"][0])
    cone_draft["media_review_binding"] = {"invented": "joint review fixture"}
    revisions.invalidate_media_attachment(radar_draft, radar_preview["media_descriptor"], at=CLOCKS["radar"][0])
    radar_draft["publish_outcome"] = "unknown"
    crw = saved_state("crw")["drafts"][0]
    crw["media_attachment"] = {"kind": gist_media.CRW, "source": {"packet_artifact_sha256": "c" * 64}}
    state = {"drafts": [cone_draft, radar_draft, crw],
             "publish_ledger": {radar_draft["event_id"]: {"phase": "unknown", "tweet_id": None}}}
    return state, cone_sha, radar_sha


def test_plan_names_needed_items_reasons_and_holds_then_restore_consumers_hold_before_upload(tmp_path):
    store = store_at(tmp_path)
    state, cone_sha, radar_sha = planned_state(store)
    plan = portable.plan(store, state)
    by_sha = {row["sha256"]: row for row in plan["items"]}
    assert by_sha[cone_sha]["status"] == "present" and by_sha[cone_sha]["drafts"][0]["reasons"] == ["attached", "current_review"]
    assert by_sha[radar_sha]["drafts"][0]["reasons"] == ["attached", "unresolved_delivery"]
    assert (by_sha["c" * 64]["status"], by_sha["c" * 64]["hold"]) == ("held", "media_source_packet_missing")
    assert plan["held"] == 1 and plan["publication_approved"] is False
    assert sorted(plan["export_batches"][0]) == sorted(["--manifest", cone_sha, "--manifest", radar_sha])
    # Export only the cone, restore into a new store: the plan and both consumers hold the radar item.
    target = tmp_path / "export"
    portable.export(store, [("published", cone_sha)], str(target))
    restored = store_at(tmp_path, "restored.sqlite3")
    portable.restore(restored, str(target))
    after = {row["sha256"]: row for row in portable.plan(restored, state)["items"]}
    assert after[cone_sha]["status"] == "present"
    assert (after[radar_sha]["status"], after[radar_sha]["hold"]) == ("held", "media_original_missing")
    radar_draft = state["drafts"][1]
    with pytest.raises(MediaWithheld) as sender:  # The sender's reader holds before any upload.
        gist_media.media_for_draft(radar_draft, store=restored, now=gist_media_now("radar"))
    assert sender.value.code == "media_original_missing"
    clean = deepcopy(radar_draft)
    clean.pop("publish_outcome")  # The preview handler already refuses an unresolved draft outright.
    radar_state = {"drafts": [clean]}
    assert held(radar_state, restored, CLOCKS["radar"][0], retained_input_sha256=radar_sha).hold == "media_original_missing"
    cone_png = gist_media.media_for_draft(state["drafts"][0], store=restored, now=gist_media_now("cone"))[0]
    assert cone_png == gist_media.media_for_draft(state["drafts"][0], store=store, now=gist_media_now("cone"))[0]


def test_plan_cli_reads_a_private_state_file_in_a_fresh_process(tmp_path):
    store = store_at(tmp_path)
    state, cone_sha, radar_sha = planned_state(store)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    os.chmod(state_file, 0o600)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
           "NO_PROXY": "*", "no_proxy": "*"}
    run = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/retain_gist_media.py"), "--store", f"sqlite:{store.path}",
                          "plan", "--state", str(state_file)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert {row["sha256"]: row["status"] for row in result["items"]} == {cone_sha: "present", radar_sha: "present", "c" * 64: "held"}
    os.chmod(state_file, 0o644)  # Not owner-only: refused before reading.
    refused = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/retain_gist_media.py"), "--store", f"sqlite:{store.path}",
                              "plan", "--state", str(state_file)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert refused.returncode != 0 and "private (0600)" in refused.stderr
