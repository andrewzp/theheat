# P00: observed runtime and product-health projection

Local continuation on `codex/p00-runtime-health`, based on deployed main `9654868ac15d728a0ccc4fad9122c908bf05366f`. P02 and the authentication fix are live; their signed-in dashboard and review-screen walkthrough is now complete. This P00 diff is local, reviewable and not deployed. Original assessments and retained tweet corpus remain in place and outside the implementation changes.

## Implemented

The bot captures a timestamped, allowlisted `runtime_inventory` inside each invocation's existing run-history entry before dispatch. It reports actual loaded writer, fact-check, critic and safety models, effective editorial/publication/source flags, code SHA/version, backend and credential presence booleans. It never dumps environment variables, credentials or local paths, and performs no network or model call. Removed claim extraction and legacy voice generation are explicitly inactive. Missing build identity is unknown. Existing run finalization, merge and SQLite run JSON preserve this snapshot; no new top-level state key or backend migration is introduced.

Both dashboard APIs now read the bot snapshot instead of inferring its configuration from Vercel's separate environment. A newer uninstrumented run cannot inherit older settings. Unsupported, invalid or future snapshots stay unknown; snapshots older than six hours are stale. Dashboard and bot deployment identities remain separate. This is evidence of an invocation, not proof that settings stayed unchanged afterward.

The main dashboard and Health tab show the latest retained nonempty source run, saved draft, current text/evidence-bound review and receipt-backed publication. Queue age includes uncertain publication and orphan ledger events; uncertainty never expires into permission to retry. Missing/malformed collections produce unknown counts, not a healthy-looking zero. Generation memory and drafts marked posted without an explicit tweet ID do not become publication receipts.

Writer reporting distinguishes unknown access, recorded responses and retained pipeline failures. Daily usage cannot order same-day errors, and an undated failure cannot be dismissed as recovered. Pipeline errors may occur after the writer. No successful workflow, stored credential or absent recent error establishes current provider credits.

Engagement reporting separates collection configuration from stored data. Fresh disabled collection is visible even when old samples exist. No eligible retained post within the collector's 30-day window means inactive collection, not successful access. Missing metrics remain null; genuine recorded zero remains zero. Nested conflict receipts count as publication evidence but remain outside the current collector's selection path unless also represented by a collected draft/top-level ledger ID. No account-wide or causal engagement claim is made.

The pipeline summary counts successful active source attempts separately from skips and unknown statuses. The automation banner no longer promises self-healing or calls unavailable workflow checks proven run failures. The health panel uses expandable detail, explicit unknown/stale labels and narrow-screen wrapping; tab navigation scrolls within its own row.

## Validation

- Full offline Python suite: **2,555 passed; 41 paid replay tests deselected**.
- Dashboard suite: **204 passed** at final functional verification.
- Ruff and mypy pass; 120 Python source files checked.
- Final production dashboard build passes after the review fixes; `git diff --check` passes. The local preview server was stopped after browser checks.
- Independent reviews found and resolved missing-state zeros, disabled-collector visibility, unorderable writer failures, and snapshot date validation. Added regressions cover these boundaries.
- Chrome local walkthrough used an isolated SQLite fixture with external credentials explicitly blank. It verified old-queue visibility, writer failure, disabled metrics, missing review, expansion of bot settings and disabled posting controls. Only read-only public workflow lookups were allowed to occur; no generation or publication action ran. Desktop and 390px panel layouts were visually reviewed, including long revision strings. The design-improve skill's referenced audit/critique/polish helper files were unavailable, so direct accessibility, state, responsive and visual checks were used; no formal skill scores are claimed.

## Evidence and remaining work

The signed-in live P02 dashboard still showed expired NASA Earthdata credentials, GPM HTTP 401, GDACS schema drift, two old June approvals, failing voice-regression/threshold workflows and state-size warnings around 3.67 MB. Those observations were refreshed during the release walkthrough. Writer credits were not tested with a paid request, and this work does not establish recovery. The new bot snapshot will remain unknown on production until the corresponding bot code runs after release; do not fabricate it by editing the Gist.

P00's instrumented local implementation is complete; production rollout and confirmation of the first real runtime snapshot remain. P00b publication containment and P00c/P13 serialized mutation authority remain subsequent work. Gist writes are still non-atomic, and the separate composer, source semantics, scientific validation, retention and dependency maintenance findings remain open. No production flag was changed, no public correction or test tweet was sent, and no paid model call or provider-account modification occurred.

Carry the actual-tweet findings forward unchanged: confirmed threshold/forecast/landfall errors are distinct from the unproven Congo thermal classification and unresolved Barrow disagreement; the timing of Beaver Dams' later QC flag remains unknown. The retained corpus is 31 receipt-backed posts, seven additional rows marked posted without IDs and 25 generation-memory texts with unverified publication. Selected live view counts and prior AI grades are not a performance benchmark or truth labels.
