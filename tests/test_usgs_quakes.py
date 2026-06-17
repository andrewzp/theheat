from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import responses

from src.data.source_status import SourceFetchError
from src.data.usgs_quakes import (
    USGS_SIGNIFICANT_DAY_URL,
    SignificantEarthquakeEvent,
    fetch_significant_earthquakes,
)


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


# Fixture timestamps for the real-fetch path must stay inside the source's
# freshness window (``assert_freshness(..., max_age_days=2)`` in
# ``fetch_significant_earthquakes``). Anchoring them to "now" (truncated to whole
# seconds so the ms round-trip through the parser is exact) keeps the suite
# date-stable — a fixed calendar date silently broke it at each 2-day rollover.
_NOW = datetime.now(UTC).replace(microsecond=0)
_RECENT_TIME = (_NOW - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
_RECENT_UPDATED = (_NOW - timedelta(hours=11, minutes=30)).isoformat().replace("+00:00", "Z")
_RECENT_GENERATED = (_NOW - timedelta(hours=11, minutes=15)).isoformat().replace("+00:00", "Z")


def _feature(
    *,
    event_id: str = "us7000abcd",
    magnitude: float = 7.1,
    alert: str | None = "orange",
    tsunami: int = 1,
) -> dict:
    return {
        "type": "Feature",
        "id": event_id,
        "properties": {
            "mag": magnitude,
            "place": "12 km S of Example City, Chile",
            "time": _ms(_RECENT_TIME),
            "updated": _ms(_RECENT_UPDATED),
            "tz": None,
            "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}",
            "detail": f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/{event_id}.geojson",
            "felt": 480,
            "cdi": 7.2,
            "mmi": 6.8,
            "alert": alert,
            "status": "reviewed",
            "tsunami": tsunami,
            "sig": 950,
            "net": "us",
            "code": event_id.removeprefix("us"),
            "ids": f",{event_id},",
            "sources": ",us,",
            "types": ",origin,phase-data,shakemap,",
            "nst": 120,
            "dmin": 1.2,
            "rms": 0.9,
            "gap": 30,
            "magType": "mww",
            "type": "earthquake",
            "title": "M 7.1 - 12 km S of Example City, Chile",
        },
        "geometry": {
            "type": "Point",
            "coordinates": [-71.25, -32.5, 18.4],
        },
    }


def _feed(features: list[dict], *, generated: str = _RECENT_GENERATED) -> dict:
    return {
        "type": "FeatureCollection",
        "metadata": {
            "generated": _ms(generated),
            "url": USGS_SIGNIFICANT_DAY_URL,
            "title": "USGS Significant Earthquakes, Past Day",
            "status": 200,
            "api": "2.4.0",
            "count": len(features),
        },
        "features": features,
    }


def _event() -> SignificantEarthquakeEvent:
    return SignificantEarthquakeEvent(
        event_id="usgs_eq_us7000abcd",
        usgs_id="us7000abcd",
        title="M 7.1 - 12 km S of Example City, Chile",
        place="12 km S of Example City, Chile",
        magnitude=7.1,
        time="2026-06-14T12:00:00Z",
        updated="2026-06-14T12:30:00Z",
        url="https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
        alert="orange",
        significance=950,
        felt_reports=480,
        cdi=7.2,
        mmi=6.8,
        tsunami=True,
        latitude=-32.5,
        longitude=-71.25,
        depth_km=18.4,
    )


class TestFetchSignificantEarthquakes:
    @responses.activate
    def test_parses_usgs_significant_geojson(self):
        responses.add(
            responses.GET,
            USGS_SIGNIFICANT_DAY_URL,
            json=_feed([_feature()]),
            status=200,
        )

        events = fetch_significant_earthquakes()

        assert len(events) == 1
        event = events[0]
        assert event.event_id == "usgs_eq_us7000abcd"
        assert event.usgs_id == "us7000abcd"
        assert event.magnitude == 7.1
        assert event.place == "12 km S of Example City, Chile"
        assert event.time == _RECENT_TIME
        assert event.updated == _RECENT_UPDATED
        assert event.alert == "orange"
        assert event.significance == 950
        assert event.felt_reports == 480
        assert event.tsunami is True
        assert event.latitude == -32.5
        assert event.longitude == -71.25
        assert event.depth_km == 18.4

    @responses.activate
    def test_empty_feed_is_success(self):
        responses.add(
            responses.GET,
            USGS_SIGNIFICANT_DAY_URL,
            json=_feed([]),
            status=200,
        )

        assert fetch_significant_earthquakes() == []

    @responses.activate
    def test_empty_feed_still_checks_metadata_freshness(self):
        responses.add(
            responses.GET,
            USGS_SIGNIFICANT_DAY_URL,
            json=_feed([], generated="2026-06-01T12:45:00Z"),
            status=200,
        )

        with pytest.raises(SourceFetchError, match="stale data"):
            fetch_significant_earthquakes(strict=True)

    @responses.activate
    def test_schema_error_raises_in_strict_mode(self):
        responses.add(
            responses.GET,
            USGS_SIGNIFICANT_DAY_URL,
            json={"features": []},
            status=200,
        )

        with pytest.raises(SourceFetchError, match="FeatureCollection"):
            fetch_significant_earthquakes(strict=True)

    @responses.activate
    def test_http_error_returns_empty_non_strict(self):
        responses.add(responses.GET, USGS_SIGNIFICANT_DAY_URL, status=503)

        assert fetch_significant_earthquakes() == []


def test_run_usgs_quakes_enqueues_candidate_and_records_source(fresh_state, monkeypatch):
    from src.orchestrator.sources import usgs_quakes as runner

    monkeypatch.setattr(runner, "_fetch_strict", lambda *args, **kwargs: [_event()])
    monkeypatch.setattr(runner, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    runner.run_usgs_quakes(fresh_state, current_run)

    queue = fresh_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "usgs_eq_us7000abcd"
    assert queue[0].legacy_type == "usgs_earthquake"
    assert queue[0].source == "usgs_quakes"
    assert queue[0].review_context["source_key"] == "usgs_quakes"
    assert queue[0].review_context["source"] == "USGS Earthquake Hazards Program"

    source_entry = next(row for row in current_run["sources"] if row["source"] == "usgs_quakes")
    assert source_entry["status"] == "success"
    assert source_entry["observed"] == 1
    assert source_entry["promoted"] == 1


def test_run_usgs_quakes_failure_records_failed_and_continues(fresh_state, monkeypatch):
    from src.orchestrator.sources import usgs_quakes as runner

    monkeypatch.setattr(
        runner,
        "_fetch_strict",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("usgs down")),
    )

    current_run = {"sources": []}
    runner.run_usgs_quakes(fresh_state, current_run)

    source_entry = next(row for row in current_run["sources"] if row["source"] == "usgs_quakes")
    assert source_entry["status"] == "failed"
    assert "usgs down" in source_entry["error"]
    assert any(error["source"] == "usgs_quakes" for error in fresh_state["errors"])
