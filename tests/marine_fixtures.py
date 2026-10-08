"""Invented paired marine products, decoded through the real source parsers."""
from copy import deepcopy
from datetime import UTC, datetime, date

import pytest

from src.data import ocean_sst_anomaly as sst
from src.data import crw_contract, coral_regional_contract, coral_source_contract, coral_dhw
from src.editorial import marine_evidence, synthesis
from src import state
from tests import crw_fixtures, coral_point_fixtures, coral_regional_fixtures


@pytest.fixture
def marine_clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 6, 16, 12, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz else cls.current.replace(tzinfo=None)

    for module in (sst, crw_contract, coral_regional_contract, coral_source_contract,
                   coral_point_fixtures, coral_regional_fixtures, marine_evidence, synthesis, state):
        monkeypatch.setattr(module, "datetime", Clock)
    return Clock


def sst_reading(monkeypatch, *, value=2.2, day="2026-06-14", slug="bay_of_bengal"):
    region = next(r for r in sst.REGION_REGISTRY if r.slug == slug)
    def get(url, **kwargs):
        body = (crw_fixtures.metadata_body().replace(crw_fixtures.DAY.encode(), day.encode())
                if url == crw_contract.METADATA_URL else crw_fixtures.csv_body(region, day=day, value=value))
        return crw_fixtures.response(body)
    monkeypatch.setattr(sst, "fetch_with_retry", get)
    result = sst.fetch_region_sst(region, strict=True, today=date.fromisoformat(day))
    assert result is not None and crw_contract.qualified_provenance(result)
    return result


def coral_reading(**kwargs):
    return coral_regional_fixtures.reading(region_id="great_nicobar", name="Great Nicobar", **kwargs)


def qualified_state(monkeypatch):
    result = deepcopy(state.DEFAULT_STATE)
    assert marine_evidence.record_reading(result, "coral", coral_reading()) == "retained"
    assert marine_evidence.record_reading(result, "sst_anomaly", sst_reading(monkeypatch)) == "retained"
    return result


def bundle(monkeypatch):
    from src.two_bot.intern.synthesis import build_synthesis_bundle
    signals = synthesis.detect_marine_compound(qualified_state(monkeypatch))
    assert len(signals) == 1
    return build_synthesis_bundle(signals[0].components["marine_payload"])
