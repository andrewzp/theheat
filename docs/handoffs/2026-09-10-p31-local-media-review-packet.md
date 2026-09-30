# P31: exact local media review packet

`src/media/review_packet.py` connects the existing qualified comparator adapter and
renderer manifest to an exact draft revision. It performs no filesystem, network,
model, subprocess or production-state operation. No publishing adapter or current
dashboard path imports it. This slice supports one qualified GHCN comparator;
multi-bundle trajectories need a later relationship contract.

`build_media_review_packet(draft, *, expected_draft_identity, editorial_policy,
graphic_spec, renderer_manifest, png_bytes)` receives independent current context.
The caller retains the expected draft identity from the review request and
supplies the current policy; neither is trusted merely because it appears in an
edited packet. The function validates existing draft identity and the scientific
adapter, requires exact equality with the draft's retained bundle, checks render
metadata/asset identities and binds the actual supplied PNG bytes and generated
alt text. JSON inputs are each bounded to 1,000,000 UTF-8 bytes; PNG bytes to 8 MiB.

PNG signature, IHDR, CRC, supported header fields and template dimensions are
checked. This is a structural check, not a complete image decoder. The filesystem
adapter must separately verify SVG/PDF bytes and safe local paths; those bytes are
not passed to this pure function. The input JSON and alt-text asset fingerprints
must match the existing renderer's serialization, and the PNG must match its hash.
The manifest's remaining asset hashes are bound to the packet.

The packet contains draft/event/revision/policy bindings, graphic/render bindings,
media dimensions/length/hash/alt text and an overall fingerprint. It always retains
`claim_agreement_status="unreviewed"` and `publication_approved=false`, including
for synthetic examples. Hash agreement does not prove source authenticity,
scientific text/plot agreement or editorial approval.

`media_review_packet_is_current(packet, draft, **current_inputs)` rebuilds the
expected result from independent current inputs and checks the entire packet.
Text edits, A-to-B-to-A revisions, changed evidence, policy or rendering invalidate
earlier packets. Editing a packet and recomputing its digest cannot confer current
status. Numeric schema fields retain their strict integer types. Inputs are not
mutated, and validation errors do not include private text.

Behavioral regressions use synthetic qualified station history and structural PNG
headers. A separate local integration check consumed an existing real rendered
synthetic comparator and verified all five cached asset hashes before building the
packet. That check is compatibility with an existing render, not a new renderer or
visual-quality assessment. Follow-up work is an immutable private review package,
then reviewed storage/authority/desk integration and joint semantic approval.
