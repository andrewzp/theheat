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
  availability. Each restriction says whether an existing check enforces it or
  only the accepted registry limit states it.
- Provider cadence, quota, reuse rights and cost are `null` for every product.
  A configured collection rule is not a provider promise, and a request bound is
  not a spending cap.
- One collector is one source, however many products it reads. Legs that reuse
  the same upstream product through different collectors (for example NIFC WFIGS
  incidents, or the GDACS subtype witnesses) also count once.
  `independent_source_count()` applies both rules.
- An alternate or witness serving is degraded service. `serving_disposition()`
  never reports the primary as recovered from it, and never establishes
  operational recovery from a run status, an empty result or a static contract.
  An unlabelled success is reported as ambiguous where unlabelled alternate routes
  exist.
- Model, reanalysis and satellite products cannot be relabelled as station
  observations: each provider is bound to the data kinds and product namespace it
  can supply.

Retired and unresolved legs stay listed in `missing_work` with their disposition.
Unknown provider terms and unverified availability stay listed in
`unmet_criteria`. Importing the module or building the export reads no adapter
modules, network, environment, credentials or files.

When a collector gains, loses or renames a leg, update its rows and run
`tests/test_source_product_contracts.py`. The tests check every code reference and
runtime leg label against the actual source, without executing an adapter.
