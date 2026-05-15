# Lane 12 — Plan D: Global Floods (Copernicus EMS)

**Branch:** `plan-d/global-floods`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (Bucket 4: global floods)
**Scope:** Add non-US flood event detection via Copernicus Emergency Management Service
**Estimated time:** 4-6 hours CC, single PR
**Parallel-safety:** **Conflicts with Lane 13 (precip/snow), Lane 14 (climate indices), Lane 15 (threshold registry)** — all touch `src/main.py`, `src/editorial/scoring.py`, `src/two_bot/intern.py`. Sequential with those. Parallel-safe with Lane 16 (main.py refactor) only if 16 hasn't started; otherwise must wait.

## Why this lane exists

@theheat currently has no non-US flood coverage. USGS river gauges cover US only; the broader story (Pakistan 2022, Sudan 2024, BC atmospheric river 2021, German flash floods 2021) is invisible. Copernicus EMS — the European Commission's emergency mapping service — publishes a continuously updated GeoJSON feed of activated flood events globally. Free, no token required for public feeds. Standard climate-diary material when a flood is the lede story of the week.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) — Bucket 4 reference
2. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/gdacs.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/gdacs.py) — closest precedent. GDACS is also Copernicus-adjacent global disaster feed. Same polling + tier-dedup model.
3. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/river_gauges.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/river_gauges.py) — US-only flood handling (post-Phase-2 NWS AHPS implementation). Don't duplicate; Plan D is the global-coverage complement.
4. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_http.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_http.py), [/Users/andrewpuschel/Documents/Claude/theheat/src/data/source_status.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/source_status.py), [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_freshness.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_freshness.py) — Phase 1 helpers (use them).
5. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_climate_context.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_climate_context.py) — F2 helper. Wire `local_climate_context(lat, lon, category="flood")` into the bundle builder.

## Source details

**Copernicus EMS Rapid Mapping activations (primary feed):**
- Public RSS/JSON: `https://emergency.copernicus.eu/mapping/list-of-activations-rapid` (HTML index) + per-activation JSON detail pages
- Alternative: `https://emergency.copernicus.eu/api/v1/activations/?event_type=flood` — investigate as first commit (live curl to confirm current schema)
- Each activation has: event_id, event_type (`flood` / `flash_flood` / `storm_surge`), country, location, activation_date, severity_tier, affected_area_km2, populations_affected

**GDACS flood subset (backup signal):**
- GDACS already on the pipeline. Filter `event_type == "Flood"` from existing feed for cross-verification.

## Detection rules

Fire when a Copernicus EMS activation crosses any of:

1. **New flood activation** (severity = `Major` or higher). Each activation_id = one event.
2. **Escalation** of an existing activation (e.g., `Moderate` → `Major`). Mirror GDACS tier-dedup; use `state.flood_activation_tiers[activation_id] = last_fired_severity`.
3. **Population impact threshold:** `populations_affected >= 100_000` for any single activation, regardless of severity tier. The "lots of people affected" cut is the editorial bar.

## Files

- `src/data/copernicus_ems.py` (new) — `CopernicusFloodActivation` dataclass + `fetch_active_flood_activations()` + `detect_flood_events()` + dedup helpers. Use `fetch_with_retry` from `_http.py`. Use `assert_response_schema` and `assert_freshness` from Phase 1.
- `src/editorial/scoring.py` — `score_global_flood(severity, populations_affected, affected_area_km2, country)` with threshold around 72 (event-driven sources)
- `src/two_bot/intern.py` — `build_global_flood_bundle(event)`. Call `local_climate_context(lat, lon, category="flood")` for the F2 enrichment. Bundle must carry: activation_id, country, event_type, severity, populations_affected, affected_area_km2, lat, lon, activation_date, copernicus_url.
- `src/editorial/approval.py` — flood events → `manual_only` (life-safety adjacent; human approves)
- `src/main.py::run_alerts` — wire the section in the standard order
- `src/state.py` + `src/state_schema.py` — add `flood_activation_tiers: dict[str, str]` (activation_id → last severity fired)
- `tests/test_copernicus_ems.py` (new) — detector tests (severity tiers, dedup, population threshold) + scoring tests + integration in `run_alerts`

## Editorial constraints

- **No life-safety bait.** Same rule as cyclones (Plan C). Banned: "catastrophic", "deadly", "life-threatening." The bot is a climate diary, not a warning service.
- **Country naming:** use Copernicus EMS canonical country names (matches ISO 3166 + EU naming). Don't translate or shorten.
- **No "BREAKING" openers.** Safety pipeline already bans these.
- **Annual cap:** none. Major floods are intrinsically high-bar — the score gate filters routine activations. Track `state.flood_annual_count` for visibility.

## Acceptance

- mypy clean, ruff clean
- Full suite passes with ~25+ new tests
- Live source smoke: `copernicus_ems.fetch_active_flood_activations(strict=True)` returns a list (possibly empty during dry-season weeks).
- Manual workflow dispatch run passes: `gh workflow run bot.yml -f mode=alerts && gh run watch`
- After deploy: 3 consecutive alerts crons show `copernicus_ems: success/skipped` in run_history.

## Constraints

- **Investigation-first commit.** First commit: live curl the Copernicus EMS feed, capture schema, document any deviation from this brief.
- **No new dependencies.** stdlib + `requests` only.
- **Subagent model floor:** Sonnet 4.6 default, never Haiku.
- **Verify the wire.** After deploy, manually trigger an alerts cron during a known flood event (or use a recent archive fixture) and confirm a flood bundle reaches `fact_check` and passes.

## Branch / PR sequence

1. Branch `plan-d/global-floods` from `main`.
2. Investigation commit (curl + doc).
3. Implementation commits per file group.
4. mypy + pytest + workflow dispatch.
5. PR → CI green → Claude merges per the standing rule.

Done. ~4-6 hours CC.
