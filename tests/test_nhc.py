"""Tests for NHC tropical-cyclone ingestion and detection."""

import responses
import pytest
import requests
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.data import nhc
from src.data.cyclones import CycloneAdvisory, saffir_simpson_category


def _advisory(
    *,
    issued_at: str,
    wind_kt: int,
    advisory_number: str = "1",
    storm_id: str = "AL012026",
    text: str = "",
) -> CycloneAdvisory:
    return CycloneAdvisory(
        source="nhc",
        storm_id=storm_id,
        storm_name="Beryl",
        basin="Atlantic",
        advisory_number=advisory_number,
        issued_at=issued_at,
        wind_kt=wind_kt,
        pressure_mb=950,
        lat=15.0,
        lon=-75.0,
        public_advisory_url="https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
        advisory_text=text,
    )


class TestFetchActiveCyclones:
    @responses.activate
    def test_empty_active_storms_is_success(self):
        responses.add(
            responses.GET,
            nhc.NHC_CURRENT_STORMS_URL,
            json={"activeStorms": []},
            status=200,
        )

        assert nhc.fetch_active_cyclones() == []

    @responses.activate
    def test_maps_active_storm_fields_and_fetches_public_advisory(self):
        responses.add(
            responses.GET,
            nhc.NHC_CURRENT_STORMS_URL,
            json={
                "activeStorms": [
                    {
                        "id": "AL012026",
                        "name": "Beryl",
                        "basin": "Atlantic",
                        "advisoryNumber": "12",
                        # Must sit inside nhc.py's 2-day freshness gate whenever
                        # the suite runs (time-travel canary: a fixed date here
                        # rots within days of being written).
                        "lastUpdate": (
                            datetime.now(timezone.utc) - timedelta(hours=6)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "intensity": "115",
                        "pressure": "950",
                        "latitudeNumeric": "15.0N",
                        "longitudeNumeric": "75.0W",
                        "publicAdvisory": "/text/MIATCPAT1.shtml",
                    }
                ]
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
            body="Beryl made landfall near Example Coast.",
            status=200,
        )

        advisories = nhc.fetch_active_cyclones()

        assert len(advisories) == 1
        advisory = advisories[0]
        assert advisory.storm_id == "AL012026"
        assert advisory.wind_kt == 115
        assert advisory.pressure_mb == 950
        assert advisory.lat == 15.0
        assert advisory.lon == -75.0
        assert advisory.category == 4
        assert advisory.public_advisory_url == "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"
        assert "landfall" in advisory.advisory_text

    @responses.activate
    def test_api_error_returns_empty_non_strict(self):
        responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, status=500)
        assert nhc.fetch_active_cyclones() == []


class TestCycloneDetection:
    def test_saffir_simpson_category_boundaries(self):
        assert saffir_simpson_category(63) == 0
        assert saffir_simpson_category(64) == 1
        assert saffir_simpson_category(83) == 2
        assert saffir_simpson_category(96) == 3
        assert saffir_simpson_category(113) == 4
        assert saffir_simpson_category(137) == 5

    def test_rapid_intensification_detects_30kt_24h_jump(self):
        events = nhc.detect_rapid_intensification([
            _advisory(issued_at="2026-07-01T00:00:00Z", wind_kt=65, advisory_number="8"),
            _advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=100, advisory_number="12"),
        ])

        assert len(events) == 1
        event = events[0]
        assert event.delta_kt_24h == 35
        assert event.previous_category == 1
        assert event.current_category == 3
        assert event.event_id == "nhc_ri_al012026_12_100"

    def test_rapid_intensification_ignores_small_changes(self):
        events = nhc.detect_rapid_intensification([
            _advisory(issued_at="2026-07-01T00:00:00Z", wind_kt=65, advisory_number="8"),
            _advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=90, advisory_number="12"),
        ])

        assert events == []

    def test_tier_crossing_uses_prior_state(self):
        events = nhc.detect_tier_crossings(
            [_advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=115, advisory_number="12")],
            {"nhc:al012026": 2},
        )

        assert len(events) == 1
        assert events[0].from_category == 2
        assert events[0].to_category == 4
        assert events[0].event_id == "nhc_tier_al012026_12_cat4"

    def test_tier_crossing_dedupes_same_tier(self):
        events = nhc.detect_tier_crossings(
            [_advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=115, advisory_number="12")],
            {"nhc:al012026": 4},
        )

        assert events == []

    def test_landfall_requires_major_hurricane_and_explicit_text(self):
        events = nhc.detect_landfalls([
            _advisory(
                issued_at="2026-07-02T00:00:00Z",
                wind_kt=100,
                advisory_number="12",
                text="Beryl made landfall near Cedar Key, Florida with sustained winds.",
            )
        ])

        assert len(events) == 1
        assert events[0].location == "Cedar Key, Florida"
        assert events[0].category == 3

    def test_landfall_ignores_sub_major_storm(self):
        events = nhc.detect_landfalls([
            _advisory(
                issued_at="2026-07-02T00:00:00Z",
                wind_kt=90,
                advisory_number="12",
                text="Beryl made landfall near Cedar Key, Florida.",
            )
        ])

        assert events == []

    def test_basin_record_helper_uses_supplied_archive_rule(self):
        events = nhc.detect_basin_records(
            [_advisory(issued_at="2026-06-15T00:00:00Z", wind_kt=115, advisory_number="9")],
            {
                "Atlantic": {
                    "earliest_cat4": {
                        "min_category": 4,
                        "label": "earliest Atlantic Category 4 on record",
                        "scope": "Atlantic best-track archive",
                    }
                }
            },
        )

        assert len(events) == 1
        assert events[0].record_label == "earliest Atlantic Category 4 on record"
        assert events[0].record_scope == "Atlantic best-track archive"


@pytest.fixture
def nested_storm():
    issue = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return {
        "id": "AL012026", "name": "Fixture", "intensity": "100", "pressure": "960",
        "latitudeNumeric": 20.0, "longitudeNumeric": -60.0, "lastUpdate": issue,
        "publicAdvisory": {"advNum": "012", "issuance": issue,
                           "fileUpdateTime": issue, "url": "/text/MIATCPAT1.shtml"},
        "forecastAdvisory": {"advNum": "999", "issuance": issue,
                             "url": "https://www.nhc.noaa.gov/text/MIATCMAT1.shtml"},
    }


@responses.activate
def test_nested_products_preserve_exact_urls_number_forecast_and_evidence(nested_storm):
    from tests.test_jtwc import _NHC_TCM_FIXTURE
    from src.orchestrator.cyclones import _bundle_for_cyclone_event, _cyclone_review_context
    before = deepcopy(nested_storm)
    responses.get(nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms": [nested_storm]})
    public_url = "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"
    responses.get(public_url, body="Fixture remains offshore.")
    responses.get(nested_storm["forecastAdvisory"]["url"], body=_NHC_TCM_FIXTURE)
    advisory, = nhc.fetch_active_cyclones(strict=True)
    assert advisory.advisory_number == "012" and advisory.issued_at == nested_storm["lastUpdate"]
    assert advisory.public_advisory_url == public_url and advisory.advisory_text == "Fixture remains offshore."
    assert len(advisory.forecast_points) == 2 and advisory.forecast_points[0].max_wind_kt == 105
    assert [c.request.url for c in responses.calls] == [nhc.NHC_CURRENT_STORMS_URL, public_url, nested_storm["forecastAdvisory"]["url"]]
    assert nested_storm == before
    event, = nhc.detect_tier_crossings([advisory], {"nhc:al012026": 2})
    assert event.event_id == "nhc_tier_al012026_012_cat3"
    assert nhc.detect_tier_crossings([advisory], {"nhc:al012026": 3}) == []
    facts = {x["label"]: x["value"] for x in _bundle_for_cyclone_event(event).current_facts}
    assert facts["advisory_number"] == "012" and facts["public_advisory_url"] == public_url
    desk = _cyclone_review_context(event, source_label="NHC", source_key="nhc", current_run=None)
    assert next(x["value"] for x in desk["facts"] if x["label"] == "Public advisory") == public_url


@pytest.mark.parametrize("value,expected", [
    ("/text/MIATCPAT1.shtml", "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"),
    ("text/MIATCPAT1.shtml", "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"),
    ("https://www.nhc.noaa.gov/text/MIATCPAT1.shtml", "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"),
    ("http://www.nhc.noaa.gov/text/MIATCPAT1.shtml", "http://www.nhc.noaa.gov/text/MIATCPAT1.shtml"),
    ("//www.nhc.noaa.gov/text/MIATCPAT1.shtml", "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"),
    ("https://nhc.noaa.gov/text/MIATCPAT1.shtml", "https://nhc.noaa.gov/text/MIATCPAT1.shtml"),
])
def test_official_urls_and_legacy_paths(value, expected):
    assert nhc._normalize_url(value) == expected


_BAD_PRODUCT_URLS = [
    None, True, 12, ["/text/fixture.shtml"], {"url": "/text/fixture.shtml"},
    "", " ", "https:/www.nhc.noaa.gov/text/fixture.shtml", "https:///www.nhc.noaa.gov/text/fixture.shtml",
    "//other.example/text/fixture.shtml", "https://other.example/", "https://www.nhc.noaa.gov.other.example/",
    "https://user:password@www.nhc.noaa.gov/text/fixture.shtml", "https://www.nhc.noaa.gov:invalid/",
    "https://www.nhc.noaa.gov:8080/", "file:///text/fixture.shtml", "javascript:alert(1)",
    "{'url': '/text/fixture.shtml'}", '["/text/fixture.shtml"]', "/text/a b.shtml",
    "/text/a\nb.shtml", "/text/a%0ab.shtml", "/text/a\\b.shtml", "/text/a%5cb.shtml",
    "///other.example/text/fixture.shtml", "x" * 2049, "/text/\ud800.shtml",
]


@pytest.mark.parametrize("value", _BAD_PRODUCT_URLS, ids=[f"bad-url-{n}" for n in range(len(_BAD_PRODUCT_URLS))])
def test_bad_optional_urls_never_fetch_and_keep_core_advisory(nested_storm, monkeypatch, value):
    monkeypatch.setattr(nhc, "fetch_with_retry", lambda *a, **k: pytest.fail("invalid optional URL fetched"))
    nested_storm["publicAdvisory"]["url"] = value
    nested_storm["forecastAdvisory"]["url"] = value
    advisory = nhc._parse_active_storm(nested_storm)
    assert advisory is not None and advisory.wind_kt == 100
    assert advisory.public_advisory_url == "" and advisory.advisory_text == ""
    assert advisory.forecast_points == () and advisory.advisory_number == "012"


@pytest.mark.parametrize("alias", ["publicAdvisory", "publicAdvisoryUrl", "public_advisory", "public_advisory_url", "advisoryUrl"])
def test_legacy_scalar_aliases_keep_their_metadata(nested_storm, monkeypatch, alias):
    monkeypatch.setattr(nhc, "_fetch_advisory_text", lambda url: "")
    nested_storm.pop("publicAdvisory")
    nested_storm[alias] = "/text/MIATCPAT1.shtml"
    nested_storm["advisoryNumber"] = 12
    advisory = nhc._parse_active_storm(nested_storm)
    assert advisory.advisory_number == "12"
    assert advisory.public_advisory_url == "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"
    assert advisory.issued_at == nested_storm["lastUpdate"]


@pytest.mark.parametrize("value,expected", [(" 012A ", "012A"), ("012", "012"), (12, "9"),
    (None, "9"), (True, "9"), ([], "9"), ({"number": "12"}, "9"), ("", "9"), ("wrong", "9")])
def test_public_number_precedence_and_strict_fallback(nested_storm, monkeypatch, value, expected):
    monkeypatch.setattr(nhc, "_fetch_advisory_text", lambda url: "")
    nested_storm["publicAdvisory"]["advNum"] = value
    nested_storm["advisoryNumber"] = 9
    advisory = nhc._parse_active_storm(nested_storm)
    assert advisory.advisory_number == expected


@pytest.mark.parametrize("value", [None, True, -1, 1.5, [], {}, "bad", "1" * 33])
def test_malformed_number_never_uses_forecast_or_container(nested_storm, monkeypatch, value):
    monkeypatch.setattr(nhc, "_fetch_advisory_text", lambda url: "")
    nested_storm["publicAdvisory"].pop("advNum")
    nested_storm["advisoryNumber"] = value
    assert nhc._parse_active_storm(nested_storm).advisory_number == ""


def test_measurement_time_precedence_and_public_issuance_fallback(nested_storm, monkeypatch):
    monkeypatch.setattr(nhc, "_fetch_advisory_text", lambda url: "")
    nested_storm["publicAdvisory"]["issuance"] = "2026-09-30T06:00:00Z"
    assert nhc._parse_active_storm(nested_storm).issued_at == nested_storm["lastUpdate"]
    nested_storm.pop("lastUpdate")
    assert nhc._parse_active_storm(nested_storm).issued_at == "2026-09-30T06:00:00Z"
    nested_storm["issued_at"] = "2026-09-30T03:00:00-03:00"
    assert nhc._parse_active_storm(nested_storm).issued_at == nested_storm["issued_at"]


@pytest.mark.parametrize("value", [None, True, 123, [], {}, "", "2026-10-01", "2026-10-01T09:00:00", "2026-02-30T09:00:00Z", "2026-10-01X09:00:00Z"])
def test_unqualified_times_never_become_file_update_or_forecast_time(nested_storm, monkeypatch, value):
    monkeypatch.setattr(nhc, "_fetch_advisory_text", lambda url: "")
    nested_storm["lastUpdate"] = value
    assert nhc._parse_active_storm(nested_storm).issued_at == nested_storm["publicAdvisory"]["issuance"]
    nested_storm["publicAdvisory"]["issuance"] = value
    assert nhc._parse_active_storm(nested_storm) is None


@pytest.mark.parametrize("public_value", [None, [], True, 123, {}, {"url": []}])
def test_malformed_public_product_leaves_forecast_available(nested_storm, monkeypatch, public_value):
    from tests.test_jtwc import _NHC_TCM_FIXTURE
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        assert url == nested_storm["forecastAdvisory"]["url"]
        return SimpleNamespace(text=_NHC_TCM_FIXTURE)
    monkeypatch.setattr(nhc, "fetch_with_retry", fetch)
    nested_storm["publicAdvisory"] = public_value
    advisory = nhc._parse_active_storm(nested_storm)
    assert len(calls) == 1 and len(advisory.forecast_points) == 2
    assert advisory.public_advisory_url == "" and advisory.advisory_number == ""


def test_optional_public_fetch_failure_preserves_forecast(nested_storm, monkeypatch):
    from tests.test_jtwc import _NHC_TCM_FIXTURE
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("MIATCPAT1.shtml"):
            raise requests.ConnectionError("offline fixture")
        return SimpleNamespace(text=_NHC_TCM_FIXTURE)
    monkeypatch.setattr(nhc, "fetch_with_retry", fetch)
    advisory = nhc._parse_active_storm(nested_storm)
    assert advisory.advisory_text == "" and len(advisory.forecast_points) == 2
    assert len(calls) == 2 and all(k["attempts"] == 2 and k["timeout"] == 15 for _, k in calls)


@pytest.mark.parametrize("source_text", [
    "Fixture is expected to make landfall near Example Coast.",
    "Fixture has not made landfall near Example Coast.",
    "Last year another storm made landfall near Example Coast.",
])
def test_restored_public_text_cannot_certify_landfall_or_buy_checks(nested_storm, monkeypatch, fresh_state, source_text):
    from src.data.cyclones import LandfallEvent
    from src.two_bot import pipeline
    from src.two_bot.intern.disasters import build_cyclone_landfall_bundle
    monkeypatch.setattr(nhc, "fetch_with_retry", lambda *a, **k: SimpleNamespace(text=source_text))
    advisory = nhc._parse_active_storm(nested_storm)
    assert nhc.detect_landfalls([advisory]) == []
    # Keep a nonvacuous downstream gate test even when screening emits nothing.
    # An explicit unqualified synthetic event must never become a source warrant.
    event = LandfallEvent(source=advisory.source, storm_id=advisory.storm_id,
        storm_name=advisory.storm_name, basin=advisory.basin,
        advisory_number=advisory.advisory_number, issued_at=advisory.issued_at,
        category=advisory.category, wind_kt=advisory.wind_kt, location="Example Coast",
        public_advisory_url=advisory.public_advisory_url, event_id="synthetic-unqualified")
    bundle = build_cyclone_landfall_bundle(event)
    def forbidden(*args, **kwargs):
        pytest.fail("unqualified landfall bought a model check")
    monkeypatch.setattr(pipeline, "run_safety_pipeline", forbidden)
    monkeypatch.setattr(pipeline.fact_check, "fact_check", forbidden)
    monkeypatch.setattr(pipeline.critic, "critic_review", forbidden)
    failures = []
    outcome = pipeline._check_safety_honesty_fact(
        "Fixture made landfall near Example Coast.", bundle, fresh_state,
        record_kill=lambda stage, reason: failures.append((stage, reason)),
    )
    assert outcome is None and any("unconfirmed_landfall" in reason for _, reason in failures)
