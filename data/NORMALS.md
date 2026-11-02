# Hot10 point normals

`normals.csv` contains the `meteostat-normals-point-v1` baseline acquired on
2 November 2026: 440 catalogue locations in 135 countries, each with 12 months.
193 sampled locations had no complete acceptable product and remain excluded.
These are monthly point normals, not observed extremes or certified records.
Underlying daily sample coverage is unavailable in this product.

Source: [Meteostat and its meteorological data providers](https://meteostat.net).
The point calculation reproduces the pinned Meteostat Python 1.7.6 nearest-point
contract; the radius, elevation, period and completeness rules were preserved.
5,172 point-months use 1991–2020; 108 use the explicit 1961–1990 fallback.
The CSV records the product, coordinates, point, period and retrieval for each row.

The exact candidate manifest is `normals.manifest.json`; its SHA256 binds the
installed CSV. `normals.install-plan.json` records the preceding Git blob and
rollback. Its private acquisition paths are explicitly redacted. Original
station captures, bounded transport receipts and per-point partitions are retained
in the operator's acquisition evidence. No unsupported values were estimated.

Meteostat's current [developer data licence](https://dev.meteostat.net/license)
and [legal disclosure](https://meteostat.net/en/legal) state CC BY 4.0. The pinned
1.7.6 package and an older support page state CC BY-NC 4.0; that historical licence
description is retained unchanged in the acquisition contract. Credit Meteostat
and its data providers when reusing the data, include the applicable licence link,
and identify the point calculation as a transformation. This installation does
not establish a commercial licensing interpretation.

Hot10 compares qualified current Open-Meteo forecast daily highs with these point
normals only among sampled catalogue cities. It does not rank the world's hottest
places, imply simultaneous observations, or certify a historical record. The
existing source freshness, ten-place minimum, writer budget, factual checks and
publication guards still apply.
