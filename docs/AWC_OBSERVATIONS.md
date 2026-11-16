# Observed airport comparisons

This optional source compares two named reporting airports in different countries
at the same UTC observation time. It reports measurements and context, never TAFs,
TREND predictions, a world ranking, a record, a climate cause or human impacts.
A difference of at least 60°C is an editorial nomination rule, not a rarity test.
The normal critic can still reject the story as uninteresting.

The source is OFF unless `THEHEAT_AWC_OBSERVED_CONTRAST=1`. It also requires
observed-only mode, the critic, exactly one candidate/sample and no revision or
refill. The ordinary alert collector can nominate one pair. The `metar_report`
mode nominates only this source and requires explicit automatic-selection intent;
it does not invoke the sender. A model PASS or a saved draft is not an X receipt.

The [NOAA Aviation Weather Center API](https://aviationweather.gov/data/api/)
provides a bulk METAR cache and reporting-station catalogue. Names must explicitly
identify airports, with matching ICAO identity, country and coordinates. Mountain
and offshore stations are not silently called airports. Missing, conflicting,
duplicate, maintenance-flagged, future or more-than-two-hour-old observations are
held. Unknown values are not zero. An older exact target can remain usable after
a newer report arrives; it must still be present and unchanged in the historical
query.

Only the observed temperature group is interpreted. The NWS documents
[NOSIG as a TREND forecast](https://www.weather.gov/asos/METAR.html), meaning no
significant change expected. It is not evidence of a broken thermometer. AWC's
`no_signal` field is not used as an observation-failure flag. Raw remarks and
forecast text never enter the writer's evidence.

Every live source read uses a fixed NOAA host, bounded responses, one physical
attempt and no redirects. Before writing, admission and sending, an independent
historical METAR request with `taf=false` and a fresh station catalogue must
confirm the selected observations. Retained hashes bind a finding; they do not
prove its truth. The citation names the target date/time and two-hour historical
window. The provider's documented default raw output excludes TAFs. Provider
history retention limits still apply.

The writer keeps its existing prompt and runtime models. The exact source URL is
reserved inside the existing 200-scalar copy ceiling. The sentence must preserve
the two airport/country scopes, temperatures, difference and common UTC time/date.
All required model checks, current policy/revision/epoch, approval delay, spacing,
daily limits and uncertain-send protections remain mandatory. No graphics are
automatically attached by this source.

The final text must contain its one exact target citation. If the generic link
formatter cannot fit that citation, the uncited body is held; it cannot become
an automatic post. Historical XML with duplicate quality flags is also held,
including repeated maintenance flags that happen to agree. A declared report
type cannot borrow an unrelated retained source bundle.

## Optional completion of scheduled delivery

`THEHEAT_POST_COLLECTION_SENDER=1` enables one extra sender pass only after a
successful, genuine first-attempt scheduled `alerts` or `both` run on main. It is
OFF by default. A catch-up must first have its durable reservation confirmed.
The same existing environment must show automatic publication/autoship enabled,
production unpaused and the one-candidate/sample/no-refill profile.

The helper waits 65 seconds, rechecks its context and starts the unchanged due
sender once. That child reloads current Gist state; the helper passes no text,
draft selection, approval or bypass argument. A failed child is not retried.
Manual dispatch, PR, rerun, tag, different repository/workflow, report generation
and sender-only modes cannot use this path. GitHub variables are captured by a
workflow's environment; changing one does not rewrite an already running process.
The sender's existing saved-state and publication checks remain independent.

Deploying either feature does not activate it or prove real publication. Record
activation, runtime observation, an actual X receipt and reader feedback separately.
