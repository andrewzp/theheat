# P09 GPM access failure: expiry evidence and deployment limits

Refreshed September 9, 2026 against access code at `739b2f01d5547d5e29f65ce744ab32260dd01449`. No credential value was retrieved; no NASA credentialed request, collector dispatch, login, rotation or configuration change was performed.

## Supported immediate blocker

The saved ingestion [run 34329327005](https://github.com/andrewzp/theheat/actions/runs/34329327005), at `10832af`, tried datapool HTTPS (HTTP 401), temporary S3 credentials (non-JSON response), then OPeNDAP (HTTP 401, stopping after its first authentication failure). The S3 log does not establish status, content type or redirect destination.

Read-only GitHub metadata reports `EARTHDATA_TOKEN` last updated **2026-06-23T15:21:02Z**. The frozen September 8 state and saved release state both report expiry **2026-08-22T15:18:07Z**, derived from JWT metadata without signature verification. The June 23 handoff records the same rotation/expiry. NASA documents a [60-day user-token lifetime](https://urs.earthdata.nasa.gov/documentation/for_users/user_token).

Together, these are strong evidence that expired credentials are the first recovery blocker. They are not proof of the current secret value in every environment, token authenticity, or absence of another access problem. The repository source selector remains `datapool`; [source issue 491](https://github.com/andrewzp/theheat/issues/491) remains open. Newer successful runs `34346691890` and `34362277644` executed `auto_publish_due` without collecting GPM, so they do not establish recovery.

## Separate latent fallback problem

NASA documents [direct S3 access within the same AWS region](https://data.gesdisc.earthdata.nasa.gov/s3credentialsREADME), [us-west-2 for this service](https://ntrs.nasa.gov/api/citations/20240001387/downloads/PMM%20precip%20data%20services_12042023.pdf). The workflow uses standard `ubuntu-latest`; [GitHub hosts those Linux runners in Azure](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners). Setting the boto3 endpoint region does not relocate execution. Direct S3 is therefore not a documented compatible automatic fallback for this runner. This is a latent contract mismatch, **not an explanation of the observed HTTP 401s**; the saved S3 attempt failed before object access.

## Smallest next actions

1. An authorized account owner should replace the expired user token through the intended Earthdata/GitHub secret surfaces and confirm [GES DISC application authorization](https://urs.earthdata.nasa.gov/documentation/for_users/what_is_app_auth). If account access is unavailable, that is the concrete external blocker. Retries, older dates and model spending cannot renew the credential.
2. Prepare a local defensive patch: fail fast on known expiry; remove unconditional S3 credential preminting; keep direct S3 outside automatic fallback on this runner; classify ambiguous S3 403/AccessDenied as access failure rather than missing dates. Preserve sanitized status, hostname, content type and bounded length/hash diagnostics, without bodies, credentials, cookies, headers or signed URLs. These mitigations do not restore access by themselves.
3. After explicit authorization, make one bounded check using the configured credential through its intended workflow environment, with publishing and model stages disabled. Use a canonical published granule/subset, reject login HTML, and verify the expected format. A 401 stops the check; a 404 alone is a path/availability question. A valid product read and one daily-grid parse are required before claiming ingestion recovery.

The actual-tweet Barrow satellite/gauge discrepancy remains separate and unresolved. Access recovery cannot establish the original granules, integration window, spatial support or cause of that difference. A modeled fallback must retain its evidence type and does not demonstrate recovered satellite observations. No public correction follows from this diagnosis.

Private supporting logs and the detailed report remain in the ignored `.gstack/diagnostics/2026-09-09-gpm-access/` directory with directory mode 700 and file mode 600. Original assessments and corpus were preserved.
