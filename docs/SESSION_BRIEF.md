# Session Brief

Handoff doc for picking up @theheat work. Read after `BRIEFING.md`. Newest section at top.

---

# 2026-05-13 (evening) — First graded two-bot cycle + four PRs in queue

## Where we landed

`main` is still on `48ee110` (PR #82 from 2026-05-12). **No PRs merged today.** Four PRs are open and queued for review:

- **PR #87** — `fix-gist-truncation` (off main, urgent). Three scheduled `theheat-bot` runs failed today on a state.json size > 900 KB hitting GitHub Gist's REST API truncation limit.
- **PR #84** — `p1-p3-belt-and-suspenders`. Defensive normalization + P3 seasonal-context world knowledge + raw_signal_dump fix.
- **PR #85** — `p4-frp-tier-category-cooldown` (stacked on #84). Wodehouse + FRP tier + category cooldown + fire variety + Chuuk punch.
- **PR #86** — `daily-plan-2026-05-13` (grading agent). Records the first graded two-bot cycle.

Recommended merge order: **#87 first** (unblocks CI), then **#84**, then **#85** (auto-rebases cleanly), then **#86** any time after.

## The headline: 0% A-rate on the first graded two-bot cycle

PR #86's grading agent ran against 4 drafts that reached pending:

| Draft | Type | Score | Grade |
|---|---|---|---|
| Mali fire — 309.6 MW | fire | 64 | C+ |
| Campeche fire — 364.7 MW | fire | 65 | C |
| Chuuk FSM — 34.4°C (94°F), May record in 76yr archive | monthly_high | 80 | B |
| Mongolia fire — 307.6 MW | fire | 64 | C |

**Critical findings:**

- **No Wodehouse violations.** Voice work landed. P4 (in #85) hardens against regression but isn't moving today's needle.
- **No P3 self-kill failures.** Seasonal-context permission working as designed.
- **No BUNDLE_FACT kills on FRP.** PR #80's bundle-side rounding confirmed.
- **New failure mode P6 — fire template convergence.** All 3 fires used identical sentence-1 ("A fire in X is radiating Y MW…"). PR #85 second commit addresses this.
- **Chuuk B-grade ceiling.** Expository "Pacific warm pool context" instead of a punch. PR #85 second commit addresses this with explicit B-vs-A example pair.

## Today's three quality PRs

### PR #84 — P1 belt-and-suspenders + P3 seasonal context (commit `decf525`)

**P1 (defensive):** Adds `normalize_station_name()` calls at the top of 4 GHCN bundle builders in `src/two_bot/intern.py` (`build_monthly_high_bundle`, `build_record_bundle`, `build_all_time_record_bundle`, `build_anomaly_bundle`). Production was already safe (ghcn.py:381 normalizes upstream); this is boundary defense against any future signal-detection path that bypasses it. Codex review noted the original commit normalized `where` and `current_facts.city` but not `raw_signal_dump.city` — second commit closed the gap via `{**asdict(ev), "city": city}` dict-spread. 5 new tests.

**P3 (positive):** Removed the over-broad `"[country]'s fire/storm/wet season peaks in [month]"` bullet from the historical_context=empty "do NOT write" list. Added new "Seasonal context for fires is world knowledge" paragraph. The HARD RULES `NO FABRICATED CONTEXT` 95%+ confidence gate still catches truly invented seasonal claims. Confirmed empirically by PR #86: no P3 self-kill failures across the 4 drafts.

### PR #85 — P4 Wodehouse + FRP tier + category cooldown + variety nudges (commits `24b4145` + `1b324f2`)

**P4 Wodehouse rule** (`writer_prompt.py`): New `# THE WODEHOUSE RULE` section before HARD RULES. Names four effort-signals: approximation when exact is available, restate-padding, poetry-attempt closers, defensive justification. No unit tests (voice-regression cron is the empirical gate).

**FRP intensity tier** (`intern.py` + `writer_prompt.py`): `_frp_tier()` helper classifies into low (<30) / moderate (30–100) / high (100–500) / very_high (≥500). Two new `current_facts` entries (`frp_tier`, `frp_tier_floor_mw`). Writer prompt instructs use of the tier word ("high-intensity at 309 MW") instead of opaque raw MW — anchors readers without a NASA/FIRMS attribution claim. 6 TDD tests at boundaries.

**Per-day category cooldown** (`types.py` + `memory.py` + `writer_prompt.py`): New `recent_categories` field on `MemorySlice`. `_signal_kind_to_category()` maps 25+ kinds to ~13 categories. `build_memory_slice` filters shipped_tweets to last 24h, dedupes by category preserving recency. Writer prompt's new `# PER-DAY CATEGORY COOLDOWN` section sets the softer rule. 4 TDD tests.

**Second commit (`1b324f2`):** Fire sentence-1 variety (4 alternative forms with full example tweets) + Chuuk expository-vs-punch nudge in THE SIGNATURE MOVE. Pure prompt edits, no new tests. **Note on prompt structure**: the Chuuk expansion landed inside THE SIGNATURE MOVE bullet 2, leaving the numbered list with `1 / 2 / 2-continued / 3`. Reads fine but the numbering is now off. If a reviewer asks, the fix is to restructure bullet 2's expansion as a separate paragraph between bullets 2 and 3.

### PR #87 — Gist truncation hotfix (commit `35f4c66`)

`src/state.py:_read_gist_state` previously read `gist["files"][STATE_FILENAME]["content"]` unconditionally. When the file exceeds ~900 KB, GitHub's REST API truncates the inline content and exposes the full payload at `raw_url`. The fix: check the `truncated` flag and follow `raw_url` with the same auth headers (30s timeout, 2x the inline path's 15s since the full payload is larger). Falls back through existing `StateReadError` paths if raw_url is missing or fails. TDD regression test mocks the truncated → raw_url path and asserts read_state succeeds; RED before fix, GREEN after.

## Editorial framework — shareability as the two-gate test

Through chat-driven iteration today, the editorial bar was sharpened into an explicit two-gate test:

1. **Stop-mid-scroll** — would a climate-literate reader pause on this in a fast scroll?
2. **Send-it-to-a-friend** — having paused, would they screenshot/quote/DM it with "did you see this?"

Both required for ship. This operationalizes the long-standing "Wait, what?" test. The existing virality-research evaluator (5 dimensions: awe, social currency, opener, show-not-tell, comparison) is the implementation. The framework predicts virality; the bot uses it as the quality bar. **Shareability is a symptom of quality, not a strategy** — engineering for shares is engagement-bait; engineering for shareability is the editorial bar.

Saved as `docs/writer-prompt-brief-v3.md` — a clean-slate design brief for handing the writer prompt to a fresh AI session. Includes brand context (utility not growth, rejected directions, reader profile), the two-gate test, the lodestar voice, pipeline context, operational constraints, observed failure modes traced to real cycles, and anti-patterns. v3 reconciles the apparent "no virality" / "virality evaluator" contradiction (v1 had it as a real bug; v3 frames both consistently).

## What today did NOT change

- `main` HEAD (still `48ee110`).
- IMPROVEMENT_PLAN.md is updated in 3 open PRs (#84, #85, #86) — careful with merge conflicts.
- QUALITY_TREND.md updated only in PR #86.
- No changes to `src/voice/`, `src/data/` (other than #82's `src/data/ghcn.py` regex from 2026-05-12), or the dashboard.
- Routine config (Claude routines UI) still opens fresh daily-plan PRs each cycle instead of pushing to a single long-lived branch — memory hook from 2026-05-12 still pending operator action.

## Open questions for tomorrow

1. **Is voice still the bottleneck, or is editorial/structural now?** Today's data (no Wodehouse violations, expository ceiling, template convergence) suggests the latter. P4 was the highest-leverage proposal in the plan; if it doesn't move A-rate tomorrow, the bottleneck has shifted and the IMPROVEMENT_PLAN needs reordering.
2. **Should the category cooldown also cover same-cycle drafts, not just 24h windows?** Current design reads from `shipped_tweets` (posted history). Within a single cron run, fires #1 and #2 both see empty `recent_categories` because neither has been posted yet. PR #85's prompt-level variety guidance partially addresses this, but a memory-layer extension (`session_drafts` tracking per-cycle) would be more robust.
3. **Is the Chuuk "expository → punch" rewrite actually shippable for non-fire signals?** The B-vs-A example pair used Chuuk specifically. Empirical test: next graded cycle's temperature record drafts — does the system clause now do work, or did the example over-fit to the warm-pool case?

---

# 2026-05-12 (late evening) — End-of-day cleanup wave

## Where we landed

`main` is on `48ee110` (PR #82). **894 tests passing** (was 876 at end of 2026-05-10; +18 across today's six PRs). **Open PR count: 5 → 0**. The morning's voice + dashboard + FRP work (next section) shipped; the afternoon revealed every alerts run today (06:40, 10:34, 14:40 UTC) was producing zero drafts because four independent production failures killed every signal. All four fixed in one PR. Plus four stale daily-plan PRs closed without merge, plus PR #72 (mypy ignore-list) finally landed.

## PRs that landed end-of-day

### PR #72 — `BotState` TypedDict + remove three mypy `ignore_errors` overrides (`fa80018`)

Adds `src/state_schema.py` with `BotState` (total=False) + 9 nested TypedDicts mirroring `DEFAULT_STATE`. Flips ~37 signatures in `src/state.py` and ~20 in `src/main.py` from `dict` to `BotState`. Widens `_build_score` / `_compute_total` metric params to `float` (one signature change cascades to ~30 call sites). The `:1000-1200` if-cascade in main is rewritten with distinct per-branch variable names (`ev_mh`, `ev_ml`, …) because mypy couldn't narrow `ev` across mutually-exclusive type assignments. Removes the three `ignore_errors = true` overrides; 147 errors → 0. Adds 3 round-trip regression tests guarding JSON wire format. The `src.voice.generator` override remains (out of scope).

### PR #79 — daily plan refinement 2026-05-12 (revised by Codex review) (`97ecae4`)

Auto-opened daily-plan PR. P2 was originally "round FRP at writer + 0.5 MW tolerance," but Codex caught that the fact-checker has no tolerance rule (claim was inconsistent with the live contract). P2 rewritten to bundle-side rounding, which #80 implements.

### PR #81 — +25 stations closing coverage gaps (`ec2375d`)

Cherry-picked from a 6-day-old branch (PR #29) onto current main as a clean rebase. The original had stale doc commits that would have reverted today's docs sweep. 613 → 638 cities, 179 → 180 countries (+Cyprus). Closes immediate gaps from @extremetemps 2026-05-05 competitive coverage: Japan southern + northern islands, Australia QLD coast + cool side, China north, Cyprus. Plus cold-pole reporters (Verkhoyansk, Oymyakon, Phalodi, Furnace Creek).

### PR #82 — four production fixes in one PR (`48ee110`)

Each issue diagnosed by `gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json | jq '.suppressions[-N:]'` against the day's three alerts runs:

1. **GHCN station-name regex too tight.** `_COOP_SUFFIX_RE = r"\s+\d+(?:\.\d+)?[NSEW]{1,3}$"` caught `1SW` / `2N` but missed space-separated `4 NE`. `PADDOCK LAKE 4 NE` (Wisconsin) carried unnormalized → BUNDLE_FACT kill every cycle. New regex: `\s+\d+(?:\.\d+)?\s*[NSEW]{1,3}$`. Plus new `_MILITARY_SUFFIX_RE = r"\s+ANG$"` for the Air National Guard suffix class.

2. **Writer JSON-parse failure as `pipeline_error`.** Nettles Is FL calendar_date_low bundle, 3 runs in a row, same `Writer returned invalid JSON` ValueError. Stochastic refusal — a second sampling almost always produces JSON. New `JSON_PARSE_RETRY_BUDGET = 1` inner retry loop in `write_tweet`. Declarative-only feedback per the JSON-contract memory hook. After exhaust, returns `WriterResult(tweet=None, kill_reason=…)` — pipeline no longer crashes.

3. **`ocean_sst: Exceeded 30 redirects`.** climatereanalyzer.org loops requests without a UA into infinite redirects. Added the `theheat-bot` UA already used by `nws_alerts.py`.

4. **`river_gauges: Expecting value: line 1`** (USGS WaterWatch retired). `_fetch_flood_stages` now always returns `{}` on failure; gauge heights still flow, only `above_flood_stage` flag is lost. Replacement endpoint is a follow-up.

5 new `TestJsonParseRetry` tests + 2 station-name normalization regression tests covering the exact production failures.

## Operations cleanup

- **4 stale daily-plan auto-PRs closed without merge** (#37, #49, #59, #66). Each accumulated 5-10 days ago and would have been a backward-revert of today's docs sweep had they been merged.
- **PR #29 closed via #81 supersession.** The original had stale doc commits; cherry-picked just the data commits.
- **12 local branches pruned** (merged + stale).
- **Operator follow-up spec'd:** the daily-plan routine opens a fresh PR each day but never closes the previous one — an AI-PR-hygiene problem, not operator inattention. Routine prompt rewrite drafted: switch to a single long-lived `daily-plan-current` branch + persistent PR. Andrew to paste into Claude routines UI.

## Memory hook added end-of-day

- **AI PR hygiene framing.** Auto-PRs authored by Claude or Codex via the routines UI are AI hygiene, not Andrew's. Stale auto-PRs must not be framed as operator inattention.

## What's left to verify

- **The 18:39 UTC alerts run is the production verification for PR #82.** All four issues should be silent. If any recurs, the relevant `src/data/*.py` or `src/two_bot/writer.py` retry path needs a second look.
- **First voice-regression nightly on merged voice runs 2026-05-13 09:00 UTC.** Final manual run before close was 12/12 in 1:32.

---

# 2026-05-11/12 (morning + afternoon) — Voice overhaul: Attenborough/Economist + code-side length guardrail

## Where we landed

`main` is on `7542728` (PR #76). **883 tests passing** (was 876 at end of 2026-05-10; +7 new `TestLengthRetry` tests in #76). Voice-regression went **12/12 green** on the final state. Three PRs merged today rewriting the writer's editorial direction AND adding a code-side guarantee that Twitter never sees a >280-char string from this pipeline.

## The arc

The session opened with Andrew reviewing pending drafts and rejecting a wink-kicker on the Point Lay May blizzard draft ("The calendar says spring."). Diagnosed: the OLD prompt's "Context" framing example was literally `"Blizzard warning in Point Lay. It is May 1."` — actively teaching the failure mode. Refactored the voice anchor to "David Attenborough and The Economist" with explicit system-explainer mandate. Iterated 4 times across voice-regression cycles (each iter caught a different failure mode that informed the next), then landed a code-side length-cap retry that makes the 280 cap a hard guarantee.

## PRs that landed today

### PR #74 — Attenborough/Economist voice + system-explainer mandate (`4cd1b20...38e0c17`)

Six commits, all to `src/two_bot/prompts/writer_prompt.py`:
- `4cd1b20` initial voice rewrite
- `de8c3df` compress over-long exemplars after run 1 caught 5/12 length failures (my "approved" exemplars were themselves 400+ chars)
- `3b515ee` drop-a-clause length tactic + ban self-supplied facility MW numbers (after run 2 caught "Hoover Dam at full capacity" fabrication on a 361 MW fire — Hoover is 2,080 MW)
- `f431b75` ban wink-shape (not just literal phrases — "well past what the calendar suggests" was a different surface text of the same anti-pattern) + soften no-context kill rule + add Mali fire exemplar
- `9eb45e9` Andrew's cleanup pass (tightened review findings, compacted exemplars further)
- `38e0c17` merge

What landed in the merged state:
- Voice anchor: Attenborough + Economist (precision data → system → stop, no wink)
- THE SIGNATURE MOVE section with 3-beat structure + "delete the last sentence" test
- Climate-arc vs stakes/pattern guidance (cold records ≠ warming signal)
- HARD RULE banning wink-kickers by shape (not just literal phrases)
- HARD RULE banning self-supplied facility MW numbers
- 4 APPROVED EXEMPLARS (Point Lay, Imperial, Mauna Loa, Mali fire)

Iter-4 trap (NOT merged): tried to add "Mandatory self-check before emitting JSON: count chars, identify clause, remove, recount, repeat..." — imperative process language broke strict-JSON output on 5/12 fixtures. Caught on the unfinished branch, never reached main. Saved to memory ([feedback_prompt_json_contract](../memory/feedback_prompt_json_contract.md)).

### PR #75 — cold-record exemplar to stop nightly flap (`c8c30c5`)

After #74 merged, voice-regression kept failing on Sissonville + Verkhoyansk. Both at >280 chars. The merged prompt had no `monthly_low` exemplar; the writer reached for verbose "Cold records in an era of warming are increasingly local and topographic:" preambles. Two commits:
- `be0a02f` Andrew compacted the Verkhoyansk warm-record exemplar (drops "the cold poles are warming faster..." second-half climate clause)
- `2aa8e04` added APPROVED EXEMPLAR #6 — Sissonville-style cold record at 244 chars, topographic mechanism only (Kanawha Valley cold-air drainage), no warming preamble. Plus declarative rule for monthly_low / country_low: pick topographic / geographic / local-flow mechanism, skip warming framing.

Voice-regression ran green 12/12 in 1:31 on this PR.

### PR #76 — writer-side length-cap retry + hard kill (`7542728`)

Prompt-only length discipline is fragile under model stochasticity. Even a green snapshot today doesn't guarantee green tomorrow on a different sampling. Added a code-side guardrail in `src/two_bot/writer.py:write_tweet`:

- `TWEET_MAX_LENGTH = 280`, `LENGTH_RETRY_BUDGET = 2` (3 attempts total)
- If the model returns >280 chars, retry with declarative feedback in the user prompt
- After 3 fails, return KILL with explicit `kill_reason`
- Feedback is declarative ("a previous attempt produced N characters; return a shorter version") — not imperative process language, per the memory hook learned from iter-4 of #74

Probability math: at worst p=0.2 per-call, p³ = 0.8%. At post-#75 baseline p≈0.05, p³ = 0.01%. Cost: ~$0.30/voice-regression run extra (~$6/mo → ~$9/mo).

7 new `TestLengthRetry` tests: retry on overlong, kill after budget, no retry when fits, no retry on kill, declarative feedback content, boundary at 280, boundary at 281.

Voice-regression ran green 12/12 in 1:32 on this PR.

### PR #78 — dashboard refresh-button feedback (`77ad753`)

Andrew reported "when I click refresh on the dashboard it doesn't look like anything happens." Verified in the browser: the click WAS firing all 5 API calls (state, drafts, suppressions, config, source-health) in ~60ms and state WAS updating — the button just gave zero UI signal. Three new states in `fetchData`:

- `refreshing` (boolean) — drives button label "refresh" → "refreshing…", disables the button, tints orange. Also prevents double-fire.
- `lastUpdated` (ISO string) — renders "updated 5s ago" via the existing `timeAgo()` helper. Makes unchanged-data refreshes visibly successful.
- `refreshError` (string | null) — surfaces failures as an orange "refresh failed" pill with the error in the title attribute. Replaces the silent `console.error` path.

`min-width: 96px` on the button prevents layout shift between the two labels. 16 existing dashboard tests still pass.

### PR #80 — fire FRP rounded at the bundle builder (`4677869`)

NASA FIRMS returns FRP at two-decimal precision (e.g. `480.34 MW`). Fact-check prompt requires exact match — *"Verify exact match (number, unit, date). Mismatches = failure."* No tolerance rule. Writer rounding `480.34 → "480 MW"` produced BUNDLE_FACT kills on three fires across two cycles (480.34 → 480, 547.92 → 548, 301.55 → 301).

**Codex saved us from the wrong fix.** The original P2 proposal in `docs/IMPROVEMENT_PLAN.md` would have added a writer-prompt rule claiming a ±0.5 MW tolerance the live fact-checker doesn't have. Codex caught it on PR #79. Plan rewritten (commit `dcc6848`) and implemented as a one-line bundle-side change:

```python
# src/two_bot/intern.py:build_fire_bundle
frp_rounded = round(fire.frp, 1)
# headline_metric.value AND raw_signal_dump.frp use frp_rounded
```

Bundle becomes source-of-truth at 1-decimal precision; writer naturally echoes; fact-checker confirms exact match. Five-case regression test in `test_intern.py` covers the three production failures plus banker's-rounding edges.

Tests: 884 passing.

## Editorial work that landed alongside

- **Killed draft #156 Mankato** (manual editorial). The pending draft was a 0.1°C tied May record in a 16yr archive with a defensive "A record is a record." closer — didn't clear the editorial bar set by the new voice. Marked status=rejected via `state.write_state()` (race-safe through `_merge_state`).

## What's NOT done (carry forward)

- **PR #72 (mypy ignore-list removal via BotState TypedDict)** — OPEN, CI green, ready to merge. Adds `src/state_schema.py` with a `BotState` TypedDict + propagates annotations through state.py / main.py / scoring.py / synthesis.py / two_bot pipeline. 147 previously-hidden errors → 0. Includes a `TestBotStateSchemaRoundTrip` to guard against future drift between `DEFAULT_STATE` and `BotState`. Worth a quick review and merge.
- **PR #73 (auto-opened daily-plan refinement 2026-05-11: 8 drafts, 12.5% A-rate)** — proves yesterday's grading-agent routine repair is working. Review when ready.
- **PR #79 (auto-opened daily-plan refinement 2026-05-12: 0 drafts)** — the doc has been revised in `dcc6848` after Codex feedback; P2 (FRP rounding) is implemented and merged via #80, so the plan's status note can be updated next pass. Other priorities in #79 (P1 station-name normalization, P3 seasonal/calendar context, P4 Wodehouse rule for the new prompt) are still untouched.
- **Pending drafts #154 (Imperial) and #158 (Point Lay)** — still have wink-kicker text from the old prompt. Decision pending: kill them so the next bot.yml run regenerates under the new voice, or let them sit and compare side-by-side as new drafts come in.
- **Dashboard QA NOT FINISHED.** The refresh button is now fixed (#78), and a partial QA pass confirmed the dashboard renders cleanly (dark monospace, 5 tabs). Per-tab exploration (Pipeline / Workbench / Suppressed / Sources) still pending. Dashboard URL: `https://dashboard-andrew-puschels-projects.vercel.app` (HTTP Basic Auth from Vercel env). Local dev: `cd dashboard && npx next dev -p 3030`.
- **Watch the next bot.yml alerts run.** With #80 merged, fire drafts should start surviving the fact-checker on FRP precision. The next cron will tell us whether other BUNDLE_FACT classes are still killing (e.g. station-name normalization per PR #79's P1).

## Defense-in-depth state (post-today)

```
writer prompt voice (Attenborough/Economist + HARD RULES tests #58 + wink-shape ban #74)
  ↓
writer-side length retry + hard kill (#76)  ← NEW: code-side guarantee
  ↓
inline safety regex (#60) + precision tuning (#67/#68)
  ↓
bundle-side FRP rounding (#80)  ← NEW: source-of-truth precision normalization
  ↓
fact-check (existing — exact match contract preserved)
  ↓
post-time safety regex (existing)
  ↓
nightly Sonnet replay (#61) — 12/12 green on final state
  ↓
source health visibility (#64 + #71)
  ↓
daily quality grading (#66 repair → validated by #73 auto-PR firing 2026-05-11)
```

## Memory hooks added today

- [Attenborough/Economist voice](../memory/feedback_voice_bigger_picture.md) — TheHeat: place each data point inside the system the reader doesn't fully see; teach, don't wink. Includes 3 approved exemplars validated by Andrew.
- [JSON-output prompt contracts](../memory/feedback_prompt_json_contract.md) — Imperative process steps ("count, remove, recount, repeat") leak into strict-JSON output; keep guidance declarative.

---

# 2026-05-10 — Cron feedback loop: voice-regression caught real signal on first scheduled run

## Where we landed

`main` is on `1ed7e2c` (PR #68). **876 tests passing** locally (was 866 at end of 2026-05-09). Pipeline working end-to-end; voice-regression harness fully validated by catching three real false-positives. Daily-plan grading-agent routine repaired out-of-tree.

## The signal that drove the session

The voice-regression workflow shipped 2026-05-09 fired its first real cron at **2026-05-10 10:06 UTC** and rejected 3 of 12 fixtures, all with the same root cause:

| Fixture | Output | Reject reason |
|---|---|---|
| sissonville_monthly_low | "…overnight on May 4 — a new May cold record in 16 years…" | Month 'may' mentioned 2 times |
| dayton_monthly_low | "…on May 5 — the coldest May night in 21 years…" | Month 'may' mentioned 2 times |
| verkhoyansk_monthly_high | "…in April, smashing its previous April record… where April still belongs to winter" | Month 'april' mentioned 3 times |

All three are good tweets. The safety rule was over-tight.

## What landed today

### PR #67 — false-positive elimination + Celsius relaxation

Two related changes in `src/voice/safety.py`:

1. **`check_month_repetition` rewrite.** Old rule `count >= 2` blocked legitimate "May date + May record-class" prose. New rule: literal `"It's <Month>"` standalone + same-month year-anchored restatement + safety net at count ≥ 4. The canonical anti-pattern `"April 10, 2026. It's April."` still rejects.
2. **`check_truncated_temperature` single-digit Celsius dropped.** Andrew's parallel-session WIP. Sub-10°C is normal for cold-record signals (Dayton hit 4°C); Celsius left to the fact-checker. Single-digit F still rejected (`91F → 1F` is the writer dropping a leading digit).

5 new tests:
- 3 regression tests with the verbatim cron-rejected tweets
- 1 for year-anchored restatement
- 1 for 4+ padding safety net

### PR #68 — Codex review follow-up

Codex flagged two precision bugs in #67:

1. `\bit'?s ({month})\b` with **optional** apostrophe rejected possessive `"Phoenix broke its May record"`. Fixed: apostrophe required, accepts both straight (`'`) and curly (`’`).
2. `({month})\s+\d{4}\.\s+(?:{month})` rejected cross-month comparisons like `"April 2026. May records..."`. Fixed: second occurrence is now backreference `\1`.

3 new regression tests covering Codex's exact examples.

### Grading-agent routine repair (out-of-tree)

PR #66 (auto-opened by the agent at 15:06 UTC) reported zero drafts graded because the routine's Step 2 used `curl https://api.github.com/gists/<id>` unauthenticated → hit GitHub's 60/hr IP rate limit → 403.

Updated the routine ([trig_016PGeHZgEYWmeQhx1xGmYg6](https://claude.ai/code/routines/trig_016PGeHZgEYWmeQhx1xGmYg6)) prompt:
- Step 2 now `git clone https://gist.github.com/<id>.git` first (public gists are git repos — no auth, no rate limit). Falls back to `gh api` if clone fails.
- Step 7 (gist write for staleness rejection) now degrades gracefully if `gist:write` scope is missing — logs skip note instead of aborting.
- Global "DO NOT abort on infra failures" constraint added.
- Validates on next cron at **2026-05-11 15:03 UTC**.

## Defense-in-depth state (post-today)

```
writer prompt (HARD RULES tests — #58)
  ↓
inline safety regex (#60) + precision tuning (#67/#68)
  ↓
fact-check (existing)
  ↓
post-time safety regex (existing)
  ↓
nightly Sonnet replay (#61) — caught 3 false positives on first run, fixed
  ↓
source health visibility (#64)
  ↓
daily quality grading (repaired today)
```

## What's NOT done

- Parallel-session WIP still uncommitted in working tree (bot.yml additions for Node + dashboard test/build steps, dashboard/lib/state-store.js improvements, voice_regression/test_writer_replay.py tightening, source_status.py). Belongs to another session/lane — left untouched.
- The 09:00 UTC voice-regression cron tomorrow (2026-05-11) will be the verification of PR #67/#68 fix on the real harness.

---

# 2026-05-08 — 13-hour debugging marathon: 4-day outage diagnosed, root-caused, fixed

## Where we landed

`main` is on `d9c84ff` (PR #47). **~813 tests passing** (was 709 at session start). Pipeline working end-to-end for the first time since 2026-05-03. **2 pending drafts in queue** (Sissonville WV + Dayton WY monthly_lows — graded B and C+ respectively). Posting still paused per the resumption-bar invariant.

**The session began with**: "we still aren't seeing drafts!"

**The session ended with**: 10 PRs landed (#38–#47), 11 CHANGELOG releases (0.3.0.0 → 0.3.10.0), structural visibility for every kill stage, and the bot generating real factually-grounded prose again.

## The bug ladder (each layer revealed by the previous fix's diagnostic surface)

| PR | What it fixed | Bug exposed by the fix |
|---|---|---|
| **#38** | Suppression ledger v1 + dashboard health-calc fix (`success` + `skipped` count as healthy) | (visibility infrastructure — no bug exposed yet) |
| **#39** | `signal_date` choking `json.dumps()` in writer/fact-check via `_json_default` ISO coercion + downstream suppression capture (`stage` field discriminator) | First post-fix run: ledger surfaces `Pipeline error: Writer returned invalid JSON` for monthly_low bundles |
| **#40** | Sonnet wraps JSON in `\`\`\`json` fences despite the prompt explicitly forbidding them — defensive parser strips them | Next run: ledger surfaces `Invalid JSON response: Let me think about this carefully.` (chain-of-thought preamble before the JSON object) |
| **#41** | `_extract_json_payload` finds first `{` and last `}` — robust to preamble + postamble + nested objects. Anthropic timeout 90s → 180s | Next run: 22-second `ReadTimeout` on monthly_low — way under 180s, so timeout-cap isn't the issue |
| **#42** | Codex bug-hunt sweep (13 findings, 0 blocker, 7 high, 6 medium, all addressed). Three new shared modules: `json_utils.py` (default + balanced extraction + comment/comma fallback), `retry.py` (`call_with_retries` exp-backoff around every LLM call), `source_status.py` (typed `SourceFetchError` / `SourceSkipped`). Wired into writer / fact-check / claim-extractor / FIRMS / fire-footprint / state.py / sqlite_store.py | Next run: retry helper logs surface `[two_bot.retry] gemini fact-check attempt 1/3 failed: ReadTimeout` — three retries failed in <300ms total. Way too fast for a 90s timeout |
| **#43** | **Root cause: `google-genai` `HttpOptions.timeout` is MILLISECONDS, not seconds.** Three sites passing `90` (= 90ms) and `180` (= 180ms) bumped to `90000` / `180000`. Confirmed against `googleapis/python-genai/google/genai/types.py`: *"Timeout for the request in milliseconds."* Regression test introspects source for any `HttpOptions(timeout=NNN)` and asserts ≥ 5000 with a loud failure message about the ms-vs-s trap | Next run: writer + fact-check now succeed end-to-end. Fact-checker rejects `"Sissonville: UNVERIFIABLE: 'Sissonville' (without '1SW') does not appear exactly in the bundle. The bundle refers to 'SISSONVILLE 1SW'"` |
| **#44** | `normalize_station_name()` in ghcn.py strips CoCoRaHS suffixes (`1SW`, `2NE`, `0.5W`), airport suffixes (`INTL AP`, `MUNI AP`), and WFO prefixes. Applied at the data-source boundary so writer + fact-check both see clean place names | Next run: fact-check accepts the normalized name but rejects new claims: `"the state 'Washington' is not in the bundle"`, `"the word 'night' is not explicitly mentioned"`, `"flowers are already up — UNVERIFIABLE"` |
| **#45** | Bundle enrichment: `state` field on event dataclasses + `expand_us_state()` (`WV` → `West Virginia`) + `_format_where()` includes state for US (`"Sissonville, West Virginia, United States"`) + `_ghcn_observation_facts()` adds `observation_kind` (`"overnight low"` / `"afternoon high"`) | Next run: **TWO PENDING DRAFTS APPEAR** (Sissonville WV + Dayton WY). Pipeline working end-to-end |
| **#46** | Fahrenheit-first audience-aware temperature formatting. `_c_to_f()` integer conversion. `_audience_unit_facts()` adds `"fahrenheit_first"` for US, `"celsius_first"` elsewhere. Bundle headline_metric carries both `value` (C) and `value_f` (integer F). Writer prompt gains a `TEMPERATURE FORMATTING` section. Anomaly delta uses 9/5 scaling only (no +32 offset) | (no new bug — verification cycle showed structural cleanliness, no new pipeline_error records) |
| **#47** | Codex review of #38–#46 caught 3 high-severity bugs the author missed: dashboard `mergeState()` was erasing Python-owned state on every approve/reject click (data loss), SQLite `_METADATA_JSON_KEYS` was dropping `memory` + `data_source_failures` on every round-trip (state loss), claim_extractor had no Gemini timeout (unbounded hang risk). All three fixed | (final) |

## The actual root cause

**`google-genai` `HttpOptions.timeout` is documented as milliseconds.** The codebase migrated from the older `google-generativeai` SDK (timeout in seconds) to `google-genai` (timeout in milliseconds) around 2026-05-03 — same window the outage started. The values didn't change but the unit did. Three sites passed bare integers (`timeout=90`, `timeout=180`) believing they were seconds; they were 90ms and 180ms — barely enough for a TLS handshake. Every Gemini fact-check call failed with `ReadTimeout` in <300ms across 3 retry attempts, silently killing every two-bot draft for **4 days** (last successful draft 2026-05-03).

The diagnostic infrastructure shipped in #38 + #42 is what made the bug findable. Without the suppression ledger and the retry helper's diagnostic prints, this would have stayed invisible indefinitely.

## What's in queue

```
2 pending drafts (graded B and C+):

1. Sissonville, West Virginia hit -2.2 °C overnight on May 4th — breaking the
   previous May low of -1.7 °C set in 2020. Coldest May night in 16 years of
   records there. Fruit trees in the Kanawha Valley were not consulted.
   --> B-grade. Voice is good (Wodehouse-passing closer), signal is borderline
       (16-yr archive, 0.5°C margin).

2. Dayton, Wyoming dropped to -9.4 °C overnight on May 5th — breaking the
   previous May low of -8.3 °C set in 2010. Coldest May night in 21 years of
   records there, by 1.1 degrees.
   --> C+ grade. Quantifies the margin but voice is flat. No hook.
```

Both pre-date PR #46 (they're locked to old `°C`-only format because event_id is in `posted_events` dedup). New signals will use F-first formatting from the start.

## Open at session end

1. **Codex review medium/low findings** — all explicitly deferred. Documented in `docs/codex-review-findings-2026-05-08.md`. See BRIEFING.md "Known Issues" section.
2. **Suppression `stage` UI rendering** — schema is wired but dashboard groups by `source` only. Highest-leverage cleanup.
3. **GHCN observed records still labeled `forecast_*_c`** in `headline_metric.label` — semantically wrong since the same dataclasses now serve both Open-Meteo (forecast) and GHCN (observed). Should split.
4. **Writer prompt tightening for speculative claims** ("Flowers are already up", "the ground froze") — these are pure hallucinations the writer should be told not to add. Bundle enrichment can't fix them.
5. **Vercel GitHub auto-deploy not firing** on pushes to main — deploys go through manual `vercel --prod`. Worth investigating.

## What is OFF the table

- Brand identity (locked at R3 v4 since 2026-05-07).
- Hot 10 leaderboard migration to GHCN (stays on Open-Meteo).
- Open-Meteo dead-code removal (kept as rollback path for at least one quarter).
- Posting unpaused (resumption bar still: majority A-grade per cycle).

---

# 2026-05-06 → 2026-05-07 — GHCN-Daily migration + brand identity locked

## Where we landed

`main` is on `bad21be` and forward through PRs #30 → #31 → #32 → #33 → #35 → #36. **709 tests passing** (was 679 at session start). Posting still paused. The signal-side migration is shipped; identity layer is locked.

## The big shifts this session

1. **Extreme-signals lane migrated from Open-Meteo to NOAA GHCN-Daily.** The bot now reads 11,907 active stations instead of 638 curated cities — 19× population expansion at $0/month. Hot 10 leaderboard explicitly stays on Open-Meteo. Feature-flagged via `THEHEAT_SIGNALS_PROVIDER` (default `ghcn` in production, `open_meteo` for fallback). Five-PR sequence: P1 foundation (parser + scripts + weekly CI workflow) → P2 detection module + 30 tests → P3 wire-up + signal_date threading + record_streaks key migration → P4 cutover + Codex fix pass → P5 stale-obs filter (post-cutover diagnostic finding) → dashboard drill-down. See CHANGELOG [0.3.0.0].

2. **The bug pile that actually mattered.**
   - **`superghcnd_diff` format misread.** Original implementation assumed flat `.dly`-shaped text; live NOAA ships a tar archive of insert/update/delete CSV members. Codex review pass (PR #33) corrected.
   - **`climatological_mean_min` missing from shipped SQLite.** The 2026-05-05 bootstrap was run before the persistence fix landed, so the asset had `climatological_mean` (TMAX) rows but no TMIN climatology — silently blocking all cold-anomaly detection. Fixed by re-bootstrap and uploaded as `thresholds-latest`. Now backed by a regression test that asserts TMIN climatology round-trips through SQLite.
   - **Stale-obs filter** (PR #35). `superghcnd_diff` files routinely contain late-arriving observations from 1-2 weeks earlier. Live diagnostic on 2026-05-06 showed every firing bundle was anomaly_hot on observations from April 24-30. Editorial age penalty correctly killed all 55 of them, producing 0 drafts — but the bot was running on noise, not news. New constant `MAX_OBS_AGE_DAYS` (default 4) sets a freshness floor.

3. **Dashboard drill-down (PR #36).** Each row in the Source Health panel now has a `▶ details` button. Click expands to: pipeline funnel (bar chart of stage drop-off — stations active → with obs → checked → raw signals → bundles → drafts) + events table (per-bundle decision rows with badges: drafted / rejected / no_qualifying_signal). Powered by a new `details: dict` field on `source_run` records. Schema is loose; conventional keys: `pipeline_metrics`, `events`, `fetch_meta`. Each source can populate what's useful.

4. **Brand identity locked at R3 v4.** Painful path: 4 rounds of designer work, several rounds of my overcorrection ("visceral fever," melting wordmarks, station-pin debate, horizon-rule signature), then back to a thermometer-bulb mark + clean Inter SemiBold wordmark + paper/ink palette + single accent (`#C2410C`) on headline numbers. Production handoff at `brand/handoff/` (consolidated to one canonical location). Includes Brand Book.html, Operator Dashboard.html, Usage Guide.html, all production PNGs (avatars, banners, favicons, OG card), all SVGs (full-color, mono, reverse, outlined). The Twitter banner the designer shipped had broken typography (font-fallback failure) AND strategic problems (newspaper masthead, "REFRESHED HOURLY" lie, fake live reading). Replaced both PNGs locally using the outlined SVGs + Chrome headless render — clean now.

5. **Coverage honesty.** GHCN-Daily covers most but not all @extremetemps records. Verified present: Phoenix Sky Harbor, MSP, Verkhoyansk, Oymyakon, Phalodi, Death Valley. **Verified missing:** Tokashiki/Okinawa, Troodos/Cyprus (Japan + Cyprus have sparse station coverage in GHCN). Closing those gaps requires hybrid feeds (JMA AMeDAS, Cyprus DoMS) — deferred to a future PR if/when a station-level Japan or Cyprus event surfaces and the bot misses it.

6. **PR housekeeping.** Closed 10 stale daily-plan / pre-GHCN refinement PRs (#11, #12, #13, #15, #18, #20, #24, #27, #28, #34). Only #29 (`expand-cities-25`) remains open — likely superseded by GHCN's 11,907-station population, but left for the user to close after deciding whether any of its 25 stations are still distinctive (Tokashiki / Troodos territory).

## Open at session end

1. **Twitter profile NOT yet updated** with the new brand assets. The user has the avatar and banner files at `brand/handoff/png/` and will upload manually when ready.
2. **#29 expand-cities-25** still open on GitHub — user's call whether to close as superseded.
3. **Watch list for first 10 alert cycles** (per the lock-in PR description): lag framing reads cleanly ("on May 4," not "today"), at least one previously-missed event class fires, `data_source_failures["ghcn"]` stays at 0, dashboard funnel shows healthy stage progression.

## What is OFF the table going into next session

- Brand identity iteration. R3 v4 is locked. Don't reopen unless something is genuinely broken.
- Hot 10 leaderboard migration to GHCN. Stays on Open-Meteo.
- The Open-Meteo dead-code removal. Kept dormant behind the feature flag for at least one quarter as the rollback path.
- The "wire service" / "publication of record" framing for the Twitter banner. Twitter banners are static images that sit for months; anything implying live data ages into a lie within 24 hours. The brand voice (in tweet copy) carries the editorial register; the static chrome stays restrained.

---

# 2026-04-26 → 2026-04-29 — Voice engine v3 + research grounding + posting paused

## Where we landed

`main` is on the voice engine v3 ship commit. **566 tests passing** (was 522 at session start). Posting paused since 2026-04-12 — deliberate quality bar set 2026-04-26: posting resumes when majority of corpus-graded drafts earn A grades. Currently 0% A-rate (Apr 29). Daily plan-refinement agent runs 15:00 UTC, refining `docs/IMPROVEMENT_PLAN.md`.

## The big shifts this session

1. **Posting bar made explicit.** "Resume posting when majority A" — pinned in BRIEFING. Applies to all future cycles. Stale drafts can't ship even when shippable; window expires.
2. **Humor research grounded the voice work.** New doc `brand/HUMOR_RESEARCH.md` (270 lines) covers the four humor theories (Kant/Schopenhauer incongruity, McGraw & Warren benign violation, relief, superiority), joke construction, comic triple, brevity + specificity, deadpan tradition (Steven Wright, Mitch Hedberg, Bob Newhart), British humor (Wodehouse rule), and Shifman meme theory. Gives every voice mechanic a name and a corpus example. **Wodehouse rule named as the most predictive principle:** the voice should never sound like it's trying to be funny.
3. **Era anchors parked at 1-in-10.** Three consecutive corpus cycles (Apr 25, 27, 29) showed 100% era-anchor deployment on records. User direction Apr 29: park at no more than 1-in-10 tweets. Voice engine v3 ships the structural gate (`_era_anchor_should_fire`, deterministic by city+year+date seed). 90% of record drafts get explicit "parked, use other vehicles" steer-away; 10% get curated content framed as "your 1-in-10 turn."
4. **Addendum-mismatch bug fixed.** `generate_all_time_record_tweet` was using `category="all_time_record"` but addenda were keyed `all_time_high`/`all_time_low` — addenda had been DORMANT. Fixed to `category=f"all_time_{kind}"`. Same for monthly. Added missing `monthly_low`, `country_low`, `record_low` addenda. The voice work that went into those addenda has now actually started applying.
5. **Daily plan-refinement agent created.** `trig_016PGeHZgEYWmeQhx1xGmYg6`, fires 15:00 UTC daily. Reads framework docs, grades drafts, refines `docs/IMPROVEMENT_PLAN.md`, opens a PR. Plan-only — does NOT implement code/prompts. User reviews, we implement together.
6. **Anchor curation cleaned.** Pruned 43 entries from `data/era_anchors.json` (politically-charged: Trump, Brexit, Capitol riot, Elon/Twitter, MeToo; mass tragedies as scaffolding: 9/11, Katrina, Hurricane Sandy, Indian Ocean tsunami; US-only sports: Cubs, Red Sox; etc). Now 205 anchors / 31 years / 6.6 avg per year, all globally legible and politically neutral.
7. **Two-bot architecture conversation opened.** User raised: separate Data Organizer (gathers + structures signals into "story bundles") from Writer (takes bundles, writes voice with great voice). Cleaner than current Gemini-generates-then-Sonnet-rewrites. Brainstorm pending.
8. **Cost reality update.** "Free tier" Gemini claim was outdated. `gemini-flash-latest` aliases to a paid preview model at $0.30/$2.50 per MTok. Current Gemini spend: ~$5–10/mo. Pin `GEMINI_MODEL=gemini-2.5-flash` to return to free tier.

User also clarified important nuances:

- **"not everything has to be a joke"** — humor mechanics are tools, not mandates. Pure data delivery is valid when the number is striking enough.
- **"the era anchor can't be used every time. it gets so old and lame"** — drove the 1-in-10 parking decision.
- **"we paused posting because the tweets sucked"** — explained the 0-pending state. Posting is a deliberate quality pause, not an operational gap.
- **"we can't post those because they aren't real time"** — drafts have time-baked content, expire fast. 14 stale pending bulk-rejected 2026-04-26.
- **"keep building and refine an improvement plan, then i can review it and we can implement together"** — sets the agent autonomy boundary. Daily agent refines plan; human + Claude implement.

## What shipped this session (chronological)

- Voice engine v2.5 (era anchors + multi-station roll-call + recalibrated rules + opener-formula ban + earned editorial heat permission) — pre-session leftover
- BRIEFING resumption-bar pin + `docs/QUALITY_TREND.md` (A-rate trend + rejection log)
- Bulk-reject 4 D-range fires + 14 stale pending drafts (queue zeroed for clean baseline)
- `brand/HUMOR_RESEARCH.md` (270 lines, sibling to VIRALITY_RESEARCH)
- Apr 27 corpus humor-lens evaluation + Apr 24 corpus re-grades (#3, #4 demoted on grammatical-referent issue)
- `data/era_anchors.json` audit + 43-entry prune
- `docs/CLAUDE_DESIGN_BRIEF.md` + `docs/claude-design-handoff/` folder (3-direction brand identity request)
- `docs/IDEAS.md` NVIDIA NIM entry (dev-only A/B harness)
- `docs/IMPROVEMENT_PLAN.md` (living plan refined daily by autonomous agent)
- Daily recurring schedule `trig_016PGeHZgEYWmeQhx1xGmYg6` for plan refinement
- Apr 29 corpus grading (3 drafts, 0% A-rate)
- **Voice engine v3 (this commit):** era-anchor 1-in-10 gate + addendum-mismatch fix + 5 record-type addenda rewrite to 6-vehicle menu + SYSTEM_PROMPT #1 vehicle-agnostic rewrite + 3 new bad-examples + 5 new gate tests

## What's pinned mid-implementation

1. **Two-bot architecture redesign.** User raised 2026-04-29; we sketched the shape (Data Organizer outputs structured story bundles; Writer takes bundles + voice). Brainstorm not yet held. Bigger lift than P1-P6 — architectural.
2. **Prompts inventory doc.** User asked for a single doc listing all bot prompts (system + per-category + helpers + safety + evaluator) with content + locations. Half-built; abandoned mid-stride when the architecture conversation opened.

## Other open threads

- **Voice rules vs @extremetemps:** the voice spec is over-engineered for breakout-viral aspiration when our genre uses ALL CAPS / editorial heat / multi-station data dumps. Voice engine v2.5 partially addresses; deeper rethink still possible.
- **`evaluator_pass=null`** on all 3 Apr 29 drafts. Either evaluator isn't writing verdict to draft state, or `EVALUATOR_ENABLED` got set false. Worth investigating.
- **Daily plan-refinement agent's first run** is tomorrow morning. Should observe the empirical effect of the v3 era-anchor gate.

## Numbers

- Tests: 522 → 566 (+44 across the session)
- Commits pushed to `main`: 12+ (era_anchors prune, HUMOR_RESEARCH, corpus updates, design brief, IDEAS, BRIEFING, QUALITY_TREND, IMPROVEMENT_PLAN, voice engine v3 — final commit pending in this session)
- Era-anchor inventory: 248 → 205 (43 pruned)
- Pending drafts: 0 (paused; would-be drafts get graded but not posted)
- API spend: $30–55/mo total stack
- Posting cadence: 0 (last post Apr 12; resumption bar majority-A not yet cleared)

## When picking up in the next session

Read in order:
1. `BRIEFING.md` (current state)
2. This file's top section (Apr 26-29 — what just happened)
3. `docs/NEXT_SESSION.md` (action menu, invariants, common commands)
4. `docs/IMPROVEMENT_PLAN.md` (living plan, P1 SHIPPED + P4-P6 active)
5. `docs/QUALITY_TREND.md` (A-rate trend)
6. `docs/DRAFT_CORPUS.md` Apr 29 + Apr 27 sections (lens evaluations + re-grades)
7. `brand/HUMOR_RESEARCH.md` (the framework)

Pull pending drafts. If new corpus needs grading, append to `DRAFT_CORPUS.md`. Then pick a menu item from `NEXT_SESSION.md` — likely either continue the voice work (P4 Wodehouse top-of-prompt), open the two-bot architecture brainstorm, or finish the prompts inventory.

---

# Session Brief — April 24, 2026

Handoff doc for picking up @theheat work. Read after `BRIEFING.md`.

## Where we landed

`main` is at `1573d15`. **522 tests passing.** Single longest session
yet — combined the fire geocoder fix, FRP floor raise, voice engine
v2 (per-category prompts + stock-formula rejector), Gemini model
upgrade to `gemini-flash-latest`, full draft-quality audit of 35
pending drafts, bulk-rejection of all 35 with full inventory archived
to `docs/DRAFT_CORPUS.md`, and an ongoing model conversation that
ended with "do it right for now, keep Sonnet."

## The big shift this session

User reviewed pending drafts and grade-distributed them honestly: 7
A/B-grade out of 35, mostly records (Sevilla, Chicago, Jacobabad,
Kathmandu, Ipoh, Medan, Hawaii). 27 fires, all formulaic. Then user
showed three @extremetemps tweets — the actual successful account in
our genre, 106K followers — which break almost every voice rule we've
codified: ALL CAPS openers, "EXTRAORDINARY" / "Mind blowing"
editorial heat, multi-station data dumps, threading.

**This is the architectural insight to preserve:** our voice spec is
optimized for *breakout-viral aspiration* (Thunberg, Hausfather,
Kalmus). The data-ticker genre we're actually in uses different
tactics. We've banned the very tools the genre leader uses. Voice
engine v2 prompt addenda partially address this — they're more
permissive of editorial heat earned by the data — but the deeper
question (multi-station roll-call format, threading, lighter telling)
is still mostly TBD.

User also clarified important nuances:

- "We don't always want to roll-call though" — but don't preclude it
  in the data structure. Roll-call should be a callable generator
  format, not the only output.
- "Maps are easy to add. The hard part is the text." → maps are
  table-stakes-but-not-the-engine; voice work is the real lever.
- "We don't want to give up our generator and evaluator model" →
  keep two-model architecture. Don't collapse to single-pass Opus.
- "I'm unemployed!" → cost matters. But: "let's do it right for now"
  → keep Sonnet 4.6 evaluator running ($25-45/mo); don't switch to
  Opus; don't switch to Haiku; just have the kill switch ready.

## What shipped this session (chronological)

1. **`22cbc8e`** — Fire reverse-geocoder upgrade. `firms.py::
   reverse_geocode_simple` was returning continent-level labels
   ("somewhere in Asia"). Replaced with a 70+ entry bounding-box
   lookup ordered most-specific to least-specific. "Eastern Siberia,
   Russia" / "Patagonia, Argentina" / "the Kazakhstan steppe" / "the
   Northern Territory, Australia" — properly named regions globally.
   `_lat_lon_to_region` and `_lat_lon_to_country` retained as thin
   wrappers for backward compat.

2. **`023c3ed`** — FRP floor raised 100 → 250 MW. Sub-200 MW fires
   produced weak copy ("a coal plant runs at 150 MW, this is one of
   those") because the math was forced. 250 MW is closer to the
   "this reads as a real incident" threshold. Plus
   `docs/VOICE_FAILURE_ANALYSIS.md` added — names five Gemini ruts
   from the corpus with concrete intervention sketches.

3. **`d99ffe4`** — `docs/DRAFT_CORPUS.md` added with 2026-04-24
   section: full inventory of all 35 pending drafts including text,
   grade, and commentary. Then bulk-rejected all 35 via direct Gist
   PATCH. Pending queue cleared. The texts remain preserved in
   the doc as the longitudinal-corpus baseline.

4. **`827a891`** — Voice engine v2: per-signal-type prompt
   addendums + stock-formula rejector. Universal prompt updated to
   explicitly ban "powers N homes," generic power-plant comparisons,
   "no name yet" closers, continent-only locations. Per-category
   addenda for fire, all_time_high/low, monthly_high, anomaly_hot,
   country_high/low, record, co2_milestone, marine_heatwave,
   ice_mass_record, fire_footprint, synthesis. Regex rejector at
   parse time as last-line defense. Removed stale Siberia
   power-plant exemplar that was teaching Gemini the bad pattern.

5. **`d0977af`** — `docs/LEVEL_UP_PLAN.md` added. **Tier ordering
   was wrong on first pass** — I had Tier 1 = "post-publish analytics
   loop" until user pointed out we don't post enough for analytics
   to mean anything. Should re-read with quality work as Tier 1 and
   analytics as Tier 2-3. Worth a revision.

6. **`e25d0f0` then `b33d4a8`** — Gemini 2.5 Flash → 3.x model upgrade.
   First attempt pinned `gemini-3.1-flash-lite-preview` (user
   correctly flagged Lite is wrong for voice work). Second iteration
   switched to the `gemini-flash-latest` alias which Google rolls to
   whatever the current best Flash is. `GEMINI_MODEL` env var lets
   prod swap to a pinned snapshot or fall back to 2.5 instantly.

7. **`fa768a4`** — Two future-lane parking entries in `docs/IDEAS.md`:
   - Grok 4 A/B as candidate generator (xAI is the only frontier
     model trained on Twitter/X data — most ideologically aligned
     with our publishing platform).
   - Fine-tune Gemma 4 / Qwen 3.5 / Llama 4 on the @extremetemps
     corpus + EXEMPLARS + our A/B drafts. The differentiated bet —
     no other climate Twitter account is doing genre-specific
     fine-tuning. ~1 week of work, ~$100-300 compute.

8. **`4f07d50`** — BRIEFING cost figure corrected $60-90 → $25-45/mo.
   Previous figure was inherited from a prior session and never
   recalibrated. Real spend verified against console.anthropic.com.

9. **`1573d15`** — Added `EVALUATOR_ENABLED` env var kill switch
   (default `true` so no behavior change). Set to `false` to skip
   the Sonnet evaluator pass and drop Anthropic spend to ~$0/mo.
   Documented in BRIEFING secrets table.

## What's pinned mid-implementation

1. **Multi-station roll-call format for `simultaneous_records`.** The
   signal currently triggers on 5+ cities globally same day but the
   generator emits a flat summary ("5 cities broke records today")
   instead of a per-station list ("26.8 Janakpur / 24.1 Dang 663m /
   20.4 Dhankuta 1192m"). User saw this gap and said do it but keep
   roll-call as one *option* among formats — not the only output.
   Implementation pinned when user redirected to models conversation.

2. **Elevation surfacing in record/anomaly generators.** Elevation
   column added to cities.csv (this session) but the generator
   prompts don't yet pull it through. Tropical-night-in-the-highlands
   stories ("never happened above 1200m") need this data in the
   prompt context.

3. **13 cities missing elevation values.** Bulk fetch hit a 429 on
   the last batch. Trivial retry — just rerun the fetch script for
   the rows where `elevation_m` is empty.

## Other open threads

- **Voice rules still over-engineered for the wrong genre.** Voice
  engine v2 helped (allows some editorial heat earned by data) but
  the @extremetemps comparison shows we may still be too prim. Worth
  another voice-prompt iteration after observing what the new model
  + new prompt produce in the next draft cycle.
- **`docs/LEVEL_UP_PLAN.md` Tier ordering is wrong.** Tier 1 should
  be quality-side (era-anchor database, regenerate-corpus, prompt
  iteration), not analytics. Worth a revision.
- **Fine-tune lane** is the most differentiated future move. Real
  data sitting unused. Parked for now per user's "do it right for
  now" pace.

## Numbers

- Tests: 501 → 522 across the session (+21)
- Commits pushed: 9 to `main`
- API spend: $25 since April 7 (~$1.50/day) — verified
- Cities tracked: 613 across 179 countries with elevation
- Pending drafts: 0 (cleared after corpus archival)

## When picking up in the next session

1. Read `BRIEFING.md` (project state)
2. Read `docs/DRAFT_CORPUS.md` 2026-04-24 section (the corpus that
   informed every voice change today)
3. Read `docs/VOICE_FAILURE_ANALYSIS.md` (named patterns)
4. Read this `SESSION_BRIEF.md` (what just happened)
5. Read `docs/NEXT_SESSION.md` (action menu for the new session)
6. Pull current pending drafts from the Gist — see whether the next
   alerts cycle output reflects voice engine v2 quality lift
