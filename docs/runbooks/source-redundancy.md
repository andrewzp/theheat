# Runbook: source redundancy & backup-served sources

How to read and act on the redundancy signals the SOURCE-REDUNDANCY LANE adds
(`docs/superpowers/plans/2026-06-13-source-redundancy-lane.md`). See also
`docs/superpowers/specs/2026-06-12-mirror-survey.md` for the verified-leg table.

## What "served via X" means

A *witness* (`src/data/_witness.py`) is a fallback feed that fires ONLY when a
primary source fetch fails. When a witness serves, the run records
`status="degraded"` with the diagnostic `served via <leg>`. Both the dashboard
(`dashboard/lib/source-health.js`) and the sentinel
(`scripts/source_health_sentinel.py`) parse that into a `served_via` field —
kept byte-equivalent across the two (the standing sync contract).

- **Dashboard:** the source row shows `firms — degraded · served via noaa_hms`.
  A backup-served source is **degraded (yellow), never healthy (green)** — even
  though drafts still flow, the operator needs to know the primary is down.
- **Sentinel CLI:** prints `BACKUP <source> primary down — served via <leg>`.
  A backup-served source is `degraded`, so it does **not** open a GitHub issue
  (only hard-failing sources do). The visibility is the dashboard row + the CLI
  line. If a primary stays backup-served for a long window, that is the operator's
  cue to investigate the primary directly.
- **Drafts are honest:** the bundle builder appends an `evidence_grade`
  (`observed_alt_host` / `model_fallback`) per the §L0 ladder, and the manual
  approval queue still gates every draft.

## Live redundancy legs

| Source | Leg | What it covers | Evidence / operator meaning |
|---|---|---|---|
| `firms` | NOAA HMS (`noaa_hms`) | A FIRMS host outage for North American fire points. | `observed_alt_host`; drafts may mention alternate source. |
| `firms` | FIRMS product chain (`VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT`) | Product lag/empty-product gaps while the FIRMS host/key still work. | Same-provider provenance only; no `evidence_grade`. |
| `gpm_imerg` | Open-Meteo precipitation (`open_meteo`) | GES DISC / IMERG outage for monitored city precipitation. | `model_fallback`; copy must say model estimate, not observed/measured. |
| `river_gauges` | Open-Meteo Flood (`open_meteo_flood`) | USGS/NWPS outage for known major-river stations with pinned coords. | `model_fallback`; no gauge-height or flood-stage feet facts. |
| `coral_dhw` | CRW ERDDAP grid (`crw_erddap`) | NOAA CRW virtual-station text failure. | `observed_alt_host`; same provider, different product/path. |
| `sea_ice` | OSI SAF / MET Norway THREDDS (`osi_saf`) | NSIDC/NOAA sea-ice CSV outage or stale data. | `observed_alt_host`; independent NetCDF concentration grid. |
| `gdacs` | Subtype witnesses (`subtype_witnesses`) | GDACS outage for significant earthquakes and active cyclone subtypes. | Degraded observations only; dedicated `usgs_quakes`, `nhc`, and `jtwc` runners own drafting to avoid duplicates. |
| `copernicus_ems` | Copernicus frontend activations API (`frontend_api`) | Dashboard API 403/transport failures for public flood activations. | Conservative activation fallback; impact fields are only used when present. |
| `jtwc` | Plain official RSS (`plain_rss`) | Enhanced RSS 403/transport failures. | Official lower-feature feed; degraded source row remains visible. |
| `ocean_sst_anomaly` | NOAA STAR/CRW SST anomaly NetCDF (`noaa_star_nc`) | CoastWatch ERDDAP timeout or 503 for regional SST anomaly regions. | Downloads latest grid once, fills failed regions, and records degraded telemetry. |

## Still unbacked or operator-gated

These sources or subpaths have no verified autonomous substitute yet. They get
source-health visibility and, where available, last-good softening, but no
automatic replacement story should be inferred.

| Source / gap | Why still uncovered | Operator action on outage |
|---|---|---|
| `gdacs` full ReliefWeb mirror | ReliefWeb now rejects unapproved appnames with 403. Request for `TheHeat-GDACSBackup-RW7K2Q` is submitted, but the parser must wait for an approved live response. | Wait for approval, set/provide the approved `RELIEFWEB_APPNAME`, then build/verify R-04. |
| `nsidc_snow` | No verified official mirror for the station SWE point payload. | Keep retry/revalidation on the existing endpoint; wait for recovery. |
| `ice_mass` | CMR resolves current PO.DAAC granules, but no second drop-in data mirror is verified. | Treat failures as source outages; do not synthesize replacement ice-mass facts. |

## When a backup leg is itself failing

`with_witness` chains both errors: if a primary AND its witness both fail, the run
records a hard failure with `<source> primary failed: …; <leg> witness failed: …`,
which the sentinel classifies and files normally. That is a genuine outage of both
legs — investigate per the usual source-down runbook.
