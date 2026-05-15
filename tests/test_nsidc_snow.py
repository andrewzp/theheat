import responses

from src.data.nsidc_snow import (
    INCH_TO_MM,
    SNOW_TODAY_SWE_URL,
    SnowReading,
    detect_snow_extremes,
    fetch_snow_today,
    update_snow_tracking,
)


def _reading(station="Albro Lake", day="2026-05-14", swe=15.0, delta=2.0):
    return SnowReading(
        station=station,
        lat=45.6,
        lon=-111.96,
        elevation_m=2529.8,
        date=day,
        swe_mm=swe * INCH_TO_MM if swe is not None else None,
        swe_delta_mm=delta * INCH_TO_MM if delta is not None else None,
        swe_normalized_pct=33.0,
        event_id=f"nsidc_snow_{station}_{day}",
    )


class TestFetchSnowToday:
    @responses.activate
    def test_fetch_snow_today_parses_points(self):
        responses.add(
            responses.GET,
            SNOW_TODAY_SWE_URL,
            json={
                "metadata": {"last_date_with_data": "2026-05-14"},
                "data": [
                    {
                        "name": "Albro Lake",
                        "lon": -111.96,
                        "lat": 45.6,
                        "elevation_meters": 2529.8,
                        "swe_inches": 15.5,
                        "swe_delta_inches": -3.3,
                        "swe_normalized_pct": 33.0,
                    }
                ],
            },
            status=200,
        )

        readings = fetch_snow_today(strict=True)

        assert len(readings) == 1
        assert readings[0].station == "Albro Lake"
        assert readings[0].date == "2026-05-14"
        assert readings[0].swe_mm == 15.5 * INCH_TO_MM
        assert readings[0].swe_delta_mm == -3.3 * INCH_TO_MM

    @responses.activate
    def test_fetch_snow_today_strict_raises_on_bad_schema(self):
        import pytest
        from src.data.source_status import SourceFetchError

        responses.add(responses.GET, SNOW_TODAY_SWE_URL, json={"bad": []}, status=200)

        with pytest.raises(SourceFetchError):
            fetch_snow_today(strict=True)

    @responses.activate
    def test_fetch_snow_today_non_strict_returns_empty_on_http_error(self):
        responses.add(responses.GET, SNOW_TODAY_SWE_URL, status=500)

        assert fetch_snow_today() == []


class TestSnowDetection:
    def test_daily_swe_gain_record(self):
        state = {
            "snow_daily_swe_gain_records": {
                "albro_lake:05-14": {"mm": 20.0, "year": 2024},
            }
        }

        events = detect_snow_extremes([_reading(delta=2.0)], state)

        assert len(events) == 1
        assert events[0].kind == "daily_swe_gain_record"
        assert events[0].mm_swe == 2.0 * INCH_TO_MM
        assert events[0].previous_record_year == 2024

    def test_daily_swe_gain_record_requires_prior_record(self):
        assert detect_snow_extremes([_reading(delta=2.0)], {"snow_daily_swe_gain_records": {}}) == []

    def test_multi_day_blizzard_event(self):
        state = {
            "snow_recent_by_station": {
                "albro_lake": [
                    {"date": "2026-05-12", "mm": 20.0},
                    {"date": "2026-05-13", "mm": 18.0},
                ]
            }
        }

        events = detect_snow_extremes([_reading(delta=1.0)], state)

        blizzards = [event for event in events if event.kind == "multi_day_blizzard"]
        assert len(blizzards) == 1
        assert blizzards[0].consecutive_days == 3
        assert blizzards[0].mm_swe == 63.4

    def test_seasonal_snow_record(self):
        state = {
            "seasonal_snow_records": {
                "albro_lake": {
                    "mm": 300.0,
                    "year": 2025,
                    "years_of_archive": 12,
                }
            }
        }

        events = detect_snow_extremes([_reading(swe=15.0, delta=0.0)], state)

        seasonal = [event for event in events if event.kind == "seasonal_snow_record"]
        assert len(seasonal) == 1
        assert seasonal[0].years_of_archive == 12

    def test_update_snow_tracking_records_all_state_maps(self):
        state = {
            "snow_daily_swe_gain_records": {},
            "snow_recent_by_station": {},
            "seasonal_snow_records": {},
        }
        update_snow_tracking(state, [_reading()])

        assert state["snow_daily_swe_gain_records"]["albro_lake:05-14"]["mm"] == 2.0 * INCH_TO_MM
        assert len(state["snow_recent_by_station"]["albro_lake"]) == 1
        assert state["seasonal_snow_records"]["albro_lake"]["mm"] == 15.0 * INCH_TO_MM

    def test_null_swe_fields_are_accepted(self):
        events = detect_snow_extremes([_reading(swe=None, delta=None)], {})

        assert events == []
