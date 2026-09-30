# Deliberate qualified GDACS RSS route

The production path began with an unqualified MAP JSON request, then used RSS
when that failed. The RSS adapter had stronger current-episode and publication
checks than the JSON path. A future JSON HTTP200 could therefore bypass those
checks, even though HTTP success does not establish suitable evidence.

Use the existing qualified GeoRSS product directly and withdraw MAP from the
production call path. The legacy JSON decoder remains only for compatibility and
replay; no production caller reaches it. GDACS documents the public GeoRSS
interface in [its guide, section 3.5](https://www.gdacs.org/documents/2025/GDACS_MHEWS_guide.pdf).
That documentation does not establish complete geographic coverage or entitlement
to every numeric claim carried in an alert.

Events keep their existing source product, source leg, identifiers and raw
provenance. All current-episode, freshness, malformed-peer, unknown-country and
scientific checks remain. Diagnostics explicitly identify the configured limited
GeoRSS product and withdrawn unqualified MAP route. Health stays degraded/limited;
this release does not turn the badge green or claim MAP recovery.

RSS response reading now streams bounded chunks and stops above the existing
2,000,000-byte decoded-body ceiling. Strict incremental UTF-8 decoding preserves
the BOM and split characters, and stops on invalid bytes without replacement.
The response closes on success, body errors or oversize input. The shared HTTP
helper also closes discarded streaming responses before its existing status
retries and on final HTTP errors. Successful streams remain the caller's
responsibility. Header retry limits, source timeout and witness eligibility are
unchanged; body failures do not create another retry loop.

A successful empty qualified selection is distinct from source failure and never
invokes a subtype witness. Existing strict-only USGS/NHC/JTWC witnesses remain
eligible for transport/outage failures, with their source identity preserved.
Malformed, stale, inaccessible or misconfigured inputs cannot be hidden by a
witness. Non-strict transport failure retains its existing empty-list behavior.

Offline regressions exercise actual source routing and runner diagnostics,
including a tempting JSON200 response that must never be requested, exact body
limits, gzip decoding, split Unicode/BOM, stream cleanup, interrupted bodies and
status retries. Retained-source replay compares exact selected events/provenance
and qualification diagnostics at the capture clock, while removing one obsolete
request. Such replay is not a new live observation, source recall study, model
quality evaluation or cost-savings measurement. Publishing and runtime model,
sample, billing, backend and source-cadence settings remain unchanged.

Local validation: 26 new cases, 274 focused cases and 5,115 full offline Python
tests pass, with 41 paid cases excluded. All 294 dashboard tests/build, Ruff,
mypy160, generated contracts and frozen historical regressions pass. Required CI
and manual policy deployment are separate release steps.
