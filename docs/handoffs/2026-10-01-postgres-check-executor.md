# Local required-check executor through PostgreSQL

The existing default-off executor previously depended on SQLite's general
artifact reader. It now accepts a five-method authority protocol and uses explicit
set/stage/grant-bound request and response accessors on both local authorities.
No production route selects this backend or enables this executor.

Each invocation still performs at most one mandatory stage. A fresh exact request
must match the committed grant before retained output is interpreted. Response
bytes must also match the observation's set, stage, grant, request and digest.
Scoped reads validate schema, identity, bounded bytes and metadata under the
existing authority lock; an original request remains available before its response.
The protocol imports neither concrete authority nor the optional PostgreSQL driver.

A lost grant acknowledgment never authorizes another request. Retained responses
recover through the same strict interpreter after a parse/completion crash; a
missing response remains unresolved. Late evidence cannot become a current pass.
Unknown charges stay held. Completing all stages grants neither posting approval
nor accounting completion. Routine sample count, prompts and runtime models stay
unchanged. Gist remains the production store and automatic publication stays paused.

## Validation

- 222 focused tests: 78 real PostgreSQL executor cases, 76 SQLite executor cases,
  53 existing PostgreSQL observation cases and 15 editorial-policy cases.
- Actual SDK HTTP fixtures exercise the four required stages; transaction faults,
  lost acknowledgments, terminated connections, fresh-process deaths and competing
  workers verify that a committed grant cannot be purchased twice.
- Eight-schema backup/restore resumes retained evidence without another request.
  Damaged metadata, missing bytes, schema/permission drift and excessive sizes
  refuse before interpretation; oversized payloads are checked before retrieval.
- A private preserved-state rehearsal uses synthetic checker inputs and offline
  responses. It establishes state preservation, not historical scientific truth
  or improved generated copy. No paid provider trial was run.
- Local stronger review covers paid dispatch and exact interpretation. It is not
  an independent review. Protocol type compatibility and lazy imports also pass.

Full release checks and exact-head CI are recorded separately at release. Both
authority adapters are now policy-bound, and the generated dashboard manifest
requires the normal manual deployment. No new migration or schema version is needed.

## Remaining boundaries

Production hosting, authenticated authority ingress, all-role budget integration,
settlement/invoice reconciliation and measured batch trials remain separate work.
This local integration does not establish lower actual bills, human-preferred
copy, global coverage, graphics attachment or completion of the broader upgrade.
