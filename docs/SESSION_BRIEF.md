# Session Brief — April 19–22, 2026

Handoff doc for picking up @theheat work in a new session. Read after
`BRIEFING.md`.

## Where we landed

`main` is at commit `0be88fc`. Four detection lanes merged. 501 tests
passing. Feed is actively drafting across the new signal types plus the
existing per-city records and wildfires.

## What shipped this session (chronological)

### Editorial cleanup first (before the lane work)
1. **Same-city-same-day dedup** — highest signal score wins per
   `(city, YYYY-MM-DD)`. A stronger signal that arrives later supersedes
   a still-pending weaker draft.
2. **3-day per-city cooldown** with elite carve-out (all-time, anomaly
   ≥18°C, record streak, NOAA confirmation) and a copy-quality bypass
   (`candidate_score.total ≥ 95`).
3. **Same-year monthly record suppression** — fixed the "Svalbard may hit
   41.5F, old record set in 2026" nonsense framing by suppressing
   monthly records whose prior record is from the current year.
4. **CO2 weekly pathway killed entirely** — routine YoY noise framed as
   "the direction" was denial-adjacent. Milestones only now.
5. **12-tweet/year cap on CO2** via `co2_annual_count` state.
6. **NOAA confirmation pipeline killed entirely** — "NOAA confirms X
   broke the record" was redundant news (we already told the reader)
   and opens with NOAA, which the safety pipeline bans. 417 lines
   removed.
7. **FIRMS letter-confidence fix** — VIIRS_SNPP_NRT returns
   categorical `l`/`n`/`h`; the old parser silently dropped every row.
   That's why fire detection returned 0 for an entire day.
8. **NWS widened** — added Blizzard, Ice Storm, Extreme Cold, Extreme
   Heat Warnings to the tracked set. All Extreme-tier, all rare.
9. **City list 257 → 613, 179 countries.** Better global coverage.
10. **Country-level records** — `France's hottest day in 30 years`
    signal that aggregates across all sampled cities in a country,
    threshold 82, elite-tier.

### The four lanes (Conductor worktrees, merged to main)

- **Lane 1 (Ocean SST).** NOAA OISST v2.1 global-mean SST via
  ClimateReanalyzer. Fires on archive-record streaks of 5+ days — day-5
  first-fire, then milestones at 10, 25, 50, 100, 150, 200, 250, 300,
  365, 400, then every +50 thereafter. Threshold 78, suggested_auto
  with 90-min delay.
- **Lane 2 (GRACE ice mass).** JPL PODAAC Level-4 mascon time series
  for Greenland + Antarctica. Two detectors: *monthly loss record* and
  *cumulative milestone* (each −1000 Gt crossing). Mondays only. Capped
  at 8 tweets/year across both regions. Requires `EARTHDATA_TOKEN` —
  first authenticated source in the pipeline.
- **Lane 3 (Fire footprint — NIFC).** NIFC WFIGS US fire-complex
  cumulative burn area with acreage-tier dedup (Dixie Complex
  20k→50k→100k produces one draft per tier, not per day). GWIS was the
  original target but publishes WMS map layers only as of Apr 2026 —
  pivoted to NIFC per the plan's explicit fallback. US-only.
- **Lane 4 (Cross-source synthesis).** Meta-layer that fires a single
  compound tweet when 3 conditions converge on the same US state within
  14 days: exceptional (D4) drought, a qualifying wildfire, and a
  qualifying heat record. Threshold 82, suggested_auto with 120-min
  delay. Scaffolding supports additional rules (marine×coastal heat,
  hurricane×surge×flood) once their input data is stable.

### Codex review + fixes (end of session)

Codex found 4 bugs in the merged lanes; all fixed in `0be88fc`:

- **P1** `_merge_state` dropped `synthesis_components` /
  `synthesis_cooldown` — every persisted Gist write reset the 14-day
  window and cooldown map. Added proper merge logic.
- **P1** `sqlite_store` round-tripped only 7 legacy keys; every
  lane-added key read back as default. Added 15 lane keys via the
  metadata table. Schema stays additive.
- **P2** Synthesis scorer expected heat anomaly but received absolute
  temperature; a 40°C forecast was treated like a 40°C anomaly.
  Writer now computes proper anomaly (true `anomaly_c` for anomaly
  events, margin-over-prior-record for record events).
- **P2** Per-cycle cap pruned drafts but left their `event_id`s in
  `posted_events`, permanently blocking future cycles from re-drafting
  those events. Extracted `_prune_weakest_cycle_drafts()` that cleans
  `posted_events` and rolls back overstated source telemetry.

## Current pipeline state

- **Tests:** 501 passing
- **Signal types firing regularly:** per-city temperature records
  (all-time, monthly, calendar-date, streaks), FIRMS wildfires,
  NWS severe weather (incl. new winter extremes), GDACS Red-tier
  disasters, CO2 milestones (natural rate ~2-3/yr), Hot 10 leaderboard
- **Signal types waiting on conditions:** Country records (need 2+
  cities in same country breaking same day), Marine heatwave (5-day
  archive-record confirmation window), Ice mass (Mondays only, monthly
  publication lag), Fire footprint (US fire complex crossing acreage
  tier), Synthesis (D4 drought + fire + heat in same US state in 14-day
  window)
- **Today's pending draft queue** (as of Apr 22 16:19 UTC): 13 drafts
  — 10 fires, 2 Alaska blizzards, 1 Sevilla record. The Sevilla record
  is the strongest of the batch ("when most people alive now were in
  elementary school" era anchor).

## Known issues flagged this session

1. **Fire reverse-geocoder is too coarse.** `firms.py::
   reverse_geocode_simple` returns continent-level labels like
   "somewhere in Asia." Gemini then produces drafts that literally
   admit "location unknown." Needs either bounding-box country
   detection or a bundled polygon dataset.
2. **Stray `theheat/theheat/` duplicate subdirectory** — Conductor
   worktree artifact. Untracked. Safe to `rm -rf theheat/theheat/`.
   Causes `ImportPathMismatchError` on repo-root pytest.

## Still deferred (see `docs/IDEAS.md`)

1. **Voice engine upgrade** — data-ticker tweets are "ok" but not
   breakout. Candidates: generator system prompt rewrite, tighter
   Sonnet evaluator calibration, dedicated "lead with the stake"
   rewrite pass.
2. **Geographic spread tiebreaker in per-cycle cap.**
3. **GWIS global fire footprint** — revisit if they publish a JSON API.
4. **Additional synthesis rules** — marine×coastal heat, hurricane×
   surge×flood (needs hurricane season so the rule can be observed
   firing in production before we trust it).
5. **Visual cards** — data quality needs to prove out first.
6. **RSS enrichment** — Carbon Brief, Climate Central feeds for context.

## Voice calibration note

User reviewed drafts late in the session and said: *"they are ok.
neither is going to go viral by any stretch."* This is a real ceiling
that lane work doesn't address — more signal types produce more tweets,
not better ones. The generator + evaluator are unchanged from the start
of the session. `brand/EXEMPLARS.md` is explicit that breakout viral
climate content requires human-shaped moments (Thunberg, Hausfather)
that pure automation can't reliably produce. The pipeline's genre is
"data-ticker excellence" (the @extremetemps model), with occasional
breakout moments possible when the underlying data is genuinely
unbelievable.

Voice engine upgrade is the next lane worth considering.

## Current running state

- **Latest commit:** `0be88fc`
- **Cities tracked:** 613 across 179 countries
- **New secrets required for prod:** `EARTHDATA_TOKEN` (for Lane 2). If
  unset, the ice_mass source short-circuits to skipped. Everything else
  works.

## When picking up in a new session

1. Read `BRIEFING.md` first (full project state — updated 2026-04-22)
2. Read this `SESSION_BRIEF.md` for recent context
3. Read `docs/NEXT_SESSION.md` for the start-of-session menu
4. Check `git log --oneline -10` to see anything landed since
5. Check dashboard at https://dashboard-phi-beryl-65.vercel.app for
   current draft queue
6. If voice/quality comes up first, the candidates are in
   `docs/IDEAS.md` → "Voice engine upgrade"
