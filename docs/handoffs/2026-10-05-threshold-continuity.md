# Contiguous threshold update checkpoints

The updater previously handled checkpoints differently in its empty and nonempty
observation paths. An empty result could advance to the latest fetched day despite
a missing interval. The other path could stall on already-processed days that it
correctly had not fetched again.

Preflight and the updater now share one bounded planner. A known checkpoint defines
the first pending day; the existing lag defines the last. Unknown, malformed, old
or ahead-of-window checkpoints stop rather than inventing history. Already-complete
windows return without fetching or writing. The initial database read does not run
the schema creation and migration helper.

Pending intervals are fetched chronologically. A missing or empty response stops
before applying observations, and later dates are not fetched. Both observation
paths use the same verified contiguous checkpoint. Station recomputation that
returns no usable thresholds also fails rather than advancing the checkpoint.
Source parsing, station filters, quality flags, threshold calculations and the
existing lag remain unchanged. Incremental threshold provenance remains explicitly
incomplete; successful date bookkeeping does not qualify scientific claims.

The updater still commits threshold rows in chunks. A later station failure can
leave a partially changed local candidate, with the old checkpoint. This is not
an all-or-nothing database transaction. The artifact workflow requires updater
success before uploading, changing the committed manifest or saving the new cache,
so that failed candidate must not become the authoritative artifact.

The 117-test focused suite includes 55 new offline regressions: completed overlap,
missing first/middle/last intervals with empty and nonempty observations, invalid
lineage, unavailable or active databases, no-op and dry-run paths, source and
recompute failures, and failure after a committed chunk. Fixtures contain invented
station data and mock source transport; no source request or provider call runs.

The legacy baseline's missing checkpoint is still unresolved. This repair neither
rebuilds that history nor establishes observed recovery. It changes no dashboard,
production state backend, runtime model setting or publication control.
