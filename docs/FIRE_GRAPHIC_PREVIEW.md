# Local MODIS thermal-detection preview

This offline preview plots one to four retained MODIS pixel measurements from one
complete fire StoryBundle. It makes no source, model or image-generation request.
Production rendering, attachment and publication are not activated.

The chart uses pixel-integrated fire radiative power (FRP) in MW. Pixel centers
are not exact flame locations or fire perimeters. Multiple pixels do not establish
a count of separate fires; the same source minute does not establish simultaneity,
one overpass or a common incident. Retained receipts omit scan/track dimensions.
See the [NASA FIRMS MODIS field reference](https://firms.modaps.eosdis.nasa.gov/descriptions/FIRMS_MODIS_Firehotspots.html).

## Input contract

`fire_graphic_spec` requires the full P05-qualified bundle, an independently
retained SHA256 for that bundle, an ordered list of full-receipt hashes (primary,
then every related signal), and an explicit boolean `synthetic`. It validates
source receipts and each primary/related identity, acquisition minute and rounded
FRP headline. No related rows are dropped to make a story fit.

All rows must be MODIS_NRT from the same canonical Terra or Aqua platform and
reported UTC minute. T/Terra and A/Aqua aliases are accepted. Duplicate pixels,
colliding event identities, mismatched summaries, other products, fire footprints,
human-impact extensions and more than four measurements are refused. Geocoder
and climate annotations remain bound in the full story but are not certified by
the measurement validation or displayed as source-derived geography.

Bars start at zero and retain input order. Their lengths use exact source FRP;
labels explicitly round FRP to one decimal and coordinates to four. Exact parsed
values, source confidence, version, precision and qualifications remain in alt
text; original source spelling remains in the bound input. Confidence is a source
quality estimate, not a probability of cause or impact. All-zero charts and values
that cannot fit the readable layout are withheld without clipping or smaller text.

## Local workflow

Use private/ignored input and output paths. Repeat the receipt argument for every
retained measurement, in order:

```sh
python scripts/build_fire_graphic_spec.py \
  --bundle PRIVATE_BUNDLE.json \
  --expected-bundle-sha256 INDEPENDENT_BUNDLE_SHA256 \
  --expected-receipt-sha256 PRIMARY_RECEIPT_SHA256 \
  --expected-receipt-sha256 RELATED_RECEIPT_SHA256 \
  --synthetic false --output PRIVATE_SPEC.json
```

The CLI reads bounded strict local JSON and creates the output exclusively. It
does not read application state, contact a provider or replace an existing file.
Use the existing optional preview renderer and private media-review package flow
described in [the local media-review guide](handoffs/2026-09-10-p31-local-media-review-packet.md).

Template `modis_thermal_detections`, template version `p31-modis-thermal-1`, and
adapter version `p31-firms-modis-1` participate in existing exact cache and review
identities. Validation reconstructs the entire chart projection from the retained
bundle, so rehashing an edited chart value does not make it eligible. Changing
text, evidence, policy or assets invalidates the corresponding prior review.

A package is unreviewed and unapproved. Receipt consistency does not authenticate
the original HTTP response, certify every source claim, establish current source
freshness or prove agreement between the tweet and graphic. Those are separate
review and production integration requirements. Public tests use invented data;
historical source packets and exact draft text stay private.

## NOAA-20/NOAA-21 VIIRS locator map

The saved-draft preview also offers a colored locator for one to four retained
VIIRS pixels when every row is the same `VIIRS_NOAA20_NRT` or `VIIRS_NOAA21_NRT`
product, platform and reported UTC minute. It is a separate explicit template
(`viirs_thermal_detection_map`, template version `p31-viirs-locator-1`, adapter
`p31-firms-viirs-map-1`); VIIRS evidence is never labeled MODIS or checked by the
MODIS validator. Suomi NPP (whose delivery is retiring), NOAA HMS, any mix of
products, platforms or minutes, missing or incomplete receipts and more than four
rows stay held. Field meanings follow the
[NASA Earthdata VIIRS I-band 375 m active fire reference](https://www.earthdata.nasa.gov/data/instruments/viirs/viirs-i-band-375-m-active-fire-data).

The existing source validators run unchanged. Every receipt is bound in source
order to an independently supplied hash; the full story and every related row
are retained, never truncated. The locator reuses the MODIS map geometry, A-D
labels, equal markers, land outlines and zero-based FRP color scale in a shorter
frame, and binds the exact bytes of both shared modules in the evidence: a change
to shared locator or axis code obsoletes earlier VIIRS evidence instead of being
silently accepted.

VIIRS confidence is the source's categorical low, nominal or high class. The
graphic shows the exact retained category for each lettered pixel; the alt text
also records the source spelling (`l`, `n`, `h`). Internal ranking numbers are
never shown as percentages, probabilities, quality scores or severity. FRP is the
source's pixel-integrated radiative power in MW (a hybrid 375 m/750 m retrieval),
not temperature, burned area, physical-fire intensity, severity or impact, and
values are never summed. Pixel centers of roughly 375 m nadir pixels are not
flame locations or perimeters; scan/track dimensions are not retained. A shared
source minute and platform do not establish simultaneity, one overpass or a
common incident. Historical rendering is not current source qualification.

The saved-draft preview stays read-only, with no attachment, review, check pass
or publication authority. Separately, the local PostgreSQL editor workflow now
selects the same VIIRS template for a qualified single-product NOAA-20 or NOAA-21
source and applies the same map display preflight to both fire map templates. It
uses the existing native five-asset package, explicit joint review, fresh
required checks and publisher-parked local decision; `publication_approved` and
production attachment authorization stay false. A saved source the adapters
cannot qualify (Suomi NPP, NOAA HMS, mixed products, platforms or minutes) is a
recorded `graphic_source_unqualified` refusal rather than an unrecorded error;
a story with a missing receipt cannot become a generation input. These local
tests use invented data and are not hosted or scientific acceptance.

Unavailable previews emit fixed internal startup, authorization, request and
state-read stage names; an upstream failure may include its bounded HTTP status.
The reader distinguishes request setup/send, response-body reading and metadata
JSON decoding. Fixed error codes identify explicitly known exception classes;
unknown classes and subclasses stay unknown. A wrapped validation failure inspects
only its immediate cause's exact class, never its message or a cause chain.
These records contain no credentials, draft or source text, request details,
URLs, exception messages or tracebacks. Logging failure leaves the same private
response and fail-closed behavior. Diagnostics do not grant source qualification
or establish that a graphic rendered successfully.

## Protected reader status

`GET /api/graphic_reader_status` (also the native `.py` path) checks the graphics
function's state reader without selecting a saved draft or rendering. It uses
the same independent Basic or exact generated-host protection, strict target and
origin checks, verified archive and locked deployment files as the preview.
Other methods, query parameters, encoded bodies and nonempty request bodies are
refused. The response is private and uncached; this endpoint does not poll itself.

A successful reply reports `state_reader: available` while rendering and source
qualification remain `not_evaluated`, with `publication_approved: false`. It means
the bounded reader obtained strict JSON, not that the application state, weather
claims, source freshness or a graphic has been qualified. It neither edits state
nor grants review/approval and makes no source-acquisition or model calls.

An authenticated reader failure returns only fixed stage and class codes. Exact
known exceptions may carry an allowlisted internal stage; subclasses and hostile
attributes cannot supply diagnostics. The stream-method stage identifies access
to the required `read1` capability; there is no alternate reader or retry when it
is missing. No credential, URL, state content, count, exception name, message or
traceback is returned. Authentication and bootstrap failures keep generic replies.
Logging failure cannot change these rules. Normal preview replies stay unchanged.

The reader removes only surrounding space, tab, CR and LF from its in-memory
GitHub token before preparing the metadata header. It does not rewrite stored
configuration, unquote or decode a token, or send credentials to the raw-state
host. Empty/non-string tokens and embedded whitespace, control, DEL or non-ASCII
bytes fail at configuration before a session is created. Canonical token headers,
upstream error handling and independent dashboard authentication stay unchanged.

Each invocation uses one reader call: at most one GitHub metadata request and one
validated versioned raw-state request when needed, within the existing 25-second
application budget and 30-second platform duration. A separate fixed entry selects
this handler through the shared bootstrap; URL/body/environment input cannot select
a mode. Both entry files are integrity-bound before archive imports. Availability
and a code deployment remain distinct from end-to-end hosted graphic acceptance.
