from unittest.mock import patch

import pytest
import requests

from src.data.source_status import SourceFetchError, SourceSkipped


class _FailingSession:
    def get(self, url, **kwargs):
        raise requests.RequestException("network down")


def test_firms_strict_missing_key_is_skipped(monkeypatch):
    from src.data import firms

    monkeypatch.setattr(firms, "FIRMS_API_KEY", "")

    with pytest.raises(SourceSkipped):
        firms.fetch_fires(strict=True)


def test_firms_strict_request_error_is_failed(monkeypatch):
    from src.data import firms

    monkeypatch.setattr(firms, "FIRMS_API_KEY", "key")
    with patch("src.data.firms.requests.get", side_effect=Exception("network down")):
        with pytest.raises(SourceFetchError):
            firms.fetch_fires(strict=True)


def test_fire_footprint_strict_request_error_is_failed():
    from src.data import fire_footprint

    with patch("src.data.fire_footprint.fetch_with_retry", side_effect=Exception("network down")):
        with pytest.raises(SourceFetchError):
            fire_footprint.fetch_active_fire_perimeters(strict=True)


def test_nws_strict_request_error_is_failed():
    from src.data import nws_alerts

    with patch(
        "src.data.nws_alerts.fetch_with_retry",
        side_effect=requests.RequestException("network down"),
    ):
        with pytest.raises(SourceFetchError):
            nws_alerts.fetch_alerts(strict=True)


def test_co2_strict_request_error_is_failed():
    from src.data import co2

    with patch(
        "src.data.co2.fetch_with_retry",
        side_effect=requests.RequestException("network down"),
    ):
        with pytest.raises(SourceFetchError):
            co2.fetch_co2_data(strict=True)


def test_ch4_strict_request_error_is_failed():
    from src.data import methane

    with patch(
        "src.data._http._get_session",
        return_value=_FailingSession(),
    ):
        with pytest.raises(SourceFetchError):
            methane.fetch_ch4_milestones(strict=True)


def test_coral_dhw_strict_request_error_is_failed():
    from src.data import coral_dhw

    with patch(
        "src.data._http._get_session",
        return_value=_FailingSession(),
    ):
        with pytest.raises(SourceFetchError):
            coral_dhw.fetch_coral_dhw(strict=True)


def test_ocean_strict_all_points_failed_is_failed(monkeypatch):
    from src.data import ocean

    monkeypatch.setattr(ocean, "OCEAN_POINTS", [(1.0, 2.0, "Test Point", "Test")])
    with patch(
        "src.data.ocean.fetch_with_retry",
        side_effect=requests.RequestException("network down"),
    ):
        with pytest.raises(SourceFetchError):
            ocean.fetch_ocean_conditions(strict=True)


def test_ice_mass_strict_missing_token_is_skipped(monkeypatch):
    from src.data import ice_mass

    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    with pytest.raises(SourceSkipped):
        ice_mass.fetch_grace_mass("greenland", strict=True)
