"""ROUTE repair R2 (root c749 checkpoint), sender side: the route outbox dispatches references only
(``senderDispatchInputs`` from the REAL Node module), bot.yml maps them into the run-step env, and
the REAL ``run_manual_tweet`` resolves the exact approved bytes from state, re-verifies everything
and never logs them. The sender REFUSES at its write-first claim (state write refused), so nothing
is published; ``post_tweet`` is a recording mock that must not be reached. Legacy dispatch is unchanged.

OFFLINE: mocked storage/platform (the existing tests/test_revision_posting.py fixture), invented text.
Red: receipts/red-review3-r2-sender-plaintext.txt, red-review3-r2-sender-print.txt.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import yaml

from src.editorial.revisions import invalidate_text, record_human_review
from src.orchestrator import posting
from src.state import DEFAULT_STATE
from tests.real_closure import route_harness as h
from tests.revision_helpers import bind_reviewed_draft
from tests.test_revision_posting import external  # noqa: F401  (pytest fixture: mocked storage/platform/safety)

pytestmark = pytest.mark.usefixtures("automatic_publication_release")
ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "PRIVATE unpublished approved copy: Invented Ford reached 41 C today."
INTENT = "11111111-2222-4333-8444-555555555555"
INPUT = re.compile(r"\$\{\{ github\.event\.inputs\.([a-z_]+) \}\}")


def _draft() -> dict:
    draft = {"id": "draft_route_sender", "event_id": "event_route_sender", "type": "monthly_high", "text": PRIVATE,
             "created_at": posting._utc_now_iso(), "updated_at": posting._utc_now_iso(),
             "approval_policy": {"mode": "manual", "can_auto_approve": False},
             "review_context": {"two_bot": {"bundle": {"event_id": "event_route_sender", "signal_kind": "monthly_high",
                                                       "current_facts": [{"label": "temperature", "value": 41}]}}}}
    return bind_reviewed_draft(draft, "manual", INTENT)


def _state(draft: dict) -> Any:
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    return state


def _safety() -> MagicMock:
    """The external fixture's recording safety mock (typed for direct mypy)."""
    return cast(MagicMock, posting.run_safety_pipeline)


def _dispatch_inputs() -> dict:
    """The exact inputs the REAL route outbox sends for this draft and intent."""
    script = ("import('./lib/gist-sender-outbox.js').then(m => process.stdout.write(JSON.stringify("
              "m.senderDispatchInputs({ id: process.argv[1], text: process.argv[3] }, { publish_intent_id: process.argv[2] }))))")
    done = subprocess.run([h.NODE, "-e", script, "draft_route_sender", INTENT, PRIVATE], cwd=h.DASHBOARD, env=h.base_env(),
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def _run_step_env(inputs: dict) -> dict[str, str]:
    """bot.yml's Run bot step env for a workflow_dispatch with these inputs (input expressions only)."""
    workflow = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(inputs) <= set(workflow["on"]["workflow_dispatch"]["inputs"]), "every dispatched input is declared"
    step = next(s for s in workflow["jobs"]["run"]["steps"] if s.get("name") == "Run bot")
    return {key: inputs.get(match[1], "") for key, value in step["env"].items() if (match := INPUT.fullmatch(value))}


def test_route_dispatch_and_step_env_carry_no_text_and_the_refusing_sender_resolves_exact_bytes(external, monkeypatch, capsys):  # noqa: F811
    storage, send = external
    storage.write_state.return_value = False  # refusing sender: the write-first publish claim cannot be saved
    inputs = _dispatch_inputs()
    assert inputs == {"mode": "manual_tweet", "draft_id": "draft_route_sender", "publish_intent_id": INTENT, "text_source": "state"}
    env = _run_step_env(inputs)
    assert env == {"TWEET_TEXT": "", "DRAFT_ID": "draft_route_sender", "PUBLISH_INTENT_ID": INTENT, "THEHEAT_SENDER_TEXT_SOURCE": "state"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    draft = _draft()
    state = _state(draft)
    run: dict = {}
    posting.run_manual_tweet(state, run)
    out = capsys.readouterr()
    _safety().assert_called_once_with(PRIVATE)  # resolved from state, exact bytes, after every check
    send.assert_not_called()  # the claim was refused before any egress
    assert storage.write_state.called, "the write-first claim was attempted"
    row = state["publish_ledger"]["event_route_sender"]
    assert (row["intent_id"], row["phase"]) == (INTENT, "not_sent")
    assert PRIVATE not in out.out and PRIVATE not in out.err and "41 C" not in out.out
    assert "text resolved from state; not logged" in out.out
    assert PRIVATE not in json.dumps(run)


@pytest.mark.parametrize("case", ["changed_text", "other_intent", "text_and_reference", "unknown_source", "missing_draft"])
def test_reference_dispatch_refuses_before_safety_when_state_does_not_bind_it(external, monkeypatch, capsys, case):  # noqa: F811
    storage, send = external
    draft = _draft()
    env = {"TWEET_TEXT": "", "DRAFT_ID": draft["id"], "PUBLISH_INTENT_ID": INTENT, "THEHEAT_SENDER_TEXT_SOURCE": "state"}
    if case == "changed_text":  # edited after approval: the binding no longer matches
        invalidate_text(draft, "A different private text after approval.")
        record_human_review(draft)
        draft["status"] = "approved"
    elif case == "other_intent":
        env["PUBLISH_INTENT_ID"] = "21111111-2222-4333-8444-555555555555"
    elif case == "text_and_reference":
        env["TWEET_TEXT"] = PRIVATE
    elif case == "unknown_source":
        env["THEHEAT_SENDER_TEXT_SOURCE"] = "input"
    else:
        env["DRAFT_ID"] = "draft_unknown"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    posting.run_manual_tweet(_state(draft))
    _safety().assert_not_called()
    send.assert_not_called()
    out = capsys.readouterr().out
    assert PRIVATE not in out and "A different private text" not in out


def test_a_reference_dispatch_that_passes_every_check_hands_the_exact_state_bytes_to_the_transport(external, monkeypatch):  # noqa: F811
    storage, send = external  # recording mocks: nothing is published
    for key, value in {"TWEET_TEXT": "", "DRAFT_ID": "draft_route_sender", "PUBLISH_INTENT_ID": INTENT, "THEHEAT_SENDER_TEXT_SOURCE": "state"}.items():
        monkeypatch.setenv(key, value)
    draft = _draft()
    posting.run_manual_tweet(_state(draft))
    send.assert_called_once_with(PRIVATE, media_png=None, alt_text=None)
    assert draft["status"] == "posted"


def test_legacy_text_dispatch_is_unchanged(external, monkeypatch, capsys):  # noqa: F811
    storage, send = external
    for key, value in {"TWEET_TEXT": PRIVATE, "DRAFT_ID": "draft_route_sender", "PUBLISH_INTENT_ID": INTENT}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("THEHEAT_SENDER_TEXT_SOURCE", raising=False)
    draft = _draft()
    posting.run_manual_tweet(_state(draft))
    send.assert_called_once_with(PRIVATE, media_png=None, alt_text=None)
    assert f"[manual] Posting: {PRIVATE}" in capsys.readouterr().out, "legacy logging unchanged (pre-existing root decision)"
