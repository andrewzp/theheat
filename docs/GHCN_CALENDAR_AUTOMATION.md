# Observed calendar-date station records

The existing `record` and `record_low` labels can enter automatic text review for
qualified observed GHCN calendar-date comparisons. A record label alone does not
establish this route. Generic records, forecasts, missing or inconsistent source
evidence and unresolved compact source references cannot use it.

Positive evidence must pass the existing full `noaa-ghcn-daily-v2` station-record
validator, including the selected day, station, reading, accepted QC, available
archive, cutoff and calendar-specific comparator. The saved type, source signal
and event must agree. Available accepted station history is not a certified
national record or complete observing history; the copy still needs its scope
and cutoff qualification.

The source requirement applies before paid selection, before automatic arming
and again at the publication boundaries. Publication keeps the existing separate
live station-archive reads and reconstructs the original observation and
comparator. Changed or unavailable source bytes stop the send; an earlier check
is not reused as a current-source pass.

This uses existing observed-only and automatic-publication/autoship controls.
It adds no activation flag, source endpoint, source allowance or model. Both
calendar signal names receive the existing automatic copy-budget hint; this hint
grants no review or approval. The final complete text remains limited to 200
Unicode scalars without truncation. The existing 90-minute delay, 36-hour framing
ceiling, current required checks and critic PASS, revision and epoch bindings,
deduplication, city/country/category controls and routine candidate/sample limits
remain. These timing limits can hold a delayed source even when its data is valid.

Other record products remain available for their existing manual handling. Fire,
human-impact and forecast policies do not change. An edit invalidates the old
review and approval; unresolved deliveries remain unknown and cannot be resent.

The operating publication target is a goal to measure with actual X receipts.
This eligibility change does not establish current source availability, global
coverage, a successful production record post or a sustained posting rate.
