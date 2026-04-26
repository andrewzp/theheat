"""Tests for src/editorial/simultaneous_format.py — roll-call routing."""

from src.editorial.simultaneous_format import (
    select_roll_call_subset,
    ROLL_CALL_MIN_STATIONS,
    ROLL_CALL_MIN_ELEVATION_SPREAD_M,
)


def _station(city, country, temp_c=40.0, elev=None, **extra):
    return {
        "city": city,
        "country": country,
        "temp_c": temp_c,
        "kind": "high",
        "old_record_c": temp_c - 2.0,
        "old_record_year": 2002,
        "margin_c": 2.0,
        "elevation_m": elev,
        **extra,
    }


class TestSelectRollCallSubset:
    def test_empty_stations_returns_none(self):
        assert select_roll_call_subset([]) is None

    def test_below_min_stations_returns_none(self):
        stations = [
            _station("A", "India", elev=10),
            _station("B", "India", elev=2000),
        ]
        # only 2 stations, threshold is 3
        assert select_roll_call_subset(stations) is None

    def test_same_country_with_elevation_spread_returns_group(self):
        stations = [
            _station("Janakpur", "Nepal", temp_c=37.5, elev=80),
            _station("Dang", "Nepal", temp_c=36.1, elev=663),
            _station("Dhankuta", "Nepal", temp_c=29.2, elev=1192),
        ]
        result = select_roll_call_subset(stations)
        assert result is not None
        assert len(result) == 3
        cities = {s["city"] for s in result}
        assert cities == {"Janakpur", "Dang", "Dhankuta"}

    def test_globally_scattered_returns_none(self):
        # 5 stations, all different countries — no group hits 3
        stations = [
            _station("Sevilla", "Spain", elev=30),
            _station("Lisbon", "Portugal", elev=10),
            _station("Rabat", "Morocco", elev=200),
            _station("Tunis", "Tunisia", elev=15),
            _station("Algiers", "Algeria", elev=205),
        ]
        assert select_roll_call_subset(stations) is None

    def test_same_country_but_flat_elevation_returns_none(self):
        # 4 Indian cities, all coastal — no altitude story
        stations = [
            _station("Mumbai", "India", elev=14),
            _station("Chennai", "India", elev=6),
            _station("Kolkata", "India", elev=9),
            _station("Visakhapatnam", "India", elev=45),
        ]
        assert select_roll_call_subset(stations) is None

    def test_largest_qualifying_group_wins(self):
        # India: 3 stations, big spread.  Pakistan: 4 stations, big spread.
        # Pakistan group is larger → it should win.
        stations = [
            _station("Mumbai", "India", elev=14),
            _station("Pune", "India", elev=560),
            _station("Shimla", "India", elev=2200),
            _station("Karachi", "Pakistan", elev=8),
            _station("Lahore", "Pakistan", elev=217),
            _station("Murree", "Pakistan", elev=2291),
            _station("Quetta", "Pakistan", elev=1680),
        ]
        result = select_roll_call_subset(stations)
        assert result is not None
        countries = {s["country"] for s in result}
        assert countries == {"Pakistan"}
        assert len(result) == 4

    def test_missing_elevations_excluded_from_spread_calc(self):
        # 4 Nepali stations but only 2 have elevations and the spread
        # between those 2 is large — should still qualify.
        stations = [
            _station("Janakpur", "Nepal", elev=80),
            _station("Pokhara", "Nepal", elev=None),
            _station("Birgunj", "Nepal", elev=None),
            _station("Dhankuta", "Nepal", elev=1192),
        ]
        result = select_roll_call_subset(stations)
        assert result is not None
        assert len(result) == 4

    def test_only_one_known_elevation_returns_none(self):
        # Can't compute spread with just one elevation value.
        stations = [
            _station("A", "Nepal", elev=80),
            _station("B", "Nepal", elev=None),
            _station("C", "Nepal", elev=None),
        ]
        assert select_roll_call_subset(stations) is None

    def test_threshold_constants_exposed_for_tuning(self):
        # The sibling module imports these as the dial — confirm they
        # exist so future tuning isn't a silent breaking change.
        assert ROLL_CALL_MIN_STATIONS >= 2
        assert ROLL_CALL_MIN_ELEVATION_SPREAD_M >= 100

    def test_blank_country_stations_are_skipped(self):
        # Three stations missing country shouldn't bucket together
        # under the empty-string key and qualify as a same-country
        # roll-call.
        stations = [
            _station("A", "", elev=50),
            _station("B", None, elev=900),
            _station("C", "  ", elev=1500),
        ]
        assert select_roll_call_subset(stations) is None

    def test_blank_country_stations_dont_block_real_country(self):
        # Real country qualifies; blank-country stations are dropped
        # but don't disqualify the real cluster.
        stations = [
            _station("Janakpur", "Nepal", temp_c=37.5, elev=80),
            _station("Dang", "Nepal", temp_c=36.1, elev=663),
            _station("Dhankuta", "Nepal", temp_c=29.2, elev=1192),
            _station("Mystery", "", elev=2000),
        ]
        result = select_roll_call_subset(stations)
        assert result is not None
        assert {s["country"] for s in result} == {"Nepal"}
        assert len(result) == 3

    def test_equal_size_groups_break_tie_deterministically(self):
        # Two countries each with exactly 3 qualifying stations and the
        # same elevation spread should always return the same group on
        # repeated calls. Tie-break order: largest spread, then
        # alphabetical country name.
        stations = [
            _station("CityA1", "Argentina", temp_c=42.0, elev=10),
            _station("CityA2", "Argentina", temp_c=41.0, elev=900),
            _station("CityA3", "Argentina", temp_c=40.0, elev=1810),
            _station("CityB1", "Brazil",    temp_c=42.0, elev=10),
            _station("CityB2", "Brazil",    temp_c=41.0, elev=900),
            _station("CityB3", "Brazil",    temp_c=40.0, elev=1810),
        ]
        # Argentina < Brazil alphabetically, equal size + spread → Argentina wins.
        result = select_roll_call_subset(stations)
        assert result is not None
        assert {s["country"] for s in result} == {"Argentina"}
        # And again, deterministic across repeated calls.
        for _ in range(5):
            again = select_roll_call_subset(stations)
            assert again is not None
            assert {s["country"] for s in again} == {"Argentina"}

    def test_larger_spread_wins_over_smaller_at_same_size(self):
        # Same group size, different spreads → larger spread wins.
        stations = [
            _station("X1", "Xland", elev=100),
            _station("X2", "Xland", elev=400),
            _station("X3", "Xland", elev=950),    # spread = 850
            _station("Y1", "Yland", elev=100),
            _station("Y2", "Yland", elev=900),
            _station("Y3", "Yland", elev=2500),   # spread = 2400
        ]
        result = select_roll_call_subset(stations)
        assert result is not None
        assert {s["country"] for s in result} == {"Yland"}
