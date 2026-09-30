# GDACS RSS core-field containment

Previously, one item with missing or invalid core fields stopped the complete RSS
feed, including valid alerts elsewhere. The bounded parser now quarantines that
item before event creation, severity selection or freshness aggregation. Every
existing required field still has to pass; an explicit empty cyclone country
retains its narrow, source-defined meaning.

Diagnostics distinguish input items, structural passes and quarantines. Field
counts use a fixed vocabulary and never include item text or identifiers. A
multiply invalid item counts once as a quarantine and once per failed field.
Rejected selected alerts and unknown severity have separate counts; validated
alert counts never imply the missing items were harmless.

Any quarantine marks the result `partial_feed`. The runner reports the gap even
when the remaining valid items are all below the selected severity. Independent
publication-time withholding counts remain available. No malformed item can
freshen a stale feed through its timestamp.

Malformed XML, missing or empty collections, parser bounds, all-invalid feeds and
unusable overall publication evidence still fail. This is explicit core-field
containment, not a catch-all exception handler or qualification of every optional
field. Source endpoints, fallback attempts, event identity, required checks and
publishing settings are unchanged.

Synthetic tests cover each core field, malformed Green and Red peers, unknown
severity, mixed freshness failures, input-order invariance, all-invalid failure,
and exact runner enqueue counts. Existing error classification remains compatible.
A privately retained valid feed can confirm unchanged selected identities; it
does not demonstrate an observed malformed-item incident, global recall or quality
improvement. Primary JSON request qualification remains separate work.
