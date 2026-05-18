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
    monkeypatch.setattr(runner, "_try_two_bot_draft", lambda *args, **kwargs: True)

    drafted = runner.run_gpm_imerg(
        bot_state,
        None,
        [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
    )

    assert drafted == 1
    assert "gpm_precip_record_france_paris_2026-05-14" in bot_state["posted_events"]
    assert bot_state["precip_daily_records"]["france:paris:05-14"]["mm"] == 75.0
    assert bot_state["source_health"]["gpm_imerg"]["success"] == 1


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

    assert drafted == 0
    assert captured["max_cities"] == runner.gpm_imerg.DEFAULT_CITY_LIMIT


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
    monkeypatch.setattr(runner, "_try_two_bot_draft", lambda *args, **kwargs: True)

    drafted = runner.run_nsidc_snow(bot_state, None)

    assert drafted == 1
    assert "nsidc_snow_seasonal_snow_record_albro_lake_2026-05-14" in bot_state["posted_events"]
    assert bot_state["snow_annual_count"][str(__import__("datetime").date.today().year)] == 1
    assert bot_state["seasonal_snow_records"]["albro_lake"]["mm"] == 800.0
    assert bot_state["source_health"]["nsidc_snow"]["success"] == 1
