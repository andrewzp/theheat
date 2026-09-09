# P06 follow-up: bounded GHCN archive selection

Date: 2026-09-09. Isolated branch: `codex/p06-fair-archive-scan`, based on
`190deee`. Local implementation only; no source/provider/model requests, paid
calls, deployment, publication, or public correction were made for this work.

## Problem and scope

The prior selector sorted each tracked/candidate lane, shifted its start by one
station per UTC day, and interleaved at most 20 unique station archives per run.
For a stable 80-station candidate pool alone, four daily selections reached only
23 stations. With 80 disjoint tracked stations competing for the same budget,
the candidate lane received ten slots and reached only 13 stations in four days.
Repeated collection runs within a day had identical priorities. Eventually
rotating through a stable pool did not establish useful coverage before a news
candidate expired.

This follow-up replaces selection only. It preserves the 20-archive **per-run**
ceiling, four concurrent request workers, the existing request and byte bounds,
the tracked/new lanes, source QC and comparator qualification, downstream country
and editorial caps, and durable evidence/receipt rules. It adds no persistent
cursor, daily budget, retry fetch, bulk refresh, or new dependency.

## Algorithm and bound

1. Normalize the supplied timezone-qualified retrieval time to UTC and identify
   its four-hour bucket (00:00, 04:00, 08:00, 12:00, 16:00, 20:00).
2. Sort each lane independently. Clamp the requested integer limit to 0–20;
   actual allocation is also bounded by the number of unique eligible stations.
3. Divide slots evenly between lanes. For odd budgets, alternate the extra slot
   between tracked and candidate lanes on even/odd buckets. A short or empty
   lane releases unused capacity to the other lane.
4. For each lane, calculate its circular start from the **cumulative reserved
   slots** before this bucket. If the even/odd allocations are `e` and `o`, and
   bucket `b = 2q + p`, the start is `(q*(e+o) + p*e) mod lane_size`. Take the
   current bucket's reserved number of consecutive stations.
5. Interleave and deduplicate both reserved windows. Fill any slots released by
   overlap from the remaining circular lane tails, skipping already selected
   stations. No reserved station is dropped, and at most 20 distinct archives
   are requested. Fetch failures do not spend additional selection slots.

For fixed lane membership and limit, the end of one bucket's reserved window is
the start of the next. Consequently, the windows concatenate into the circular
sorted lane. After enough consecutive buckets reserve at least `lane_size`
slots, every station in that lane has been selected. Overlap filling can improve
coverage but cannot weaken that guarantee. Cumulative alternating allocations
are necessary for odd budgets: multiplying the bucket number by the current
allocation alone can skip stations or starve a lane at a limit of one.

The reported sweep bound is conservative across both starting parities. Given
nonempty lane size `n` and pair allocation `e+o > 0`, use
`q,r = divmod(n-1, e+o)`; the bound is `2q+1` if `r+1 <= min(e,o)`, otherwise
`2q+2`. A nonempty lane with no slots reports no finite bound (`null`); an empty
lane reports zero.

Offline examples below are engineered workloads, **not measured production
station counts or evidence of NOAA reporting availability**:

| Stable tracked pool | Stable candidate pool | Limit | Reserved slots per opportunity | Opportunities to select the whole union |
| --- | --- | --- | --- | --- |
| 80 | 80, disjoint | 20 | 10 / 10 | 8 |
| 0 | 80 | 20 | 0 / 20 | 4 |
| 4 | 80, disjoint | 20 | 4 / 16 | 5 |
| 80 | 80, disjoint | 19 | 10 / 9, then 9 / 10 | 9 |
| 80 | 80, disjoint | 1 | 1 / 0, then 0 / 1 | 160 |
| 1,000 | 1,000, disjoint | 20 | 10 / 10 | 100 |

Eight consecutive four-hour opportunities span 28 hours from first to last;
the nominal eight-slot interval is 32 hours. Four span 12 hours from first to
last. The 1,000/1,000 example plainly exceeds the news horizon and reports 1,980
unselected stations in a single run. No workload-independent freshness claim is
made.

## Operational metrics and evidence limits

The existing source run details already carry the GHCN pipeline metrics through
both GHCN-only and combined-provider collection paths. The new `archive_selection`
object adds the UTC bucket, clamped limit, actual eligible pool sizes, overlap,
selected/unselected unique counts, per-lane reserved and selected slots,
per-lane verified/unverified counts, and conditional stable sweep opportunities.
Per-lane selected/verified counts can overlap and must not be added to calculate
unique requests. Existing attempted, failed, verified, exhausted and tracked
unscanned counters remain available.

An archive counted as verified here has been fetched and parsed as a current
station snapshot. That does **not** certify complete comparator coverage or a
record claim; the separate candidate acceptance, QC, same-source evidence,
interval coverage and editorial gates still decide that. Metrics explicitly
state this verification scope. Source request failure raises the unverified
count without increasing the request budget. A source path that never reaches
selection leaves the selection object `null`, not an invented empty workload.

The bound requires unchanged pools and limit plus an execution in every
consecutive four-hour bucket. Membership changes (including new retained claims),
limit changes, missing/delayed runs, candidate expiry and failed source requests
can invalidate the timing bound. Stateless selection does not pretend to know
the actual historical scan cursor. Same-bucket retries with unchanged pools and
limit repeat the same priorities and can refetch those archives; this work adds
no cross-run snapshot cache. A deliberately skipped-bucket regression shows that
24 tracked stations with 20 slots and only one daily run can repeatedly select
the same 20, while the next four-hour run covers the remaining four.

`MAX_OBS_AGE_DAYS=4` is an inclusive age cutoff (ages 0 through 4), not a promise
of four full remaining days after arrival. The three-day diff lookback, NOAA
arrival lag and actual execution schedule can leave fewer opportunities. We did
not make new production source requests; current production pool sizes and the
effect on real timely coverage remain to be measured from post-integration run
metrics. `timely_verification_guaranteed` remains false.

Historical tweet evidence limits are unchanged: a missing/unavailable archive
does not disprove an old claim. Only an independently qualified material change
can invalidate unpublished evidence through the existing revision path. Posted
drafts and publication receipts are preserved; no public corrections are made.

## Validation and integration

Run from this checkout with the existing main repository virtual environment:

```sh
/Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python -m pytest tests/test_ghcn.py tests/test_ghcn_format.py tests/test_ghcn_time_integrity.py tests/test_ghcn_scientific_supply.py tests/test_records_cluster.py tests/test_main.py tests/test_ghcn_archive_selection.py -q
/Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python -m ruff check src/data/ghcn.py tests/test_ghcn_archive_selection.py tests/test_ghcn_time_integrity.py
/Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python -m mypy src/data/ghcn.py
```

Focused validation: 377 tests passed; Ruff and mypy passed. Tests cover multiple
starting buckets, fixed odd/even/zero/capped limits, unequal/empty/overlapping
lanes, UTC-equivalent times, same-bucket stability, invalid time/limit refusal,
overflow, missed-opportunity limits, the actual injected source fetch ceiling,
failed-fetch coverage metrics, and preservation of posted drafts.

Independent review found no blocker. The reviewer reran 133 focused tests plus
Ruff, mypy and the diff check, then exercised 1,200 deterministic randomized
fixed-pool configurations across unequal/overlapping memberships, varied epochs
and limits. Every reported lane bound covered its lane, request budgets and
count diagnostics matched, and unchanged same-bucket retries were identical.

Integrate as a later reviewed follow-up to the current release. Regenerate the
P07 editorial policy source manifest **after all combined source cherry-picks**;
the selector lives in the already inventoried `src/data/ghcn.py`, so no policy
source-list expansion is required. Run the integrated policy and release checks.
No release was performed in this worktree; root handles integration and the
existing authorized release workflow.
