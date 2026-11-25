# River observation dates and units

The USGS gauge parser qualifies the timestamp of each selected station reading.
A fresh reading at one station cannot make an older station reading current.
The existing selection of the last value in each series is unchanged; an invalid
last value is withheld rather than replaced with an earlier value.

An eligible reading declares USGS quantity `00065` and unit `ft` in its returned
variable metadata. This quantity check happens before threshold metadata is
requested, so a metadata outage cannot hide an already invalid returned quantity.
Requesting gauge height does not label a different returned quantity.
A metre, discharge or unknown-unit series is withheld; valid peers
remain available. If all positive readings have unsupported quantities or units,
the source reports a schema failure and cannot use the outage/model fallback.

The NOAA minor flood threshold must independently declare `flood.stageUnits`
as `ft` and contain a finite number. Unsupported or missing units and nonfinite
thresholds follow the existing strict metadata/schema failure policy; they are
not converted by guesswork or treated as outages. Numeric spellings of the
source's missing marker, such as `-9999.0`, mean the same absence as `-9999`.
Missing thresholds remain unknown and cannot produce a flood event.

An eligible reading also has a finite positive gauge height and an explicit ISO
datetime with a known UTC offset. Missing, malformed, naive, unknown-offset
(`-00:00`) and future timestamps are withheld. The existing two-calendar-day
allowance is measured against one UTC clock captured after fetching observations
and threshold metadata. This is a calendar-day allowance, not a 48-hour promise.
Valid stations survive a response containing other ineligible stations.

The reading, flood event, writer bundle and existing daily event ID use the
measurement's UTC date. Fetching the same measurement on a later day does not
make a new daily identity. This does not establish a full daily observation
interval or qualify a flood's duration, extent or impacts.

An empty provider result remains empty. If all positive readings are held for
time, the source reports a failure. Stale-only failures retain the existing
clearly model-labelled fallback behavior. Missing, malformed and future times
cannot be hidden by that fallback. Model discharge is never an observed gauge
height. The river story route retains its existing manual-review policy.

The parser is included in the editorial policy identity. A parser change makes
old checks and approval obsolete without rewriting retained content or delivery
receipts. Deployment does not authorize publication or source activation.

These checks validate the declared gauge-height quantity and feet, but do not
validate gauge datum, USGS-to-NWPS station mapping or measurement QC; those
remain separate qualification questions. This also does not migrate the
legacy USGS WaterServices endpoint. Consult the official
[WaterServices retirement notice](https://waterdata.usgs.gov/blog/api-waterservices-decom)
before planning that migration; do not treat parser tests as current provider
availability evidence.
