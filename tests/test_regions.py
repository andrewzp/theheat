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
