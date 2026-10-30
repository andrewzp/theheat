"""Real failure journeys for the store-backed families (CRW, published radar, NHC cone).

Sender phase: an approved state produced through the packaged preview, then FRESH
actual-CLI sender processes over the PostgreSQL adapter (OFFLINE protocol fixture)
with faults injected at named points. Route phase: the actual dashboard handlers with
fresh packaged-preview processes, toggling the same faults between operator steps.

Invariants: a hold never fabricates a receipt, substitutes an image or resends blindly;
the original approval and durable-intent ordering are preserved; a reconnected store
never stands in for a missing review; native and text-only paths stay usable.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.editorial.policy import current_editorial_policy
from src.media import gist_assets, gist_assets_postgres as pg, gist_crw_media as crw, gist_media
from tests import gist_pg_protocol_fixture as fx
from tests.gist_store_helpers import CLOCKS
from tests.test_gist_store_journey import FAMILIES, node_binary
from tests.test_gist_two_consumer_journey import (PACKAGED_SERVER, ROOT, approved_state, base_env, deploy_runtime,
                                                  inputs_for, packaged_preview, send, shared_store)


@pytest.fixture(autouse=True)
def no_ambient_pg(monkeypatch):
    for name in [n for n in os.environ if n.startswith("PG")]:
        monkeypatch.delenv(name)


def approved(family, tmp_path):
    writer, store_env, fixture = shared_store("postgres-protocol-fixture", tmp_path)
    state, draft, preview = approved_state(family, tmp_path, writer, store_env, fixture)
    return state, draft, preview, store_env, fixture


def after_approval(family, minutes=1):
    """The sender runs after the dashboard decision (the merge orders drafts by update time)."""
    from datetime import datetime, timedelta
    return (datetime.fromisoformat(CLOCKS[family][0].replace("Z", "+00:00")) + timedelta(minutes=minutes)).isoformat()


def run_send(tmp_path, state, draft, store_env, family, name, *, now=None, **options):
    return send(tmp_path, json.dumps(state), inputs_for(draft), draft["event_id"], now or after_approval(family),
                store_env, family=family, name=name, **options)


def manual_outcome(final):
    return next(src for run in reversed(final["run_history"]) for src in run.get("sources", [])
                if src.get("source") == "manual_publish")


def saved_draft(final, draft):
    return next(d for d in final["drafts"] if d["id"] == draft["id"])


@pytest.mark.parametrize("fault,code", [("unavailable", "media_store_unavailable"), ("revoked", "wrong permissions"),
                                        ("tamper", "changed"), ("truncate", "changed"), ("timeout", "unavailable")])
@pytest.mark.parametrize("family", FAMILIES)
def test_store_failure_after_approval_holds_before_intent_then_recovers(family, fault, code, tmp_path):
    state, draft, preview, store_env, fixture = approved(family, tmp_path)
    fx.set_fault(fixture, fault)
    held, after_hold = run_send(tmp_path, state, draft, store_env, family, "held")
    sent = saved_draft(after_hold, draft)
    assert held["exit"] == 0 and held["calls"] == [] and held["uploaded"] is None
    assert sent["publish_outcome"] == "not_sent" and "Graphic needs a new preview" in sent["post_error"]
    assert draft["event_id"] not in after_hold["publish_ledger"]  # No phantom submitted intent.
    # The failed send spends its intent: the draft returns to pending with no intent id.
    assert sent["status"] == "pending" and "publish_intent_id" not in sent
    assert "invented" not in sent["post_error"] and "password" not in sent["post_error"]  # No DSN/provider text.
    fx.set_fault(fixture, "")
    # A reconnected store authorizes nothing by itself: the unchanged intent is refused...
    stale, _ = run_send(tmp_path, after_hold, draft, store_env, family, "stale-intent", now=after_approval(family, 2))
    assert stale["calls"] == []
    # ...and only a fresh operator approval (new intent) sends the exact reviewed bytes.
    from tests.gist_media_helpers import approve
    retry_state = json.loads((tmp_path / "gist-state.json").read_text())
    renewed = saved_draft(retry_state, draft)
    approve(renewed, intent="invented-renewed-intent",
            attestations={name: True for name in gist_media.required_attestations(renewed["media_attachment"])})
    (tmp_path / "gist-state.json").write_text(json.dumps(retry_state))
    retried, final = send(tmp_path, json.dumps(retry_state), inputs_for(renewed), draft["event_id"],
                          after_approval(family, 3), store_env, family=family, name="retried")
    assert [c[0] for c in retried["calls"]] == ["upload", "alt", "create"]
    assert retried["calls"][1][2] == preview["delivery_text"]
    assert final["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"


@pytest.mark.parametrize("family", FAMILIES)
def test_store_outage_after_the_durable_intent_never_rereads_or_substitutes(family, tmp_path):
    state, draft, preview, store_env, fixture = approved(family, tmp_path)
    record, final = run_send(tmp_path, state, draft, store_env, family, "sender", fault_after_intent="unavailable")
    # The verified bytes from before the intent are the ones uploaded; no read after it.
    assert record["reads_at_intent"] == record["reads_at_end"]
    assert [c[0] for c in record["calls"]] == ["upload", "alt", "create"]
    import base64
    assert record["uploaded"] == base64.b64decode(preview["png_base64"])
    assert final["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"


@pytest.mark.parametrize("failure", ["upload", "alt", "create", "empty_receipt"])
@pytest.mark.parametrize("family", FAMILIES)
def test_unknown_x_acknowledgement_is_never_resent_by_a_fresh_sender(family, failure, tmp_path):
    state, draft, _preview, store_env, _fixture = approved(family, tmp_path)
    first, after = run_send(tmp_path, state, draft, store_env, family, "first", failure=failure)
    row = after["publish_ledger"][draft["event_id"]]
    assert row["phase"] == "unknown" and row["tweet_id"] is None  # No fabricated receipt.
    assert saved_draft(after, draft)["publish_outcome"] == "unknown"
    again, final = run_send(tmp_path, state, draft, store_env, family, "again")
    assert again["calls"] == [] and final["publish_ledger"][draft["event_id"]]["phase"] == "unknown"
    assert first["calls"][0][0] == "upload"


@pytest.mark.parametrize("family", FAMILIES)
def test_source_expiry_and_correction_hold_without_sending(family, tmp_path):
    state, draft, _preview, store_env, _fixture = approved(family, tmp_path)
    expired, after = run_send(tmp_path, state, draft, store_env, family, "expired", now=CLOCKS[family][1])
    held = saved_draft(after, draft)
    assert expired["calls"] == [] and held["status"] != "posted"
    assert held.get("publish_outcome") in (None, "not_sent")  # Refused before any submitted intent.
    assert after["publish_ledger"].get(draft["event_id"], {}).get("tweet_id") is None
    assert manual_outcome(after)["status"] in ("skipped", "failed")  # Recorded, never silently sent.
    # A corrected source bundle no longer matches the reviewed descriptor.
    corrected = deepcopy(state)
    bundle = saved_draft(corrected, draft)["review_context"]["two_bot"]["bundle"]
    bundle["where"] = f"{bundle['where']} (corrected)"
    (tmp_path / "gist-state.json").unlink()
    changed, after_change = run_send(tmp_path, corrected, draft, store_env, family, "corrected")
    refused = saved_draft(after_change, draft)
    assert changed["calls"] == [] and refused["status"] != "posted"
    assert after_change["publish_ledger"].get(draft["event_id"], {}).get("tweet_id") is None
    assert manual_outcome(after_change)["status"] in ("skipped", "failed")
    assert after_change["publish_ledger"].get(draft["event_id"], {}).get("tweet_id") is None


def test_nws_correction_supersedes_the_reviewed_radar_warning(tmp_path):
    from tests.gist_published_helpers import radar_feature
    state, draft, _preview, store_env, _fixture = approved("radar", tmp_path)
    feature = radar_feature()
    cancel = deepcopy(feature)
    cancel["id"] = cancel["id"] + "-cancel"
    cancel["properties"].update(id=feature["properties"]["id"] + "-cancel", messageType="Cancel",
                                references=[{"identifier": feature["properties"]["id"]}])
    record, final = run_send(tmp_path, state, draft, store_env, "radar", "sender", nws_features=[feature, cancel])
    assert record["calls"] == []
    held = saved_draft(final, draft)
    assert held["status"] != "posted" and "nws" in (held.get("post_error") or "").lower()
    assert final["publish_ledger"].get(draft["event_id"], {}).get("tweet_id") is None  # No fabricated receipt.


def test_lost_retention_acknowledgement_is_unknown_then_an_identical_retry_retains(tmp_path):
    from tests.gist_store_helpers import retain
    backing = fx.create(tmp_path / "protocol.sqlite3")
    writer = pg.PostgresMediaStore(pg.parse_dsn(fx.WRITER_DSN), role="writer", driver=fx.module(backing))
    fx.set_fault(backing, "lost_commit_ack")
    for family in FAMILIES:
        with pytest.raises((gist_assets.MediaStoreError, crw.MediaWithheld)) as unknown:
            retain(family, writer)
        assert getattr(unknown.value, "code", None) == "media_retention_unknown"  # Never reported as retained.
    fx.set_fault(backing, "")
    first = {family: retain(family, writer) for family in FAMILIES}
    assert first == {family: retain(family, writer) for family in FAMILIES}  # Idempotent, same identities.


def test_native_and_text_only_paths_stay_usable_while_the_store_is_down(tmp_path):
    from src.editorial.revisions import decision_revision, draft_identity
    from tests.gist_hazard_helpers import saved_state as native_state
    _writer, store_env, fixture = shared_store("postgres-protocol-fixture", tmp_path)
    fx.set_fault(fixture, "unavailable")
    deploy = deploy_runtime(tmp_path)
    manifest = json.loads((deploy / "lib/graphic-runtime-manifest.json").read_text())
    state = native_state("pm25")
    draft = state["drafts"][0]
    request = {"draft_id": draft["id"], "format": "png",
               "expected_revision": {**draft_identity(draft), "decision_revision": decision_revision(draft)},
               "expected_policy_source_sha256": manifest["identity"]["policy_source_sha256"],
               "expected_preview_runtime_sha256": manifest["runtime_sha256"]}
    reply = packaged_preview(tmp_path, deploy, state, request, store_env, fixture)
    assert reply["status"] == 200 and reply["body"]["media_kind"] == "gist_pm25_forecast_v1"
    # A store-backed draft approved text-only (no attachment) still sends its text.
    from src.editorial import revisions
    from tests.gist_store_helpers import saved_state
    text_state = saved_state("crw")
    text_draft = text_state["drafts"][0]
    revisions.record_human_review(text_draft)  # Offline decision fixture: text-only, no attachment.
    revisions.authorize_draft(text_draft, "manual", "invented-text-intent")
    text_draft.update(status="approved", approval_mode="manual", publish_intent_id="invented-text-intent")
    record, final = send(tmp_path, json.dumps(text_state), inputs_for(text_draft), text_draft["event_id"],
                         after_approval("crw"), store_env, family="crw")
    assert [c[0] for c in record["calls"]] == ["create"] and record["uploaded"] is None
    assert final["publish_ledger"][text_draft["event_id"]]["phase"] == "confirmed"
    assert fx.counter(fixture, "payload_reads") == 0  # Neither path touched the unavailable store.


ROUTE_FAILURES = r'''
import fs from "node:fs"; import { spawnSync } from "node:child_process"; import { pathToFileURL } from "node:url"
const [family, out, policyJSON, retained, configPath] = process.argv.slice(1)
const config = JSON.parse(fs.readFileSync(configPath, "utf8"))
const lib = name => pathToFileURL(`${process.cwd()}/${name}`).href
const { withGist, body, attestationsFor } = await import(lib("tests/helpers/gist-hazard-harness.js"))
const fault = name => {
  const run = spawnSync(config.python, ["-c", `from tests import gist_pg_protocol_fixture as fx; fx.set_fault(${JSON.stringify(config.fixture_file)}, ${JSON.stringify(name)})`],
    { cwd: "..", encoding: "utf8", env: { PATH: process.env.PATH, LC_ALL: "C", PYTHON_DOTENV_DISABLED: "1" } })
  if (run.status !== 0) throw new Error(run.stderr)
}
const render = (request, rawState, authorization) => {
  const run = spawnSync(config.python, ["-I", "-c", config.server, config.entry, config.fixture_module, config.fixture_file],
    { cwd: config.cwd, env: config.env, input: JSON.stringify({ request, raw_state: rawState, authorization }),
      encoding: "utf8", timeout: 120000, maxBuffer: 32 * 1024 * 1024 })
  if (run.status !== 0) throw new Error(`packaged preview failed: ${run.stderr.slice(-4000)}`)
  const reply = JSON.parse(run.stdout)
  return { status: reply.status, body: reply.body }
}
const results = {}
const journey = (name, steps) => withGist(family, async t => {
  const log = []
  const step = async (label, action, extra = {}) => {
    const result = await t.post(body(t.get(), action, extra))
    log.push({ label, status: result.status, code: result.body.code ?? null,
      attached: Object.hasOwn(t.get(), "media_attachment"), status_after: t.get().status })
    return result
  }
  const policy = async () => (await t.list()).find(d => d.id === t.primary).editorial_policy.policy_sha256
  const joint = async preview => ({ reviewConfirmed: true, mediaReviewConfirmed: true, expectedMediaSha256: preview.media_descriptor_sha256,
    expectedPolicySha256: await policy(), ...attestationsFor(preview) })
  await steps({ t, step, log, policy, joint })
  results[name] = { log, dispatches: t.dispatches.length }
  fault("")
}, { editorialPolicy: JSON.parse(policyJSON), retainedInput: retained, render })

await journey("preview_holds_and_text_only", async ({ t, step, log, policy }) => {
  for (const name of ["unavailable", "revoked", "tamper", "truncate", "timeout"]) {
    fault(name)
    const reply = t.previewReply(t.get())
    log.push({ label: `preview_${name}`, status: reply.status, code: reply.body.code ?? null, hold: reply.body.hold ?? null })
  }
  fault("unavailable")
  await step("attach_while_down", "attach_graphic", { expectedMediaSha256: "0".repeat(64), retainedInputSha256: retained })
  await step("text_only_review", "review", { reviewConfirmed: true, expectedPolicySha256: await policy() })
  await step("text_only_approve", "approve")
})
await journey("between_preview_and_attach", async ({ t, step }) => {
  const preview = t.preview(t.get())
  fault("unavailable")
  await step("attach_down", "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256, retainedInputSha256: retained })
  fault("")
  await step("attach_restored", "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256, retainedInputSha256: retained })
})
await journey("before_joint_review", async ({ t, step, joint }) => {
  const preview = t.preview(t.get())
  await step("attach", "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256, retainedInputSha256: retained })
  const review = await joint(preview)
  fault("unavailable")
  await step("review_down", "review", review)
  await step("approve_down", "approve")
  fault("")
  await step("approve_reconnected_without_review", "approve")
  await step("review_restored", "review", await joint(preview))
  await step("approve_restored", "approve")
})
await journey("edit_revert_remove_replace", async ({ t, step, joint }) => {
  const original = t.get().text
  const preview = t.preview(t.get())
  await step("attach", "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256, retainedInputSha256: retained })
  await step("review", "review", await joint(preview))
  await step("edit", "edit", { editedText: original + " Edited." })
  await step("approve_after_edit", "approve")
  await step("revert", "edit", { editedText: original })
  await step("approve_after_revert", "approve")
  await step("remove", "remove_graphic")
  await step("replace", "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256, retainedInputSha256: retained })
  await step("approve_after_replace", "approve")
  await step("review_again", "review", await joint(preview))
  await step("approve_final", "approve")
})
fs.writeFileSync(out, JSON.stringify(results))
'''


@pytest.mark.parametrize("family", FAMILIES)
def test_route_phase_failures_through_the_actual_handlers(family, tmp_path):
    writer, store_env, fixture = shared_store("postgres-protocol-fixture", tmp_path)
    from tests.gist_store_helpers import retain
    retained = retain(family, writer)
    deploy = deploy_runtime(tmp_path)
    preview_env = {**base_env(tmp_path), "DASHBOARD_USERNAME": "invented-reviewer",
                   "DASHBOARD_PASSWORD": "invented-password", **{k: v for k, v in store_env.items() if k != fx.ENV}}
    config = {"python": sys.executable, "server": PACKAGED_SERVER, "entry": str(deploy / "api/graphic_preview.py"),
              "fixture_module": str(Path(fx.__file__).resolve()), "fixture_file": str(fixture),
              "cwd": str(tmp_path / "unrelated-cwd"), "env": preview_env}
    (tmp_path / "config.json").write_text(json.dumps(config))
    out = tmp_path / "results.json"
    run = subprocess.run([node_binary(), "--input-type=module", "-e", ROUTE_FAILURES, family, str(out),
                          json.dumps(current_editorial_policy()), retained, str(tmp_path / "config.json")],
                         cwd=ROOT / "dashboard", env={**base_env(tmp_path), "THEHEAT_TEST_PYTHON": sys.executable},
                         capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stderr[-4000:]
    results = json.loads(out.read_text())
    holds = {row["label"]: row for row in results["preview_holds_and_text_only"]["log"]}
    assert {k: (v["status"], v["hold"]) for k, v in holds.items() if k.startswith("preview_")} == {
        "preview_unavailable": (422, "media_store_unavailable"), "preview_revoked": (422, "media_store_unavailable"),
        "preview_tamper": (422, "media_asset_changed"), "preview_truncate": (422, "media_asset_changed"),
        "preview_timeout": (422, "media_store_unavailable")}
    assert (holds["attach_while_down"]["status"], holds["attach_while_down"]["code"]) == (409, "graphic_recheck_required")
    assert holds["attach_while_down"]["attached"] is False
    assert (holds["text_only_review"]["status"], holds["text_only_approve"]["status"]) == (200, 200)
    assert results["preview_holds_and_text_only"]["dispatches"] == 1  # Text-only still dispatches.
    steps = {r["label"]: r for r in results["between_preview_and_attach"]["log"]}
    assert (steps["attach_down"]["status"], steps["attach_down"]["code"]) == (409, "graphic_recheck_required")
    assert steps["attach_down"]["attached"] is False
    assert steps["attach_restored"]["status"] == 200 and steps["attach_restored"]["attached"] is True
    steps = {r["label"]: r for r in results["before_joint_review"]["log"]}
    assert (steps["review_down"]["status"], steps["review_down"]["code"]) == (409, "graphic_recheck_required")
    assert (steps["approve_down"]["status"], steps["approve_down"]["code"]) == (409, "review_required")
    reconnected = steps["approve_reconnected_without_review"]  # Reconnection inherits nothing.
    assert (reconnected["status"], reconnected["code"]) == (409, "review_required")
    assert (steps["review_restored"]["status"], steps["approve_restored"]["status"]) == (200, 200)
    assert results["before_joint_review"]["dispatches"] == 1
    steps = {r["label"]: r for r in results["edit_revert_remove_replace"]["log"]}
    assert [steps[k]["status"] for k in ("attach", "review", "edit")] == [200, 200, 200]
    assert {steps[k]["code"] for k in ("approve_after_edit", "approve_after_revert", "approve_after_replace")} == {
        "review_required"}
    assert steps["remove"]["attached"] is False and steps["replace"]["attached"] is True
    assert steps["approve_after_replace"]["status"] == 409
    assert (steps["review_again"]["status"], steps["approve_final"]["status"]) == (200, 200)
    assert results["edit_revert_remove_replace"]["dispatches"] == 1
