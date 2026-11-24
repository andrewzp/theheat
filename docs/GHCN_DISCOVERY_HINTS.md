# Station discovery when GHCN diff files are missing

## Bounded archive sampling after a rejected or empty lookup

When the existing collector has a complete all-404 diff capture and its single
lookup returns HTTP400 or a complete supported200with no usable nominees, it can independently sample active untracked stations
from its installed cache. Cached comparison values and the error response are
not current weather. A station needs a matching cached identity, a finite
temperature comparator and the configured minimum archive years merely to enter
this sample. Only newly fetched original `.dly` bytes can provide observations;
the existing source, age, QC, coverage and comparator checks still decide whether
anything is usable.

The unchanged two-lane selector shares the existing maximum of 20 archive checks
between tracked history and the unhinted pool. Same-bucket retries and input order
do not change selection; the one-slot case still alternates the lanes. Previously
unused allowance can be consumed, but there is no extra lookup or higher archive
ceiling. Authentication, rate, server and transport failures, malformed lookups,
partial/malformed diff intake, cold starts and explicit retained readers
do not enable this path. Cancellation still fences every subsequent request.

Schema 3 archive-intake telemetry explicitly names the unhinted sampling origin
and pool, preserving zero provider nominations and the precise failed-or-empty lookup. Sources
checks the current interval, both lane allocations and counts before interpreting
it. This sample is not a repaired diff or lookup, a new independent source, a
global or timely coverage guarantee, or permission to write or publish a claim.
With a large station pool and a small allowance, a full sweep may take months;
missing runs or changing membership further weaken that selection-only bound.
Actual useful output and coverage remain to be measured in ordinary runs.

## Failed lookup diagnostics

A 400 response remains an unavailable lookup, with no weather observations or
nominations. During that same request only, the collector may read at most 8193
payload bytes to accept a complete diagnostic of at most 8192 bytes before the
shared HTTP helper closes the error. It retains only a fingerprint, byte count
and up to 8 supported input-field/classification pairs. Input messages are bounded
to 240 Unicode scalars while parsing; arbitrary provider text is never retained.
One documented public units-error template maps to a fixed classification; other
supported text is withheld. Raw responses, echoed values, URLs and headers are not retained. Unsupported,
truncated, oversized or late diagnostics remain unavailable without a retry.
The existing cooperative 15 s read deadline and 5 s socket timeout still apply; this is not a
hard DNS/OS/header wall deadline or source SLA.

The Sources display labels these classifications as **untrusted provider errors**. They
are inert operator text, never weather facts, a verified failure diagnosis or
instructions to change a request. Lookup metadata v2 is limited to this 400 case;
the original v1 success/other-error records remain supported. A new ordinary run
must supply the actual diagnostic before any request repair. Collection slots,
tracked-archive work, QC/history/comparator checks and writer limits are unchanged.
The optional read checks cancellation before and after each client read; once
control returns, cancellation prevents the next read and later archive requests.
Supported chunk framing has plain hexadecimal size lines, CRLF separators and an
empty trailer. Other framing stays unsupported. These same framing checks also
protect ordinary successful lookup payloads; no global HTTP class is patched.

## Nomination and archive boundaries

The request supplies the documented comma-separated `stations` selector using
only currently eligible untracked station IDs. The current service reports a maximum of100stationIDs; the client uses
that100-ID bound and retains its8192-byte prepared-URI guard. The source reply
is an engineering capacity diagnostic, not weather authority or an availability
promise. A rejected request never causes a split, retry or automatic refill. The sorted pool is divided into consecutive
chunks; the collector's captured UTC four-hour bucket selects one chunk. With an
unchanged pool, successive buckets visit each chunk once per cycle. Pool changes,
missing runs, unavailable data and reporting delays grant no coverage guarantee.
For12,522eligible stations that is126chunks, not a global query on every run.

The lookup diagnostics retain the pool/selection fingerprints, bucket, selected
and unselected counts and prepared URI length. Only the selected subset may be
nominated from a returned response. Unrequested high values cannot consume an
archive slot. Standalone calls without a captured clock use the supplied day's
UTC midnight; malformed, naive or mismatched-day clocks refuse before dispatch.
The request's dates and station observations retain their existing meanings.
This local request correction follows an ordinary400 diagnostic naming stations;
it does not prove service recovery, current observations or a useful story.

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

## Empty successful lookups

A complete, supported200response with no usable nomination also retains the
existing bounded untracked-station archive sample. Its trace explicitly says
`cached_active_stations_after_lookup_no_nominations`, distinct from the existing
400case. An empty API response is not proof that every station archive lacks
fresh observations. Only the same original archives and full QC/history/age/
comparator readers can supply facts. The20-archive cap and tracked reservations
remain; no new lookup fallback follows auth, quota, transport or malformed-body
errors. A returned-but-unusable hint never becomes a weather observation.

The exact fixed stations-limit diagnostic maps to `station_limit_100`; arbitrary
messages and reflected values remain withheld. This does not establish actual
source recovery, global recall, a useful draft, X publication or four posts/day.

For a nonempty reply, quiet sampling additionally needs at least one requested
station with a canonical date in the requested window and a TMAX/TMIN key. An
unrelated, malformed-date or stale-only reply cannot allocate untracked archive
work. This is a lookup-scope check, not acceptance of its numeric values.
The source display ties the new quiet-sampling origin and fixed capacity code
to the current100-ID producer; genuine historical500-ID traces stay readable in
their original paths. At exactly two body bytes, a zero-row report must retain
the digest of `[]`; this specific consistency check authenticates no arbitrary
longer payload.
