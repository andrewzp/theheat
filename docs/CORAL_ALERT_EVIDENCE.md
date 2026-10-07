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
bleaching or qualify combined marine stories.

The point backup validates the documented [DHW dataset](https://coastwatch.noaa.gov/erddap/info/noaacrwdhwDaily/index.html)
once per collection, then pins every point query to its declared latest product
time. It checks exact CSV columns/units, a single row, finite valid values, grid
coordinates and chronology. Metadata is limited to 1 MiB and point responses to
8 KiB; responses close on failure. Metadata failure stops this backup collection.
The existing seven-day backup allowance, primary-first routing and one attempt
per backup request remain. This adds one metadata request per backup collection
and no model request.

Source precision is retained before threshold detection: 3.96 does not cross 4
through rounding. Receipts retain product, time, point, value and response identity
without putting full source files in prompts. Missing or conflicting receipts
block writer/checker use. Primary and legacy data are never silently upgraded.

Receipts validate binding, not upstream authenticity. A coherently substituted
receipt cannot be authenticated without retained source bytes or a separate trust
anchor. Any receipt change is different evidence and invalidates prior review and
approval. Full source archival, primary-station qualification and combined-story
qualification remain separate work.
