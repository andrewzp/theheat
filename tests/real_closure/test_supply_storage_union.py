"""Invented NOAA product through the composed real loaders, Node and graphic.

No retained weather, provider request, model result or platform delivery is used.
"""
from copy import deepcopy

import pytest

from src.data import ghcnd_monthly_normals as gn
from src.editorial import hot10_contract as contract
from src.media import gist_media
from src.two_bot.intern import build_hot10_bundle
from tests import gist_hazard_helpers as gh, live_content_harness as h
from tests.real_closure import supply_ghcnd_fixture as gf
from tests.test_evidence_json_roundtrip import wire


def source(tmp_path, *, coincident=False, zero=False):
    cities = tuple((name, zone, 0.0) for name, zone, _kind in h.CITIES) if zero else h.CITIES
    rows = gf.installed_rows(gh.HOT10_CAPTURE.month, cities, normal_c=0.0 if zero else h.NORMAL_C)
    if coincident:
        for row in rows:
            row.update(station_lat=row["lat"], station_lon=row["lon"], distance_km="0.0")
    path = gf.write_rows(tmp_path / gn.INSTALLED_NAME, rows)
    normals = gn.load_normals(path)
    temps = h.city_temps(gh.HOT10_CAPTURE, cities)
    if zero:
        # Use the actual adapter on zero-valued invented forecast payloads.
        from datetime import date
        from src.data.temperature_evidence import forecast_day
        for temp, (_name, zone, _kind) in zip(temps, cities, strict=True):
            payload = h.forecast_payload(temp.lat, temp.lon, zone=zone, max_c=0.0, now=gh.HOT10_CAPTURE)
            result = forecast_day(payload, retrieved_at=gh.HOT10_CAPTURE.isoformat())
            temp.temp_high_c, temp.evidence = result["max_c"], result["evidence"]
            temp.signal_date = date.fromisoformat(result["valid_date"])
    ranked = contract.qualify(temps, normals, sampled=len(cities), now=gh.HOT10_CAPTURE,
                              product=contract.GHCND_PRODUCT)
    assert ranked["complete"], ranked["universe"]
    return build_hot10_bundle(ranked["rows"], changes=[], event_id="invented-noaa-storage-union",
                              universe=ranked["universe"]).to_dict()


@pytest.mark.parametrize("coincident", [False, True])
@pytest.mark.parametrize("zero", [False, True])
def test_noaa_source_and_complete_graphic_survive_actual_node_storage(tmp_path, coincident, zero):
    bundle = source(tmp_path, coincident=coincident, zero=zero)
    frozen = deepcopy(bundle)
    original = gist_media.prepare_media(bundle, synthetic=True)
    stored = bundle
    for _ in range(2):
        stored = wire(stored)
        assert contract.validate_bundle(stored) == []
        assert contract.current_hold(stored, gh.HOT10_CAPTURE) is None
        after = gist_media.prepare_media(stored, synthetic=True)
        for key in ("png", "descriptor", "delivery_text", "full_text"):
            assert original[key] == after[key], key
    assert bundle == frozen
    assert "NOAA" in original["delivery_text"] and "mean daily maximum" in original["full_text"]


@pytest.mark.parametrize("field", ["first_year", "last_year"])
def test_noaa_year_metadata_cannot_use_measurement_numeric_equivalence(tmp_path, field):
    bundle = source(tmp_path)
    row = bundle["raw_signal_dump"]["cities"][0]
    row["baseline"][field] = float(row["baseline"][field])
    row["row_fingerprint"] = contract.row_fingerprint(row)
    assert contract.validate_bundle(bundle)
