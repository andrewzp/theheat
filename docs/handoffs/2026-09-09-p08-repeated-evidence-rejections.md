# P08: bounded retries for repeated model evidence rejections

This implements the cost priority in `docs/plans/2026-09-09-product-priorities.md`. It reuses and narrows PR [#464](https://github.com/andrewzp/theheat/pull/464), reviewed at exact head `2b70565a44faaecef4c2c818ca5f89a1841e799f` (`econ/p13-negative-cache`). The PR supplied the two-fresh-verdict design, individual timestamp expiry, kill switch, bounded retention, queue partition/refill handling and many regression cases. Its branch and worktree were not modified.

## Result and boundaries

An unchanged, prompt-ready candidate is deferred after two separate writer attempts unanimously return the same explicit source-evidence rejection code. The dashboard's existing suppression stream records `negative_cache` with a model-attributed reason, retry time and operator bypass. Both legacy triage and refill skip deferred candidates without consuming a writer attempt; a changed-evidence sibling can still take the slot. Direct two-bot dispatch uses the same check immediately before generation and records each attempted verdict once.

The strict writer response adds nullable `kill_scope` (`evidence`, `style`, `context`, `unknown`) and `kill_code` (`insufficient_evidence`, `conflicting_evidence`). A viable tweet requires both null; other scopes require a null code. Older response JSON without the two fields is accepted and cannot arm the cache. The associated prompt change is integrated atomically with this schema/parser change: P07 core is already in main `c0774e6`; metadata follow-up `5108b062` is included locally as `a4bb1fc`. No extra model stage or evaluation is introduced.

Only the initial paid writer-sampling stage can accrue verdicts, and an entire attempt counts once regardless of sample count. All samples must return the same explicit evidence code on their first unchanged response, without contract/transport diagnostics. Local writer provenance defaults to ineligible and cannot be supplied by provider JSON. Any length retry, JSON retry or critic revision prevents reuse of its result against the original packet. An active same-category memory conflict also prevents caching. Style, dullness, queue context, arbitrary textual reasons, critic rejection, failed generated-text checks, deterministic source-contract failures, malformed responses, network outages and billing failures cannot arm the cache. A model's `insufficient_evidence` response is its judgment about the supplied packet; it is not proof that the event is false or that the source is incomplete.

## Identity, expiry and storage

The input fingerprint covers the complete serialized StoryBundle and actual writer MemorySlice. It does not drop retrieval timestamps, source revisions or other changing evidence. The decision epoch hashes effective writer/critic/checker/safety model IDs and settings, actual prompt values, response schema and the source files that define interpretation, scientific policy and context. Changed evidence, relevant memory, model ID, prompt or policy reopens the attempt immediately. Unreadable or malformed inputs disable reuse for that lookup.

The default TTL is 12 hours, with a hard maximum of 48 hours. At least two individually fresh timestamps are always required; the minimum cannot be configured below two. Each event/input/policy/code revision has its own deterministic key. Up to 12 unique UTC verdict instants are retained per revision, and the cache retains at most 200 revisions. Different inputs or evidence codes never pool their counts. Equal-time descriptive metadata and cap eviction have deterministic tie-breaks. Merge and lookup reject malformed or mismatched-key records; merge independently expires old timestamps so stale writers cannot revive expired evidence. Eviction can remove retry history and cause early reconsideration, which is a safe loss of reuse.

The field is Python-owned state metadata carried by the generated dashboard storage contract. Real Python → dashboard JavaScript → Python SQLite tests preserve the cache along with posted text, confirmed receipts and publication ledger. This feature does not mutate tweet approval or publication receipts.

Operator settings:

- `THEHEAT_NEGATIVE_CACHE_ENABLED=0` disables both reuse and recording immediately in that process. Running one bounded cycle with it disabled permits reevaluation; restore the setting afterward.
- `THEHEAT_NEGATIVE_CACHE_TTL_H` sets retention from zero to 48 hours (default 12; non-finite/invalid values fall back to default).
- `THEHEAT_NEGATIVE_CACHE_MIN_KILLS` increases the activation threshold from two to at most ten.

## Evidence and limits

Tests exercise the actual pipeline, dispatcher and both queue modes with the writer call replaced by a local fake. They show avoided invocations after repeated explicit judgments and reopening on changed facts/context/prompt/model/policy; they do not measure model classification quality, live source coverage, dollars saved or engagement. Exact retrieval metadata can change on every cycle, reducing reuse deliberately. Provider changes behind an unchanged model alias are not detectable locally; the finite TTL and bypass bound that uncertainty. No paid calls, bulk provider work, production publishing or public corrections were performed.

The earlier actual-tweet audit remains the baseline. Forecast-versus-observation wording defects and source evidence limits are retained in P06's handoffs; this cache does not turn those historical findings into broader claims or hide new source evidence. Graphics and fuller worldwide adapter coverage remain later work.

## Validation

Validated after rebasing on merged main `c0774e6` and integrating the nullable-metadata prompt follow-up: **3,261 Python tests passed, 41 paid replay tests deselected; 292 dashboard tests passed; production dashboard build, Ruff, mypy (131 source files), generated state-contract freshness and diff whitespace checks passed.** The focused cache suite contains 39 cases, including input-revision merge interleavings, per-verdict expiry, exact-key mismatch, output-dictionary reuse, SQLite roundtrips and changed-evidence queue slots. Independent review reproduced and then verified the retry-context guard using actual writer/provider-mocked paths. All tests are offline; the repository's `voice_replay` exclusion remains active. No VERSION, deployment or publishing configuration was changed by P08.
