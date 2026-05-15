import pytest

from src.data._climate_context import CLIMATE_CONTEXT_REGIONS, local_climate_context


@pytest.mark.parametrize("region", CLIMATE_CONTEXT_REGIONS, ids=lambda region: region.key)
def test_each_curated_region_resolves_from_representative_point(region):
    ctx = local_climate_context(region.sample_lat, region.sample_lon)

    assert ctx is not None
    assert ctx.region_climate_system == region.context.region_climate_system


def test_lookup_is_inclusive_at_bounding_box_boundaries():
    sahel = next(region for region in CLIMATE_CONTEXT_REGIONS if region.key == "sahel")

    assert local_climate_context(sahel.lat_min, sahel.lon_min) == sahel.context
    assert local_climate_context(sahel.lat_max, sahel.lon_max) == sahel.context


def test_specific_context_wins_when_boxes_overlap():
    ctx = local_climate_context(28.2, -81.1)

    assert ctx is not None
    assert ctx.region_climate_system == "the Florida sea-breeze zone"


def test_dateline_crossing_region_accepts_negative_longitudes():
    ctx = local_climate_context(-15.0, -170.0)

    assert ctx is not None
    assert ctx.region_climate_system == "the South Pacific Convergence Zone"


def test_longitudes_are_normalized_from_0_to_360():
    ctx = local_climate_context(-15.0, 190.0)

    assert ctx is not None
    assert ctx.region_climate_system == "the South Pacific Convergence Zone"


def test_out_of_table_point_returns_none():
    assert local_climate_context(80.0, 0.0) is None


def test_invalid_latitude_returns_none():
    assert local_climate_context(91.0, 0.0) is None


def test_curated_entries_have_source_metadata():
    for region in CLIMATE_CONTEXT_REGIONS:
        assert region.source_title
        assert region.source_url.startswith("https://")
