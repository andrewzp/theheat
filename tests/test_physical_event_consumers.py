"""Pure and HTTP-fixture boundary checks for source-scoped episode consumers."""
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import requests
import responses

from src.data import nhc
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import (CycloneSupplyError, advisory_row, decode_advisory,
                                        digest, sidecar)
from src.storage.physical_events import EpisodeContext, forecast_qualified
from src.two_bot.memory import build_memory_slice
from src.two_bot.types import StoryBundle
from src.two_bot.writer import build_writer_user_prompt
from tests.test_postgres_physical_events import advisory, EPISODE


def binding():
    return dict(schema_version=1, episode_id=EPISODE, revision_sha256="a"*64,
                source_assertion_refs=["b"*64], identity_class="source_scoped")


def bound_bundle():
    return StoryBundle(signal_kind="cyclone_tier_crossing", where="Invented A, Atlantic", when="2026-10-11",
        event_id="nhc_tier_al012026_2", headline_metric={"label": "wind_kt", "value": 100},
        current_facts=[{"label": "wind_kt", "value": 100}],
        raw_signal_dump={"source": "nhc", "physical_episode": binding()})


@pytest.mark.parametrize("bad", [None, {}, "ready"])
def test_bound_memory_and_actual_request_refuse_missing_context(bad):
    bundle = bound_bundle()
    with pytest.raises(ValueError, match="resolved_episode_context_required"):
        build_memory_slice({}, bundle, episode_context=bad)
    with pytest.raises(ValueError, match="resolved_episode_context_required"):
        build_writer_user_prompt(bundle, SimpleNamespace(to_dict=lambda: {}), episode_context=bad)


def test_bound_context_mismatch_and_no_legacy_prefix_region_fallback():
    bundle = bound_bundle()
    context = EpisodeContext(p._canonical(binding()), p._canonical([binding()]))
    state = {"memory": {"shipped_tweets": [{"event_id": bundle.event_id, "tweet_text": "Unbound legacy report."}],
                        "ongoing_events": [{"event_id": bundle.event_id, "signal_kind": bundle.signal_kind,
                            "region": bundle.where, "country": "", "days_running": 99}]}}
    result = build_memory_slice(state, bundle, episode_context=context)
    assert result.recent_tweets_same_event == [] and result.ongoing_event is None
    bad = deepcopy(bundle)
    bad.raw_signal_dump["physical_episode"]["revision_sha256"] = "c"*64
    with pytest.raises(CycloneSupplyError, match="episode_context_mismatch"):
        build_memory_slice(state, bad, episode_context=context)


def test_news_cannot_add_country_name_only_impact_to_bound_input():
    from src.editorial.newsworthiness import _event_matches_candidate
    bundle = bound_bundle()
    # Even a heat-like matching signal in a bound envelope cannot inherit the
    # legacy news matcher's coarse country/date attribution.
    bundle.signal_kind = "absolute_extreme_hot"
    bundle.country = "US"
    bundle.current_facts += [dict(label="kind", value="hot")]
    assert not _event_matches_candidate(dict(kind="heat_mortality"), SimpleNamespace(bundle=bundle, legacy_type="absolute_extreme"))


@pytest.mark.parametrize("size,complete", [(0, False), (7999, True), (8000, True), (8001, False), (16000, False)])
def test_source_completeness_observed_before_truncation(monkeypatch, size, complete):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(text="x"*size)
    monkeypatch.setattr(nhc, "fetch_with_retry", fetch)
    metadata = {}
    text = nhc._fetch_advisory_text("https://www.nhc.noaa.gov/text/fixture.shtml", acquisition=metadata)
    assert len(text) == min(size, 8000) and metadata == {"complete": complete} and len(calls) == 1
    assert nhc._fetch_advisory_text("https://www.nhc.noaa.gov/text/fixture.shtml") == text
    assert len(calls) == 2


def test_missing_or_failed_text_acquisition_is_unknown_not_short_complete(monkeypatch):
    metadata = {}
    assert nhc._fetch_advisory_text("", acquisition=metadata) == "" and metadata == {}
    def fail(*args, **kwargs):
        raise requests.RequestException("invented failure")
    monkeypatch.setattr(nhc, "fetch_with_retry", fail)
    assert nhc._fetch_advisory_text("https://www.nhc.noaa.gov/text/fixture.shtml", acquisition=metadata) == ""
    assert metadata == {}


@responses.activate
def test_optional_observer_preserves_legacy_bytes_and_exact_forecast_suffix():
    issued = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = dict(id="AL012026", name="Invented A", intensity="70", lastUpdate=issued,
               publicAdvisory={"advNum": "2A"},
               forecastAdvisory=dict(advNum="2", issuance=issued, url="/text/fixture-forecast.shtml"))
    responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms": [raw]})
    responses.add(responses.GET, "https://www.nhc.noaa.gov/text/fixture-forecast.shtml", body="Invented complete product.")
    legacy = nhc.fetch_active_cyclones(strict=True)
    observed = []
    retained = nhc.fetch_active_cyclones(strict=True, retention_observer=lambda a, m: observed.append((a, m)))
    assert [asdict(a) for a in legacy] == [asdict(a) for a in retained]
    assert len(responses.calls) == 4 and observed[0][1]["forecast_advisory_number"] == "2"
    item = dict(advisory=advisory_row(retained[0]), metadata=observed[0][1])
    assert not forecast_qualified(item)  # Do not strip A from public product.
    item["metadata"]["forecast_advisory_number"] = "2A"
    assert forecast_qualified(item)
    item["metadata"]["forecast_issued_at_original"] = "2000-01-01T00:00:00Z"
    assert not forecast_qualified(item)
    item["metadata"]["forecast_issued_at_original"] = None
    assert not forecast_qualified(item)


@pytest.mark.parametrize("change", ["bool", "nan", "infinity", "extra", "missing", "bare_date", "tuple", "point", "oversize"])
def test_typed_advisory_codec_refuses_coercion_and_schema_drift(change):
    row = advisory_row(advisory())
    if change == "bool":
        row["wind_kt"] = True
    if change == "nan":
        row["lat"] = float("nan")
    if change == "infinity":
        row["lon"] = float("inf")
    if change == "extra":
        row["unknown"] = "x"
    if change == "missing":
        row.pop("pressure_mb")
    if change == "bare_date":
        row["issued_at"] = "2026-10-11"
    if change == "tuple":
        row["forecast_points"] = ()
    if change == "point":
        row["forecast_points"] = [{"valid_at": "12/0000Z"}]
    if change == "oversize":
        row["advisory_text"] = "x"*8001
    with pytest.raises(CycloneSupplyError):
        decode_advisory(row)


def test_source_sidecar_cannot_claim_other_forecast_points():
    row = advisory_row(advisory())
    metadata = sidecar(None, row)
    assert metadata["forecast_text_complete"] is None
    metadata["forecast_points_sha256"] = "f"*64
    with pytest.raises(CycloneSupplyError, match="forecast_points_mismatch"):
        sidecar(metadata, row)
