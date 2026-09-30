# Default-OFF batch submission adapter

`submit_batch_once` connects the existing local plan, reservation and worker
journal to one optional Anthropic batch create request. It returns immediately
when disabled, before authority, clock or transport I/O. It is unwired to all
production entry points and defaults OFF. This implementation authorizes no paid
trial, schedule, production backend migration or publication.

Enabled execution verifies the exact retained plan, current loaded editorial
policy and required provider credential prerequisites before constructing a
transport. Presence remains access/funding-unverified. The authority then compares
the supplied current context and grants a single submission under a 60-second
lease. A committed prior attempt never calls the provider again. No model, prompt,
sample count, output schema, pricing or runtime editorial flag changed.

The adapter fixes the API origin, sets SDK retries to zero and disables HTTP
redirects. Successful response reads are capped at 64KiB with a 30-second network
timeout and an elapsed read bound checked between chunks. The network timeout is
not a guaranteed total wall-clock deadline across every connection/read phase.
The SDK handles non-success error bodies internally; they are never exposed in
application diagnostics. Clients close on every ordinary result/failure path.
Returned provider URLs are not followed.

A successful body is retained against the exact grant before current-owner
adoption. An expired worker can preserve response evidence but cannot adopt it.
Transport errors, invalid acknowledgments, oversized bodies and lost database
acknowledgments leave the request/charge uncertain. There is no automatic provider
retry, synchronous fallback, cancellation or charge release. Public status fields
never grant collection, factual approval or publication.

Validation: 35 new cases; 232 focused cases; all 4,370 offline Python tests pass,
41 paid excluded. Ruff, mypy over 148 source files, generated contracts and diff
checks pass. Actual Anthropic SDK 0.94.0 uses httpx.MockTransport, verifying exact
HTTP request contents and one attempt on 429/5xx/timeouts/redirects, bounded success
reads, client closure, secret-free diagnostics and crash/replay handling. No model
was called. SDK metadata declares Python >=3.9; local tests use Python 3.14 and
remote Python 3.12 CI remains pending release. The older declared SDK lower bound
was not independently executed; source retrieval for that version was unavailable.
No dashboard source changed and no production deployment occurred.

Next: retain bounded result files before parsing, fence current result review,
account for unusable output, and pass eligible exact text through the ordinary
mandatory checks. Actual lower cost or improved human preference is not inferred
from a successful mocked submission.
