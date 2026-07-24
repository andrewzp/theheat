# Handoff — 2026-07-24 · economics P2 executing; billing empty AGAIN is the gate; P2.1 batch lane is the open thread

> Wraps the 2026-07-23→24 session (post-restore health check → cost overrun found by the new
> ledger → P2.2 + P1.3 built under codex-xhigh loops → billing ran dry mid-flight).
> **`main` @ `15d8f34`, v0.9.108.0, tree clean.** Everything below is MERGED unless marked OPEN.
> This handoff's kickoff block encodes the state of PLAN-ECONOMICS-MASTER-v3 (§Execution status,
> updated this session) at `15d8f34` — if that plan doc has moved since, the repo copy wins.

## 🔴 GATE — the Anthropic balance is EMPTY again (Andrew-only)

Week 1 of restored production burned the top-up: the P0.6 ledger measured **~$1.74/day writer**
(~$13.89 over 8 days, 48–81 calls/day) + canaries + the Sunday full suite + PR-gate runs. The
budget watch fired [#461](https://github.com/andrewzp/theheat/issues/461) on 07-22 at the
70%/90% thresholds of the $14 budget — the alarm worked; the top-up wasn't sized for the
measured burn. As of 2026-07-24T01:58Z every writer call returns `credit balance is too low`
(`req_011CdL46tCVENsrxZz7roJhm`). The daily 09:17Z canary goes red on this class by design.

1. **Andrew: top up AND set Console auto-reload + monthly cap** (platform.claude.com → Plans &
   Billing) — the one P0 item only you can do; skipping it is why this recurred.
2. Then: `gh workflow run voice-regression.yml --repo andrewzp/theheat` → green = recovered.
3. While empty: cycles fail $0 (per-call breaker + cycle breaker), nothing posts wrongly,
   pending drafts age normally. No code action needed.

## ★ THE OPEN THREAD — P2.1 Batch API writer lane (build it in this session)

The dollar mover: 50% off input AND output, stacks with prompt caching. Design is settled in
[PLAN-ECONOMICS-MASTER-v3 §3 P2.1] and refined this session:

- **Submit** at cycle end (flag `THEHEAT_BATCH_WRITER_ENABLED`, code default `0`, bot.yml plumbs
  the repo var): after ALL $0 pre-writer predicates (incl. the new negative cache), serialize the
  slate — `custom_id = event_id`, one `MessageCreateParamsNonStreaming` per candidate with the
  SAME cached-system-block + user prompt the sync path builds (extract a shared
  `build_user_prompt()` from `write_tweet`), `output_config` schema riding (#463). Store
  `pending_writer_batches[batch_id] = {submitted_at, entries: {event_id: {bundle: to_dict, and
  the save_draft kwargs — source/city/tweet_date/legacy_type/cooldown_exempt/review_context/
  draft_metadata/score-total}}}` — new state key: DEFAULT_STATE + MERGE_SPEC + state_schema +
  sqlite list (4-point registration; contract tests enforce).
- **Collect** in the hourly `auto_publish_due` run (start of `process_due_drafts`) AND at drain
  start: retrieve → `ended` → results by custom_id → reconstruct `StoryBundle.from_dict` (write
  it + `RelatedSignal.from_dict`; to_dict is faithful, facts-only) → parse → gates UNCHANGED
  (safety → honesty → fact-check → per-candidate critic with CURRENT shipped_recent) →
  `save_draft`. Over-length batch results get ONE sync `write_tweet` retry chain (supply
  preservation beats the marginal cost; p(over-length)≈0.2 per the length-budget comment).
- **Freshness guard**: `collected_at - submitted_at > THEHEAT_BATCH_FRESHNESS_H` (default 6) →
  force `mode="manual_only"` via the existing draft_save decision-4 mechanism — stale batch
  results must never autoship. Expired batches (>24h API window): drop entries with a
  `batch_expired` suppression (transient — NOT negative-cached); candidates re-enter organically.
- **Ledger**: record per-result usage with `stage="writer_batch"` and a `batch=True` kwarg on
  `record_usage` that halves the estimate (50% off all token classes). Week-1 batch cache-hit
  rate in the ledger decides where in the $7–12 writer range we land.
- **MemorySlice is submission-time for the prompt; gates use live state at collection** — no
  slice persistence needed. `on_draft_success`/`annual_cap_check` closures can't serialize:
  annual counts re-check at next submission; document the small undercount.
- Sync path stays for dryruns + any future live-alert lane. codex-xhigh loop mandatory
  (writer/pipeline/state/posting surfaces).

**Merge order first**: (1) [#464](https://github.com/andrewzp/theheat/pull/464) on its codex
verdict (carries VERSION 0.9.109.0; $0 gates already green). (2)
[#463](https://github.com/andrewzp/theheat/pull/463) (P2.2 structured outputs — codex r2 clean
APPROVE; rebase over main, VERSION → 0.9.110.0 + CHANGELOG position, one codex round on the
post-rebase delta; its `replay` voice gate re-runs on push and needs the refilled balance to go
green; merge discipline: ANY red check blocks). P2.1 branches after both (it touches
`writer.py` and the drain).

## What happened this session (all MERGED unless noted)

- **Post-restore health check (07-23)**: production alive and posting (5 tweets since restore,
  global mix), canary green daily, self-heal gate $0-green, routine grading — and the ledger
  exposed the run-rate: **~$57/mo annualized vs the plan's $13–16 writer estimate** (peak-season
  deep queues → refill at the ~6-attempt cap every cycle × ~1.85 retry multiplier). This
  readout satisfied the plan's P2 gate and un-gated P1.3 (its pre-registered trigger observed:
  same-event paid-stage re-kills across cycles, e.g. `cal_high_RQC00660158_2026-07-21` ×2).
- **[#464](https://github.com/andrewzp/theheat/pull/464) — P1.3 cross-cycle negative cache**
  (OPEN at handoff — codex loop round 8 pending; latest push gates green, 2508 tests):
  `src/two_bot/negative_cache.py` + `state["writer_negative_cache"]` + drain wiring. Skip
  activates after **min_kills (floor 2, not tunable below)** kills on identical bundle sha
  under the same **decision epoch** (repo VERSION + writer/critic/fact-check/safety-LLM model
  ids + prompt sha + samples/revise/critic-enabled flags) within TTL 48h; evidence itself must
  be TTL-fresh; pure read predicate; merge freshness-filters each side (no resurrection);
  check at the paid boundary; **critic kills excluded** (they weigh the rolling pending-queue
  context); first-terminal-wins across every funnel path; dispatch advisory-safety kill
  populates `result_out`. Seven codex rounds so far (r1 supply-risk design → … → r7 critic
  exclusion), every round's findings fixed with regression tests; round 8 was in flight at
  handoff in the closing session's local scratchpad (NOT readable by you). **Next session:
  run your OWN codex-xhigh round on the PR's current full diff (state that r1–r7 findings and
  their fixes are in the commit messages) — merge on clean APPROVE (required `test` is green;
  voice jobs skip), else continue the loop.** Knobs:
  `THEHEAT_NEGATIVE_CACHE_ENABLED` (default ON), `_TTL_H` (48), `_MIN_KILLS` (2+).
- **[#463](https://github.com/andrewzp/theheat/pull/463) — P2.2 writer structured outputs**
  (OPEN, billing-held): `output_config.format` json_schema on the Anthropic call; JSON-parse
  retry lane becomes a residual net; refusal/empty-content responses route into that net
  instead of IndexError→pipeline_error (codex r1 P1, fixed); `anthropic>=0.77` floor; voice
  untouched — the writer-path PR gate is the before/after proof once billing refills.
  codex r1 REJECT → r2 clean APPROVE.
- **Ops**: #453 closed (day-one wobble, self-recovered). #452 diagnosed: `THEHEAT_METRICS_ENABLED=1`
  since 07-07 but the lane has NEVER succeeded — X API **401 on `GET /2/tweets`** (OAuth1 posting
  fine; READ tier/billing not attached to the app). Fix is in the X developer portal (Andrew).
  Docs sweep: BRIEFING header/status/dependency line, IMPROVEMENT_PLAN live-flag row,
  plan §Execution status addendum, this handoff.

## Watch items (next session)

- **First cycles after top-up**: negative-cache `negative_cache` suppression rows appear only
  after repeat kills (min_kills=2) — expect few at first; funnel shows them. Ledger calls/day
  should drop as #463 lands (JSON-lane share) and P2.1 halves the rest.
- **Budget var**: `THEHEAT_MONTHLY_BUDGET_USD` defaults $14 (plan's 20% target). At peak-season
  volume even the full train may land ~$15–22; either accept alerts as the throttle signal or
  Andrew raises to the plan's $18 hard-ceiling band.
- **Gemini quota** (conflict 4 in the plan) and **state size #390** (1.38MB) unchanged.

## Andrew-gated (do NOT start unbidden)

- Top-up + auto-reload + cap (**the gate**, above). X portal read tier (#452).
- records-cluster dryrun + `THEHEAT_RECORDS_CLUSTER_ENABLED` flip; #324 claim/warrant review;
  #346 dup-city (HELD); held levers (Haiku tiering, Sonnet 5 challenger, prompt compilation) OFF.

## Standing rules (bind every session — verbatim)

- `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH` on EVERY
  Bash command **including codex and git** (fresh shells lose cwd — git exits 128, codex "not a
  trusted directory"; retry with the prefix). Python `.venv/bin/python`; ruff/mypy
  `.venv/bin/ruff` / `.venv/bin/mypy`. Parallel sessions may hold worktrees — do YOUR work in a
  fresh worktree off origin/main; never stash/switch the shared tree.
- Before every push: `ruff check src/ tests/` AND `mypy src/` AND
  `THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q` — all green (currently ~2491;
  the count drifts — green is the bar, the number is a hint). Real exit codes — never gate on
  `cmd | tail`.
- codex-xhigh on any diff touching editorial gates / posting / state / storage /
  workflows-that-post, looped to clean APPROVE (zero P0/P1/P2), LAST round STARTING after the
  LAST edit: `codex exec -c model_reasoning_effort='"xhigh"' "<prompt>" < /dev/null` — run in
  background, ONE layer; 10-min foreground timeouts kill xhigh reviews.
- Merge: `gh pr checks <N> --repo andrewzp/theheat` → required `test` SUCCESS **and no red
  check of any kind** → `gh pr merge <N> --squash --delete-branch` → VERIFY
  `git log origin/main -1`. **Claude merges.**
- One PR per unit; VERSION + CHANGELOG ride code PRs; docs are their own PR; never weaken an
  honesty gate; US-only is off-brand; every new/changed scheduled workflow's PR carries a
  `cost/run × cadence = $/month` line.

---

## Paste-ready kickoff prompt for the next session

> Pick up @theheat. `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH`
> — that exact prefix on EVERY Bash command INCLUDING codex and git (fresh shells lose cwd; git
> exits 128, codex "not a trusted directory" — retry with the prefix). Python `.venv/bin/python`
> (ruff/mypy = `.venv/bin/ruff` / `.venv/bin/mypy`); repo `andrewzp/theheat`; `main` was
> `15d8f34` v0.9.108.0 at handoff — re-verify before assuming (this session's PRs may have
> merged since).
>
> **READ FIRST, in order:** (1) `docs/handoffs/2026-07-24-next-session.md` — the gate + open
> thread + full state (this prompt encodes it as of `15d8f34`; the repo copy wins if newer).
> (2) `docs/superpowers/plans/economics/PLAN-ECONOMICS-MASTER-v3.md` incl. the new §Execution
> status. (3) `docs/superpowers/plans/front-page-parity/INDEX.md` §Standing rules. Memories:
> `project_theheat_2026_07_14_production_stop`, `reference_theheat_drafting_health`,
> `feedback_theheat_one_house_voice`.
>
> **FIRST — the billing gate** (I will have topped up + set auto-reload): rerun
> `gh workflow run voice-regression.yml` → green, and confirm drafting resumes (new
> `drafts[*].created_at` in gist `06c02c97ffc0d11458687f1ed998d9e5` after the next 4-hourly
> cycle). If the balance is still empty, STOP and tell me.
>
> **SECOND — land the two open PRs, in order:** (a) **#464** (negative cache): check its codex
> loop's latest verdict (round 8 was in flight at handoff) — merge on clean APPROVE ($0 gates
> already green), else continue the loop to clean APPROVE; it carries VERSION 0.9.109.0.
> (b) **#463** (structured outputs, codex r2 APPROVED): rebase over main (VERSION → 0.9.110.0,
> CHANGELOG position), one codex-xhigh round on the post-rebase delta, wait for the
> writer-path `replay` gate to go green on the refreshed balance, merge (any red check
> blocks).
>
> **THEN — THE OPEN THREAD: build P2.1, the Batch API writer lane**, exactly as specified in
> the handoff's §open-thread block (submit-at-cycle / collect-hourly / gates-on-collection /
> freshness guard → manual_only / batch_expired transient / stage="writer_batch" ledger at 50% /
> StoryBundle.from_dict / shared build_user_prompt; flag default OFF, bot.yml plumbs the var).
> codex-xhigh looped to clean APPROVE; full gates before every push. Ship flag-OFF; the
> activation variable flip is mine unless I say otherwise in-session.
>
> **HOW (binds — INDEX §Standing rules):** prefix on every command; ruff + mypy +
> `THEHEAT_TIME_TRAVEL_DAYS=90` pytest green before every push (real exit codes); codex-xhigh
> background with generous timeouts, LAST round after LAST edit; Claude merges (required `test`
> SUCCESS + zero red checks → squash → verify origin/main); one PR per unit; VERSION + CHANGELOG
> ride code PRs; docs are their own PR; never weaken an honesty gate; US-only is off-brand;
> cost/run × cadence line on any scheduled-workflow change. Work autonomously; stop only for a
> real fork, a prod flag flip, or anything touching the writer's published voice (before/after
> required).
>
> **Also on the board (Andrew-gated, do NOT start unbidden):** X-portal read tier for
> twitter_metrics (#452); records-cluster dryrun + flag; #324 claim/warrant; #346 dup-city;
> state-size (#390); held levers stay OFF.
