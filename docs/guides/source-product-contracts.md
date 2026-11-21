# Source product and serving-leg contracts

`src/data/source_product_contracts.py` extends the advisory source inventory one
level down. For every wired collector (and the leaderboard) it lists each product
or serving leg the code can use: its parent collector, chain, role (primary,
alternate route, alternate product, witness, reference, component, corroboration,
cache, retired or unresolved), provider, data kind, health keys, geographic, time
and unit limits, provenance, any code request bound and the claim restrictions
already in force.

`product_contract_document()` returns a separate versioned export
(`theheat.source-product-contracts/v4`). The v1 registry and its dashboard JSON
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
- Provider fields are `null` where documentation remains unknown. Exact named
  AWC, NIFC, two GPM Late daily legs and two GHCN legs carry dated primary-document facts with source URLs and snapshot
  hashes. A `partial` fact stays in `unmet_criteria`; only its exact documented
  product/field can leave that list. Costs remain unknown. A configured collection
  rule is not a provider promise, and a request bound is not a spending cap.
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

`decode_product_contract_document()` validates a detached v1, v2, v3 or v4 export. A matching
digest only binds bytes. The rows must decode to the supported finite inventory
with valid kinds, parents, health keys, restrictions and scoped enforcement.
`missing_work`, `unmet_criteria` and the upstream groups are recomputed from those
rows, so clearing them and rehashing is refused. Unknown versions or data are
refused, never coerced.

Retired and unresolved legs stay listed in `missing_work` with their disposition.
Importing the module or building the export reads no adapter modules, network,
environment, credentials or files.

## Dated provider documentation

The reviewed facts are scoped to eight legs, not whole providers:

| Product | Documented cadence | Remaining limits |
| --- | --- | --- |
| AWC METAR cache and historical API | Cache every minute; individual reports usually hourly. | The API's 100 requests/minute does not establish cache quotas or guaranteed capacity. |
| AWC station catalogue | Cache daily. | Cache quota unknown; this reference is not a temperature reading. |
| NIFC WFIGS current incidents, including the newsworthiness leg | IRWIN synchronization every five minutes; fall-off hourly. | The declared 2,000-row default is not a rate quota, census or measurement clock; other query modes remain unqualified. |
| GPM IMERG Late daily V07, OPeNDAP and HTTPS grid legs | The derived daily file follows its last half-hourly input; its target is no earlier than 14 hours after the UTC day closes. | A latency target, not an availability guarantee. Quotas and costs remain unknown; S3 and Final are outside this documentation tranche. |
| GHCN-Daily differences and station histories | The integrated dataset receives daily updates and weekend reconstruction. | Dataset processing is not each station's reporting clock or guaranteed access/freshness. Values and QC flags can change. Reuse rights, quotas and costs remain unknown. |

Sources: [AWC API documentation](https://aviationweather.gov/data/api/) and the
[exact NIFC item metadata](https://www.arcgis.com/sharing/rest/content/items/4181a117dc9e43db8598533e29972015?f=pjson),
with its linked layer. Both NIFC legs share one upstream product.

The [exact NASA daily collection document](https://cmr.earthdata.nasa.gov/search/concepts/C2723754859-GES_DISC.umm_json)
identifies `GPM_3IMERGDL`, version `07`, DOI `10.5067/GPM/IMERGDL/DAY/07`.
Its daily value is a mean rate scaled to mm/day from valid half-hourly inputs;
the period does not establish 48 valid samples or a gauge accumulation. The two
documented GPM delivery legs share this upstream product and count once.
These facts establish neither the currently configured URL's correctness nor
access, scientific eligibility or recovery. No source transport is changed.

The [GHCN-Daily product documentation](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily)
describes integrated daily updates, weekend reconstruction and continuing value/
QC revisions. Version4 records only that dataset-processing cadence for the exact
daily-difference and station-history products. It establishes neither a station's
reporting interval nor publication-time QC, guaranteed updates or endpoint health.
The provider's general cloud-migration notice is not a diagnosis of a particular
failed request. No replacement URL, source-age/QC rule or reuse clearance follows.

Reuse evidence remains partial. The [NWS policy](https://www.weather.gov/disclaimer)
distinguishes its own material from third-party inputs; it does not clear every
international source or map. NIFC's item publishes a disclaimer without identifying
an affirmative license for every contribution. Neither finding grants a claim,
activation, current access, availability or zero-cost assurance.
The [GPM data policy](https://gpm.nasa.gov/data/policy) describes processed data as
freely available and asks for dataset-specific credit. This tranche retains
partial reuse evidence: it does not clear account entitlement, third-party maps,
logos or imagery, or infer zero operating cost.

`checked_at` records the UTC documentation review time, not a provider update or
weather observation. The readiness consumer holds a documented component when any
review postdates its assessment cutoff. Explicit exports `schema=LEGACY_SCHEMA`,
`schema=PREVIOUS_SCHEMA` and `schema=GPM_SCHEMA` preserve complete v1, v2 and v3
documents byte-for-byte, including their original dates and unknown fields.
Decoding them does not insert later facts. Version3 adds only the two named GPM
legs; the default version4 adds cadence only for the two named GHCN legs.
Unknown schemas, altered facts/references
and falsely cleared gaps are refused even if their digest is recomputed.

When a collector gains, loses or renames a leg, or a check changes scope, update
its rows and run `tests/test_source_product_contracts.py`. The tests check every
code reference, enforcement function and runtime leg label against the actual
source, without executing an adapter.
