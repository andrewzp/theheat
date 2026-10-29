"""Invented-data journeys through the real handlers for the store-backed image families.

retained input (local store) → saved draft → Python preview (schema 4 CRW / 5 published)
→ browser response contract → actual dashboard drafts route (attach with the exact
retained input, idempotent repeat, text-only/attestation-free/auto refusals, joint
review with attestations, manual approval + recorded workflow dispatch) → Python manual
worker reading the same local store → durable intent → fake X upload/alt/create →
confirmed receipt → no resend.

Named fake boundaries only: the Gist HTTP API (in memory), GitHub workflow dispatch
(recorded), the final safety model stub, the worker's Gist write and the X SDK
factories. The media store is the real local immutable artifact store. No network.
"""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from freezegun import freeze_time
import pytest

from src.editorial.policy import current_editorial_policy
from src.media import gist_assets
from src.state import DEFAULT_STATE
from tests.gist_media_helpers import install_fake_x
from tests.gist_published_helpers import fake_nws_feed
from tests.gist_store_helpers import retain

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ["crw", "radar", "cone"]


def node_binary():
    found = os.environ.get("THEHEAT_TEST_NODE") or shutil.which("node")
    if not found:
        pytest.skip("Node is required for the actual dashboard handlers")
    return found

ROUTE_JOURNEY = r'''
import fs from "node:fs"; import { pathToFileURL } from "node:url"
const [family, out, policyJSON, retained] = process.argv.slice(1)
const lib = name => pathToFileURL(`${process.cwd()}/${name}`).href
const { withGist, body, revision, attestationsFor } = await import(lib("tests/helpers/gist-hazard-harness.js"))
const { mediaPNGRequest, validateGraphicResponse } = await import(lib("lib/graphic-preview.js"))
const manifest = JSON.parse(fs.readFileSync("lib/graphic-runtime-manifest.json", "utf8"))
await withGist(family, async t => {
  const steps = [], original = t.get()
  const preview = t.preview(original)
  const request = mediaPNGRequest({ ...original, revision_identity: revision(original) }, manifest, retained)
  const browser = await validateGraphicResponse(preview, request, manifest)
  const step = async (name, action, extra = {}) => {
    const result = await t.post(body(t.get(), action, extra))
    steps.push({ name, status: result.status, code: result.body.code ?? null, review_status: result.body.draft?.review_status ?? null,
      review_kind: result.body.draft?.review_kind ?? null })
  }
  const sha = preview.media_descriptor_sha256
  await step("attach_without_input", "attach_graphic", { expectedMediaSha256: sha })
  await step("attach", "attach_graphic", { expectedMediaSha256: sha, retainedInputSha256: retained })
  const attached = revision(t.get())
  await step("attach_repeat", "attach_graphic", { expectedMediaSha256: sha, retainedInputSha256: retained })
  steps.at(-1).revision_unchanged = JSON.stringify(revision(t.get())) === JSON.stringify(attached)
  await step("text_only_review", "review", { reviewConfirmed: true, expectedPolicySha256: t.get().review_binding?.policy_sha256 ?? null })
  const policySha = (await t.list()).find(d => d.id === t.primary).editorial_policy.policy_sha256
  const joint = { reviewConfirmed: true, mediaReviewConfirmed: true, expectedMediaSha256: sha, expectedPolicySha256: policySha }
  if (preview.schema_version === 5) {
    const partial = { ...attestationsFor(preview).publishedAttestations }
    delete partial[Object.keys(partial)[0]]
    await step("joint_review_missing_attestation", "review", { ...joint, publishedAttestations: partial })
  }
  await step("joint_review", "review", { ...joint, ...attestationsFor(preview) })
  await step("auto_approve", "auto_approve")
  await step("approve", "approve")
  fs.writeFileSync(out, JSON.stringify({ preview, browser_ok: browser === preview, steps, dispatches: t.dispatches,
    previews: t.previews.length, raw_state: t.raw(), clock: t.clock.current, primary: t.primary }))
}, { editorialPolicy: JSON.parse(policyJSON), retainedInput: retained })
'''


@pytest.mark.parametrize("family", FAMILIES)
def test_actual_handler_journey_sends_exact_retained_bytes_and_description(family, tmp_path, monkeypatch):
    store_path = tmp_path / "media.sqlite3"
    retained = retain(family, gist_assets.SQLiteMediaStore(store_path))
    out = tmp_path / "route-result.json"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "LC_ALL": "C", "LANG": "C", "NETRC": "/dev/null",
           "NO_PROXY": "*", "no_proxy": "*", "THEHEAT_TEST_PYTHON": sys.executable,
           "THEHEAT_MEDIA_STORE": f"sqlite:{store_path}"}
    policy = json.dumps(current_editorial_policy())
    run = subprocess.run([node_binary(), "--input-type=module", "-e", ROUTE_JOURNEY, family, str(out), policy, retained],
                         cwd=ROOT / "dashboard", env=env, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-4000:]
    route = json.loads(out.read_text())
    preview = route["preview"]
    published = preview["schema_version"] == 5
    assert route["browser_ok"] is True and preview["schema_version"] == (4 if family == "crw" else 5)
    expected = [("attach_without_input", 409), ("attach", 200), ("attach_repeat", 200), ("text_only_review", 409)]
    expected += [("joint_review_missing_attestation", 409)] if published else []
    expected += [("joint_review", 200), ("auto_approve", 409), ("approve", 200)]
    assert [(s["name"], s["status"]) for s in route["steps"]] == expected
    steps = {s["name"]: s for s in route["steps"]}
    assert steps["attach_without_input"]["code"] == "media_retained_input_required"
    assert steps["attach_repeat"]["revision_unchanged"] is True
    assert steps["text_only_review"]["code"] == "media_review_required"
    if published:
        assert steps["joint_review_missing_attestation"]["code"] == "media_attestation_required"
    assert steps["joint_review"]["review_status"] == "passed" and steps["joint_review"]["review_kind"] == "human_media"
    assert len(route["dispatches"]) == 1
    inputs = route["dispatches"][0]["inputs"]
    saved = json.loads(route["raw_state"])
    primary = next(d for d in saved["drafts"] if d["id"] == route["primary"])
    assert primary["media_attachment"] == preview["media_descriptor"] and primary["status"] == "approved"
    if published:
        assert primary["review_binding"]["published_attestations"]["confirmed"] == [
            row["name"] for row in preview["inspection"]["required_attestations"]]
    assert saved["unrelated"] == {"preserve": True}
    assert "png_base64" not in route["raw_state"] and "iVBORw0KGgo" not in route["raw_state"]
    assert "R0lGOD" not in route["raw_state"]  # Nor a GIF original.

    reviewed_png = base64.b64decode(preview["png_base64"])
    fake = install_fake_x(monkeypatch)
    if family == "radar":
        fake_nws_feed(monkeypatch)
    for name, value in (("TWEET_TEXT", inputs["tweet_text"]), ("DRAFT_ID", inputs["draft_id"]),
                        ("PUBLISH_INTENT_ID", inputs["publish_intent_id"]),
                        (gist_assets.ENV, f"sqlite:{store_path}")):
        monkeypatch.setenv(name, value)
    bot_state = {**deepcopy(DEFAULT_STATE), **saved}
    sent_at = datetime.fromtimestamp(route["clock"] / 1000, timezone.utc)
    with freeze_time(sent_at):
        fake.posting.run_manual_tweet(bot_state)
    assert fake.calls == [
        ("upload", reviewed_png, "hot10.png"),
        ("alt", "98765", preview["delivery_text"]),
        ("create", primary["text"], {"media_ids": ["98765"]}),
    ]
    identity = (primary["media_attachment"]["asset"]["derivative_sha256"] if published
                else primary["media_attachment"]["image"]["png_sha256"])
    assert hashlib.sha256(reviewed_png).hexdigest() == identity
    receipt = bot_state["publish_ledger"][primary["event_id"]]
    assert receipt["phase"] == "confirmed" and receipt["tweet_id"] == "invented-x-receipt"
    with freeze_time(sent_at):
        fake.posting.run_manual_tweet(bot_state)
    assert len(fake.calls) == 3


@pytest.mark.parametrize("family", FAMILIES)
def test_missing_store_or_input_at_send_is_refused_before_any_attempt(family, tmp_path, monkeypatch):
    """An approved draft whose store is unconfigured or lost holds before intent and transport."""
    from src.editorial import revisions
    from src.media import gist_media
    from tests.gist_media_helpers import approve, attach, run_manual, state_for
    from tests.gist_store_helpers import CLOCKS, TEXTS, TYPES, family_bundle
    store = gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3")
    retained = retain(family, store)
    bundle = family_bundle(family)
    now = datetime.fromisoformat(CLOCKS[family][0].replace("Z", "+00:00"))
    prepared = gist_media.prepare_media(bundle, retained_input_sha256=retained, store=store, now=now)
    draft = {"id": f"invented-{family}", "event_id": bundle["event_id"], "type": TYPES[family], "status": "pending",
             "text": TEXTS[family], "created_at": CLOCKS[family][0], "review_context": {"two_bot": {"bundle": bundle}}}
    revisions.initialize_revision(draft)
    attach(draft, prepared["descriptor"], at=CLOCKS[family][0])
    approve(draft, attestations={name: True for name in gist_media.required_attestations(draft["media_attachment"])})
    fake = install_fake_x(monkeypatch)
    if family == "radar":
        fake_nws_feed(monkeypatch)
    for environ, code in (({}, "media store"), ({gist_assets.ENV: f"sqlite:{tmp_path / 'lost.sqlite3'}"}, "does not exist")):
        monkeypatch.delenv(gist_assets.ENV, raising=False)
        for key, value in environ.items():
            monkeypatch.setenv(key, value)
        attempt = deepcopy(draft)
        with freeze_time(now):
            run_manual(monkeypatch, fake, state_for(attempt), attempt)
        # Pre-intent refusal: no durable write, no SDK call, no submitted ledger row.
        assert fake.calls == [] and fake.persisted == [] and attempt["publish_outcome"] == "not_sent", code
        assert code in attempt["post_error"]
