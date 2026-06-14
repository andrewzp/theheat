"""S-14 freshness rollout regression tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses

from src.data import air_quality, co2, drought, enso, fire_footprint, firms
from src.data import gdacs, gpm_imerg, ice_mass, jtwc, nhc, nws_alerts
from src.data import river_gauges, sea_ice, water_levels
from src.data.source_status import SourceFetchError


def _old_ms() -> int:
    return int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000)


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


@responses.activate
@patch("src.data.firms.FIRMS_API_KEY", "test_key")
def test_firms_stale_data_raises_freshness():
    body = (
        "latitude,longitude,confidence,frp,acq_date\n"
        "34.05,-118.25,90,350.0,2020-01-01\n"
    )
    responses.add(
        responses.GET,
        f"{firms.FIRMS_URL}/test_key/VIIRS_SNPP_NRT/world/1",
        body=body,
        status=200,
    )

    # R-06: asserts the PRIMARY product's freshness gate. The public fetch_fires
    # now chains products (R-06) and falls back to the NOAA HMS witness (R-02), so
    # this specific stale-product error is intentionally superseded there.
    with pytest.raises(SourceFetchError, match="firms stale data"):
        firms._fetch_fires_primary(80, 250.0, "VIIRS_SNPP_NRT", 1)


@responses.activate
def test_sea_ice_stale_data_raises_freshness():
    body = """Year, Month, Day, Extent, Missing, Source Data
 , , , in 10^6 sq km, ,
 2020,    1,    1,  12.500,       0, source
"""
    responses.add(responses.GET, sea_ice.ARCTIC_URL, body=body, status=200)

    with pytest.raises(SourceFetchError, match="sea_ice stale data"):
        sea_ice.fetch_sea_ice(strict=True)


@responses.activate
def test_drought_stale_data_raises_freshness():
    responses.add(
        responses.GET,
        drought.DROUGHT_URL,
        json=[{"Name": "Texas", "MapDate": "2020-01-02", "D3": 15, "D4": 10}],
        status=200,
    )

    with pytest.raises(SourceFetchError, match="drought stale data"):
        drought.fetch_drought_data(strict=True)


@responses.activate
def test_co2_stale_data_raises_freshness():
    body = "2020,1,1,2020.001,410.12\n"
    responses.add(responses.GET, co2.CO2_URL, body=body, status=200)

    with pytest.raises(SourceFetchError, match="co2 stale data"):
        co2.fetch_co2_data(strict=True)


@responses.activate
def test_gdacs_stale_data_raises_freshness():
    responses.add(
        responses.GET,
        gdacs.GDACS_URL,
        json={
            "features": [
                {
                    "properties": {
                        "eventtype": "TC",
                        "alertlevel": "Red",
                        "name": "Old Cyclone",
                        "country": "Mozambique",
                        "description": "stale",
                        "eventid": "old-1",
                        "fromdate": "2020-01-01T00:00:00Z",
                    }
                }
            ]
        },
        status=200,
    )

    with pytest.raises(SourceFetchError, match="gdacs stale data"):
        gdacs.fetch_disasters(strict=True)


@responses.activate
@patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
def test_ice_mass_stale_data_raises_freshness(_env):
    data_url = (
        "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/"
        "GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4/"
        "greenland_mass_200204_202001.txt"
    )
    responses.add(
        responses.GET,
        ice_mass.CMR_GRANULES_URL,
        json={"feed": {"entry": [{"links": [{"href": data_url}]}]}},
        status=200,
    )
    responses.add(
        responses.GET,
        data_url,
        body="HDR\n2019.958   -100.0   10.0\n2020.0417   -120.0   10.0\n",
        status=200,
    )

    with pytest.raises(SourceFetchError, match="ice_mass stale data"):
        ice_mass.fetch_grace_mass("greenland", strict=True)


@responses.activate
def test_nws_alerts_stale_data_raises_freshness():
    responses.add(
        responses.GET,
        nws_alerts.NWS_URL,
        json={
            "features": [
                {
                    "properties": {
                        "event": "Hurricane Warning",
                        "severity": "Extreme",
                        "areaDesc": "Miami-Dade, FL",
                        "headline": "Hurricane Warning",
                        "sent": "2020-01-01T00:00:00Z",
                    }
                }
            ]
        },
        status=200,
    )

    with pytest.raises(SourceFetchError, match="nws_alerts stale data"):
        nws_alerts.fetch_alerts(strict=True)


@responses.activate
def test_river_gauges_stale_data_raises_freshness():
    responses.add(
        responses.GET,
        river_gauges.USGS_URL,
        json={
            "value": {
                "timeSeries": [
                    {
                        "sourceInfo": {"siteCode": [{"value": "07010000"}]},
                        "values": [
                            {
                                "value": [
                                    {
                                        "value": "35.5",
                                        "dateTime": "2020-01-01T00:00:00Z",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        },
        status=200,
    )
    responses.add(
        responses.GET,
        river_gauges.FLOOD_URL.format(site_id="07010000"),
        json={"flood": {"categories": {"minor": {"stage": 30.0}}}},
        status=200,
    )

    with patch("src.data.river_gauges.MAJOR_STATIONS", [river_gauges.MAJOR_STATIONS[0]]):
        with pytest.raises(SourceFetchError, match="river_gauges stale data"):
            river_gauges.fetch_river_levels(strict=True)


def test_water_levels_stale_data_raises_freshness():
    obs = {"data": [{"t": "2020-01-01 00:00", "v": "1.8"}]}
    pred = {"predictions": [{"t": "2020-01-01 00:00", "v": "1.1"}]}

    with (
        patch("src.data.water_levels.STATIONS", [water_levels.STATIONS[0]]),
        patch(
            "src.data.water_levels.fetch_with_retry",
            side_effect=[_mock_response(obs), _mock_response(pred)],
        ),
    ):
        with pytest.raises(SourceFetchError, match="water_levels stale data"):
            water_levels.fetch_water_levels(strict=True)


@responses.activate
def test_enso_stale_data_raises_freshness():
    responses.add(
        responses.GET,
        enso.ONI_URL,
        body="SEAS    YR   TOTAL   APTS   ANOM\nDJF    2020    -0.8   26.1   -0.8\n",
        status=200,
    )

    with pytest.raises(SourceFetchError, match="enso stale data"):
        enso.fetch_enso_data(strict=True)


@responses.activate
def test_jtwc_stale_data_raises_freshness():
    rss = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Western Pacific Tropical Warning</title>
        <link>https://www.metoc.navy.mil/jtwc/products/wp0226web.txt</link>
        <description>TROPICAL STORM 02W (MAWAR) WARNING NR 012. MAX SUSTAINED WINDS - 70 KT.</description>
        <pubDate>Wed, 01 Jan 2020 00:00:00 +0000</pubDate>
      </item>
    </channel></rss>
    """
    responses.add(responses.GET, jtwc.JTWC_RSS_URL, body=rss, status=200)

    with pytest.raises(SourceFetchError, match="jtwc stale data"):
        jtwc.fetch_active_cyclones(strict=True)


@responses.activate
def test_nhc_stale_data_raises_freshness():
    responses.add(
        responses.GET,
        nhc.NHC_CURRENT_STORMS_URL,
        json={
            "activeStorms": [
                {
                    "id": "AL012020",
                    "name": "Oldstorm",
                    "lastUpdate": "2020-01-01T00:00:00Z",
                    "intensity": "65",
                }
            ]
        },
        status=200,
    )

    with pytest.raises(SourceFetchError, match="nhc stale data"):
        nhc.fetch_active_cyclones(strict=True)


@responses.activate
def test_fire_footprint_stale_data_raises_freshness():
    payload = {
        "features": [
            {
                "attributes": {
                    "UniqueFireIdentifier": "2020-OLD-000001",
                    "IncidentName": "Old Fire",
                    "IsCpxChild": 0,
                    "IncidentSize": 100_000.0,
                    "POOState": "US-CA",
                    "FireDiscoveryDateTime": _old_ms(),
                    "ModifiedOnDateTime": _old_ms(),
                }
            }
        ]
    }
    responses.add(responses.GET, fire_footprint.GWIS_URL, json=payload, status=200)

    with pytest.raises(SourceFetchError, match="fire_footprint stale data"):
        fire_footprint.fetch_active_fire_perimeters(strict=True)


@patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
def test_gpm_imerg_stale_data_raises_freshness(_env, monkeypatch):
    monkeypatch.setattr(gpm_imerg, "_gpm_source", lambda: "opendap")
    monkeypatch.setattr(gpm_imerg, "_resolve_available_date", lambda **kw: date(2020, 1, 1))
    monkeypatch.setattr(gpm_imerg, "_fetch_city_precip", lambda **kw: 1.0)

    # R-03: asserts the PRIMARY's freshness gate (public fetch_daily_precip now
    # falls back to the Open-Meteo witness when the primary raises).
    with pytest.raises(SourceFetchError, match="gpm_imerg stale data"):
        gpm_imerg._fetch_daily_precip_primary(
            [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
            strict=True,
        )


def test_air_quality_stale_data_raises_freshness():
    payload = {
        "hourly": {
            "time": [f"2020-01-01T{hour:02d}:00" for hour in range(24)],
            "pm2_5": [150.0] * 24,
            "dust": [0.0] * 24,
            "aerosol_optical_depth": [0.2] * 24,
            "us_aqi": [200] * 24,
        }
    }

    with patch("src.data.air_quality.fetch_with_retry", return_value=_mock_response(payload)):
        with pytest.raises(SourceFetchError, match="air_quality stale data"):
            air_quality.fetch_batch_air_quality(
                [{"city": "Lahore", "country": "Pakistan", "lat": "31.5", "lon": "74.3"}]
            )
