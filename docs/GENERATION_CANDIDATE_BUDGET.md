# Generation candidate budget

Each generation operation may start the writer for only a bounded number of
distinct candidate stories. This page covers:

- what can be configured;
- each operation's maximum;
- what refill does;
- what a failure looks like;
- how the next operation recovers.

It is a candidate limit. It does not limit provider calls, retries, posts or the
invoice.

## Configuration

| Variable | Meaning |
| --- | --- |
| `THEHEAT_TRIAGE_ENABLED` | `1` turns on ranking and the operation budget. Any other value keeps the legacy path: no operation limit, and every queued event is written once, in queue order. |
| `THEHEAT_MAX_DRAFTS_PER_CYCLE` | N, the most candidates one alerts operation may hand to the writer. If unset or empty, N is 3 (the bot workflow also passes `3` by default). The value must be a plain whole number from 1 to 200. It is read once when each operation starts. |
| `THEHEAT_REFILL_ENABLED` | Off by default. When on, the drain goes further down the ranked list after a failed attempt, until it reaches its own target (`THEHEAT_DRAFTS_TARGET_PER_CYCLE`, default 3) or its own attempt ceiling (`THEHEAT_REFILL_MAX_ATTEMPTS`, default twice the target). With triage on, refill also stops at N. When off, the drain never enters the refill path. |

When triage is on and the value is not a plain whole number from 1 to 200 (for
example `abc`, `0`, `-1` or `500`), it is refused, not replaced by the default. The
operation then makes no writer call and records a `triage` run row with
`partial_failure` and the note `candidate_budget_config_invalid`.

## Operations and their maxima

| Operation | Entry point | Maximum candidate attempts |
| --- | --- | --- |
| alerts | `python -m src.main alerts`: one `run_alerts` call covering every source, the supplied warning and NHC runners, every drain and refill | N with triage on. Legacy (triage off): one attempt per queued event, with no operation limit. |
| leaderboard (Hot10) | `python -m src.main leaderboard` | 1. Hot10 is a single daily candidate, not ten posts. |
| both | alerts, then leaderboard, in one process | N + 1, counted as two separate operations. There is no shared global cap. |
| manual_tweet, auto_publish_due | the sender | 0. These modes post approved drafts and generate nothing; the sender's own final safety check is separate. |
| finite NHC/NWS trials | their own scripts | Their fixed trial profiles, unchanged: NHC 1 candidate and 4 reserved calls; NWS 2 candidates and 8 reserved calls. |

In offline tests with invented rows, the current Hot10 bundle is refused at the
source boundary for missing primary-source identity, before any writer call.
These tests do not establish whether live Hot10 rows pass that check.

## What is counted, and what is not

- **Candidate attempt.** One distinct queued story handed to the writer path.
  - A slot is reserved before the paid boundary.
  - The slot stays used if the attempt is rejected, fails or has an unknown outcome.
  - The slot is returned only when the pipeline reports that the writer never
    started: a cache hit, a current-source hold or a missing provider prerequisite.
  - A second copy of an event already handled in the same operation buys nothing.
- **Provider attempts.** One candidate attempt runs the writer (one routine sample;
  revise stays off), then the required safety, fact-check and critic checks.
  - The writer may make bounded repair calls: up to 2 for length and 1 for JSON.
  - Each provider call has bounded transport retries: up to 3 tries for transient
    failures. Billing exhaustion and definitive client errors stop immediately.
  - The candidate budget does not cap any of these.
- **Paid responses.** A returned response may be billed. A refused or unknown
  outcome is not proof of no charge.
- **Retries.** These follow the existing retry rules. The budget adds none and
  removes none.
- **Posts.** Posting is separate. The sender's existing daily cap (10 posts per UTC calendar
  day) applies. The candidate budget is not a two-per-day setting and never posts anything.
- **Invoice cost.** Unknown or partial. `THEHEAT_MONTHLY_BUDGET_USD` (default 14) is
  a reporting comparison with 70% and 90% alerts, not spend enforcement. Unknown
  billing is reported as unknown.

## What operators see

| Case | Signal |
| --- | --- |
| No eligible candidates | Source rows succeed with nothing triaged. There is no `triage` or `generation` row and no writer-stage suppression. |
| Candidate budget reached | `triage_cap` suppressions with reason `global_cap=N` (selection) or `candidate_budget=N` (later drains or refill). This is a normal cap; the run is not marked partial. |
| Selector unavailable or untrustworthy | No writer call. There is a `triage_error` suppression, degraded `triage` source health and a `triage` run row with `partial_failure`: note `selector_unavailable`, or `selector_invalid` with a code such as `selector_over_cap`. |
| Unsafe configured maximum | A `triage` row with `partial_failure`, note `candidate_budget_config_invalid` and an error code. No writer call. |
| Missing provider access | One `provider_preflight` suppression. The rest of the operation is held, with a `generation` row: `partial_failure`, `provider_access_missing`, blocked stage names and reason codes. No credential values are recorded. |
| Provider billing exhausted | The existing `budget_exhausted` and `billing_cycle_abort` suppressions and `billing_aborted` counters, plus a `generation` row: `partial_failure`, `provider_billing_exhausted`. A later operation in the same process is skipped with the same row. |
| Writer or check refusal | A suppression at stage `writer`, `safety`, `fact_check` or `critic`. This is an editorial outcome and does not make the run partial. |
| Source unavailable | That source's row shows `failed`, and the run is partial. |

The workflow step can exit successfully (green) while the saved application run is
`partial_failure`. Read the saved run status, not only the workflow colour.

## Recovery

Every operation builds its own budget when it starts. Nothing about the budget is
saved between operations or shared between them, so the next scheduled run or
manual dispatch starts fresh. Do not restart an exhausted operation to buy more
attempts. Candidates are queued again only when their sources produce them again
in a later run.

- **Selector fault.** The next operation ranks normally once the fault is gone.
- **Unsafe maximum.** Correct the repository variable.
- **Provider access.** Restore the missing credential.
- **Billing exhaustion.** This needs an owner action on the provider account.

None of these recoveries is automatic, paid or retried by this budget.
