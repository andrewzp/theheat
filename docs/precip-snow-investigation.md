# Precipitation + Snow Source Investigation

Lane 13 first pass, captured May 15, 2026.

## GPM IMERG Daily Precipitation

Entry point:

```bash
curl -L --max-time 30 -sS -D - https://gpm.nasa.gov/data
```

Result: `200 OK`, HTML overview page for NASA GPM precipitation data.

Daily IMERG Final product index:

```bash
curl -L --max-time 30 -sS -D - \
  https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07/
```

Result: `200 OK`, OPeNDAP Hyrax directory. The product is organized as
`/GPM_L3/GPM_3IMERGDF.07/{YYYY}/{MM}/`, not day-of-year folders. A concrete
daily file path observed:

```text
https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07/2025/01/3B-DAY.MS.MRG.3IMERG.20250101-S000000-E235959.V07B.nc4
```

Metadata schema:

```bash
curl -L --max-time 30 -sS -D - \
  https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07/2025/01/3B-DAY.MS.MRG.3IMERG.20250101-S000000-E235959.V07B.nc4.dds

curl -L --max-time 30 -sS -D - \
  https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07/2025/01/3B-DAY.MS.MRG.3IMERG.20250101-S000000-E235959.V07B.nc4.das
```

Observed fields:

- `precipitation[time=1][lon=3600][lat=1800]`, `Float32`, units `mm/day`.
- `MWprecipitation[time=1][lon=3600][lat=1800]`, `Float32`, units `mm/day`.
- `randomError[time=1][lon=3600][lat=1800]`, `Float32`, units `mm/day`.
- `probabilityLiquidPrecipitation[time=1][lon=3600][lat=1800]`, `Int16`, units `percent`.
- `lon[3600]`, degrees east.
- `lat[1800]`, degrees north.
- `_FillValue` for precipitation-like fields is `-9999.90039`.

Near-real-time daily product:

```bash
curl -L --max-time 30 -sS -D - \
  https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDL.07/

curl -L --max-time 30 -sS -D - \
  https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDL.07/2026/05/contents.html
```

Result: `200 OK`. The daily late-run product has current-month files. A concrete
file observed for May 2026:

```text
https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDL.07/2026/05/3B-DAY-L.MS.MRG.3IMERG.20260501-S000000-E235959.V07C.nc4
```

Implementation should use `GPM_3IMERGDL.07` for operational daily smoke and
record checks, while keeping `GPM_3IMERGDF.07` as the archive/final-product
reference.

Data access:

```bash
curl -g -L --max-time 30 -sS -D - \
  "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07/2025/01/3B-DAY.MS.MRG.3IMERG.20250101-S000000-E235959.V07B.nc4.ascii?precipitation[0:1:0][1799:1:1799][899:1:899],lat[899:1:899],lon[1799:1:1799]"
```

Result: redirect to Earthdata Login, then `401 Unauthorized` without credentials.
The response includes `WWW-Authenticate: Basic realm="Please enter your Earthdata
Login credentials..."`. Production fetches need `EARTHDATA_TOKEN` as a bearer
token, matching the existing GRACE-FO source pattern.

## NSIDC Snow Today

Entry point:

```bash
curl -L --max-time 30 -sS -D - https://nsidc.org/api/snow-today
```

Result: `302` to trailing slash, then `200 OK`, HTML directory index with:

- `common/`
- `snow-surface-properties/`
- `snow-water-equivalent/`

Snow water equivalent variables:

```bash
curl -L --max-time 30 -sS -D - \
  https://nsidc.org/api/snow-today/snow-water-equivalent/variables.json
```

Observed JSON keys:

- `swe_inches`, long name `Snow Water Equivalent`, unit field currently says `cm`.
- `swe_delta_inches`, long name `Change in Snow Water Equivalent`, unit field currently says `cm`.
- `swe_normalized_pct`, long name `Percentage of Median Snow Water Equivalent`, units `%`.

Point observations:

```bash
curl -L --max-time 30 -sS -D - \
  https://nsidc.org/api/snow-today/snow-water-equivalent/points/swe.json
```

Result: `200 OK`, public JSON. Observed shape:

```json
{
  "metadata": {"last_date_with_data": "2026-05-14"},
  "data": [
    {
      "name": "Albro Lake",
      "lon": -111.96,
      "lat": 45.6,
      "elevation_meters": 2529.8,
      "swe_inches": 15.5,
      "swe_delta_inches": -3.3,
      "swe_normalized_pct": 33.0
    }
  ]
}
```

Auth requirement: none observed for the Snow Today JSON endpoints. Keep fetches
plain `GET` with strict-mode error handling.

Snow surface properties:

```bash
curl -L --max-time 30 -sS -D - \
  https://nsidc.org/api/snow-today/snow-surface-properties/variables.json
```

Result: `200 OK`, MODIS/Terra variables for snow-cover percent, grain size,
dust/soot albedo effect, and related raster/plot products. Lane 13 should use
the SWE point feed first because it has direct point observations with daily
delta and median percentage fields.
