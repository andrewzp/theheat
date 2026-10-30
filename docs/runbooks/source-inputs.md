# Runbook: qualified source inputs (normals, GHCN thresholds, Earthdata, HMS)

These are owner-run, networked operations. Each one is bounded, resumable and
leaves the previously installed input in place until a replacement qualifies.
None of them changes production state, posts, or flips a flag. Run them from a
clean checkout of the released code in an isolated working directory `W`.

## Climate normals (Hot 10 `missing_normal`)

The acquisition uses the owned, physically bounded transport in
`src/data/bounded_http.py` for the agreed `meteostat-normals-point-v1` product:
one absolute deadline across DNS, connect, TLS, headers, body, backoff and
redirects; a cap on physical requests including retries and every redirect
hop; received and decoded byte caps; and cancellation on SIGTERM. Insufficient
or invalid input still refuses.

```sh
python scripts/build_normals.py plan --output W/normals-plan.json
python scripts/build_normals.py acquire --plan W/normals-plan.json --out-dir W/normals-candidate \
  --installed data/normals.csv --max-requests 15195 --max-bytes 37519360 \
  --max-decoded-bytes 150077440 --deadline-seconds 3600 --max-retries 2
python scripts/build_normals.py admit --candidate W/normals-candidate/candidate
python scripts/build_normals.py install-plan --candidate W/normals-candidate/candidate
```

`acquire` is resumable; rerun it until it reports ready. A `provider_endpoint_missing`
result means the pinned 1.x bulk endpoint no longer serves the product; moving to
another provider version is a deliberate product migration, not a retry.
`install-plan` prints the copy steps; the installed file changes only when you
apply them. Acceptance: `python scripts/theheat_onboard.py preflight` no longer
reports `hot10: holds: qualified normals not installed`.

## GHCN-Daily station thresholds (`threshold_baseline_unavailable`)

A threshold is an alert comparator, never a certified historical record.

```sh
python scripts/build_station_thresholds.py resolve-inputs --output W/fetch-plan.json
python scripts/build_station_thresholds.py fetch-inputs --fetch-plan W/fetch-plan.json \
  --dest W/inputs --deadline-seconds 7200 --max-retries 3
python scripts/build_station_thresholds.py package --inputs W/inputs --work-dir W/work \
  --out-dir W/out --partitions 16 --deadline-seconds 21600
gh release upload thresholds-latest W/out/station_thresholds-<sha>.sqlite.gz --repo andrewzp/theheat
gh api repos/andrewzp/theheat/releases/tags/thresholds-latest > W/release.json
python scripts/build_station_thresholds.py install-manifest --manifest W/out/station_thresholds.version \
  --build-manifest W/out/build-manifest.json --release-assets W/release.json
```

`resolve-inputs` pins exact sizes and the NCEI dataset version from two bounded
reads. `fetch-inputs` (about 3.8 GB, resumable with `If-Range`) rejects an archive
whose size differs from the plan and re-reads the version before and after.
`install-manifest` replaces the manifest only when the saved release metadata
shows the uploaded asset with its digest, keeping the previous manifest beside
it. Commit the new `data/station_thresholds.version`. Install within about eight
days of the fetch or the weekly refresh reports that a full rebuild is needed.
Acceptance: the next bot run reports `THEHEAT_GHCN_THRESHOLD_VERIFICATION=success`
and the GHCN leg no longer reports `threshold_baseline_unavailable`.

Regional pilot coverage on the same inputs:
`python scripts/regional_coverage.py ghcn-pilots --inputs W/inputs --output W/ghcn-pilots.json`
(station counts, never recall).

## Earthdata / GPM IMERG

GPM stays unavailable until the owner renews `EARTHDATA_TOKEN`; a stored key is
not recovery. Sources shows the credential state, any refusal backoff and the
age of the last good GPM data. `THEHEAT_EARTHDATA_REFUSAL_BACKOFF=1` (default
off) spaces repeated refusals of the same credential at 6 h, 24 h, then 72 h.
Acceptance: an alerts run whose `gpm_imerg` incident reports
`product_state == primary_qualified`.

## FIRMS and HMS

The FIRMS area endpoint is unchanged. HMS publishes each UTC day's file later in
that day, so an early-day request for the current file is `granule_missing`, not
an outage. `THEHEAT_HMS_PREVIOUS_DAY_FILE=1` (default off) reads the previous
day's published file once in that case. Acceptance: an early-UTC run records the
current granule as missing and the previous one as qualified.

## Turning on a reviewed control

Set the repository variable to exactly `1` (`gh variable set NAME --body 1`); the
bot workflow mirrors every new control at `'0'` otherwise. Roll back with
`--body 0`. Each control is independent; none is required for existing text
stories to operate.
