# Retain provider usage dimensions without adding model calls

The cumulative usage ledger previously kept configured model names and a small
set of token counts. It discarded returned model versions, thinking/tool usage,
cache-duration splits, service labels and modality breakdowns. These omissions
made it harder to understand unsupported charges without another provider call.

`usage_observations.observe_response` now extracts only allowlisted SDK metadata
before output parsing. It preserves requested and resolved model identities,
optional provider response identity, absent values, explicit zeros, malformed
fields and unknown usage dimensions. No prompt, candidate, grounding text, raw
response, exception body or credential is serialized. No extra provider request,
retry, sample or model-selection change is introduced.

Google observations retain prompt/candidate/cache/thinking/tool-prompt/total token
counts, traffic type and modality breakdowns. Anthropic observations retain the
base token counts, five-minute/one-hour cache creation splits, thinking tokens,
server web-tool counts, tier and inference geography. These dimensions are not
silently summed or treated as equivalent billing units. Extraction follows the
locked SDK types and official [Google response reference](https://ai.google.dev/api/generate-content#UsageMetadata)
and [Anthropic message reference](https://platform.claude.com/docs/en/api/messages/create).

## Retention and integrity

The new `llm_usage_observations` state field holds at most 32 recent observations,
each at most 4096 canonical JSON bytes. The envelope stays below 132 KiB. Shared
generated constants and Python/JavaScript validation keep the representations
aligned. SQLite carries the same field; this is not a production backend change.

An observation receives a local ID and UTC capture timestamp once, before entering
the existing buffer. Failed drains retain the same identities. Stale saves union
exact records instead of duplicating them; different payloads with the same ID
remain distinct evidence. The API reports conflicts still in the retained window.
Deterministic retention makes truncation explicit; invalid input and buffer loss
cannot become reassuring completeness. Preparing both state fields before commit
prevents an ordinary mid-fold failure from partially updating the legacy ledger.

The protected usage readout includes a sanitized `usage_observation_window`.
Legacy estimates and counters remain separate. Google remains unpriced. Existing
prices are not refreshed or retroactively applied, and no usage observation settles
a reservation or grants a spending/publication approval.

## Validation and limits

Offline fixtures use the actual locked Google and Anthropic SDK models. Tests
cover extra dimensions, unknown/raising metadata, no content capture, repeated or
conflicting identities, stale merge ordering, size/buffer bounds, concurrent capture,
failed-drain recovery and actual Python/dashboard SQLite round trips. Existing
stage tests compare requests and output disposition with observation enabled and
disabled. Full release checks and exact-head CI are recorded separately.

This is a recent diagnostic window, not a complete account ledger. Responses lost
before capture, non-state-writing paths, concurrent Gist writes, older evicted
observations, unknown rates, grounding charges and outside account usage remain
accounting gaps. The local durable check executor still retains its own exact raw
observations and remains unwired. Complete production accounting, invoice
reconciliation and shared budget enforcement require their outstanding integration.
No lower invoice, monthly cost, improved copy or successful runtime capture is
inferred from passing offline fixtures. Publishing remains paused.
