# Completing automatic alerts recovery

The existing source-health sentinel can request one alerts cycle when retained
alerts history is stale and no bot run is active. Only its first scheduled main
run may do so. It supplies `automatic_only=true` and its numeric run ID; these
inputs alone grant no approval or permission to send.

The bot's separate `automatic-catchup-proof` job has read-only workflow metadata
access and no Gist, model, X or other provider credentials. It requires GitHub's
bot actor and triggering actor, the first main bot attempt, and an automatic-only
alerts request. It reads at most two same-repository metadata responses: the
scheduled sentinel parent and that parent's first-attempt jobs. Both responses
are bounded to 64 KiB, with no retry, redirect or pagination. Declared lengths
must match the received bytes; chunked responses must terminate completely with
the empty trailer section. Nonempty trailers are explicitly unsupported and held.
Ambiguous or unknown framing is held. It requires the
same source revision, a parent created within 30 minutes, and one successfully
completed catchup job and dispatch step with consistent timestamps, normalizing
documented explicit UTC offsets. The dispatch command has its own conditional
step: a decision not to dispatch is skipped, never a successful dispatch. Other
sentinel reconcilers may fail independently.

This is a match to scheduled-dispatch metadata under GitHub's built-in actor
context. It is not universal caller authentication, credential fencing, a
transactional state store or proof of delivery. Unknown/malformed/incomplete
metadata yields `eligible=false`; manual dispatch, reruns and a caller-supplied
parent label cannot substitute for the checked context. A slow queue or a main
revision change can also hold completion conservatively.

For an admitted automatic recovery, the existing post-collection sender waits
the same 65 seconds, checks its context again, and starts the unchanged due
sender once. It supplies no draft ID, text, cached state, approval or bypass.
The due sender reloads current state and applies its existing source, revision,
policy, approval, expiry, spacing, daily limit and uncertain-send protections.
The one-candidate/sample, no-revise and no-refill limits remain required.

The existing `THEHEAT_POST_COLLECTION_SENDER` flag still controls completion.
Normal scheduled completion is unchanged. Failed proof or a changed/pause
context does not start another sender, collect again, retry a send or promote a
manual draft. A separately eligible draft can still be considered by a later
ordinary sender under its normal rules; this change promises no delivery SLA.

Source qualification, model checks, a new automatic draft and an actual X receipt
must each be observed separately. Offline fixtures and a merged workflow do not
establish any of those production outcomes.
