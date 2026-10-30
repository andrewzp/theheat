"""Invented-data journeys through the real handlers for each new image family.

saved draft → Python PNG preview → browser response contract → actual dashboard
drafts route (attach, idempotent repeat, text-only/auto refusals, joint review,
manual approval + recorded workflow dispatch) → Python manual worker → durable
intent → fake X upload/alt/create → confirmed receipt → no resend.

Real code: build_preview, dashboard/lib/graphic-preview.js, dashboard/app/api/drafts/
route.js with its revision/lossless writers, posting.run_manual_tweet → post_approved
→ twitter.post_tweet. Named fake boundaries: the Gist HTTP API (in memory), GitHub
workflow dispatch (recorded), the final safety model (explicit offline stub), the
worker's Gist write (recorded) and the X SDK factories. No network or real post.
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
from src.state import DEFAULT_STATE
from tests.gist_media_helpers import install_fake_x

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ["pm25", "modis", "viirs", "hot10"]

ROUTE_JOURNEY = r'''
import fs from "node:fs"; import { pathToFileURL } from "node:url"
const [family, out, policyJSON] = process.argv.slice(1)
const lib = name => pathToFileURL(`${process.cwd()}/${name}`).href
const { withGist, body, revision } = await import(lib("tests/helpers/gist-hazard-harness.js"))
const { mediaPNGRequest, validateGraphicResponse } = await import(lib("lib/graphic-preview.js"))
const manifest = JSON.parse(fs.readFileSync("lib/graphic-runtime-manifest.json", "utf8"))
await withGist(family, async t => {
  const steps = [], original = t.get()
  const preview = t.preview(original)
  const browser = await validateGraphicResponse(preview, mediaPNGRequest({ ...original, revision_identity: revision(original) }, manifest), manifest)
  const step = async (name, action, extra = {}) => {
    const result = await t.post(body(t.get(), action, extra))
    steps.push({ name, status: result.status, code: result.body.code ?? null, review_status: result.body.draft?.review_status ?? null,
      review_kind: result.body.draft?.review_kind ?? null })
  }
  const sha = preview.media_descriptor_sha256
  await step("attach", "attach_graphic", { expectedMediaSha256: sha })
  const attached = revision(t.get())
  await step("attach_repeat", "attach_graphic", { expectedMediaSha256: sha })
  steps.at(-1).revision_unchanged = JSON.stringify(revision(t.get())) === JSON.stringify(attached)
  await step("text_only_review", "review", { reviewConfirmed: true, expectedPolicySha256: t.get().review_binding?.policy_sha256 ?? null })
  const policySha = (await t.list()).find(d => d.id === t.primary).editorial_policy.policy_sha256
  await step("joint_review", "review", { reviewConfirmed: true, mediaReviewConfirmed: true, expectedMediaSha256: sha, expectedPolicySha256: policySha })
  await step("auto_approve", "auto_approve")
  await step("approve", "approve")
  fs.writeFileSync(out, JSON.stringify({ preview, browser_ok: browser === preview, steps, dispatches: t.dispatches,
    previews: t.previews.length, raw_state: t.raw(), clock: t.clock.current, primary: t.primary }))
}, { editorialPolicy: JSON.parse(policyJSON) })
'''


def node_binary():
    found = os.environ.get("THEHEAT_TEST_NODE") or shutil.which("node")
    if not found:
        pytest.skip("Node is required for the actual dashboard handlers")
    return found


@pytest.mark.parametrize("family", FAMILIES)
def test_actual_handler_journey_sends_exact_reviewed_png_and_delivery_text(family, tmp_path, monkeypatch):
    out = tmp_path / "route-result.json"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "LC_ALL": "C", "LANG": "C", "NETRC": "/dev/null",
           "NO_PROXY": "*", "no_proxy": "*", "THEHEAT_TEST_PYTHON": sys.executable}
    policy = json.dumps(current_editorial_policy())  # the sender's own current policy
    run = subprocess.run([node_binary(), "--input-type=module", "-e", ROUTE_JOURNEY, family, str(out), policy],
                         cwd=ROOT / "dashboard", env=env, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-4000:]
    route = json.loads(out.read_text())
    preview = route["preview"]
    assert route["browser_ok"] is True and preview["schema_version"] == 4
    assert [(s["name"], s["status"]) for s in route["steps"]] == [
        ("attach", 200), ("attach_repeat", 200), ("text_only_review", 409), ("joint_review", 200),
        ("auto_approve", 409), ("approve", 200)]
    steps = {s["name"]: s for s in route["steps"]}
    assert steps["attach_repeat"]["revision_unchanged"] is True
    assert steps["text_only_review"]["code"] == "media_review_required"
    assert steps["joint_review"]["review_status"] == "passed" and steps["joint_review"]["review_kind"] == "human_media"
    assert route["previews"] >= 3  # attach, repeat and review each rechecked the server-side PNG
    assert len(route["dispatches"]) == 1
    inputs = route["dispatches"][0]["inputs"]
    saved = json.loads(route["raw_state"])
    primary = next(d for d in saved["drafts"] if d["id"] == route["primary"])
    assert inputs["mode"] == "manual_tweet" and inputs["draft_id"] == primary["id"] and inputs["tweet_text"] == primary["text"]
    assert primary["media_attachment"] == preview["media_descriptor"] and primary["status"] == "approved"
    assert saved["unrelated"] == {"preserve": True}
    assert "png_base64" not in route["raw_state"] and "iVBORw0KGgo" not in route["raw_state"]

    reviewed_png = base64.b64decode(preview["png_base64"])
    fake = install_fake_x(monkeypatch)
    for name, value in (("TWEET_TEXT", inputs["tweet_text"]), ("DRAFT_ID", inputs["draft_id"]),
                        ("PUBLISH_INTENT_ID", inputs["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    bot_state = {**deepcopy(DEFAULT_STATE), **saved}
    # Sender time equals the approval time: inside the explicit image-path window.
    sent_at = datetime.fromtimestamp(route["clock"] / 1000, timezone.utc)
    with freeze_time(sent_at):
        fake.posting.run_manual_tweet(bot_state)
    assert fake.calls == [
        ("upload", reviewed_png, "hot10.png"),
        ("alt", "98765", preview["delivery_text"]),
        ("create", primary["text"], {"media_ids": ["98765"]}),
    ]
    assert hashlib.sha256(reviewed_png).hexdigest() == primary["media_attachment"]["image"]["png_sha256"]
    assert fake.persisted and fake.persisted[0][0]["publish_ledger"][primary["event_id"]]["phase"] == "submitted"
    receipt = bot_state["publish_ledger"][primary["event_id"]]
    assert receipt["phase"] == "confirmed" and receipt["tweet_id"] == "invented-x-receipt"
    posted = next(d for d in bot_state["drafts"] if d["id"] == primary["id"])
    assert posted["status"] == "posted" and posted["media_attachment"] == preview["media_descriptor"]
    with freeze_time(sent_at):
        fake.posting.run_manual_tweet(bot_state)  # a repeated dispatch never creates again
    assert len(fake.calls) == 3
