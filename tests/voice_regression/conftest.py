"""Bundle fixtures for the live writer-replay regression suite.

These fixtures construct realistic StoryBundle instances spanning the most
common signal_kinds. Tests in test_writer_replay.py call the real writer
(Sonnet) against each bundle and assert the output passes the safety
pipeline.

To add a new bundle: copy one of the existing `_*_bundle()` fixture
factories, adjust the fields, and parametrize it into the tests in
test_writer_replay.py.
"""

from __future__ import annotations

import pytest

from src.two_bot.types import MemorySlice, StoryBundle


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "voice_replay: live writer-replay test (calls real Anthropic API; "
        "skipped by default, run via the voice-regression workflow)",
    )


# ---------------------------------------------------------------------------
# Bundle fixtures — one per representative signal_kind
# ---------------------------------------------------------------------------


@pytest.fixture
def sissonville_monthly_low_bundle() -> StoryBundle:
    """US Fahrenheit-first, monthly_low, archive-window-only.

    Mirrors the actual Sissonville WV tweet shipped 2026-05-04. Exercises:
    Fahrenheit-first audience routing, archive_window_only language
    constraint, anti-fabrication on temporal/seasonal framing.
    """
    return StoryBundle(
        signal_kind="monthly_low",
        where="Sissonville, West Virginia",
        when="2026-05-04",
        event_id="ghcn_monthly_low_USW00013866_2026_05",
        headline_metric={
            "label": "observed_low_c",
            "value": -2.2,
            "unit": "C",
            "value_f": 28,
        },
        current_facts=[
            {"label": "city", "value": "Sissonville"},
            {"label": "country", "value": "US"},
            {"label": "state", "value": "West Virginia"},
            {"label": "month", "value": "May"},
            {"label": "kind", "value": "low"},
            {"label": "today_temp_c", "value": -2.2},
            {"label": "today_temp_f", "value": 28},
            {"label": "observation_kind", "value": "daily_minimum"},
            {"label": "audience_unit", "value": "fahrenheit_first"},
        ],
        historical_context={
            "prior_record_c": -1.7,
            "prior_record_f": 29,
            "prior_record_year": 2020,
            "archive_years": 16,
            "month": "May",
            "margin_c": -0.5,
            "margin_f": -1,
            "archive_window_only": True,
        },
        raw_signal_dump={
            "city": "Sissonville",
            "country": "US",
            "state": "West Virginia",
            "kind": "low",
            "month": 5,
            "new_temp_c": -2.2,
            "old_record_c": -1.7,
            "old_record_year": 2020,
            "years_of_data": 16,
        },
    )


@pytest.fixture
def dayton_monthly_low_bundle() -> StoryBundle:
    """The Dayton WY bundle that triggered two fact-check kills on 2026-05-08
    for invented temporal framing ("January reading", "three weeks into
    meteorological spring"). Replaying this regularly verifies the writer
    no longer fabricates context for cold-anomaly bundles in Wyoming.
    """
    return StoryBundle(
        signal_kind="monthly_low",
        where="Dayton, Wyoming",
        when="2026-05-05",
        event_id="ghcn_monthly_low_USC00482409_2026_05",
        headline_metric={
            "label": "observed_low_c",
            "value": -9.4,
            "unit": "C",
            "value_f": 15,
        },
        current_facts=[
            {"label": "city", "value": "Dayton"},
            {"label": "country", "value": "US"},
            {"label": "state", "value": "Wyoming"},
            {"label": "month", "value": "May"},
            {"label": "kind", "value": "low"},
            {"label": "today_temp_c", "value": -9.4},
            {"label": "today_temp_f", "value": 15},
            {"label": "observation_kind", "value": "daily_minimum"},
            {"label": "audience_unit", "value": "fahrenheit_first"},
        ],
        historical_context={
            "prior_record_c": -8.3,
            "prior_record_f": 17,
            "prior_record_year": 2010,
            "archive_years": 21,
            "month": "May",
            "margin_c": -1.1,
            "margin_f": -2,
            "archive_window_only": True,
        },
        raw_signal_dump={
            "city": "Dayton",
            "country": "US",
            "state": "Wyoming",
            "kind": "low",
            "month": 5,
            "new_temp_c": -9.4,
            "old_record_c": -8.3,
            "old_record_year": 2010,
            "years_of_data": 21,
        },
    )


@pytest.fixture
def verkhoyansk_monthly_high_bundle() -> StoryBundle:
    """Non-US Celsius-first, monthly_high, exotic place name.

    Exercises: geographic orientation rule (Verkhoyansk → "Verkhoyansk,
    Russia"), Celsius-first audience routing, non-US audience_unit.
    """
    return StoryBundle(
        signal_kind="monthly_high",
        where="Verkhoyansk, Russia",
        when="2026-04-29",
        event_id="meteo_monthly_high_Verkhoyansk_2026_04",
        headline_metric={
            "label": "forecast_high_c",
            "value": 14.8,
            "unit": "C",
            "value_f": 59,
        },
        current_facts=[
            {"label": "city", "value": "Verkhoyansk"},
            {"label": "country", "value": "RU"},
            {"label": "month", "value": "April"},
            {"label": "kind", "value": "high"},
            {"label": "today_temp_c", "value": 14.8},
            {"label": "today_temp_f", "value": 59},
            {"label": "audience_unit", "value": "celsius_first"},
        ],
        historical_context={
            "prior_record_c": 12.3,
            "prior_record_f": 54,
            "prior_record_year": 2018,
            "archive_years": 30,
            "month": "April",
            "margin_c": 2.5,
            "margin_f": 5,
            "archive_window_only": True,
        },
        raw_signal_dump={
            "city": "Verkhoyansk",
            "country": "RU",
            "kind": "high",
            "month": 4,
            "new_temp_c": 14.8,
            "old_record_c": 12.3,
            "old_record_year": 2018,
            "years_of_data": 30,
        },
    )


@pytest.fixture
def mali_fire_bundle() -> StoryBundle:
    """Fire signal with no historical_context. Exercises: writer obeying
    the "if historical_context is empty, do not invent rarity claims"
    rule, named-power-plant peer comparison rule.
    """
    return StoryBundle(
        signal_kind="fire",
        where="Mali",
        when="2026-04-30",
        event_id="fire_13.5_-4.2_2026-04-30",
        headline_metric={"label": "FRP", "value": 361.0, "unit": "MW"},
        current_facts=[
            {"label": "satellite_confidence", "value": 95, "unit": "%"},
            {"label": "country", "value": "ML"},
            {"label": "nearest_region", "value": "Mali"},
            {"label": "lat", "value": 13.5},
            {"label": "lon", "value": -4.2},
        ],
        historical_context={},
        raw_signal_dump={
            "lat": 13.5,
            "lon": -4.2,
            "confidence": 95,
            "frp": 361.0,
            "nearest_city": "Mali",
            "country": "ML",
            "event_id": "fire_13.5_-4.2_2026-04-30",
        },
    )


@pytest.fixture
def cyclone_rapid_intensification_bundle() -> StoryBundle:
    """Cyclone RI: Cat 1 to Cat 4 in 24h, with Caribbean warm-pool context."""
    return StoryBundle(
        signal_kind="cyclone_rapid_intensification",
        where="Beryl, Atlantic",
        when="2026-07-02T00:00:00Z",
        event_id="nhc_ri_al012026_12_115",
        headline_metric={"label": "delta_kt_24h", "value": 40, "unit": "kt"},
        current_facts=[
            {"label": "source", "value": "NHC"},
            {"label": "storm_name", "value": "Beryl"},
            {"label": "basin", "value": "Atlantic"},
            {"label": "category", "value": 4},
            {"label": "wind_speed_kt", "value": 115, "unit": "kt"},
            {"label": "central_pressure_mb", "value": 950, "unit": "mb"},
            {"label": "lat", "value": 18.0},
            {"label": "lon", "value": -75.0},
            {"label": "advisory_number", "value": "12"},
            {"label": "public_advisory_url", "value": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"},
            {"label": "previous_wind_kt", "value": 75, "unit": "kt"},
            {"label": "previous_category", "value": 1},
            {"label": "delta_kt_24h", "value": 40, "unit": "kt"},
            {"label": "region_climate_system", "value": "the Caribbean warm pool"},
            {"label": "climate_mechanism_note", "value": "warm tropical waters feed humidity, heavy rain, and cyclone energy"},
            {"label": "season_context", "value": "Atlantic tropical warm-season regime"},
        ],
        historical_context={
            "window_hours": 24,
            "rapid_intensification_threshold_kt": 30,
        },
        raw_signal_dump={
            "storm_name": "Beryl",
            "basin": "Atlantic",
            "current_wind_kt": 115,
            "previous_wind_kt": 75,
            "delta_kt_24h": 40,
            "current_category": 4,
            "previous_category": 1,
        },
    )


@pytest.fixture
def cyclone_landfall_bundle() -> StoryBundle:
    """Major hurricane landfall, safety-sensitive and manual-only."""
    return StoryBundle(
        signal_kind="cyclone_landfall",
        where="Cedar Key, Florida",
        when="2026-07-02T00:00:00Z",
        event_id="nhc_landfall_al012026_12_cedar_key",
        headline_metric={"label": "category", "value": 3},
        current_facts=[
            {"label": "source", "value": "NHC"},
            {"label": "storm_name", "value": "Beryl"},
            {"label": "basin", "value": "Atlantic"},
            {"label": "category", "value": 3},
            {"label": "wind_speed_kt", "value": 100, "unit": "kt"},
            {"label": "central_pressure_mb", "value": 960, "unit": "mb"},
            {"label": "lat", "value": 29.1},
            {"label": "lon", "value": -83.0},
            {"label": "advisory_number", "value": "12"},
            {"label": "public_advisory_url", "value": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"},
            {"label": "landfall_location", "value": "Cedar Key, Florida"},
            {"label": "region_climate_system", "value": "the Gulf Coast humid subtropical belt"},
            {"label": "climate_mechanism_note", "value": "warm Gulf moisture feeds humid heat and heavy-rain setups"},
        ],
        historical_context={"scope": "major_hurricane_landfall"},
        raw_signal_dump={
            "storm_name": "Beryl",
            "basin": "Atlantic",
            "category": 3,
            "wind_kt": 100,
            "location": "Cedar Key, Florida",
        },
    )


@pytest.fixture
def cyclone_basin_record_bundle() -> StoryBundle:
    """Atlantic basin record fixture for archive-backed cyclone wording."""
    return StoryBundle(
        signal_kind="cyclone_basin_record",
        where="Beryl, Atlantic",
        when="2026-06-15T00:00:00Z",
        event_id="nhc_record_al012026_9_earliest_cat4",
        headline_metric={"label": "category", "value": 4},
        current_facts=[
            {"label": "source", "value": "NHC"},
            {"label": "storm_name", "value": "Beryl"},
            {"label": "basin", "value": "Atlantic"},
            {"label": "category", "value": 4},
            {"label": "wind_speed_kt", "value": 115, "unit": "kt"},
            {"label": "central_pressure_mb", "value": 950, "unit": "mb"},
            {"label": "lat", "value": 14.5},
            {"label": "lon", "value": -57.0},
            {"label": "advisory_number", "value": "9"},
            {"label": "public_advisory_url", "value": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"},
            {"label": "record_label", "value": "earliest Atlantic Category 4 on record"},
            {"label": "record_scope", "value": "Atlantic best-track archive"},
        ],
        historical_context={
            "record_label": "earliest Atlantic Category 4 on record",
            "record_scope": "Atlantic best-track archive",
            "scope": "basin_record",
        },
        raw_signal_dump={
            "storm_name": "Beryl",
            "basin": "Atlantic",
            "category": 4,
            "wind_kt": 115,
            "record_label": "earliest Atlantic Category 4 on record",
        },
    )


@pytest.fixture
def co2_milestone_bundle() -> StoryBundle:
    """CO2 milestone — no city, no temperature. Tests writer adapting to
    a non-place, non-temperature signal kind."""
    return StoryBundle(
        signal_kind="co2_milestone",
        where="Mauna Loa",
        when="2026-04-19",
        event_id="co2_milestone_436ppm",
        headline_metric={"label": "ppm_crossed", "value": 436, "unit": "ppm"},
        current_facts=[
            {"label": "ppm_crossed", "value": 436},
            {"label": "actual_ppm", "value": 436.1},
            {"label": "source", "value": "NOAA GML"},
            {"label": "station", "value": "Mauna Loa"},
            {"label": "audience_unit", "value": "fahrenheit_first"},
        ],
        historical_context={
            "preindustrial_ppm": 280,
            "first_400ppm_year": 2013,
            "ppm_growth_per_year_recent": 2.5,
        },
        raw_signal_dump={
            "ppm_crossed": 436,
            "actual_ppm": 436.1,
            "date": "2026-04-19",
            "event_id": "co2_milestone_436ppm",
        },
    )


@pytest.fixture
def fresh_memory_slice() -> MemorySlice:
    """Empty memory — all era anchors / peer comparisons / framings
    available. Used in replay tests so writer isn't constrained by
    test-irrelevant memory state."""
    return MemorySlice(
        recent_tweets_same_country=[],
        recent_tweets_same_event=[],
        ongoing_event=None,
        used_era_anchors=[],
        used_peer_comparisons=[],
        used_framings=[],
        shipped_tweet_texts=[],
    )
