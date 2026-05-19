"""Tests for lat/lon → US state lookup."""

from src.editorial._regions import lat_lon_to_state


class TestLatLonToState:
    def test_interior_california(self):
        # Sacramento
        assert lat_lon_to_state(38.58, -121.49) == "California"

    def test_interior_texas(self):
        # Austin
        assert lat_lon_to_state(30.27, -97.74) == "Texas"

    def test_interior_florida(self):
        # Miami
        assert lat_lon_to_state(25.76, -80.19) == "Florida"

    def test_interior_alaska(self):
        # Anchorage
        assert lat_lon_to_state(61.22, -149.90) == "Alaska"

    def test_interior_new_york(self):
        # NYC
        assert lat_lon_to_state(40.71, -74.01) == "New York"

    def test_outside_us_mexico(self):
        # Mexico City
        assert lat_lon_to_state(19.43, -99.13) is None

    def test_outside_us_london(self):
        assert lat_lon_to_state(51.51, -0.13) is None

    def test_outside_us_pacific(self):
        assert lat_lon_to_state(0.0, -150.0) is None

    def test_border_lake_tahoe_picks_one(self):
        # Lake Tahoe is on the CA/NV border; disambiguation must pick one.
        result = lat_lon_to_state(39.10, -120.04)
        assert result in {"California", "Nevada"}


class TestCitiesToStateMap:
    def test_us_cities_mapped(self):
        from src.editorial._regions import cities_to_state_map
        cities = [
            {"city": "Sacramento", "latitude": 38.58, "longitude": -121.49, "country": "United States"},
            {"city": "Austin",     "latitude": 30.27, "longitude": -97.74,  "country": "United States"},
        ]
        assert cities_to_state_map(cities) == {
            "Sacramento": "California",
            "Austin": "Texas",
        }

    def test_csv_lat_lon_headers_are_mapped(self):
        from src.editorial._regions import cities_to_state_map
        cities = [
            {"city": "Sacramento", "lat": "38.58", "lon": "-121.49", "country": "United States"},
        ]
        assert cities_to_state_map(cities) == {"Sacramento": "California"}

    def test_non_us_cities_skipped(self):
        from src.editorial._regions import cities_to_state_map
        cities = [
            {"city": "Sacramento", "latitude": 38.58, "longitude": -121.49, "country": "United States"},
            {"city": "London",     "latitude": 51.51, "longitude": -0.13,   "country": "United Kingdom"},
        ]
        assert cities_to_state_map(cities) == {"Sacramento": "California"}

    def test_missing_coords_skipped(self):
        from src.editorial._regions import cities_to_state_map
        cities = [{"city": "Broken", "latitude": None, "longitude": None, "country": "United States"}]
        assert cities_to_state_map(cities) == {}
