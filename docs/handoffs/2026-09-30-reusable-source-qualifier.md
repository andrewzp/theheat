# Reusable source qualifier in novelty memory

A factual checker can classify the standalone source label `model-estimated` as
an era anchor. Once that phrase enters novelty memory, later drafts can be rejected
for repeating a necessary scientific qualification. Supplying the same entry in
the writer's one-use anchor list can also discourage honest source labeling.

The memory layer now recognizes only that complete two-word qualifier, including
case, spacing and hyphen variants. It omits those entries from the writer's novelty
context, ignores them when checking era/peer reuse, and avoids adding new ones to
those novelty lists. Existing stored entries and all shipped text remain intact.

Longer substantive expressions containing the qualifier still participate in
normal reuse detection. Full-tweet duplicates and framing reuse retain their
existing behavior. The exemption grants no factual pass: scientific gates, strict
claim extraction and the required model check still run. A returned factual
rejection remains a rejection. Synchronous and batch checks share this behavior.

The tests use synthetic text and explicit offline provider fixtures. They cover
legacy preservation, new recording, exact qualifier variants, genuine repeated
anchors/comparisons, complete tweet duplicates and both provider acceptance and
rejection. These fixtures do not adjudicate a historical draft or measure improved
copy, operating cost or provider reliability. Publishing remains paused.
