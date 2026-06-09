"""Tests for the reanalysis-anomaly source runner (the standalone orchestrator).

The runner has the most branching of the reganom code: env gate, cache hit/miss,
batched-fetch degradation, SourceSkipped (cache absent), the §D attempt-time onset
guard, duplicate suppression, and the score gate. These mock at the data-layer +
common-helper boundaries so the writer pipeline never runs.
"""

from __future__ import annotations

from datetime import date

from src.data import reanalysis_anomaly as ra
from src.data.reanalysis_anomaly import RegionalAnomalyEvent
from src.data.source_status import SourceSkipped
from src.orchestrator.sources import reanalysis_anomaly as runner
from src.state import _fresh_state


def _event(slug="Sahel", window_start="2026-06-05", window_end="2026-06-07"):
    return RegionalAnomalyEvent(
        region=slug,
        region_slug=slug,
        cities_sampled=6,
        mean_anomaly_c=7.5,
        mean_zscore=3.2,
        fraction_exceeding=0.83,
        sustained_days=3,
        window_start=window_start,
        window_end=window_end,
        event_id=f"reganom_{slug}_{window_end}",
    )


def _detect_for(slug, ev):
    return lambda region, *a, **k: ev if region.slug == slug else None


class TestRunReanalysisAnomaly:
    def test_env_gate_off_returns_zero_and_does_no_work(self, monkeypatch) -> None:
        monkeypatch.delenv("THEHEAT_REGANOM_ENABLED", raising=False)
        called = {"clim": False}
        monkeypatch.setattr(
            ra, "load_daily_climatology",
            lambda *a, **k: called.__setitem__("clim", True) or {},
        )
        assert runner.run_reanalysis_anomaly(_fresh_state(), None) == 0
        assert called["clim"] is False  # gated off before any work

    def test_source_skipped_when_cache_absent(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")

        def _skip(*a, **k):
            raise SourceSkipped("climatology cache not found")

        monkeypatch.setattr(ra, "load_daily_climatology", _skip)
        rec = {}
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: rec.update(k))
        runner.run_reanalysis_anomaly(_fresh_state(), None)
        assert rec.get("status") == "skipped"
        assert rec.get("note")  # uses note=, not error= (sibling convention)

    def test_degraded_when_batch_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")
        monkeypatch.setattr(ra, "load_daily_climatology", lambda *a, **k: {})
        monkeypatch.setattr(ra, "fetch_all_reganom_t2m", lambda *a, **k: {})
        rec = {}
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: rec.update(k))
        assert runner.run_reanalysis_anomaly(_fresh_state(), None) == 0
        assert rec.get("status") == "degraded"

    def test_live_cache_hit_skips_fetch(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")
        monkeypatch.setattr(ra, "load_daily_climatology", lambda *a, **k: {})

        def _boom(*a, **k):
            raise AssertionError("fetch must not run on a same-day cache hit")

        monkeypatch.setattr(ra, "fetch_all_reganom_t2m", _boom)
        monkeypatch.setattr(ra, "detect_regional_anomaly", lambda *a, **k: None)
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: None)
        st = _fresh_state()
        st["_reganom_live_cache"] = {
            "date": date.today().isoformat(),
            "results": {"13.51,2.11": [("2026-06-07", 40.0)]},
        }
        runner.run_reanalysis_anomaly(st, None)  # must not raise

    def test_attempt_time_suppression_and_enqueue(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")
        monkeypatch.setattr(ra, "load_daily_climatology", lambda *a, **k: {})
        monkeypatch.setattr(ra, "fetch_all_reganom_t2m", lambda *a, **k: {(13.51, 2.11): [("2026-06-07", 40.0)]})
        ev = _event()
        monkeypatch.setattr(ra, "detect_regional_anomaly", _detect_for("Sahel", ev))
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: None)
        enq: list[str] = []
        monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda bs, **k: enq.append(k["event_id"]) or True)
        st = _fresh_state()
        runner.run_reanalysis_anomaly(st, None)
        assert ev.event_id in enq
        # §D: the onset marker is written at ATTEMPT time (before the writer runs).
        assert st["reganom_last_fired"]["Sahel"] == ev.window_start

    def test_onset_guard_skips_still_ongoing_window(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")
        monkeypatch.setattr(ra, "load_daily_climatology", lambda *a, **k: {})
        monkeypatch.setattr(ra, "fetch_all_reganom_t2m", lambda *a, **k: {(13.51, 2.11): [("2026-06-07", 40.0)]})
        ev = _event(window_start="2026-06-05")
        monkeypatch.setattr(ra, "detect_regional_anomaly", _detect_for("Sahel", ev))
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: None)
        enq: list[str] = []
        monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda bs, **k: enq.append(k["event_id"]) or True)
        st = _fresh_state()
        st["reganom_last_fired"] = {"Sahel": "2026-06-05"}  # same window already attempted
        runner.run_reanalysis_anomaly(st, None)
        assert enq == []  # ongoing spell — not re-enqueued

    def test_newer_window_fires_after_prior(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")
        monkeypatch.setattr(ra, "load_daily_climatology", lambda *a, **k: {})
        monkeypatch.setattr(ra, "fetch_all_reganom_t2m", lambda *a, **k: {(13.51, 2.11): [("2026-06-12", 41.0)]})
        ev = _event(window_start="2026-06-10", window_end="2026-06-12")  # a NEW spell
        monkeypatch.setattr(ra, "detect_regional_anomaly", _detect_for("Sahel", ev))
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: None)
        enq: list[str] = []
        monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda bs, **k: enq.append(k["event_id"]) or True)
        st = _fresh_state()
        st["reganom_last_fired"] = {"Sahel": "2026-06-05"}  # older window
        runner.run_reanalysis_anomaly(st, None)
        assert ev.event_id in enq

    def test_duplicate_event_is_skipped(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")
        monkeypatch.setattr(ra, "load_daily_climatology", lambda *a, **k: {})
        monkeypatch.setattr(ra, "fetch_all_reganom_t2m", lambda *a, **k: {(13.51, 2.11): [("2026-06-07", 40.0)]})
        ev = _event()
        monkeypatch.setattr(ra, "detect_regional_anomaly", _detect_for("Sahel", ev))
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: None)
        enq: list[str] = []
        monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda bs, **k: enq.append(k["event_id"]) or True)
        st = _fresh_state()
        st["posted_events"] = [ev.event_id]
        runner.run_reanalysis_anomaly(st, None)
        assert enq == []

    def test_one_region_failure_does_not_abort_the_rest(self, monkeypatch) -> None:
        monkeypatch.setenv("THEHEAT_REGANOM_ENABLED", "1")
        monkeypatch.setattr(ra, "load_daily_climatology", lambda *a, **k: {})
        monkeypatch.setattr(ra, "fetch_all_reganom_t2m", lambda *a, **k: {(13.51, 2.11): [("2026-06-07", 40.0)]})
        ev = _event()

        def _detect(region, *a, **k):
            if region.slug == "France":
                raise ValueError("boom in one region")
            return ev if region.slug == "Sahel" else None

        monkeypatch.setattr(ra, "detect_regional_anomaly", _detect)
        rec = {}
        monkeypatch.setattr(runner, "_record_source_run", lambda *a, **k: rec.update(k))
        enq: list[str] = []
        monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda bs, **k: enq.append(k["event_id"]) or True)
        runner.run_reanalysis_anomaly(_fresh_state(), None)
        # France raised, but Sahel still enqueued and the run recorded success.
        assert ev.event_id in enq
        assert rec.get("status") == "success"
