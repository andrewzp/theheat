# Fire collection moves to NOAA-21

The default FIRMS collection sequence is now NOAA-21, NOAA-20, then MODIS.
An explicit NOAA-20 request tries NOAA-20, NOAA-21, then MODIS; an explicit MODIS
request uses MODIS alone within the FIRMS product chain. A healthy first product
stops the sequence and is reported as the primary source. A later product retains
its actual product, acquisition minute and degraded source-leg label.

This transition happens when this release is installed. It has no hidden clock
switch that could restore S-NPP collection after a clock rollback. Explicit S-NPP
collection returns a bounded `SourceSkipped` in strict mode and an empty result
in ordinary mode, before HTTP access. Internal collection entry points also reject
it; neither another FIRMS product nor HMS silently replaces that explicit request.

Historical S-NPP rows and qualified receipts remain supported, with either an unset
or matching S-NPP source leg. Their source attribution, dates, identities and
evidence are not rewritten. The [source-minute contract](2026-10-07-fire-source-time.md)
still governs acquisition time, typed confidence, freshness, legacy duplicate
holds and unsupported incident/simultaneity claims.

Valid empty or below-threshold input can advance to the next selected product.
Auth/configuration/schema errors stay visible. The existing HMS alternate-host
witness is considered only for eligible failure of every selected FIRMS product;
one reachable valid-empty response prevents a false host-outage inference. Its
geographic limits and evidence grade are unchanged. Each product retains the same
HTTP retry/timeout bounds; the default active product count falls from four to
three. That is a request bound, not measured monthly savings or global coverage.

NOAA's [October 1 update](https://coastwatch.star.nesdis.noaa.gov/cwn/news/2026-10-01/cessation-suomi-national-polar-orbiting-partnership-s-npp-data-update-1.html)
announces cessation of S-NPP delivery on November 2, 2026 at 13:00 UTC and recommends
NOAA-21 as primary and NOAA-20 as secondary. NASA's [area API documentation](https://firms.modaps.eosdis.nasa.gov/api/area/)
lists both NRT replacements. This advance application transition does not establish
the exact response NASA will return after retirement or current global availability.
Offline tests use invented packets, including dates before, at and well after the
announced cutoff. No credential-bearing API replay, model call, publishing
activation or historical correction is part of this release.
