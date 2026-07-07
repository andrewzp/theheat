# Row 6 — The daily editor brief: the queue stops being where stories die

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. Read-only over state + one auto-maintained GitHub issue —
> low risk; a single codex round at the end suffices (no posting/gate/state-write code).

**Goal:** Every day Andrew sees, without opening the dashboard, exactly what's waiting
for him: the pending queue ranked by what needs him NOW (aging human-gated drafts,
closing forecast windows, high scores), with one-tap dashboard links — so Bavi-class
drafts stop dying unreviewed.

**Architecture:** A new sentinel watch (`editor_brief`) reusing the proven quartet
grammar (pure function → build body → plan action → create/update/close via `gh`),
riding the existing hourly sentinel run and its `GITHUB_TOKEN` (issues: write). One
issue, marker-tagged, updated in place; closes when the queue is empty. Channel decision
(deliberately): a GitHub issue — Andrew already receives sentinel issues; zero new
infrastructure; a push-notification channel can subscribe to the issue later. **No JS
mirror**: the dashboard's drafts view already renders the queue itself; the brief is a
notification surface, not shared classification logic (document this deviation in the PR
body — the Python↔JS mirror rule covers shared source-health classification, which this
is not).

**Tech Stack:** existing sentinel + `gh` CLI only.

## Global Constraints

All of [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
§Standing rules, plus:
- Read-only with respect to state: the brief NEVER mutates drafts (rejection is row 3's
  sweep; approval is Andrew's).
- Draft text in the issue body is truncated to 140 chars per row — the issue is a
  pointer, not a mirror; the dashboard is where review happens.
- The issue must never flap: `plan_editor_brief_action` only updates when the rendered
  body actually differs (the queue-watch diff pattern).

## File map (one PR)

- Modify: `scripts/source_health_sentinel.py`
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/test_source_health_sentinel.py`

Branch: `git checkout main && git pull && git checkout -b feat/editor-brief`

---

### Task 1: The pure function + body builder

**Files:** `scripts/source_health_sentinel.py`, tests in
`tests/test_source_health_sentinel.py` (new classes beside `TestQueueWatch`, ~line 655).

**Interfaces:**
- Consumes: `state["drafts"]` rows — keys `status`, `type`, `created_at`, `tweet_date`,
  `score` (dict with `total`), `approval_mode`, `auto_approve_at`, `text`, `id`; the
  existing helpers `_is_auto_owned` (line ~946) and `_parse_ts`.
- Produces (all in the sentinel, beside the queue-watch block):

```python
EDITOR_BRIEF_TITLE = "Editor brief: what the queue needs from you"
EDITOR_BRIEF_MARKER = "<!-- source-health-editor-brief -->"
EDITOR_BRIEF_MAX_ROWS = 10
EDITOR_BRIEF_URGENT_AGE_H = 24


def editor_brief(drafts: list[dict] | None, *, now: datetime) -> list[dict]:
    """One finding per human-gated pending draft, ranked needs-you-first.

    Ranking key (descending urgency):
      1. forecast window closing (tweet_date == today or tomorrow, for any
         draft — an elapsed-forecast draft is row 3's sweep's job, not ours)
      2. age >= EDITOR_BRIEF_URGENT_AGE_H
      3. score.total
    Auto-owned drafts (approval_mode auto/policy_auto with auto_approve_at)
    are excluded — the machine already owns them.
    Returns [] when nothing is pending → the issue auto-closes.
    """
```

Each finding dict: `{id, type, age_h: int, score: int, tweet_date: str|None,
urgent: bool, closing: bool, preview: str}` (preview = first 140 chars of `text`).

`build_editor_brief_body(findings) -> str`: marker first line; an "⚡ Needs you now"
section (urgent or closing rows) then "— Fresh" for the rest, capped at
`EDITOR_BRIEF_MAX_ROWS` total with a `(+N more on the dashboard)` tail; each row
rendered as
`- **{type}** · score {score} · {age_h}h old{" · forecast {tweet_date}" if tweet_date}` +
a blockquoted preview; footer links the dashboard and states the auto-maintained
contract ("closes itself when the queue is empty").

- [ ] **Step 1: Failing tests** (today-relative timestamps built from
`datetime.now(timezone.utc)`; follow `TestQueueWatch`'s `_draft` fixture style):

```python
class TestEditorBrief:
    def _draft(self, *, hours_old=2.0, dtype="fire", score=70, status="pending",
               tweet_date=None, auto=False, text="draft text"):
        now = datetime.now(timezone.utc)
        d = {
            "id": f"d_{dtype}_{hours_old}",
            "status": status,
            "type": dtype,
            "created_at": (now - timedelta(hours=hours_old)).isoformat().replace("+00:00", "Z"),
            "score": {"total": score},
            "text": text,
        }
        if tweet_date:
            d["tweet_date"] = tweet_date
        if auto:
            d["approval_mode"] = "auto"
            d["auto_approve_at"] = now.isoformat().replace("+00:00", "Z")
        return d

    def test_ranks_closing_forecast_first_then_aging_then_score(self):
        today = datetime.now(timezone.utc).date().isoformat()
        drafts = [
            self._draft(dtype="all_time_high", score=90),
            self._draft(dtype="fire", hours_old=30.0, score=60),
            self._draft(dtype="absolute_extreme", score=50, tweet_date=today),
        ]
        findings = editor_brief(drafts, now=datetime.now(timezone.utc))
        assert [f["type"] for f in findings] == ["absolute_extreme", "fire", "all_time_high"]
        assert findings[0]["closing"] and findings[1]["urgent"]

    def test_excludes_auto_owned_and_non_pending(self):
        drafts = [self._draft(auto=True), self._draft(status="posted")]
        assert editor_brief(drafts, now=datetime.now(timezone.utc)) == []

    def test_empty_queue_returns_empty(self):
        assert editor_brief([], now=datetime.now(timezone.utc)) == []

    def test_body_sections_and_cap(self):
        drafts = [self._draft(dtype=f"t{i}", score=50 + i) for i in range(12)]
        findings = editor_brief(drafts, now=datetime.now(timezone.utc))
        body = build_editor_brief_body(findings)
        assert EDITOR_BRIEF_MARKER in body
        assert "more on the dashboard" in body
        assert body.count("score ") == EDITOR_BRIEF_MAX_ROWS
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (the ranking: build a sort key
`(not closing, not urgent, -score)` ascending — closing first, then urgent, then score
desc; `closing` = `tweet_date` in {today, tomorrow}; `urgent` = age ≥ 24h). **Step 4:**
Run → PASS. **Step 5:** Commit
`"feat(sentinel): editor_brief — ranked needs-you-now view of the pending queue"`.

### Task 2: Plan/apply quartet + main() wiring

Copy the queue-watch quartet verbatim with the brief's constants
(`plan_editor_brief_action(findings, open_issue)` — create when findings and no issue;
update only on body diff; close when findings empty and issue open;
`_open_editor_brief_issue` matches on `EDITOR_BRIEF_TITLE`;
`_create/_update/_close_editor_brief_issue` via the same `_run_gh` calls). Wire in
`main()` immediately after the queue-watch block (lines ~1387-1403) with the same
three-way apply shape.

- [ ] Failing tests first: `TestEditorBriefIssue` mirroring `TestQueueWatchIssue`
(~lines 729-746) — create/update/close/no-op transitions.
- [ ] Implement → PASS → commit
`"feat(sentinel): editor-brief issue plumbing — create/update/close, marker-tagged"`.

### Task 3: Version, changelog, gates, PR, live verify

- [ ] VERSION bump + CHANGELOG entry (name the Bavi-died-unreviewed motivation).
- [ ] Full gates green (the sentinel tests + the whole canary suite).
- [ ] PR; one codex-xhigh round (read-only surface — ask it to check: issue-flap risk
in the body diffing; the auto-owned exclusion matches `_is_auto_owned` semantics; no
state mutation anywhere; `gh` failure tolerance matches the other watches). Merge on
green + verify squash.
- [ ] **Live verify:** the next hourly sentinel run creates the issue (queue is
non-empty in prod); confirm ranking sanity by eye; approve/reject something on the
dashboard and confirm the next run updates or closes the issue.

**Success criteria:** Andrew can act on the queue from the issue alone; queue-watch
(#364) alarms become rare because the brief drives review before the 24h threshold;
no draft with a closing forecast window ever again ages out unseen.
