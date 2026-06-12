# Mirror Survey - 2026-06-12

THIRTY-LOOP S-13 survey of the 403-cluster and NASA-style sources. Verdicts:

- `CHAIN`: plausible future code path can serve equivalent source payloads.
- `WITNESS`: useful official corroboration or operator diagnosis, but not a drop-in feed.
- `NONE`: no verified official alternate suitable for chaining in the bot.

## Verification Probes

GeoRSS gate:

```text
curl -s "https://www.gdacs.org/xml/rss.xml" | head -50
status: RSS served; first item includes gdacs:eventid, gdacs:eventtype, gdacs:alertlevel,
gdacs:episodealertlevel, gdacs:fromdate, georss:point, geo:Point, gdacs:country.
```

Survey probes:

```text
https://www.metoc.navy.mil/jtwc/jtwc.html
status=403 type=text/html bytes=919
```

```text
https://coastwatch.noaa.gov/erddap/griddap/noaacrwdhwDaily.html
status=200 type=text/html;charset=UTF-8 bytes=62084
```

```text
https://api.water.noaa.gov/nwps/v1/gauges/07010000
status=202 type=text/html; charset=UTF-8 bytes=0
```

```text
https://mapping.emergency.copernicus.eu/activations/
status=200 type=text/html; charset=utf-8 bytes=15729
```

```text
https://firms.modaps.eosdis.nasa.gov/api/area/csv/MAP_KEY/VIIRS_NOAA20_NRT/world/1
status=400 type=text/plain;charset=UTF-8 bytes=16
body: Invalid MAP_KEY.
```

```text
https://cmr.earthdata.nasa.gov/search/granules.json?short_name=GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4&page_size=1
status=200 type=application/json;charset=utf-8 bytes=3774
```

```text
https://nsidc.org/api/snow-today/snow-water-equivalent/points/swe.json
status=200 type=application/json bytes=139461
body prefix: {"metadata":{"last_date_with_data":"2026-06-11"},"data":[...
```

```text
https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv
status=200 type=application/octet-stream bytes=1867472
body prefix: Year, Month, Day, Extent, Missing, Source Data
```

## Verdicts

| Source | Current endpoint(s) | Candidate official mirror / alternate | Verification | Verdict | Notes |
|---|---|---|---|---|---|
| `jtwc` | `https://www.metoc.navy.mil/jtwc/rss/jtwc.rss?layout=enhanced`, plus warning-product `.txt` links from RSS descriptions. | JTWC public warning page at `https://www.metoc.navy.mil/jtwc/jtwc.html`. | Curl returned 403 for the page from this environment. | `NONE` | The page is official, but not a verified chainable feed. NHC advisories are not a full JTWC mirror for west-Pacific/Indian Ocean storms. |
| `coral_dhw` | NOAA Coral Reef Watch virtual-station index `https://coralreefwatch.noaa.gov/product/vs/data.php` and station text files under `/product/vs/data/`. | NOAA CoastWatch ERDDAP CRW 5 km DHW grid `https://coastwatch.noaa.gov/erddap/griddap/noaacrwdhwDaily.html`. | Curl returned 200 and the ERDDAP dataset page. | `CHAIN` | Official grid can support a future station/region sampling chain, but needs region mapping and grid subsetting before replacing station text files. |
| `river_gauges` | USGS IV API `https://waterservices.usgs.gov/nwis/iv/` for live gauge heights; NOAA NWPS `https://api.water.noaa.gov/nwps/v1/gauges/{site_id}` for flood-stage metadata. | NOAA NWPS gauge API as a stage-category witness. | Curl to `07010000` returned 202 with empty body. | `WITNESS` | This source is already dual-host, but the legs are complementary, not mirrors: USGS supplies readings; NWPS supplies thresholds/metadata. |
| `copernicus_ems` | Rapid Mapping dashboard APIs under `https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/`. | Public activation pages under `https://mapping.emergency.copernicus.eu/activations/`. | Curl returned 200 HTML for the activation listing. | `WITNESS` | Official pages can confirm activation existence during API failures, but parsing HTML would not provide the same structured impact stats. |
| `firms` | NASA FIRMS area CSV `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/world/{days}` with `VIIRS_SNPP_NRT` by default. | Same API with alternate official products such as `VIIRS_NOAA20_NRT`, `VIIRS_SNPP_SP`, or MODIS variants. | Curl with placeholder key returned `400 Invalid MAP_KEY`, confirming auth gating before product verification. | `CHAIN` | Product alternates can cover source-product outages when the API host and key are healthy. They do not solve host/IP reputation failures. |
| `ice_mass` | NASA CMR `https://cmr.earthdata.nasa.gov/search/granules.json` resolves PO.DAAC archive `.txt` granules under `archive.podaac.earthdata.nasa.gov`. | CMR metadata / PO.DAAC cloud links as operator witness; potential future S3 path would require Earthdata-cloud credential handling. | CMR query returned 200 JSON for the Greenland short name. | `WITNESS` | Current resolver already avoids hard-coded archive filenames. No drop-in HTTP mirror was verified. |
| `nsidc_snow` | NSIDC Snow Today API `https://nsidc.org/api/snow-today/snow-water-equivalent/points/swe.json`. | No verified official mirror for the same station SWE point payload. | Curl returned 200 JSON with `metadata.last_date_with_data=2026-06-11`. | `NONE` | Keep retry/revalidation on the existing endpoint; future fallback would need a different product model, not a mirror. |
| `sea_ice` | NSIDC/NOAA Sea Ice Index CSVs on `noaadata.apps.nsidc.org`, north/south v4.0 daily files. | The current noaaData host is the official alternate relative to older NSIDC paths; no second chainable mirror verified. | Curl returned 200 for the Arctic v4.0 CSV. | `NONE` | Current endpoint is healthy and validator-backed. If noaaData fails, a future chain would need a separately verified NSIDC distribution path. |
