# SOURCE-REDUNDANCY LANE — Progress tracker

> State lives HERE and only here. Each step's PR updates its own row in the same PR.
> Statuses: `TODO` · `IN-PROGRESS` · `DONE` · `DONE(<qualifier>)` · `BLOCKED(<reason>)` · `AWAITING-ANDREW(<what>)`.
> Pick: first TODO whose deps are all DONE. Rails inherited from THIRTY-LOOP §0–§5/§8. Grading ladder: plan §L0.

| Step | Target | Leg added | Kind | Tier | Deps | Status | PR | Note |
|---|---|---|---|---|---|---|---|---|
| R-00 | foundation | source-leg provenance + 2 grades + `with_witness` | infra | A | — | DONE | #PENDING | `_witness.py` + `source_leg` on 6 dataclasses + 2 prompt grades + survey table; 11 witness tests |
| R-01 | dashboard+sentinel | chain-leg visibility (Py+JS in sync) | infra | A | R-00 | DONE | #PENDING | `served_via` field (Py+JS byte-equiv), dashboard row chip, runbook; backup-served=degraded not healthy |
| R-02 | firms (NASA 5/40) | NOAA HMS (NESDIS+GOES, N. America) | independent | A | R-00 | TODO | | stops host-outage no-draft |
| R-03 | gpm_imerg (NASA 18/40) | Open-Meteo precip + ensemble filter | independent(model) | A | R-00 | TODO | | highest value |
| R-04 | gdacs (EU 9/40) | ReliefWeb (UN OCHA) | independent | A | R-00 | TODO | | |
| R-05 | river_gauges (403s) | Open-Meteo Flood (GloFAS, model-framed) | independent(model) | A | R-00 | TODO | | copernicus_ems OUT |
| R-06 | firms (product gaps) | VIIRS_SNPP→NOAA20→NOAA21→MODIS chain | same-provider | A | R-00 | TODO | | same host; not a host-outage fix |
| R-07 | coral_dhw (NOAA 403s) | CRW ERDDAP `noaacrwdhwDaily` grid | same-provider | A | R-00 | TODO | | verify dataset id live |
| R-08 | gdacs subtypes (supply) | USGS quakes + NHC cyclone GIS (new sources) | additive | B | R-00 | TODO | | optional / supply expansion |
| R-09 | sea_ice (NSIDC multi-day) | OSI SAF / U. Bremen | independent | B | R-00 | TODO | | dep-gated (netCDF4/pyhdf) |

Cut in review (plan §L5): ocean_sst witness; global fire-drought-heat / S-27 unblock; GPM-S3-as-public-mirror. Predecessor docs `second-witness-lane.md` + `source-backup-feeds.md` merged here and deleted.

## Awaiting Andrew (decisions parked by design)
- R-09 sea-ice: needs a parser dependency (`netCDF4` or `pyhdf`) — implement behind it, flip on approval.

## Session log
| Date | Session | Steps shipped | Notes |
|---|---|---|---|
| 2026-06-13 | Claude (direct, codex step skipped per Andrew) | R-00 | Provenance foundation: `_witness.py`, `source_leg` on 6 dataclasses, `observed_alt_host`+`model_fallback` prompt grades, survey legs table. Self-review caught a real `dataclasses.replace` type-var error that `mypy src/` missed (file not yet in import graph) — fixed. |
| 2026-06-13 | Claude (direct) | R-01 | Sync-contract pair: `served_via` parser+field byte-equivalent in `source-health.js` + `source_health_sentinel.py`; dashboard row chip + red-error suppression; runbook with unbacked-source table. Backup-served = degraded (never healthy), no issue opened; parity tests both suites. |
