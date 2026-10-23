"""One invented publication crosses the real receipt/sample/JS-view boundary.

Only storage and the publication transport are explicit offline mocks. Existing
revision fixtures supply test-only checks; no provider or platform is contacted.
"""
from copy import deepcopy
from datetime import UTC, datetime
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, cast
from unittest.mock import MagicMock

from src.data.metric_history import append_sample
from src.editorial.revisions import draft_identity, fingerprint
from src.orchestrator import posting
from src.state_schema import BotState
from tests.revision_helpers import bind_reviewed_draft


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/post_outcome_publication_context.json"
POSTED = "2026-10-20T12:00:00Z"
SAMPLED = datetime(2026, 10, 21, 12, tzinfo=UTC)


def publication_fixture(monkeypatch) -> dict[str, Any]:
    importlib.reload(posting)
    draft: dict[str, Any] = {
        "id": "invented-outcome-draft", "event_id": "invented-outcome-event",
        "type": "monthly_high", "tweet_date": "2026-10-20", "hot10_rows": None,
        "text": "Invented fixture: a station recorded a monthly high.",
        "manual_override": True, "selected_candidate_rank": 2,
        "review_context": {"two_bot": {
            "angle_chosen": "unbound_writer_angle",
            "bundle": {
                "event_id": "invented-outcome-event", "signal_kind": "monthly_high",
                "where": "INVENTED STATION", "when": "2026-10-20",
                "headline_metric": {}, "current_facts": [], "historical_context": {},
                "raw_signal_dump": {"source_product": "public-invented-fixture",
                                    "description": "DO_NOT_DISPLAY_FULL_SOURCE"},
            },
        }},
    }
    bind_reviewed_draft(draft, "manual", "invented-outcome-intent")
    state = cast(BotState, {"drafts": [draft], "publish_ledger": {}, "posted_events": []})
    original = deepcopy(draft)
    submitted = {}
    storage = MagicMock()
    storage.check_daily_cap.return_value = True
    send = MagicMock(return_value={"id": "123"})

    def store(value, *, expected_draft, expected_publish_ledger):
        assert expected_draft == original and expected_publish_ledger is None
        assert value["publish_ledger"][draft["event_id"]]["phase"] == "submitted"
        send.assert_not_called()
        submitted.update(deepcopy(expected_draft))
        return True

    storage.write_state.side_effect = store
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "_utc_now_iso", lambda: POSTED)
    assert posting.post_approved(draft, state) == "posted"
    send.assert_called_once_with(original["text"], media_png=None, alt_text=None)
    receipt = deepcopy(state["publish_ledger"][draft["event_id"]])
    assert receipt["phase"] == "confirmed" and receipt["tweet_id"] == "123"
    # Retain only the fixture's deterministic fields. Every identity input is
    # copied from the actual submitted snapshot, never from a later draft edit.
    retained = {key: submitted[key] for key in (
        "id", "event_id", "type", "tweet_date", "hot10_rows", "text",
        "content_revision", "review_context", "manual_override", "selected_candidate_rank",
    )}
    retained["review_context"]["two_bot"] = {
        key: retained["review_context"]["two_bot"][key] for key in ("bundle", "angle_chosen")
    }
    assert all(receipt[key] == value for key, value in draft_identity(retained).items())
    retained.update(status="posted", publish_outcome="confirmed", tweet_id="123", posted_at=POSTED)
    result_state: dict[str, Any] = {"drafts": [retained], "publish_ledger": {retained["event_id"]: receipt}}
    metrics = append_sample(None, tweet_id="123", counts={"likes": 0, "impressions": 12,
                            "created_at": POSTED}, sampled_at=SAMPLED, state=result_state)
    result_state["tweet_metrics"] = {"123": metrics}
    return result_state


def test_actual_publication_sample_projects_and_renders_exact_context(monkeypatch, tmp_path):
    state = publication_fixture(monkeypatch)
    assert state == json.loads(FIXTURE.read_text())
    before = deepcopy(state)
    sample = next(iter(state["tweet_metrics"]["123"]["samples"].values()))
    assert sample["schema_version"] == 1 and sample["post_age_seconds"] == 86400
    # Keep the original schema1 observation bytes/identity cross-runtime input.
    (tmp_path / "producer-state.json").write_text(json.dumps(state, indent=2) + "\n")
    script = """
        import assert from 'node:assert/strict';
        import React from 'react';
        import {renderToStaticMarkup} from 'react-dom/server';
        import {postOutcomes} from './lib/post-outcomes.js';
        import History from './app/components/PostOutcomeHistory.js';
        globalThis.fetch = () => {throw new Error('No external I/O permitted')};
        let input = ''; for await (const chunk of process.stdin) input += chunk;
        const state = JSON.parse(input), before = JSON.stringify(state);
        const outcomes = postOutcomes(state, {now: Date.parse('2026-10-22T12:00:00Z')});
        const context = outcomes.posts[0].publication_context;
        assert.equal(context.status, 'recorded');
        Object.assign(process.env, {NODE_ENV:'production', DASHBOARD_USERNAME:'fixture-reader',
            DASHBOARD_PASSWORD:'fixture-only', GITHUB_TOKEN:'fixture-only', GIST_ID:'fixture_outcomes',
            THEHEAT_STATE_BACKEND:'gist'});
        Date.now = () => Date.parse('2026-10-22T12:00:00Z');
        const reads = [];
        globalThis.fetch = async (url, options) => {
            assert.ok(!options?.method || options.method === 'GET'); reads.push(String(url));
            if (String(url) === 'https://api.github.com/gists/fixture_outcomes')
                return Response.json({files:{'state.json':{content:JSON.stringify(state)}}});
            if (String(url).endsWith('/actions/runs?per_page=10')) return Response.json({workflow_runs:[]});
            throw new Error('Unexpected external request');
        };
        const {GET} = await import('./app/api/dashboard/route.js');
        assert.equal((await GET(new Request('http://localhost/api/dashboard'))).status, 401);
        assert.equal(reads.length, 0);
        const response = await GET(new Request('http://localhost/api/dashboard', {headers:{
            authorization:'Basic '+Buffer.from('fixture-reader:fixture-only').toString('base64')}}));
        assert.equal(response.status, 200); assert.equal(reads.length, 2);
        const body = await response.json();
        assert.deepEqual(body.productHealth.post_outcomes, outcomes);
        const html = renderToStaticMarkup(React.createElement(History, {outcomes:body.productHealth.post_outcomes}));
        assert.match(html, /Recorded type: monthly high/);
        assert.match(html, /Source evidence matches the published revision/);
        assert.doesNotMatch(html, /unbound_writer_angle|DO_NOT_DISPLAY_FULL_SOURCE/);
        assert.equal(JSON.stringify(state), before);
        console.log(JSON.stringify({context, outcomes, html, unauthenticated_reads:0,
            intercepted_existing_GET_reads:reads.length, real_external_calls:0}));
    """
    node = shutil.which("node")
    assert node, "Node24 is required for the actual cross-runtime reader/view"
    result = subprocess.run([node, "--input-type=module", "--eval", script],
        cwd=ROOT / "dashboard", input=json.dumps(state), text=True, capture_output=True,
        timeout=15, env={key: value for key, value in os.environ.items()
                        if key in {"PATH", "LC_ALL", "NETRC", "no_proxy", "NO_PROXY"}})
    (tmp_path / "node-result.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["context"]["source"]["bundle_sha256"] == fingerprint(
        state["drafts"][0]["review_context"]["two_bot"]["bundle"])
    assert output["outcomes"]["posts"][0]["observations"][0]["counts"]["likes"] == 0
    assert output["intercepted_existing_GET_reads"] == 2
    assert output["unauthenticated_reads"] == output["real_external_calls"] == 0
    assert state == before
