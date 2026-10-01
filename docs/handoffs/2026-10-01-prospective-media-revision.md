# Prospective media revisions

An existing text review cannot approve a newly attached graphic. This slice builds
the exact future pending revision and its review packet first, so a supplied joint
review can cover the actual text, graphic, alt text and evidence it would attach.
It does not save that revision to production or grant publication permission.

`build_media_attachment_proposal` resolves the current draft from a supplied state
snapshot and checks its complete predecessor identity, including decision revision.
It validates the proposed graphic against the retained source bundle, creates the
new revision when content changes, and builds a new joint-review packet against it.
`build_media_removal_proposal` removes a present attachment through the same pending
revision transition. Exact identical content is a no-op; stale predecessor requests,
conflicts, malformed or unresolved publication evidence and exhausted counters fail.

The content-only `media_attachment` field binds the graphic specification, renderer
manifest, PNG hash and exact alt text. Review and packet hashes stay outside this
field to avoid a circular identity. Python and JavaScript include it in evidence
identity only when present; absent-field legacy identities remain unchanged.
Present null or malformed values never silently become absence. Revision history,
merge conflicts and SQLite round trips retain the field. Returning to earlier
content cannot restore the old revision or its checks and approval.

A review packet for an attached draft must describe that exact independently
validated graphic. A coherently rehashed but mismatched attachment is refused.
The existing joint-review helper accepts explicit supplied decisions for the
prospective packet, while keeping authentication, source truth, scientific review,
asset retention and publication permission separate. Synthetic examples retain
their synthetic label. PNG validation is structural, not image decoding or visual
certification; immutable retention must still verify all five asset byte streams.

Until the authenticated attachment and transport path is integrated, legacy model,
human and posting paths reject any present attachment. The dashboard returns a
specific conflict for text-only confirmation and displays the joint-review
requirement. Editing text keeps the media and invalidates its old decisions. A
future authority must independently rebuild the proposal under its transaction,
resolve current roles, and retain assets, decision, revision and command receipt
atomically. The proposal hash alone is neither a signature nor authorization.

Validation includes 468 focused offline Python cases, shared identity/merge vectors,
309 dashboard tests and a successful dashboard build. A synthetic localhost browser
fixture confirmed the notice, disabled confirmation/posting controls, and retained
media/history after an Edit/Save operation. No production authentication or live
attachment flow was exercised. Full offline PostgreSQL tests and exact-head CI are
required before release; dashboard/policy changes require manual deployment.

No runtime models, prompts, sample counts, paid-service settings or publishing
activation changed. This is a revision and approval prerequisite; production media,
independent human review and measured quality/cost improvement remain open.
