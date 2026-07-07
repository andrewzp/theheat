# Row 8 — FPP weekly rollup: the representativeness number

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. Read-only computation + one weekly issue + a dashboard card;
> the Python↔JS mirror rule APPLIES here (shared match-stage logic) → mirror tests
> required; one codex round at the end.

**Goal:** Every Monday, one number answers Andrew's question: *of the verified major
extreme-weather events the news lane surfaced this week, how many did we detect, draft,
and post?* — archived immutably per week, with the current rolling view on the
dashboard.

**Architecture:** The 7-day state windows (`news_events`, `candidates_log` — both pruned
at 7 days, `src/state.py:1834-1835`) align exactly with a weekly cadence, so a
Monday-gated sentinel step can compute the week's parity from live state with no new
state keys: **the immutable archive is the issue itself** (one NEW dated issue per week,
labeled, never updated — unlike the update-in-place watches). The matcher extends the
existing conservative `_news_event_matched` boolean into a STAGE function
(posted > drafted > detected > missed), mirrored into `dashboard/lib/source-health.js`
for a live rolling card.

**Honest scope (stated on every surface):** FPP v1 measures parity on the verticals the
news lane retrieves — `fire` + `heat_mortality`, ≤10 events/cycle — a selection-biased
denominator that widens with row 10. The number is meaningless until
`THEHEAT_NEWSWORTHINESS_ENABLED=1` has been live ≥7 days (the issue says "insufficient
data" until then rather than reading silently green — the coverage-watch precedent).

## File map (one PR)

- Modify: `scripts/source_health_sentinel.py`
- Modify: `dashboard/lib/source-health.js`, `dashboard/app/api/dashboard/route.js` or the payload builder it uses (follow `buildSourceHealthPayload`), `dashboard/app/components/` (one new card), `dashboard/app/page.js`
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/test_source_health_sentinel.py`, `dashboard/tests/source-health.test.js`

Branch: `git checkout main && git pull && git checkout -b feat/fpp-weekly-rollup`

---

### Task 1: The match-stage function (Python) — extend, don't fork, the news-gap matcher

**Files:** `scripts/source_health_sentinel.py`, tests beside the news-gap tests.

**Interfaces:**
- Consumes: the existing `_news_event_matched(ev, candidates, drafts)` internals
  (`scripts/source_health_sentinel.py:1151-1172`): `_NEWS_KIND_FAMILIES`,
  `_news_match_tokens`, `_token_in`.
- Produces: `news_event_match_stage(ev, candidates, drafts) -> str` returning one of
  `"posted" | "drafted" | "detected" | "missed" | "unmatchable"`, where: posted = token
  match against a draft with `status == "posted"`; drafted = token match against any
  other draft; detected = family+token match against `candidates_log` rows; missed =
  usable tokens but no match anywhere; unmatchable = no usable place tokens (excluded
  from both numerator AND denominator — never silently counted either way).
  `_news_event_matched` is then reimplemented as
  `return news_event_match_stage(ev, candidates, drafts) != "missed"` so the news-gap
  watch's behavior is BYTE-IDENTICAL for its purposes (unmatchable stays treated as
  matched there, exactly as today's early-return does).

- [ ] **Step 1: Failing tests** — replay the matcher's own semantics per stage:

```python
class TestNewsEventMatchStage:
    _EV = {"kind": "fire", "headline": "Alpine fire kills 3",
           "place": {"country": "United States", "name": "Colorado Springs"}}

    def test_posted_beats_drafted_beats_detected(self):
        cand = [{"event_id": "x", "category": "fire", "type": "fire",
                 "city": "Colorado Springs", "where": "Colorado Springs", "date": "d"}]
        pending = [{"text": "fire near Colorado Springs", "type": "fire", "status": "pending"}]
        posted = [{"text": "fire near Colorado Springs", "type": "fire", "status": "posted"}]
        assert news_event_match_stage(self._EV, cand, posted) == "posted"
        assert news_event_match_stage(self._EV, cand, pending) == "drafted"
        assert news_event_match_stage(self._EV, cand, []) == "detected"

    def test_missed_and_unmatchable(self):
        assert news_event_match_stage(self._EV, [], []) == "missed"
        assert news_event_match_stage({"kind": "fire", "headline": ""}, [], []) == "unmatchable"

    def test_news_gap_behavior_unchanged(self):
        # the news-gap watch treats unmatchable as matched (no noise) — must survive.
        assert _news_event_matched({"kind": "fire", "headline": ""}, [], []) is True
```

- [ ] **Step 2:** FAIL → **Step 3:** implement (the stage function is the old body with
the draft loop split by status, posted checked first) → **Step 4:** the ENTIRE existing
news-gap test class must still pass unchanged → **Step 5:** commit
`"feat(sentinel): news_event_match_stage — the FPP funnel stage per news event (news-gap behavior unchanged)"`.

### Task 2: The weekly rollup + archive issue

**Files:** `scripts/source_health_sentinel.py`, tests beside the other watch tests.

**Interfaces:**
- Produces:

```python
FPP_ISSUE_LABEL = "fpp-weekly"
FPP_MARKER = "<!-- fpp-weekly-rollup -->"
FPP_MIN_EVENTS = 3  # below this, report insufficient_data, never a green %


def fpp_rollup(news_events, candidates, drafts, *, now) -> dict:
    """{week_of, verticals, total, unmatchable, posted, drafted, detected,
    missed, parity: {detected_pct, drafted_pct, posted_pct} | None,
    insufficient: bool, events: [{headline, kind, stage}]}
    Denominator = total - unmatchable. parity None when insufficient."""


def build_fpp_issue_title(now) -> str:
    # "FPP week of 2026-07-06: posted 2/5, drafted 3/5, detected 4/5 (fire+heat verticals)"
    # or "...: insufficient data (N verified events)"


def build_fpp_issue_body(rollup) -> str:
    # marker + the three-stage funnel + a per-event table (headline | kind |
    # stage) + the scope caveat paragraph VERBATIM: denominator is the news
    # lane's own capped retrieval (fire + heat_mortality, ≤10/cycle) — parity
    # on what the lane sees, not on the whole world; widens with row 10.
```

- Monday gate + one-shot: in `main()`, after the news-gap block — run ONLY when
  `datetime.now(timezone.utc).weekday() == 0` (the `sea_ice.py:13` precedent) AND no
  issue labeled `fpp-weekly` already exists whose title contains this week's
  `week_of` date (the sentinel runs hourly; the existence check is the idempotency
  guard — same `gh issue list --label fpp-weekly --json title` machinery as
  `_open_queue_watch_issue`, but matching on the dated title). Create-only: the weekly
  issue is never updated or auto-closed — it IS the archive. Andrew closes them at
  leisure.

- [ ] Failing tests: rollup math (5 events → stages counted, percentages), the
insufficient path (<3 usable events → `insufficient=True`, `parity=None`, title says
insufficient), the unmatchable exclusion (denominator shrinks), the Monday/idempotency
plan logic (pure helper `plan_fpp_action(rollup, existing_titles, now) -> dict | None`
— None on non-Mondays, None when this week's title already exists).
- [ ] Implement → PASS → commit
`"feat(sentinel): FPP weekly rollup — one immutable parity issue per Monday, insufficient-data guarded"`.

### Task 3: The JS mirror + dashboard card

**Files:** `dashboard/lib/source-health.js` (mirror `newsEventMatchStage` +
`fppRollup`, wired into `buildSourceHealthPayload` as `fpp: fppRollup(...)` with the
same constants and a `// MUST match scripts/source_health_sentinel.py` comment — the
queue-watch mirror precedent at line ~377), a new
`dashboard/app/components/FppCard.js` following `Hot10Card.js`'s exact card shape
(title "Front-page parity (rolling 7d)", the three percentages or "insufficient data
(N events)" plus the scope caveat as the stat-label line, a "flag dark" state when
`news_events` is empty), wired into `dashboard/app/page.js` beside `Hot10Card`.

- [ ] Failing JS mirror tests in `dashboard/tests/source-health.test.js` replaying the
Python stage tests 1:1 (the `queueWatch` mirror-test precedent at lines ~901-934).
- [ ] Implement → `cd dashboard && npm test` → PASS → commit
`"feat(dashboard): FPP rolling card + JS mirror of the match-stage rollup"`.
- [ ] **Deploy note for the PR body:** dashboard deploy is MANUAL `vercel --prod`
after merge.

### Task 4: Version, changelog, gates, PR, codex, live verify

- [ ] VERSION bump + CHANGELOG entry (name the scope caveat explicitly).
- [ ] Full gates INCLUDING `cd dashboard && npm test` and the dashboard build.
- [ ] PR + one codex-xhigh round — ask it to attack: does reimplementing
`_news_event_matched` on top of the stage function change ANY news-gap outcome
(byte-level behavior diff); the Monday idempotency under the hourly cron (24 runs every
Monday — exactly one issue); percentage math on zero denominators; JS↔Python mirror
drift.
- [ ] Merge on green + verify squash; `vercel --prod` the dashboard.
- [ ] **Live verify:** requires the master flag live ≥7 days (track-0). First Monday
after that: exactly one `fpp-weekly` issue with sane numbers; hand-check every listed
event's stage against the dashboard; the card matches the issue's rolling equivalent.

**Success criteria:** a weekly FPP series exists from the first post-flip Monday; the
number is cited in handoffs; misses become row-10/row-12 evidence instead of anecdotes.
