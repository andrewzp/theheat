# Fire detections retain their source minute

FIRMS and NOAA HMS thermal detections now carry a qualified source product, a UTC
acquisition minute and a compact selected-row receipt. The collection date no longer
stands in for observation time. Each row is checked before confidence/FRP selection:
its source minute cannot be in the future, and its UTC calendar date must be within
the existing two-day allowance. A fresh low-power row cannot refresh a stale
high-power row.

FIRMS dates use `YYYY-MM-DD`; one through four ASCII time digits are left-padded to
HHMM. HMS uses the observed one-based `YYYYDDD` and four-digit HHMM. Leap years and
calendar rollover are validated. Serialized zero seconds express minute precision,
not measured seconds. HMS's requested file date stays distinct from its row time.
Required headers, finite coordinates/FRP and product/instrument/satellite identity
are checked. Malformed rows are isolated with bounded diagnostic counts; malformed
headers, wholly invalid packets and wholly stale/future packets fail explicitly.
Valid empty or below-threshold results remain distinct from failures.

VIIRS confidence stays categorical (low/nominal/high), MODIS retains its numeric
quality value, and HMS confidence stays unavailable. Existing internal ranking
scores and selection thresholds are unchanged. FRP headlines still round to one
decimal while receipts preserve the selected wire value. Geocoder labels are
separate inferences and are not certified by a measurement receipt.

The receipt binds normalized selected fields with a digest. It is neither a complete
response archive nor upstream authentication. FIRMS receipts contain only the public
API documentation URL, never the credential-bearing request URL. Public failure
messages and formatted tracebacks use fixed diagnostics after the existing backup
decision. The FIRMS product order and HTTP retry bounds remain unchanged. Typed
transport errors survive product exhaustion so a timeout does not lose backup
eligibility when its message omits the error type.

New IDs preserve the rounded daily coordinate cell and add the source date and
`_utc1`. Before generation, enqueue, save and final send, legacy IDs for the same
formatted cell are checked from source day D−1 through D+3. Any retained draft,
posted event or confirmed/unresolved/conflicting publication attempt holds the
candidate. A standalone explicit `not_sent` receipt does not establish publication.
Malformed history never grants clearance. This conservatively accommodates the old
local processing-day IDs; it can also withhold a legitimate nearby-day event.
New IDs do not become aliases of each other. No historical row is rewritten, and
these checks do not make Gist writes transactional.

Thermal related summaries include a detached validated acquisition receipt. Their
identity, minute and FRP are checked at assembly and direct checker entry. Missing
legacy receipts, detached fields and recognizable misrouted thermal records stop
before paid generation/checks. Minute equality, country grouping and neighboring
pixels do not prove physical simultaneity, a common overpass or one fire. Bounded
checks reject explicit simultaneity/same-overpass claims; existing incident and
causal checks remain mandatory. Ordinary separate observations can proceed through
all required checks. Nonthermal related serialization remains unchanged.

This changes the editorial policy identity, invalidating older checks and approval.
It adds no model call and changes no runtime model, sample/revision setting,
publishing flag or backend. Receipt bytes increase the evidence payload; no token,
invoice, quality, coverage or savings improvement is inferred from offline tests.
Old illustrative dry-run fire objects without source evidence remain unqualified.

Historical evaluation uses complete **invented** source rows only in its declared
structural probes. They do not repair missing historical packets, adjudicate an old
post or become positive editorial examples. The frozen catalog and original source
files remain unchanged.

Source definitions:

- [NASA FIRMS acquisition fields](https://firms.modaps.eosdis.nasa.gov/content/academy/data_ingest/firms_data_ingest.html)
- [VIIRS attributes](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html)
- [MODIS attributes](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_MODIS_Firehotspots.html)
- [NOAA HMS documentation](https://www.ospo.noaa.gov/products/land/hms.html)

HMS's one-based day-of-year interpretation was checked against bounded public
January 1, leap-day and year-end file prefixes; those reads do not qualify every
row, source date or satellite. Operational availability and useful global coverage
still require separate evidence.
