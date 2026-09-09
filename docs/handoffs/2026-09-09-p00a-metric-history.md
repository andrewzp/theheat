# P00a: prospective public-metric history

Status: implemented and independently reviewed locally in `codex/p00a-metric-history`, based on released P00b/P03 `8fafd75`. Release integration is recorded separately. No platform lookup, new schedule, paid call or production flag change was made during development.

## Result

The existing collector stores distinct timestamped observations under each retained `tweet_metrics` row instead of overwriting the last counts. The latest projection remains compatible with existing readers. Counts include likes, reposts, replies, quotes, impressions and bookmarks. Absent or invalid fields are null; a recorded zero is data. Unexpected IDs are ignored. Partial or wholly unusable lookup results are recorded as partial failure, so an incomplete response cannot falsely report collector recovery.

The same existing lookup requests `created_at` alongside `public_metrics`. Only that platform timestamp establishes publication time and post age. Confirmed receipt times, draft `posted_at` and legacy unphased ledger times are separate labeled receipt proxies. Modern intent `at` precedes the network call and establishes neither age. Missing, conflicting or future timestamps stay unknown. Only a retained receipt fingerprint establishes the published text revision; a later edited draft cannot manufacture that association.

Every observation has a content-derived identity covering the complete payload. Merge preserves distinct samples, including a reused caller key with different contents. Existing flat rows are preserved verbatim under `legacy_rows`, including merges before the first new sample; they are not invented as modern observations. Conflicting latest counts are detected across legacy and modern history, using normalized instants so `Z` and timezone offsets cannot evade detection. Dashboard totals withhold a conflicting latest value. A genuinely later observation clears that latest conflict while retaining the earlier evidence.

History is nested in the existing durable metric map; no top-level state key is added. Real Python/JavaScript SQLite round trips cover nested observations and null counts. Merge tests cover stale writes, replay, commutativity and three-way associativity. This preserves information during normal merges; unconditional concurrent Gist writes remain nontransactional and require P00c/P13.

## Validation

- Full offline suite on this base: **2,629 passed, 41 paid voice replays deselected**.
- **223 dashboard tests**, production build, Ruff and mypy (121 source files) passed.
- Independent final review reran 50 metric/collector/adapter/persistence tests and 22 dashboard tests. Earlier review exercised 3,375 three-way sample/legacy combinations and prompted the provenance and merge corrections above.
- No actual X call was made; adapter behavior is verified with synthetic provider responses. The existing live window currently has no eligible retained posts, so this does not establish fresh collection or credential recovery.

## Evidence limits and remaining P00a work

The collector keeps its prior once-per-day gate, 30-day application window and maximum 50 IDs. This patch does not increase polling volume, backfill account history or promise fixed post-age sampling. Eligibility still depends on retained top-level draft/ledger receipt dates; nested conflict receipts can have their reference resolved if selected but are not added to the collector's selection inventory here. P00's dashboard exposes this inventory limit. Historical samples are retained but not yet displayed as trends; P30 owns the richer interface and joins.

X's [metrics documentation](https://docs.x.com/x-api/fundamentals/metrics) and [post data dictionary](https://docs.x.com/x-api/fundamentals/data-dictionary) were checked on September 9, 2026. Public metrics combine organic and promoted activity. Impressions do not mean unique readers. The 30-day restriction described for non-public/organic/promoted metrics is not the reason for this application's public-metric window. Access and field availability can vary; absent fields remain unknown.

The frozen incumbent remains 63 retained texts: 31 receipt-backed, seven posted-state/no-ID and 25 generation-memory-only with unverified publication. Twelve selected posts were corroborated live; eight selected lifetime view counts were 12–416. That is neither the complete account history nor causal evidence of lift. No old outcome is fabricated or relabeled by this patch. P00a still needs an independently qualified reference-event denominator, editor rankings, blind evidence-equivalent rewrite evaluation, executable scientific gates and actual prospective samples. P07a and P30 continue those integrations.
