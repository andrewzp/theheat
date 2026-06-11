"""Run-alerts orchestration regressions."""

from __future__ import annotations

from copy import deepcopy

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE
from src.two_bot.types import StoryBundle, TriageCandidateBundle


def _fresh_state() -> dict:
    return deepcopy(DEFAULT_STATE)


def _score(total: int = 80, category: str = "coral_bleaching") -> EditorialScore:
    return EditorialScore(
        category=category,
        severity=80,
        novelty=80,
        timeliness=80,
        confidence=80,
        shareability=80,
        sensitivity=0,
        total=total,
        threshold=60,
        reasons=[],
    )


def _bundle(
    signal_kind: str = "coral_bleaching",
    event_id: str = "evt_drain_credit",
) -> StoryBundle:
    return StoryBundle(
        signal_kind=signal_kind,
        where="Great Barrier Reef",
        when="2026-05-17",
        event_id=event_id,
        headline_metric={"label": "DHW", "value": 8},
        current_facts=[],
    )


def _candidate(
    *,
    source: str = "coral_dhw",
    event_id: str = "evt_drain_credit",
) -> TriageCandidateBundle:
    return TriageCandidateBundle(
        bundle=_bundle(event_id=event_id),
        score=_score(),
        event_id=event_id,
        source=source,
        review_context={},
        city="",
        tweet_date="2026-05-17",
        cooldown_exempt=False,
        legacy_type="coral_bleaching",
        created_at="2026-05-17T12:00:00Z",
    )


def test_run_alerts_drafted_count_comes_from_drain_only(monkeypatch, capsys):
    """Source runner return values must not inflate the final saved count."""
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
        "run_air_quality",
        "run_coral_dhw",
        "run_water_levels",
        "run_river_gauges",
        "run_ice_mass",
        "run_gpm_imerg",
        "run_nsidc_snow",
        "run_ozone_hole",
        "run_reanalysis_anomaly",
        "run_synthesis",
    ):
        monkeypatch.setattr(alerts_mod, name, lambda *args, **kwargs: 1)

    monkeypatch.setattr(
        alerts_mod,
        "_drain_and_write_triage_queue",
        lambda *args, **kwargs: 2,
    )
    monkeypatch.setattr(
        alerts_mod,
        "_prune_weakest_cycle_drafts",
        lambda bot_state, drafts_before, current_run, drafted, **kwargs: drafted,
    )

    alerts_mod.run_alerts(_fresh_state(), current_run={"sources": []})

    assert "[alerts] Done. Saved 2 drafts." in capsys.readouterr().out


def test_source_run_gets_drafted_credit_after_drain(monkeypatch):
    """A saved drain survivor credits the originating source run."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    bot_state["drafts"] = []
    bot_state["posted_events"] = []
    current_run = {
        "sources": [
            {
                "source": "coral_dhw",
                "status": "success",
                "observed": 1,
                "promoted": 1,
                "drafted": 0,
            }
        ]
    }
    bot_state["_triage_queue"] = [_candidate(source="coral_dhw")]

    def fake_generate_draft(bundle, state, result_out=None):
        return {
            "text": "Great Barrier Reef bleaching stress reached a notable tier today.",
            "two_bot_metadata": {"writer": "stubbed"},
        }

    def fake_try_two_bot_draft(bundle, state, score, **kwargs):
        from src.two_bot.pipeline import generate_draft

        draft = generate_draft(bundle, state, result_out={})
        if draft is None:
            return False
        return common.save_draft(
            draft["text"],
            state,
            kwargs["legacy_type"],
            kwargs["event_id"],
            score=score,
            review_context=kwargs["review_context"],
        )

    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setattr("src.two_bot.pipeline.generate_draft", fake_generate_draft)
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try_two_bot_draft)

    drafted = common._drain_and_write_triage_queue(bot_state, current_run)

    assert drafted == 1
    assert current_run["sources"][0]["drafted"] == 1
