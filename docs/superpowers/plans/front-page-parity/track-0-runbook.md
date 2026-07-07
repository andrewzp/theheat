# Track 0 runbook — flip and live-verify Bet A (rows 1–2)

> **Who does what:** Andrew runs the three `gh variable set` commands (prod flag flips
> are his). ANY session (or a lesser model on watch duty) runs the verification steps —
> they are read-only. Roll back any step with the single `gh variable set … --body 0`
> shown beside it. Source of truth for design intent:
> [the Bet A spec](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md)
> §Flags and rollout.

**Goal:** the newsworthiness lane live (A0), then sourced-impact enrichment (A1), then
near-miss boost (A2) — each verified on real cycles before the next flip.

## Step 1 — master (A0): retrieval lane + news-gap watch. Zero editorial surface.

> **STATUS: LIVE 2026-07-07 12:59:59Z — VERIFIED.** Across post-flip cycles: the
> `newsworthiness` source row reports `success` (never `skipped`); `news_events`
> citations hand-checked by replaying the exact NIFC query against the live feed —
> every claim/value pair matched verbatim; news-gap watch (#395) was discriminating
> (2 real gaps, 8/10 events matched, no false gaps); ≤5 LLM calls/cycle; zero
> editorial surface. A0 verification complete.

Andrew:
```bash
gh variable set THEHEAT_NEWSWORTHINESS_ENABLED --body 1 --repo andrewzp/theheat
```
Rollback: `gh variable set THEHEAT_NEWSWORTHINESS_ENABLED --body 0 --repo andrewzp/theheat`

Watcher, after the NEXT 2–3 alerts cycles (cron `0 0,4,8,16,20 * * *` UTC — wait for at
least two to complete; check with
`gh run list --repo andrewzp/theheat --workflow bot.yml --limit 6`):

- [ ] **The source row exists and is not failing.** In the latest alerts run log
  (`gh run view <run-id> --repo andrewzp/theheat --log | grep -i newsworthiness`),
  the `newsworthiness` source reports `success` or `degraded` — `skipped` means the
  flag didn't reach the run (check `bot.yml` env passthrough), repeated `failed` means
  roll back and investigate.
- [ ] **`state["news_events"]` is populating with real citations.** The state gist is
  operator-visible via the dashboard, or ask Andrew to paste the `news_events` block.
  For each of 2–3 entries: open the `url` by hand and confirm the page supports the
  `claim`/`value`, the `source_name` matches the page's publisher, and `as_of` is
  within the last 72h. ANY entry with a missing/mismatched warrant → roll back (this
  is the iron constraint failing, which the verify ladder should make impossible).
- [ ] **Impact-entry hygiene:** every entry's `impact[]` items each carry
  `source_name` + `url` + `as_of` (the parse-time floor working).
- [ ] **News-gap watch sanity.** `gh issue list --repo andrewzp/theheat --label
  source-health-sentinel` — after the sentinel's next 4h run, a "News-gap watch"
  issue may appear. Sanity-check it: each listed gap should be a real, verified world
  event (fire / heat mortality) that the bot genuinely has no candidate for. A gap
  issue full of events we DID draft = matcher bug, file an issue; no gap issue at all
  is fine (quiet news window).
- [ ] **Cost check:** the lane makes ≤5 LLM calls/cycle by design; nothing to meter
  manually, but a runaway (many Gemini calls in the log) → roll back.

## Step 2 — enrich (A1): sourced human impact on matched bundles. FORCED manual review.

> **STATUS: LIVE 2026-07-07 16:23:52Z** (Andrew's explicit go). Pre-flip gate re-run
> GREEN on current main (evidence contract PASS; a candidate SHIPS the full ladder;
> `[decision4] … FORCED manual_only (cited_impact)`). Verifying: clean across 3+ cycles —
> flag reaches every run, no runaway, **P0 guard holds (zero autoship-armed impact
> drafts)**. NOTE: enrichment has not yet FIRED a live human-impact draft (stochastic —
> current `news_events` are all NIFC structured fire data). The manual-only mechanism is
> proven by the dryrun gate; the remaining live spot-check (enriched figures verbatim +
> source named) awaits the first real enriched draft.

Precondition: Step 1 verified across ≥2 cycles.

Watcher first — re-run the pre-flip gate on CURRENT main:
```bash
gh workflow run news-enrich-dryrun.yml --repo andrewzp/theheat
gh run list --repo andrewzp/theheat --workflow news-enrich-dryrun.yml --limit 1
gh run view <run-id> --repo andrewzp/theheat --log | tail -40
```
- [ ] The run is GREEN (this workflow has NO `|| true` — red means do not flip), and the
  log shows: evidence contract PASS, at least one candidate SHIPS through
  writer→safety→§F→fact-check→critic, `[decision4] … FORCED manual_only (cited_impact)`
  on impact-citing drafts.

Andrew:
```bash
gh variable set THEHEAT_NEWS_ENRICH_ENABLED --body 1 --repo andrewzp/theheat
```
Rollback: `gh variable set THEHEAT_NEWS_ENRICH_ENABLED --body 0 --repo andrewzp/theheat`

Watcher, next 2–3 cycles:
- [ ] Any impact-carrying draft appears ONLY in the manual queue (`approval_mode` never
  `auto` for drafts whose text cites an impact figure; the dashboard shows them
  pending). An impact-citing draft with autoship armed = P0, roll back immediately.
- [ ] Spot-check one enriched draft's figures against its `human_impact` entries: value
  verbatim-or-plainly-rounded AND the entry's `source_name` named in the tweet text.
- [ ] The writer's non-enriched output is unchanged (no impact language on bundles
  without `human_impact`).

## Step 3 — boost (A2): capped near-miss rescue at the fire score gate.

> **STATUS: NOT YET FLIPPED — Andrew's next flag action.** Precondition (A1 verified
> ≥2 cycles) is met for the SAFETY invariant (P0 guard holds); recommendation is to
> wait for ≥1 live enriched draft to spot-check figures before flipping, OR accept the
> dryrun proof. Andrew's call + explicit go.

Precondition: Step 2 verified across ≥2 cycles.

Andrew:
```bash
gh variable set THEHEAT_NEWS_BOOST_ENABLED --body 1 --repo andrewzp/theheat
```
Rollback: `gh variable set THEHEAT_NEWS_BOOST_ENABLED --body 0 --repo andrewzp/theheat`

Watcher, over the following days (boosts only fire when a near-miss + a matched verified
news event coincide — may be days apart):
- [ ] Suppression ledger / dashboard Suppressed tab: any rescued or killed fire whose
  `score.reasons` carries `news_boost=+8 per <source> (<url>)` — the provenance must be
  present and the URL real.
- [ ] No boost ever appears on a candidate more than 8 below threshold (the hard floor),
  and never without a structured/verified news match.
- [ ] A rescued draft is still `manual_only` if it cites impact (decision 4 unaffected).

## After all three are live

- Row 8 (FPP weekly rollup) gains real data — build it if not yet built.
- `writer-dryrun.yml` (`--type fire`) is the ongoing fire-voice iteration loop.
- Record the flip dates in the next handoff; the A3 evidence clock (row 12) starts at
  Step 1's flip.
