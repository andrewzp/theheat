# Conductor Lanes — Deferred Detection Work

Four independent lanes, each adds a new data source or synthesis layer to
@theheat's detection pipeline. They're independent enough to run in parallel
worktrees — no two lanes touch the same scoring/generator region (except all
four modify `main.py`'s `run_alerts` orchestrator, which merges cleanly as
long as each lane adds its section in the standard order).

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
