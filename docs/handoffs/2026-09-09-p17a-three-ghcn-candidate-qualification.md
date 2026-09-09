# P17a: three GHCN candidates checked against original NOAA bytes

**Result: none of these three station candidates qualifies for a timely observed-temperature pilot at this retrieval.** This is a station/snapshot finding, not a conclusion about Spain, India, South Africa or their national services. It supplements the [initial pilot checklist](2026-09-09-p17a-observed-temperature-pilots.md); no routing or operational settings changed.

At **2026-09-09 15:29:40–41 UTC**, exactly four free public NOAA requests retrieved one shared GHCN format document and one archive each for Madrid-Retiro, Madras/Minambakkam and Cape Town International. All returned HTTP 200 within the existing 8 MB archive bound. There were no retries, redirects, additional stations, recentdiff downloads, model calls or writes to live state/database. Original bytes, URLs, response headers, retrieval times and hashes are retained privately.

## Observation availability

| Candidate | Latest source-accepted TMAX date | Latest source-accepted TMIN date | Source-date age at retrieval: max / min | Timely pilot disposition |
| --- | --- | --- | --- | --- |
| `SP000003195`, Madrid-Retiro | 2026-09-04 | 2026-09-04 | 5 / 5 days | Outside the current inclusive 0–4 day news window. |
| `IN020040900`, Madras/Minambakkam | 2025-08-23 | 2025-08-23 | 382 / 382 days | No timely accepted temperature in this archive snapshot. |
| `SFM00068816`, Cape Town International | 2025-08-21 | 2025-08-11 | 384 / 394 days | Neither variable is timely; their latest accepted dates differ. |

These are **source-date age screens against the UTC retrieval date**, not measured elapsed reporting latency: the `.dly` format does not establish these stations' exact observation interval/timezone. There were no accepted TMAX/TMIN values in the September 5–9 window for any candidate. Madrid has represented but missing cells in that window; the other two files do not represent it. All three HTTP Last-Modified headers are dated September 9, demonstrating why a freshly modified archive is not evidence of a fresh station observation. [Madrid archive](https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/SP000003195.dly), [Madras archive](https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/IN020040900.dly), [Cape Town archive](https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/SFM00068816.dly).

“Source-accepted” here means finite, nonmissing temperature with blank QFLAG, not independently certified measurement accuracy. The latest Madrid values have MFLAG `H`: hourly-derived extrema; their SFLAG `2` identifies Synoptic Summary of the Day version 2. The latest Madras/Cape Town values carry SFLAG `S`, Global Summary of the Day, which NOAA describes as derived from hourly synoptic reports. Preserve those measurement/source flags in any later claim; do not upgrade sampled extrema into certified station records. The format document calls `2` the successor to `S`, but **this check does not establish why these two station files stopped, whether newer identifiers exist or whether another product has current readings**. [NOAA GHCN format and flag definitions](https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt).

## Separate comparator failure

Offline replay through the existing `_archive_snapshot`, `_thresholds_from_verified_archive` and `record_comparison_qualified` helpers rejected **all six variable comparisons**, even at their old latest accepted dates. The following counts cover each variable's first accepted sample through its candidate day minus one; the candidate cannot contribute to its own comparator.

| Station / variable | Requested prior cutoff | Latest accepted prior sample | Omitted source-calendar days | Explicit missing cells | QC-rejected cells |
| --- | --- | --- | ---: | ---: | ---: |
| Madrid TMAX | 2026-09-03 | 2026-09-03 | 123 | 135 | 14 |
| Madrid TMIN | 2026-09-03 | 2026-09-03 | 123 | 137 | 13 |
| Madras TMAX | 2025-08-22 | 2025-08-22 | 4,753 | 4,294 | 1 |
| Madras TMIN | 2025-08-22 | 2025-08-21 | 4,358 | 6,295 | 4 |
| Cape Town TMAX | 2025-08-20 | 2025-08-20 | 1,765 | 2,759 | 0 |
| Cape Town TMIN | 2025-08-10 | 2025-07-29 | 2,252 | 5,446 | 0 |

Every variable's **verified source cutoff is null**. Accepted-sample dates do not repair omitted intervals. Madrid's two missing intervals are December 1936–January 1937 and October–November 2025. Explicit missing/QC cells are separately visible exclusions; this result does not conflate them with omitted source months. The variables contain 107, 59 and 49 distinct accepted-sample years respectively, but those counts alone do not satisfy the source-calendar gate or certify complete physical history. No gate was relaxed to obtain a pilot.

## Evidence retention and verification

Private package: `.gstack/pilots/2026-09-09-p17a/` in the original checkout. `retrieval-manifest.json` binds all four original downloads. `qualification-report.json` contains variable scopes, exact candidate cells, QC/missing counts, omitted date intervals and refusal reasons; per-station reports and the previous local metadata extract are separate. Metadata was reused from the checksum-verified local database, not newly recovered from NOAA's station metadata file.

| Original payload | Bytes | SHA-256 |
| --- | ---: | --- |
| `SP000003195.dly` | 1,043,820 | `61aa2fc70430cb9407533f65caf89bf0c5e6010c62d9449365630d8ea9083ecb` |
| `IN020040900.dly` | 928,260 | `382528dfb7735860caee89ec07377e47ed9f32c3d492828327f1fe3b442d0416` |
| `SFM00068816.dly` | 628,830 | `1bf4325101f3bcf1e3edac37cb6b8724063643dddb715973be0f5e38909f1fe5` |
| `ghcn-readme.txt` | 28,567 | `3a71ae355252a6693a56a473ed7182b500ae7816c2cb2b2ce708c1e9ea9dcfde` |

`analyze_offline.py` blocks socket connections, checks source hashes and uses the existing production qualification helpers from the `b65ff01` worktree. A separate direct fixed-width parse agreed on accepted counts and the latest date/value/flags for all six variables; independently enumerated calendar gaps matched the qualifier counts. No synthetic weather or replacement values were introduced. The format document declares version 3.34; this is not an independently recovered release identifier for each archive file. No paid or full application test suite is claimed for this read-only acquisition.

## Next decision

Keep these three candidates marked **failed current qualification**, with freshness and baseline gaps recorded separately. Do not activate the non-US route on the strength of these results. A later bounded candidate/service qualification may investigate alternatives, but none was fetched or substituted here. Redistribution/access terms, exact reporting intervals, source-discovery arrival through recentdiff, repeat latency and a successful observed `StoryBundle`/graphic remain unproven. These snapshots neither measure regional recall nor establish the truth of the old Chennai tweet; no public correction follows from this work.
