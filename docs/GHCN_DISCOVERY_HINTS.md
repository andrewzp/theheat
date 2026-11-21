# Station discovery when GHCN diff files are missing

## Failed lookup diagnostics

A 400 response remains an unavailable lookup, with no weather observations or
nominations. During that same request only, the collector may read at most 8193
payload bytes to accept a complete diagnostic of at most 8192 bytes before the
shared HTTP helper closes the error. It retains only a fingerprint, byte count
and up to 8 supported input-field/message pairs (messages at most 240 Unicode scalars).
Raw responses, echoed values, URLs and headers are not retained. Unsupported,
truncated, oversized or late diagnostics remain unavailable without a retry.
The existing cooperative 15 s read deadline and 5 s socket timeout still apply; this is not a
hard DNS/OS/header wall deadline or source SLA.

The Sources display labels these messages as **untrusted provider errors**. They
are inert operator text, never weather facts, a verified failure diagnosis or
instructions to change a request. Lookup metadata v2 is limited to this 400 case;
the original v1 success/other-error records remain supported. A new ordinary run
must supply the actual diagnostic before any request repair. Collection slots,
tracked-archive work, QC/history/comparator checks and writer limits are unchanged.

## Nomination and archive boundaries

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
Each nomination needs a finite existing cached comparator. Missing history never
becomes a reason to spend an archive slot, and numeric conflicts are compared
exactly before any conversion. Invalid optional station IDs or an unsupported
lookup cannot cancel the original tracked-station checks.

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
length headers are refused. A redirect is refused before the client's redirect preparation can read its
body or consult credentials. Chunked replies need a complete empty trailer through
the supported response reader; truncated or nonempty trailers are held.
Raw reads are bounded to32MiB and300000JSON rows, with a15second cooperative
deadline checked around raw client reads and a5second
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
