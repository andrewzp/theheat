# Bounded local batch collection

`collect_batch_once` is independently OFF by default. It can recover work after
new submission is stopped; it never creates a batch, calls a model/checker, writes
a draft, changes production Gist or grants approval. Existing uncertain charge
holds remain intact.

## Behavior

The local result index validates retained artifacts and receipt bindings. Reuse
prefers the chosen complete receipt, then a retained complete download; it needs
no credentials or transport and always performs a fresh fenced review. Explicit
refresh permits one new read cycle. With only partial receipts a later invocation
can retry retrieval without buying another writer request. Exhausted receipt
capacity blocks new network reads before evidence would be lost.

A read cycle has at most one metadata GET and, only for terminal matching metadata,
one results GET. The SDK uses fixed origin, validated provider ID and canonical
routes; provider-supplied URLs are never followed. Retries and redirects stay off.
The 30-second network timeout and inter-chunk elapsed guard are not a promise of a
strict total duration across every transport phase. Successful/partial reads retain
at most 65,536 metadata bytes and 3,000,000 result bytes. A size/time/read failure
returns retained prefix bytes explicitly incomplete, never a truncated success.
SDK error-body handling is internal and no exception body enters diagnostics.

The canonical endpoint is documented in Anthropic's [results reference](https://platform.claude.com/docs/en/api/messages/batches/results).
The SDK convenience results method fetches metadata again and follows results_url;
the adapter instead uses its raw HTTP interface and preserves exact JSONL bytes.

Nonterminal progress is an observation only, not a terminal receipt or polling
loop. Invalid metadata and interrupted terminal downloads are retained before
review. A late worker may preserve bytes; only current fenced ownership may review.
The actual loaded policy overrides a stale caller policy; missing policy retains
evidence without a review. Missing unrelated checker credentials cannot prevent
accounting recovery, but no check is thereby completed. Review freshness and later
required checks remain mandatory before any candidate use.

## Validation and limits

51 new cases, 126 focused result/submit/collection cases and 4,461 full offline
Python tests pass (41 paid excluded). Ruff, mypy over 150 source files, generated
contracts and whitespace checks pass. One existing Google SDK warning remains. Actual installed
Anthropic SDK 0.94.0 was exercised through HTTPX MockTransport: fixed routes, at
most two GETs, unknown URLs, redirects, rate limits, server errors, timeouts,
oversize, exact bound at EOF, partial reads and resource cleanup. Real local
transactions exercise lost commit acknowledgment, restart, expiry, contradictory
responses, changed context and result capacity. No live API call occurred.

The dependency lower bound 0.77 and remote Python 3.12 CI have not been executed
for this slice. The local SDK check is not a compatibility claim for every allowed
version. No production scheduler, paid trial, mandatory-check integration or
account-wide budget enforcement is added by this local collector.
