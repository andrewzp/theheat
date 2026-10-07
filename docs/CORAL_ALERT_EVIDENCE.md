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

The primary regional feed supplies a heritage seven-day maximum BAA code. It is
not a current daily category or the expanded Alert Levels 3–5 product. The
[regional product definition](https://coralreefwatch.noaa.gov/product/vs/description.php)
describes regional statistics and the 90th-percentile HotSpot method; its map
coordinates are regional markers, not individual sampled pixels.

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
approval. Full source archival and combined-story qualification remain separate work.

The primary feed now validates its version 3.1 index (at most 4 MiB), date and
station identities. Each selected station uses an 8 KiB tail and 2,049-byte header;
the header request carries the tail's strong ETag in `If-Match`. Both responses
must be exact uncompressed 206 ranges from the same version and size. A 32 MiB
file-size ceiling bounds computation; it is not a scientific measurement limit.
Full-file responses, changed versions, invalid columns/dates, nonfinite numbers,
negative heat stress, fractional BAA codes and gaps in retained daily rows reject.
Header first-valid dates use year/day/month; daily rows use year/month/day.

The latest daily row must match the index date and supplied heritage label. DHW
keeps source precision through selection and review. Every selected station now
requires its header, including below-threshold readings; this adds up to one small
header request for those readings. Eight workers, three bounded transport attempts
and existing partial-result/outage-fallback semantics remain. Schema failure does
not masquerade as backup recovery. No model request is added.

Primary receipts bind the index, both ranges, marker, source day, DHW and BAA to
current writer evidence. Missing legacy receipts remain unqualified. Source text
is not copied into prompts. The evidence explicitly separates the source day,
12-week DHW accumulation and heritage seven-day maximum. Every recognizable alert
label in proposed copy must match the supplied code and immediately follow a local
qualifier such as `7-day maximum was Alert Level 2` or `seven-day peak: Bleaching Watch`.
A qualifier across a sentence, punctuation or newline does not qualify a label.
This is a bounded lexical check, not universal entailment or a replacement for the
required factual and safety checks. It does not establish actual coral damage.

These source and binding checks are independent of human writing preferences,
global opportunity coverage, observed source uptime or measured operating savings.
