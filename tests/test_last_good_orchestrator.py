from __future__ import annotations

from src.data import last_good
from src.data.co2 import CO2Reading
from src.state import _fresh_state


def test_run_co2_writes_last_good_on_success(monkeypatch):
    from src.orchestrator.sources import co2 as runner

    bot_state = _fresh_state()
    current_run = {"sources": []}
    readings = [
        CO2Reading(date="2026-06-09", ppm=429.4, event_id="co2_2026-06-09_429"),
        CO2Reading(date="2026-06-10", ppm=429.8, event_id="co2_2026-06-10_429"),
    ]

    monkeypatch.setattr(runner.co2, "fetch_co2_data", lambda: readings)
    monkeypatch.setattr(runner.co2, "detect_milestone", lambda _readings: None)

    runner.run_co2(bot_state, current_run)

    cached = bot_state["last_good_readings"]["co2"]
    assert cached["data_date"] == "2026-06-10"
    assert cached["payload"] == {"date": "2026-06-10", "ppm": 429.8}
    assert current_run["sources"][0]["status"] == "success"


def test_run_co2_serves_last_good_as_degraded_without_enqueue(monkeypatch):
    from src.orchestrator.sources import co2 as runner

    bot_state = _fresh_state()
    current_run = {"sources": []}
    last_good.write(
        bot_state,
        "co2",
        "2026-06-10",
        {"date": "2026-06-10", "ppm": 429.8},
        captured_at="2026-06-11T00:00:00Z",
    )

    def boom(**_kwargs):
        raise RuntimeError("upstream down")

    def fail_if_detected(_readings):
        raise AssertionError("cached readings must not drive story detection")

    def fail_if_enqueued(*_args, **_kwargs):
        raise AssertionError("cached readings must not reach triage")

    monkeypatch.setattr(runner.co2, "fetch_co2_data", boom)
    monkeypatch.setattr(runner.co2, "detect_milestone", fail_if_detected)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", fail_if_enqueued)

    runner.run_co2(bot_state, current_run)

    source_run = current_run["sources"][0]
    assert source_run["status"] == "degraded"
    assert source_run["error"] == "served last-good (2026-06-10)"


def test_run_co2_does_not_serve_cache_after_successful_fetch_detector_error(monkeypatch):
    from src.orchestrator.sources import co2 as runner

    bot_state = _fresh_state()
    current_run = {"sources": []}
    last_good.write(
        bot_state,
        "co2",
        "2026-06-10",
        {"date": "2026-06-10", "ppm": 429.8},
        captured_at="2026-06-11T00:00:00Z",
    )
    readings = [
        CO2Reading(date="2026-06-10", ppm=429.8, event_id="co2_2026-06-10_429"),
    ]

    monkeypatch.setattr(runner.co2, "fetch_co2_data", lambda: readings)
    monkeypatch.setattr(
        runner.co2,
        "detect_milestone",
        lambda _readings: (_ for _ in ()).throw(RuntimeError("detector bug")),
    )

    runner.run_co2(bot_state, current_run)

    source_run = current_run["sources"][0]
    assert source_run["status"] == "failed"
    assert source_run["error"] == "detector bug"
