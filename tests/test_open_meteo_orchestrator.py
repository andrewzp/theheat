from datetime import date

from src.data.open_meteo import ExtremeSignalBundle, RecordEvent
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
    assert drafted == 0
    assert len(bot_state["_triage_queue"]) == 2
    assert source_run["source"] == "open_meteo_extreme_signals"
    assert source_run["drafted"] == 0

    assert runner._drain_and_write_triage_queue(bot_state, current_run) == 2
    assert source_run["drafted"] == 2
