# Row 9 — Engagement capture: turn on the dormant lane, feed the corpus

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. Small PR; one codex round (it touches bot.yml and a read-only
> metrics path, no editorial gates).

**Goal:** Per-tweet likes/retweets/replies flow into state daily so the grading corpus
can compare its A–F grades against what readers actually did — FUTURE_STATE's "eval set
from actual performance," started.

**Key discovery (check-dormant-before-building):** the lane is ALREADY GENERAL. The
candidate pool (`_metric_candidate_tweet_ids`, `src/orchestrator/hot10.py:44-76`) pulls
from `publish_ledger` + ALL posted drafts (30-day lookback, 50 newest), not just Hot 10
tweets; `src/data/twitter_metrics.py` batches up to 100 ids into ONE
`tweepy.Client.get_tweets(ids, tweet_fields=["public_metrics"])` call; a once-per-day
gate (`_metric_source_seen_today`) means ~1 API read call per day total. Only two things
are Hot-10-coupled: the flag has NO bot.yml passthrough (so prod always resolves `"0"`),
and the invocation lives inside `run_leaderboard` (daily 12:00 UTC — which is fine).

**Blocking input (Andrew, before the flip):** confirm the X API tier in use allows
`GET /2/tweets` reads at ~30 calls/month (1 batched call/day). Even the free tier's
read cap covers this volume; verify against the current developer-portal numbers before
flipping (WebFetch the live page — do not trust remembered tier limits).

## File map (one PR + one flip)

- Modify: `.github/workflows/bot.yml` (one passthrough block)
- Modify: `dashboard/app/api/dashboard/route.js` payload or a small `/api/metrics`
  route (Task 3) + `dashboard/app/components/` (optional card)
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/test_main.py` already covers `_metrics_enabled` gating — extend only if
  Task 3 adds code.

Branch: `git checkout main && git pull && git checkout -b feat/engagement-capture`

---

### Task 1: The bot.yml passthrough

- [ ] **Step 1:** In `.github/workflows/bot.yml`, in the production env block (the
`THEHEAT_*` passthrough list, ~lines 259-301), add — matching the house pattern exactly
(10-space indent, rationale comment, activate/rollback commands):

```yaml
          # Twitter engagement metrics polling (dormant since built). Reads
          # public_metrics for the last 30d of posted tweets, one batched
          # API call per day, gated once-per-day in code. Feeds the grading
          # corpus (FUTURE_STATE eval-set). Code default stays "0".
          # Activate: gh variable set THEHEAT_METRICS_ENABLED --body 1 --repo andrewzp/theheat
          # Rollback: gh variable set THEHEAT_METRICS_ENABLED --body 0 --repo andrewzp/theheat
          THEHEAT_METRICS_ENABLED: ${{ vars.THEHEAT_METRICS_ENABLED || '0' }}
```

- [ ] **Step 2:** Verify placement mirrors its neighbors:
`grep -n -A2 "THEHEAT_METRICS_ENABLED" .github/workflows/bot.yml` and
`.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/bot.yml')); print('yaml ok')"`.
- [ ] **Step 3:** Commit `"feat(ci): THEHEAT_METRICS_ENABLED passthrough — the dormant engagement lane becomes flippable"`.

### Task 2: The flip + live verify (Andrew flips; any session verifies)

- [ ] Andrew (after the tier check): `gh variable set THEHEAT_METRICS_ENABLED --body 1 --repo andrewzp/theheat`
- [ ] Watcher, after the next 12:00 UTC leaderboard run: the run log shows the
`twitter_metrics` source row with `status=success` (or `skipped: No recent tweet ids`
if nothing posted in 30d — also healthy). `status=failed` with an auth error → check
Twitter credentials; `skipped: No Twitter credentials configured` → the four
TWITTER_* secrets aren't reaching the leaderboard job.
- [ ] Confirm `state["tweet_metrics"]` populates: `{tweet_id: {at, likes, retweets,
replies}}` (visible via the dashboard state or Andrew's gist view).

### Task 3: Surface it to the corpus (the actual point)

**Files:** `dashboard/app/api/dashboard/route.js` (or wherever the main payload is
assembled — follow how `hot10` reaches `payload.state`) + optionally one small card.

- [ ] **Step 1:** Expose `tweet_metrics` joined to posted drafts in the dashboard
payload: for each draft with `status=="posted"` and a `tweet_id`, attach
`metrics: state.tweet_metrics[tweet_id] ?? null`. The join key chain is verified:
`tweet_metrics[tweet_id]` ↔ `draft.tweet_id` ↔ `draft.type`/`draft.event_id`
(`src/orchestrator/posting.py:196-203` writes all three onto the draft at post time).
- [ ] **Step 2:** Update the daily-plan routine's instructions doc (the grading
routine reads the dashboard/gist): add one step — "record each graded-and-posted
draft's likes/retweets/replies next to its grade in DRAFT_CORPUS.md when metrics
exist." (Docs change to wherever the routine prompt lives — find it with
`grep -rln "daily plan" docs/ .github/` — as its own docs PR if the file is
routine-owned.)
- [ ] **Step 3:** Tests for whatever payload code was added; `cd dashboard && npm
test` green.
- [ ] **Step 4:** Commit `"feat(dashboard): posted drafts carry their engagement metrics — the corpus can grade against readers"`.

### Task 4: Version, changelog, gates, PR, codex

- [ ] VERSION bump + CHANGELOG entry. Full gates (incl. dashboard). PR + one
codex-xhigh round (ask: any way the metrics path can throw into the leaderboard run
— it must stay try/except-isolated as today; payload join correctness; no
secret/token leakage into the payload). Merge on green + verify squash; `vercel
--prod` if dashboard files changed.

**Success criteria:** 30 days post-flip there is an engagement column beside the
grades — enough to start asking "do A-grades outperform B-grades?" with data.
