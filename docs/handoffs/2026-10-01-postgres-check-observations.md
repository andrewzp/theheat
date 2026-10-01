# Durable check response observations

A worker can receive a paid checker response and crash before interpreting it.
Retaining the exact response first makes that evidence recoverable. The optional
local PostgreSQL authority now supports this step; production remains on Gist.
The existing production executor and provider transport are unchanged.

## Storage and API

An owner explicitly calls `initialize_check_executions()` after installing the
seven existing schemas. The additive `theheat_check_executions` schema retains
raw responses (including empty or malformed bytes) up to 128 KiB, canonical metadata
up to 4 KiB, and one observation per committed check grant. Database constraints
check byte counts and SHA-256. Immutable tables, restricted runtime privileges,
installation verification and the existing core transaction lock protect the records.

`check_execution("observe", metadata, raw=..., now=...)` requires the exact check
set, stage, grant, original request hash and response hash. It validates completion,
HTTP status and reason independently of any provider verdict. HTTP 200 or complete
transport does not mean the factual check passed. Late responses remain useful
evidence even after the original worker loses its lease.

Exact repeats return the original observation without another write. Conflicting
bytes or metadata refuse replacement. Observation time cannot precede the grant,
latest check write or latest observation. Reads validate the retained packet,
attempt and response joins without treating historical evidence as current eligibility.

`check_execution("read", {"check_set_id": ...}, now=...)` preserves the existing
SQLite result shape. `read_check_response(check_set_id, stage, grant_id)` returns
bytes bound to that grant; it does not expose a general hash-addressed storage API.
Payload sizes are checked before retrieving stored blobs.

## Recovery and limits

Retention never creates another grant, a terminal check verdict, an accounting
settlement, a draft or publication approval. A failed or ambiguous commit cannot
return success. A fresh authority can read or retry an acknowledged observation;
a lost response does not authorize another paid request. Existing unresolved
spending holds remain intact.

The offline recovery rehearsal uses the actual request preparation and response
interpretation functions with explicit synthetic provider responses. It verifies
exact prepared request bytes and hash before interpretation. Malformed JSON,
duplicate fields, truncation, blocked responses and unsupported content cannot pass.
Explicit terminal completion still goes through the existing freshness and policy
checks; late or obsolete outcomes remain stale.

Production executor integration remains separate work. It needs a dedicated exact
request accessor and an adapter that retains evidence before interpreting it. This
change neither selects hosting nor migrates production state or enables batch work.
The storage implementation participates in editorial policy identity, so the generated
dashboard policy manifest requires manual deployment after merge.

## Verification

Focused tests exercise SQLite parity, strict input and storage bounds, immutable
permissions, schema drift, caller mutation, clock edges, expired/replaced workers,
write/commit failure, killed connections, lost acknowledgments, independent concurrent
processes and restoration of all eight schemas. A private compatibility rehearsal
preserves existing draft and receipt data; only synthetic checker inputs and outcomes
are exercised. No actual production draft is certified by that rehearsal.

Required offline regression tests and exact-head CI remain release gates. Passing
these checks does not establish factual source truth, better copy, global coverage,
a reconciled bill or measured savings. Runtime models, one routine writer sample,
explicit required checks and the publishing pause remain unchanged.
