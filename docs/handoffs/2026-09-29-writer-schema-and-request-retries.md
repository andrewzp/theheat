# Writer schema compatibility and nonretryable request errors

A read-only runtime investigation found Anthropic rejecting the writer's nullable
rejection enum before generation, then the shared retry helper repeating that
identical HTTP400 request. The API diagnostic named the enum value evidence and
the declared string/null type array. This is a software request failure; it does
not establish the account's credit balance or an all-year incident explanation.

## Fix

`kill_scope` and `kill_code` now use an anyOf containing a string-enum branch and a
null branch. The same values remain allowed; required fields, strict additional
properties, parser, prompts, model settings and sample count are unchanged. Shared
synchronous and batch requests receive the same schema. Anthropic documents these
basic types and anyOf in its [supported schema features](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

The shared retry owner now reads structured HTTP statuses from Anthropic, Google
and HTTP-client exceptions. Definite 4xx stop immediately, except 408/409/429.
Billing keeps its existing distinct BudgetExhaustedError classification. Unknown,
timeout and server failures retain their prior bounded retry budget; conflicting
or invalid status fields are not guessed from message text. Other exceptions are
re-raised unchanged. No new error body logging or provider/model switching is added.

## Verification and limits

38 new cases; 139 focused and 4,516 full offline Python tests pass in the original
local SDK environment. All 294 dashboard tests/build, Ruff, mypy (150 source
files), generated contracts and whitespace checks pass. One existing SDK warning
remains. No scientific rule changed after the preceding historical regression.

A separate check against newly observed production SDK versions exposed a
compatibility gap: Anthropic 1.9 uses httpx2, while the local 0.94 environment uses
httpx. 32 of 190 focused checks failed at client construction/mock transport; 158
passed. In particular the local batch adapter's explicit httpx client cannot be
passed to that newer SDK. This must be fixed and retested before release; do not
present the original environment's green suite as production dependency parity.


The actual installed Anthropic SDK is exercised through HTTPX MockTransport.
A fixture reproduces the observed old-schema HTTP400 and proves it is attempted
once, without a JSON or length repair. The new wire shape succeeds against that
bounded fixture. Scalar-contract equivalence, all allowed rejection values,
invalid combinations and sync/batch request parity remain covered. Real SDK error
objects verify permanent and retryable HTTP status handling.

This offline fixture encodes the observed compiler failure; it is not Anthropic's
live compiler. Successful funded generation is not yet observed. No API request,
production publishing, credit change, paid replay or public correction ran.
A release must still pass required CI and manually deploy the regenerated dashboard
policy manifest. Local tests cannot substitute for that release or runtime proof.

The HTTP-family gap is resolved by the subsequent [tested dependency change](2026-09-29-tested-provider-sdk-dependencies.md); the failed probe above remains historical evidence.
