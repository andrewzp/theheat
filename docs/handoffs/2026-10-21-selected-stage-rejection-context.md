# Selected safety and critic rejection context

New synchronous candidates rejected by the safety pipeline or final selected
critic can retain a private `rejected_candidate` packet through the existing
suppression store and authenticated API. These packets use schema version 2,
with separate `selected_safety_rejection` and `selected_critic_rejection` scopes.
Existing factual-rejection version 1 packets retain their original shape and
meaning; legacy rows remain readable without backfilling missing evidence.

A retained packet records the exact selected text and hash, initial or revised
attempt, complete detached source bundle and hash, stage and structured terminal
verdict. The bundle is captured before that stage and compared at rejection.
Changes since generation entry or during the stage make capture unavailable.
Equality cannot detect a transient mutation that is restored. Revision captures
use the actual second candidate and its own terminal verdict. A slate rejected
before selection has no selected-candidate packet.

Safety exposes only its final allowed/reason tuple. Its packet preserves the
explicit refusal and reason, with `response_status: "not_exposed"` and a null
response diagnostic. This does not establish a complete model response, provider
request, cache receipt or paid call. Malformed, invalid or unavailable safety
outcomes produce an unavailable disposition. Critic packets retain the terminal
KILL reason and correlation hash of the returned response; they do not duplicate
raw provider bodies. Exhausted critic parsing is unavailable, not a completed
editorial judgment. Transport exceptions remain outside the retained packet
scope and preserve their existing operational failure disposition.

The existing limits remain 32,768 serialized bytes per source bundle, 4,096 UTF-8
bytes per text and 40,960 serialized bytes for the entire packet. Missing, changed,
invalid or oversized evidence is never truncated into a retained packet. Captures
and suppression insertion detach mutable objects. Reused result dictionaries and
negative-cache early returns clear prior packets. Public selected-stage logs use
bounded correlation diagnostics instead of candidate text or model reasons.

The latest 100 suppression rows remain temporary operational context. At the
packet ceiling, packet content alone adds at most 3.90625 MiB before outer state
formatting. This is neither a permanent archive nor total-state growth control.
There is no new model/source call, cache eligibility, retry, budget, prompt,
check-order, runtime setting, backend or publication authority.

Offline tests exercise real writer, safety, fact-check and critic functions with
explicit model fixtures, actual revision and suppression paths, Python state
save/merge/read, and the actual authenticated JavaScript API with mocked storage.
Unauthenticated requests must return before reading storage. Tests cover version
compatibility, exact bounds, unavailable checks, failed capture, mutation, selected
and revised identity, stale reuse and existing retention. Local tests are separate
from review, CI, deployment and production observation.

P15 remains partial. These packets do not contain full provider requests, memory,
checker state or prompt archives, and do not reconstruct historical rejections.
Scientific adjudication, human copy quality, costs and measured product improvement
require separate evidence.
