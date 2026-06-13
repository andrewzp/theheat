"""Integration tests for main orchestrator with all externals mocked."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import ANY, patch, MagicMock
from datetime import date, datetime, timedelta, timezone

import pytest

from src.state import DEFAULT_STATE
from src.main import (
    _classify_ghcn_source_status,
    save_draft,
    post_approved,
    run_alerts,
    run_leaderboard,
    run_manual_tweet,
    process_due_drafts,
)
from src.data.open_meteo import CityTemp, RecordEvent
from src.data.firms import FireEvent
from src.data.co2 import CO2Reading, CO2Milestone
from src.data.coral_dhw import CoralBleachingEvent, CoralDHWReading
from src.data.cyclones import CycloneAdvisory, TierCrossingEvent
from src.data.methane import MethaneMilestone, MethaneReading


def _fresh_state():
    return deepcopy(DEFAULT_STATE)


class TestGhcnSourceStatus:
    def test_success_when_all_diff_dates_fetched(self):
        metrics = {
            "diff_dates_missing": 0,
            "diff_dates_fetched": 3,
            "diff_missing_dates": [],
        }

        assert _classify_ghcn_source_status(metrics, today=date(2026, 5, 14)) == "success"

    def test_tolerates_newest_diff_date_missing(self):
        metrics = {
            "diff_dates_missing": 1,
            "diff_dates_fetched": 2,
            "diff_missing_dates": ["2026-05-13"],
        }

        assert _classify_ghcn_source_status(metrics, today=date(2026, 5, 14)) == "success"

    def test_degraded_when_older_diff_date_missing(self):
        metrics = {
            "diff_dates_missing": 1,
            "diff_dates_fetched": 2,
            "diff_missing_dates": ["2026-05-12"],
        }

        assert _classify_ghcn_source_status(metrics, today=date(2026, 5, 14)) == "degraded"

    def test_degraded_when_multiple_diff_dates_missing(self):
        metrics = {
            "diff_dates_missing": 2,
            "diff_dates_fetched": 1,
            "diff_missing_dates": ["2026-05-13", "2026-05-12"],
        }

        assert _classify_ghcn_source_status(metrics, today=date(2026, 5, 14)) == "degraded"

    def test_degraded_when_missing_dates_not_reported(self):
        metrics = {
            "diff_dates_missing": 1,
            "diff_dates_fetched": 2,
        }

        assert _classify_ghcn_source_status(metrics, today=date(2026, 5, 14)) == "degraded"

    def test_run_alerts_records_success_for_newest_diff_lag(
        self,
        monkeypatch,
        mock_alerts_pipeline_sources,
    ):
        monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "ghcn")
        monkeypatch.setattr("src.main.open_meteo.load_cities", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.firms.fetch_fires", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.fetch_co2_data", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.detect_milestone", MagicMock(return_value=None))

        newest_missing = (date.today() - timedelta(days=1)).isoformat()

        def fake_ghcn_fetch(*, metrics_out=None):
            if metrics_out is not None:
                metrics_out.update({
                    "stations_active": 11982,
                    "stations_with_obs": 3985,
                    "stations_checked": 5207,
                    "raw_signals": 400,
                    "bundles_after_dedup": 0,
                    "diff_dates_attempted": 3,
                    "diff_dates_fetched": 2,
                    "diff_dates_missing": 1,
                    "diff_missing_dates": [newest_missing],
                })
            return [], []

        mock_alerts_pipeline_sources.check_extreme_signals_for_stations.side_effect = (
            fake_ghcn_fetch
        )
        bot_state = _fresh_state()
        current_run = {"sources": []}

        run_alerts(bot_state, current_run=current_run)

        source = next(
            item for item in current_run["sources"]
            if item["source"] == "open_meteo_extreme_signals"
        )
        assert source["status"] == "success"
        assert "diff_missing:1" in source["note"]
        health = bot_state["source_health"]["open_meteo_extreme_signals"]
        assert health["degraded"] == 0
        assert health["success"] == 1


class TestCycloneAlerts:
    def test_run_alerts_records_nhc_cyclone_draft(
        self,
        monkeypatch,
        mock_alerts_pipeline_sources,
    ):
        monkeypatch.setattr("src.main.open_meteo.load_cities", MagicMock(return_value=[]))
        monkeypatch.setattr(
            "src.main.open_meteo.check_extreme_signals_for_cities",
            MagicMock(return_value=([], [])),
        )
        monkeypatch.setattr("src.main.firms.fetch_fires", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.fetch_co2_data", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.detect_milestone", MagicMock(return_value=None))
        draft = MagicMock(return_value=True)
        monkeypatch.setattr("src.main._try_two_bot_draft", draft)

        advisory = CycloneAdvisory(
            source="nhc",
            storm_id="AL012026",
            storm_name="Beryl",
            basin="Atlantic",
            advisory_number="12",
            issued_at="2026-07-02T00:00:00Z",
            wind_kt=115,
            pressure_mb=950,
            lat=18.0,
            lon=-75.0,
            public_advisory_url="https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
        )
        event = TierCrossingEvent(
            source="nhc",
            storm_id="AL012026",
            storm_name="Beryl",
            basin="Atlantic",
            advisory_number="12",
            issued_at="2026-07-02T00:00:00Z",
            from_category=2,
            to_category=4,
            wind_kt=115,
            pressure_mb=950,
            lat=18.0,
            lon=-75.0,
            public_advisory_url="https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
            event_id="nhc_tier_al012026_12_cat4",
        )
        import src.main as main

        main.nhc.fetch_active_cyclones.return_value = [advisory]
        main.nhc.detect_tier_crossings.return_value = [event]
        state_dict = _fresh_state()
        current_run = {"sources": []}

        run_alerts(state_dict, current_run=current_run)

        draft.assert_any_call(
            ANY,
            state_dict,
            ANY,
            legacy_type="cyclone_tier_crossing",
            event_id="nhc_tier_al012026_12_cat4",
            review_context=ANY,
            cooldown_exempt=True,
        )
        source = next(item for item in current_run["sources"] if item["source"] == "nhc")
        assert source["observed"] == 1
        assert source["promoted"] == 1
        assert source["drafted"] == 1
        assert state_dict["cyclone_tiers"]["nhc:al012026"] == 4
        assert state_dict["cyclone_annual_count"][str(date.today().year)] == 1


@pytest.fixture
def mock_alerts_pipeline_sources(monkeypatch):
    """Clamp the run_alerts data sources that test classes typically leave unmocked.

    Covers methane, coral_dhw, nws_alerts, gdacs, copernicus_ems, nhc, jtwc, sea_ice, drought,
    enso, ocean, ocean_sst, ocean_sst_anomaly, water_levels, river_gauges,
    ice_mass, synthesis, ghcn, and fire_footprint. Callers must still mock `src.main.open_meteo`,
    `src.main.firms`, and `src.main.co2` per-test (those vary by scenario).

    run_alerts has 20 _try_two_bot_draft call sites, one per signal-type
    branch. Tests that exercise a single branch and assert call counts on
    `_try_two_bot_draft` need every other branch's data source mocked away,
    or real network responses occasionally trigger extra draft attempts and
    break `assert_called_once`. See test_run_alerts_ocean_sst_drafts_on_day_5
    for the canonical inline equivalent.
    """
    methane = MagicMock()
    monkeypatch.setattr("src.main.methane", methane)
    methane.fetch_ch4_milestones.return_value = []
    methane.detect_milestone.return_value = None

    coral = MagicMock()
    monkeypatch.setattr("src.main.coral_dhw", coral)
    coral.fetch_coral_dhw.return_value = []
    coral.detect_dhw_thresholds.return_value = []

    nws = MagicMock()
    monkeypatch.setattr("src.main.nws_alerts", nws)
    nws.fetch_alerts.return_value = []

    gdacs = MagicMock()
    monkeypatch.setattr("src.main.gdacs", gdacs)
    gdacs.fetch_disasters.return_value = []

    copernicus = MagicMock()
    monkeypatch.setattr("src.main.copernicus_ems", copernicus)
    copernicus.fetch_active_flood_activations.return_value = []
    copernicus.detect_flood_events.return_value = []

    nhc = MagicMock()
    monkeypatch.setattr("src.main.nhc", nhc)
    nhc.fetch_active_cyclones.return_value = []
    nhc.detect_rapid_intensification.return_value = []
    nhc.detect_tier_crossings.return_value = []
    nhc.detect_landfalls.return_value = []

    jtwc = MagicMock()
    monkeypatch.setattr("src.main.jtwc", jtwc)
    jtwc.fetch_active_cyclones.return_value = []
    jtwc.detect_rapid_intensification.return_value = []
    jtwc.detect_tier_crossings.return_value = []
    jtwc.detect_landfalls.return_value = []

    sea_ice = MagicMock()
    monkeypatch.setattr("src.main.sea_ice", sea_ice)
    sea_ice.fetch_sea_ice.return_value = []
    sea_ice.detect_record_low.return_value = None

    drought = MagicMock()
    monkeypatch.setattr("src.main.drought", drought)
    drought.fetch_drought_data.return_value = []

    enso = MagicMock()
    monkeypatch.setattr("src.main.enso", enso)
    enso.fetch_enso_data.return_value = []
    enso.detect_transition.return_value = None

    climate_indices = MagicMock()
    monkeypatch.setattr("src.main.climate_indices", climate_indices)
    climate_indices.fetch_nao.return_value = []
    climate_indices.fetch_ao.return_value = []
    climate_indices.fetch_pdo.return_value = []
    climate_indices.detect_phase_transition.return_value = None
    climate_indices.detect_extreme_excursion.return_value = None
    climate_indices.detect_nao_ao_alignment.return_value = None

    ocean = MagicMock()
    monkeypatch.setattr("src.main.ocean", ocean)
    ocean.fetch_ocean_conditions.return_value = []
    ocean.detect_extreme_waves.return_value = []

    ocean_sst = MagicMock()
    monkeypatch.setattr("src.main.ocean_sst", ocean_sst)
    ocean_sst.fetch_global_sst.return_value = None
    ocean_sst.detect_streak_milestone.return_value = (None, None)

    monkeypatch.setattr("src.main.ocean_sst_anomaly.fetch_all_regions", lambda strict=False: [])

    water = MagicMock()
    monkeypatch.setattr("src.main.water_levels", water)
    water.fetch_water_levels.return_value = []
    water.detect_storm_surge.return_value = []

    river = MagicMock()
    monkeypatch.setattr("src.main.river_gauges", river)
    river.fetch_river_levels.return_value = []
    river.detect_floods.return_value = []

    ice = MagicMock()
    monkeypatch.setattr("src.main.ice_mass", ice)
    ice.fetch_grace_mass.return_value = []
    ice.detect_monthly_record.return_value = None
    ice.detect_cumulative_milestone.return_value = None

    ozone = MagicMock()
    monkeypatch.setattr("src.main.ozone_hole", ozone)
    ozone.fetch_ozone_hole_data.return_value = []
    ozone.fetch_ozone_hole_annual_peaks.return_value = []
    ozone.detect_seasonal_peak.return_value = None

    synth = MagicMock()
    monkeypatch.setattr("src.main.synthesis", synth)
    synth.detect_fire_drought_heat.return_value = []

    ghcn = MagicMock()
    monkeypatch.setattr("src.main.ghcn", ghcn)
    ghcn.check_extreme_signals_for_stations.return_value = ([], [])

    ff = MagicMock()
    monkeypatch.setattr("src.main.fire_footprint", ff)
    ff.fetch_active_fire_perimeters.return_value = []
    ff.detect_tier_crossings.return_value = []
    ff.TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]

    return ghcn


class TestSaveDraft:
    def test_saves_draft_to_state(self):
        state = _fresh_state()
        result = save_draft("test tweet", state, "record", "evt_1")
        assert result is True
        assert len(state["drafts"]) == 1
        assert state["drafts"][0]["text"] == "test tweet"
        assert state["drafts"][0]["status"] == "pending"

    def test_deduplicates_by_event_id(self):
        state = _fresh_state()
        save_draft("tweet 1", state, "record", "evt_1")
        result = save_draft("tweet 2", state, "record", "evt_1")
        assert result is False
        assert len(state["drafts"]) == 1

    def test_allows_empty_event_id(self):
        state = _fresh_state()
        save_draft("tweet 1", state, "custom", "")
        save_draft("tweet 2", state, "custom", "")
        assert len(state["drafts"]) == 2

    def test_persists_score_metadata(self):
        from src.editorial.scoring import score_co2_milestone

        state = _fresh_state()
        score = score_co2_milestone(434, 434.02)
        save_draft("test tweet", state, "co2_milestone", "evt_1", score=score)
        assert state["drafts"][0]["score"]["total"] == score.total
        assert state["drafts"][0]["score"]["passes"] is True

    def test_persists_candidate_metadata(self):
        from src.editorial.candidates import rank_candidates
        from src.editorial.scoring import score_record_event

        state = _fresh_state()
        bundle = rank_candidates(
            [
                "Phoenix just hit 121F. NEW RECORD. The old one was from 1998.",
                "Phoenix with 121F today. That broke a 27-year record.",
            ],
            "record",
        )
        score = score_record_event(49.4, 47.2, 1998)
        save_draft(
            bundle.text,
            state,
            "record",
            "evt_record",
            score=score,
            candidates=[candidate.as_dict() for candidate in bundle.candidates],
            candidate_score=bundle.selected_score.as_dict(),
        )

        assert len(state["drafts"][0]["candidates"]) == 2
        assert state["drafts"][0]["candidate_score"]["total"] == bundle.selected_score.total

    def test_persists_review_context(self):
        from src.editorial.scoring import score_fire_event

        state = _fresh_state()
        score = score_fire_event(97, 1200, region="Northern California")
        review_context = {
            "source": "NASA FIRMS",
            "source_key": "firms",
            "headline": "Wildfire signal near Northern California",
            "facts": [{"label": "Satellite confidence", "value": "97%"}],
            "run_id": "run_alerts_1",
        }

        save_draft(
            "Fire signal draft",
            state,
            "fire",
            "fire_evt",
            score=score,
            review_context=review_context,
        )

        assert state["drafts"][0]["review_context"]["source"] == "NASA FIRMS"
        assert state["drafts"][0]["review_context"]["facts"][0]["value"] == "97%"

    def test_arms_policy_auto_for_hot10(self):
        from src.editorial.scoring import score_hot10

        state = _fresh_state()
        score = score_hot10(9.2, 10, 3)
        save_draft(
            "Hot 10 draft",
            state,
            "hot10",
            "hot10_evt",
            score=score,
            candidate_score={"total": 81},
        )

        assert state["drafts"][0]["approval_policy"]["mode"] == "armed_auto"
        assert state["drafts"][0]["auto_approve_at"].endswith("Z")
        assert state["drafts"][0]["approval_mode"] == "policy_auto"

    def test_blocks_auto_policy_for_sensitive_drafts(self):
        from src.editorial.scoring import score_global_disaster

        state = _fresh_state()
        score = score_global_disaster("Red", "Cyclone")
        save_draft(
            "Disaster draft",
            state,
            "global_disaster",
            "gdacs_evt",
            score=score,
            candidate_score={"total": 84},
        )

        assert state["drafts"][0]["approval_policy"]["mode"] == "manual_only"
        assert "auto_approve_at" not in state["drafts"][0]

    def _bundle_with_advisory_url(self, url: str):
        return SimpleNamespace(
            signal_kind="cyclone_tier_crossing",
            where="Beryl, Atlantic",
            current_facts=[{"label": "public_advisory_url", "value": url}],
        )

    def _dispatch_module(self):
        import importlib
        import src.orchestrator.two_bot_dispatch as dispatch

        return importlib.reload(dispatch)

    def test_cyclone_draft_gets_advisory_url_when_fits(self, monkeypatch):
        from src.editorial.scoring import score_cyclone_tier_crossing
        dispatch = self._dispatch_module()

        monkeypatch.setattr(
            "src.two_bot.pipeline.generate_draft",
            lambda *args, **kwargs: {"text": "Beryl jumped to Category 4 in the Atlantic.", "two_bot_metadata": {}},
        )
        state = _fresh_state()
        url = "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"

        saved = dispatch._try_two_bot_draft(
            self._bundle_with_advisory_url(url),
            state,
            score_cyclone_tier_crossing(2, 4, "Atlantic"),
            legacy_type="cyclone_tier_crossing",
            event_id="cyclone_evt_1",
            review_context={"facts": []},
        )

        assert saved is True
        assert state["drafts"][0]["text"].endswith(f"\n{url}")

    def test_url_omitted_when_over_budget(self, monkeypatch):
        from src.editorial.scoring import score_cyclone_tier_crossing
        dispatch = self._dispatch_module()

        monkeypatch.setattr(
            "src.two_bot.pipeline.generate_draft",
            lambda *args, **kwargs: {"text": "x" * 250, "two_bot_metadata": {}},
        )
        state = _fresh_state()
        url = "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"

        saved = dispatch._try_two_bot_draft(
            self._bundle_with_advisory_url(url),
            state,
            score_cyclone_tier_crossing(2, 4, "Atlantic"),
            legacy_type="cyclone_tier_crossing",
            event_id="cyclone_evt_2",
            review_context={"facts": []},
        )

        assert saved is True
        assert state["drafts"][0]["text"] == "x" * 250

    def test_non_cyclone_unaffected(self, monkeypatch):
        from src.editorial.scoring import score_fire_event
        dispatch = self._dispatch_module()

        monkeypatch.setattr(
            "src.two_bot.pipeline.generate_draft",
            lambda *args, **kwargs: {"text": "Fire signal draft", "two_bot_metadata": {}},
        )
        state = _fresh_state()
        url = "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"

        saved = dispatch._try_two_bot_draft(
            self._bundle_with_advisory_url(url),
            state,
            score_fire_event(97, 1200, region="Northern California"),
            legacy_type="fire",
            event_id="fire_evt_1",
            review_context={"facts": []},
        )

        assert saved is True
        assert state["drafts"][0]["text"] == "Fire signal draft"


class TestSameCityDayDedup:
    """One tweet per (city, date). Highest signal score wins."""

    def _score_with_total(self, total: int):
        from src.editorial.scoring import EditorialScore

        return EditorialScore(
            category="record",
            severity=0,
            novelty=0,
            timeliness=0,
            confidence=0,
            shareability=0,
            sensitivity=0,
            total=total,
            threshold=72,
            reasons=[],
        )

    def test_stronger_signal_supersedes_pending(self):
        state = _fresh_state()
        save_draft(
            "weak Bujumbura tweet",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        result = save_draft(
            "strong Bujumbura tweet",
            state,
            "monthly_high",
            "monthly_high_Bujumbura_2026_04",
            score=self._score_with_total(82),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        assert result is True
        assert len(state["drafts"]) == 1
        assert state["drafts"][0]["text"] == "strong Bujumbura tweet"
        assert state["drafts"][0]["score"]["total"] == 82

    def test_weaker_signal_dropped(self):
        state = _fresh_state()
        save_draft(
            "strong tweet",
            state,
            "monthly_high",
            "monthly_high_Bujumbura_2026_04",
            score=self._score_with_total(82),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        result = save_draft(
            "weak tweet",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        assert result is False
        assert len(state["drafts"]) == 1
        assert state["drafts"][0]["text"] == "strong tweet"

    def test_different_cities_both_saved(self):
        state = _fresh_state()
        save_draft(
            "Bujumbura",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        save_draft(
            "Medan",
            state,
            "record",
            "record_Medan_2026-04-18",
            score=self._score_with_total(72),
            city="Medan",
            tweet_date="2026-04-18",
        )
        assert len(state["drafts"]) == 2

    def test_same_city_different_dates_both_saved(self):
        state = _fresh_state()
        save_draft(
            "day one",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        save_draft(
            "day two",
            state,
            "all_time_high",
            "all_time_high_Bujumbura_2026-04-19",
            score=self._score_with_total(80),
            city="Bujumbura",
            tweet_date="2026-04-19",
            cooldown_exempt=True,
        )
        assert len(state["drafts"]) == 2

    def test_already_posted_same_day_skipped(self):
        state = _fresh_state()
        state["drafts"].append(
            {
                "id": "draft_1",
                "text": "posted already",
                "type": "record",
                "event_id": "record_Bujumbura_2026-04-18",
                "status": "posted",
                "city": "Bujumbura",
                "tweet_date": "2026-04-18",
                "posted_at": "2026-04-18T10:00:00Z",
                "score": {"total": 72},
            }
        )
        result = save_draft(
            "stronger too late",
            state,
            "monthly_high",
            "monthly_high_Bujumbura_2026_04",
            score=self._score_with_total(85),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        assert result is False
        assert len(state["drafts"]) == 1


class TestCityCooldown:
    """After we post about a city, suppress that city for N days unless elite."""

    def _score_with_total(self, total: int):
        from src.editorial.scoring import EditorialScore

        return EditorialScore(
            category="record",
            severity=0,
            novelty=0,
            timeliness=0,
            confidence=0,
            shareability=0,
            sensitivity=0,
            total=total,
            threshold=72,
            reasons=[],
        )

    def _seed_recent_posted_draft(self, state: dict, city: str, hours_ago: int):
        from datetime import timedelta

        from src.main import _utc_now

        posted_at = (_utc_now() - timedelta(hours=hours_ago)).isoformat().replace(
            "+00:00", "Z"
        )
        state["drafts"].append(
            {
                "id": f"draft_old_{city}",
                "text": f"old {city} tweet",
                "type": "record",
                "event_id": f"record_{city}_old",
                "status": "posted",
                "city": city,
                "tweet_date": "2026-04-15",
                "posted_at": posted_at,
                "score": {"total": 72},
            }
        )

    def test_blocks_non_elite_within_cooldown(self):
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix again",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
        )
        assert result is False
        assert len(state["drafts"]) == 1

    def test_allows_elite_during_cooldown(self):
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix all-time record",
            state,
            "all_time_high",
            "all_time_high_Phoenix_2026-04-19",
            score=self._score_with_total(85),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=True,
        )
        assert result is True
        assert len(state["drafts"]) == 2

    def test_allows_non_elite_after_cooldown_expires(self):
        state = _fresh_state()
        # 4 days ago — past the 3-day cooldown
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=4 * 24)
        result = save_draft(
            "Phoenix after cooldown",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
        )
        assert result is True
        assert len(state["drafts"]) == 2

    def test_no_city_no_cooldown(self):
        """Events without a city (CO2 milestone, simultaneous, etc.) are unaffected."""
        state = _fresh_state()
        # Seed a recent posted draft with no city attached
        state["drafts"].append(
            {
                "id": "co2_old",
                "text": "old CO2",
                "type": "co2_milestone",
                "event_id": "co2_434",
                "status": "posted",
                "posted_at": "2026-04-18T10:00:00Z",
            }
        )
        result = save_draft(
            "new CO2",
            state,
            "co2_milestone",
            "co2_435",
            score=self._score_with_total(65),
        )
        assert result is True

    def test_exceptional_copy_bypasses_cooldown(self):
        """candidate_score.total >= 95 lets an otherwise-blocked draft through."""
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix with stunning copy",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
            candidate_score={"total": 96},
        )
        assert result is True
        assert len(state["drafts"]) == 2

    def test_merely_good_copy_does_not_bypass_cooldown(self):
        """Copy at 94 still respects cooldown — only >=95 counts as elite."""
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix good but not great",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
            candidate_score={"total": 94},
        )
        assert result is False
        assert len(state["drafts"]) == 1

    def test_pending_drafts_do_not_trigger_cooldown(self):
        """Cooldown only triggers on posted tweets, not pending drafts."""
        state = _fresh_state()
        save_draft(
            "first Phoenix draft",
            state,
            "record",
            "record_Phoenix_2026-04-18",
            score=self._score_with_total(72),
            city="Phoenix",
            tweet_date="2026-04-18",
        )
        # Different day, different city — no cooldown because the prior is pending
        result = save_draft(
            "Bujumbura new day",
            state,
            "record",
            "record_Bujumbura_2026-04-19",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-19",
        )
        assert result is True


class TestMonthlyRecordSameYearSuppression:
    """Monthly records where the prior record was set in the current calendar
    year read as nonsense ('hottest April — previous record set in 2026').
    Suppress them at detection."""

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_suppresses_monthly_when_old_record_this_year(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        from src.data.open_meteo import ExtremeSignalBundle, MonthlyRecord
        from datetime import date

        current_year = date.today().year
        # Bundle where the only detected signal is a monthly_high whose
        # prior record was set this calendar year — should be skipped.
        bundle = ExtremeSignalBundle(
            monthly_high=MonthlyRecord(
                city="Svalbard",
                country="NO",
                kind="high",
                month=4,
                new_temp_c=5.3,
                old_record_c=3.7,
                old_record_year=current_year,
                years_of_data=30,
                event_id=f"monthly_high_Svalbard_{current_year}_04",
            ),
        )
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([bundle], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_monthly_record_tweet.assert_not_called()

    @patch("src.main._try_two_bot_draft")
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_allows_monthly_when_old_record_prior_year(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft, mock_two_bot,
        mock_alerts_pipeline_sources,
    ):
        """When the prior record was set in a prior year, the signal
        should be allowed through — and it should hit the two-bot
        pipeline (monthly_high was ported from voice gen to two-bot
        on 2026-05-03 per the no-cheap-model-writing directive)."""
        from src.data.open_meteo import ExtremeSignalBundle, MonthlyRecord
        from datetime import date

        bundle = ExtremeSignalBundle(
            monthly_high=MonthlyRecord(
                city="Svalbard",
                country="NO",
                kind="high",
                month=4,
                new_temp_c=5.3,
                old_record_c=3.7,
                old_record_year=date.today().year - 5,
                years_of_data=30,
                event_id="monthly_high_Svalbard_2021_04",
            ),
        )
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([bundle], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False
        mock_two_bot.return_value = True

        state = _fresh_state()
        run_alerts(state)

        # Voice generator must NOT be called for monthly_high anymore —
        # this is the whole point of the port.
        mock_gen.generate_monthly_record_tweet.assert_not_called()
        # Two-bot path is exercised. The bundle that flows through is
        # built from the MonthlyRecord above.
        mock_two_bot.assert_called_once()


class TestCO2AnnualCap:
    """At most 12 CO2 tweets per calendar year — prevents feed spam from
    multiple milestones clustering in a noisy week."""

    def test_cap_helpers_increment_and_detect(self):
        from src.main import (
            CO2_ANNUAL_CAP,
            _co2_annual_cap_reached,
            _increment_co2_annual_count,
        )
        from datetime import date

        state = _fresh_state()
        assert _co2_annual_cap_reached(state) is False
        for _ in range(CO2_ANNUAL_CAP):
            _increment_co2_annual_count(state)
        assert _co2_annual_cap_reached(state) is True
        assert state["co2_annual_count"][str(date.today().year)] == CO2_ANNUAL_CAP

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    def test_skips_milestone_when_cap_reached(
        self, mock_om, mock_firms, mock_co2, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        from src.main import CO2_ANNUAL_CAP
        from datetime import date

        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = [MagicMock()]
        mock_co2.detect_milestone.return_value = CO2Milestone(
            ppm_crossed=436,
            actual_ppm=436.1,
            date="2026-04-19",
            event_id="co2_milestone_436ppm",
        )

        state = _fresh_state()
        state["co2_annual_count"] = {str(date.today().year): CO2_ANNUAL_CAP}

        run_alerts(state)
        # CO2 milestone draft should not have been generated
        mock_gen.generate_co2_milestone_tweet.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main._try_two_bot_draft")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    def test_allows_milestone_below_cap(
        self, mock_om, mock_firms, mock_co2, mock_two_bot, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        """Below the annual CO2 cap, a fresh milestone should reach the
        two-bot pipeline (ported from voice gen on 2026-05-04)."""
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = [MagicMock()]
        mock_co2.detect_milestone.return_value = CO2Milestone(
            ppm_crossed=436,
            actual_ppm=436.1,
            date="2026-04-19",
            event_id="co2_milestone_436ppm",
        )
        mock_two_bot.return_value = True

        state = _fresh_state()
        # 3 tweets this year is well under cap — milestone should draft
        from datetime import date

        state["co2_annual_count"] = {str(date.today().year): 3}

        run_alerts(state)
        # Voice gen no longer called; two-bot path is the live path.
        mock_gen.generate_co2_milestone_tweet.assert_not_called()
        mock_two_bot.assert_called_once()


class TestCH4Alerts:
    @patch("src.main._try_two_bot_draft")
    def test_run_alerts_drafts_ch4_milestone(
        self,
        mock_two_bot,
        monkeypatch,
        mock_alerts_pipeline_sources,
    ):
        import src.main as main

        monkeypatch.setattr("src.main.open_meteo.load_cities", MagicMock(return_value=[]))
        monkeypatch.setattr(
            "src.main.open_meteo.check_extreme_signals_for_cities",
            MagicMock(return_value=([], [])),
        )
        monkeypatch.setattr("src.main.firms.fetch_fires", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.fetch_co2_data", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.detect_milestone", MagicMock(return_value=None))
        main.methane.fetch_ch4_milestones.return_value = [
            MethaneReading("2026-03-01", 1938.0, "ch4_2026-03"),
            MethaneReading("2026-04-01", 1942.3, "ch4_2026-04"),
        ]
        main.methane.detect_milestone.return_value = MethaneMilestone(
            ppb_crossed=1940,
            actual_ppb=1942.3,
            date="2026-04-01",
            event_id="ch4_milestone_1940ppb",
        )
        mock_two_bot.return_value = True

        state = _fresh_state()
        current_run = {"sources": []}
        run_alerts(state, current_run=current_run)

        mock_two_bot.assert_any_call(
            ANY,
            state,
            ANY,
            legacy_type="ch4_milestone",
            event_id="ch4_milestone_1940ppb",
            review_context=ANY,
        )
        assert state["ch4_last_milestone"] == 1940
        assert state["ch4_annual_count"][str(date.today().year)] == 1
        source = next(item for item in current_run["sources"] if item["source"] == "ch4_milestone")
        assert source["observed"] == 2
        assert source["promoted"] == 1


class TestCoralDHWAlerts:
    def test_run_alerts_coral_dhw_enqueues_to_triage_queue(
        self,
        monkeypatch,
        mock_alerts_pipeline_sources,
    ):
        """coral_dhw is now migrated to the triage path. When run_coral_dhw
        processes a passing-score event, it enqueues a TriageCandidateBundle
        instead of calling _try_two_bot_draft directly.

        We test this by calling run_coral_dhw in isolation (not through run_alerts,
        which runs all sources and has Python 3.14 specialization issues with
        module-level monkeypatching).

        The drain step behavior (drafted counter, annual count) is tested separately
        in TestDrainTelemetry and TestCoralDHWSourceRunnerMigration.
        """
        import src.orchestrator.sources.coral_dhw as coral_source
        from src.two_bot.types import TriageCandidateBundle
        from src.orchestrator.sources.coral_dhw import run_coral_dhw

        reading = CoralDHWReading(
            region_id="gbr_northern",
            region_full_name="Northern GBR",
            date="2026-05-13",
            dhw_value=8.2,
            stress_level="Alert Level 1",
            baa_7day_max=3,
            lat=-16.1,
            lon=145.975,
        )
        event = CoralBleachingEvent(
            region_id="gbr_northern",
            region_full_name="Northern GBR",
            date="2026-05-13",
            dhw_value=8.2,
            dhw_tier=8,
            bleaching_level="mass bleaching expected",
            stress_level="Alert Level 1",
            lat=-16.1,
            lon=145.975,
            event_id="coral_dhw_gbr_northern_tier8",
        )
        # Patch the data module in the namespace where run_coral_dhw actually looks it up.
        coral_data_mock = MagicMock()
        coral_data_mock.fetch_coral_dhw.return_value = [reading]
        coral_data_mock.detect_dhw_thresholds.return_value = [event]
        monkeypatch.setattr(coral_source, "coral_dhw", coral_data_mock)

        state = _fresh_state()
        current_run = {"sources": []}
        # Call the source runner directly (not through run_alerts) to avoid
        # Python 3.14 adaptive specialization caching issues with monkeypatching.
        run_coral_dhw(state, current_run)

        # The source runner should have enqueued exactly one candidate.
        queue = state.get("_triage_queue", [])
        assert len(queue) == 1
        candidate = queue[0]
        assert isinstance(candidate, TriageCandidateBundle)
        assert candidate.source == "coral_dhw"
        assert candidate.legacy_type == "coral_bleaching"
        assert candidate.event_id == "coral_dhw_gbr_northern_tier8"
        assert candidate.cooldown_exempt is False

        # Tier update is gated on on_draft_success — spec § 7 says spilled
        # candidates must re-detect on next cron, and for coral_dhw the tier
        # update IS the re-detection cooldown. On enqueue alone, the tier must
        # NOT yet be in coral_dhw_last_tier.
        last_tiers = state.get("coral_dhw_last_tier", {})
        assert "gbr_northern" not in last_tiers or last_tiers.get("gbr_northern") != 8

        # Source run telemetry: observed=1, promoted=1 (drafted is deferred to drain).
        source = next(item for item in current_run["sources"] if item["source"] == "coral_dhw")
        assert source["observed"] == 1
        assert source["promoted"] == 1


class TestPostApproved:
    @patch("src.main.state")
    @patch("src.main.post_tweet")
    def test_respects_daily_cap(self, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = False
        state = _fresh_state()
        draft = {
            "id": "draft_1",
            "event_id": "event_1",
            "publish_intent_id": "intent_1",
            "text": "test tweet",
        }
        result = post_approved(draft, state)
        assert result == "failed"
        mock_tw.assert_not_called()

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    def test_no_tweet_without_durable_intent(self, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_state.write_state.return_value = False
        state = _fresh_state()
        draft = {
            "id": "draft_1",
            "event_id": "event_1",
            "publish_intent_id": "intent_1",
            "text": "test tweet",
        }

        result = post_approved(draft, state)

        assert result == "failed"
        mock_state.write_state.assert_called_once_with(state)
        mock_tw.assert_not_called()

    @patch("src.main.state")
    @patch("src.main.post_to_bluesky")
    @patch("src.main.post_tweet")
    def test_increments_count_on_success(self, mock_tw, mock_bluesky, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_state.write_state.return_value = True
        mock_tw.return_value = {"id": "123"}
        state = _fresh_state()
        draft = {
            "id": "draft_1",
            "event_id": "event_1",
            "publish_intent_id": "intent_1",
            "text": "test tweet",
        }
        result = post_approved(draft, state)
        assert result == "posted"
        assert state["publish_ledger"]["event_1"]["tweet_id"] == "123"
        assert draft["tweet_id"] == "123"
        mock_bluesky.assert_called_once_with("test tweet")
        mock_state.increment_daily_count.assert_called_once_with(state)

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    def test_returns_failed_on_failure(self, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_state.write_state.return_value = True
        mock_tw.return_value = None
        state = _fresh_state()
        draft = {
            "id": "draft_1",
            "event_id": "event_1",
            "publish_intent_id": "intent_1",
            "text": "test tweet",
        }
        result = post_approved(draft, state)
        assert result == "failed"

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    def test_returns_rate_limited(self, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_state.write_state.return_value = True
        mock_tw.return_value = {"error": "rate_limited"}
        state = _fresh_state()
        draft = {
            "id": "draft_1",
            "event_id": "event_1",
            "publish_intent_id": "intent_1",
            "text": "test tweet",
        }
        result = post_approved(draft, state)
        assert result == "rate_limited"
        mock_state.increment_daily_count.assert_not_called()


class TestRunAlerts:
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_calls_all_data_sources(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False

        state = _fresh_state()
        run_alerts(state)

        mock_om.load_cities.assert_called_once()
        mock_om.check_extreme_signals_for_cities.assert_called_once()
        mock_firms.fetch_fires.assert_called_once()
        mock_co2.fetch_co2_data.assert_called_once()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_deduplicates_events(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_om.check_records_for_cities.return_value = [
            RecordEvent("Phoenix", "US", 48.0, 47.0, 2023, "record_phoenix_1"),
        ]
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = True

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_record_tweet.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_data_source_errors_gracefully(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        mock_om.load_cities.side_effect = Exception("API down")
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None

        state = _fresh_state()
        result = run_alerts(state)
        assert result is not None
        mock_state.log_error.assert_called()

    @patch("src.main.save_draft")
    @patch("src.two_bot.pipeline.generate_fire_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_drafts_fire_alert(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen,
        mock_generate_fire_draft, mock_draft,
        monkeypatch,
        mock_alerts_pipeline_sources,
    ):
        # Pin scoring.date.today() to mid-April so the shoulder-season novelty
        # boost keeps the synthetic fire above the editorial threshold across
        # calendar tipover (May would drop a frp=250 signal below 64).
        import src.editorial.scoring as _scoring
        class _FixedAprilDate(date):
            @classmethod
            def today(cls):
                return date(2026, 4, 15)
        monkeypatch.setattr(_scoring, "date", _FixedAprilDate)

        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_om.check_records_for_cities.return_value = []
        mock_firms.fetch_fires.return_value = [
            FireEvent(34.0, -118.0, 95, 250.0, "Southwestern US", "US", "fire_1"),
        ]
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False
        mock_generate_fire_draft.return_value = {
            "type": "fire",
            "text": "Fire in Southwestern US.",
            "event_id": "fire_1",
            "two_bot_metadata": {"angle_chosen": "plain_number"},
        }
        mock_draft.return_value = True
        mock_two_bot = MagicMock(return_value=True)
        monkeypatch.setattr("src.main._try_two_bot_draft", mock_two_bot)

        state = _fresh_state()
        run_alerts(state)

        mock_generate_fire_draft.assert_not_called()
        mock_two_bot.assert_called_once()
        mock_gen.generate_fire_tweet.assert_not_called()

    def test_run_alerts_ocean_sst_drafts_on_day_5(self, monkeypatch):
        """Day-5 streak crossing → one draft saved under marine_heatwave."""
        from src import main
        from src.main import run_alerts
        from src.data.ocean_sst import GlobalSSTObservation

        fresh_st = _fresh_state()
        fresh_st["ocean_sst_streak"] = {"seeded": True, "last_milestone_fired": None}

        obs = GlobalSSTObservation(
            date="2026-04-20", day_of_year=110,
            today_c=20.52, archive_max_c=20.31,
            archive_max_year=2023, years_of_data=44,
            streak_days=5, streak_start_date="2026-04-16",
            streak_peak_anomaly_c=0.25,
        )

        # Patch all other alert sources to no-ops so only ocean_sst runs.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities", lambda cities: ([], []))
        monkeypatch.setattr(main.firms, "fetch_fires", lambda: [])
        monkeypatch.setattr(main.co2, "fetch_co2_data", lambda: [])
        monkeypatch.setattr(main.co2, "detect_milestone", lambda readings: None)
        monkeypatch.setattr(main.methane, "fetch_ch4_milestones", lambda: [])
        monkeypatch.setattr(main.methane, "detect_milestone", lambda readings, **kwargs: None)
        monkeypatch.setattr(main.coral_dhw, "fetch_coral_dhw", lambda: [])
        monkeypatch.setattr(main.coral_dhw, "detect_dhw_thresholds", lambda readings, last_tiers=None: [])
        monkeypatch.setattr(main.nws_alerts, "fetch_alerts", lambda: [])
        monkeypatch.setattr(main.gdacs, "fetch_disasters", lambda min_severity=None: [])
        monkeypatch.setattr(main.copernicus_ems, "fetch_active_flood_activations", lambda: [])
        monkeypatch.setattr(main.copernicus_ems, "detect_flood_events", lambda activations, tiers=None: [])
        monkeypatch.setattr(main.sea_ice, "fetch_sea_ice", lambda hemisphere=None: [])
        monkeypatch.setattr(main.sea_ice, "detect_record_low", lambda readings: None)
        monkeypatch.setattr(main.drought, "fetch_drought_data", lambda: [])
        monkeypatch.setattr(main.enso, "fetch_enso_data", lambda: [])
        monkeypatch.setattr(main.enso, "detect_transition", lambda readings: None)
        monkeypatch.setattr(main.ocean, "fetch_ocean_conditions", lambda: [])
        monkeypatch.setattr(main.ocean, "detect_extreme_waves", lambda r: [])
        monkeypatch.setattr(main.ocean_sst, "fetch_global_sst", lambda: obs)
        monkeypatch.setattr(main.ocean_sst_anomaly, "fetch_all_regions", lambda strict=False: [])
        monkeypatch.setattr(main.water_levels, "fetch_water_levels", lambda: [])
        monkeypatch.setattr(main.water_levels, "detect_storm_surge", lambda r: [])
        monkeypatch.setattr(main.river_gauges, "fetch_river_levels", lambda: [])
        monkeypatch.setattr(main.river_gauges, "detect_floods", lambda r: [])

        # Stub the two-bot pipeline (live path post-2026-05-04 port) so
        # we don't make real LLM calls. Side-effect: save a draft to
        # state so the assertions below see the marine_heatwave draft.
        captured = {}
        def fake_try_two_bot(bundle, bot_state, score, *, legacy_type, event_id, review_context, **kwargs):
            from src.main import save_draft
            captured["bundle"] = bundle
            captured["legacy_type"] = legacy_type
            return save_draft(
                "Day 5 of record global SSTs.",
                bot_state, legacy_type, event_id,
                score=score,
                review_context=review_context,
            )
        monkeypatch.setattr(main, "_try_two_bot_draft", fake_try_two_bot)

        run_alerts(fresh_st)

        drafts = fresh_st.get("drafts", [])
        marine_drafts = [d for d in drafts if d.get("type") == "marine_heatwave"]
        assert len(marine_drafts) == 1
        assert "marine_heatwave_streak_5_2026-04-20" in fresh_st.get("posted_events", [])
        assert captured["legacy_type"] == "marine_heatwave"
        assert captured["bundle"].signal_kind == "marine_heatwave"
        assert captured["bundle"].headline_metric == {
            "label": "streak_days",
            "value": 5,
            "unit": "days",
        }
        assert captured["bundle"].historical_context["archive_max_year"] == 2023


class TestRunLeaderboard:
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main._try_two_bot_draft")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_computes_anomalies_and_drafts(
        self, mock_state, mock_om, mock_two_bot, mock_gen, mock_draft
    ):
        """Hot 10 leaderboard: ported from voice gen to two-bot writer
        on 2026-05-04. The voice generator's `generate_tweet` is no
        longer reached for the hot10 category."""
        mock_om.load_cities.return_value = [
            {"city": "Phoenix", "country": "US", "lat": "33.45", "lon": "-112.07"}
        ]
        mock_om.load_normals.return_value = {"Phoenix": {4: 30.0}}
        mock_om.fetch_all_city_temps.return_value = [
            CityTemp("Phoenix", "US", 33.45, -112.07, 45.0),
        ]
        mock_om.compute_anomalies.return_value = [
            CityTemp("Phoenix", "US", 33.45, -112.07, 45.0, 30.0, 15.0),
        ]
        mock_om.rank_hot10.return_value = [
            CityTemp("Phoenix", "US", 33.45, -112.07, 45.0, 30.0, 15.0),
        ]
        mock_two_bot.return_value = True
        mock_state.update_streaks.return_value = {}

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_om.compute_anomalies.assert_called_once()
        mock_om.rank_hot10.assert_called_once()
        mock_gen.generate_tweet.assert_not_called()
        mock_two_bot.assert_called_once()
        assert result is not None

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_empty_temps_gracefully(
        self, mock_state, mock_om, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.load_normals.return_value = {}
        mock_om.fetch_all_city_temps.return_value = []

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_gen.generate_tweet.assert_not_called()
        mock_draft.assert_not_called()
        assert result is not None

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_no_valid_anomalies(
        self, mock_state, mock_om, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = [
            {"city": "Unknown", "country": "XX", "lat": "0", "lon": "0"}
        ]
        mock_om.load_normals.return_value = {}
        mock_om.fetch_all_city_temps.return_value = [
            CityTemp("Unknown", "XX", 0, 0, 30.0),
        ]
        mock_om.compute_anomalies.return_value = []
        mock_om.rank_hot10.return_value = []

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_gen.generate_tweet.assert_not_called()
        assert result is not None

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_updates_state_with_hot10(
        self, mock_state, mock_om, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.load_normals.return_value = {}
        mock_om.fetch_all_city_temps.return_value = [
            CityTemp("Miami", "US", 25.76, -80.19, 38.0),
        ]
        mock_om.compute_anomalies.return_value = [
            CityTemp("Miami", "US", 25.76, -80.19, 38.0, 30.0, 8.0),
        ]
        mock_om.rank_hot10.return_value = [
            CityTemp("Miami", "US", 25.76, -80.19, 38.0, 30.0, 8.0),
        ]
        mock_gen.generate_tweet.return_value = "Hot 10: Miami +8."
        mock_draft.return_value = True
        mock_state.update_streaks.return_value = {}

        state = _fresh_state()
        result = run_leaderboard(state)

        assert "last_hot10" in result
        assert "Miami" in result["last_hot10"]["cities"]


class TestRunManualTweet:
    @patch.dict("os.environ", {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1"}, clear=True)
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_updates_matching_draft_by_id(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        mock_post.return_value = "posted"
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "approved",
        }]

        result = run_manual_tweet(state)

        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["posted_at"].endswith("Z")
        assert "publish_intent_id" not in result["drafts"][0]

    @patch.dict("os.environ", {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1"}, clear=True)
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_returns_draft_to_pending_on_safety_failure(self, mock_safety, mock_post):
        mock_safety.return_value = (False, "Banned pattern: '!'")
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "approved",
        }]

        result = run_manual_tweet(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["post_error"] == "Banned pattern: '!'"

    @patch.dict(
        "os.environ",
        {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1", "PUBLISH_INTENT_ID": "stale-token"},
        clear=True,
    )
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_skips_stale_publish_intent(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "approved",
            "publish_intent_id": "fresh-token",
        }]

        result = run_manual_tweet(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "approved"

    @patch.dict("os.environ", {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1"}, clear=True)
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_rejects_non_approved_draft_posts(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "pending",
        }]

        result = run_manual_tweet(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"

    @patch.dict("os.environ", {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1"}, clear=True)
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_manual_tweet_ignores_spacing_guard(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        mock_post.return_value = "posted"
        state = _fresh_state()
        recent_posted_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat().replace("+00:00", "Z")
        state["drafts"] = [
            {
                "id": "posted_recently",
                "text": "Already posted",
                "status": "posted",
                "posted_at": recent_posted_at,
            },
            {
                "id": "draft_1",
                "text": "Manual draft",
                "status": "approved",
            },
        ]

        result = run_manual_tweet(state)

        mock_post.assert_called_once_with(state["drafts"][1], state)
        assert result["drafts"][1]["status"] == "posted"


class TestProcessDueDrafts:
    @staticmethod
    def _due_auto_draft(draft_id: str, text: str = "Queued draft"):
        return {
            "id": draft_id,
            "text": text,
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "armed_auto",
                "can_auto_approve": True,
            },
        }

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_half_recorded_post_repaired_not_reposted(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["publish_ledger"] = {
            "event_1": {
                "intent_id": "intent_1",
                "tweet_id": "tweet_123",
                "at": "2026-06-12T12:00:00Z",
            }
        }
        state["drafts"] = [{
            "id": "draft_1",
            "event_id": "event_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "armed_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_safety.assert_not_called()
        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["tweet_id"] == "tweet_123"
        assert result["drafts"][0]["posted_at"] == "2026-06-12T12:00:00Z"

    @patch("src.main.post_approved")
    def test_stale_intent_cleared_after_2h(self, mock_post):
        state = _fresh_state()
        state["publish_ledger"] = {
            "event_1": {
                "intent_id": "intent_1",
                "tweet_id": None,
                "at": "2000-01-01T00:00:00Z",
            }
        }

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert "event_1" not in result["publish_ledger"]

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_posts_due_auto_approved_drafts(self, mock_safety, mock_post):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "armed_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_safety.assert_called_once_with("Queued draft")
        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["approval_mode"] == "auto"
        assert "auto_approve_at" not in result["drafts"][0]

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_spacing_defers_second_due_draft(self, mock_safety, mock_post, capsys):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [
            self._due_auto_draft("draft_1", "Queued draft 1"),
            self._due_auto_draft("draft_2", "Queued draft 2"),
        ]

        result = process_due_drafts(state)

        assert mock_post.call_count == 1
        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][1]["status"] == "pending"
        assert result["drafts"][1]["auto_approve_at"] == "2000-01-01T00:00:00Z"
        assert "[posting] spacing guard: deferring 1 due drafts" in capsys.readouterr().out

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_spacing_allows_after_window(self, mock_safety, mock_post):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [
            {
                "id": "posted_old",
                "text": "Already posted",
                "status": "posted",
                "posted_at": "2000-01-01T00:00:00Z",
            },
            self._due_auto_draft("draft_1", "Queued draft 1"),
        ]

        result = process_due_drafts(state)

        mock_post.assert_called_once_with(state["drafts"][1], state)
        assert result["drafts"][1]["status"] == "posted"

    @patch.dict("os.environ", {"THEHEAT_MIN_TWEET_SPACING_MIN": "60"})
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_spacing_env_override(self, mock_safety, mock_post):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        recent_posted_at = (
            datetime.now(timezone.utc) - timedelta(minutes=30)
        ).isoformat().replace("+00:00", "Z")
        state["drafts"] = [
            {
                "id": "posted_recently",
                "text": "Already posted",
                "status": "posted",
                "posted_at": recent_posted_at,
            },
            self._due_auto_draft("draft_1", "Queued draft 1"),
        ]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][1]["status"] == "pending"

    @patch("src.main.post_approved")
    def test_skips_future_auto_approval_windows(self, mock_post):
        mock_post.return_value = "posted"
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2999-01-01T00:00:00Z",
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"

    @patch("src.main.post_approved")
    def test_blocks_due_drafts_when_policy_forbids_auto(self, mock_post):
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {"can_auto_approve": False},
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["post_error"] == "Auto-approval blocked by policy"

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_safety_rejection_blocks_auto_post(self, mock_safety, mock_post):
        mock_safety.return_value = (False, "Banned pattern: '#climate'")
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Bad draft #climate",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "armed_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["approval_mode"] == "manual"
        assert "safety rejected" in result["drafts"][0]["post_error"]
        assert "auto_approve_at" not in result["drafts"][0]

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_suggested_auto_posts_when_human_queued_it(self, mock_safety, mock_post):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Suggested draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_mode": "auto",
            "approval_policy": {
                "mode": "suggested_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_post.assert_called_once_with(state["drafts"][0], state)
        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["approval_mode"] == "auto"

    @patch("src.main.post_approved")
    def test_suggested_auto_still_blocks_unqueued_state(self, mock_post):
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Suggested draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "suggested_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["post_error"] == "Auto-approval blocked by policy"

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_naive_auto_approval_timestamp_is_treated_as_utc(self, mock_safety, mock_post):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00",
            "approval_policy": {
                "mode": "armed_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_post.assert_called_once_with(state["drafts"][0], state)
        assert result["drafts"][0]["status"] == "posted"


class TestRunAlertsIceMass:
    def test_monday_with_record_drafts(self, monkeypatch):
        """On a Monday, a fresh monthly record for Greenland drafts a tweet
        and updates state (ice_mass_max_loss + ice_mass_last_seen + count)."""
        from src import main
        import datetime as _dt

        class FakeDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 4, 20)  # a Monday

        monkeypatch.setattr(main, "date", FakeDate)

        # Monkeypatch ice_mass module: happy readings, fire a record
        from src.data import ice_mass as ice_mass_mod
        readings = [
            ice_mass_mod.IceMassReading("greenland", "2026-02", -5000.0, 100, "ice_mass_greenland_2026-02"),
            ice_mass_mod.IceMassReading("greenland", "2026-03", -5500.0, 100, "ice_mass_greenland_2026-03"),
        ]
        monkeypatch.setattr(ice_mass_mod, "fetch_grace_mass",
                            lambda region: readings if region == "greenland" else [])
        # Short-circuit all other fetchers
        for mod_name in (
            "firms", "co2", "nws_alerts", "gdacs", "copernicus_ems", "sea_ice", "drought", "enso",
            "ocean", "water_levels", "river_gauges",
        ):
            mod = getattr(main, mod_name, None)
            if mod is None:
                continue
            for fn in dir(mod):
                if fn.startswith("fetch_"):
                    monkeypatch.setattr(mod, fn, lambda *a, **k: [])
        # Stub open_meteo to avoid HTTP calls for all ~600 cities
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda *a, **k: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities", lambda *a, **k: ([], []))

        # Stub the two-bot pipeline — ice_mass was ported on 2026-05-04.
        # Returns a draft dict so save_draft is reached and state side-
        # effects run.
        def fake_try_two_bot(bundle, bot_state, score, *, legacy_type, event_id, review_context, **kwargs):
            from src.main import save_draft
            return save_draft(
                "Greenland lost 500 Gt. Largest monthly loss in GRACE record.",
                bot_state, legacy_type, event_id,
                score=score, review_context=review_context,
            )
        monkeypatch.setattr(main, "_try_two_bot_draft", fake_try_two_bot)

        bot_state = {
            "last_hot10": {"date": None, "cities": []},
            "streaks": {},
            "posted_events": [],
            "daily_tweet_count": {},
            "co2_annual_count": {},
            "drafts": [],
            "run_history": [],
            "errors": [],
            "city_all_time_max": {},
            "city_all_time_min": {},
            "city_monthly_max": {},
            "city_monthly_min": {},
            "record_streaks": {},
            "ice_mass_max_loss": {},
            "ice_mass_last_milestone": {},
            "ice_mass_last_seen": {},
            "ice_annual_count": {},
        }
        main.run_alerts(bot_state)

        assert bot_state["ice_mass_last_seen"].get("greenland") == "2026-03"
        assert bot_state["ice_mass_max_loss"].get("greenland", {}).get("gt") == -500.0
        assert bot_state["ice_annual_count"].get("2026", 0) >= 1
        # The event must be recorded
        assert any("ice_mass_record_greenland_monthly_2026-03" == e
                   for e in bot_state["posted_events"])

    def test_non_monday_skips(self, monkeypatch):
        from src import main
        import datetime as _dt

        class FakeDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 4, 21)  # a Tuesday

        monkeypatch.setattr(main, "date", FakeDate)

        from src.data import ice_mass as ice_mass_mod
        called = {"n": 0}

        def spy(region):
            called["n"] += 1
            return []

        monkeypatch.setattr(ice_mass_mod, "fetch_grace_mass", spy)
        for mod_name in (
            "firms", "co2", "nws_alerts", "gdacs", "copernicus_ems", "sea_ice", "drought", "enso",
            "ocean", "water_levels", "river_gauges",
        ):
            mod = getattr(main, mod_name, None)
            if mod is None:
                continue
            for fn in dir(mod):
                if fn.startswith("fetch_"):
                    monkeypatch.setattr(mod, fn, lambda *a, **k: [])
        # Stub open_meteo to avoid HTTP calls for all ~600 cities
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda *a, **k: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities", lambda *a, **k: ([], []))

        bot_state = {
            "last_hot10": {"date": None, "cities": []}, "streaks": {},
            "posted_events": [], "daily_tweet_count": {}, "co2_annual_count": {},
            "drafts": [], "run_history": [], "errors": [],
            "city_all_time_max": {}, "city_all_time_min": {},
            "city_monthly_max": {}, "city_monthly_min": {},
            "record_streaks": {}, "ice_mass_max_loss": {},
            "ice_mass_last_milestone": {}, "ice_mass_last_seen": {},
            "ice_annual_count": {},
        }
        main.run_alerts(bot_state)
        assert called["n"] == 0


class TestFireFootprintIntegration:
    @patch("src.main._try_two_bot_draft")
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_tier_crossing_creates_draft_and_updates_state(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft, mock_two_bot,
        mock_alerts_pipeline_sources,
    ):
        """Fire footprint ported to two-bot writer on 2026-05-04. The
        FireComplex flows through `build_fire_footprint_bundle` →
        `_try_two_bot_draft`, not the voice generator."""
        from src.data.fire_footprint import FireComplex

        complex = FireComplex(
            complex_id="GWIS_AAA",
            name="Dixie Complex",
            country="US",
            region="California",
            hectares=213_000,
            start_date=None,
            tier=3,
            event_id="fire_footprint_GWIS_AAA_tier3",
        )
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.return_value = [complex]
        mock_ff.detect_tier_crossings.return_value = [complex]
        mock_ff.TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
        mock_state.is_duplicate.return_value = False
        mock_two_bot.return_value = True

        # Wire update_fire_complex_tier side_effect to actually write to state_dict
        def _real_update_tier(sd, complex_id, tier):
            sd.setdefault("fire_complex_tiers", {})[complex_id] = tier

        mock_state.update_fire_complex_tier.side_effect = _real_update_tier

        state_dict = _fresh_state()
        run_alerts(state_dict)

        # Voice gen no longer reached.
        mock_gen.generate_fire_footprint_tweet.assert_not_called()
        # Two-bot is the live path. Inspect the bundle for shape + content.
        mock_two_bot.assert_called_once()
        bundle_arg = mock_two_bot.call_args.args[0]
        assert bundle_arg.signal_kind == "fire_footprint"
        assert bundle_arg.headline_metric["value"] == 213_000

        mock_state.update_fire_complex_tier.assert_called_once_with(state_dict, "GWIS_AAA", 3)
        # State updated with tier
        assert state_dict.get("fire_complex_tiers", {}).get("GWIS_AAA") == 3

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_same_day_second_run_gated_out(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.return_value = []

        state_dict = _fresh_state()
        state_dict["fire_footprint_last_run"] = date.today().isoformat()

        run_alerts(state_dict)

        mock_ff.fetch_active_fire_perimeters.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_fetch_error_is_logged_not_fatal(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft,
        mock_alerts_pipeline_sources,
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.side_effect = RuntimeError("boom")

        state_dict = _fresh_state()

        # Must not raise
        run_alerts(state_dict)
        mock_state.log_error.assert_any_call(state_dict, "fire_footprint", "boom")


class TestPerCycleCapCleanup:
    """Regression: when the per-cycle cap prunes weaker drafts, the
    pruned drafts' event_ids used to remain in posted_events, so later
    cycles skipped those events as "already drafted" even though no
    tweet ever shipped. The per-source drafted telemetry was also left
    overstated."""

    def _seed_drafts_after_mark(self, n: int):
        """Return (bot_state, drafts_before) with n pre-existing drafts
        representing 'this cycle produced n drafts' — each with a
        matching posted_events entry just like run_alerts' per-section
        record_event() does."""
        from src.main import MAX_DRAFTS_PER_CYCLE  # noqa: F401 (import side effect)
        state_dict = _fresh_state()
        drafts_before = 0
        for i in range(n):
            state_dict["drafts"].append({
                "id": f"d{i}",
                "event_id": f"evt_{i}",
                "type": "record",
                "text": f"tweet {i}",
                "status": "pending",
                "score": {"total": 80 - i},  # d0 is strongest, last is weakest
            })
            state_dict["posted_events"].append(f"evt_{i}")
        return state_dict, drafts_before

    def test_pruned_event_ids_removed_from_posted_events(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict, drafts_before = self._seed_drafts_after_mark(MAX_DRAFTS_PER_CYCLE + 2)
        assert len(state_dict["posted_events"]) == MAX_DRAFTS_PER_CYCLE + 2

        drafted = _prune_weakest_cycle_drafts(state_dict, drafts_before, None, MAX_DRAFTS_PER_CYCLE + 2)

        assert drafted == MAX_DRAFTS_PER_CYCLE
        kept_event_ids = {d["event_id"] for d in state_dict["drafts"]}
        # Weakest two should have been dropped — those are the highest-
        # numbered event_ids (evt_3, evt_4 if cap is 3).
        assert len(kept_event_ids) == MAX_DRAFTS_PER_CYCLE
        # Critical: pruned events MUST NOT remain in posted_events.
        for e in state_dict["posted_events"]:
            assert e in kept_event_ids, (
                f"Pruned event {e} lingered in posted_events — will block future drafting"
            )

    def test_no_prune_when_under_cap(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict, drafts_before = self._seed_drafts_after_mark(MAX_DRAFTS_PER_CYCLE - 1)
        before_posted = list(state_dict["posted_events"])
        drafted = _prune_weakest_cycle_drafts(state_dict, drafts_before, None, MAX_DRAFTS_PER_CYCLE - 1)
        assert drafted == MAX_DRAFTS_PER_CYCLE - 1
        assert state_dict["posted_events"] == before_posted

    def test_rolls_back_source_drafted_telemetry(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict, drafts_before = self._seed_drafts_after_mark(MAX_DRAFTS_PER_CYCLE + 2)
        # Simulate a run record where the two pruned drafts came from
        # the open_meteo source.
        current_run = {
            "sources": [
                {"source": "open_meteo_extreme_signals", "drafted": MAX_DRAFTS_PER_CYCLE + 2},
            ],
        }
        _prune_weakest_cycle_drafts(state_dict, drafts_before, current_run, MAX_DRAFTS_PER_CYCLE + 2)

        # Two drafts were pruned; drafted count should drop by 2.
        src = current_run["sources"][0]
        assert src["drafted"] == MAX_DRAFTS_PER_CYCLE, (
            f"Expected drafted to roll back to {MAX_DRAFTS_PER_CYCLE}, got {src['drafted']}"
        )

    def test_ice_mass_subsource_telemetry_rollback(self):
        """ice_mass logs as ``ice_mass_greenland`` / ``ice_mass_antarctica``
        rather than plain ``ice_mass``. Prune should match the prefix."""
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict = _fresh_state()
        for i in range(MAX_DRAFTS_PER_CYCLE + 1):
            state_dict["drafts"].append({
                "id": f"d{i}",
                "event_id": f"evt_{i}",
                "type": "ice_mass_record" if i == MAX_DRAFTS_PER_CYCLE else "record",
                "status": "pending",
                "score": {"total": 80 if i < MAX_DRAFTS_PER_CYCLE else 75},
            })
            state_dict["posted_events"].append(f"evt_{i}")
        current_run = {
            "sources": [
                {"source": "ice_mass_greenland", "drafted": 1},
                {"source": "open_meteo_extreme_signals", "drafted": MAX_DRAFTS_PER_CYCLE},
            ],
        }
        _prune_weakest_cycle_drafts(state_dict, 0, current_run, MAX_DRAFTS_PER_CYCLE + 1)

        # The ice_mass_record draft (weakest) was pruned → greenland telemetry rolls back.
        greenland = next(s for s in current_run["sources"] if s["source"] == "ice_mass_greenland")
        assert greenland["drafted"] == 0

    def test_new_source_types_roll_back_source_drafted_telemetry(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict = _fresh_state()
        draft_types = ["record", "record_low", "monthly_high", "precipitation_extreme"]
        for i, draft_type in enumerate(draft_types):
            state_dict["drafts"].append({
                "id": f"d{i}",
                "event_id": f"evt_{i}",
                "type": draft_type,
                "status": "pending",
                "score": {"total": 90 - i},
                "review_context": {"source_key": "gpm_imerg"} if draft_type == "precipitation_extreme" else {},
            })
            state_dict["posted_events"].append(f"evt_{i}")
        current_run = {
            "sources": [
                {"source": "open_meteo_extreme_signals", "drafted": MAX_DRAFTS_PER_CYCLE},
                {"source": "gpm_imerg", "drafted": 1},
            ],
        }

        _prune_weakest_cycle_drafts(state_dict, 0, current_run, MAX_DRAFTS_PER_CYCLE + 1)

        gpm = next(s for s in current_run["sources"] if s["source"] == "gpm_imerg")
        assert gpm["drafted"] == 0

    def test_review_context_source_key_does_not_override_prune_mapping(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict = _fresh_state()
        draft_types = ["record", "record_low", "monthly_high", "record_streak"]
        for i, draft_type in enumerate(draft_types):
            state_dict["drafts"].append({
                "id": f"d{i}",
                "event_id": f"evt_{i}",
                "type": draft_type,
                "status": "pending",
                "score": {"total": 90 - i},
                "review_context": {"source_key": draft_type},
            })
            state_dict["posted_events"].append(f"evt_{i}")
        current_run = {
            "sources": [
                {"source": "open_meteo_extreme_signals", "drafted": MAX_DRAFTS_PER_CYCLE + 1},
            ],
        }

        _prune_weakest_cycle_drafts(state_dict, 0, current_run, MAX_DRAFTS_PER_CYCLE + 1)

        source_run = current_run["sources"][0]
        assert source_run["drafted"] == MAX_DRAFTS_PER_CYCLE


class TestSynthesisRecording:
    def test_fire_in_us_records_component(self, monkeypatch):
        from unittest.mock import MagicMock
        from copy import deepcopy
        from src.state import DEFAULT_STATE
        from src import main
        from src.data import firms

        bot_state = deepcopy(DEFAULT_STATE)

        fake_fire = MagicMock(
            event_id="fire_38.58_-121.49_2026-04-20",
            lat=38.58, lon=-121.49,
            nearest_city="Sacramento", country="United States",
            confidence=95, frp=1500.0,
        )
        monkeypatch.setattr(firms, "fetch_fires", lambda: [fake_fire])
        monkeypatch.setattr(main, "_save_generated_draft", lambda *a, **kw: True)
        # Short-circuit open-meteo + others.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities",
                            lambda cities: ([], []))

        main.run_alerts(bot_state)

        fires = bot_state["synthesis_components"]["fires"].get("California", [])
        assert any(f["event_id"] == fake_fire.event_id for f in fires)


class TestSynthesisStage:
    def test_synthesis_stage_creates_draft(self, monkeypatch):
        from copy import deepcopy
        from datetime import datetime, timedelta, UTC
        from src.state import (
            DEFAULT_STATE,
            record_synthesis_component,
            record_synthesis_drought_snapshot,
        )
        from src import main

        bot_state = deepcopy(DEFAULT_STATE)
        now = datetime.now(UTC)

        def iso(d):
            return (now - timedelta(days=d)).isoformat().replace("+00:00", "Z")

        record_synthesis_drought_snapshot(bot_state, [
            {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
        ])
        record_synthesis_component(bot_state, kind="fire", region="California",
            event_id="pre_fire", metadata={"frp": 1400.0, "region": "Sacramento"},
            timestamp=iso(2))
        record_synthesis_component(bot_state, kind="heat", region="California",
            event_id="pre_heat",
            metadata={"kind": "calendar", "city": "Sacramento", "value_c": 40.0},
            timestamp=iso(1))

        # Short-circuit every per-source fetch so only the synthesis stage runs.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities",
                            lambda cities: ([], []))
        monkeypatch.setattr(main.firms, "fetch_fires", lambda: [])
        # Synthesis was ported to two-bot writer on 2026-05-04. Stub
        # `_try_two_bot_draft` to capture the call without making real
        # LLM requests.
        captured = {}
        def fake_two_bot(bundle, bot_state_arg, score, *, legacy_type, event_id, review_context, **kwargs):
            captured["legacy_type"] = legacy_type
            captured["event_id"] = event_id
            captured["bundle_signal_kind"] = bundle.signal_kind
            captured["components"] = bundle.raw_signal_dump.get("components")
            return True
        monkeypatch.setattr(main, "_try_two_bot_draft", fake_two_bot)

        main.run_alerts(bot_state)

        assert captured.get("legacy_type") == "synthesis_fire_drought_heat"
        assert captured.get("bundle_signal_kind") == "synthesis_fire_drought_heat"
        assert captured["components"] == [
            {"kind": "drought", "d4_pct": 10.0},
            {"kind": "fire", "peak_frp_mw": 1400.0, "peak_region": "Sacramento"},
            {"kind": "heat", "peak_city": "Sacramento", "peak_kind": "calendar", "peak_value_c": 40.0},
        ]
        assert "california" in captured["event_id"]
        # Cooldown must have been recorded so a second cycle is suppressed.
        cooldown = bot_state["synthesis_cooldown"].get("fire_drought_heat") or {}
        assert "California" in cooldown

    def test_synthesis_stage_creates_marine_compound_draft(self, monkeypatch):
        from copy import deepcopy
        from datetime import datetime, timedelta, UTC
        from src.state import DEFAULT_STATE, record_synthesis_component
        from src.orchestrator.sources.synthesis import run_synthesis

        bot_state = deepcopy(DEFAULT_STATE)
        now = datetime.now(UTC)

        def iso(days_ago):
            return (now - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")

        record_synthesis_component(
            bot_state,
            kind="coral",
            region="great_nicobar",
            event_id="coral_dhw_great_nicobar_tier8",
            metadata={
                "region_id": "great_nicobar",
                "region_full_name": "Great Nicobar",
                "dhw_value": 9.1,
                "dhw_tier": 8,
                "bleaching_level": "mass bleaching expected",
                "date": "2026-06-11",
            },
            timestamp=iso(1),
        )
        record_synthesis_component(
            bot_state,
            kind="sst_anomaly",
            region="bay_of_bengal",
            event_id="sst_anom_component_bay_of_bengal_2026-06-11",
            metadata={
                "region_slug": "bay_of_bengal",
                "region_display_name": "Bay of Bengal",
                "anomaly_c": 2.3,
                "tier": 0,
                "cells_used": 80,
                "date": "2026-06-11",
            },
            timestamp=iso(1),
        )

        captured = {}

        def fake_enqueue(bot_state_arg, *, bundle, score, source, legacy_type, event_id, review_context, **kwargs):
            captured["legacy_type"] = legacy_type
            captured["event_id"] = event_id
            captured["source"] = source
            captured["bundle_signal_kind"] = bundle.signal_kind
            captured["components"] = bundle.raw_signal_dump.get("components")
            captured["review_context"] = review_context
            kwargs["on_draft_success"]()
            return True

        monkeypatch.setattr(
            "src.orchestrator.sources.synthesis._enqueue_story_candidate",
            fake_enqueue,
        )

        run_synthesis(bot_state, {"sources": []})

        assert captured["legacy_type"] == "synthesis_marine_compound"
        assert captured["source"] == "synthesis_fire_drought_heat"
        assert captured["bundle_signal_kind"] == "synthesis_marine_compound"
        assert captured["components"][0]["kind"] == "coral"
        assert captured["components"][1]["kind"] == "sst_anomaly"
        cooldown = bot_state["synthesis_cooldown"].get("marine_compound") or {}
        assert "great_nicobar" in cooldown


# ---------------------------------------------------------------------------
# Triage integration tests (spec § 8, engineering-review T1/T2 tests)
# ---------------------------------------------------------------------------

def _make_triage_candidate(
    *,
    signal_kind: str = "coral_bleaching",
    total: int = 80,
    source: str = "coral_dhw",
    event_id: str = "evt_001",
    created_at: str = "2026-05-17T12:00:00Z",
):
    """Build a minimal TriageCandidateBundle for integration tests."""
    from src.two_bot.types import TriageCandidateBundle
    from src.two_bot.types import StoryBundle
    from src.editorial.scoring._shared import EditorialScore

    bundle = StoryBundle(
        signal_kind=signal_kind,
        where="Test Location",
        when="2026-05-17",
        event_id=event_id,
        headline_metric={"label": "Test", "value": 1},
        current_facts=[],
    )
    score = EditorialScore(
        category=signal_kind,
        severity=total,
        novelty=total,
        timeliness=total,
        confidence=total,
        shareability=total,
        sensitivity=0,
        total=total,
        threshold=60,
        reasons=[],
    )
    return TriageCandidateBundle(
        bundle=bundle,
        score=score,
        event_id=event_id,
        source=source,
        review_context={},
        city="",
        tweet_date="2026-05-17",
        cooldown_exempt=False,
        legacy_type=signal_kind,
        created_at=created_at,
    )


class TestTriageIntegration:
    """Integration tests for the _drain_and_write_triage_queue path in run_alerts."""

    def test_run_alerts_drains_triage_queue_after_sources(self, monkeypatch):
        """After all sources run, _drain_and_write_triage_queue processes the queue."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
        from src.orchestrator import common

        bot_state = _fresh_state()
        c = _make_triage_candidate()
        bot_state["_triage_queue"] = [c]

        written = []

        def fake_try_two_bot_draft(bundle, state, score, **kwargs):
            written.append(kwargs.get("event_id"))
            return True

        monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", fake_try_two_bot_draft)
        monkeypatch.setattr(
            "src.orchestrator.triage.select_survivors",
            lambda state, queue, **kw: queue,  # pass-through
        )

        current_run = {"sources": []}
        drafted = common._drain_and_write_triage_queue(bot_state, current_run)

        assert written == [c.event_id]
        assert drafted == 1
        # Queue should be gone after drain
        assert "_triage_queue" not in bot_state

    def test_run_alerts_only_calls_writer_for_survivors(self, monkeypatch):
        """When triage is ON, only survivors reach _try_two_bot_draft."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
        from src.orchestrator import common

        bot_state = _fresh_state()
        survivor = _make_triage_candidate(event_id="survivor", total=90)
        spilled = _make_triage_candidate(event_id="spilled", total=70)
        bot_state["_triage_queue"] = [survivor, spilled]

        written = []

        def fake_try_two_bot_draft(bundle, state, score, **kwargs):
            written.append(kwargs.get("event_id"))
            return True

        monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", fake_try_two_bot_draft)
        monkeypatch.setattr(
            "src.orchestrator.triage.select_survivors",
            lambda state, queue, **kw: [survivor],  # triage selects only the survivor
        )

        current_run = {"sources": []}
        drafted = common._drain_and_write_triage_queue(bot_state, current_run)

        assert written == ["survivor"]
        assert drafted == 1

    def test_drain_records_triage_and_writer_attempt_telemetry(self, monkeypatch):
        """Drain credits source telemetry after triage chooses survivors."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
        from src.orchestrator import common

        bot_state = _fresh_state()
        survivor = _make_triage_candidate(event_id="survivor", source="river_gauges", total=90)
        spilled = _make_triage_candidate(event_id="spilled", source="river_gauges", total=70)
        bot_state["_triage_queue"] = [survivor, spilled]

        monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", lambda *a, **k: True)
        monkeypatch.setattr(
            "src.orchestrator.triage.select_survivors",
            lambda state, queue, **kw: [survivor],
        )

        current_run = {
            "sources": [{
                "source": "river_gauges",
                "status": "success",
                "observed": 2,
                "promoted": 2,
                "drafted": 0,
            }]
        }
        drafted = common._drain_and_write_triage_queue(bot_state, current_run)

        assert drafted == 1
        row = current_run["sources"][0]
        assert row["triaged_in"] == 2
        assert row["triaged_out"] == 1
        assert row["writer_attempted"] == 1
        assert row["drafted"] == 1

    def test_run_alerts_with_triage_disabled_writes_all_candidates(self, monkeypatch):
        """When THEHEAT_TRIAGE_ENABLED=0, all candidates in queue are written."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
        from src.orchestrator import common

        bot_state = _fresh_state()
        c1 = _make_triage_candidate(event_id="c1", total=90)
        c2 = _make_triage_candidate(event_id="c2", total=70)
        c3 = _make_triage_candidate(event_id="c3", total=60)
        bot_state["_triage_queue"] = [c1, c2, c3]

        written = []

        def fake_try_two_bot_draft(bundle, state, score, **kwargs):
            written.append(kwargs.get("event_id"))
            return True

        monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", fake_try_two_bot_draft)

        current_run = {"sources": []}
        drafted = common._drain_and_write_triage_queue(bot_state, current_run)

        # All 3 should be written regardless of score ordering
        assert sorted(written) == ["c1", "c2", "c3"]
        assert drafted == 3

    def test_run_alerts_reports_drafts_written_by_triage_drain(self, monkeypatch, capsys):
        """The top-level saved count must include drafts written in the drain step."""
        import importlib

        alerts_mod = importlib.import_module("src.orchestrator.run_alerts")

        monkeypatch.setattr(alerts_mod.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(alerts_mod, "cities_to_state_map", lambda cities: {})
        for name in (
            "run_extreme_signals",
            "run_firms",
            "run_fire_footprint",
            "run_co2",
            "run_methane",
            "run_nws_alerts",
            "run_gdacs",
            "run_copernicus_ems",
            "_process_cyclone_source",
            "run_sea_ice",
            "run_drought",
            "run_enso",
            "run_climate_indices",
            "run_ocean",
            "run_ocean_sst",
            "run_ocean_sst_anomaly",
            "run_coral_dhw",
            "run_water_levels",
            "run_river_gauges",
            "run_ice_mass",
            "run_gpm_imerg",
            "run_nsidc_snow",
            "run_ozone_hole",
            "run_synthesis",
        ):
            monkeypatch.setattr(alerts_mod, name, lambda *args, **kwargs: 0)
        monkeypatch.setattr(alerts_mod, "_drain_and_write_triage_queue", lambda *args, **kwargs: 2)
        monkeypatch.setattr(
            alerts_mod,
            "_prune_weakest_cycle_drafts",
            lambda bot_state, drafts_before, current_run, drafted, **kwargs: drafted,
        )

        alerts_mod.run_alerts(_fresh_state(), current_run={"sources": []})

        assert "[alerts] Done. Saved 2 drafts." in capsys.readouterr().out

    def test_partial_migration_respects_global_cap(self, monkeypatch, mock_alerts_pipeline_sources):
        """Mixed cycle: some sources legacy (direct _try_two_bot_draft), some via triage queue.
        Total drafts must stay ≤ MAX_DRAFTS_PER_CYCLE even in mixed state.

        This is the steady-state during source migration rollout.
        """
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
        import src.main as main_mod
        from src.orchestrator.finalize import MAX_DRAFTS_PER_CYCLE

        bot_state = _fresh_state()
        draft_call_count = [0]

        def fake_try_two_bot_draft(bundle, state, score, **kwargs):
            # Each call adds a draft directly (simulating legacy sources)
            draft_call_count[0] += 1
            draft_text = f"draft_{draft_call_count[0]}"
            from src.orchestrator.common import save_draft
            save_draft(draft_text, state, kwargs.get("legacy_type", "record"), kwargs.get("event_id", "e"))
            return True

        monkeypatch.setattr("src.main._try_two_bot_draft", fake_try_two_bot_draft)
        monkeypatch.setattr("src.main.open_meteo.load_cities", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.firms.fetch_fires", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.fetch_co2_data", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.detect_milestone", MagicMock(return_value=None))
        monkeypatch.setattr("src.main.gpm_imerg.fetch_daily_precip", MagicMock(return_value=[]))

        # Pre-seed a triage queue (as if one migrated source added candidates)
        triage_candidates = [
            _make_triage_candidate(event_id=f"triage_{i}", signal_kind=f"cat_{i}", total=90 - i * 5)
            for i in range(4)
        ]
        bot_state["_triage_queue"] = triage_candidates

        current_run = {"sources": []}
        main_mod.run_alerts(bot_state, current_run=current_run)

        # Total drafts in state must not exceed MAX_DRAFTS_PER_CYCLE
        all_drafts = bot_state.get("drafts", [])
        assert len(all_drafts) <= MAX_DRAFTS_PER_CYCLE, (
            f"Expected ≤ {MAX_DRAFTS_PER_CYCLE} drafts, got {len(all_drafts)}"
        )

    def test_run_alerts_pops_stale_queue_on_entry(self, monkeypatch, mock_alerts_pipeline_sources):
        """The bot_state.pop('_triage_queue') at the top of run_alerts drops stale queues."""
        import src.main as main_mod
        from src.two_bot.types import TriageCandidateBundle
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")  # disable triage so no writes happen
        monkeypatch.setattr("src.main.open_meteo.load_cities", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.firms.fetch_fires", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.fetch_co2_data", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main.co2.detect_milestone", MagicMock(return_value=None))
        monkeypatch.setattr("src.main.gpm_imerg.fetch_daily_precip", MagicMock(return_value=[]))
        monkeypatch.setattr("src.main._try_two_bot_draft", MagicMock(return_value=False))

        bot_state = _fresh_state()
        # Simulate a stale queue from a crashed prior cron
        stale_candidate = _make_triage_candidate(event_id="stale_evt")
        bot_state["_triage_queue"] = [stale_candidate]

        # run_alerts should pop the stale queue at entry
        # After the run, the stale candidate should NOT have been processed
        # (the queue is cleared at entry, then drained fresh)
        current_run = {"sources": []}
        main_mod.run_alerts(bot_state, current_run=current_run)

        # _triage_queue should not be in bot_state after the run completes
        assert "_triage_queue" not in bot_state
