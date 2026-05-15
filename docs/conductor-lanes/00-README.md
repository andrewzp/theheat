# Conductor Lanes — Parallel Workstreams

## Currently startable (2026-05-15)

### Queue order (each waits for the prior to merge — all touch main.py + scoring.py + intern.py)

| # | Lane | Time | Notes |
|---|---|---|---|
| 1 | [08 — Plan B: Coral DHW + CH4 methane](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/08-plan-b-coral-dhw-ch4.md) | 4-5 hr | in flight 2026-05-14 22:12 |
| 2 | [12 — Plan D: Global floods (Copernicus EMS)](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/12-plan-d-global-floods.md) | 4-6 hr | non-US flood coverage |
| 3 | [13 — Plan E: Precip + Snow (GPM-IMERG + NSIDC)](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/13-plan-e-precip-snow.md) | 5-7 hr | requires NASA EarthData token |
| 4 | [14 — Plan F: Climate indices (NAO/AO/PDO + ozone)](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/14-plan-f-climate-indices.md) | 3-4 hr | long-arc + seasonal signals |
| 5 | [15 — Threshold registry refactor](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/15-threshold-registry.md) | 2-3 hr | centralize ~25 magic numbers |
| 6 | [16 — main.py refactor (split monolith)](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/16-main-py-refactor.md) | 3-4 hr | 3,070 → ~50 line entrypoint + modules |

### Recently landed (2026-05-14 → 05-15)

| Lane | Status |
|---|---|
| [05 — Plan A foundation + restore + degraded fix](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/05-plan-a-foundation.md) | all 3 phases shipped (#99, #102, #105) |
| [06 — Plan A state trim](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/06-plan-a-state-trim.md) | shipped (#98) |
| [07 — Plan A dashboard /health view](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/07-plan-a-dashboard.md) | shipped (#101 + #103) |
| [09 — Plan C tropical cyclones](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/09-plan-c-tropical-cyclones.md) | shipped (#108) — ready for Atlantic season |
| [10 — Docs cleanup](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/10-docs-cleanup.md) | shipped (#106) |
| [11 — F2 bundle enrichment](/Users/andrewpuschel/Documents/Claude/theheat/docs/conductor-lanes/11-f2-bundle-enrichment.md) | shipped (#107) |

Plan-of-record for Plan A: [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md)

## Legacy: lanes 01-04 (shipped, archived for reference)

Four older lanes from a coverage-expansion initiative. All four shipped earlier in 2026 and are now part of the pipeline (ocean_sst, ice_mass, fire_footprint, synthesis). Files kept for the lane-prompt pattern reference only. Don't re-execute.

---

# Original lane conventions (still applies to 05/06/07)

The original four lanes were independent enough to run in parallel worktrees — no two
lanes touched the same scoring/generator region (except all four modified `main.py`'s
`run_alerts` orchestrator, which merged cleanly as long as each lane added its section
in the standard order).

Before starting ANY lane, read in this order:

1. `BRIEFING.md` (root) — current pipeline, approval policies, state shape
2. `PIPELINE.md` (root) — flow diagram
3. `docs/IDEAS.md` — why these were deferred
4. `brand/VOICE.md` + `brand/MESSAGING_ARCHITECTURE.md` — voice rules
5. The lane prompt itself (01 / 02 / 03 / 04)

## Shared constraints every lane must respect

- **Utility, not business.** No follower/engagement optimization.
- **Set-and-forget.** No new human-in-the-loop layers.
- **$0 recurring.** Free-tier APIs only. No new paid services without asking.
- **Honest framing.** If the archive is 30 years, say "30 years of records,"
  not "ever." Any dataset window must be explicit in the copy.
- **Extreme only.** Routine data isn't tweetable (killed CO2 weekly,
  NOAA confirmations in April 2026). New signals must meet the bar:
  a smart non-expert should say "wait, what?" when they see it.
- **No press-release openers.** Safety pipeline bans NOAA/NWS/GDACS etc.
  as tweet openers. The generator must phrase signals in the data-ticker
  voice, not the agency's.
- **No meta-commentary.** "THIS IS SERIOUS" / "catastrophic" / "life-
  threatening" all banned by the safety pipeline.
- **Annual cap pattern** (if relevant). CO2 is capped at 12/year — if a
  new signal type has similar "drip-drip" risk, add a matching cap.

## Existing reference patterns

- Simple polled API with event-type filter: `src/data/nws_alerts.py`
- Evolving-event dedup (intensity tiers): `src/data/gdacs.py`
- Scheduled fetch (day-of-week gate): `src/data/sea_ice.py`, `src/data/drought.py`
- CSV parse with schema edge-cases: `src/data/firms.py`
- Aggregate-across-readings: `detect_country_records` in `src/data/open_meteo.py`

## Pipeline conventions

- Each source module defines dataclasses for its events and a `fetch_*` /
  `detect_*` function. Data-source modules never write to state directly.
- `main.py::run_alerts()` adds a source section: fetch, per-event loop,
  score via `_should_draft`, generate via `generator.generate_*_tweet`,
  save via `_save_generated_draft`.
- `_record_source_run` at the end of every section captures observed /
  promoted / drafted / error for the dashboard.
- Scores defined in `src/editorial/scoring.py` with category + threshold.
- Approval policy in `src/editorial/approval.py`.
- Category hints in `src/editorial/candidates.py`.
- Fallback template in `src/voice/templates.py`.
- Generator in `src/voice/generator.py` using `generate_tweet()`.

## Running tests

```
source .venv/bin/activate && python -m pytest
```

Full suite is ~320 tests. Every new signal type should add:
- detector tests (happy path + edge cases)
- scoring tests (above/below threshold)
- a `run_alerts` integration test in `tests/test_main.py`

## Branching / PRs

Each lane should branch from `main`, keep the diff focused, and open its
own PR. Don't bundle lanes. If a lane discovers a bug in shared code,
fix it in a separate commit on that lane's branch with a clear message.
