# Regional SST source evidence

The regional SST adapter now keeps its source evidence through event creation and
review. Previously a primary-host reading could be rejected for missing provenance,
while the backup-host label alone could imply stronger evidence than the packet held.

The primary path validates dataset identity once per collection, sharing that result
across the 13 existing region requests. CSV parsing checks exact headers/units, one
UTC product timestamp, geographic bounds, duplicate cells and a complete rectangular
sample at the existing one-degree stride. Missing and physically out-of-range values
are excluded and counted. Malformed data and products outside the five-day window
remain failures, rather than reasons to silently switch hosts.

The native backup validates its internal product identity, global coordinate axes,
packed Celsius-anomaly encoding, masks and time against the selected filename. A
transport outage can use this backup; a successful below-threshold primary reading
is not replaced. Both paths retain the requested URL, response hash/size, retrieval
time, actual sampled bounds, valid/excluded counts and calculation method. Downloads
use fixed byte caps, socket timeouts, limited attempts and elapsed checks between
chunks; redirects and non-identity content encoding are rejected. This is not a
hard process-level wall-clock deadline against every possible stalled transport.

The evidence describes a sampled regional mean from a satellite analysis relative to
CRW climatology. It does not establish a full-grid basin mean, a station measurement,
a certified historical record or a Hobday marine-heatwave classification. Product
reference time is not an independently verified measurement interval. ERDDAP and
native files select edge cells differently; their sample means need not be identical.
These rules follow [NOAA's dataset metadata](https://coastwatch.noaa.gov/erddap/info/noaacrwsstanomalyDaily/index.html)
and [CRW's product description](https://coralreefwatch.noaa.gov/product/5km/index_5km_ssta.php).

Source receipts bind the region, date, value and cell count. Missing or inconsistent
receipts stay unqualified, including legacy events. Hashes establish identity, not
independent scientific truth or continued availability of the remote bytes. The
current bounds contract covers the existing integer-degree region boxes; arbitrary
new region definitions need their own sampling review.

## Verification and follow-through

Offline tests use invented CSV and real compressed NetCDF fixtures, including a
complete HTTP-to-review-queue case without injected provenance. Counterexamples cover
changed dates/units, duplicate and truncated grids, invalid/missing metadata, native
mask/scaling conflicts, bounded stream failures and host-fallback rules. The required
Python, database and dashboard release checks apply to the reviewed commit.

Separately retained public-source reads exercise all configured primary region
contracts and both file formats. These are source checks, not publishing trials,
independent pixel verification, global opportunity recall or preferred-copy evidence.
No LLM request is needed for this adapter validation. Required editorial checks,
runtime models, one routine writer sample and publishing controls remain unchanged.
Scheduled production recovery must be observed separately after deployment.
