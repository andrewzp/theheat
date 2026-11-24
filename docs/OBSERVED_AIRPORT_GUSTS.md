# Observed airport gusts

`THEHEAT_AWC_OBSERVED_GUST=1` separately opts into `observed_metar_gust`.
The default is off. Ordinary alerts and the existing `metar_report` mode use
it; a deployed implementation does not itself change its operator setting.

This route admits one reported wind gust at a named airport, not a forecast,
sustained wind, daily maximum, record, regional maximum or impact report.
The current editorial screen is 50–100 knots inclusive. It conservatively
requires the same complete airport, observation-time, coordinate, maintenance
and temperature agreement as the existing airport-comparison reader, plus
agreement between decoded integral wind fields and one primary-body KT gust.
Other units, wind in remarks or TREND forecasts, duplicates, contradictory
reports and incomplete fields do not qualify. This subset is not a census of
global wind stations.

The [AWC product guide](https://aviationweather.gov/help/data/#metars) explains
observed METAR wind groups and gusts. The [AWC API documentation](https://aviationweather.gov/data/api/)
recommends its current cache files for bulk acquisition. Both enabled airport
profiles share one catalogue GET and one current-observation GET. They remain
one provider; this is not independent corroboration.

Before the writer, draft admission and publication, the exact station/report
at its saved UTC time is compared against a fresh historical API response and
station catalogue. A newer cache reading cannot silently replace it. Reports
must remain within two hours, including the one-minute automatic delay. A
changed or unavailable source, disabled setting, changed review or policy,
obsolete publication authority or uncertain send blocks publication.

The draft must retain the complete airport, country, gust, observation clock
and UTC date. Supplied rounded km/h and mph conversions may make knots more
readable. It carries the exact historical source link before required safety,
factual and critic checks. The writer still makes one sample for the shared
single candidate slot, with no refill or revision loop; the automatic limit
remains 200 characters. Local checks supplement the required models, never
replace them.

At most three gust candidates are nominated deterministically by strength,
freshness and station ID. Retained gust drafts and prior uncertain attempts
prevent repeat spending for that station; routine spacing is 24 hours. These
rules identify a station report, not a physical storm. Temperature comparisons
keep their separate 24-hour format spacing. Existing per-type, country, daily
and spend controls continue to apply. This adds no automatic image route.

Offline fixture success proves integration and refusals. Actual source
qualification, model quality, X delivery and four useful posts per day require
runtime evidence. More ordinary executions can increase total provider spend;
a single-sample limit is not a hard monthly ceiling or a reconciled bill.
