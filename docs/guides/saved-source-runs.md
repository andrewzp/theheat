# Read saved source runs

The Sources panel describes retained collection results. It does not make a new
source request or establish current availability, current measurement data,
scientific validity or event recall. This remains true when a saved status says
healthy, when collection is paused, and when a successful run found no candidates.

Each source shows its latest dated run and last unambiguous successful collection
in the supplied history, with UTC dates and ages relative to the stated snapshot.
Missing, invalid, timezone-free or future timestamps cannot establish either date.
Conflicting statuses at a timestamp remain ambiguous; a degraded alternate does
not become primary recovery. Stored timestamps and source records are unchanged.
The timing projection groups at JavaScript millisecond resolution; finer same-
millisecond status conflicts are conservatively ambiguous, not proof of recovery.

Timing uses the existing durable source-history preference. On older snapshots,
the fallback dates describe the collection run's start, not a precise source
completion time. Missing history and a bounded-out inventory show unknown dates,
never zero ages. At most4096supplied rows per source are examined by this timing
projection. Existing aggregate counts, classifications and ordering are retained.

The panel imposes no new cadence or freshness threshold and certifies no source
rights or claim permissions. Live recovery requires an observed qualified source
result. A code deployment does not resume collection, generation or publication.
