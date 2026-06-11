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
