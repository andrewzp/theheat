"""Phase B — decouple the ship gate (auto-ship critic-PASS allowlist drafts).

Behind THEHEAT_AUTOSHIP_ON_CRITIC_PASS (default OFF). Covers the codex must-fixes:
  - approval_mode="auto" AND a delayed auto_approve_at are BOTH set (else nothing posts).
  - HARD tweet_type allowlist, NOT policy-mode inference.
  - fail-closed when critic metadata is absent / not a PASS.
  - posting-time freshness + one-shot idempotency guards inside process_due_drafts.
  - flag OFF == byte-for-byte current behavior; flag rollback stops pre-marked drafts.
"""

from __future__ import annotations

from copy import deepcopy

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE


def _fresh_state() -> dict:
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = []
    return state


def _critic_ctx(passed: bool = True, verdict: str = "PASS") -> dict:
    return {"two_bot": {"critic": {"passed": passed, "verdict": verdict}}}


def _save(bot_state, *, tweet_type="co2_milestone", event_id="e1", review_context=None,
          score=None, candidate_score=None):
    from src.orchestrator import common
    return common.save_draft(
        "CO2 crossed a grim threshold this week.",
        bot_state, tweet_type, event_id, score=score, candidate_score=candidate_score,
        review_context=review_context,
    )


def _only_draft(bot_state):
    return bot_state["drafts"][-1]


# ---------------------------------------------------------------------------
# draft_save eligibility
# ---------------------------------------------------------------------------

class TestAutoshipEligibility:
    def test_flag_off_leaves_draft_manual(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", raising=False)
        bot_state = _fresh_state()
        assert _save(bot_state, review_context=_critic_ctx()) is True
        d = _only_draft(bot_state)
        assert d["approval_mode"] == "manual"
        assert "auto_approve_at" not in d
        assert "autoship_on_critic_pass" not in d

    def test_flag_on_allowlist_critic_pass_arms_autoship(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="co2_milestone", review_context=_critic_ctx())
        d = _only_draft(bot_state)
        assert d["approval_mode"] == "auto"
        assert d.get("auto_approve_at")  # delayed window set
        assert d.get("autoship_on_critic_pass") is True

    def test_hot10_in_allowlist(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="hot10", event_id="h1", review_context=_critic_ctx())
        assert _only_draft(bot_state).get("autoship_on_critic_pass") is True

    def test_no_critic_metadata_is_fail_closed(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="co2_milestone", review_context={})  # no two_bot.critic
        d = _only_draft(bot_state)
        assert d["approval_mode"] == "manual"
        assert "autoship_on_critic_pass" not in d

    def test_critic_not_pass_is_fail_closed(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="co2_milestone",
              review_context=_critic_ctx(passed=False, verdict="KILL"))
        assert _only_draft(bot_state)["approval_mode"] == "manual"

    def test_non_allowlist_type_never_arms(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        # 'record' is low-sensitivity suggested_auto but NOT in the hard allowlist.
        _save(bot_state, tweet_type="record", event_id="r1", review_context=_critic_ctx())
        d = _only_draft(bot_state)
        assert d["approval_mode"] == "manual"
        assert "autoship_on_critic_pass" not in d

    def test_human_impact_type_never_arms(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="fire", event_id="f1", review_context=_critic_ctx())
        assert _only_draft(bot_state)["approval_mode"] == "manual"

    def _strong(self):
        return EditorialScore(category="co2_milestone", severity=80, novelty=80,
                              timeliness=80, confidence=80, shareability=80, sensitivity=0,
                              total=80, threshold=60, reasons=[])

    def test_armed_auto_allowlist_flag_on_critic_pass_is_guarded(self, monkeypatch):
        """codex follow-up: an armed_auto (strong) allowlist draft must route through
        the guarded autoship path when the flag is ON, not bare policy_auto."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="co2_milestone", review_context=_critic_ctx(),
              score=self._strong(), candidate_score={"total": 80})  # is_strong -> armed_auto
        d = _only_draft(bot_state)
        assert d["approval_policy"]["mode"] == "armed_auto"
        assert d["approval_mode"] == "auto"
        assert d.get("autoship_on_critic_pass") is True  # guarded, not bare policy_auto

    def test_armed_auto_allowlist_flag_on_no_critic_is_fail_closed(self, monkeypatch):
        """An armed_auto allowlist draft with NO critic PASS must NOT bare-post when
        the flag is ON — it stays manual (fail-closed)."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="co2_milestone", review_context={},  # no critic
              score=self._strong(), candidate_score={"total": 80})
        d = _only_draft(bot_state)
        assert d["approval_mode"] == "manual"
        assert "auto_approve_at" not in d
        assert "autoship_on_critic_pass" not in d

    def test_armed_auto_allowlist_flag_off_is_unchanged(self, monkeypatch):
        """Flag OFF: an armed_auto allowlist draft keeps its current policy_auto path."""
        monkeypatch.delenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", raising=False)
        bot_state = _fresh_state()
        _save(bot_state, tweet_type="co2_milestone", review_context=_critic_ctx(),
              score=self._strong(), candidate_score={"total": 80})
        d = _only_draft(bot_state)
        assert d["approval_mode"] == "policy_auto"
        assert d.get("auto_approve_at")
        assert "autoship_on_critic_pass" not in d


# ---------------------------------------------------------------------------
# process_due_drafts posting-time guards
# ---------------------------------------------------------------------------

def _marked_due_draft(*, created_offset_h=0, attempted=False):
    from src.orchestrator.common import _utc_now_iso, _utc_after_minutes_iso
    from src.orchestrator.common import _utc_now
    from datetime import timedelta
    created = (_utc_now() - timedelta(hours=created_offset_h)).isoformat().replace("+00:00", "Z")
    draft = {
        "id": "draft_x", "text": "CO2 crossed a grim threshold this week.",
        "type": "co2_milestone", "event_id": "evt_co2", "status": "pending",
        "created_at": created, "updated_at": created,
        "auto_approve_at": _utc_after_minutes_iso(-5),  # due (5 min ago)
        "approval_mode": "auto",
        "approval_policy": {"mode": "suggested_auto", "can_auto_approve": True},
        "autoship_on_critic_pass": True,
    }
    if attempted:
        draft["autoship_attempted"] = True
    return draft


def _run_due(bot_state, monkeypatch, post_result="posted"):
    from src.orchestrator import posting
    calls = {"n": 0}

    def fake_post_approved(draft, state):
        calls["n"] += 1
        return post_result

    monkeypatch.setattr(posting, "post_approved", fake_post_approved)
    posting.process_due_drafts(bot_state)
    return calls["n"]


class TestProcessDueGuards:
    def test_fresh_marked_draft_posts(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        bot_state["drafts"] = [_marked_due_draft(created_offset_h=1)]
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 1
        assert bot_state["drafts"][0]["status"] == "posted"

    def test_stale_marked_draft_blocked(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        monkeypatch.setenv("THEHEAT_AUTOSHIP_MAX_AGE_H", "36")
        bot_state = _fresh_state()
        bot_state["drafts"] = [_marked_due_draft(created_offset_h=48)]  # older than 36h
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 0
        d = bot_state["drafts"][0]
        assert d["status"] == "pending"
        assert d["approval_mode"] == "manual"
        assert "auto_approve_at" not in d

    def test_already_attempted_marked_draft_blocked(self, monkeypatch):
        """One-shot idempotency: a marked draft whose prior attempt didn't confirm
        'posted' is handed to a human, never blind-retried (double-post risk)."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        bot_state["drafts"] = [_marked_due_draft(created_offset_h=1, attempted=True)]
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 0
        assert bot_state["drafts"][0]["approval_mode"] == "manual"

    def test_flag_rollback_demotes_marked_draft(self, monkeypatch):
        """Flipping the flag OFF stops auto-shipping even pre-marked drafts."""
        monkeypatch.delenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", raising=False)
        bot_state = _fresh_state()
        bot_state["drafts"] = [_marked_due_draft(created_offset_h=1)]
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 0
        assert bot_state["drafts"][0]["approval_mode"] == "manual"

    def test_failed_post_demotes_to_manual(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        bot_state["drafts"] = [_marked_due_draft(created_offset_h=1)]
        _run_due(bot_state, monkeypatch, "failed")
        d = bot_state["drafts"][0]
        assert d["status"] == "pending"
        assert d["approval_mode"] == "manual"  # unknown outcome -> human, no blind retry

    def test_rate_limited_keeps_retryable(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        bot_state["drafts"] = [_marked_due_draft(created_offset_h=1)]
        _run_due(bot_state, monkeypatch, "rate_limited")
        d = bot_state["drafts"][0]
        # clean pre-post rejection -> safe to retry next cycle (still auto, attempt cleared)
        assert d.get("approval_mode") == "auto"
        assert d.get("autoship_attempted") is not True

    def test_attempt_marked_and_touched_before_post(self, monkeypatch):
        """codex P1: the one-shot marker is set AND updated_at bumped before the
        post, so a crash mid-post can't drop it and blind-retry (double-post)."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        from src.orchestrator import posting
        bot_state = _fresh_state()
        draft = _marked_due_draft(created_offset_h=1)
        before_updated = draft["updated_at"]
        bot_state["drafts"] = [draft]
        seen = {}

        def fake_post_approved(d, state):
            seen["attempted"] = d.get("autoship_attempted")
            seen["updated_at"] = d.get("updated_at")
            return "posted"

        monkeypatch.setattr(posting, "post_approved", fake_post_approved)
        posting.process_due_drafts(bot_state)
        assert seen["attempted"] is True
        assert seen["updated_at"] != before_updated  # touched -> wins merge

    def test_stale_source_date_blocks_even_when_freshly_created(self, monkeypatch):
        """codex P2: a freshly-created draft built from stale upstream data (old
        bundle 'when') must not auto-ship."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        monkeypatch.setenv("THEHEAT_AUTOSHIP_MAX_AGE_H", "36")
        bot_state = _fresh_state()
        draft = _marked_due_draft(created_offset_h=0)  # fresh queue age
        draft["review_context"] = {"two_bot": {"bundle": {"when": "2026-06-10"}}}  # 6 days stale
        bot_state["drafts"] = [draft]
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 0
        assert bot_state["drafts"][0]["approval_mode"] == "manual"

    def test_transition_policy_auto_with_critic_pass_is_guarded_and_posts(self, monkeypatch):
        """Activation-window hole: a policy_auto allowlist draft saved while the flag
        was OFF (no marker) must be pulled into the guarded path when the flag is ON
        and post only with a critic PASS."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        from src.orchestrator.common import _utc_now, _utc_after_minutes_iso
        from datetime import timedelta
        bot_state = _fresh_state()
        created = (_utc_now() - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        bot_state["drafts"] = [{
            "id": "d_trans", "text": "CO2 crossed a grim threshold this week.",
            "type": "co2_milestone", "event_id": "evt_trans", "status": "pending",
            "created_at": created, "updated_at": created,
            "auto_approve_at": _utc_after_minutes_iso(-5),
            "approval_mode": "policy_auto",
            "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
            "review_context": _critic_ctx(),  # has a critic PASS
        }]
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 1

    def test_transition_policy_auto_without_critic_pass_blocked(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        from src.orchestrator.common import _utc_now, _utc_after_minutes_iso
        from datetime import timedelta
        bot_state = _fresh_state()
        created = (_utc_now() - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        bot_state["drafts"] = [{
            "id": "d_trans2", "text": "CO2 crossed a grim threshold this week.",
            "type": "co2_milestone", "event_id": "evt_trans2", "status": "pending",
            "created_at": created, "updated_at": created,
            "auto_approve_at": _utc_after_minutes_iso(-5),
            "approval_mode": "policy_auto",
            "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
            "review_context": {},  # no critic metadata
        }]
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 0
        assert bot_state["drafts"][0]["approval_mode"] == "manual"

    def test_transition_draft_rate_limited_stays_retryable(self, monkeypatch):
        """A transition-window draft (no marker) that rate-limits must stay retryable
        too — the retry-clear keys on autoship_attempted, not the marker."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        from src.orchestrator.common import _utc_now, _utc_after_minutes_iso
        from datetime import timedelta
        bot_state = _fresh_state()
        created = (_utc_now() - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        bot_state["drafts"] = [{
            "id": "d_rl", "text": "CO2 crossed a grim threshold this week.",
            "type": "co2_milestone", "event_id": "evt_rl", "status": "pending",
            "created_at": created, "updated_at": created,
            "auto_approve_at": _utc_after_minutes_iso(-5),
            "approval_mode": "policy_auto",
            "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
            "review_context": _critic_ctx(),
        }]
        _run_due(bot_state, monkeypatch, "rate_limited")
        d = bot_state["drafts"][0]
        assert d.get("autoship_attempted") is not True  # cleared -> retryable next cycle
        assert d["approval_mode"] != "manual"

    def test_already_posted_event_blocked(self, monkeypatch):
        """codex follow-up: a marked draft whose event_id is already posted must not
        double-post (defense vs a same-event second draft from a state merge)."""
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        bot_state = _fresh_state()
        bot_state["posted_events"] = ["evt_co2"]
        bot_state["drafts"] = [_marked_due_draft(created_offset_h=1)]  # event_id evt_co2
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 0
        assert bot_state["drafts"][0]["approval_mode"] == "manual"

    def test_unmarked_armed_auto_draft_unchanged(self, monkeypatch):
        """Flag OFF + a normal armed_auto draft (no marker) posts exactly as today."""
        monkeypatch.delenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", raising=False)
        from src.orchestrator.common import _utc_after_minutes_iso
        bot_state = _fresh_state()
        bot_state["drafts"] = [{
            "id": "d_armed", "text": "leaderboard", "type": "hot10", "event_id": "ev_armed",
            "status": "pending", "created_at": "2026-06-16T00:00:00Z",
            "auto_approve_at": _utc_after_minutes_iso(-5),
            "approval_mode": "policy_auto",
            "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
        }]
        posts = _run_due(bot_state, monkeypatch, "posted")
        assert posts == 1
        assert bot_state["drafts"][0]["status"] == "posted"
