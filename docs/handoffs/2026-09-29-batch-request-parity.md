# Shared writer requests for future batch planning

Version 0.9.108.21 extracts two pure helpers in `src/two_bot/writer.py`:
`build_writer_user_prompt(bundle, memory, revision_constraint=None)` and
`anthropic_writer_request(user_prompt)`. The revision argument is keyword-only.

The existing synchronous writer calls those helpers. Formatting, conditional
related-signal and impact guidance, revision suffix order, cached system prefix,
model selection, output schema and 1024-token request bound remain unchanged.
Each Anthropic request owns a detached schema; a caller cannot mutate the global
contract through its returned dictionary. Loaded prompt/model/schema values are
read when constructing a request, not captured as stale default arguments.

Existing evidence/scope checks still precede construction. Both provider routes
receive the shared user prompt. Provider-specific configuration, transport/JSON/
length retries, accounting and output parsing are unchanged. Helpers make no
credential, network, filesystem or SDK-client call and do not qualify evidence.

Validation covers the real mocked SDK kwargs and client settings, both dispatch
routes, eight combinations of guidance/revision inputs, detached mutation and
rejected evidence before construction. Full release checks are recorded with the
local commit; no paid replay or provider call is part of this task.

This is request parity, not a submitted batch or demonstrated saving. Next add
bounded immutable batch plans and exact result binding, then durable reservations,
ownership and default-OFF transport. The changed editorial-policy manifest requires
manual dashboard deployment after eventual authorized release.
