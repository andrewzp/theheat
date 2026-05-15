"""Source runner for NAO/AO/PDO climate-mode indices."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


_INDEX_FETCHERS = (
    ("NAO", "fetch_nao"),
    ("AO", "fetch_ao"),
    ("PDO", "fetch_pdo"),
)

_INDEX_CAPS = {"NAO": 6, "AO": 6, "PDO": 3}


def run_climate_indices(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    if date.today().day != 1:
        for index_name, _fetcher_name in _INDEX_FETCHERS:
            skipped_start = time.perf_counter()
            _record_source_run(
                current_run, bot_state, index_name.lower(), skipped_start,
                status="skipped", note="Runs on the 1st of the month",
            )
        skipped_start = time.perf_counter()
        _record_source_run(
            current_run, bot_state, "nao_ao_alignment", skipped_start,
            status="skipped", note="Runs on the 1st of the month",
        )
        return drafted

    print("[alerts] Checking climate-mode indices...")
    readings_by_index = {}
    for index_name, fetcher_name in _INDEX_FETCHERS:
        source_start = time.perf_counter()
        source_promoted = 0
        source_drafted = 0
        try:
            readings = _fetch_strict(getattr(climate_indices, fetcher_name))
            readings_by_index[index_name] = readings
            if readings:
                state.update_oscillation_last_phase(bot_state, index_name, readings[-1].phase)

            for event in (
                climate_indices.detect_phase_transition(readings),
                climate_indices.detect_extreme_excursion(readings),
            ):
                if event is None:
                    continue
                if state.is_duplicate(bot_state, event.event_id):
                    continue
                if _oscillation_annual_cap_reached(bot_state, index_name):
                    break

                if isinstance(event, climate_indices.OscillationTransition):
                    score = score_oscillation_transition(
                        event.index_name,
                        event.value,
                        event.previous_duration_months,
                    )
                    legacy_type = "oscillation_transition"
                    headline = f"{event.full_name} flipped {event.to_phase.lower()}"
                    facts = [
                        _fact("Index", event.full_name),
                        _fact("New phase", event.to_phase),
                        _fact("Index value", f"{event.value:+.2f}"),
                        _fact("Previous duration", f"{event.previous_duration_months} months"),
                    ]
                else:
                    score = score_oscillation_extreme(event.index_name, event.sigma_excursion)
                    legacy_type = "oscillation_extreme"
                    headline = f"{event.full_name} extreme excursion"
                    facts = [
                        _fact("Index", event.full_name),
                        _fact("Index value", f"{event.value:+.2f}"),
                        _fact("Sigma excursion", f"{event.sigma_excursion:.1f}"),
                        _fact("Comparison year", event.comparison_year),
                    ]

                if not _should_draft(score, event.event_id):
                    continue
                source_promoted += 1
                review_context = _review_context(
                    source="NOAA",
                    source_key=index_name.lower(),
                    headline=headline,
                    current_run=current_run,
                    facts=facts,
                )
                from src.two_bot.intern import build_oscillation_bundle
                bundle = build_oscillation_bundle(event)
                if _try_two_bot_draft(
                    bundle,
                    bot_state,
                    score,
                    legacy_type=legacy_type,
                    event_id=event.event_id,
                    review_context=review_context,
                ):
                    state.record_event(bot_state, event.event_id)
                    state.increment_oscillation_annual_count(bot_state, index_name)
                    drafted += 1
                    source_drafted += 1

            _record_source_run(
                current_run, bot_state, index_name.lower(), source_start,
                status="success", observed=len(readings),
                promoted=source_promoted, drafted=source_drafted,
            )
        except Exception as e:
            print(f"[alerts] {index_name} climate index error: {e}")
            state.log_error(bot_state, index_name.lower(), str(e))
            _record_source_run(
                current_run, bot_state, index_name.lower(), source_start,
                status="failed", error=str(e),
            )

    drafted += _run_nao_ao_alignment(bot_state, current_run, readings_by_index)
    return drafted


def _run_nao_ao_alignment(
    bot_state: BotState,
    current_run: dict | None,
    readings_by_index: dict,
) -> int:
    source_start = time.perf_counter()
    try:
        event = climate_indices.detect_nao_ao_alignment(
            readings_by_index.get("NAO", []),
            readings_by_index.get("AO", []),
        )
        if event is None:
            _record_source_run(
                current_run, bot_state, "nao_ao_alignment", source_start,
                status="success", observed=0, promoted=0, drafted=0,
            )
            return 0
        if state.is_duplicate(bot_state, event.event_id):
            _record_source_run(
                current_run, bot_state, "nao_ao_alignment", source_start,
                status="success", observed=1, promoted=0, drafted=0,
            )
            return 0
        if (
            _oscillation_annual_cap_reached(bot_state, "NAO")
            or _oscillation_annual_cap_reached(bot_state, "AO")
        ):
            _record_source_run(
                current_run, bot_state, "nao_ao_alignment", source_start,
                status="success", observed=1, promoted=0, drafted=0,
            )
            return 0

        score = score_oscillation_extreme(
            "NAO/AO blocking alignment",
            max(event.nao_sigma_excursion, event.ao_sigma_excursion),
        )
        if not _should_draft(score, event.event_id):
            _record_source_run(
                current_run, bot_state, "nao_ao_alignment", source_start,
                status="success", observed=1, promoted=0, drafted=0,
            )
            return 0
        review_context = _review_context(
            source="NOAA",
            source_key="nao_ao_alignment",
            headline="NAO and AO both extreme negative",
            current_run=current_run,
            facts=[
                _fact("NAO", f"{event.nao_value:+.2f}"),
                _fact("AO", f"{event.ao_value:+.2f}"),
                _fact("NAO sigma", f"{event.nao_sigma_excursion:.1f}"),
                _fact("AO sigma", f"{event.ao_sigma_excursion:.1f}"),
            ],
        )
        from src.two_bot.intern import build_oscillation_bundle
        bundle = build_oscillation_bundle(event)
        drafted = 0
        if _try_two_bot_draft(
            bundle,
            bot_state,
            score,
            legacy_type="oscillation_alignment",
            event_id=event.event_id,
            review_context=review_context,
        ):
            state.record_event(bot_state, event.event_id)
            state.increment_oscillation_annual_count(bot_state, "NAO")
            state.increment_oscillation_annual_count(bot_state, "AO")
            drafted = 1
        _record_source_run(
            current_run, bot_state, "nao_ao_alignment", source_start,
            status="success", observed=1, promoted=1, drafted=drafted,
        )
        return drafted
    except Exception as e:
        print(f"[alerts] NAO/AO alignment error: {e}")
        state.log_error(bot_state, "nao_ao_alignment", str(e))
        _record_source_run(
            current_run, bot_state, "nao_ao_alignment", source_start,
            status="failed", error=str(e),
        )
        return 0


def _oscillation_annual_cap_reached(bot_state: BotState, index_name: str) -> bool:
    year_key = str(date.today().year)
    key = f"{index_name.lower()}_annual_count"
    cap = _INDEX_CAPS[index_name]
    counts = cast(dict, bot_state.get(key, {}))
    count = int(counts.get(year_key, 0) or 0)
    if count >= cap:
        print(f"[{index_name.lower()}] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False
