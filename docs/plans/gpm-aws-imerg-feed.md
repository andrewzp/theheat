# Plan — gpm_imerg alternate feed (escape the GES DISC OPeNDAP bottleneck)

Status: **DRAFT for review** · Author: Claude (2026-06-06) · Target version: 0.9.15.0

## Correction up front (read this first)

When I recommended "AWS Open Data," I claimed it was **public, credential-free, and
locally testable**. That was wrong. The dataset's S3 home is
`arn:aws:s3:::gesdisc-cumulus-prod-protected/GPM_L3/GPM_3IMERGDL.07/` in **us-west-2**,
and it is **Controlled Access** — you must mint temporary AWS credentials from your
Earthdata login to read it. So:

- It is **not** anonymous/public.
- It is **not** locally testable without Earthdata creds (same limitation as today's
  OPeNDAP path — none of the gpm paths are locally testable without the token).
- It still depends on Earthdata auth (we have `EARTHDATA_TOKEN`).

The plan below reflects the real options. The recommendation changed accordingly.

## Problem & root cause

gpm_imerg fetches daily precip by issuing **75 per-city OPeNDAP `.ascii` subset
requests** to `gpm1.gesdisc.eosdis.nasa.gov`. Each request makes GES DISC compute a
1-cell subset on the fly. Under load this fails with `503` and, increasingly,
`ConnectTimeout`. The `ConnectTimeout` is the key signal: the connection itself isn't
being accepted in time — that's **host-level overload**, not just the OPeNDAP service.

Implication: a fix that stays on `gpm1.gesdisc` (same host) may not fully escape the
problem. A *robust* fix needs a **different host** and **one request per run** instead
of 75.

Current cost: a failing run burns up to ~28 min (capped in 0.9.11.1) and gpm has
produced **0 promoted / 0 drafted in 7 days** — zero product value so far. This is
reliability-on-principle work, not value-recovery. Worth keeping proportionate.

## Goal

Swap only the **fetch layer**: download the full daily IMERG Late grid **once**, parse
it, and subset all monitored cities **locally**. Everything downstream
(`CityPrecipReading`, `detect_precip_records`, rolling-accumulation + country logic,
scoring) stays **unchanged**. The grid math already exists and is reused verbatim:
`GRID_STEP_DEGREES=0.1`, `LON_CELLS=3600`, `LAT_CELLS=1800`, `FILL_VALUE=-9999.0`,
`_lon_index()`, `_lat_index()`, and the `precipitation[time, lon, lat]` ordering
(confirmed from the current `.ascii` subset `precipitation[0][lon_index][lat_index]`).

## Options (accurate trade-offs)

| Option | Host | Auth | Escapes gpm1 overload? | New deps | Notes |
|---|---|---|---|---|---|
| **A. GES DISC data pool** (`/data/.../*.nc4` HTTPS) | gpm1.gesdisc (same) | `EARTHDATA_TOKEN` (have it) | **Partial** — static file, no subset compute, but same host | h5py/netCDF4 | Simplest. May still `ConnectTimeout` if the host (not just OPeNDAP) is the bottleneck. |
| **B. AWS S3 (cumulus)** | S3 us-west-2 (different) | Earthdata → S3 temp creds | **Yes** — fully off gpm1 | boto3 + h5py/netCDF4 | Robust. Needs the s3credentials mint flow + boto3. Not locally testable. |
| **C. PPS servers** | jsimpson/arthurhou (different) | **separate PPS account** | Yes | h5py/netCDF4 | New credential to provision; daily Late may not be on the NRT server. Worst auth story. |

## Recommendation: **B (AWS S3)**, structured so we can fall back to A and OPeNDAP

Because the failures are host-level (`ConnectTimeout`), only a different host (B or C)
is a *real* fix. B reuses the Earthdata token we already have (via temp-cred minting),
so it avoids provisioning a new PPS account (C). Build it behind a source flag with
graceful fallback so we never make gpm *worse* than today:

```
THEHEAT_GPM_SOURCE = s3 (new default) | datapool | opendap (current/fallback)
```

On S3 failure → fall back to the data-pool download (A); on that failure → fall back to
the existing OPeNDAP path. Same-day, one source flag, fully reversible.

## Architecture (Option B)

1. **Mint S3 credentials** — `GET https://data.gesdisc.earthdata.nasa.gov/s3credentials`
   with the Earthdata bearer token → temporary AWS access key / secret / session token
   (valid ~1h). Cache in-process (~55 min TTL). New helper `src/data/_s3credentials.py`.
   *Verify the exact endpoint + that a Bearer `EARTHDATA_TOKEN` is accepted (vs Earthdata
   username/password) — open question O1.*
2. **Resolve the daily file key** — walk back from yesterday (the Late product lags
   1–2 days) probing S3 object existence (`head_object`) under
   `gesdisc-cumulus-prod-protected/GPM_L3/GPM_3IMERGDL.07/YYYY/MM/`. Reuse the existing
   walk-back contract from `_resolve_available_date` (404/missing → step back; transient
   → stop). *Verify the exact key/filename pattern + format (.nc4 vs .HDF5) — O2.*
3. **Download once** — `boto3` S3 `get_object` (temp creds, us-west-2) → bytes in memory
   (daily file is single-digit MB). One request per run, not 75.
4. **Parse + subset locally** — open the bytes with `h5py` (if `.HDF5`) or `netCDF4`
   (if `.nc4`); read the `precipitation` dataset `[1, 3600, 1800]`; for each city extract
   `precip[0, _lon_index(lon), _lat_index(lat)]`; apply `FILL_VALUE` masking; build
   `CityPrecipReading`. *Pick h5py vs netCDF4 after confirming format (O2). h5py is the
   lighter dep if files are raw HDF5.*
5. **Downstream unchanged** — hand `CityPrecipReading[]` to the existing detection +
   scoring, exactly as today.

## Files

- `requirements.txt` — add `boto3` and `h5py` (or `netCDF4`).
- `src/data/_s3credentials.py` (new) — mint + cache temp S3 creds from Earthdata.
- `src/data/gpm_imerg.py` — new `_fetch_grid_s3()` + `_subset_grid()` + a
  `THEHEAT_GPM_SOURCE`-driven dispatch in `fetch_daily_precip`; keep dataclasses,
  `detect_precip_records`, rolling/country logic, `_lon_index/_lat_index` **as-is**.
- `tests/test_gpm_imerg.py` — fixture-grid tests (below).
- `.github/workflows/bot.yml` — set `THEHEAT_GPM_SOURCE: ${{ vars.THEHEAT_GPM_SOURCE || 's3' }}`
  (no new secret — reuses `EARTHDATA_TOKEN`). Confirm boto3 region pinned to us-west-2.

## Testing strategy

- **Unit (local, no creds):** build a tiny in-memory HDF5/netCDF grid fixture with known
  values at specific cells; assert `_subset_grid` returns the right precip for cities at
  those lat/lons (reusing `_lon_index/_lat_index`), and that `FILL_VALUE` → None. Mock the
  S3 download + credential mint. This covers the parse/subset logic deterministically.
- **Cross-check (CI, one-off):** for a recent published date, assert an S3-derived city
  value equals the OPeNDAP-derived value for the same city/date (proves grid orientation
  + indexing match). Guard behind a network/creds marker.
- **Fallback test:** S3 raises → datapool attempted → opendap attempted; assert the chain.
- **CI:** the scheduled bot run exercises the real S3 path with `EARTHDATA_TOKEN`.
- Honest limitation: like today's OPeNDAP path, the live fetch is **not locally testable**
  without `EARTHDATA_TOKEN`; real verification is the first CI/cron run.

## Open questions to resolve EARLY in the build (before writing the fetch)

- **O1.** Exact s3credentials endpoint for GES DISC + whether it accepts our Bearer
  `EARTHDATA_TOKEN` (some DAACs require Earthdata user/pass or a netrc flow).
- **O2.** Exact S3 key/filename pattern under the cumulus prefix + file format
  (`.nc4` vs `.HDF5`) → decides h5py vs netCDF4.
- **O3.** AWS mirror freshness: is the Late daily on S3 within its normal 1–2 day lag?
  (If S3 lags more than OPeNDAP, the walk-back must tolerate it.)
- **O4.** boto3 + h5py/netCDF4 install cleanly on `ubuntu-latest` (wheels, no apt libs).
- **O5.** Egress: GitHub runners aren't us-west-2 → cross-region egress on each run.
  Files are small (single-digit MB) so cost/latency is negligible, but confirm.

## Rollout & verification gates

1. Land deps + the s3credentials helper + the new fetch behind `THEHEAT_GPM_SOURCE`
   defaulting to **opendap** (no behavior change yet). CI green.
2. Resolve O1/O2 with a throwaway CI job (mint creds, list one key, print format).
3. Flip the repo var `THEHEAT_GPM_SOURCE=s3`; watch the next cron: gpm source-health
   should climb and the latency should drop (one download vs 75 subsets). The sentinel
   tracks it; the dashboard already shows it honestly.
4. If S3 underperforms, flip the var back — zero code push.

## ROI caveat (revisit before step 1)

gpm is **0 promoted / 0 drafted**. This plan adds `boto3` + an HDF5 parser for a source
with no demonstrated product value. The sentinel + dashboard now track it honestly with
no noise. Reasonable to build for reliability-on-principle; equally reasonable to park
this until a precip record clears the editorial bar. Decision belongs to the operator.
