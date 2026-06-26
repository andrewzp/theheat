from datetime import date

from src.data.open_meteo import (
    AbsoluteExtremeEvent,
    AllTimeRecord,
    ExtremeSignalBundle,
    RecordEvent,
    WetBulbEvent,
)
from src.state import _fresh_state


def test_record_streak_draft_counts_in_source_telemetry(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner

    signal_date = date(2026, 5, 15)
    record = RecordEvent(
        city="Paris",
        country="France",
        new_temp_c=35.0,
        old_record_c=33.0,
        old_record_year=2024,
        event_id="record_paris_2026-05-15",
        signal_date=signal_date,
    )
    bundle = ExtremeSignalBundle(
        city="Paris",
        country="France",
        calendar_date_high=record,
        signal_date=signal_date,
    )
    bot_state = _fresh_state()
    bot_state["record_streaks"] = {
        "Paris": {
            "days": 2,
            "last_date": "2026-05-14",
            "start_date": "2026-05-13",
            "peak_temp_c": 34.0,
        },
    }
    current_run = {"id": "run_1", "mode": "alerts", "started_at": "2026-05-15T00:00:00Z", "sources": []}

    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, metrics_out: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *args, **kwargs: True)
    monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", lambda *args, **kwargs: True)

    drafted = runner.run_extreme_signals(bot_state, current_run, [], {}, {})

    source_run = current_run["sources"][0]
    assert drafted is None
    assert len(bot_state["_triage_queue"]) == 2
    assert source_run["source"] == "open_meteo_extreme_signals"
    assert source_run["drafted"] == 0

    assert runner._drain_and_write_triage_queue(bot_state, current_run) == 2
    assert source_run["drafted"] == 2


def test_absolute_extreme_is_queued_when_it_is_strongest(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner

    signal_date = date(2026, 7, 15)
    absolute = AbsoluteExtremeEvent(
        city="Tromso",
        country="Norway",
        today_temp_c=31.5,
        band_label="Arctic",
        threshold_c=30.0,
        kind="hot",
        lat=70.0,
        lon=25.0,
        event_id="absextreme_Tromso_2026-07-15",
        signal_date=signal_date,
    )
    bundle = ExtremeSignalBundle(
        city="Tromso",
        country="Norway",
        absolute_extreme=absolute,
        signal_date=signal_date,
    )
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "mode": "alerts", "started_at": "2026-07-15T00:00:00Z", "sources": []}
    enqueued: list[dict] = []

    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, metrics_out: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *args, **kwargs: True)

    def fake_enqueue(*args, **kwargs):
        enqueued.append(kwargs)
        return True

    monkeypatch.setattr(runner, "_enqueue_story_candidate", fake_enqueue)

    runner.run_extreme_signals(bot_state, current_run, [], {}, {})

    assert len(enqueued) == 1
    assert enqueued[0]["legacy_type"] == "absolute_extreme"
    assert enqueued[0]["event_id"] == "absextreme_Tromso_2026-07-15"
    assert enqueued[0]["cooldown_exempt"] is False


def test_absolute_extreme_loses_to_all_time_record(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner

    signal_date = date(2026, 7, 15)
    absolute = AbsoluteExtremeEvent(
        city="Tromso",
        country="Norway",
        today_temp_c=31.5,
        band_label="Arctic",
        threshold_c=30.0,
        kind="hot",
        lat=70.0,
        lon=25.0,
        event_id="absextreme_Tromso_2026-07-15",
        signal_date=signal_date,
    )
    all_time = AllTimeRecord(
        city="Tromso",
        country="Norway",
        kind="high",
        new_temp_c=31.5,
        old_record_c=30.5,
        old_record_year=1985,
        years_of_data=30,
        event_id="alltime_high_Tromso_2026-07-15",
        signal_date=signal_date,
    )
    bundle = ExtremeSignalBundle(
        city="Tromso",
        country="Norway",
        all_time_high=all_time,
        absolute_extreme=absolute,
        signal_date=signal_date,
    )
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "mode": "alerts", "started_at": "2026-07-15T00:00:00Z", "sources": []}
    enqueued: list[dict] = []

    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, metrics_out: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *args, **kwargs: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *args, **kwargs: enqueued.append(kwargs) or True)

    runner.run_extreme_signals(bot_state, current_run, [], {}, {})

    assert len(enqueued) == 1
    assert enqueued[0]["legacy_type"] == "all_time_high"
    assert enqueued[0]["event_id"] == "alltime_high_Tromso_2026-07-15"


def test_wet_bulb_extreme_is_queued_in_second_pass(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner

    signal_date = date(2026, 7, 12)
    wet_bulb = WetBulbEvent(
        city="Jacobabad",
        country="Pakistan",
        daily_max_tw_c=35.5,
        tier=3,
        tier_label="tier_3",
        tier_threshold_c=35.0,
        event_id="wetbulb_Jacobabad_2026-07-12_tier3",
        signal_date=signal_date,
    )
    bundle = ExtremeSignalBundle(
        city="Jacobabad",
        country="Pakistan",
        wet_bulb_extreme=wet_bulb,
        signal_date=signal_date,
    )
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "mode": "alerts", "started_at": "2026-07-12T00:00:00Z", "sources": []}
    enqueued: list[dict] = []

    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.delenv("THEHEAT_WETBULB_ENABLED", raising=False)
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, metrics_out: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *args, **kwargs: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *args, **kwargs: enqueued.append(kwargs) or True)

    runner.run_extreme_signals(bot_state, current_run, [], {}, {})

    assert len(enqueued) == 1
    assert enqueued[0]["legacy_type"] == "wet_bulb_extreme"
    assert enqueued[0]["event_id"] == "wetbulb_Jacobabad_2026-07-12_tier3"
    assert enqueued[0]["cooldown_exempt"] is True


def test_wet_bulb_extreme_kill_switch_disables_second_pass(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner

    wet_bulb = WetBulbEvent(
        city="Jacobabad",
        country="Pakistan",
        daily_max_tw_c=35.5,
        tier=3,
        tier_label="tier_3",
        tier_threshold_c=35.0,
        event_id="wetbulb_Jacobabad_2026-07-12_tier3",
    )
    bundle = ExtremeSignalBundle(
        city="Jacobabad",
        country="Pakistan",
        wet_bulb_extreme=wet_bulb,
    )
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "mode": "alerts", "started_at": "2026-07-12T00:00:00Z", "sources": []}
    enqueued: list[dict] = []

    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setenv("THEHEAT_WETBULB_ENABLED", "0")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, metrics_out: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *args, **kwargs: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *args, **kwargs: enqueued.append(kwargs) or True)

    runner.run_extreme_signals(bot_state, current_run, [], {}, {})

    assert enqueued == []


def test_streaks_not_pruned_on_fetch_failure(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner

    bot_state = _fresh_state()
    bot_state["record_streaks"] = {
        "Paris": {
            "days": 3,
            "last_date": "2026-06-01",
            "start_date": "2026-05-30",
            "peak_temp_c": 34.0,
            "updated_at": "2026-06-01",
        },
    }
    current_run = {"id": "run_1", "mode": "alerts", "started_at": "2026-06-12T00:00:00Z", "sources": []}
    prune_calls = []

    def fake_check(_cities, metrics_out):
        metrics_out.update({"city_fetch_failures": 5, "city_readings": 0})
        return [], []

    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", fake_check)
    monkeypatch.setattr(
        runner.state,
        "prune_stale_record_streaks",
        lambda state: prune_calls.append(state) or state,
    )

    runner.run_extreme_signals(bot_state, current_run, [], {}, {})

    assert prune_calls == []
    assert current_run["sources"][0]["status"] == "failed"


def test_both_provider_runs_ghcn_for_us_and_open_meteo_for_world(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner

    signal_date = date(2026, 6, 25)
    us_event = AbsoluteExtremeEvent(
        city="Phoenix", country="United States", today_temp_c=48.0,
        band_label="Desert", threshold_c=46.0, kind="hot", lat=33.4, lon=-112.0,
        event_id="absextreme_Phoenix_2026-06-25", signal_date=signal_date,
    )
    us_bundle = ExtremeSignalBundle(
        city="Phoenix", country="United States", absolute_extreme=us_event,
        signal_date=signal_date, station_id="USW00023183",
        station_name="PHOENIX SKY HARBOR INTL AP",
    )
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z", "sources": []}
    enqueued: list[dict] = []
    world_cities = [{"city": "Seville", "country": "Spain", "lat": "37.4", "lon": "-6.0"}]

    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "both")
    monkeypatch.setattr(
        runner.ghcn, "check_extreme_signals_for_stations",
        lambda *args, **kwargs: ([us_bundle], []),
    )
    # The world half is sourced from the cached warm+hot path now, not the
    # superseded _check_city_extreme_signals seam: warm seeds Seville's
    # thresholds from the archive, then the forecast (46.0 > cached 40.0)
    # fires an all-time-high via evaluate_city.
    monkeypatch.setattr(runner, "_fetch_city_archive", lambda c: {
        "time": ["1996-06-01"], "temperature_2m_max": [40.0], "temperature_2m_min": [10.0],
        "wet_bulb_temperature_2m_max": [24.0]})
    monkeypatch.setattr("src.data.open_meteo.fetch_forecasts_batch",
        lambda cities: {c["city"]: {"max_c": 46.0, "min_c": 12.0, "tw_max_c": 10.0} for c in cities})
    monkeypatch.setattr(runner, "_should_draft", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        runner, "_enqueue_story_candidate",
        lambda *args, **kwargs: enqueued.append(kwargs) or True,
    )

    runner.run_extreme_signals(bot_state, current_run, world_cities, {}, {})

    event_ids = {e["event_id"] for e in enqueued}
    assert "absextreme_Phoenix_2026-06-25" in event_ids  # US sourced from GHCN
    assert any("Seville" in e.get("event_id", "") for e in enqueued)  # Europe sourced from Open-Meteo
    assert current_run["sources"][0]["note"].startswith("provider:both")


def test_surfaced_heat_event_records_coverage(monkeypatch):
    from datetime import date
    from src.data.open_meteo import AbsoluteExtremeEvent, ExtremeSignalBundle
    from src.orchestrator.sources import open_meteo as runner
    from src.state import _fresh_state

    ev = AbsoluteExtremeEvent(city="Seville", country="Spain", today_temp_c=45.1,
        band_label="Temperate", threshold_c=42.0, kind="hot", lat=37.4, lon=-6.0,
        event_id="absextreme_Seville_2026-06-25", signal_date=date(2026, 6, 25))
    bundle = ExtremeSignalBundle(city="Seville", country="Spain", absolute_extreme=ev, signal_date=date(2026, 6, 25))
    bot_state = _fresh_state()
    current_run = {"id": "r1", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z", "sources": []}
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, m: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *a, **k: True)
    runner.run_extreme_signals(bot_state, current_run, [], {}, {})
    recs = [r for r in bot_state["coverage_log"] if r["event_id"] == "absextreme_Seville_2026-06-25"]
    assert recs and recs[0]["cls"] == "heat" and recs[0]["continent"] == "Europe"


def test_cold_extreme_is_not_recorded_as_heat(monkeypatch):
    from datetime import date
    from src.data.open_meteo import AbsoluteExtremeEvent, ExtremeSignalBundle
    from src.orchestrator.sources import open_meteo as runner
    from src.state import _fresh_state

    cold = AbsoluteExtremeEvent(city="Nw Michigan", country="United States", today_temp_c=0.6,
        band_label="Temperate", threshold_c=2.0, kind="cold", lat=45.0, lon=-85.0,
        event_id="absextreme_cold_NwMichigan_2026-06-25", signal_date=date(2026, 6, 25))
    bundle = ExtremeSignalBundle(city="Nw Michigan", country="United States", absolute_extreme=cold,
                                 signal_date=date(2026, 6, 25))
    bot_state = _fresh_state()
    current_run = {"id": "r1", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z", "sources": []}
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, m: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *a, **k: True)
    runner.run_extreme_signals(bot_state, current_run, [], {}, {})
    assert bot_state["coverage_log"] == []  # cold extreme must not pollute the heat tally


def test_classify_world_status_rules():
    from src.orchestrator.world_cache import classify_world_status as cls
    base = {"world_total": 595, "forecast_attempted": 595, "forecast_failures": 0, "warm_attempted": 8, "warm_failures": 0, "saturated": False}
    assert cls({**base, "cached_count": 595, "coverage_ratio": 0.2}, prev_cached_count=595) == "degraded"   # steady low coverage
    assert cls({**base, "cached_count": 595, "coverage_ratio": 0.98}, prev_cached_count=595) == "success"
    assert cls({**base, "cached_count": 40, "coverage_ratio": 0.07}, prev_cached_count=20) == "success"      # bootstrap climbing
    assert cls({**base, "cached_count": 40, "coverage_ratio": 0.07}, prev_cached_count=40) == "degraded"     # bootstrap STALLED
    assert cls({**base, "cached_count": 595, "coverage_ratio": 0.98, "saturated": True}, prev_cached_count=595) == "degraded"


def test_world_path_emits_no_calendar_streak_or_simultaneous():
    """World evaluate_city bundles never carry calendar_date_high, so the
    streak + simultaneous-records lanes stay empty for non-US cities
    (calendar-date is US/GHCN-only — handoff 2026-06-26)."""
    from src.data.world_thresholds import evaluate_city, CityThresholds
    from datetime import date
    cached = CityThresholds(city="Lyon", as_of="2026-06-01", years_of_data=30,
                            all_time_max=(40.0, 2019), monthly_max={"06": (39.0, 2019)})
    b = evaluate_city("Lyon", "France", {"max_c": 45.0, "min_c": 20.0, "tw_max_c": 10.0},
                      cached, lat=45.7, lon=4.8, today=date(2026, 6, 26))
    assert b.calendar_date_high is None
    assert b.calendar_date_low is None


def test_both_world_half_warms_then_evaluates_and_surfaces_metrics(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner
    from src.orchestrator import world_cache
    from src.state import _fresh_state
    store = {}
    monkeypatch.setattr(world_cache, "read_cache", lambda: dict(store))
    monkeypatch.setattr(world_cache, "write_cache", lambda c: store.update(c) or True)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "both")
    monkeypatch.setattr(runner.ghcn, "check_extreme_signals_for_stations", lambda metrics_out: ([], []))
    monkeypatch.setattr(runner, "_fetch_city_archive", lambda c: {
        "time": ["1996-06-01"], "temperature_2m_max": [40.0], "temperature_2m_min": [10.0],
        "wet_bulb_temperature_2m_max": [24.0]})
    monkeypatch.setattr("src.data.open_meteo.fetch_forecasts_batch",
        lambda cities: {c["city"]: {"max_c": 46.0, "min_c": 12.0, "tw_max_c": 10.0} for c in cities})
    cities = [{"city": "Madrid", "country": "Spain", "lat": "40.4", "lon": "-3.7"}]
    run = {"id": "r", "mode": "alerts", "started_at": "2026-06-26T00:00:00Z", "sources": []}
    runner.run_extreme_signals(_fresh_state(), run, cities, {}, {})
    assert "Madrid" in store
    src = [s for s in run["sources"] if s["source"] == "open_meteo_extreme_signals"][0]
    om = src["details"]["open_meteo_pipeline_metrics"]
    assert "coverage_ratio" in om and "cached_count" in om
