"""Invented candidates and paid-boundary spies for operation candidate-budget tests.

Candidates enter through the real source boundary (``_enqueue_story_candidate``,
including its evidence audit). Model stages are explicit OFFLINE stubs installed
at the stage functions; each still dispatches through the real
``trial_budget.provider_call`` boundary, so every counted call is a provider
attempt the production path would have paid for. Nothing here reaches a network,
model, Gist or X, and no invented verdict says anything about real copy quality.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from src.state import DEFAULT_STATE
from src.two_bot import pipeline, trial_budget
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests.fire_source_fixtures import fire_event

REGIONS = ("Mali", "Niger", "Chad", "Sudan", "Ghana", "Benin", "Togo", "Guinea")


def fresh_state() -> Any:  # A BotState-shaped invented dict.
    state = deepcopy(DEFAULT_STATE)
    state["drafts"], state["posted_events"] = [], []
    return state


def fires(count: int, *, frp: float = 361.0):
    """Distinct invented FIRMS detections (distinct coordinates, so distinct events)."""
    return [fire_event(lat=10.0 + index, lon=-4.0 - index, frp=frp - index, region=REGIONS[index % len(REGIONS)])
            for index in range(count)]


def enqueue_fires(state: Any, count: int, *, source: str = "firms") -> list[str]:
    """The real source boundary: score, audit and queue each invented detection."""
    from src.editorial.scoring import score_fire_event
    from src.orchestrator.common import _review_context
    from src.orchestrator.triage_queue import _enqueue_story_candidate
    from src.two_bot.intern.fire import build_fire_bundle
    ids = []
    for fire in fires(count):
        score = score_fire_event(fire.confidence, fire.frp, region=fire.nearest_city)
        assert score.passes, "invented fixture must pass the editorial gate"
        out: dict = {}
        assert _enqueue_story_candidate(
            state, bundle=build_fire_bundle(fire), score=score, source=source, legacy_type="fire",
            event_id=fire.event_id, admission_out=out,
            review_context=_review_context(source="Invented FIRMS", source_key="firms",
                                           headline=f"Invented detection near {fire.nearest_city}", facts=[]),
        ), out
        ids.append(fire.event_id)
    return ids


@dataclass
class Spies:
    """Paid-boundary spies: who reached each provider stage, in order."""

    writer_kill: set[str] = field(default_factory=set)  # event ids the writer kills
    critic_kill: set[str] = field(default_factory=set)  # event ids the critic rejects
    critic_reject_first: int = 0  # reject the first n critic calls, whoever they are
    calls: list[tuple[str, str]] = field(default_factory=list)

    def install(self, monkeypatch) -> "Spies":
        monkeypatch.setenv("ANTHROPIC_API_KEY", "invented-no-provider-access")
        monkeypatch.setenv("GEMINI_API_KEY", "invented-no-provider-access")
        monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
        for name in ("THEHEAT_WRITER_SAMPLES", "THEHEAT_CRITIC_REVISE_ENABLED", "THEHEAT_CRITIC_ENABLED"):
            monkeypatch.setenv(name, {"THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
                                      "THEHEAT_CRITIC_ENABLED": "1"}[name])
        monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
        monkeypatch.setattr(pipeline.writer, "write_tweet", self.writer)
        monkeypatch.setattr(pipeline, "run_safety_pipeline", self.safety)
        monkeypatch.setattr(pipeline.fact_check, "fact_check", self.fact_check)
        monkeypatch.setattr(pipeline.critic, "critic_review", self.critic)
        return self

    def _dispatch(self, stage: str, provider: str, event_id: str) -> None:
        def send(**_request):
            self.calls.append((stage, event_id))
            return object()
        trial_budget.provider_call(stage, provider, {"model": "invented-offline-" + stage}, send)

    def writer(self, bundle, memory, **_kwargs):
        self._dispatch("writer", "anthropic", bundle.event_id)
        if bundle.event_id in self.writer_kill:
            return WriterResult(None, "Explicit invented offline writer kill.", "", None, None, "Offline fixture.")
        text = {
            "official_warning": "Invented Warning Agency warns: dangerous winds are possible tonight on Example Island.",
            "hot10": "Invented City 0 tops today's Hot 10, running 10.0C above its normal high.",
        }.get(bundle.signal_kind, f"NASA satellites recorded a strong thermal detection near {bundle.where}.")
        return WriterResult(text, None, "number", None, None, "Explicit invented offline model response.")

    def safety(self, text):
        self._dispatch("safety", "google", "")
        return True, None

    def fact_check(self, tweet, claims, bundle, *_args, **_kwargs):
        self._dispatch("fact_check", "google", bundle.event_id)
        return FactCheckResult(True, [], "Explicit invented offline fact check.")

    def critic(self, text, bundle, *_args, **_kwargs):
        self._dispatch("critic", "google", bundle.event_id)
        rejected_first = sum(stage == "critic" for stage, _ in self.calls) <= self.critic_reject_first
        if bundle.event_id in self.critic_kill or rejected_first:
            return CriticResult(False, "Explicit invented offline critic rejection.", "Offline fixture.")
        return CriticResult(True, None, "Explicit invented offline critic pass.")

    def writer_events(self) -> list[str]:
        return [event for stage, event in self.calls if stage == "writer"]


def offline_world(monkeypatch):
    """Every real source runner offline (connections counted and refused), invented
    FIRMS detections at the adapter boundary and the offline stage spies installed."""
    import socket
    from types import SimpleNamespace

    from src.data import firms

    connects: list = []

    def refused(self, address, *args, **kwargs):
        connects.append(address)  # Every attempted source connection, counted and refused.
        raise OSError("network refused: invented operation test")
    monkeypatch.setattr(socket.socket, "connect", refused)
    # Offline runners retry their refused requests with real backoff sleeps. Only
    # the waiting is removed; the number of attempts (counted above) is unchanged.
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    for name in ("THEHEAT_REFILL_ENABLED", "THEHEAT_FUNNEL_TELEMETRY", "THEHEAT_MULTISIGNAL_CONTEXT",
                 "THEHEAT_NEWS_ENRICH_ENABLED", "THEHEAT_NEWSWORTHINESS_ENABLED", "THEHEAT_DRAFTS_TARGET_PER_CYCLE",
                 "THEHEAT_REFILL_MAX_ATTEMPTS", "THEHEAT_NHC_ADVISORY_ACQUISITION"):
        monkeypatch.delenv(name, raising=False)
    fetches: list = []

    def fetch_fires(*args, **kwargs):
        fetches.append("firms")
        return fires(3)
    monkeypatch.setattr(firms, "fetch_fires", fetch_fires)
    return SimpleNamespace(spies=Spies().install(monkeypatch), connects=connects, fetches=fetches)


OTHER_ALERT_RUNNERS = (
    "run_extreme_signals", "run_fire_footprint", "run_co2", "run_methane", "run_nws_alerts", "run_gdacs",
    "run_usgs_quakes", "run_copernicus_ems", "_process_cyclone_source", "run_sea_ice", "run_drought", "run_enso",
    "run_climate_indices", "run_ocean", "run_ocean_sst", "run_ocean_sst_anomaly", "run_air_quality", "run_coral_dhw",
    "run_water_levels", "run_river_gauges", "run_ice_mass", "run_gpm_imerg", "run_nsidc_snow", "run_ozone_hole",
    "run_reanalysis_anomaly", "run_newsworthiness", "run_synthesis",
)


def isolate_firms(monkeypatch) -> None:
    """Only the real FIRMS runner contributes; every other runner reports nothing.

    Used only where a claim is about the run status a generation hold produces on
    its own, so unavailable offline sources cannot make that status partial.
    """
    import importlib
    alerts = importlib.import_module("src.orchestrator.run_alerts")
    monkeypatch.setattr(alerts.open_meteo, "load_cities", lambda: [])
    monkeypatch.setattr(alerts, "cities_to_state_map", lambda cities: {})
    for name in OTHER_ALERT_RUNNERS:
        monkeypatch.setattr(alerts, name, lambda *args, **kwargs: None)
    # src.main re-syncs its own compatibility globals into the split modules on
    # every dispatch, so the same names are replaced there too.
    main = importlib.import_module("src.main")
    for name in OTHER_ALERT_RUNNERS:
        monkeypatch.setattr(main, name, lambda *args, **kwargs: None, raising=False)
