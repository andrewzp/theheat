# Batch checks bind the final formatted text

The experimental batch lane now retains both the original provider candidate and
the text produced by the existing source-link formatter. Its new schema2 check
packet keeps the original candidate ID and metadata, and adds a separate derivation
binding the raw candidate, complete bundle, policy, formatter identity and final text.

SQLite and PostgreSQL independently build that derivation from the retained result
row during atomic intake. Current validation compares the entire raw candidate as
well as its ID. Deterministic checks, safety, fact-check requests and interpretation,
and critic requests all use one verified final-text accessor. Formatting never
adds a model request or grants publication approval.

Current trusted source must independently reproduce the final string. Consistent
stored hashes alone cannot certify the transformation. The formatter uses the
existing conservative full editorial source identity, including dependencies.
When that implementation is unavailable, history remains readable with an explicit
unavailable verification result; it cannot acquire a new execution grant.

Schema1 packets remain raw-text history. Their bytes, identifiers and historical
stage dispositions are preserved. They cannot be silently upgraded or supply new
current checks. Exact old terminal receipt retries and late raw observations are
retained; new late completion is stale. The executor blocks legacy or unavailable
formatters before acquiring a lease or constructing a provider transport. Existing
unknown-cost holds, one grant per stage and job/item uniqueness remain in force.

Tests use synthetic inputs and offline provider fixtures. Both database adapters
exercise raw/final separation, candidate substitution, historical reads and late
receipts; existing real transaction, failure/retry and restore tests exercise new
schema2 intake. Direct scientific-rule fixtures receive new in-memory derivations
while retaining their actual negative assertions. No scientific check is bypassed
to make a formatter fixture pass.

This remains local/preview code. It does not activate batch submission, create a
production authority, promote a draft, change runtime models or samples, or prove
better copy or lower bills. Dashboard policy must be manually deployed after the
required checks. Gist remains the production store and publishing stays paused.
