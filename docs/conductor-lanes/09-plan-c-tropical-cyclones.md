# Lane 09 — Plan C: Tropical Cyclones (NHC + JTWC)

**Branch:** `plan-c/tropical-cyclones`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (Plan C: Bucket 3)
**Scope:** Add tropical cyclone track data — NHC (Atlantic + East Pacific) + JTWC (Western Pacific, Indian Ocean, Southern Hemisphere)
**Estimated time:** 5-7 hours CC, single PR
**Parallel-safety:** **Conflicts with Lane 08 (coral/methane), Lane 11 (F2)** — touches `src/two_bot/intern.py`, `src/editorial/scoring.py`, `src/main.py`. Sequential with those.
**Time pressure:** Atlantic hurricane season starts **June 1**. Useful to land before then so the bot can narrate the season.

## Why this lane exists

@theheat has a structural gap: when a major hurricane is happening (Helene 2024, Beryl 2024, Otis 2023), the bot cannot narrate it. GDACS catches Red-tier disasters when they're declared, but the *evolution* of a cyclone (Cat 1 → Cat 4 in 36 hours, eye-wall replacement, rapid intensification, landfall) is invisible. Cyclones are some of the most "diary of a warming planet"–shaped stories — rapid intensification is the climate-change-amplified hurricane story.

This lane wires two operational sources for global cyclone coverage:

- **NHC** (National Hurricane Center) — Atlantic + East Pacific (NorthAm-relevant)
- **JTWC** (Joint Typhoon Warning Center) — Western Pacific, North Indian Ocean, Southern Hemisphere

Combined coverage is ~95% of global cyclone basins.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) — see "Plan C: Bucket 3" reference
2. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/gdacs.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/gdacs.py) — existing evolving-event tier dedup pattern (Cat 3→4 strengthening). Cyclones follow the same model.
3. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/nws_alerts.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/nws_alerts.py) — polled API + event-filter pattern.
4. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_http.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_http.py), [/Users/andrewpuschel/Documents/Claude/theheat/src/data/source_status.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/source_status.py), [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_freshness.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_freshness.py) — Phase 1 helpers.
5. [/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md](/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md) — section on GDACS tier dedup is the closest precedent.

## Sub-task 9a — NHC (Atlantic + East Pacific)

**Source:** NHC publishes active advisories as text products + Best Track XML/JSON archives.
- Live advisories: `https://www.nhc.noaa.gov/CurrentStorms.json` (active storms with public_advisory URLs)
- Per-storm forecast: parse from the public advisory JSON or follow the GIS XML
- Free, no token

**Detection rules** (fire when ANY of these cross a threshold):

1. **Rapid intensification (RI):** wind speed increases ≥30 kt in 24 hours. This is the canonical climate-change-amplified hurricane signal.
2. **Saffir-Simpson tier crossing:** Cat 1→2, 2→3, 3→4, 4→5. Each crossing = one event. Mirror GDACS tier dedup at `src/data/gdacs.py`.
3. **Major hurricane landfall:** Cat 3+ landfall confirmed in advisory. One event per landfall.
4. **Basin records:** earliest Cat 4+ on record, latest Cat 5 on record, etc. — surface when archive data supports.

**Files:**
- `src/data/nhc.py` (new) — `CycloneAdvisory`, `RapidIntensificationEvent`, `TierCrossingEvent`, `LandfallEvent` dataclasses + `fetch_active_cyclones()` + `detect_*` functions
- `tests/test_nhc.py` — happy path + RI detection + tier dedup + landfall detection

## Sub-task 9b — JTWC (other basins)

**Source:** JTWC publishes warnings as text + RSS feeds.
- Live warnings: `https://www.metoc.navy.mil/jtwc/products/atcf/` and the RSS at `https://www.metoc.navy.mil/jtwc/rss/jtwc.rss?layout=enhanced` (verify current URL via curl as the first commit; JTWC has reorganized the feed in the past)
- Free, no token

**Detection rules:** Same as NHC's rules 1-3 (rapid intensification + tier crossing + landfall). Same dedup model.

**Note on JTWC categories:** JTWC uses its own naming (Tropical Storm, Typhoon, Super Typhoon) but the underlying wind speeds map cleanly to Saffir-Simpson. Normalize at the data-layer boundary so the bundle uses one consistent scale.

**Files:**
- `src/data/jtwc.py` (new) — mirror NHC's shape with JTWC-specific parsing
- `tests/test_jtwc.py` — happy path + category normalization + tier dedup

## Sub-task 9c — Shared scoring + bundle + orchestrator

**Files:**
- `src/editorial/scoring.py` — add:
  - `score_cyclone_rapid_intensification(delta_kt_24h, current_category, basin)` — high severity for RI ≥ 35 kt
  - `score_cyclone_tier_crossing(from_cat, to_cat, basin)` — escalating with tier crossed
  - `score_cyclone_landfall(category, location, basin)` — Cat 3+ landfall scores elite
- `src/two_bot/intern.py` — `build_cyclone_*_bundle()` functions per event type. Bundle must carry: storm name, basin, category, wind speed kt, central pressure mb, lat/lon, advisory number, public_advisory URL.
- `src/editorial/approval.py` — cyclone events → `manual_only` (high-stakes, life-safety adjacent; human approves)
- `src/main.py::run_alerts` — wire NHC + JTWC sections
- `src/state.py` + `src/state_schema.py` — add `cyclone_tiers: dict[str, int]` (storm_id → last-fired tier) for dedup

**Editorial constraints:**
- **Voice rule (extreme caution):** cyclones are life-safety events. Banned: "catastrophic", "life-threatening", "deadly", any framing that mocks or trivializes the event. The bot is a climate diary, not a warning service.
- **No "BREAKING" openers.** The safety pipeline already bans press-release openers; cyclones get extra attention because the temptation is highest.
- **Annual cap:** none — cyclone events are intrinsically high-bar (RI ≥ 30 kt, Cat 3+ landfall, Cat 4-5 tier crossings). Let the score gate do its job. Track expected volume in `state.cyclone_annual_count` for visibility but don't enforce a cap until we see data.

## Sub-task 9d — voice-regression coverage

Add at least 3 voice-regression scenarios:
- Rapid intensification (Cat 1 → Cat 4 in 24h)
- Major hurricane landfall (Cat 3 Florida)
- Atlantic basin record (earliest Cat 4 on record)

## Acceptance

- mypy clean
- Full suite passes with ~30+ new tests added (NHC + JTWC + scoring + intern + run_alerts integration)
- Run manual test cron: `gh workflow run bot.yml -f mode=alerts && gh run watch`. New alerts cycle should fetch active storms (probably zero during the off-season) and exit cleanly.
- After deploy: 3 consecutive crons show `nhc: success/skipped` and `jtwc: success/skipped` in run_history.
- Voice regression passes for all 3 new scenarios.

## Constraints

- **Authoritative sources only.** NHC and JTWC are operational forecasters. Don't supplement with social media or unofficial track data.
- **Quote the advisory.** When the bundle's `public_advisory` URL is available, surface it in the bundle so readers can verify.
- **No category-bait.** "It's now a Category 4!" without context is a press-release opener. Frame the rate-of-change or the climate-system mechanism behind it.
- **Subagent model floor:** Sonnet 4.6 default, never Haiku. Cyclone work is high-stakes and worth Opus for the editorial nuance — flag to Andrew if the lane wants to escalate.
- **Verify the wire.** After deploy, manually trigger a test cron during an active storm (or use a recent storm's archive data to simulate). Confirm bundle entity claims pass fact-check.

## Branch / PR sequence

1. Branch `plan-c/tropical-cyclones` from `main`.
2. Investigation first commit: curl NHC + JTWC feeds, capture schemas, document any deviation from the brief.
3. Implementation commits: 9a (NHC), 9b (JTWC), 9c (shared scoring/bundle/orchestrator), 9d (voice-regression).
4. Run mypy + pytest + `gh workflow run bot.yml` + voice-regression.
5. PR → CI green → Claude merges per the standing rule.

Done. ~5-7 hours CC end-to-end. Ship before June 1 to be ready for the Atlantic season.
