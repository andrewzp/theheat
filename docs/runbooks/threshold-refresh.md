# Station threshold refresh and protected adoption

The Sunday refresh prepares and publishes an immutable database candidate.
A successful maintenance run does **not** install that candidate. The installed
baseline is the manifest on protected `main`; readers verify its exact database.
Adoption requires an operator and a normal tested pull request.

## Runtime limits and resumption

Scheduled refreshes and ordinary manual invocations retain a 15-minute updater
limit and a 30-minute job limit. For an explicitly selected manual catch-up,
`workflow_dispatch` input `catch_up=true` selects 30 and 45 minutes respectively.
Both modes retain four acquisition workers and the same lineage and checkpoint
validation. The longer budget does not widen the supported baseline age.

An updater timeout remains a failure. If checkpoint mode is enabled, the workflow
seals completed progress in `threshold-refresh-checkpoint` for two days. Inspect
the original run and the current owner before selecting its `resume_run_id`;
do not dispatch a duplicate. Resume must use the same baseline and source scope.
Changing the time budget does not change that scope. Cancellation or runner loss
can still prevent sealing. A checkpoint is never an installable baseline.

## Find a pending candidate

The operator checks the latest `refresh-thresholds.yml` run in Actions after each
maintenance run. The last step writes **Threshold adoption pending** as a warning
annotation and puts the artifact digest and this runbook in the run summary.
The `verified-threshold-handoff` artifact expires after seven days. Its receipt
records `pending_protected_pull_request`; that is its state when created, not a
live status query. Compare its exact manifest with protected `main` to determine
whether it was subsequently adopted. Workflow-health green only describes the
maintenance run; it does not establish baseline adoption or reader consumption.
There is no automatic adoption PR or new notification service in this workflow.

## Verify and adopt through existing approved access

1. With the existing authenticated operator GitHub CLI, inspect the exact run's
   repository, workflow, main ref, first attempt, checked-out SHA and successful
   publication and handoff steps. Confirm the named artifact belongs to that
   run, is unexpired and has the platform-recorded digest. Verify the downloaded
   ZIP digest before extraction; allow exactly three regular files:
   `station_thresholds.version`, `stations.csv` and `handoff.json`.
2. Use a clean isolated checkout of current `main`. Preserve existing local data.
   Confirm inventory has not changed between the hosted base and current main.
   Verify the packet with the trusted repository, run ID and hosted base SHA:

   ```sh
   python -m scripts.threshold_handoff verify --directory PACKET \
     --repo OWNER/REPO --run-id RUN_ID --base-sha HOSTED_SHA
   ```

   The verifier binds exact file hashes and the installed/committed baseline to
   the receipt. The receipt alone proves neither origin nor database validity.
3. Run `scripts.threshold_artifacts ensure` with `--manifest` pointing to the
   packet manifest and `--db` pointing to an isolated database. Verify the
   immutable asset, schema, watermark and counts, then compare the inventory to
   that verified database. Refuse conflicting base changes. If both candidate
   files already equal main, report already adopted and verify reader evidence.
4. Commit only the two verified data files on a branch and create the adoption PR
   with the existing authenticated operator CLI. Verify ordinary pull-request CI
   actually runs on the reviewed head: all required partitions and aggregate
   `test` must pass, while publishing and paid replay remain skipped. Merge through
   normal protection. Do not infer checks from PR creation or bypass protection.
5. Verify the exact adopted file hashes on main and the first ordinary collector's
   checksum-bound read. Record merged adoption separately from hosted consumption.

The maintenance workflow uses `GITHUB_TOKEN` only for its existing operations.
Creating an adoption PR with that token is not a substitute for this operator
step: GitHub documents downstream event restrictions and approval-required runs
for supported token-originated PR events. See
[GitHub's token event rules](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs).
Absent, pending, approval-required or different-head checks do not satisfy `test`.
Do not dispatch the production bot to manufacture CI. Fully unattended adoption
would need a separately reviewed trigger/access design; no new credentials or
permissions are required by the operator path above.
