# Local physical episode preparation

The explicit local NHC lane retains parsed advisories in the existing immutable
PostgreSQL repository before detection. It joins qualified source identities to
durable episode revisions, then uses the existing cyclone detectors, intern,
evidence audit, bundle capture, memory and writer request builder. It does not
call a model, enqueue callback-free cyclone drafts or publish anything.

`CycloneEpisodeLane` can be passed explicitly to the existing
`_process_cyclone_source` NHC boundary. There is no environment flag, production
backend switch or automatic enrollment. Without that argument, the source runner
and its success callbacks follow their existing path.

## Identity and evidence

- Only full NHC AL/EP identities with a year and numbers 01–49 qualify. Name-only,
  yearless, internal, test and investigative identities remain retained but held.
  This range includes potential tropical cyclones; identity is not storm status.
- A parsed application snapshot is not a complete original-response archive.
  Original advisory/product time strings and parsed-row/forecast-point hashes
  are retained. The optional parser observer adds no fetch or retry.
- Forecast membership requires a known complete forecast text before the legacy
  8,000-character cap, matching separate product issuance and exact advisory
  number including any suffix. Unknown or mismatched products cannot acquire a
  forecast membership. A forecast threat is not observed impact or landfall.
- A cyclone does not become another episode when its supported forecast threat
  crosses a country border. Different full IDs, years, basins and authorities are
  not merged by names, nearby tracks or a language model.

## Durable preparation and replay

`CycloneSupplySession.capture` freezes a caller-fixed run ID, capture time,
producer revision and complete typed inventory. `read(expected_sha=...)` resolves
that exact retained run. Missing or malformed storage has no live-source fallback.

`PhysicalEpisodeSession.apply_retained_run` requires a fixed operation ID/time,
the exact retained run hash and an expected head for every qualified episode.
It appends each revision and its operation result in one transaction under an
episode lock. The indexed head read is bounded. Repeating an identical operation
is safe; changing its content is refused. Lost commit acknowledgment triggers one
exact read reconciliation, never another source acquisition.

`prepare_episode_requests` re-resolves the requested current head, exact retained
members and explicit episode memory context. It constructs the real audited
writer request and verifies currentness again before returning it. Bound inputs
cannot fall back to coarse legacy event prefixes, region matches or news impact
matches. The result includes exact bundle, memory and policy hashes. These are
preparation identities, not model grants, posting receipts or settled costs.

An opportunity has a stable ID derived from its episode and meaningful scientific
claim. Detection is not consumption. Ordinary advisories may rebuild a currently
eligible opportunity under that same ID after a crash, using current evidence.
The historical `seen_opportunities` field is an observed-identity set only.
It does not suppress an unconsumed request or imply a post. Weakening, stale
forecast points, conflicts and other ineligibility cannot blindly carry an old
claim forward. Success/consumption enrollment remains a separate integration.

Source conflicts, late evidence needing new derivation, and unresolved relationship
proposals hold current consumers while preserving prior source and story evidence.
Split/merge proposals hold all named expected heads atomically; they do not move
members or combine old same-event memories. A bounded overflow retains the complete
source inventory and holds the episode instead of truncating assigned membership.

## Scope still open

The P18 heat prepass can retain exact station grouping proposals, including
cross-border and transitive proximity groups. These remain unconfirmed; existing
aggregate scientific holds and editorial station caps still apply. Fire/flood
report relationships remain retained unadjudicated assertions, not physical
incident identities or summed impact totals.

Other authority aliases, positive heat/fire/flood lifecycles, reviewed split/merge
resolution, raw-product archives, cyclone callbacks and urgent/shared generation
enrollment, production coordination and measured editorial outcomes remain open.
This local slice is not the complete physical-event or global-coverage upgrade.
