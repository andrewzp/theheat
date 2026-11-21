# Station discovery when GHCN diff files are missing

Missing daily diff files need not confine archive checks to stations already in
revision history. The existing legacy GHCN collector can make one additional
lookup request to NOAA's [documented access service](https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation).
Its response only nominates untracked active station IDs for the existing archive
selection lanes. **Lookup numbers never become observations, QC flags, baseline
records, claim evidence or writer input.**

Only original per-station `.dly` bytes provide observations. The existing age, QC,
archive coverage, cutoff, intervening-record and required editorial checks remain
mandatory. A false lookup value can nominate a station, but its actual archive
can disagree, fail or contain no qualified story. No source agreement is inferred.
The bounded reader supports one explicit JSON lookup shape (`STATION`, `DATE`,
`TMAX`/`TMIN`); unsupported or conflicting responses nominate nothing. Its tests
use invented data and establish neither current provider response format nor
availability, global coverage, source rights or the absence of missed events.

The extra request requires all of these conditions:

- No diff body was returned, and this invocation captured every attempted client
  request as HTTP404. Partial intake, parse failures, auth/rate/server errors and
  unavailable capture cannot enable it.
- The normal collector has existing active tracked stations, additional active
  untracked stations, and a positive archive limit. Cold starts, explicit retained
  runtimes and injected observation readers are excluded.
- The fixed NOAA HTTPS origin receives one `daily-summaries` query for TMAX/TMIN,
  metric units and JSON, over at most the preceding four calendar days through
  the current request day. It follows no redirects and makes no retry.

The lookup uses the existing counted `source_http_get` call declaration. No secret
or implicit netrc authentication is used. Encoded bodies and ambiguous/unsupported
length headers are refused. Raw reads are bounded to32MiB and300000JSON rows,
with a15second cooperative deadline checked around raw client reads and a5second
socket inactivity timeout. It cannot interrupt DNS/OS or header/chunk-framing
work inside the client; this is not a hard wall deadline, SLA or financial cap.
An operation cancelled before dispatch still refuses before the request is sent.
A cancellation observed after a lookup or around an archive read also refuses
subsequent work; an already dispatched request remains spent.

Archive verification stays capped at20, with the same tracked/candidate lane
reservations, four-hour rotation and unchanged scope of its conditional sweep
bound. At the default three diff dates the upper bound is30original diff client
calls, one lookup and20archives; this is an acquisition bound, not billed spend.
The lookup cannot change writer samples, refill, models, approvals, sender state,
unknown-delivery handling or automatic-image settings.

Sources keeps the original v1 tracked-only trace for unchanged paths. Expanded
nominations use a separate v2 scope that joins lookup counts to the actual
selected/verified archive lanes. Failed lookup counts remain supplied-but-
unavailable. A failed diff remains failed even when selected archives supply
qualified values. Neither the trace nor a successful run certifies global recall
or that a draft was written or published.

Source-product inventory v5 also distinguishes current archive observations from
the archive's historical-reference role. They are the same upstream bytes and
are not independent sources. The nomination row is discovery-only; it cannot be
relabelled as a station observation. Complete v1–v4 exports remain byte-identical.
