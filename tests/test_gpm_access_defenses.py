"""Offline access-failure containment, without NASA or model requests."""
import base64
from datetime import date, datetime, timezone
import json

import boto3
from botocore.exceptions import ClientError
import pytest

from src.data import gpm_imerg as gpm
from src.data._s3credentials import S3Credentials
from src.data.source_status import SourceFetchError


NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)


def token(exp):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"synthetic.{payload}.not-a-real-signature"


class Clock:
    @staticmethod
    def now(tz):
        return NOW.astimezone(tz)


@pytest.mark.parametrize("expiry", [NOW.timestamp() - 1, NOW.timestamp()])
def test_expired_token_refuses_before_all_nasa_and_witness_requests(monkeypatch, capsys, expiry):
    secret = token(expiry)
    monkeypatch.setenv("EARTHDATA_TOKEN", secret)
    monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")
    monkeypatch.setattr(gpm, "datetime", Clock)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("unexpected request")
        pytest.fail("Expired credential must stop before any source request")

    for name in ("_fetch_daily_precip_grid", "_resolve_available_date", "_fetch_city_precip",
                 "get_s3_credentials", "_fetch_precip_open_meteo"):
        monkeypatch.setattr(gpm, name, forbidden)
    with pytest.raises(SourceFetchError, match="EARTHDATA_TOKEN expired") as caught:
        gpm.fetch_daily_precip([], strict=True)
    assert not calls
    assert secret not in str(caught.value) + capsys.readouterr().out
    assert gpm.fetch_daily_precip([], strict=False) == []
    assert not calls


@pytest.mark.parametrize("credential", [
    token(NOW.timestamp() + 1), "opaque-token", token(None), token(True), token("invalid"),
])
def test_unknown_or_future_expiry_does_not_claim_access_or_skip_endpoint_check(monkeypatch, credential):
    monkeypatch.setenv("EARTHDATA_TOKEN", credential)
    monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")
    monkeypatch.setattr(gpm, "datetime", Clock)
    calls = []

    def actual_boundary(*args, **kwargs):
        calls.append(args[0])
        raise gpm._GridFetchUnavailable("synthetic endpoint failure")

    monkeypatch.setattr(gpm, "_fetch_daily_precip_grid", actual_boundary)
    monkeypatch.setattr(gpm, "_resolve_available_date", lambda **kwargs: (_ for _ in ()).throw(
        SourceFetchError("synthetic credential access refusal")))
    with pytest.raises(SourceFetchError, match="access refusal"):
        gpm.fetch_daily_precip([], strict=True)
    assert calls == ["datapool"]


@pytest.mark.parametrize("code,status,expected_attempts", [
    ("AccessDenied", 403, 1), ("403", 403, 1), ("ExpiredToken", 400, 1),
    ("InvalidAccessKeyId", 403, 1), ("NoSuchBucket", 404, 1),
    ("NoSuchKey", 403, 1), ("404", 401, 1), ("AccessDenied", 404, 1),
    ("NoSuchKey", 404, 3), ("NotFound", 404, 3), ("404", 404, 3),
])
def test_s3_walkback_only_advances_on_missing_object_evidence(monkeypatch, code, status, expected_attempts):
    monkeypatch.setattr(gpm, "get_s3_credentials", lambda token: S3Credentials("AK", "SK", "ST", NOW))
    attempted = []

    class Client:
        def get_object(self, **kwargs):
            attempted.append(kwargs["Key"])
            raise ClientError({"Error": {"Code": code},
                               "ResponseMetadata": {"HTTPStatusCode": status}}, "GetObject")

    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: Client())
    error = gpm._GridNotFound if expected_attempts == 3 else gpm._GridTransient
    with pytest.raises(error):
        gpm._fetch_grid_with_walkback("s3", start_date=date(2026, 9, 8), product="late",
                                     token="synthetic", max_lookback=2)
    assert len(attempted) == expected_attempts
