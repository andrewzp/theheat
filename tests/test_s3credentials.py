from datetime import datetime, timedelta, timezone

import responses

from src.data import _s3credentials as s3c
from src.data._s3credentials import clear_cache, get_s3_credentials


def _payload(expiration):
    return {
        "accessKeyId": "AKIA-TEST",
        "secretAccessKey": "secret-test",
        "sessionToken": "session-test",
        "expiration": expiration,
    }


class TestS3Credentials:
    def setup_method(self):
        clear_cache()

    @responses.activate
    def test_mint_parses_fields_and_sends_bearer(self):
        responses.add(
            responses.GET,
            s3c.GESDISC_S3CREDENTIALS_URL,
            json=_payload("2030-01-01 00:00:00+00:00"),
            status=200,
        )

        creds = get_s3_credentials("earthdata-tok")

        assert creds.access_key_id == "AKIA-TEST"
        assert creds.secret_access_key == "secret-test"
        assert creds.session_token == "session-test"
        assert creds.expiration == datetime(2030, 1, 1, tzinfo=timezone.utc)
        assert responses.calls[0].request.headers["Authorization"] == "Bearer earthdata-tok"

    @responses.activate
    def test_caches_within_validity_window(self):
        responses.add(
            responses.GET,
            s3c.GESDISC_S3CREDENTIALS_URL,
            json=_payload("2030-01-01 00:00:00+00:00"),
            status=200,
        )

        first = get_s3_credentials("tok")
        second = get_s3_credentials("tok")

        assert first is second
        assert len(responses.calls) == 1  # second served from cache, no re-mint

    @responses.activate
    def test_refreshes_within_safety_window(self):
        # Credentials whose expiry is inside the safety window must be re-minted.
        responses.add(
            responses.GET,
            s3c.GESDISC_S3CREDENTIALS_URL,
            json=_payload("2026-06-06 13:00:00+00:00"),
            status=200,
        )
        responses.add(
            responses.GET,
            s3c.GESDISC_S3CREDENTIALS_URL,
            json=_payload("2026-06-06 15:00:00+00:00"),
            status=200,
        )

        noon = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        first = get_s3_credentials("tok", now=lambda: noon)
        again = get_s3_credentials("tok", now=lambda: noon)
        assert first is again
        assert len(responses.calls) == 1  # 13:00 expiry is >5min out at noon → cached

        almost_expired = datetime(2026, 6, 6, 12, 58, tzinfo=timezone.utc)
        third = get_s3_credentials("tok", now=lambda: almost_expired)
        assert len(responses.calls) == 2  # within 5-min safety window → re-mint
        assert third.expiration == datetime(2026, 6, 6, 15, 0, tzinfo=timezone.utc)

    @responses.activate
    def test_expiration_fallback_on_unparseable_value(self):
        responses.add(
            responses.GET,
            s3c.GESDISC_S3CREDENTIALS_URL,
            json=_payload("not-a-real-date"),
            status=200,
        )

        fixed = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        creds = get_s3_credentials("tok", now=lambda: fixed)

        # Unparseable expiry → conservative fallback TTL so a format drift can't
        # wedge the source; worst case we just refresh early.
        assert creds.expiration == fixed + timedelta(seconds=s3c._DEFAULT_TTL_S)

    @responses.activate
    def test_naive_expiration_assumed_utc(self):
        responses.add(
            responses.GET,
            s3c.GESDISC_S3CREDENTIALS_URL,
            json=_payload("2030-01-01 00:00:00"),  # no offset
            status=200,
        )

        creds = get_s3_credentials("tok")
        assert creds.expiration == datetime(2030, 1, 1, tzinfo=timezone.utc)
