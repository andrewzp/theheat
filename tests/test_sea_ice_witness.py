from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import responses
from netCDF4 import Dataset

from src.data._witness import tag_source_leg
from src.data.sea_ice import SeaIceReading, SeaIceRecord, detect_record_low, fetch_sea_ice
from src.data.source_status import SourceFetchError


def _write_tiny_osi_saf(path: Path) -> bytes:
    with Dataset(path, "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("yc", 2)
        ds.createDimension("xc", 3)
        xc = ds.createVariable("xc", "f8", ("xc",))
        yc = ds.createVariable("yc", "f8", ("yc",))
        xc.units = "km"
        yc.units = "km"
        xc[:] = [0.0, 100.0, 200.0]
        yc[:] = [200.0, 100.0]
        ice = ds.createVariable("ice_conc", "f4", ("time", "yc", "xc"), fill_value=-999.0)
        ice.units = "%"
        ice[0, :, :] = [
            [0.0, 16.0, 80.0],
            [-999.0, 20.0, 14.0],
        ]
    return path.read_bytes()


def test_osi_saf_extent_from_netcdf_bytes(tmp_path):
    from src.data.sea_ice_witness import reading_from_netcdf_bytes

    reading = reading_from_netcdf_bytes(
        _write_tiny_osi_saf(tmp_path / "tiny.nc"),
        hemisphere="Arctic",
        data_date="2026-06-13",
    )

    assert reading == SeaIceReading(
        hemisphere="Arctic",
        extent_million_km2=0.03,
        date="2026-06-13",
        event_id="sea_ice_arctic_2026-06-13",
    )


def test_osi_saf_catalog_selects_latest_file_for_hemisphere():
    from src.data.sea_ice_witness import latest_file_url_from_catalog

    catalog = """<?xml version="1.0" encoding="UTF-8"?>
    <catalog xmlns="http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0">
      <dataset>
        <dataset name="ice_conc_sh_polstere-100_multi_202606131200.nc" urlPath="osisaf/met.no/ice/conc/2026/06/ice_conc_sh_polstere-100_multi_202606131200.nc" />
        <dataset name="ice_conc_nh_polstere-100_multi_202606111200.nc" urlPath="osisaf/met.no/ice/conc/2026/06/ice_conc_nh_polstere-100_multi_202606111200.nc" />
        <dataset name="ice_conc_nh_polstere-100_multi_202606131200.nc" urlPath="osisaf/met.no/ice/conc/2026/06/ice_conc_nh_polstere-100_multi_202606131200.nc" />
      </dataset>
    </catalog>
    """

    selected = latest_file_url_from_catalog(catalog, hemisphere="Arctic")

    assert selected.data_date == "2026-06-13"
    assert selected.url.endswith("ice_conc_nh_polstere-100_multi_202606131200.nc")


def test_osi_saf_invalid_netcdf_raises_source_fetch_error():
    from src.data.sea_ice_witness import reading_from_netcdf_bytes

    with pytest.raises(SourceFetchError, match="OSI SAF NetCDF read failed"):
        reading_from_netcdf_bytes(
            b"not a netcdf file",
            hemisphere="Arctic",
            data_date="2026-06-13",
        )


@responses.activate
def test_fetch_sea_ice_primary_healthy_skips_witness(monkeypatch):
    import src.data.sea_ice as sea_ice

    sea_ice._SEA_ICE_REVALIDATION_CACHE.clear()
    fresh = date.today()
    body = f"""Year, Month, Day, Extent, Missing, Source Data
 , , , in 10^6 sq km, ,
 {fresh.year}, {fresh.month:4d}, {fresh.day:4d}, 12.500, 0, source
"""
    responses.add(responses.GET, sea_ice.ARCTIC_URL, body=body, status=200)
    monkeypatch.setattr(
        sea_ice.sea_ice_witness,
        "fetch_osi_saf_sea_ice",
        lambda *args, **kwargs: pytest.fail("witness should not be called"),
    )

    readings = fetch_sea_ice(hemisphere="Arctic")

    assert readings
    assert all(reading.source_leg is None for reading in readings)


@responses.activate
def test_fetch_sea_ice_falls_back_to_osi_saf_on_primary_error(monkeypatch):
    import src.data.sea_ice as sea_ice

    sea_ice._SEA_ICE_REVALIDATION_CACHE.clear()
    responses.add(responses.GET, sea_ice.ARCTIC_URL, status=503)
    witness_readings = tag_source_leg(
        [SeaIceReading("Arctic", 10.291, "2026-06-13", "sea_ice_arctic_2026-06-13")],
        "osi_saf",
    )
    monkeypatch.setattr(
        sea_ice.sea_ice_witness,
        "fetch_osi_saf_sea_ice",
        lambda *args, **kwargs: witness_readings,
    )

    readings = fetch_sea_ice(hemisphere="Arctic")

    assert readings == witness_readings
    assert readings[0].source_leg == "osi_saf"


def test_detect_record_low_propagates_witness_source_leg():
    readings = [
        SeaIceReading("Arctic", 13.234, "1979-01-01", "sea_ice_arctic_1979-01-01"),
        SeaIceReading("Arctic", 12.800, "2024-01-01", "sea_ice_arctic_2024-01-01"),
        SeaIceReading(
            "Arctic",
            12.500,
            "2026-01-01",
            "sea_ice_arctic_2026-01-01",
            source_leg="osi_saf",
        ),
    ]

    record = detect_record_low(readings)

    assert record is not None
    assert record.source_leg == "osi_saf"


def test_sea_ice_bundle_marks_osi_saf_observed_alt_host():
    from src.two_bot.intern import build_sea_ice_bundle

    bundle = build_sea_ice_bundle(
        SeaIceRecord(
            hemisphere="Arctic",
            extent_million_km2=12.5,
            date="2026-01-01",
            record_type="lowest",
            previous_extent=12.8,
            previous_year=2024,
            event_id="sea_ice_record_arctic_2026-01-01",
            source_leg="osi_saf",
        )
    )

    assert {"label": "evidence_grade", "value": "observed_alt_host"} in bundle.current_facts


def test_run_sea_ice_records_degraded_when_osi_saf_served(fresh_state, monkeypatch):
    from src.orchestrator.sources import sea_ice as runner

    class Monday(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 15)

    readings = tag_source_leg(
        [SeaIceReading("Arctic", 10.291, "2026-06-13", "sea_ice_arctic_2026-06-13")],
        "osi_saf",
    )
    monkeypatch.setattr(runner, "date", Monday)
    monkeypatch.setattr(runner, "_fetch_strict", lambda *args, **kwargs: readings)
    monkeypatch.setattr(runner.sea_ice, "detect_record_low", lambda readings: None)

    current_run = {"sources": []}
    runner.run_sea_ice(fresh_state, current_run)

    arctic = next(row for row in current_run["sources"] if row["source"] == "sea_ice_arctic")
    assert arctic["status"] == "degraded"
    assert arctic["note"] == "served via osi_saf"
    assert fresh_state.get("_triage_queue", []) == []
