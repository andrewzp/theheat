# Contiguous threshold update checkpoints

The updater previously handled checkpoints differently in its empty and nonempty
observation paths. An empty result could advance past missing source changes. The
other path could stall on already-processed dates it had not fetched again.

Preflight and the updater now share one bounded range of possible snapshot
endpoints. A known checkpoint defines the starting snapshot; the existing four-day
lag bounds the end. The default twelve-day lookback covers the weekly cadence,
lag and a buffer. Unknown, malformed, old or ahead-of-window checkpoints stop rather
than inventing history. Complete windows return without fetching or writing, and
the initial database read does not run schema creation or migration.

NOAA defines each diff as changes between the two snapshot dates in its filename;
a valid interval can span multiple days. The updater requests only intervals
starting at its last verified endpoint. A 404 permits probing a later endpoint
within the bounded window, still from that exact predecessor. It never chooses
an unrelated predecessor just because a file exists. Transport errors and redirects
stop; each candidate gets one request. See the
[NOAA format specification](https://www.ncei.noaa.gov/pub/data/ghcn/daily/superghcnd/readme-superghcnd_diff.txt).

Only a connected, parsed interval advances the checkpoint. If the tail is not
available, the updater can retain the verified prefix and explicitly warn that
coverage through the lag cutoff remains incomplete. If no connected interval is
available, it fails without applying observations. An empty response or parse
failure also stops before application. Empty and nonempty observation paths use
the same checkpoint; unusable station recomputation cannot advance it. Source
parsing, filters, quality flags and threshold calculations retain their behavior.
Successful date bookkeeping does not qualify scientific claims.

Threshold rows still commit in chunks. A later station failure can leave a
partially changed local candidate with the old checkpoint. This is not an
all-or-nothing database transaction. The artifact workflow requires updater success
before uploading, changing the committed manifest or saving the new cache, so that
failed candidate cannot become the authoritative artifact.

The focused suite passes 128 tests, including 66 new regressions covering missing
coverage, explicit multi-day bridges, wrong predecessors, the weekly lagged window,
invalid lineage, source/recompute failures and failure after a committed chunk.
Tests use invented station data and mock transport; no live source or provider call.

The legacy baseline's missing checkpoint remains unresolved. This repair neither
rebuilds that history nor establishes observed recovery. It changes no dashboard,
production state backend, runtime model setting or publication control.
