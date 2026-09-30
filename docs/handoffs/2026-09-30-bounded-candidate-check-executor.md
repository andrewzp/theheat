# Bounded local execution of mandatory candidate checks

The experimental batch lane can now run the actual required checks, one stage
per invocation: deterministic evidence/honesty/safety/reuse gates, then model
safety, fact checking and editorial review. The worker defaults OFF, performs no
I/O when disabled, and has no workflow or production-store integration.

`execute_check_once` in `src/two_bot/check_executor.py` takes an existing exact
check-set identity, current evidence context and checker state, worker owner,
UTC clock and a trusted reservation for the exact prepared request. The request
builder in `check_requests.py` uses the same prompts and parsers as synchronous
checking. Batch requests add an explicit 4,096-output-token bound; synchronous
defaults are unchanged. There is no revision, slate or synchronous fallback.

Each model stage has one durable dispatch grant. The concrete Google SDK adapter
uses the official API origin, one HTTP attempt, no redirects, 15-second socket
timeouts, a 90-second observed read budget and a 128-KiB response ceiling. Socket
waiting can exceed the read budget by one socket timeout. The worker requires
more than 120 seconds before lease, usefulness deadline or UTC-day expiry and
checks again after recording its grant. Expired or changed context never passes.

An additive immutable observation journal retains raw response bytes and transport
status before check interpretation. Parsing failures do not discard that evidence
or request another response. A restarted worker can interpret a retained response
only against the exact original request. With no retained response, the attempt
requires reconciliation. A response completed after ownership or context changes
remains stale. Token metadata is retained when readable; unknown charges remain
held and are never automatically settled by this worker.

Required checks use real scientific and reuse rules. Strict claim extraction is
still mandatory. Provider-blocked output, multiple candidates, tool parts,
truncation, invalid JSON, and unavailable responses cannot pass. The local stage
does not turn its cheap checks into completed model checks. The returned status
always denies publication approval and creates no draft or posting intent.

## Validation and remaining work

Offline tests use the real Google SDK with synthetic HTTP responses and the real
check parsers. They cover one-request behavior on 429, 500 and malformed output;
lost commit acknowledgments; process death before and after observation commit;
exact request recovery; late responses; changed evidence, state, policy, owner and
calendar day; output and time bounds; immutable observations; additive migration
and backup restoration. Existing synchronous tests preserve request behavior.

This is a local execution implementation, not a production batch rollout. The
Gist store remains authoritative in production. Before integration, finish one
production command authority and all-route cost accounting, establish approved
price/reservation policy and migration/rollback controls, and conduct an explicitly
authorized, bounded trial. No savings, funding continuity, source recovery or
improvement in generated copy is established by these fixtures.
