# Dated GHCN source candidates

`scripts/ingest_ghcn_snapshot.py` reads an already supplied NOAA dated full CSV gzip
and builds an isolated SQLite candidate containing selected stations' raw TMAX and
TMIN rows. The old bootstrap reads per-station `.dly` members from a different,
undated archive. Renaming that archive or assigning it a local file timestamp does
not establish the dated starting state needed for incremental updates.

NOAA's [dated full products](https://www.ncei.noaa.gov/pub/data/ghcn/daily/superghcnd/)
and [field definition](https://www.ncei.noaa.gov/pub/data/ghcn/daily/superghcnd/readme-superghcnd_full.txt)
specify `superghcnd_full_YYYYMMDD.csv.gz` and eight CSV fields. The importer preserves
the integer value, measurement/quality/source flags and raw observation-time code.
Missing or flagged observations are retained; no timezone, reporting interval,
station completeness, certified record or scientific eligibility is inferred.

## Inputs and invocation

Supply a regular, nonsymlink archive and a JSON transfer receipt with exactly:

| Field | Required value |
|---|---|
| `schema_version` | Integer `1` |
| `source_kind` | `noaa-superghcnd-full-csv-gzip` |
| `url` | Exact HTTPS NOAA dated-full URL, without redirects/query/fragment |
| `snapshot_date` | ISO date matching the URL's dated filename |
| `retrieved_at` | Aware ISO acquisition timestamp, no earlier than the snapshot date in UTC |
| `http_status` | Integer `200`, for the complete transfer |
| `compressed_sha256` | Exact lowercase SHA256 of the entire compressed file |
| `compressed_bytes` | Positive integer byte count |

The receipt is supplied by the caller. Local hash/date/size consistency is verified;
its authenticity is not independently attested. A caller-written receipt cannot
turn invented data into qualified observations. Independent acquisition/provenance
review is still required before production use.

For a small local fixture, explicit limits might be:

```sh
python -m scripts.ingest_ghcn_snapshot \
  --archive fixture.csv.gz --receipt fixture-receipt.json \
  --output new-candidate.sqlite --station ZZ000000001 \
  --max-compressed-bytes 1048576 --max-expanded-bytes 1048576 \
  --max-rows 10000 --max-selected-rows 10000 --max-database-bytes 1048576
```

The station above is invented. Those example limits are for synthetic fixtures,
not a capacity estimate or permission to acquire NOAA's full archive. Every path,
station and resource bound is explicit; there is no default production DB, download,
upload, network call or model request. Larger real inputs need a measured resource
plan within the tool's absolute limits.

## Failure and output contract

The entire compressed identity is checked before staging begins. The same open
file descriptor is rehashed during decoding, with file metadata checked again
before promotion. All rows are parsed, even outside the selected scope; input bytes,
row count, selected rows, line length and SQLite page count are bounded. Duplicate
selected station/date/element keys fail, including identical duplicates. Every
requested station must have retained temperature rows; those rows can still be
missing or rejected by source QC.

The candidate contains `snapshot_observations` and `snapshot_metadata`, not the
production threshold schema. The final completed receipt is stored only after full
EOF/CRC/hash/scope checks. Partial files stay in a temporary sibling directory.
The closed complete file and destination directory are flushed around atomic,
no-clobber promotion. Existing outputs, including dangling symlinks, are never
replaced. An interrupted or failed decode exposes no final output. A failure after
promotion can leave a complete file with a lost acknowledgement; retain and inspect
that file rather than deleting it or overwriting it on retry. CLI errors contain
fixed categories, not raw rows, provider messages or private paths.

This is not `station_thresholds.sqlite`, and it deliberately fails that asset's
existing verifier. It does not set `last_diff_date`, alter maintenance, create
scientific approval, restore a production source or activate publishing. The next
boundary must derive qualified comparators and handle exact snapshot deltas without
mixing a dated cursor with unlabelled current station downloads.

Validation uses invented offline receipts, gzip files and SQLite candidates,
including corruption, late parse failure, duplicate rows, resource exhaustion,
source mutation, interruption, promotion races and lost acknowledgement.
