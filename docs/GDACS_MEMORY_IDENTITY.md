# GDACS report-series memory

`global_disaster` is the GDACS writer-input family, including explicitly labeled
subtype witnesses. A display country/name and a shortened candidate ID cannot
identify an event. Related memory for this family now requires an exact source
identity corroborated by the current bundle's raw source fields and unique fact
labels. The currently supported identity is the GDACS GeoRSS event type plus its
full source event ID, with the fixed served product/leg/URL and matching candidate
ID. Underscores and case are preserved; no three-token prefix is used.

A shared GDACS event ID is a **source report series**, not independent proof of
one physical incident. The writer receives `source_report_series` with a scope
qualification, earlier report context and matching published texts. It receives
neither an `ongoing_event` nor `recent_tweets_same_event` from this weaker identity.
Publication-poll dates and `days_running` are not projected as event duration.
Source-issued changes of country or ingest ID can retain this report history;
different source IDs or hazard codes cannot share it.

The small versioned identity is retained in publication-memory snapshots and
restored through the real memory recorder. These miniature restored bundles are
memory projections only, never a substitute for source evidence or scientific
revalidation. Missing, malformed, contradictory or legacy identities are not
inferred from names, countries or old candidate IDs. Unsupported subtype witness
identities remain unqualified for related-event memory until they have their own
reader. General country/feed/category history remains available as general
context, distinct from evidence of the current incident.

The strict physical `EpisodeContext` resolver and its currentness checks remain
separate and unchanged. The optional hazard-admission ledger stays default off;
this repair does not activate it, select another database, change source or
publication eligibility, weaken checks, or authorize a post. Other heat/fire/
cyclone/flood lifecycle acceptance remains separate P20 work.
