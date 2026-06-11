from src.data.gpm_imerg import CityPrecipReading
from src.data.nsidc_snow import SnowReading
from src.state import _fresh_state


def test_run_gpm_imerg_drafts_and_updates_tracking(monkeypatch):
    from src.orchestrator.sources import gpm_imerg as runner

    bot_state = _fresh_state()
    bot_state["precip_daily_records"] = {
        "france:paris:05-14": {"mm": 40.0, "year": 2024},
    }
    reading = CityPrecipReading(
        city="Paris",
        country="France",
        lat=48.85,
        lon=2.35,
        date="2026-05-14",
        mm_total=75.0,
        source_product="late",
        event_id="gpm_imerg_france_paris_2026-05-14",
    )
    monkeypatch.setattr(runner.gpm_imerg, "fetch_daily_precip", lambda **kwargs: [reading])
    monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", lambda *args, **kwargs: True)
    current_run = {"sources": []}

    drafted = runner.run_gpm_imerg(
        bot_state,
        current_run,
        [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
    )

    assert drafted is None
    assert len(bot_state["_triage_queue"]) == 1
    assert bot_state["_triage_queue"][0].source == "gpm_imerg"
    assert "gpm_precip_record_france_paris_2026-05-14" not in bot_state["posted_events"]
    assert bot_state["precip_daily_records"]["france:paris:05-14"]["mm"] == 75.0

    assert runner._drain_and_write_triage_queue(bot_state, current_run) == 1
    assert "gpm_precip_record_france_paris_2026-05-14" in bot_state["posted_events"]
    assert bot_state["precip_daily_records"]["france:paris:05-14"]["mm"] == 75.0
    assert bot_state["source_health"]["gpm_imerg"]["success"] == 1
    assert current_run["sources"][0]["drafted"] == 1


def test_run_gpm_imerg_uses_default_city_cap_when_env_absent(monkeypatch):
    from src.orchestrator.sources import gpm_imerg as runner

    bot_state = _fresh_state()
    captured = {}

    def fake_fetch_daily_precip(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.delenv("GPM_IMERG_MAX_CITIES", raising=False)
    monkeypatch.setattr(runner.gpm_imerg, "fetch_daily_precip", fake_fetch_daily_precip)

    drafted = runner.run_gpm_imerg(
        bot_state,
        None,
        [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
    )

    assert drafted is None
    assert captured["max_cities"] == runner.gpm_imerg.DEFAULT_CITY_LIMIT
    assert captured["max_workers"] == runner.gpm_imerg.DEFAULT_MAX_WORKERS


def test_run_gpm_imerg_passes_worker_env(monkeypatch):
    from src.orchestrator.sources import gpm_imerg as runner

    bot_state = _fresh_state()
    captured = {}

    def fake_fetch_daily_precip(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setenv("GPM_IMERG_MAX_CITIES", "12")
    monkeypatch.setenv("GPM_IMERG_MAX_WORKERS", "3")
    monkeypatch.setattr(runner.gpm_imerg, "fetch_daily_precip", fake_fetch_daily_precip)

    drafted = runner.run_gpm_imerg(
        bot_state,
        None,
        [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
    )

    assert drafted is None
    assert captured["max_cities"] == 12
    assert captured["max_workers"] == 3


def test_run_nsidc_snow_drafts_seasonal_record_and_counts(monkeypatch):
    from src.orchestrator.sources import nsidc_snow as runner

    bot_state = _fresh_state()
    bot_state["seasonal_snow_records"] = {
        "albro_lake": {"mm": 300.0, "year": 2025, "years_of_archive": 10},
    }
    reading = SnowReading(
        station="Albro Lake",
        lat=45.6,
        lon=-111.96,
        elevation_m=2529.8,
        date="2026-05-14",
        swe_mm=800.0,
        swe_delta_mm=0.0,
        swe_normalized_pct=140.0,
        event_id="nsidc_snow_albro_lake_2026-05-14",
    )
    monkeypatch.setattr(runner.nsidc_snow, "fetch_snow_today", lambda: [reading])
    monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", lambda *args, **kwargs: True)
    current_run = {"sources": []}

    drafted = runner.run_nsidc_snow(bot_state, current_run)

    assert drafted is None
    assert len(bot_state["_triage_queue"]) == 1
    assert bot_state["_triage_queue"][0].source == "nsidc_snow"
    assert "nsidc_snow_seasonal_snow_record_albro_lake_2026-05-14" not in bot_state["posted_events"]

    assert runner._drain_and_write_triage_queue(bot_state, current_run) == 1
    assert "nsidc_snow_seasonal_snow_record_albro_lake_2026-05-14" in bot_state["posted_events"]
    assert bot_state["snow_annual_count"][str(__import__("datetime").date.today().year)] == 1
    assert bot_state["seasonal_snow_records"]["albro_lake"]["mm"] == 800.0
    assert bot_state["source_health"]["nsidc_snow"]["success"] == 1
    assert current_run["sources"][0]["drafted"] == 1
