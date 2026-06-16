# Codex orientation - SOURCE-REDUNDANCY lane (current 2026-06-16)

Read this before touching source-redundancy work. It summarizes the current
state; the source of truth remains
`docs/superpowers/plans/2026-06-13-source-redundancy-PROGRESS.md`.

## Current state

- Repo: `/Users/andrewpuschel/Documents/Claude/theheat`
- `main`: 0.9.81.0 at this docs sweep.
- Lane status: mostly shipped. R-00, R-01, R-02, R-03, R-05, R-06, R-07,
  R-08, and R-09 are done. R-04 ReliefWeb is the only planned lane leg still
  blocked.
- Open blocker: ReliefWeb requires an approved appname. Request submitted for
  `TheHeat-GDACSBackup-RW7K2Q`; do not write a parser until the approved
  appname returns a live response shape.

## Rails that still matter

- No push to `main`. Use branch -> PR -> required `test` check -> squash merge.
- TDD for code changes. Write failing tests first.
- Live verify any new endpoint before writing a parser against it.
- Keep `scripts/source_health_sentinel.py` and
  `dashboard/lib/source-health.js` classifier behavior in sync in one PR.
- Do not set repo variables/secrets, flip reganom, disable workflows, or edit
  the production gist.
- Dashboard-touching PRs require `cd dashboard && vercel --prod` after merge,
  then verify `https://dashboard-phi-beryl-65.vercel.app` returns `401`.

## Witness pattern

A witness is a fallback feed that fires only when the primary fetch fails.

- Use `with_witness(primary, witness, *, source_key, leg_label)` from
  `src/data/_witness.py`.
- The public return shape stays the same.
- Witness results carry `source_leg`.
- Runners record backup-served runs as `status="degraded"` with
  `note="served via <leg>"`.
- `SourceSkipped`, auth/config failures, and parser/schema failures must not be
  hidden by a witness.

## Evidence grades

- `observed_alt_host`: alternate host/instrument supplied an observation. The
  copy may say observed, but must be honest about the alternate source.
- `model_fallback`: a numerical model stood in for a measurement. Copy must not
  say observed, measured, or recorded.
- Same-provider/product-chain legs may carry `source_leg` for telemetry without
  adding an evidence grade when the data is semantically equivalent.

## Shipped legs

| Source | Leg | Status |
|---|---|---|
| `firms` | NOAA HMS (`noaa_hms`) | independent observed fallback, North America |
| `firms` | FIRMS product chain | same-host product-gap insurance |
| `gpm_imerg` | Open-Meteo precipitation (`open_meteo`) | model fallback |
| `river_gauges` | Open-Meteo Flood (`open_meteo_flood`) | model fallback, known coords only |
| `coral_dhw` | CRW ERDDAP (`crw_erddap`) | same-provider alternate product |
| `sea_ice` | OSI SAF / MET Norway THREDDS (`osi_saf`) | independent NetCDF grid |
| `gdacs` | subtype witnesses (`subtype_witnesses`) | degraded observations from USGS/NHC/JTWC subtypes |
| `usgs_quakes` | new source key | additive independent earthquake source |
| `copernicus_ems` | frontend activations API (`frontend_api`) | conservative fallback |
| `jtwc` | plain official RSS (`plain_rss`) | simpler official endpoint |
| `ocean_sst_anomaly` | NOAA STAR SSTA NetCDF (`noaa_star_nc`) | fills failed ERDDAP regions |

## Remaining work

Only R-04 remains in the planned lane:

1. Wait for ReliefWeb appname approval.
2. Live-probe the approved endpoint and save the response shape in the PR body.
3. Build the parser with tests.
4. Keep GDACS health honest. ReliefWeb may be a lagging backup, not a reason to
   claim GDACS primary is healthy.

Separate future work, not part of the lane:

- `nsidc_snow` has no verified mirror.
- `ice_mass` has CMR/PO.DAAC resolution but no second drop-in data mirror.
- Better dashboard/runbook UX for long-lived backup-served primaries.

## Useful commands

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
source .venv/bin/activate
python -m pytest -m "not voice_replay" -q
python -m mypy src/
ruff check .
(cd dashboard && PATH=/opt/homebrew/bin:$PATH npm test && PATH=/opt/homebrew/bin:$PATH npm run build)
gh issue list --state open --label source-health-sentinel --json number,title,labels
```

Never run `pytest tests/voice_regression/ -m voice_replay` locally.
