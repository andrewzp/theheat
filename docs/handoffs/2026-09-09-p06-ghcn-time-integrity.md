# P06 GHCN source chronology and material revision history

This is a local implementation handoff. It continues the completed September 8 assessment and its actual-tweet evidence limits. It does not certify old tweets, enable automatic publishing, recover missing original source payloads, or authorize public corrections.

## Result

GHCN cached maxima now nominate bounded source verification; they cannot authorize a new historical record comparison. Before a candidate's station-reported valid date, the verifier reconstructs accepted extrema from a current original `.dly` response. The candidate itself never enters its comparator. All-time, monthly and calendar-date comparisons use independent TMAX and TMIN histories, actual sample years and per-variable source coverage.

A requested cutoff is distinct from the last accepted value and a verified source cutoff. Missing source months or omitted years withhold comparison claims and produce an explicit coverage gap. A complete source calendar may still contain missing or QC-rejected cells: those exclusions remain counted, and the supported claim is only an extreme among available source-accepted GHCN station samples through the qualified cutoff. It does not establish complete observations or an official national record.

The source retains measurement, quality and source flags, observation time when supplied, retrieval time and source-response fingerprints. GHCN station reporting intervals, local timezone, model issue time and historical publication-time QC stay unknown unless the source actually provides them. The code does not replace a station observation date with the run date.

## Bounded collection

Each run attempts at most 20 station-archive fetches, interleaving candidate stations with stations referenced by retained claims. A deterministic daily rotation prevents a fixed first group from always winning. The maximum applies per run; this implementation does not claim a persistent 20-per-day budget. Requests use at most four workers, 30-second request timeouts and an 8 MB response cap. Exhausted, failed and unscanned verification remains visible in source metrics. Existing recent-diff collection remains separate.

Old-dated diff revisions affecting tracked points are retained before the news-age filter. A run with no fresh news can still review a bounded set of retained claims. A missing or unverified current archive produces an uncertainty finding, not a refutation. A later explicit QC rejection or a changed accepted value can establish a current source revision, but does not prove when the QC flag first appeared.

## Durable evidence and approvals

`temperature_history` is an additive durable map carried by Python and dashboard state stores and their SQLite metadata contract. It stores material record points, comparators, subsequent value/QC revisions and exact affected-claim links. Full global daily observations and original archive-byte storage remain P10/P11 work; this map is not a replacement for them.

A finding links retained draft ID, event ID, exact text hash, available receipt ID, valid date and source revision. Repeating the same finding is idempotent. Immutable union preserves every conflicting payload, including a collision at a previously generated conflict key. Reserved `:conflict:<fingerprint>` suffixes are canonicalized before union so replay and merge order cannot erase evidence. Python and JavaScript use the same shared fixture cases and real cross-runtime SQLite round trips.

Only a verified material change may revoke an unpublished pending/approved draft's obsolete evidence review and posting approval. The previous full draft is retained in revision history, including exact text, candidates, checks, approval and intent evidence. Posted drafts, retained receipts and uncertain/malformed send outcomes remain unchanged; they receive separate findings. The P02 helper remains the source of truth for uncertainty and identity checks.

## Actual-tweet regression scope

The Beaver Dams fixture reproduces the retained June 12 value of 34.8°C, June 25 value of 39.9°C, older 31.9°C comparator and currently visible June 25 QFLAG `S`. Surrounding daily values are explicitly engineered test support. The test proves that a verified intervening accepted record changes the comparator and that current QC evidence is retained without rewriting the publication record. It does not establish the original publication-time QC flag or recover the original NOAA response used by either tweet. The older audit's distinction between omitted progression and a literal previous-record contradiction remains intact.

A separate regression uses 15 June 25 values from 2000–2014 and a 2026 candidate. That fixture must not claim a reconciled interval through June 24, 2026: its omitted source years withhold all-time, monthly and calendar-date comparisons. A paired TMAX/TMIN case proves a continuous low-temperature archive cannot qualify a high-temperature gap.

## Validation and integration

On this worktree, 156 focused GHCN, format and persistence tests passed with the already-released `10832af` revision helper loaded only in an isolated test process. Four additional source-cache integrity regressions also passed (160 tests in that combined invocation). Six dashboard durable-history tests, focused Ruff checks and mypy for the five reviewed source files passed. The shared P06 worktree predates the released malformed-outcome fix; its unmodified old helper causes three expected malformed-conflict tests to fail. No duplicate helper patch was added here. Root integration must run the full suite against the actual current helper before release.

All tests are offline. No source fetch, model call, tweet publication or public correction was performed for this validation. The combined P06 release owner will record final integrated validation and remaining world/aggregate limitations separately.

## Independent world-cache review

Review found that two comparator payloads could reuse the same claimed baseline revision ID and avoid same-time quarantine. Cache merge now fingerprints the full semantic snapshot independently of its claimed ID. Conflict-version union retains every payload even when old maps reused caller-provided keys. Retrieval timestamps are normalized as instants so equivalent UTC-offset spellings cannot masquerade as newer evidence. A later verified source read can reactivate the cache entry while prior conflicting payloads remain retained. Regression coverage includes reversed merges, three-way conflict unions, offset timestamps and stale replay after recovery.
