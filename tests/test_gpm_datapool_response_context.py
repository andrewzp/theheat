"""Existing-response operational labels; no live source or qualification pass."""
from datetime import date
from unittest.mock import Mock

import requests
import pytest

from src.data import gpm_imerg as gpm

DAY = date(2026, 11, 20)
SECRET = "invented-private-bearer"


def response(*, status=200, url="https://data.gesdisc.earthdata.nasa.gov/example.nc4", media="application/x-netcdf", redirects=0):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["Content-Type"] = media
    result.history = [requests.Response() for _ in range(redirects)]
    result._content = b"invented retained bytes, not a qualified weather frame"
    return result


def test_actual_existing_get_logs_only_fixed_response_labels(monkeypatch, capsys):
    result = response(url=f"https://urs.earthdata.nasa.gov/login?token={SECRET}", media=f"text/html; private={SECRET}", redirects=1)
    get = Mock(return_value=result)
    monkeypatch.setattr(gpm.requests, "get", get)
    expected_timeout = gpm._request_timeout_s()
    assert gpm._fetch_grid_bytes_datapool(target_date=DAY, product="late", token=SECRET) == result._content
    get.assert_called_once_with(f"{gpm.DATAPOOL_BASE}/{gpm._imerg_relpath('late', DAY)}",
                               headers={"Authorization": f"Bearer {SECRET}"}, timeout=expected_timeout)
    assert capsys.readouterr().out == (
        "[gpm_imerg] datapool response context: status=200 media=html "
        "destination=earthdata_login redirects=1\n"
    )


def test_grid_bytes_and_http_status_handling_are_unchanged(monkeypatch, capsys):
    result = response()
    monkeypatch.setattr(gpm.requests, "get", Mock(return_value=result))
    assert gpm._fetch_grid_bytes_datapool(target_date=DAY, product="late", token=SECRET) == result._content
    assert "status=200 media=netcdf destination=datapool redirects=0" in capsys.readouterr().out


@pytest.mark.parametrize(("url", "destination"), [
    (f"https://data.gesdisc.earthdata.nasa.gov/file?token={SECRET}", "datapool"),
    (f"https://gpm1.gesdisc.eosdis.nasa.gov/path?opaque={SECRET}", "opendap"),
    (f"https://URS.EARTHDATA.NASA.GOV:443/login?code={SECRET}", "earthdata_login"),
    (f"https://{SECRET}@urs.earthdata.nasa.gov/login", "other"),
    (f"https://urs.earthdata.nasa.gov.evil.invalid/{SECRET}", "other"),
    (f"https://urs.earthdata.nasa.gov:8443/{SECRET}", "other"),
    (f"http://urs.earthdata.nasa.gov/{SECRET}", "other"),
    (f"https://unknown.invalid/{SECRET}", "other"),
    (f"https://urs.earthdata.nasa.gov:bad/{SECRET}", "unknown"),
    (SECRET * 500, "unknown"),
], ids=["datapool", "opendap", "login", "userinfo", "lookalike", "port", "http", "foreign", "bad-port", "too-long"])
def test_destination_is_a_finite_label_never_url_userinfo_or_query(url, destination):
    result = gpm._datapool_response_context(response(url=url))
    assert result == f"status=200 media=netcdf destination={destination} redirects=0"
    assert SECRET not in result
    assert "://" not in result


@pytest.mark.parametrize(("value", "media"), [
    ("text/html; charset=UTF-8", "html"), ("APPLICATION/X-NETCDF", "netcdf"),
    ("application/x-hdf5", "hdf"), ("application/x-hdf", "hdf"),
    ("application/octet-stream", "octet_stream"), (f"private/{SECRET}\nsecret", "unknown"),
    (SECRET * 100, "unknown"), (None, "unknown"), (True, "unknown"),
], ids=["html", "netcdf", "hdf5", "hdf", "octet", "secret", "too-long", "none", "bool"])
def test_media_is_a_finite_label_never_raw_header(value, media):
    result = response(media=value)
    line = gpm._datapool_response_context(result)
    assert line == f"status=200 media={media} destination=datapool redirects=0"
    assert SECRET not in line


def test_missing_or_malformed_metadata_never_reads_body_request_headers_or_cookies():
    result = response()
    result.headers.clear()
    result.headers["Set-Cookie"] = SECRET
    result.request = Mock()
    result.request.headers = {"Authorization": SECRET}
    result.raw = Mock()
    result.raw.read.side_effect = AssertionError("body must not be read")
    result._content = False
    assert gpm._datapool_response_context(result) == "status=200 media=missing destination=datapool redirects=0"
    assert result._content is False
    result.raw.read.assert_not_called()
    result.status_code = True
    result.headers = None
    result.url = None
    result.history = None
    assert gpm._datapool_response_context(result) == "status=unknown media=unknown destination=unknown redirects=unknown"


def test_nonstandard_adapter_properties_are_not_invoked_for_logging():
    class Trap:
        def __getattribute__(self, name):
            raise AssertionError("No new property access on an adapter")
    assert gpm._datapool_response_context(Trap()) == "status=unknown media=unknown destination=unknown redirects=unknown"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 503])
def test_logging_does_not_read_error_body_or_change_existing_http_exception(monkeypatch, status, capsys):
    result = response(status=status)
    result._content = False
    result.raw = Mock()
    result.raw.read.side_effect = AssertionError("No HTTP error body read")
    get = Mock(return_value=result)
    monkeypatch.setattr(gpm.requests, "get", get)
    expected = gpm._GridNotFound if status == 404 else gpm._GridTransient
    with pytest.raises(expected):
        gpm._fetch_grid_bytes_datapool(target_date=DAY, product="late", token=SECRET)
    get.assert_called_once()
    result.raw.read.assert_not_called()
    assert result._content is False
    assert SECRET not in capsys.readouterr().out


def test_optional_diagnostic_failure_does_not_change_successful_content(monkeypatch, capsys):
    result = response()
    monkeypatch.setattr(gpm.requests, "get", Mock(return_value=result))
    monkeypatch.setattr(gpm, "_datapool_response_context", Mock(side_effect=RuntimeError(SECRET)))
    assert gpm._fetch_grid_bytes_datapool(target_date=DAY, product="late", token=SECRET) == result._content
    assert capsys.readouterr().out == ""


def test_broken_log_output_does_not_swallow_the_provider_refusal(monkeypatch):
    result = response(status=404)
    monkeypatch.setattr(gpm.requests, "get", Mock(return_value=result))
    monkeypatch.setattr(gpm, "print", Mock(side_effect=OSError(SECRET)), raising=False)
    with pytest.raises(gpm._GridNotFound):
        gpm._fetch_grid_bytes_datapool(target_date=DAY, product="late", token=SECRET)


@pytest.mark.parametrize("url", [
    "https://ur\ns.earthdata.nasa.gov/login", "https://gpm1.ges\tdisc.eosdis.nasa.gov/x",
    "\x00https://urs.earthdata.nasa.gov/login", " https://urs.earthdata.nasa.gov/login",
], ids=["authority-lf", "authority-tab", "leading-nul", "leading-space"])
def test_literal_url_controls_cannot_be_normalized_into_known_destination(url):
    assert "destination=unknown" in gpm._datapool_response_context(response(url=url))


@pytest.mark.parametrize("media", ["\x0btext/html\r\n", "text/html\n", "text/html; private=\x1bsecret"],
                         ids=["vertical-tab-crlf", "trailing-lf", "parameter-escape"])
def test_literal_header_controls_cannot_be_normalized_into_known_media(media):
    assert "media=unknown" in gpm._datapool_response_context(response(media=media))


def test_normal_encoded_query_and_optional_mime_whitespace_stay_readable():
    result = response(url=f"https://urs.earthdata.nasa.gov/login?opaque=%0A{SECRET}",
                      media="\t text/html \t; charset=UTF-8\t")
    assert gpm._datapool_response_context(result) == "status=200 media=html destination=earthdata_login redirects=0"
