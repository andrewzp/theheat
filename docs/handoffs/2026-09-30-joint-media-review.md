# Exact joint text and graphic review

`record_joint_media_review` binds a supplied decision to an independently rebuilt
media review packet. The trusted caller supplies the current draft identity,
editorial policy, graphic specification, renderer manifest, PNG bytes, authenticated
principal, UTC review time and fingerprint of the preview shown for review.

The payload contains a decision, reason and five explicit confirmations: text
matches data, graphic matches data, text and graphic agree, qualifications remain
visible, and alt text agrees. Acceptance requires all five to be true. Rejection
and requests for changes can retain negative or incomplete confirmations. Unknown
fields, truthy strings, invalid dates, Unicode and unbounded inputs are refused.

The resulting record preserves the complete packet, reviewer provenance, decision
and synthetic marker. It does not mutate the draft or record posting approval.
The existing packet supports a qualified single-station temperature comparator;
this addition does not qualify more sources or graphic types.

`joint_media_review_status` requires the review fingerprint from **separate trusted
retention**, independently current packet inputs, and the original reviewer's
current principal. Never use the submitted record's own hash as the trusted
expectation. Recomputed hashes alone cannot authenticate a decision. An editor or
publisher may review; a different subject or a reviewer whose role has become
viewer cannot reuse the decision. A refreshed login preserves original provenance.

Changes to text, revision, evidence, policy, image, renderer, template or alt text
invalidate current acceptance. Editing A to B and back to A remains obsolete after
the revision advances. Readback distinguishes accepted, rejected, needs_changes,
obsolete, invalid and reviewer_unavailable. Incompatible future review contracts
must advance the record schema version and refuse earlier versions.

This is a pure local helper with no I/O, provider call, authentication adapter,
durable journal or production attachment. Both publication approval and production
attachment authorization are always false. A `Principal` must come from a trusted
adapter; constructing one is not authentication. Hashes do not prove human
attention, source truth or semantic agreement. Tests use supplied synthetic
decisions and structural PNG fixtures, not human ratings or rendered visual QA.

Next: retain decisions and exact assets immutably, then implement the attachment
revision and authenticated review interface against an explicitly chosen production
authority. Define attachment effects on existing text checks and publication
intents before any draft mutation. Gist remains the production store today.
