# Pause production collection and drafting

Set the GitHub Actions repository variable `THEHEAT_PRODUCTION_PAUSED` to `1`.
On the current workflow revision this skips the `bot.yml` production
`run` job for schedules and collection dispatches before it starts. The existing
reviewed `manual_tweet` publication route retains its separate safeguards, so a
dashboard approval is not silently accepted into a skipped run. Leave `bot.yml`
enabled: its required PR tests are independent of this variable.

Disable the separate `refresh-thresholds.yml` workflow to stop weekly source
acquisition. Keep `THEHEAT_SELFHEAL_REPAIR_ENABLED=0` so intentional pauses cannot
be repaired automatically. The source/workflow observers may report stale data
or a disabled workflow during a deliberate pause.

Set `THEHEAT_PRODUCTION_PAUSED=1` in the dashboard's Production environment and
deploy the dashboard. This makes authenticated generation and collection-trigger
requests return HTTP 503 before provider calls or workflow dispatch. Existing
drafts, evidence, publication receipts, and source artifacts are unchanged.

Inspect active and queued runs when pausing. These controls do not interrupt a
run already in progress; inspect its current step before cancelling, because
production Gist writes are not transactional. Do not dispatch a publishing job
just to test the pause. Read the remote controls and scheduled job outcomes.

## Resume

1. Set the repository variable `THEHEAT_PRODUCTION_PAUSED` to `0`.
2. Set the dashboard Production variable to `0` and redeploy.
3. Re-enable `refresh-thresholds.yml` if it was enabled before the pause.
4. Restore the previously recorded self-heal setting only if intended.

Automatic publication has separate controls. Resuming collection does not
authorize enabling publication or autoship; preserve those pause settings.

## Scope

Offline tests and explicit development evaluations remain available. This is an
operational pause of current production entry points, not revocation of API
credentials. A deliberate CLI invocation, an old workflow ref without the guard,
or an older dashboard deployment can bypass the new controls. Do not use those
routes while production is paused. No external scheduler is changed by this
runbook; inspect any separately configured scheduler before claiming coverage.
