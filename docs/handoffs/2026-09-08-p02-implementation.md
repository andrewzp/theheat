# P02: revision-safe editing, review and approval

Implementation on `codex/p02-revision-safe-approval`, based on `4b4d965c0ee040463f63893a7304e53012a909fe`. This continues the completed September 8 assessment. The assessment reports and retained tweet corpus are preserved. Following local validation, the user authorized deployment with “please push this live.” Release version is `0.9.108.2`; final merge/deployment evidence will be recorded separately. No test tweets, public corrections or paid model calls are part of release verification.

## Result and scope

Changing saved tweet text, including selecting an alternate, creates a new content revision. Previous fact checks, critic results, review, approval and future posting authorization cannot authorize the changed text. The former text, evidence and decisions remain in revision history. Returning to the original wording still requires a new review.

The editor shows that review is needed and requires an explicit acknowledgement that the current text was checked against its source evidence. That acknowledgement records human review and permits a subsequent manual approval. It does not fabricate model passes. Automatic scheduling requires current model checks; there is no new paid recheck workflow in this slice. Legacy approvals without revision bindings fail closed and require review. An unchanged no-op edit retains its valid review.

The dashboard carries a version snapshot on every mutation. Edits retain the snapshot from when editing began, including across dashboard refreshes. A stale request receives a conflict response; unsaved text is preserved and the editor must explicitly compare it with the latest saved version before replacing that version. Queued approvals remain visible and can be cancelled before a send attempt begins. Unknown or in-flight publication outcomes block edits and approval until reconciled.

## Durable contract

- `content_revision` starts at one for newly saved drafts; legacy drafts are treated as zero. Each actual text change increments it. `text_sha256` covers exact UTF-8 text without trimming or normalization.
- `evidence_sha256` covers the retained event ID, signal type, tweet date, display/source review context, model evidence bundle and Hot 10 rows. Model commentary and check results are excluded from this evidence fingerprint; model checks have a separate fingerprint. This identifies retained evidence, not the complete original upstream dataset or a scientific validity certification.
- Python and JavaScript share a canonical JSON fingerprint contract with frozen cross-runtime fixtures, including numbers and Unicode. Malformed or non-finite evidence cannot establish review.
- `review_binding` ties human or model review to content and evidence. A model binding also covers the exact fact-check and critic results, both of which must pass. The pipeline records the checked text and bundle fingerprints where the actual review inputs are known. Save-time additions such as an appended URL cannot inherit checks for different text.
- `decision_revision` changes when review/approval decisions change, even when text stays the same. Approval contains this counter as well as content/evidence identity. A stale save with a newer timestamp cannot restore a revoked approval. Review remains tied to content/evidence so a subsequent valid approval does not invalidate the review itself.
- `approval_binding` contains manual/auto mode and the publication intent when present. A tracked manual workflow must present the same intent and exact saved text. The final Python sending function independently verifies current review, authorization and status.
- `revision_history` preserves superseded copy and decisions. Equal-revision contradictory contents or equal-counter contradictory approvals become explicit conflicts requiring resolution and review. State merging preserves newer content and decision revisions rather than selecting old approval based on timestamp or status.
- Publication evidence survives editing, cancellation and state merging. Ledger rows preserve exact submitted text and content identity, a stable attempt start time, intent, outcome and receipt. Confirmation adds `confirmed_at` without changing the attempt identity. Distinct attempts remain separately represented. Missing receipts never expire into permission to retry. A proven rate-limit rejection or pre-network refusal is treated as not sent.
- The submitted text is copied before network activity. Publication memory and receipts use that snapshot, preventing a later mutation from changing the historical record of what was sent. Human-edited copy does not acquire claims extracted from an obsolete model review.

These are draft and ledger fields within existing top-level state structures; no new top-level state key or backend migration is introduced. JavaScript SQLite draft mutations lock before reading. Gist mutations and Python pre-send writes reject conflicts visible in their latest reads, including ledger-only changes. These checks do **not** supply an atomic Gist compare-and-swap or remove the final read/write/send race.

## Validation

Final integrated validation on this working diff:

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | 2,549 passed; 41 paid replay tests deselected |
| `npm test` in `dashboard` | 168 passed |
| `.venv/bin/python -m ruff check src tests` | Passed |
| `.venv/bin/python -m mypy src` | Passed; 119 source files |
| `npm run build` in `dashboard` | Passed |
| `git diff --check` | Passed |

Focused regressions cover armed-draft edits, alternate selection, changed evidence, altered check results, A→B→A edits, stale acknowledgements, cancellation without text changes, stale queued jobs, unknown publication, known not-sent retries, matching receipts, frozen sent copy, cross-runtime state merging and both storage adapters. Invalid Unicode is rejected before mutation. Lost dashboard responses preserve unsaved edits and explain that the action may have completed before refreshing state.

The first integrated Python run exposed outdated success fixtures and cross-test mock leakage from the legacy `main` compatibility facade, as well as a real reconciliation timestamp bug. Fixtures now establish explicit checked-text/evidence proof, sender tests reload the production module before mocking external boundaries, and receipt reconciliation preserves immutable attempt start separately from confirmation time. The final full suites above include these corrections.

An isolated SQLite fixture and local dashboard server were prepared with external requests blocked. The browser tool rejected both local URLs with `ERR_BLOCKED_BY_CLIENT`, so a visual/interactive walkthrough was **not** completed. The server was stopped. API tests, UI control tests and the production build pass, but they do not substitute for visual browser QA.

The local implementation was presented with Git intent-to-add entries so all new files appeared in the review diff. The authorized release includes the implementation, tests and this record. The pre-existing assessment/corpus artifacts remain locally preserved and outside the release commit; the local assessment handoff links to this continuation record.

## Operational refresh

The starting checkout and remote `main` were both verified at `4b4d965c0ee040463f63893a7304e53012a909fe`. Existing open PRs included #463 (structured outputs), #464 (negative cache), #438, #346, #324 and #207; none was a P02 implementation. The non-secret flags were `AUTOSHIP_ON_CRITIC_PASS=1`, `CRITIC_REVISE_ENABLED=0`, and `WRITER_SAMPLES=1`. These observations are a point-in-time check, not a production release decision. No writer request was made to test whether the previously observed credit failure had recovered. No backend, flag, workflow or public post was changed.

## Actual-tweet findings remain release evidence

This slice prevents checks from following edited copy. It does not repair factual mistakes that a checker originally approved. Preserve the audit's distinctions:

- Anchorage confused an alert threshold with a historical rainfall record; Chennai and Bishkek promoted forecasts to observations; Bavi was described as having made landfall while an official position placed it offshore.
- Congo's purported wildfire is strongly suspected to be a volcanic anomaly, but the exact pixel classification remains unproven. Barrow has an unreconciled satellite/gauge discrepancy. Beaver Dams omitted intervening record progression; a later NOAA quality flag is visible now, with unknown addition time.
- The corpus contains 31 receipt-backed posts, seven additional rows marked posted without IDs and 25 generation-memory texts of unverified publication. Twelve receipt-backed posts were corroborated live. The eight selected view counts (12–416) are not a complete history or a controlled engagement benchmark. Prior AI letter grades are not truth labels.

The original audit, fact notes and corpus linked from the main handoff remain the evidence source. This implementation makes no public corrections or historical truth-label changes.

## Remaining work and release limits

P00c/P13 still need an atomic publishing authority; P14 still needs the complete durable publishing/outcome-reconciliation design. The existing untracked manual composer remains a separate escape hatch outside this P02 change. This slice does not fix all known SQLite metadata losses or broad retention problems (P03), validate weather evidence semantics (P05), or rewrite factual/editorial policy (P07). It also does not add an operator workflow for resolving unknown platform outcomes; those remain blocked rather than silently retried.

The next specific task is **P00: timestamped runtime inventory and truthful dashboard health**. Show effective flags/models, deployment version, last successful source/draft/post, queue age and actionable failures; distinguish unknown or inactive collection from success. Refresh the writer-credit and source-access failures without assuming that a green workflow means the product works. Then proceed through P00b/P00c containment, P00a retained benchmarks, P00d correction-candidate review and the remaining Phase 0 dependencies in the assessment. Public corrections remain proposals requiring authorization.

Do not restore or activate automatic production publishing on the strength of P02 tests or recovered model credits. Any deployment must coordinate the dashboard and Python contracts; mixing an old dashboard or old publisher with the new bindings is not a supported release configuration.
