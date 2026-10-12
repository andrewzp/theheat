# Pause production collection and drafting

Set the GitHub Actions repository variable `THEHEAT_PRODUCTION_PAUSED` to `1`.
On the current workflow revision this skips the `bot.yml` production
`run` job for schedules and collection dispatches before it starts. The existing
reviewed `manual_tweet` publication route retains its separate safeguards, so a
dashboard approval is not silently accepted into a skipped run. Leave `bot.yml`
enabled: its required PR tests are independent of this variable.

The same repository variable skips both paid `voice-regression.yml` jobs before
checkout, credentials or requests: weekly/manual/opted-in PR replay and the daily
canary. Its keyless PR changes job and required offline CI remain available.
Existing schedules and paid PR opt-in rules are unchanged; do not dispatch an
evaluation to verify the pause. Observe an existing scheduled job's outcome.

The same variable also skips the entire `refresh-thresholds.yml` job before
weekly or manually requested source acquisition, baseline mutation, artifact
publication or commits. Preserve its existing enabled/disabled state; the guard
also applies if that workflow is enabled later. Keep
`THEHEAT_SELFHEAL_REPAIR_ENABLED=0` so intentional pauses cannot be repaired
automatically. The source/workflow observers receive the same pause variable:
source liveness reports configured pause, and successful or unknown bot,
voice-regression and refresh-thresholds workflow results cannot resolve an
existing incident while paused. Existing run evidence and genuine source or
workflow failures remain visible; pause alone never closes their issues.
The dashboard still shows retained source/workflow history, including an
independently disabled threshold workflow. Configured pause does not prove running
workers have stopped, source freshness, recovery or zero spending.

The Automation area reads the single repository pause variable during its shared
15-second status refresh. A configured collector pause is shown separately from
this dashboard deployment's generation pause, including differing settings. The
last recorded workflow conclusion and time remain visible; genuine workflow or
access failures retain their alert. An inaccessible, malformed or timed-out flag
read is explicitly unknown, never evidence that collection resumed. This display
does not change source history, runtime inventory or any pause setting.

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
   This also restores the existing scheduled/manual paid voice-evaluation
   and threshold-refresh eligibility; PR replay still requires its separate
   opt-in and existing rules. Clearing the variable does not enable a disabled
   workflow.
2. Set the dashboard Production variable to `0` and redeploy.
3. Separately re-enable `refresh-thresholds.yml` only if resuming that collection
   is authorized and it was enabled before the pause.
4. Restore the previously recorded self-heal setting only if intended.

Automatic publication has separate controls. Resuming collection does not
authorize enabling publication or autoship; preserve those pause settings.

## Scope

Offline tests remain available. Independently authorized development evaluations
are separate from the guarded GitHub paid jobs. This is an operational pause of
current production entry points, not revocation of API
credentials. A deliberate CLI invocation, an old workflow ref without the guard,
or an older dashboard deployment can bypass the new controls. Do not use those
routes while production is paused. No external scheduler is changed by this
runbook; inspect any separately configured scheduler before claiming coverage.
