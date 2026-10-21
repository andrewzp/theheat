# Saved-source graphic preview

The private draft workbench offers an explicit **Preview graphic** action for fire,
PM2.5 forecast and qualified GHCN station-temperature drafts. It builds one SVG
from the complete retained source bundle. It does not
fetch new weather, call a model, write state, attach media or approve publication.
Other hazards and incomplete or unsupported source evidence produce no graphic.

The preview sits beside the saved text. Editing, a pending draft action, switching
stories or changing the saved revision removes it. Rebuilding revokes the previous
browser Blob; cancelled and late responses cannot install a replacement. Source
time, scope and a full visible text description accompany the image. A chart can
describe historical saved evidence without establishing present freshness, source
authenticity, a physical fire's extent or agreement with the tweet's claims.

## Read-only boundary

`dashboard/api/graphic_preview.py` is a native Python function, with authorization
independent of Next middleware. It accepts only the saved draft ID, full expected
content/text/evidence/decision revision, policy source hash and preview runtime hash.
Clients cannot supply source packets, retrieval URLs or a synthetic override.

Complete dashboard Basic credentials are required unless the existing outer
Vercel protection mode is configured. In that mode, the actual request Host must
equal the validated generated deployment hostname; aliases and inconsistent
absolute targets do not gain access through forwarded headers. Missing configuration
fails closed. Supplied Origin must match. Authentication precedes JSON parsing,
state reads and rendering; this endpoint has no local development bypass.

Only the configured production Gist backend is supported. There is no database
bootstrap or write path. The reader uses fixed GitHub API locations and strictly
validated, versioned raw URLs, without redirects, retries or credential forwarding.
It reads the saved draft again after rendering and rejects content, status,
decision or conflict changes. This checks two snapshots; it is not a transaction
and grants no authority against a later state change.

Requests are limited to 4 KiB, GitHub API responses to 12 MiB, raw state to 8 MiB,
and the complete source bundle to 1 MB. JSON rejects duplicate keys, non-finite
numbers, invalid Unicode and excessive nesting. SVG bytes have a separate 1 MB
limit; encoded JSON responses are at most 1 MiB. One in-process request runs at a
time. The application checks a 25-second budget between bounded operations and
before returning success. Connect/read timeouts bound network inactivity; Vercel's
30-second function maximum covers blocking operations as well. This is not a
global concurrency or spending cap. Gist reads and hosting costs remain unmeasured.

Responses use fixed error messages, private/no-store caching and nosniff. The
handler suppresses request logs, including Vercel's prepended native logger.
Source receipts, draft text, credentials and upstream exception bodies are not
logged or included in errors. Platform-level access/fetch metadata remains subject
to the hosting platform's own logging behavior.

## Colored locator and retained images

Current qualified MODIS previews use a colored locator. Equal-size markers identify the selected satellite pixel centers; their blue-to-yellow scale represents pixel-integrated radiative power in MW. They do not show fire perimeters, severity or separate fire counts. The original platform, reported UTC minute, quantitative legend and source qualifiers remain attached. Unresolvable marker or label collisions, out-of-bounds views and unreadable layouts are unavailable rather than silently altered.

The coarse Natural Earth land resource is pinned and packaged locally. Coordinate close-ups omit coastlines that cannot resolve that scale and retain a separate world locator. Rendering acquires no new weather and makes no model call. Published charts and radar ingestion are not implemented by this adapter.

The separate experimental PostgreSQL editor workflow can retain a native image package, record joint text/image review and run the existing four checks before parking a revision-bound approval. Its historical PNG read verifies the exact successful preparation and immutable package, without depending on the current basemap, recent-command listing or current editability. Those original bytes remain evidence only: current attachment, checks and approval still require current source, policy, renderer and draft identity. The Gist SVG endpoint described above remains read-only.

## Acquisition and forecast timing

Success schema2 uses a strict source-context variant. MODIS retains its reported
UTC acquisition minute. PM2.5 retains the local forecast calendar day and timezone,
UTC interval, and separate request/retrieval times. The browser displays the local
date string directly, without changing it to the viewer's timezone. Old runtime
identities and schema1 responses are refused.

PM2.5 graphics contain all24 instantaneous hourly samples and their independently
recomputed sample mean. They identify CAMS via Open-Meteo and the sampled grid point;
they are model forecasts, not station measurements, measured exposure or health
thresholds. Related, extended, station-corroborated, dust, incomplete and legacy
packets are refused without removing evidence or repairing values. The full text
description preserves hourly values, grid/time bounds and retained-record limits.
No image establishes independent acquisition authenticity or source currentness.

## Observed station-temperature comparison

The GHCN preview uses the existing temperature adapter unchanged. It compares one
observed daily station maximum or minimum with the qualified available accepted
archive, month or calendar-date samples. Forecast, reanalysis, gridded, legacy and
unqualified archives have no substitute. Source revision, station, units, dates,
QC, coverage and the pre-observation comparator cutoff are rechecked before
rendering. Missing and rejected source cells remain exclusions. The comparison
does not certify an official record or a citywide reading.

The caption preserves the station ID and source-calendar date, labels the value
observed, and states that the reporting interval and timezone are unknown. The
archive retrieval timestamp is shown separately; it does not establish a UTC
observation day or publication-time QC. The full image description preserves the
source and comparator limitations. Existing text/evidence/policy/runtime identity
and the two-read change fence still apply. Temperature is enabled only for this
read-only SVG preview; the experimental native editor/attachment path has not
adopted it. No new provider call, automatic render, review or posting authority is
created.

## Reproducible package and checks

The generated archive contains an explicit allowlist of public Python source,
the existing font and its license, and the byte-identical public place/country
registries. Resource destinations and original source paths are explicitly bound;
the archive uses embedded registry reads without extracting files. Ordinary source
checkouts retain their existing data-directory readers. Registry bytes and reader
code also participate in editorial policy identity. It retains the scientific guards used by the
shared adapter. The manifest binds every file, archive bytes, policy source,
entrypoint, Python dependency manifest and lock. The entrypoint verifies the
package before importing it without extraction or downloads. A bad or missing
package returns a private unavailable response.

Story-builder exports load only their owning module. This lets the package retain
the complete air-quality reconstruction without importing unrelated hazard adapters.
The native preview uses pinned `tzdata` with system timezone paths disabled and
clears pre-existing timezone caches; a missing or incompatible package fails closed.
The bot's timezone configuration and source rules are unchanged. These dependencies
support the same complete forecast reconstruction used by the source adapter.

After changing a packaged source or dependency, run:

```sh
python scripts/gen_editorial_policy.py
python scripts/gen_dashboard_graphic_runtime.py
python scripts/gen_dashboard_graphic_runtime.py --check
python -m pytest tests/test_dashboard_pm25_preview.py tests/test_dashboard_graphic_auth.py tests/test_dashboard_graphic_reader.py tests/test_dashboard_graphic_preview.py tests/test_dashboard_graphic_http.py tests/test_dashboard_graphic_runtime.py tests/test_evidence_graphic_render.py tests/test_fire_graphic_adapter.py -q -m 'not voice_replay'
python -m pytest tests/test_intern_import_boundaries.py tests/test_graphic_runtime_resources.py tests/test_places.py tests/test_air_quality_graphic_adapter.py -q -m 'not voice_replay'
cd dashboard
npm test
npm run build
```

Install the existing optional `requirements-graphics.txt` for Python renderer
tests. Native Vercel builds use the dashboard's pinned Python 3.12 dependency lock.
Required offline CI verifies archive and manifest freshness rather than silently
regenerating them. Follow normal reviewed-head release checks and manual dashboard
deployment. Verify native extensionless and `.py` routes on the generated hostname
and every alias. Anonymous protection checks alone do not establish signed-in UI
behavior or a working production source bundle.
