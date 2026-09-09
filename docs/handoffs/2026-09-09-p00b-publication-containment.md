# P00b publication containment

Local implementation. Production rollout and an observed paused bot snapshot must be verified separately. No provider call, publishing attempt, production mutation or deployment was performed while implementing this slice.

## Configuration and release protocol

`THEHEAT_AUTOMATIC_PUBLICATION_ENABLED` accepts only `1` to request automatic publication. Missing, empty, invalid and `0` all pause it. This default applies in every runtime, including production. `THEHEAT_AUTOMATIC_PUBLICATION_EPOCH` must be 8–96 ASCII letters/digits/dots/underscores/hyphens, beginning with a letter or digit. It identifies a release authorization, not a lock.

Initial containment configuration: enabled `0`, epoch `p00b-paused-2026-09-09`, legacy `THEHEAT_AUTOSHIP_ON_CRITIC_PASS=0`. The legacy flag alone does not pause policy-only or manually scheduled automatic publication.

Rotate the epoch on **every pause and every release**. Observe a paused bot invocation and its persisted `publication_control` before releasing. That invocation retires the previous epoch, the paused epoch, and obsolete epochs bound to pending auto approvals; it revokes timers/approval bindings while preserving source evidence, reviews, exact publication attempts and receipts. Retired epochs merge by union without trimming. Returning to a retired epoch stays blocked, and old or missing epoch bindings never authorize auto sends. New automation requires a new epoch and new approval.

The dashboard also defaults paused. To release its scheduling UI/API later, configure the same enabled flag and epoch in the dashboard deployment, and first obtain a fresh bot snapshot (at most six hours) confirming that epoch is enabled. Runtime display labels this as observed configuration, not a live external flag read.

Changing repository variables cannot recall a running old process. Confirm all older jobs have ended, reconcile possible sends, deploy the new guard, and verify the first paused invocation. An off/on toggle completely between observations with a reused epoch cannot be discovered from process environment alone; rotating every epoch and verifying the persisted pause is mandatory. P00c will centralize that operator transition and its credentials.

## Behavior

Draft creation and evidence collection continue. Both arming paths, due processing, final sender and latest-read intent persistence enforce the automatic policy. Existing manual reviewed draft approvals remain usable through their exact P02 contract; no manual canary is invoked by this change. Unknown platform outcomes never become retryable through a pause.

The ad-hoc composer is a writing preview only. Its former `/api/post` route refuses publication, and the Python manual entry/final sender refuse untracked text independently. Publishing requires a retained draft ID, current review and exact approval. This containment does not claim that the separate preview generation already shares scientific validation or usage accounting; P25 remains open.

Production re-enable gate: P02/P05/P07/P07a and relevant P04/P06 pass; P03/P00c fixed or explicitly contained; pending drafts revalidated; authorized controlled manual canary succeeds. The current upgrade assessment and actual-tweet evidence qualifications remain the baseline. No public correction is authorized by a technical release.

## Verification

Offline regression coverage includes every auto ownership lane, missing/malformed config and epoch, direct sender bypass, raw API/CLI text, pause/release with stale state, retired-epoch intent-write refusal, unknown-attempt preservation, fresh bot/web policy agreement and cross-language malformed-control fixtures. Existing editorial/posting tests opt into a named offline release fixture rather than relying on automatic publication being enabled by default. Platform and model calls are replaced.

Independent P03 review checked the final sender and persistence path and found a null/missing JavaScript merge discrepancy, fixed with a shared malformed-control fixture. The observer becomes durable only after successful state save; production verification must read the persisted control after a paused invocation.

Final local validation: **2,580 Python tests passed**, 41 paid replay tests deselected; **211 dashboard tests passed**; Ruff, mypy (121 modules), production dashboard build and diff whitespace checks passed. No live model or platform request was made.

## Remaining limits

Gist PATCH is not atomic. Epoch union protects observed stale merges, not simultaneous unconditional writes. Credential isolation and one serialized command consumer remain [P00c](../plans/2026-09-09-p00c-single-mutation-authority.md). A real hosted pause observation and old-worker audit are deployment gates. Scientific claim validation, source recovery, publication reconciliation and the eventual single editorial API remain separate plan work.
