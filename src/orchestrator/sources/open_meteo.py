"""Source runner for Open-Meteo and GHCN extreme signals."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_extreme_signals(bot_state: BotState, current_run: dict | None, cities: list[dict], us_city_state_map: dict[str, str], city_elevations: dict[tuple[str, str], int]) -> int:
    drafted = 0
    # 1. Extreme climate signals — dispatched by THEHEAT_SIGNALS_PROVIDER.
    # "open_meteo" (default): 638 curated cities via Open-Meteo archive API.
    # "ghcn": ~9,449 active NOAA GHCN-Daily stations via superghcnd_diff + SQLite threshold cache.
    # Hot 10 leaderboard (run_leaderboard) always uses Open-Meteo regardless of this flag.
    _signals_provider = os.environ.get("THEHEAT_SIGNALS_PROVIDER", "open_meteo").lower()
    print(f"[alerts] Checking extreme climate signals (provider={_signals_provider})...")
    signals_start = time.perf_counter()
    signal_counts = {
        "all_time": 0,
        "monthly": 0,
        "absolute_extreme": 0,
        "anomaly": 0,
        "calendar": 0,
        "streak": 0,
    }
    # Per-station data for the simultaneous_records signal. Richer than
    # just (city, country) so the roll-call format can surface temps,
    # margins, and elevations. See src/editorial/simultaneous_format.py
    # for the routing decision (flat summary vs. multi-station roll-call).
    simultaneous_record_stations: list[dict] = []
    ghcn_pipeline_metrics: dict = {}
    open_meteo_pipeline_metrics: dict = {}
    # Per-bundle decision log for the dashboard drill-down. Each row records
    # which bundle was processed, what its strongest signal was (if any), and
    # whether it ended up as a draft, rejection, duplicate, or no-signal.
    ghcn_event_log: list[dict] = []
    try:
        if _signals_provider not in {"open_meteo", "ghcn"}:
            raise ValueError(
                "THEHEAT_SIGNALS_PROVIDER must be 'open_meteo' or 'ghcn', "
                f"got {_signals_provider!r}"
            )
        if _signals_provider == "ghcn":
            bundles, country_records = ghcn.check_extreme_signals_for_stations(
                metrics_out=ghcn_pipeline_metrics,
            )
        else:
            bundles, country_records = _check_city_extreme_signals(
                cities,
                open_meteo_pipeline_metrics,
            )
        source_promoted = 0
        source_drafted = 0
        for bundle in bundles:
            # Process signals in descending order of priority:
            # all-time > monthly > absolute-extreme > anomaly > calendar-date.
            # The strongest signal wins — we don't draft multiple tweets for the same city.

            strongest_signal: AllTimeRecord | MonthlyRecord | AbsoluteExtremeEvent | AnomalyEvent | RecordEvent | None = None
            strongest_score: EditorialScore | None = None
            strongest_event_id: str | None = None
            strongest_headline = ""
            strongest_facts = []
            strongest_type = ""
            strongest_city = ""
            signal_year = (bundle.signal_date or date.today()).year
            # Default these so the bottom-of-loop event-log capture
            # works whether or not the if-cascade fires.
            candidate_queued = False

            if bundle.all_time_high:
                ev: AllTimeRecord = bundle.all_time_high
                if not state.is_duplicate(bot_state, ev.event_id):
                    score = score_all_time_record(
                        ev.new_temp_c, ev.old_record_c, ev.old_record_year,
                        ev.years_of_data, kind="high",
                    )
                    if _should_draft(score, ev.event_id):
                        strongest_signal = ev
                        strongest_score = score
                        strongest_event_id = ev.event_id
                        strongest_type = "all_time_high"
                        strongest_city = ev.city
                        strongest_headline = f"{ev.city} on pace for its hottest in {ev.years_of_data}yr archive"
                        strongest_facts = [
                            _fact("Forecast high", _temp_pair_c(ev.new_temp_c)),
                            _fact("Prior archive max", _temp_pair_c(ev.old_record_c)),
                            _fact("Prior max year", ev.old_record_year),
                            _fact("Archive span", f"{ev.years_of_data} years"),
                            _fact("Country", ev.country),
                        ]
                        signal_counts["all_time"] += 1

            if strongest_signal is None and bundle.all_time_low:
                ev = bundle.all_time_low
                if not state.is_duplicate(bot_state, ev.event_id):
                    score = score_all_time_record(
                        ev.new_temp_c, ev.old_record_c, ev.old_record_year,
                        ev.years_of_data, kind="low",
                    )
                    if _should_draft(score, ev.event_id):
                        strongest_signal = ev
                        strongest_score = score
                        strongest_event_id = ev.event_id
                        strongest_type = "all_time_low"
                        strongest_city = ev.city
                        strongest_headline = f"{ev.city} hit its coldest reading in {ev.years_of_data}yr archive"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev.new_temp_c)),
                            _fact("Prior archive min", _temp_pair_c(ev.old_record_c)),
                            _fact("Prior min year", ev.old_record_year),
                            _fact("Archive span", f"{ev.years_of_data} years"),
                            _fact("Country", ev.country),
                        ]
                        signal_counts["all_time"] += 1

            if strongest_signal is None and bundle.monthly_high:
                ev_mh: MonthlyRecord = bundle.monthly_high
                # Suppress "hottest April ever - old record set in 2026"
                # tweets. When the prior record was set in the same year as
                # this reading, the "hottest ever" framing reads as nonsense.
                if (
                    not state.is_duplicate(bot_state, ev_mh.event_id)
                    and ev_mh.old_record_year != signal_year
                ):
                    score = score_monthly_record(
                        ev_mh.new_temp_c, ev_mh.old_record_c, ev_mh.old_record_year,
                        ev_mh.month, ev_mh.years_of_data, kind="high",
                    )
                    if _should_draft(score, ev_mh.event_id):
                        month_name = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][ev_mh.month]
                        strongest_signal = ev_mh
                        strongest_score = score
                        strongest_event_id = ev_mh.event_id
                        strongest_type = "monthly_high"
                        strongest_city = ev_mh.city
                        strongest_headline = f"{ev_mh.city} on pace for hottest {month_name} on record"
                        strongest_facts = [
                            _fact("Forecast high", _temp_pair_c(ev_mh.new_temp_c)),
                            _fact(f"Prior {month_name} max", _temp_pair_c(ev_mh.old_record_c)),
                            _fact("Prior year", ev_mh.old_record_year),
                            _fact("Archive span", f"{ev_mh.years_of_data} years"),
                        ]
                        signal_counts["monthly"] += 1

            if strongest_signal is None and bundle.monthly_low:
                ev_ml: MonthlyRecord = bundle.monthly_low
                if (
                    not state.is_duplicate(bot_state, ev_ml.event_id)
                    and ev_ml.old_record_year != signal_year
                ):
                    score = score_monthly_record(
                        ev_ml.new_temp_c, ev_ml.old_record_c, ev_ml.old_record_year,
                        ev_ml.month, ev_ml.years_of_data, kind="low",
                    )
                    if _should_draft(score, ev_ml.event_id):
                        month_name = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][ev_ml.month]
                        strongest_signal = ev_ml
                        strongest_score = score
                        strongest_event_id = ev_ml.event_id
                        strongest_type = "monthly_low"
                        strongest_city = ev_ml.city
                        strongest_headline = f"{ev_ml.city} hit its coldest {month_name} reading on record"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev_ml.new_temp_c)),
                            _fact(f"Prior {month_name} min", _temp_pair_c(ev_ml.old_record_c)),
                            _fact("Prior year", ev_ml.old_record_year),
                            _fact("Archive span", f"{ev_ml.years_of_data} years"),
                        ]
                        signal_counts["monthly"] += 1

            if strongest_signal is None and bundle.absolute_extreme:
                ev_ae: AbsoluteExtremeEvent = bundle.absolute_extreme
                if not state.is_duplicate(bot_state, ev_ae.event_id):
                    score = score_absolute_extreme(
                        ev_ae.today_temp_c,
                        ev_ae.lat,
                        ev_ae.band_label,
                        ev_ae.threshold_c,
                        kind=ev_ae.kind,
                    )
                    if _should_draft(score, ev_ae.event_id):
                        strongest_signal = ev_ae
                        strongest_score = score
                        strongest_event_id = ev_ae.event_id
                        strongest_type = "absolute_extreme"
                        strongest_city = ev_ae.city
                        strongest_headline = (
                            f"{ev_ae.city}: {ev_ae.today_temp_c:.1f}C "
                            f"({ev_ae.band_label} absolute extreme)"
                        )
                        strongest_facts = [
                            _fact("City", ev_ae.city),
                            _fact("Country", ev_ae.country),
                            _fact("Temperature", _temp_pair_c(ev_ae.today_temp_c)),
                            _fact("Latitude band", ev_ae.band_label),
                            _fact("Band threshold", _temp_pair_c(ev_ae.threshold_c)),
                            _fact("Kind", ev_ae.kind),
                            _fact("Data source", ev_ae.data_source),
                        ]
                        signal_counts["absolute_extreme"] += 1

            if strongest_signal is None and bundle.anomaly_hot:
                ev_ah: AnomalyEvent = bundle.anomaly_hot
                if not state.is_duplicate(bot_state, ev_ah.event_id):
                    score = score_anomaly(
                        ev_ah.today_temp_c, ev_ah.historical_mean_c, ev_ah.anomaly_c,
                        kind="hot",
                    )
                    if _should_draft(score, ev_ah.event_id):
                        strongest_signal = ev_ah
                        strongest_score = score
                        strongest_event_id = ev_ah.event_id
                        strongest_type = "anomaly_hot"
                        strongest_city = ev_ah.city
                        strongest_headline = f"{ev_ah.city}: +{ev_ah.anomaly_c:.1f}C above normal"
                        strongest_facts = [
                            _fact("Today", _temp_pair_c(ev_ah.today_temp_c)),
                            _fact("Historical mean", _temp_pair_c(ev_ah.historical_mean_c)),
                            _fact("Anomaly", f"+{ev_ah.anomaly_c:.1f}C"),
                        ]
                        signal_counts["anomaly"] += 1

            if strongest_signal is None and bundle.anomaly_cold:
                ev_ac: AnomalyEvent = bundle.anomaly_cold
                if not state.is_duplicate(bot_state, ev_ac.event_id):
                    score = score_anomaly(
                        ev_ac.today_temp_c, ev_ac.historical_mean_c, ev_ac.anomaly_c,
                        kind="cold",
                    )
                    if _should_draft(score, ev_ac.event_id):
                        strongest_signal = ev_ac
                        strongest_score = score
                        strongest_event_id = ev_ac.event_id
                        strongest_type = "anomaly_cold"
                        strongest_city = ev_ac.city
                        strongest_headline = f"{ev_ac.city}: {ev_ac.anomaly_c:.1f}C below normal"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev_ac.today_temp_c)),
                            _fact("Historical mean low", _temp_pair_c(ev_ac.historical_mean_c)),
                            _fact("Anomaly", f"{ev_ac.anomaly_c:.1f}C"),
                        ]
                        signal_counts["anomaly"] += 1

            if strongest_signal is None and bundle.calendar_date_high:
                ev_cdh: RecordEvent = bundle.calendar_date_high
                if not state.is_duplicate(bot_state, ev_cdh.event_id):
                    score = score_record_event(
                        ev_cdh.new_temp_c, ev_cdh.old_record_c, ev_cdh.old_record_year,
                    )
                    if _should_draft(score, ev_cdh.event_id):
                        strongest_signal = ev_cdh
                        strongest_score = score
                        strongest_event_id = ev_cdh.event_id
                        strongest_type = "record"
                        strongest_city = ev_cdh.city
                        strongest_headline = f"{ev_cdh.city} is forecast to challenge a heat record"
                        strongest_facts = [
                            _fact("Forecast high", _temp_pair_c(ev_cdh.new_temp_c)),
                            _fact("Previous record", _temp_pair_c(ev_cdh.old_record_c)),
                            _fact("Old record year", ev_cdh.old_record_year),
                            _fact("Record gap", f"+{ev_cdh.new_temp_c - ev_cdh.old_record_c:.1f}C"),
                            _fact("Country", ev_cdh.country),
                        ]
                        signal_counts["calendar"] += 1
                        # Track only heat records for the simultaneous-records
                        # lane, preserving enough station detail for roll-call.
                        simultaneous_record_stations.append({
                            "city": ev_cdh.city,
                            "country": ev_cdh.country,
                            "temp_c": ev_cdh.new_temp_c,
                            "kind": "high",
                            "old_record_c": ev_cdh.old_record_c,
                            "old_record_year": ev_cdh.old_record_year,
                            "margin_c": round(ev_cdh.new_temp_c - ev_cdh.old_record_c, 1),
                            "elevation_m": city_elevations.get((ev_cdh.city, ev_cdh.country)),
                            "signal_date": (bundle.signal_date or date.today()).isoformat(),
                        })

            if strongest_signal is None and bundle.calendar_date_low:
                ev_cdl: RecordEvent = bundle.calendar_date_low
                if not state.is_duplicate(bot_state, ev_cdl.event_id):
                    score = score_record_low_event(
                        ev_cdl.new_temp_c, ev_cdl.old_record_c, ev_cdl.old_record_year,
                    )
                    if _should_draft(score, ev_cdl.event_id):
                        strongest_signal = ev_cdl
                        strongest_score = score
                        strongest_event_id = ev_cdl.event_id
                        strongest_type = "record_low"
                        strongest_city = ev_cdl.city
                        strongest_headline = f"{ev_cdl.city} hit a daily cold record"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev_cdl.new_temp_c)),
                            _fact("Previous record low", _temp_pair_c(ev_cdl.old_record_c)),
                            _fact("Old record year", ev_cdl.old_record_year),
                            _fact("Record gap", f"{ev_cdl.new_temp_c - ev_cdl.old_record_c:.1f}C"),
                            _fact("Country", ev_cdl.country),
                        ]
                        signal_counts["calendar"] += 1

            if strongest_signal:
                # If strongest_signal is set, the cascade above always set
                # strongest_event_id alongside it — narrow for downstream calls
                # that accept only str.
                assert strongest_event_id is not None
                source_promoted += 1
                # Record synthesis component as soon as editorial gate passes:
                syn_state = us_city_state_map.get(strongest_city)
                if syn_state and strongest_type in {
                    "all_time_high", "monthly_high", "anomaly_hot", "record",
                }:
                    value_c = getattr(strongest_signal, "new_temp_c", None)
                    if value_c is None:
                        value_c = getattr(strongest_signal, "today_temp_c", 0.0)
                    # Compute an anomaly figure the synthesis scorer can use.
                    # anomaly_hot events expose a true anomaly; record events
                    # carry an implicit margin over their prior archive-high,
                    # which is a reasonable proxy. Unknown → 0 (scorer clamps
                    # with abs()+min() so zero contributes nothing).
                    anomaly_c = getattr(strongest_signal, "anomaly_c", None)
                    if anomaly_c is None:
                        old_record_c = getattr(strongest_signal, "old_record_c", None)
                        if old_record_c is not None and value_c is not None:
                            anomaly_c = max(float(value_c) - float(old_record_c), 0.0)
                    kind_map = {
                        "all_time_high": "all_time",
                        "monthly_high": "monthly",
                        "anomaly_hot": "anomaly",
                        "record": "calendar",
                    }
                    state.record_synthesis_component(
                        bot_state,
                        kind="heat",
                        region=syn_state,
                        event_id=strongest_event_id,
                        metadata={
                            "kind": kind_map.get(strongest_type, "record"),
                            "city": strongest_city,
                            "value_c": float(value_c or 0),
                            "anomaly_c": (
                                float(anomaly_c) if anomaly_c is not None else None
                            ),
                        },
                    )
                _signal_source_label = (
                    f"NOAA GHCN-Daily (station {bundle.station_id})"
                    if _signals_provider == "ghcn"
                    else "Open-Meteo forecast + archive"
                )
                review_context = _review_context(
                    source=_signal_source_label,
                    source_key="open_meteo_extreme_signals",
                    headline=strongest_headline,
                    current_run=current_run,
                    facts=strongest_facts,
                )
                # Elite signals bypass the city cooldown. Non-elite signals
                # (calendar-date, monthly, modest anomalies) apply it so a
                # single city heatwave doesn't monopolize the feed.
                elite = strongest_type in ("all_time_high", "all_time_low")
                if strongest_type in ("anomaly_hot", "anomaly_cold"):
                    anomaly_magnitude = abs(
                        getattr(strongest_signal, "anomaly_c", 0) or 0
                    )
                    if anomaly_magnitude >= 18:
                        elite = True

                # Route through the two-bot pipeline. User directive
                # 2026-05-04: the cheap model never writes audience-
                # facing prose. If a future signal type is added that
                # doesn't have a bundle builder, we DROP the signal
                # rather than fall through to voice gen — a missed
                # tweet is better than a Gemini-Flash-written tweet.
                bundle_result: dict = {}
                two_bot_bundle = _two_bot_bundle_for_extreme_signal(
                    strongest_type,
                    strongest_signal,
                    result_out=bundle_result,
                )
                if two_bot_bundle is None:
                    print(
                        f"[two_bot.dispatch] No bundle builder for "
                        f"extreme-signal type {strongest_type!r}; "
                        f"dropping {strongest_event_id}"
                    )
                    ctx = _current_suppression_ctx()
                    if ctx is not None:
                        _record_downstream_suppression(
                            bot_state=ctx["bot_state"],
                            source=ctx.get("source"),
                            run_id=ctx.get("run_id"),
                            event_id=strongest_event_id,
                            score=strongest_score,
                            kill_stage=bundle_result.get("kill_stage", "bundle_build"),
                            kill_reason=bundle_result.get(
                                "kill_reason", "Bundle build failed"
                            ),
                            summary=strongest_city or strongest_headline or None,
                        )
                    continue

                candidate_queued = _enqueue_story_candidate(
                    bot_state,
                    bundle=two_bot_bundle,
                    score=strongest_score,
                    source="open_meteo_extreme_signals",
                    legacy_type=strongest_type,
                    event_id=strongest_event_id,
                    review_context=review_context,
                    city=strongest_city,
                    tweet_date=(bundle.signal_date or date.today()).isoformat(),
                    cooldown_exempt=elite,
                )

                if candidate_queued:
                    # Streak tracking — update on any calendar-date high record.
                    # Key: station_id on GHCN path; city name on Open-Meteo path.
                    # Old city-name entries prune naturally via prune_stale_record_streaks.
                    if strongest_type == "record" and bundle.calendar_date_high:
                        ev_cd = bundle.calendar_date_high
                        streak_key = bundle.station_id if _signals_provider == "ghcn" and bundle.station_id else ev_cd.city
                        state.update_record_streak(
                            bot_state,
                            streak_key,
                            ev_cd.new_temp_c,
                            event_date=bundle.signal_date,
                        )
                        streak = state.get_record_streak(bot_state, streak_key)
                        if streak and streak.get("days", 0) >= 3:
                            streak_event_id = f"streak_{streak_key.replace(' ', '_')}_{streak['last_date']}"
                            if not state.is_duplicate(bot_state, streak_event_id):
                                streak_score = score_record_streak(
                                    streak["days"], streak.get("peak_temp_c", ev_cd.new_temp_c),
                                )
                                if _should_draft(streak_score, streak_event_id):
                                    from src.data.open_meteo import RecordStreakEvent
                                    from src.two_bot.intern import build_record_streak_bundle
                                    streak_event = RecordStreakEvent(
                                        city=ev_cd.city,
                                        country=ev_cd.country,
                                        consecutive_days=streak["days"],
                                        start_date=streak["start_date"],
                                        peak_temp_c=streak.get("peak_temp_c", ev_cd.new_temp_c),
                                        event_id=streak_event_id,
                                        signal_date=bundle.signal_date,
                                    )
                                    streak_bundle = build_record_streak_bundle(streak_event)
                                    streak_ctx = _review_context(
                                        source="state.record_streaks",
                                        source_key="record_streak",
                                        headline=f"{ev_cd.city}: {streak['days']} consecutive daily records",
                                        current_run=current_run,
                                        facts=[
                                            _fact("Consecutive days", streak["days"]),
                                            _fact("Streak start", streak["start_date"]),
                                            _fact("Peak temp", _temp_pair_c(streak.get("peak_temp_c", ev_cd.new_temp_c))),
                                        ],
                                    )
                                    if _enqueue_story_candidate(
                                        bot_state,
                                        bundle=streak_bundle,
                                        score=streak_score,
                                        source="open_meteo_extreme_signals",
                                        legacy_type="record_streak",
                                        event_id=streak_event_id,
                                        review_context=streak_ctx,
                                        city=ev_cd.city,
                                        tweet_date=(bundle.signal_date or date.today()).isoformat(),
                                        cooldown_exempt=True,
                                    ):
                                        signal_counts["streak"] += 1
                                        source_promoted += 1

            # Append a per-bundle row to the dashboard event log. Captured
            # for every bundle iterated regardless of decision so the UI can
            # show "X considered, Y drafted, Z rejected, W no-signal".
            # Only the GHCN provider exposes station_id; rows from the
            # Open-Meteo provider get an empty station_id and the city instead.
            if _signals_provider == "ghcn":
                if strongest_event_id and not candidate_queued:
                    decision = "rejected"
                elif candidate_queued:
                    decision = "queued_for_triage"
                else:
                    decision = "no_qualifying_signal"
                ghcn_event_log.append({
                    "station_id": bundle.station_id,
                    "station_name": bundle.station_name,
                    "country": bundle.country,
                    "city": bundle.city,
                    "signal_date": (
                        bundle.signal_date.isoformat() if bundle.signal_date else None
                    ),
                    "decision": decision,
                    "type": strongest_type or None,
                    "event_id": strongest_event_id,
                    "score": (
                        round(strongest_score.total, 2) if strongest_score else None
                    ),
                    "today_max_c": bundle.today_max_c,
                    "today_min_c": bundle.today_min_c,
                })

        # Simultaneous records detection — fire one summary signal if many cities broke records.
        # Two formats available; flat summary is the default. Roll-call (per-station list with
        # elevations) fires only when the cluster shape qualifies — same country with a
        # meaningful elevation spread. See src/editorial/simultaneous_format.py.
        simultaneous_groups: dict[str, list[dict]] = {}
        for station_row in simultaneous_record_stations:
            sim_date = station_row.get("signal_date") or date.today().isoformat()
            simultaneous_groups.setdefault(sim_date, []).append(station_row)
        for today_iso, simultaneous_group in simultaneous_groups.items():
            if len(simultaneous_group) < 5:
                continue
            sim_event_id = f"simultaneous_records_{today_iso}"
            if not state.is_duplicate(bot_state, sim_event_id):
                city_names = [s["city"] for s in simultaneous_group]
                sim_score = score_simultaneous_records(len(city_names), city_names)
                if _should_draft(sim_score, sim_event_id):
                    from src.two_bot.intern import build_simultaneous_records_bundle
                    roll_call_subset = select_roll_call_subset(simultaneous_group)
                    if roll_call_subset:
                        rc_country = roll_call_subset[0].get("country", "")
                        rc_elevs = [
                            s["elevation_m"] for s in roll_call_subset
                            if s.get("elevation_m") is not None
                        ]
                        rc_facts = [
                            _fact("Format", "roll-call"),
                            _fact("Country", rc_country),
                            _fact("Stations in subset", len(roll_call_subset)),
                            _fact("Total simultaneous", len(simultaneous_group)),
                        ]
                        if rc_elevs:
                            rc_facts.append(
                                _fact(
                                    "Elevation range",
                                    f"{min(rc_elevs)}m to {max(rc_elevs)}m",
                                )
                            )
                        sim_ctx = _review_context(
                            source=(
                                "NOAA GHCN-Daily"
                                if _signals_provider == "ghcn"
                                else "open_meteo_extreme_signals"
                            ),
                            source_key="simultaneous_records",
                            headline=(
                                f"{len(roll_call_subset)} stations across {rc_country} "
                                f"broke records (multi-altitude)"
                            ),
                            current_run=current_run,
                            facts=rc_facts,
                        )
                        sim_stations = roll_call_subset
                    else:
                        sim_ctx = _review_context(
                            source=(
                                "NOAA GHCN-Daily"
                                if _signals_provider == "ghcn"
                                else "open_meteo_extreme_signals"
                            ),
                            source_key="simultaneous_records",
                            headline=f"{len(city_names)} cities broke records on same day",
                            current_run=current_run,
                            facts=[
                                _fact("Format", "flat summary"),
                                _fact("City count", len(city_names)),
                                _fact("Sample cities", ", ".join(city_names[:5])),
                            ],
                        )
                        sim_stations = simultaneous_group
                    sim_bundle = build_simultaneous_records_bundle(
                        sim_stations, event_id=sim_event_id, when=today_iso,
                    )
                    _enqueue_story_candidate(
                        bot_state,
                        bundle=sim_bundle,
                        score=sim_score,
                        source="open_meteo_extreme_signals",
                        legacy_type="simultaneous_records",
                        event_id=sim_event_id,
                        review_context=sim_ctx,
                    )

        # Country-level records — the biggest story our pipeline produces.
        # Aggregates across every sampled city in a country; fires when
        # today's peak beats the archive-wide peak anywhere in the country.
        country_count = 0
        for cr in country_records:
            if state.is_duplicate(bot_state, cr.event_id):
                continue
            score = score_country_record(
                cr.new_temp_c, cr.old_record_c, cr.old_record_year,
                kind=cr.kind, cities_sampled=cr.cities_sampled,
                years_of_data=cr.years_of_data,
            )
            if not _should_draft(score, cr.event_id):
                continue
            source_promoted += 1
            descriptor = "hottest" if cr.kind == "high" else "coldest"
            country_source_label = (
                "NOAA GHCN-Daily station aggregate"
                if _signals_provider == "ghcn"
                else "Open-Meteo archive (country-wide aggregate)"
            )
            cr_ctx = _review_context(
                source=country_source_label,
                source_key="country_record",
                headline=f"{cr.country}: {descriptor} reading in {cr.years_of_data}-yr archive",
                current_run=current_run,
                facts=[
                    _fact("Country", cr.country),
                    _fact("Peak city today", cr.peak_city),
                    _fact("Peak temp today", _temp_pair_c(cr.new_temp_c)),
                    _fact("Prior archive peak", _temp_pair_c(cr.old_record_c)),
                    _fact("Prior peak city", cr.old_record_city),
                    _fact("Prior peak year", cr.old_record_year),
                    _fact("Cities aggregated", cr.cities_sampled),
                ],
            )
            # Country records: ported to two-bot writer (Sonnet) on
            # 2026-05-03. Country records are also not subject to
            # per-city cooldown — no single city "owns" this story.
            from src.two_bot.intern import build_country_record_bundle
            cr_bundle = build_country_record_bundle(cr)
            syn_state = us_city_state_map.get(cr.peak_city)

            def _on_success(
                _bs: BotState = bot_state,
                _country_record = cr,
                _syn_state: str | None = syn_state,
            ) -> None:
                if _country_record.kind == "high" and _syn_state:
                    state.record_synthesis_component(
                        _bs,
                        kind="heat",
                        region=_syn_state,
                        event_id=_country_record.event_id,
                        metadata={
                            "kind": "all_time",
                            "city": _country_record.peak_city,
                            "value_c": float(_country_record.new_temp_c or 0),
                        },
                    )

            if _enqueue_story_candidate(
                bot_state,
                bundle=cr_bundle,
                score=score,
                source="open_meteo_extreme_signals",
                legacy_type=f"country_{cr.kind}",
                event_id=cr.event_id,
                review_context=cr_ctx,
                tweet_date=(cr.signal_date or date.today()).isoformat(),
                on_draft_success=_on_success,
            ):
                country_count += 1

        # Prune stale streaks at cycle end
        state.prune_stale_record_streaks(bot_state)

        total_observed = sum(signal_counts.values()) + country_count
        # Build a structured note. For GHCN: surface the funnel
        # (active -> with-obs -> checked -> raw_signals -> bundles -> queued)
        # so the dashboard can render pipeline visibility.
        signal_breakdown = (
            f"all_time:{signal_counts['all_time']} monthly:{signal_counts['monthly']} "
            f"absolute_extreme:{signal_counts['absolute_extreme']} "
            f"anomaly:{signal_counts['anomaly']} calendar:{signal_counts['calendar']} "
            f"streak:{signal_counts['streak']} country:{country_count}"
        )
        source_status = "success"
        details: dict | None = None
        if _signals_provider == "ghcn" and ghcn_pipeline_metrics:
            source_status = _classify_ghcn_source_status(ghcn_pipeline_metrics)
            diff_attempted = ghcn_pipeline_metrics.get("diff_dates_attempted", "-")
            diff_fetched = ghcn_pipeline_metrics.get("diff_dates_fetched", "-")
            diff_missing = ghcn_pipeline_metrics.get("diff_dates_missing", "-")
            funnel = (
                f"stations_active:{ghcn_pipeline_metrics.get('stations_active', '-')} "
                f"stations_with_obs:{ghcn_pipeline_metrics.get('stations_with_obs', '-')} "
                f"checked:{ghcn_pipeline_metrics.get('stations_checked', '-')} "
                f"raw_signals:{ghcn_pipeline_metrics.get('raw_signals', '-')} "
                f"bundles:{ghcn_pipeline_metrics.get('bundles_after_dedup', '-')} "
                f"diffs:{diff_fetched}/{diff_attempted} "
                f"diff_missing:{diff_missing} "
                f"queued:{source_promoted}"
            )
            note = f"provider:ghcn {funnel} | {signal_breakdown}"
            details = {
                "provider": "ghcn",
                "pipeline_metrics": dict(ghcn_pipeline_metrics),
                # Cap the events list so a single noisy cycle (thousands of
                # raw signals dedup-survived to dozens of bundles) doesn't
                # bloat the run record.
                "events": ghcn_event_log[:200],
            }
        else:
            city_failures = int(open_meteo_pipeline_metrics.get("city_fetch_failures", 0) or 0)
            city_readings = int(open_meteo_pipeline_metrics.get("city_readings", 0) or 0)
            if city_failures and city_readings:
                source_status = "degraded"
            elif city_failures and not city_readings:
                source_status = "failed"
            note = f"provider:{_signals_provider} {signal_breakdown}"
            if open_meteo_pipeline_metrics:
                details = {
                    "provider": "open_meteo",
                    "pipeline_metrics": dict(open_meteo_pipeline_metrics),
                }
        if source_status == "failed":
            fail_count = state.increment_data_source_failure(bot_state, _signals_provider)
            try:
                if fail_count >= 3:
                    print(
                        f"[alerts] STRUCTURAL ALERT: {_signals_provider} "
                        f"has failed {fail_count} consecutive cycles"
                    )
            except TypeError:
                pass
        else:
            state.reset_data_source_failure(bot_state, _signals_provider)
        _record_source_run(
            current_run, bot_state, "open_meteo_extreme_signals", signals_start,
            status=source_status, observed=total_observed,
            promoted=source_promoted, drafted=source_drafted,
            note=note, details=details,
        )
    except Exception as e:
        print(f"[alerts] Extreme signals error: {e}")
        fail_count = state.increment_data_source_failure(bot_state, _signals_provider)
        try:
            if fail_count >= 3:
                print(f"[alerts] STRUCTURAL ALERT: {_signals_provider} has failed {fail_count} consecutive cycles")
        except TypeError:
            pass  # mock or unexpected return type — skip the alert
        state.log_error(bot_state, "open_meteo_extreme_signals", str(e))
        _record_source_run(
            current_run, bot_state, "open_meteo_extreme_signals", signals_start,
            status="failed", error=str(e),
        )
    return drafted
