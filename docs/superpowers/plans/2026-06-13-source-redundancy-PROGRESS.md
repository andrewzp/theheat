# SOURCE-REDUNDANCY LANE — Progress tracker

> State lives HERE and only here. Each step's PR updates its own row in the same PR.
> Statuses: `TODO` · `IN-PROGRESS` · `DONE` · `DONE(<qualifier>)` · `BLOCKED(<reason>)` · `AWAITING-ANDREW(<what>)`.
> Pick: first TODO whose deps are all DONE. Rails inherited from THIRTY-LOOP §0–§5/§8. Grading ladder: plan §L0.

| Step | Target | Leg added | Kind | Tier | Deps | Status | PR | Note |
|---|---|---|---|---|---|---|---|---|
| R-00 | foundation | source-leg provenance + 2 grades + `with_witness` | infra | A | — | DONE | #269 | `_witness.py` + `source_leg` on 6 dataclasses + 2 prompt grades + survey table; 11 witness tests |
| R-01 | dashboard+sentinel | chain-leg visibility (Py+JS in sync) | infra | A | R-00 | DONE | #270 | `served_via` field (Py+JS byte-equiv), dashboard row chip, runbook; backup-served=degraded not healthy; Vercel prod deployed 2026-06-14 |
| R-02 | firms (NASA 5/40) | NOAA HMS (NESDIS+GOES, N. America) | independent | A | R-00 | DONE | #271 | HMS witness in fetch_fires; observed_alt_host grade; runner degraded telemetry; live-verified 200 |
| R-03 | gpm_imerg (NASA 18/40) | Open-Meteo precip + ensemble filter | independent(model) | A | R-00 | DONE | #274 | with_witness wrap; ≥3-model agreement filter; model_fallback grade; runner telemetry; endpoints live-verified 200 |
| R-04 | gdacs (EU 9/40) | ReliefWeb (UN OCHA) | independent | A | R-00 | AWAITING-ANDREW(appname-approval-email) | | ReliefWeb appname request submitted 2026-06-15 for `TheHeat-GDACSBackup-RW7K2Q` using `contact@theheat.app`; immediate API probe still returns 403 until ReliefWeb approves it. |
| R-05 | river_gauges (403s) | Open-Meteo Flood (GloFAS, model-framed) | independent(model) | A | R-00 | DONE | #279 | model-fallback witness in fetch_river_levels; known USGS coords only; discharge+p75+absolute-floor gate; no ft facts; degraded telemetry |
| R-06 | firms (product gaps) | VIIRS_SNPP→NOAA20→NOAA21→MODIS chain | same-provider | A | R-00 | DONE | #276 | product chain in fetch_fires primary; non-first product = source_leg, NO grade; all-empty→[] (no HMS); all-fail→HMS |
| R-07 | coral_dhw (NOAA 403s) | CRW ERDDAP `noaacrwdhwDaily` grid | same-provider | A | R-00 | DONE | #283 | Endpoint recovered on fresh probe; ERDDAP point witness samples pinned CRW station coords, adds observed_alt_host grade, and records degraded telemetry `served via crw_erddap`. |
| R-08 | gdacs subtypes (supply) | USGS quakes + NHC cyclone GIS (new sources) | additive | B | R-00 | DONE(usgs-quakes; cyclone-existing-nhc-jtwc) | #281 | Added independent `usgs_quakes` source key for USGS significant earthquakes, with parser, runner, scorer, bundle, manual-only policy, voice fixture, and source-health telemetry. Cyclone subtype already has separate `nhc`/`jtwc` source keys; no duplicate GIS parser shipped. |
| R-09 | sea_ice (NSIDC multi-day) | OSI SAF / MET Norway THREDDS | independent | B | R-00 | DONE | #282 | `netCDF4` OSI SAF 401-b witness parses latest NH/SH concentration grids; evidence_grade observed_alt_host; degraded telemetry `served via osi_saf`. |

Cut in review (plan §L5): ocean_sst witness; global fire-drought-heat / S-27 unblock; GPM-S3-as-public-mirror. Predecessor docs `second-witness-lane.md` + `source-backup-feeds.md` merged here and deleted.

## Awaiting Andrew (decisions parked by design)
- **R-04 ReliefWeb: waiting on appname approval email.** ReliefWeb's API now returns
  `403 AccessDeniedHttpException` for any unregistered appname (verified live with the spec URL + the
  courtesy UA — the `appname=theheat` the plan assumed is no longer accepted). Codex submitted the
  free appname request on 2026-06-15 for `TheHeat-GDACSBackup-RW7K2Q` with `contact@theheat.app`.
  ReliefWeb's form says they review and respond within two business days. Once approved, provide/set
  the approved value as `RELIEFWEB_APPNAME`, then R-04 can be built + verified. The lane's STOP rule
  (don't ship an unverified endpoint) remains honored — no parser was written against an unseen
  response shape.

## Session log
| Date | Session | Steps shipped | Notes |
|---|---|---|---|
| 2026-06-13 | Claude (direct, codex step skipped per Andrew) | R-00 | Provenance foundation: `_witness.py`, `source_leg` on 6 dataclasses, `observed_alt_host`+`model_fallback` prompt grades, survey legs table. Self-review caught a real `dataclasses.replace` type-var error that `mypy src/` missed (file not yet in import graph) — fixed. |
| 2026-06-13 | Claude (direct) | R-01 | Sync-contract pair: `served_via` parser+field byte-equivalent in `source-health.js` + `source_health_sentinel.py`; dashboard row chip + red-error suppression; runbook with unbacked-source table. Backup-served = degraded (never healthy), no issue opened; parity tests both suites. Vercel prod deployed 2026-06-14. |
| 2026-06-13 | Claude (direct) | R-02 | NOAA HMS independent fire witness for firms (live-verified 200). with_witness in fetch_fires; column-name parse of whitespace-padded HMS file; -999/out-of-NA dropped; observed_alt_host grade; runner degraded telemetry. Full-sweep caught 2 issues (mypy splat + a stale test that relied on the hermetic guard) — both fixed. |
| 2026-06-14 | Claude (direct) | R-03 | Open-Meteo precip witness for gpm_imerg (endpoints live-verified 200). Renamed primary to _fetch_daily_precip_primary + with_witness wrap; ≥3-model ensemble-agreement filter; model_fallback grade via source_leg propagation through detect_precip_records; runner telemetry. Full-sweep caught 5 stale strict-failure tests now intercepted by the witness — redirected to _fetch_daily_precip_primary (testing the primary's internals). Removed an iCloud dup test file. |
| 2026-06-14 | Claude (direct) | R-04(BLOCKED) | ReliefWeb live verify returned 403 (requires a pre-approved appname now) — honored the STOP, recorded BLOCKED + AWAITING-ANDREW, no parser shipped against an unverifiable endpoint. |
| 2026-06-14 | Claude (direct) | R-06 | FIRMS same-host product chain (SNPP→NOAA20→NOAA21→MODIS) in fetch_fires primary; non-first product tagged source_leg (degraded) with NO grade; all-empty→[] (no HMS), all-fail→HMS. Redirected the FIRMS freshness test to _fetch_daily_precip_primary-style _fetch_fires_primary (chain overwrites the single-product error). |
| 2026-06-14 | Claude (direct) | R-05 + R-07 deferred (groundwork) | Both witnesses need reference coords behind their failing primary host. Gathered + recorded: USGS authoritative gauge coords (R-05) + verified CRW ERDDAP host/var/format (R-07, host is coastwatch.noaa.gov not pfeg) in docs/superpowers/specs/2026-06-14-r05-r07-groundwork.md. R-05 also has 2 open design problems (discharge↔ft impedance, p75 semantics). Stopped feature work here per context budget; R-08 optional, R-09 dep-gated (Andrew). |
| 2026-06-14 | Codex | SOURCE-REDUNDANCY review fixes | Tightened `with_witness` so auth/schema/parser failures cannot be masked by backups while stale provider data remains backup-eligible; stopped FIRMS product-chain/HMS fallback on invalid MAP_KEY; kept GPM Open-Meteo model-fallback readings out of satellite record state. Also corrected merged PR numbers + stale Vercel-awaiting note above. |
| 2026-06-14 | Codex | R-05 | Open-Meteo Flood / GloFAS model fallback for river_gauges. Kept public shape, added known-coordinate discharge witness, model_fallback bundle facts with no gauge/stage feet, and degraded telemetry (`served via open_meteo_flood`). p75 treated as ensemble gate, not climatological threshold. |
| 2026-06-14 | Codex | R-07(BLOCKED) | NOAA CRW ERDDAP was unreachable from executor-side curls during implementation: base, catalog, info, DAS, and point-style requests all timed out with 0 bytes / `HTTP:000`. Honored the live-verify STOP; no parser shipped against an unavailable endpoint. |
| 2026-06-14 | Codex | R-08 | Added USGS Significant Earthquakes as independent `usgs_quakes` supply for GDACS earthquake blind spots. Existing separate `nhc`/`jtwc` cyclone source keys cover the cyclone subtype; no GDACS health masking or duplicate cyclone parser. |
| 2026-06-14 | Codex | R-09 | Added OSI SAF sea-ice witness through the current MET Norway THREDDS public catalog, with `netCDF4` parsing, observed_alt_host bundle grade, and degraded telemetry when NSIDC is unavailable/stale. |
| 2026-06-15 | Codex | R-07 | Re-probed NOAA CoastWatch ERDDAP after the timeout blocker; endpoint returned 200, so added CRW grid fallback for coral_dhw with pinned station coords, observed_alt_host grade, and degraded telemetry. |
| 2026-06-15 | Codex | R-04(appname-requested) | Submitted ReliefWeb appname request for `TheHeat-GDACSBackup-RW7K2Q` using `contact@theheat.app`; Google Forms confirmation returned, and an immediate API probe still returned 403 pending approval. |
