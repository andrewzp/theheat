# Station threshold baseline

`station_thresholds.version` selects a checksum-bound, immutable compressed SQLite
asset on the existing `thresholds-latest` release. It is a TheHeat-derived
candidate-discovery comparator built from NOAA GHCN-Daily Version 3.35, input
version `3.35-upd-2026102817`, retrieved 30 October 2026. Accepted input samples
precede the explicit 24 October cutoff.

The package contains 133,041 catalogue entries and 12,627 active stations across
189 country-code groups. 12,624 active stations have threshold provenance; the
three without comparators remain unsupported. These counts describe the baseline,
not currently reporting stations or measured global coverage. Current observations
and the bounded current station archive must pass the existing QC, freshness,
coverage and intervening-history checks before any historical comparison is used.
The baseline itself certifies no record or uninterrupted historical coverage.

The compressed asset and decompressed database identities and sizes are recorded
in the manifest. The normal workflow downloads, expands and verifies the database
before setting its verification result; a missing/mismatched file cannot qualify
by its name. The original bound build manifest, 16 completed partition receipts,
input identities and source metadata are retained in operator evidence. The
previous committed manifest is recoverable from the preceding Git revision; its
missing old remote asset is not claimed available as a rollback.

Source and dataset citation: Menne et al. (2012), *Global Historical Climatology
Network – Daily*, Version 3.35, NOAA NCEI, https://doi.org/10.7289/V5D21VHZ,
accessed 30 October 2026. Method reference: Menne et al. (2012), *An Overview of
the Global Historical Climatology Network-Daily Database*,
https://doi.org/10.1175/JTECH-D-11-00103.1.

The current NOAA-managed [GHCN-D dataset licence](https://registry.opendata.aws/noaa-ghcn/),
linked from [NOAA's dataset metadata](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00861),
states CC0-1.0 for this composite global daily dataset. NOAA requests attribution
and prohibits implying endorsement or presenting modified data as original NOAA
data. This asset is explicitly TheHeat's derived output. Its inputs were acquired
from NCEI; they are not relabelled as NODD captures. The older CDO export notice
and the current dataset-specific release basis are retained in operator evidence.

The unchanged lineage guard requires a timely incremental refresh. The initial
24 October watermark needs a catch-up before 7 November 2026 UTC; waiting for
the 8 November weekly job alone is insufficient. Do not widen the 12-day window
to conceal a gap. A failed catch-up requires explicit recovery or rebuild.
