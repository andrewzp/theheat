# Complete checked-bundle retention

New accepted synchronous drafts retain the complete StoryBundle serialization in
`review_context.two_bot.bundle`, including raw source inputs, headline metric,
historical context, related signals, country and human-impact facts. Previously,
only the identity and current-facts projection survived. The existing Python and
JavaScript review fingerprints now bind all those retained fields without a new
unbound evidence store. Old incomplete bundles are never backfilled.

Capture follows the current writer's sorted JSON and documented date, Decimal,
set and dataclass serialization. It is detached before paid generation, limited to
32,768 serialized bytes, and rejects bytes, nonfinite/unsupported data and integers
outside JavaScript's exact range. No input is silently truncated. Unsupported
capture produces a bounded diagnostic before provider work; existing evidence
schema failures keep their established disposition.

After all required checks, a second capture must equal the first. A changed or
newly invalid bundle cannot inherit earlier verdicts. This comparison does not
prove that a transient mutation was never restored. Retained source and duplicate
human-impact metadata do not alias caller-owned objects. Provider prompts, models,
sample counts and required checks are unchanged.

The informational `bundle_capture` marker describes the capture format and scope;
it grants no authorization. An edit may remove it along with old verdict metadata,
while keeping the complete source bundle and the prior revision's capture record.
The compact publication-memory reader remains compact. Full provider requests,
responses, memory/checker state and rejected-candidate context require separate
archive work; a complete StoryBundle does not claim to contain those.

Tests use explicit offline model results through actual generation and draft-save
functions, mocked transport through real Python state persistence, and the actual
JavaScript read/edit/merge/save path. They cover complete nested fields, mutation
invalidation, legacy preservation, codec parity, size boundaries, unsafe integers,
no paid calls for uncapturable inputs, and all required checks for accepted inputs.

The per-bundle ceiling is an admission budget, not a measured production maximum
or total-state ceiling. Protected history can grow indefinitely under the existing
retention policy. Durable external storage, failed-packet retention and measured
quality/cost improvement remain open. The generated dashboard policy needs manual
deployment at the reviewed merge. Publishing remains a separate authorization.
