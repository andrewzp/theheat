"""Collector → draft → preview association for the CRW packet reference.

Only {artifact_sha256, packet_sha256} rides in the real bundle. It survives the
queue, the existing one-sample generation/check path (offline model fixtures), the
Gist state encoding and reload, and becomes the only acceptable packet: any other
packet (even one with identical bytes but other acquisition-time assertions), a
malformed reference, a stale day or failed qualification refuses preview,
attachment, approval and sending. Raw CSV never enters prompts or Gist state.
"""
from copy import deepcopy
import json
from typing import Any, cast
from unittest.mock import Mock

import pytest

from src import state as state_module
from src.editorial.revisions import fingerprint
from src.media import gist_assets, gist_crw_media as crw
from src.media.gist_hazard_media import MediaWithheld
from src.state import DEFAULT_STATE
from src.two_bot import fact_check, pipeline
from src.two_bot.bundle_capture import MAX_BUNDLE_BYTES, capture_bundle
from src.two_bot.types import CriticResult, FactCheckResult, StoryBundle, WriterResult
from tests.gist_crw_helpers import collected_inputs, varied_inputs
from tests.gist_media_helpers import approve, attach

CLOCK = "2026-06-16T13:00:00Z"


class NoRead:
    """A store that must never be read: refusals happen before any store access."""

    def get(self, *_a, **_k):
        raise AssertionError("store read before the reference check")


@pytest.fixture
def collected(tmp_path):
    bundle, packet = collected_inputs()
    store = gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3")
    key = crw.retain_packet(store, packet)
    assert key == bundle["raw_signal_dump"]["retained_packet"]["artifact_sha256"]
    return bundle, packet, store, key


def test_reference_rides_generation_check_and_gist_reload_without_bytes(monkeypatch, collected):
    bundle, _packet, _store, key = collected
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "offline-fixture-no-provider-access")
    source = StoryBundle.from_dict(deepcopy(bundle)) if hasattr(StoryBundle, "from_dict") else StoryBundle(**deepcopy(bundle))
    writer = Mock(return_value=WriterResult(
        "Invented Caribbean satellite analysis runs about 3°C above its daily climatology.",
        None, "number", None, None, "Invented fixture"))
    monkeypatch.setattr(pipeline.writer, "write_tweet", writer)
    monkeypatch.setattr(pipeline, "run_safety_pipeline", lambda _t: (True, None))
    monkeypatch.setattr(fact_check, "fact_check", lambda *a: FactCheckResult(True, [], "Offline fixture"))
    monkeypatch.setattr(pipeline.critic, "critic_review", lambda *a, **k: CriticResult(True, None, "Offline fixture"))
    from tests.two_bot.conftest import _state_with_memory
    pipeline.generate_draft(source, cast(Any, _state_with_memory()))
    prompt = json.dumps([str(a) for a in writer.call_args.args] + [str(v) for v in writer.call_args.kwargs.values()])
    assert "time,latitude,longitude" not in prompt and "csv_utf8" not in prompt  # No raw CSV in the prompt.
    # The bundle (with its reference) stays within the original 32 KiB capture bound.
    captured = capture_bundle(source)  # Refuses (never truncates) above the bound.
    assert len(captured.serialized.encode()) <= MAX_BUNDLE_BYTES
    assert captured.payload()["raw_signal_dump"]["retained_packet"]["artifact_sha256"] == key
    draft = {"id": "invented-collected", "event_id": bundle["event_id"], "type": "regional_sst_anomaly",
             "status": "pending", "text": "Invented text.", "created_at": CLOCK,
             "review_context": {"two_bot": {"bundle": deepcopy(bundle)}}}
    saved = {**deepcopy(DEFAULT_STATE), "drafts": [draft]}
    reloaded = state_module._normalize_state(json.loads(json.dumps(state_module._normalize_state(saved),
                                                                   default=state_module.json_default)))
    again = reloaded["drafts"][0]["review_context"]["two_bot"]["bundle"]
    assert crw.packet_reference(again)["artifact_sha256"] == key and fingerprint(again) == fingerprint(bundle)
    assert "csv_utf8" not in json.dumps(reloaded) and "time,latitude" not in json.dumps(reloaded)


def test_only_the_collected_packet_is_accepted(collected):
    bundle, packet, store, key = collected
    prepared = crw.prepare_media(bundle, store, key)
    assert prepared["descriptor"]["source"]["packet_artifact_sha256"] == key
    # Same bytes, other acquisition-time assertions: valid alone, but not this draft's packet.
    other = {**packet, "metadata_retrieved_at": "2026-06-16T12:30:00Z", "csv_retrieved_at": "2026-06-16T12:45:00Z"}
    other_key = crw.retain_packet(store, other)
    assert other_key != key
    with pytest.raises(MediaWithheld) as refused:
        crw.prepare_media(bundle, NoRead(), other_key)
    assert refused.value.code == "media_source_packet_mismatch"
    # Without a reference (legacy/manual retention) that packet is still acceptable.
    legacy, _ = varied_inputs()
    assert crw.prepare_media(legacy, store, other_key)["descriptor"]["source"]["packet_artifact_sha256"] == other_key


@pytest.mark.parametrize("reference", [None, "x", {"schema_version": 2}, {"schema_version": 1, "artifact_sha256": "A" * 64,
                                                                           "packet_sha256": "b" * 64}])
def test_malformed_reference_holds_before_any_store_read(collected, reference):
    bundle, _packet, _store, key = collected
    broken = deepcopy(bundle)
    broken["raw_signal_dump"]["retained_packet"] = reference
    with pytest.raises(MediaWithheld) as held:
        crw.prepare_media(broken, NoRead(), key)
    assert held.value.code == "media_source_packet_invalid"


def test_attachment_approval_and_send_refuse_another_packet(collected):
    bundle, packet, store, key = collected
    descriptor = crw.prepare_media(bundle, store, key)["descriptor"]
    assert crw.validate_descriptor(descriptor, bundle) == descriptor
    other_key = crw.retain_packet(store, {**packet, "csv_retrieved_at": "2026-06-16T12:45:00Z"})
    swapped = deepcopy(descriptor)
    swapped["source"]["packet_artifact_sha256"] = other_key
    swapped["source"]["packet_sha256"] = fingerprint({**packet, "csv_retrieved_at": "2026-06-16T12:45:00Z"})
    with pytest.raises(MediaWithheld) as refused:
        crw.validate_descriptor(swapped, bundle)
    assert refused.value.code == "media_source_packet_mismatch"
    from src.editorial import revisions
    draft = {"id": "invented-collected", "event_id": bundle["event_id"], "type": "regional_sst_anomaly",
             "status": "pending", "text": "Invented text.", "created_at": CLOCK,
             "review_context": {"two_bot": {"bundle": deepcopy(bundle)}}}
    revisions.initialize_revision(draft)
    attach(draft, swapped, at=CLOCK)
    with pytest.raises(MediaWithheld) as unreviewed:
        approve(draft)  # The joint media review (and so approval) refuses first.
    assert unreviewed.value.code == "media_source_packet_mismatch"
    from datetime import datetime
    with pytest.raises(MediaWithheld) as unsent:
        crw.media_for_draft(draft, now=datetime.fromisoformat(CLOCK.replace("Z", "+00:00")), store=store)
    assert unsent.value.code == "media_source_packet_mismatch"


def test_stale_day_and_failed_qualification_still_refuse(collected):
    from datetime import datetime
    bundle, packet, store, key = collected
    draft = {"review_context": {"two_bot": {"bundle": bundle}}}
    assert crw.currentness(bundle, datetime.fromisoformat("2026-06-25T00:00:00+00:00"))[0] == "media_source_stale"
    with pytest.raises(MediaWithheld):
        crw.recheck_before_upload(draft, now=datetime.fromisoformat("2026-06-25T00:00:00+00:00"))
    changed = deepcopy(packet)
    changed["metadata_utf8"] = changed["metadata_utf8"].replace('"degree_C"', '"degree_F"')
    changed_key = crw.retain_packet(store, changed)
    tampered = deepcopy(bundle)
    tampered["raw_signal_dump"]["retained_packet"] = {"schema_version": 1, "artifact_sha256": changed_key,
                                                      "packet_sha256": fingerprint(changed)}
    with pytest.raises(MediaWithheld) as unqualified:
        crw.prepare_media(tampered, store, changed_key)
    assert unqualified.value.code == "media_source_unqualified"


def test_reference_is_part_of_the_reviewed_bundle_identity(collected):
    bundle, _packet, _store, _key = collected
    legacy, _ = varied_inputs()
    assert {k: v for k, v in bundle["raw_signal_dump"].items() if k != "retained_packet"} == legacy["raw_signal_dump"]
    assert fingerprint(bundle) != fingerprint(legacy)  # Changing the reference is a source change.


ASSOCIATION_ROUTE = r'''
import fs from "node:fs"; import { spawnSync } from "node:child_process"; import { pathToFileURL } from "node:url"
import React from "react"; import { renderToStaticMarkup } from "react-dom/server"
const [out, policyJSON, other] = process.argv.slice(1)
const manifest = JSON.parse(fs.readFileSync("lib/graphic-runtime-manifest.json", "utf8"))
// The checkout preview, returning named holds as their HTTP status and payload.
const RENDER = [
  "import json,sys,socket",
  "socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(AssertionError('external connection trapped'))",
  "from src.dashboard_preview.errors import PreviewError",
  "from src.dashboard_preview.preview import build_preview",
  "from src.dashboard_preview.reader import Budget",
  "v=json.load(sys.stdin); state=json.loads(v['raw_state'])",
  "try: print(json.dumps({'status':200,'body':json.loads(build_preview(v['request'],policy_sha=v['policy'],runtime_sha=v['runtime'],read_state=lambda:state,budget=Budget()))}))",
  "except PreviewError as e: print(json.dumps({'status':e.status,'body':e.payload()}))"].join("\n")
const render = (request, rawState) => {
  const run = spawnSync(process.env.THEHEAT_TEST_PYTHON, ["-c", RENDER], { cwd: "..", encoding: "utf8", timeout: 120000,
    input: JSON.stringify({ request, raw_state: rawState, policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 }),
    env: { PATH: process.env.PATH, HOME: process.env.HOME, LC_ALL: "C", LANG: "C", NETRC: "/dev/null", NO_PROXY: "*", no_proxy: "*",
      PYTHON_DOTENV_DISABLED: "1", THEHEAT_MEDIA_STORE: process.env.THEHEAT_MEDIA_STORE }, maxBuffer: 32 * 1024 * 1024 })
  if (run.status !== 0) throw new Error(run.stderr.slice(-4000))
  return JSON.parse(run.stdout)
}
const lib = name => pathToFileURL(`${process.cwd()}/${name}`).href
const { withGist, body, attestationsFor } = await import(lib("tests/helpers/gist-hazard-harness.js"))
const { retainedPacketReference } = await import(lib("lib/graphic-preview.js"))
const { validGistMedia } = await import(lib("lib/gist-media.js"))
const { GraphicPreview } = await import(lib("app/components/GraphicPreview.js"))
await withGist("crw_collected", async t => {
  const steps = [], original = t.get()
  const reference = retainedPacketReference(original)
  // The Workbench renders the route's client projection of this draft.
  const listed = (await t.list()).find(d => d.id === t.primary)
  const markup = renderToStaticMarkup(React.createElement(GraphicPreview, { draft: listed, onAction() {} }))
  const step = async (name, action, extra = {}) => {
    const result = await t.post(body(t.get(), action, extra))
    steps.push({ name, status: result.status, code: result.body.code ?? null })
  }
  const refused = t.previewReply(original, other)
  const preview = t.preview(original, reference.artifact_sha256)
  const sha = preview.media_descriptor_sha256
  await step("attach_other_packet", "attach_graphic", { expectedMediaSha256: sha, retainedInputSha256: other })
  await step("attach_collected", "attach_graphic", { expectedMediaSha256: sha, retainedInputSha256: reference.artifact_sha256 })
  const attached = t.get()
  if (!attached.media_attachment) throw new Error(`collected attach failed: ${JSON.stringify(steps)}`)
  const swapped = structuredClone(attached.media_attachment)
  swapped.source.packet_artifact_sha256 = other
  const policySha = (await t.list()).find(d => d.id === t.primary).editorial_policy.policy_sha256
  await step("joint_review", "review", { reviewConfirmed: true, mediaReviewConfirmed: true, expectedMediaSha256: sha,
    expectedPolicySha256: policySha, ...attestationsFor(preview) })
  await step("approve", "approve")
  fs.writeFileSync(out, JSON.stringify({ reference, default_selected: markup.includes(`value="${reference.artifact_sha256}"`),
    collector_help: markup.includes("Selected from the packet the collector retained for this draft"),
    refused_preview: { status: refused.status, hold: refused.body.hold ?? null }, steps,
    valid_attached: validGistMedia(attached, attached.media_attachment), valid_swapped: validGistMedia(attached, swapped),
    preview_packet: preview.media_descriptor.source.packet_artifact_sha256 }))
}, { editorialPolicy: JSON.parse(policyJSON), retainedInput: null, render })
'''


def test_workbench_defaults_to_the_collected_packet_and_the_route_refuses_any_other(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    from src.editorial.policy import current_editorial_policy
    from tests.test_gist_store_journey import node_binary
    bundle, packet = collected_inputs()
    store_path = tmp_path / "media.sqlite3"
    store = gist_assets.SQLiteMediaStore(store_path)
    key = crw.retain_packet(store, packet)
    other = crw.retain_packet(store, {**packet, "csv_retrieved_at": "2026-06-16T12:45:00Z"})
    out = tmp_path / "association.json"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "LC_ALL": "C", "LANG": "C", "NETRC": "/dev/null",
           "NO_PROXY": "*", "no_proxy": "*", "THEHEAT_TEST_PYTHON": sys.executable,
           "THEHEAT_MEDIA_STORE": f"sqlite:{store_path}"}
    run = subprocess.run([node_binary(), "--input-type=module", "-e", ASSOCIATION_ROUTE, str(out),
                          json.dumps(current_editorial_policy()), other],
                         cwd=Path(__file__).resolve().parents[1] / "dashboard", env=env, capture_output=True, text=True,
                         timeout=600)
    assert run.returncode == 0, run.stderr[-4000:]
    result = json.loads(out.read_text())
    assert result["reference"]["artifact_sha256"] == key and result["preview_packet"] == key
    assert result["default_selected"] is True and result["collector_help"] is True
    assert result["refused_preview"] == {"status": 422, "hold": "media_source_packet_mismatch"}
    steps = {s["name"]: s for s in result["steps"]}
    assert steps["attach_other_packet"]["status"] >= 400
    assert [steps[n]["status"] for n in ("attach_collected", "joint_review", "approve")] == [200, 200, 200]
    assert result["valid_attached"] is True and result["valid_swapped"] is False
