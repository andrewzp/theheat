# Runtime persistence and dashboard dependency maintenance

Prepared release: **0.9.108.8**, based on current main `3194e7c`. This addresses an observed operational failure and the previously recorded dashboard advisories. Publishing remains paused; no hosting, model or platform purchase is involved.

## Completed-run persistence

Paused production run `34311472549` saved state/control, then failed its separate final run-history save while the workflow returned success. Its latest runtime snapshot therefore remained old. The original transport cause is unknown because the writer swallowed the exception detail; the state-size warning does not establish that cause. All 40 draft texts, publication ledger, 31 receipt IDs and LLM usage were preserved.

The CLI now finalizes the report before its final state save. One successful write carries both the completed report and the run's returned state. A failed attempt retries that same completed snapshot; two unconfirmed writes exit nonzero, without printing completion. The writer emits only exception class and a valid HTTP status, never exception text, request payloads, URLs or credentials.

Five regressions exercise real run finalization, dispatcher-returned state, current runtime metadata, existing receipts/paused control, partial source outcomes, identical retry snapshots, nonzero exhaustion and sanitized diagnostics. Independent review reran all 167 focused CLI/runtime/state tests and found no actionable issue. Full offline validation on the fix: **3,081 passed**, 41 paid voice replays excluded; Ruff and mypy passed (128 source files).

This is the final flush, not a transactional ingestion or publication authority. Existing intermediate saves in individual modes remain. An acknowledgment may be lost after the server applies a write: an exhausted workflow correctly reports that persistence is unconfirmed, even if the state is later found saved. The retry is state persistence, not a replay of generation or publishing. Hosted Gist concurrency remains P00c/P13 work.

## Dashboard dependencies

The September 9 registry audit reported four affected dependency groups (three high, one critical) in the previous lockfile. This does not establish that every advisory was exploitable through the dashboard's configured feature set. Current publisher advisories and registry metadata were checked before choosing compatible patches.

| Package | Previous | Updated |
| --- | --- | --- |
| Next.js | 15.5.15 | 15.5.25 |
| PostCSS override | 8.5.10 | 8.5.28 |
| sharp | 0.34.5 | 0.35.4 |
| nanoid | 3.3.11 | 3.3.18 |

React and React DOM remain 19.2.4. Next's declared optional sharp range includes 0.35.4, so no incompatible override is introduced. The Next minimum is raised within major 15; the existing PostCSS override is updated. Resolved packages and platform-native artifacts are retained in the lockfile.

Primary references: [Next image-optimization advisory](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4), [sharp/libheif advisory](https://github.com/lovell/sharp/security/advisories/GHSA-rgj7-g3m4-5g8c), [PostCSS source-map advisory](https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp). The audit's other affected ranges were also resolved by these updates. Native image optimization is checked for compatibility; dependency updates do not change the site's evidence or editorial policy.

Verification: fresh lockfile install; **zero known vulnerabilities** in the resulting npm audit; **286 dashboard tests** and production build passed. A native PNG encode/decode preserved format and 8×6 dimensions with sharp 0.35.4/libvips 8.18.6. Ten localhost HTTP checks on the built application confirmed `/`, `/health`, `/api/dashboard`, `/api/drafts` and `/api/config` return 401 anonymously and 200 with fixture authentication. These used an empty local SQLite database, blank Gist credentials and fixture-only login. The owned local server was stopped afterward. This is not the pending signed-in production visual walkthrough.

No original assessment/corpus file is included in this release. No public post, correction, model call, metric lookup, automatic publishing enablement or production database migration was performed. Post-deploy access checks and an actual completed runtime readback remain release gates.
