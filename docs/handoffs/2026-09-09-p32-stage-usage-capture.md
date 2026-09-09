# P32: capture the existing checking and news responses

Implementation baseline: `a51b809`, following the reviewed five-site accounting map. This is response accounting, not full account reconciliation, a budget cap, or a model-quality claim.

## Change

A shared `record_response(stage, response, model, provider)` observer captures the existing fact-checker, critic, safety, grounded-news search and per-impact verification return sites. Capture follows the SDK/retry return and precedes text access or JSON parsing. The two writer sites retain their existing compatibility entry point. Requests, prompts, models, tool configuration, provider invocation count, transport retry budget and parsing/revision policy are unchanged.

Returned but empty, rejected or malformed output still produces a response row. A transport failure before a response does not invent one. Metadata errors record one unpriced response; accounting failure cannot create a provider retry or alter a stage result. Google responses cannot borrow the Anthropic price table even when their requested model string coincides with an Anthropic name. Existing stored estimates are never repriced.

Python and JavaScript readers list the six instrumented stage keys as this code version's capabilities. That is not proof that retained runs captured every call, and no historical usage is backfilled. Missing/partial/inconsistent accounting remains explicit, and the existing monthly reference thresholds and prior-incident handling are unchanged.

## Boundaries deliberately retained

- Gemini token and grounding costs remain unpriced. Prompt/candidate/cache counts do not fully represent thinking, tool, modality or service-tier dimensions.
- The shared buffer still holds 500 responses. New checking/news traffic can evict earlier writer rows; the test and reporting limitations expose that possibility. Per-day/model cumulative witnesses remain capped at 32, and day retention remains 45.
- Failed persistence, process termination, late source threads and runs without state writes can lose accounting. Existing cumulative MAX merges can undercount concurrent workers. No per-call durable ledger or invoice reconciliation is claimed.
- `MAX_VERIFY_FETCHES=3` limits page retrievals, not model verification calls. Multiple impact entries can share one page and each require verification. This change measures those existing responses; a real call cap remains separate work.
- Safety's pre-existing no-key/provider-error/empty-answer behavior is unchanged. An allowed boolean still does not prove a model check completed; the P10 decision note records that separate execution-status requirement.
- Automatic publication remains paused. No paid evaluation, account credit, provider call, workflow dispatch, test tweet or public correction is part of local implementation and validation.

## Validation

Focused tests mock the lowest-level SDK calls and compare exact request arguments and outputs with capture enabled/disabled. They cover returned-response timing, JSON versus transport retries, missing keys, deterministic rejection, metadata exceptions, accounting failure, multiple impacts sharing one page, buffer eviction and cross-language SQLite preservation of legacy estimates and publication uncertainty.

A separate AST comparison removes only the five observer calls/imports and confirms that all four stage modules otherwise match the baseline, including request and retry behavior. The existing private historical runner has no unexpected observations or provider calls; its original frozen package is unchanged. Combined validation passes 3,661 offline Python tests, 294 dashboard tests, production build, standard Ruff/mypy and both generated contracts. Direct newsworthiness mypy reproduces three pre-existing nullable-place narrowing errors in both the baseline and this branch; that data module is excluded from standard mypy. No live quality, invoice savings or fully reconciled cost claim follows from mocked calls.
