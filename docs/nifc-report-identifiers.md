# NIFC report identifiers and saved-draft tiers

NIFC WFIGS reported incident size is manual-only. A reported size is not a
measured burn perimeter, rate of spread or continuous burning interval. An
incident's origin state does not describe its footprint or an international
border crossing.

Current candidates and saved-draft tier keys use one full source identity:
NIFC WFIGS, its incident-size product, wildfire type, identifier kind and the
complete normalized identifier. `UniqueFireIdentifier` remains preferred over
`IrwinID`; invalid preferred values do not acquire a fallback identity. Case is
preserved. The key is a bounded SHA-256 digest of that canonical identity, and
the candidate ID also includes the reported-size tier. Names and origin-state
revisions do not create another identity.

The tier watermark advances only after a draft is successfully saved. It does
not establish approval, sending or an X publication. Same-tier reports remain
suppressed; a higher reported-size tier can be considered under the existing
eligibility, one-candidate budget and required checks. The loaded Gist snapshot
is not a distributed transaction or lock.

No historical rows or bare tier keys are migrated. A visible old bare key or
matching legacy event is ambiguous between identifier kinds and holds the new
candidate before writing. Missing or malformed relevant tracking also holds.
These holds contribute to the existing source admission-hold count and a fixed
saved-tier diagnostic, rather than appearing as a successful empty feed. An
empty initialized tier map with no matching retained history can admit a new
qualified identity; this is not proof of a complete external job inventory.

Exact older qualified report snapshots remain readable as prior report context.
Their packet and projected facts must still match. This compatibility reader is
used only by memory; current admission and checking reject old candidate IDs.
Unqualified or changed snapshots cannot establish report identity. Historical
publication classifications, unresolved deliveries, approvals and exact verdict
cache scopes are unchanged. No unknown attempt is resent by this repair.

The regression journey uses invented HTTP, SDK and Gist responses through real
source, queue, check, save, merge and JSON read/write code. Its pending drafts and
fixture receipts are not real weather, model-quality evidence or X posts.
