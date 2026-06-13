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

## Unbacked sources — visibility only, no autonomous backup draft

These sources have NO verified independent leg yet (see the mirror-survey
verdicts). They get last-good softening (S-15) and dashboard/sentinel visibility,
but they do **not** autonomously draft from a backup during an outage. If one is
chronically down, that is a manual investigation, not an automatic substitution.

| Source | Why unbacked | Operator action on outage |
|---|---|---|
| `jtwc` | JTWC public page 403s; NHC advisories are not a full west-Pacific/Indian-Ocean mirror. | Confirm the outage; west-Pacific/Indian-Ocean cyclones may simply be uncovered until JTWC returns. No substitute. |
| `nsidc_snow` | No verified official mirror for the station SWE point payload. | Keep retry/revalidation on the existing endpoint; wait for recovery. |
| `sea_ice` | Second source (OSI SAF / U. Bremen) is dep-gated on `netCDF4`/`pyhdf` (R-09, `AWAITING-ANDREW`). | Slow signal; last-good softens short gaps. Approve the parser dep to enable the OSI SAF witness. |
| `copernicus_ems` | Public activation pages can confirm an activation exists but can't rebuild structured impact stats. | Confirm activation manually if needed; not a structured-data substitute. |

## When a backup leg is itself failing

`with_witness` chains both errors: if a primary AND its witness both fail, the run
records a hard failure with `<source> primary failed: …; <leg> witness failed: …`,
which the sentinel classifies and files normally. That is a genuine outage of both
legs — investigate per the usual source-down runbook.
