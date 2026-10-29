# Source product and serving-leg contracts

`src/data/source_product_contracts.py` extends the advisory source inventory one
level down. For every wired collector (and the leaderboard) it lists each product
or serving leg the code can use: its parent collector, chain, role (primary,
alternate route, alternate product, witness, reference, component, corroboration,
cache, retired or unresolved), provider, data kind, health keys, geographic, time
and unit limits, provenance, any code request bound and the claim restrictions
already in force.

`product_contract_document()` returns a separate versioned export
(`theheat.source-product-contracts/v1`). The v1 registry and its dashboard JSON
are unchanged; nothing is added to old registry rows.

What the contracts do not do:

- They grant no claim permission, activation, source qualification or production
  availability.
- Each restriction is either advisory (only the accepted registry limit states it)
  or enforced by named checks scoped to the products they actually see. A product
  outside every scope keeps the restriction with enforcement `unresolved`. For
  example, the GHCN history qualification covers the GHCN legs only; CO2, OpenAQ,
  CO-OPS and Snow Today have no product-specific record check, and their current
  scientific gates are unchanged. Each export row carries
  `restriction_enforcement`, and the unresolved products are listed in
  `unmet_criteria`.
- Provider cadence, quota, reuse rights and cost are `null` for every product.
  A configured collection rule is not a provider promise, and a request bound is
  not a spending cap.
- One collector is at most one source, however many products it reads. Legs that
  reuse one upstream product through different collectors count once. The
  leaderboard and the temperature alerts both read the same best-match daily
  maximum forecast, so they are one group; NIFC WFIGS incidents and the GDACS
  subtype witnesses are other examples (`shared_upstream_groups`).
  `max_independent_source_count()` applies both rules. It is an upper bound only:
  independence between the remaining groups is `not_established`.
- `serving_disposition()` never names a served product from a run status alone.
  Evidence is a runtime leg label or explicit served product IDs.
  `serving_disposition_from_run_entry()` reads that evidence from an actual run
  entry: the runners' `served via <leg>` and `served last-good (...)` wording, and
  the air-quality runner's own lane availability.
  - The one inference allowed is an unlabelled success when a single wired,
    unlabelled primary exists for the health key. Runners record every labelled
    alternate or retained serving as degraded, so that success can only be the
    primary. Anything else stays `null`.
  - A retained last-good value is reported with `retained_not_fresh`, never as a
    fresh station reading.
  - An alternate, witness or cache serving is degraded service, not primary
    recovery, and no status, empty result or static contract establishes
    operational recovery.
- Model, reanalysis and satellite products cannot be relabelled as station
  observations: each provider is bound to the data kinds and product namespace it
  can supply.

The synthesis runner's two derived legs are listed separately: the
fire/drought/heat overlap, and the CRW DHW / regional SST anomaly pairing. The
pairing keeps each component's own date and footprint; a configured association
is not a shared footprint.

`decode_product_contract_document()` validates a detached export. A matching
digest only binds bytes. The rows must decode to the supported finite inventory
with valid kinds, parents, health keys, restrictions and scoped enforcement.
`missing_work`, `unmet_criteria` and the upstream groups are recomputed from those
rows, so clearing them and rehashing is refused. Unknown versions or data are
refused, never coerced.

Retired and unresolved legs stay listed in `missing_work` with their disposition.
Importing the module or building the export reads no adapter modules, network,
environment, credentials or files.

When a collector gains, loses or renames a leg, or a check changes scope, update
its rows and run `tests/test_source_product_contracts.py`. The tests check every
code reference, enforcement function and runtime leg label against the actual
source, without executing an adapter.
