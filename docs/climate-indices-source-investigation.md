# Lane 14 source investigation: climate indices

Checked on 2026-05-14 with `curl -L --fail --max-time 30`.

## NAO

- Brief URL: `https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/nao.txt`
- Result: 404.
- Verified URL: `https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.nao.monthly.b5001.current.ascii`
- Schema: whitespace-delimited rows, no header, `year month value`.
- Sample:

```text
1950    1    0.9200
1950    2    0.4000
1950    3   -0.3600
```

## AO

- Brief URL: `https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ao.txt`
- Result: 404.
- Verified URL: `https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_ao_index/monthly.ao.index.b50.current.ascii`
- Schema: whitespace-delimited rows, no header, `year month value`.
- Sample:

```text
1950    1   -0.0603
1950    2    0.6268
1950    3   -0.0081
```

## PDO

- Brief URL: `https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/pdo.txt`
- Result: 404.
- Verified URL: `https://psl.noaa.gov/pdo/data/pdo.timeseries.ersstv5.data`
- Schema: first row is `start_year end_year`; following rows are `year jan feb ... dec`.
- Sample:

```text
1854 2026
1854     0.050    -0.090     0.138     0.131    -0.064     0.005    -0.201    -0.849    -0.727    -1.597    -1.301    -1.582
```

## Antarctic ozone hole

- Brief source: `https://ozonewatch.gsfc.nasa.gov/data/`
- Result: directory listing of gridded Level 3 ozone text files, not the seasonal area CSV implied by the brief.
- Verified daily area URL pattern: `https://ozonewatch.gsfc.nasa.gov/meteorology/figures/ozone/to3areas_{year}_toms+omi+omps.txt`
- Verified annual peak URL: `https://ozonewatch.gsfc.nasa.gov/statistics/ytd_data.txt`
- Daily area schema: header metadata, then fixed-width/whitespace rows:
  `Date Data Minimum 10% 30% Mean 70% 90% Maximum`. Units are million km2.
- Annual peak schema: comment/header lines, then fixed-width/whitespace rows:
  `Year area_date_mmdd area_million_km2 min_ozone_date_mmdd min_ozone_du`.
- Daily sample:

```text
Name: Ozone Hole Area
Units: Million km!U2!N
Source: toms+omi+omps
Missing: -9999.0
Climatology: 1979 to 2025
Date            Data   Minimum     10%     30%    Mean     70%     90% Maximum
2026-01-01      0.00      0.00    0.00    0.00    0.00    0.00    0.00    0.00
```

Annual sample:

```text
# Maximum of daily ozone hole area
# Minimum of daily minimum ozone
         Ozone Hole Area       Minimum Ozone
          Date     Value      Date     Value
Year    (YYMM) (mil km2)    (YYMM)      (DU)
1979      0917       1.1      0917     194.0
1980      0921       3.3      1016     192.0
```
