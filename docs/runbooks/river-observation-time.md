# River observation dates

The USGS gauge parser qualifies the timestamp of each selected station reading.
A fresh reading at one station cannot make an older station reading current.
The existing selection of the last value in each series is unchanged; an invalid
last value is withheld rather than replaced with an earlier value.

An eligible reading has a finite positive gauge height and an explicit ISO
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

This qualification does not validate gauge datum, units or USGS-to-NWPS station
mapping; redesign those boundaries separately. It also does not migrate the
legacy USGS WaterServices endpoint. Consult the official
[WaterServices retirement notice](https://waterdata.usgs.gov/blog/api-waterservices-decom)
before planning that migration; do not treat parser tests as current provider
availability evidence.
