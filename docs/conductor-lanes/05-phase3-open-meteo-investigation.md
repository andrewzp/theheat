# Phase 3 open_meteo degraded investigation

Date: 2026-05-14
Branch: `plan-a/open-meteo-degraded`

## Question

Why is `open_meteo_extreme_signals` marked `degraded` when the GHCN provider
otherwise produces readings and candidate events?

Phase 3 specifically called out `diff_dates_missing`. The live state-history
query showed the degraded rows are all the same pattern:

```text
finished_at                    status    diff_dates_attempted  diff_dates_fetched  diff_dates_missing  diff_missing_dates  stations_active  stations_with_obs  station_obs_pairs  stations_checked  raw_signals
2026-05-14T03:35:07.167775Z    degraded  3                     2                   1                   2026-05-13          11982            3985               5527               5207              400
2026-05-14T06:48:40.840080Z    degraded  3                     2                   1                   2026-05-13          11982            3985               5527               5207              400
2026-05-14T10:20:26.996447Z    degraded  3                     2                   1                   2026-05-13          11982            3985               5527               5207              400
2026-05-14T14:29:05.072859Z    degraded  3                     2                   1                   2026-05-13          11982            3985               5527               5207              400
2026-05-14T17:53:47.901031Z    degraded  3                     2                   1                   2026-05-13          11982            3985               5527               5207              400
2026-05-14T21:12:40.547280Z    degraded  3                     2                   1                   2026-05-13          11982            3985               5527               5207              400
```

The current local date is `2026-05-14 EDT`, so `2026-05-13` is the newest
attempted GHCN diff date. A direct NCEI availability probe matched the same
shape:

```text
2026-05-14
  no non-404 diff candidates

2026-05-13
  no non-404 diff candidates

2026-05-12
  superghcnd_diff_20260511_to_20260512.tar.gz 200 269301

2026-05-11
  superghcnd_diff_20260510_to_20260511.tar.gz 200 218615
```

## Conclusion

This matches hypothesis A from the brief: the newest comparison date is not
published by NOAA yet at cron time. The source is still doing useful work:
2/3 diffs are fetched, 3,985 stations have observations, 5,527 station/date
pairs are parsed, 5,207 stations are checked, and 400 raw signals are found.

The 3,985-of-11,982 station count is stable across degraded runs, but it is not
the degraded trigger. The trigger is currently any missing diff date. Treating a
single newest-date miss as degraded makes normal NOAA publication lag look like
a source failure.

## Fix direction

Keep `failed` behavior for zero fetched diffs in `src/data/ghcn.py`. In
`src/main.py`, classify the GHCN source as `degraded` only when the missing
diff count exceeds the expected newest-date lag tolerance, and include
`diff_missing_dates` in the run details so future investigations can see which
dates were absent.
