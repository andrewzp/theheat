# NIFC report history in writer memory

Qualified NIFC WFIGS incident-size reports retain prior publication context under
their exact official incident identifier. A change in the internal size tier
changes the candidate ID without turning it into a different report series.
Names, regions, countries, prefixes and sensor detections never supply this key.
The selected `UniqueFireIdentifier` and fallback `IrwinID` use separate namespaces;
the code does not infer aliases between them.

The existing pure source audit must verify the entire current report bundle:
record, size, attribution, clocks, origin, units and derived facts. A missing or
contradictory report has no source-series history. The pre-existing exact-candidate
publication history remains limited to prior published text, with no source or
physical-episode authority. General country/category history stays separate.

The writer receives `source_report_series`, containing prior published text and
reported region/country with an explicit claim limit. It does not receive a
physical `ongoing_event` or a duration. An incident report is not a measured burn
perimeter, proof of continuous burning, fire spread, a growth rate or combined
impacts. A changed origin-state label does not establish border-crossing fire.
All required current checks still apply to new text.

Publication snapshots retain the exact report inputs needed by the same offline
audit after JSON restore. An identifier alone cannot recreate source evidence.
This audit uses exact retained fields before the generic history reader can
fill missing values, coerce strings or discard malformed facts.
These NIFC snapshots are limited to 32 KiB using the state writer's compact,
ASCII-escaped JSON encoding. Oversize, unserializable,
legacy, unrecognized or changed inputs keep general publication history without
establishing a series identity. This limit does not change source qualification.
No data is downloaded to restore memory, and no historical identity is backfilled.

This reader does not authorize a draft, change the manual-only NIFC route, send a
post, select a backend, establish provider truth or activate episode collection.
GDACS report-series and resolved cyclone identities retain their separate rules.
