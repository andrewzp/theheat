# Thermal observations and publication memory

A FIRMS or NOAA HMS thermal detection is a sensor observation. Its source cell,
day, acquisition minute, or inferred region does not establish one continuing
physical fire, its duration, burned area, or a shared cause with other detections.

For an unbound `fire` bundle, writer memory therefore supplies no `ongoing_event`
or `recent_tweets_same_event`, including for a repeated source cell. Publication
recording retains the text, source event ID, general country/feed history,
category cooldown, framing and novelty history; it creates no physical ongoing
row. Existing stored rows remain intact and cannot grant thermal continuity.
Restoring retained publication metadata follows the same rule.

An explicit physical binding still requires the existing resolved, current
`EpisodeContext` and its validations. A missing or malformed context refuses;
it cannot fall back to the thermal observation path. Official perimeter bundles,
GDACS report-series memory, and other signal families retain their existing
behavior. These distinctions do not change source qualification, deduplication,
required checks, models, prompts, spending limits or publication controls.

Offline checks exercise invented CSV observations through the actual parser,
geocoder, source runner, evidence/queue boundary, publication recorder and writer
request, plus repeated-cell, legacy-row and JSON-restore cases. They establish
the local memory contract, not a physical incident or improved model output.
