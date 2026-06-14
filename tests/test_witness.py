"""Tests for the source-redundancy witness helpers (R-00 provenance foundation)."""

from __future__ import annotations

import dataclasses

import pytest
import requests

from src.data._witness import (
    degraded_via,
    source_leg_of,
    tag_source_leg,
    with_witness,
)
from src.data.source_status import SourceFetchError, SourceSkipped


@dataclasses.dataclass
class _Event:
    event_id: str
    source_leg: str | None = None


@dataclasses.dataclass(frozen=True)
class _FrozenEvent:
    event_id: str
    source_leg: str | None = None


def test_with_witness_returns_primary_when_healthy():
    primary_events = [_Event(event_id="primary")]

    def primary() -> list[_Event]:
        return primary_events

    def witness() -> list[_Event]:
        raise AssertionError("witness must not be called on the happy path")

    result = with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")
    assert result == primary_events


def test_with_witness_falls_back_on_fetch_error():
    def primary() -> list[_Event]:
        raise SourceFetchError("503 Service Unavailable")

    def witness() -> list[_Event]:
        return tag_source_leg([_Event(event_id="w")], "noaa_hms")

    result = with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")
    assert result == [_Event(event_id="w", source_leg="noaa_hms")]


def test_with_witness_does_not_mask_auth_failure():
    def primary() -> list[_Event]:
        raise SourceFetchError("401 Client Error: Unauthorized")

    def witness() -> list[_Event]:
        raise AssertionError("witness must not hide primary credential failures")

    with pytest.raises(SourceFetchError, match="Unauthorized"):
        with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")


def test_with_witness_does_not_mask_schema_drift():
    def primary() -> list[_Event]:
        raise SourceFetchError("firms schema drift: missing required field latitude")

    def witness() -> list[_Event]:
        raise AssertionError("witness must not hide parser/schema failures")

    with pytest.raises(SourceFetchError, match="schema drift"):
        with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")


def test_with_witness_falls_back_on_stale_provider_data():
    def primary() -> list[_Event]:
        raise SourceFetchError("gpm_imerg stale data: latest data point is 2026-06-01")

    def witness() -> list[_Event]:
        return tag_source_leg([_Event(event_id="w")], "open_meteo")

    result = with_witness(primary, witness, source_key="gpm_imerg", leg_label="open_meteo")
    assert result == [_Event(event_id="w", source_leg="open_meteo")]


def test_with_witness_does_not_mask_malformed_freshness_date():
    def primary() -> list[_Event]:
        raise SourceFetchError("freshness check failed: invalid date 'not-a-date'")

    def witness() -> list[_Event]:
        raise AssertionError("witness must not hide parser/freshness defects")

    with pytest.raises(SourceFetchError, match="invalid date"):
        with_witness(primary, witness, source_key="gpm_imerg", leg_label="open_meteo")


def test_with_witness_falls_back_on_requests_exception():
    def primary() -> list[_Event]:
        raise requests.ConnectionError("transport boom")

    def witness() -> list[_Event]:
        return tag_source_leg([_Event(event_id="w")], "noaa_hms")

    result = with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")
    assert result[0].source_leg == "noaa_hms"


def test_with_witness_propagates_source_skipped():
    def primary() -> list[_Event]:
        raise SourceSkipped("map key intentionally absent")

    def witness() -> list[_Event]:
        raise AssertionError("witness must not be called when the source is skipped")

    with pytest.raises(SourceSkipped):
        with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")


def test_with_witness_chains_both_errors():
    def primary() -> list[_Event]:
        raise SourceFetchError("primary 500")

    def witness() -> list[_Event]:
        raise requests.Timeout("witness timeout")

    with pytest.raises(SourceFetchError) as excinfo:
        with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")

    message = str(excinfo.value)
    assert "primary 500" in message
    assert "witness timeout" in message


def test_witness_event_carries_source_leg():
    result = tag_source_leg([_Event(event_id="witness")], "noaa_hms")
    assert result == [_Event(event_id="witness", source_leg="noaa_hms")]


def test_tag_source_leg_handles_frozen_dataclass():
    result = tag_source_leg([_FrozenEvent(event_id="w")], "open_meteo")
    assert result == [_FrozenEvent(event_id="w", source_leg="open_meteo")]


def test_source_leg_of_returns_leg_when_present():
    events = tag_source_leg([_Event(event_id="w")], "reliefweb")
    assert source_leg_of(events) == "reliefweb"


def test_source_leg_of_none_when_primary_served():
    assert source_leg_of([_Event(event_id="p")]) is None


def test_degraded_via_reports_leg_when_witness_served():
    events = tag_source_leg([_Event(event_id="w")], "noaa_hms")
    assert degraded_via(events) == "served via noaa_hms"


def test_degraded_via_none_when_primary_served():
    assert degraded_via([_Event(event_id="p")]) is None
