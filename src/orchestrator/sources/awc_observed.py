"""One explicitly enabled same-time airport comparison; existing writer budget."""
from __future__ import annotations

import os
import time

from src.data import awc_observed as source
from src.data import awc_gust
from src.editorial.observed_scope import enabled as observed_only
from src.editorial.scoring._shared import _build_score
from src.orchestrator.candidate_budget import CandidateBudgetConfigError, configured_max_candidates
from src.orchestrator.telemetry import _record_source_run
from src.orchestrator.triage_queue import _enqueue_story_candidate
from src.state_schema import BotState


def settings_hold():
    from src.two_bot.pipeline import _critic_enabled
    if not source.enabled() and not awc_gust.enabled():
        return "awc_source_disabled"
    if not observed_only() or not _critic_enabled():
        return "awc_observed_mode_and_critic_required"
    if os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1":
        return "awc_generation_paused"
    try:
        limit = configured_max_candidates()
    except CandidateBudgetConfigError:
        return "awc_operation_limit_invalid"
    if (limit != 1 or os.environ.get("THEHEAT_WRITER_SAMPLES", "1") != "1"
            or os.environ.get("THEHEAT_CRITIC_REVISE_ENABLED", "0") != "0"
            or os.environ.get("THEHEAT_REFILL_ENABLED", "0") != "0"):
        return "awc_one_candidate_sample_no_refill_required"
    return None


def run_awc_observed(bot_state: BotState, current_run: dict | None) -> None:
    if awc_gust.enabled():
        _run_profiles(bot_state, current_run)
        return
    started = time.perf_counter()
    try:
        if hold := settings_hold():
            _record_source_run(current_run, bot_state, "awc_observed", started, status="skipped", note=hold)
            return
        evidence = source.nominate()
        if evidence is None:
            _record_source_run(current_run, bot_state, "awc_observed", started, status="success",
                               observed=0, promoted=0, drafted=0, note="No qualified same-time airport pair")
            return
        bundle = source.build_bundle(evidence)
        from src import state
        if (state.is_duplicate(bot_state, bundle.event_id)
                or any(row.get("event_id") == bundle.event_id for row in bot_state.get("drafts", []))
                or bundle.event_id in bot_state.get("publish_ledger", {})):
            _record_source_run(current_run, bot_state, "awc_observed", started, status="success",
                               observed=1, promoted=0, drafted=0, note="Station pair/day already retained")
            return
        from src.editorial.format_spacing import awc_format_hold
        from src.orchestrator.common import _utc_now
        if spacing := awc_format_hold(bot_state, now=_utc_now()):
            _record_source_run(current_run, bot_state, "awc_observed", started, status="success",
                               observed=1, promoted=0, drafted=0,
                               note=("Airport comparison writing is spaced 24 hours after a confirmed X publication"
                                     if spacing == "awc_format_spacing" else
                                     "Publication history is unavailable for airport comparison spacing"),
                               details={"editorial_hold": spacing})
            return
        score = _build_score(source.KIND, severity=70, novelty=75, timeliness=95,
            confidence=85, shareability=85, sensitivity=0, threshold=72,
            reasons=["Same-time observations at two named airports; not a record or rarity finding"])
        promoted = _enqueue_story_candidate(bot_state, bundle=bundle, score=score,
            source="awc_observed", legacy_type=source.KIND, event_id=bundle.event_id,
            review_context={"source": evidence["source"], "source_key": "awc_observed",
                "headline": "Same-time reported airport temperature contrast", "facts": [
                    {"label": "Source", "value": evidence["source_url"]},
                    {"label": "Observed UTC", "value": bundle.when}]})
        _record_source_run(current_run, bot_state, "awc_observed", started, status="success",
                           observed=1, promoted=int(promoted), drafted=0)
    except Exception as exc:  # noqa: BLE001 — an unavailable source cannot buy a substitute
        _record_source_run(current_run, bot_state, "awc_observed", started, status="failed",
                           error=str(exc) if isinstance(exc, source.ObservedHeld) else
                                 "awc_observed_source_held:" + type(exc).__name__,
                           observed=0, promoted=0, drafted=0)


def _run_profiles(bot_state: BotState, current_run: dict | None) -> None:
    """Both profiles share two cache GETs; they never buy separate writer slots."""
    from src import state
    from src.editorial.format_spacing import awc_format_hold
    from src.orchestrator.common import _utc_now

    started = time.perf_counter()
    try:
        if hold := settings_hold():
            _record_source_run(current_run, bot_state, "awc_observed", started, status="skipped", note=hold)
            return
        capture = (source._read(source.STATIONS_URL), source._read(source.METARS_URL))
        findings = [(awc_gust, value) for value in awc_gust.nominate(now=_utc_now, capture=capture)]
        if source.enabled():
            pair = source.nominate(now=_utc_now, capture=capture)
            if pair is not None:
                findings.append((source, pair))
        promoted, holds = 0, []
        for profile, evidence in findings:
            bundle = profile.build_bundle(evidence, now=_utc_now)
            if (state.is_duplicate(bot_state, bundle.event_id)
                    or any(row.get("event_id") == bundle.event_id for row in bot_state.get("drafts", []))
                    or bundle.event_id in bot_state.get("publish_ledger", {})):
                holds.append("awc_source_already_retained")
                continue
            spacing = (awc_gust.retained_station_hold(bot_state, evidence, now=_utc_now)
                       if profile is awc_gust else awc_format_hold(bot_state, now=_utc_now()))
            if spacing:
                holds.append(spacing)
                continue
            gust = profile is awc_gust
            score = _build_score(profile.KIND, severity=75 if gust else 70, novelty=75, timeliness=95,
                confidence=85, shareability=85, sensitivity=0, threshold=72,
                reasons=["Reported airport gust; no sustained wind, impacts or record claim" if gust else
                         "Same-time observations at two named airports; not a record or rarity finding"])
            promoted += int(_enqueue_story_candidate(bot_state, bundle=bundle, score=score,
                source="awc_observed", legacy_type=profile.KIND, event_id=bundle.event_id,
                review_context={"source": evidence["source"], "source_key": "awc_observed",
                    "headline": "Reported airport wind gust" if gust else "Same-time airport temperature contrast",
                    "facts": [{"label": "Source", "value": evidence["source_url"]},
                              {"label": "Observed UTC", "value": bundle.when}]}))
        _record_source_run(current_run, bot_state, "awc_observed", started, status="success",
            observed=len(findings), promoted=promoted, drafted=0,
            note="Observed METAR profiles; no independent physical incident or forecast claim",
            details={"gust_nominated": sum(profile is awc_gust for profile, _ in findings),
                     "contrast_nominated": sum(profile is source for profile, _ in findings),
                     "editorial_holds": sorted(set(holds))})
    except Exception as exc:  # noqa: BLE001 — never buy a substitute for a held source
        _record_source_run(current_run, bot_state, "awc_observed", started, status="failed",
            error=str(exc) if isinstance(exc, source.ObservedHeld) else "awc_profiles_held:" + type(exc).__name__,
            observed=0, promoted=0, drafted=0)
