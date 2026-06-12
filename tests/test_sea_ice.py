"""Tests for NSIDC sea ice extent data."""

from datetime import date, timedelta

import responses

from src.data.sea_ice import SeaIceReading, SeaIceRecord, fetch_sea_ice, detect_record_low

FRESH_DAY = date.today() - timedelta(days=1)
FRESH_ROW = f"{FRESH_DAY.year}, {FRESH_DAY.month:4d}, {FRESH_DAY.day:4d}"

SAMPLE_CSV = f"""Year, Month, Day, Extent, Missing, Source Data
 , , , in 10^6 sq km, ,
 1979,    1,    1,  13.234,       0, source
 1980,    1,    1,  13.100,       0, source
 2024,    1,    1,  12.800,       0, source
 {FRESH_ROW},  12.500,       0, source
"""

SAMPLE_CSV_NO_RECORD = f"""Year, Month, Day, Extent, Missing, Source Data
 , , , in 10^6 sq km, ,
 1979,    1,    1,  13.234,       0, source
 1980,    1,    1,  13.100,       0, source
 {FRESH_ROW},  13.300,       0, source
"""


class TestFetchSeaIce:
    @responses.activate
    def test_happy_path_arctic(self):
        responses.add(
            responses.GET,
            "https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv",
            body=SAMPLE_CSV,
            status=200,
        )
        readings = fetch_sea_ice(hemisphere="Arctic")
        assert len(readings) == 4
        assert all(isinstance(r, SeaIceReading) for r in readings)
        assert readings[0].hemisphere == "Arctic"
        assert readings[0].extent_million_km2 == 13.234

    @responses.activate
    def test_happy_path_antarctic(self):
        responses.add(
            responses.GET,
            "https://noaadata.apps.nsidc.org/NOAA/G02135/south/daily/data/S_seaice_extent_daily_v4.0.csv",
            body=SAMPLE_CSV,
            status=200,
        )
        readings = fetch_sea_ice(hemisphere="Antarctic")
        assert len(readings) == 4
        assert readings[0].hemisphere == "Antarctic"

    @responses.activate
    def test_api_error_returns_empty(self):
        responses.add(
            responses.GET,
            "https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv",
            status=500,
        )
        assert fetch_sea_ice(hemisphere="Arctic") == []

    @responses.activate
    def test_skips_invalid_rows(self):
        bad_csv = f"""Year, Month, Day, Extent, Missing, Source Data
 , , , in 10^6 sq km, ,
 1979,    1,    1,  13.234,       0, source
 bad,  row,  here
 {FRESH_ROW},  12.500,       0, source
"""
        responses.add(
            responses.GET,
            "https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv",
            body=bad_csv,
            status=200,
        )
        readings = fetch_sea_ice(hemisphere="Arctic")
        assert len(readings) == 2


class TestDetectRecordLow:
    def test_detects_record_low(self):
        readings = [
            SeaIceReading("Arctic", 13.234, "1979-01-01", "sea_ice_arctic_1979-01-01"),
            SeaIceReading("Arctic", 13.100, "1980-01-01", "sea_ice_arctic_1980-01-01"),
            SeaIceReading("Arctic", 12.800, "2024-01-01", "sea_ice_arctic_2024-01-01"),
            SeaIceReading("Arctic", 12.500, "2025-01-01", "sea_ice_arctic_2025-01-01"),
        ]
        record = detect_record_low(readings)
        assert record is not None
        assert isinstance(record, SeaIceRecord)
        assert record.extent_million_km2 == 12.500
        assert record.previous_extent == 12.800
        assert record.previous_year == 2024
        assert record.record_type == "lowest"

    def test_no_record_when_not_lowest(self):
        readings = [
            SeaIceReading("Arctic", 13.234, "1979-01-01", "sea_ice_arctic_1979-01-01"),
            SeaIceReading("Arctic", 13.100, "1980-01-01", "sea_ice_arctic_1980-01-01"),
            SeaIceReading("Arctic", 13.300, "2025-01-01", "sea_ice_arctic_2025-01-01"),
        ]
        assert detect_record_low(readings) is None

    def test_empty_readings_returns_none(self):
        assert detect_record_low([]) is None

    def test_single_reading_returns_none(self):
        readings = [
            SeaIceReading("Arctic", 13.234, "2025-01-01", "sea_ice_arctic_2025-01-01"),
        ]
        assert detect_record_low(readings) is None
