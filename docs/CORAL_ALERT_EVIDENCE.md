# Coral heat stress and alert classifications

The ERDDAP backup supplies a DHW point sample. It does not fetch HotSpot or BAA.
NOAA's alert categories require paired HotSpot/DHW evidence; the seven-day BAA
product is a separate composite. DHW alone cannot determine even “No Stress.”
See [NOAA's alert definitions](https://www.coralreefwatch.noaa.gov/product/5km/index_5km_baa-max-7d.php).

The backup therefore retains its DHW measurement and threshold tier while marking
the alert classification unavailable. Writer evidence distinguishes its grid point
from the primary regional virtual-station statistic. Conflicting legacy labels
are retained for review but fail the current pre-writer boundary. Recognizable
unsupported alert labels also fail before a paid factual check; plain DHW or
unknown-status statements still require every normal check.

Primary supplied labels remain supplied labels. This change does not validate
their underlying source packets, promote heritage categories, establish observed
bleaching or qualify combined marine stories. It adds no source or model request.
