"""Temperature two-bot intern builders."""



from __future__ import annotations



from dataclasses import asdict

from datetime import date

from src.data.ghcn import normalize_station_name

from src.data.open_meteo import AllTimeRecord

from src.data.open_meteo import AnomalyEvent

from src.data.open_meteo import AbsoluteExtremeEvent

from src.data.open_meteo import CountryRecord

from src.data.open_meteo import MonthlyRecord

from src.data.open_meteo import RecordEvent

from src.data.open_meteo import RecordStreakEvent

from src.data.reanalysis_anomaly import RegionalAnomalyEvent

from src.editorial.records_cluster import CAUSE_ATTRIBUTION_DENYLIST, ClusterName

from src.two_bot.types import StoryBundle

from ._shared import _MONTH_NAMES, _audience_unit_facts, _c_to_f, _climate_context_facts, _format_where, _ghcn_observation_facts, _headline_temp_label, _resolve_when



def build_monthly_high_bundle(ev: MonthlyRecord, *, source: str = "open_meteo") -> StoryBundle:
    """Assemble a StoryBundle for a monthly high-temperature record signal.

    Args:
        ev:     The ``MonthlyRecord`` dataclass from Open-Meteo or GHCN.
        source: ``"ghcn"`` for GHCN observed station records (emits
                ``observed_*_c``); ``"open_meteo"`` (default) for forecast
                data (emits ``forecast_*_c``).
    """

    month_name = _MONTH_NAMES[ev.month] if 1 <= ev.month <= 12 else str(ev.month)
    state = getattr(ev, "state", None)
    city = normalize_station_name(ev.city) or ev.city
    where = _format_where(city, ev.country, state)
    metric_label = _headline_temp_label(ev.kind, source)
    new_temp_f = _c_to_f(ev.new_temp_c)
    old_record_f = _c_to_f(ev.old_record_c)
    margin_c = round(ev.new_temp_c - ev.old_record_c, 2)
    return StoryBundle(
        signal_kind=f"monthly_{ev.kind}",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": metric_label,
            "value": ev.new_temp_c,
            "unit": "C",
            "value_f": new_temp_f,
        },
        current_facts=[
            {"label": "city", "value": city},
            {"label": "country", "value": ev.country},
            {"label": "month", "value": month_name},
            {"label": "kind", "value": ev.kind},
            {"label": "today_temp_c", "value": ev.new_temp_c},
            {"label": "today_temp_f", "value": new_temp_f},
            *_ghcn_observation_facts(state, ev.kind),
            *_audience_unit_facts(ev.country),
            *_climate_context_facts(
                getattr(ev, "lat", None),
                getattr(ev, "lon", None),
                category=ev.kind,
            ),
        ],
        historical_context={
            "prior_record_c": ev.old_record_c,
            "prior_record_f": old_record_f,
            "prior_record_year": ev.old_record_year,
            "archive_years": ev.years_of_data,
            "month": month_name,
            "margin_c": margin_c,
            "margin_f": (new_temp_f - old_record_f)
                if (new_temp_f is not None and old_record_f is not None)
                else None,
        },
        raw_signal_dump={**asdict(ev), "city": city},
    )

def build_country_record_bundle(cr: CountryRecord) -> StoryBundle:
    """Assemble a StoryBundle for a country-level archive-record signal."""

    return StoryBundle(
        signal_kind=f"country_{cr.kind}",
        where=cr.country,
        when=_resolve_when(cr.signal_date),
        event_id=cr.event_id,
        headline_metric={
            "label": "country_archive_peak_c",
            "value": cr.new_temp_c,
            "unit": "C",
        },
        current_facts=[
            {"label": "country", "value": cr.country},
            {"label": "peak_city_today", "value": cr.peak_city},
            {"label": "prior_peak_city", "value": cr.old_record_city},
            {"label": "kind", "value": cr.kind},
        ],
        historical_context={
            "prior_peak_c": cr.old_record_c,
            "prior_peak_year": cr.old_record_year,
            "prior_peak_city": cr.old_record_city,
            "archive_years": cr.years_of_data,
            "cities_sampled": cr.cities_sampled,
            "kind": cr.kind,
            "margin_c": round(cr.new_temp_c - cr.old_record_c, 2),
        },
        raw_signal_dump=asdict(cr),
    )

def build_record_bundle(ev: RecordEvent, *, source: str = "open_meteo") -> StoryBundle:
    """Assemble a StoryBundle for a calendar-day record signal.

    "Calendar-day record" means a city is forecast to break the previous
    record for *this specific date* (e.g. May 3). These signals fire
    routinely in temperate climates, so the editorial bar should be high
    — the writer's discipline (and the empty-margin guard) decides
    whether it ships, not the absolute temperature.

    Args:
        ev:     The ``RecordEvent`` dataclass from Open-Meteo or GHCN.
        source: ``"ghcn"`` for GHCN observed records; ``"open_meteo"``
                (default) for forecast data.
    """

    kind = getattr(ev, "kind", "high")
    state = getattr(ev, "state", None)
    city = normalize_station_name(ev.city) or ev.city
    margin_c = round(ev.new_temp_c - ev.old_record_c, 2)
    new_temp_f = _c_to_f(ev.new_temp_c)
    old_record_f = _c_to_f(ev.old_record_c)
    where = _format_where(city, ev.country, state)
    when = _resolve_when(ev.signal_date)
    return StoryBundle(
        signal_kind="calendar_record" if kind == "high" else "calendar_record_low",
        where=where,
        when=when,
        event_id=ev.event_id,
        headline_metric={
            "label": _headline_temp_label(kind, source),
            "value": ev.new_temp_c,
            "unit": "C",
            "value_f": new_temp_f,
        },
        current_facts=[
            {"label": "city", "value": city},
            {"label": "country", "value": ev.country},
            {"label": "calendar_date", "value": when},
            {"label": "kind", "value": kind},
            {"label": "today_temp_c", "value": ev.new_temp_c},
            {"label": "today_temp_f", "value": new_temp_f},
            *_ghcn_observation_facts(state, kind),
            *_audience_unit_facts(ev.country),
            *_climate_context_facts(
                getattr(ev, "lat", None),
                getattr(ev, "lon", None),
                category=kind,
            ),
        ],
        historical_context={
            "prior_record_c": ev.old_record_c,
            "prior_record_f": old_record_f,
            "prior_record_year": ev.old_record_year,
            "margin_c": margin_c,
            "margin_f": (new_temp_f - old_record_f)
                if (new_temp_f is not None and old_record_f is not None)
                else None,
            "scope": "calendar_date_only",
            "kind": kind,
        },
        raw_signal_dump={**asdict(ev), "city": city},
    )

def build_all_time_record_bundle(ev: AllTimeRecord, *, source: str = "open_meteo") -> StoryBundle:
    """City broke (or is forecast to break) its archive-record temperature.

    Highest-tier temperature signal — a ``+0.5C over a 50-year archive``
    is a real headline. The writer should treat the archive span as the
    rarity peg.

    Args:
        ev:     The ``AllTimeRecord`` dataclass from Open-Meteo or GHCN.
        source: ``"ghcn"`` for GHCN observed records; ``"open_meteo"``
                (default) for forecast data.
    """

    state = getattr(ev, "state", None)
    city = normalize_station_name(ev.city) or ev.city
    where = _format_where(city, ev.country, state)
    new_temp_f = _c_to_f(ev.new_temp_c)
    old_record_f = _c_to_f(ev.old_record_c)
    margin_c = round(ev.new_temp_c - ev.old_record_c, 2)
    return StoryBundle(
        signal_kind=f"open_meteo_archive_{ev.kind}",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": _headline_temp_label(ev.kind, source),
            "value": ev.new_temp_c,
            "unit": "C",
            "value_f": new_temp_f,
        },
        current_facts=[
            {"label": "city", "value": city},
            {"label": "country", "value": ev.country},
            {"label": "kind", "value": ev.kind},
            {"label": "today_temp_c", "value": ev.new_temp_c},
            {"label": "today_temp_f", "value": new_temp_f},
            *_ghcn_observation_facts(state, ev.kind),
            *_audience_unit_facts(ev.country),
            *_climate_context_facts(
                getattr(ev, "lat", None),
                getattr(ev, "lon", None),
                category=ev.kind,
            ),
        ],
        historical_context={
            "prior_record_c": ev.old_record_c,
            "prior_record_f": old_record_f,
            "prior_record_year": ev.old_record_year,
            "archive_years": ev.years_of_data,
            "archive_start_year": date.today().year - ev.years_of_data,
            "archive_window_only": True,
            "kind": ev.kind,
            "margin_c": margin_c,
            "margin_f": (new_temp_f - old_record_f)
                if (new_temp_f is not None and old_record_f is not None)
                else None,
            "scope": "archive_history",
            "forbidden_claims": [
                "all-time high",
                "all-time low",
                "hottest ever",
                "coldest ever",
                "highest ever",
                "lowest ever",
                "in recorded history",
            ],
        },
        raw_signal_dump={**asdict(ev), "city": city},
    )

def build_anomaly_bundle(ev: AnomalyEvent, *, source: str = "open_meteo") -> StoryBundle:
    """Today's reading is far above (or below) the historical mean.

    Args:
        ev:     The ``AnomalyEvent`` dataclass from Open-Meteo or GHCN.
        source: ``"ghcn"`` for GHCN observed records; ``"open_meteo"``
                (default) for forecast data. Passed through so callers are
                consistent; anomaly headline_metric uses ``anomaly_c`` label
                regardless of source.
    """

    state = getattr(ev, "state", None)
    city = normalize_station_name(ev.city) or ev.city
    where = _format_where(city, ev.country, state)
    kind = "hot" if ev.anomaly_c >= 0 else "cold"
    # Map anomaly direction to TMAX/TMIN observation framing for the
    # observation_kind fact: hot anomalies derive from afternoon highs,
    # cold anomalies from overnight lows.
    obs_kind = "high" if kind == "hot" else "low"
    today_temp_f = _c_to_f(ev.today_temp_c)
    historical_mean_f = _c_to_f(ev.historical_mean_c)
    # Anomaly itself is a delta — convert via 9/5 scaling, no offset.
    anomaly_f = (
        round(ev.anomaly_c * 9 / 5)
        if ev.anomaly_c is not None
        else None
    )
    return StoryBundle(
        signal_kind=f"anomaly_{kind}",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": "anomaly_c",
            "value": ev.anomaly_c,
            "unit": "C",
            "value_f": anomaly_f,
        },
        current_facts=[
            {"label": "city", "value": city},
            {"label": "country", "value": ev.country},
            {"label": "today_c", "value": ev.today_temp_c},
            {"label": "today_f", "value": today_temp_f},
            {"label": "historical_mean_c", "value": ev.historical_mean_c},
            {"label": "historical_mean_f", "value": historical_mean_f},
            {"label": "anomaly_c", "value": ev.anomaly_c},
            {"label": "anomaly_f", "value": anomaly_f},
            *_ghcn_observation_facts(state, obs_kind),
            *_audience_unit_facts(ev.country),
            *_climate_context_facts(
                getattr(ev, "lat", None),
                getattr(ev, "lon", None),
                category=kind,
            ),
        ],
        historical_context={
            "historical_mean_c": ev.historical_mean_c,
            "anomaly_c": ev.anomaly_c,
            "archive_years": ev.years_of_data,
            "scope": "monthly_baseline",
        },
        raw_signal_dump={**asdict(ev), "city": city},
    )

def build_absolute_extreme_bundle(ev: AbsoluteExtremeEvent) -> StoryBundle:
    """Assemble a StoryBundle for a latitude-banded absolute extreme signal."""
    state = getattr(ev, "state", None)
    city = normalize_station_name(ev.city) or ev.city
    where = _format_where(city, ev.country, state)
    today_temp_f = _c_to_f(ev.today_temp_c)
    threshold_f = _c_to_f(ev.threshold_c)
    is_forecast = ev.data_source == "forecast"
    return StoryBundle(
        signal_kind=f"absolute_extreme_{ev.kind}",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": f"today_temp_c_{ev.kind}",
            "value": ev.today_temp_c,
            "unit": "C",
            "value_f": today_temp_f,
            "is_forecast": is_forecast,
        },
        current_facts=[
            {"label": "city", "value": city},
            {"label": "country", "value": ev.country},
            {"label": "lat", "value": ev.lat},
            {"label": "band_label", "value": ev.band_label},
            {"label": "today_c", "value": ev.today_temp_c},
            {"label": "today_f", "value": today_temp_f},
            {"label": "threshold_c", "value": ev.threshold_c},
            {"label": "threshold_f", "value": threshold_f},
            {"label": "kind", "value": ev.kind},
            {"label": "data_source", "value": ev.data_source},
            *_audience_unit_facts(ev.country),
            *_climate_context_facts(ev.lat, ev.lon, category=ev.kind),
        ],
        historical_context={
            "band_label": ev.band_label,
            "threshold_c": ev.threshold_c,
            "scope": "latitude_band_absolute",
            "is_forecast": is_forecast,
        },
        raw_signal_dump={**asdict(ev), "city": city},
    )

def build_regional_anomaly_bundle(ev: RegionalAnomalyEvent) -> StoryBundle:
    """Assemble a StoryBundle for a sampled-city regional anomaly (honesty Layer 1).

    The signal is a POINT INDEX over N sampled cities — never an area-weighted
    national mean. This builder enforces that at the bundle level:
      * ``where`` names the N sampled cities, never the bare region;
      * ``signal_kind`` is the BARE literal "regional_anomaly" so the deterministic
        §F honesty gate (which keys on ``bundle.signal_kind == "regional_anomaly"``)
        fires;
      * ``current_facts`` leads with ``data_kind = point_index_not_area_weighted``
        and keeps ``region`` only as the audience-unit lookup key;
      * ``forbidden_claims`` lists dishonest aggregate phrasings for the §F gate to
        substring-match. They are curated to be HONEST-FORM-SAFE: none of them is a
        substring of "N sampled cities in {region} …", so the gate rejects the
        bare-region / national / area-weighted framings without false-killing an
        honest draft. (The naked "{region} averaged X" verb form is steered by the
        writer prompt + judged by fact-check, not substring-matched here.)
    """
    region = ev.region
    anomaly_f = round(ev.mean_anomaly_c * 1.8, 1)  # an anomaly is a DELTA — no +32 offset
    # Lead figure rounded to a WHOLE degree. A sampled-city point-index mean is not
    # precise to 0.01C, so citing "11.53C" is false precision — and reads as a stats
    # bulletin, not the story. Publishing the rounded value lets the writer lead with
    # a clean "about 12C" by citing a bundle field VERBATIM, rather than rounding the
    # raw mean itself (which the strict BUNDLE_FACT fact-check would kill as a
    # precision mismatch). Same rationale as zscore_1dp below; the raw ``value`` is
    # still published so the fact-check can verify a finer decimal citation
    # (±0.1C of raw) and for the record.
    anomaly_rounded_c = round(ev.mean_anomaly_c)
    # Publish the z-score at 1-decimal precision. It is supporting context, not the
    # lead; exposing the raw float (e.g. 3.42) makes the writer's natural "3.4
    # standard deviations" citation read as a rounded-precision mismatch to the
    # strict BUNDLE_FACT fact-check, which kills the whole draft.
    zscore_1dp = round(ev.mean_zscore, 1)
    # Recency: the spell may have ENDED within the detector's recency window (window_end
    # before the latest complete ERA5 day). Surface ended_days_ago so the writer frames an
    # ended spell in the PAST tense; when ended, forbid present/ongoing phrasings so the
    # deterministic §F honesty gate kills "is running / currently / right now" framings.
    ended_days_ago = 0
    if ev.latest_complete_day and ev.window_end:
        try:
            ended_days_ago = max(0, (
                date.fromisoformat(ev.latest_complete_day) - date.fromisoformat(ev.window_end)
            ).days)
        except ValueError:
            ended_days_ago = 0
    forbidden = [
        "national mean", "national average", "area-weighted", "area weighted",
        "country-wide average", "countrywide average", "nationwide average",
        "country-wide mean",
        f"{region}'s average", f"{region}'s temperature",
        f"all of {region}", f"the whole of {region}",
        f"entire {region}", f"{region} as a whole",
    ]
    if ended_days_ago > 0:
        # Present/ongoing framings of an ENDED spell. Deterministic backstop; the
        # fact-check §j2 recency rule (keyed on ended_days_ago > 0) is the catch-all for
        # current-state verbs not enumerated here. All forms are unambiguously present
        # tense, so an honest PAST-tense draft ("ran … through {window_end}") trips none.
        forbidden += [
            "is running", "are running", "currently", "right now", "as we speak",
            "still running", "still sweltering",
            "is baking", "are baking", "bakes",
            "is roasting", "are roasting", "roasts",
            "is scorching", "are scorching", "scorches",
            "is sweltering", "are sweltering", "swelters",
            "is gripping", "are gripping", "grips",
            "is sizzling", "is simmering", "sizzles", "simmers",
        ]
    return StoryBundle(
        signal_kind="regional_anomaly",
        where=f"{ev.cities_sampled} sampled cities in {region}",
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": "sampled_city_mean_anomaly_c",
            "value": ev.mean_anomaly_c,
            "unit": "C",
            "value_f": anomaly_f,
            # The whole-degree figure the writer LEADS with ("about 12C"); raw
            # ``value`` stays for fact-check tolerance + the record.
            "value_rounded_c": anomaly_rounded_c,
            "cities_sampled": ev.cities_sampled,
        },
        current_facts=[
            {"label": "data_kind", "value": "point_index_not_area_weighted"},
            {"label": "cities_sampled", "value": ev.cities_sampled},
            {"label": "mean_anomaly_c", "value": ev.mean_anomaly_c},
            {"label": "mean_anomaly_f", "value": anomaly_f},
            {"label": "mean_zscore", "value": zscore_1dp},
            # fraction_exceeding is a fraction of city-DAYS over the window, NOT a
            # same-day count of cities — exposing it as a fact invited the writer to
            # mint a false "5 of 6 cities" claim that the fact-check (rightly) killed.
            # It survives in raw_signal_dump for the record; the only honest, citable
            # city count is cities_sampled, and all of them fed the mean.
            {"label": "sustained_days", "value": ev.sustained_days},
            # Window + recency: when ended_days_ago > 0 the spell has ENDED (peaked then
            # eased) — the writer must use past tense and cite the window, never "currently".
            {"label": "window_start", "value": ev.window_start},
            {"label": "window_end", "value": ev.window_end},
            {"label": "ended_days_ago", "value": ended_days_ago},
            # ``region`` is retained ONLY to feed _audience_unit_facts; the writer
            # prompt forbids citing it as a bare aggregate.
            {"label": "region", "value": region},
            *_audience_unit_facts(region),
        ],
        historical_context={
            "scope": "sampled_city_daily_era5_anomaly",
            "anomaly_floor_c": 6.0,
            "zscore_floor": 2.0,
            "mean_zscore": zscore_1dp,
            "sustained_days": ev.sustained_days,
            "window_start": ev.window_start,
            "window_end": ev.window_end,
            "latest_complete_day": ev.latest_complete_day,
            "ended_days_ago": ended_days_ago,
            # Honest-form-safe dishonest phrasings (substring-matched, case-insensitive, by
            # the §F gate). When the spell has ENDED, present/ongoing framings are appended.
            "forbidden_claims": forbidden,
        },
        raw_signal_dump=asdict(ev),
    )

def build_record_streak_bundle(ev: RecordStreakEvent) -> StoryBundle:
    """A city has broken its daily record N consecutive days."""

    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    return StoryBundle(
        signal_kind="record_streak",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": "consecutive_days",
            "value": ev.consecutive_days,
            "unit": "days",
        },
        current_facts=[
            {"label": "city", "value": ev.city},
            {"label": "country", "value": ev.country},
            {"label": "consecutive_days", "value": ev.consecutive_days},
            {"label": "start_date", "value": ev.start_date},
            {"label": "peak_temp_c", "value": ev.peak_temp_c},
        ],
        historical_context={
            "scope": "consecutive_calendar_records",
            "start_date": ev.start_date,
            "peak_temp_c": ev.peak_temp_c,
        },
        raw_signal_dump=asdict(ev),
    )

def build_simultaneous_records_bundle(
    stations: list[dict],
    *,
    event_id: str,
    when: str | None = None,
) -> StoryBundle:
    """Many cities broke their calendar-day record on the same day.

    ``stations`` is the list of per-station dicts main.py builds in the
    extreme-signals loop (city, country, temp_c, kind, old_record_c,
    old_record_year, margin_c, elevation_m). Geographic spread and
    elevation diversity are the story.
    """

    when = when or date.today().isoformat()
    countries = sorted({s.get("country", "") for s in stations if s.get("country")})
    cities = [s.get("city", "") for s in stations if s.get("city")]
    return StoryBundle(
        signal_kind="simultaneous_records",
        where=", ".join(countries) if countries else "global",
        when=when,
        event_id=event_id,
        headline_metric={
            "label": "stations_breaking_record",
            "value": len(stations),
            "unit": "cities",
        },
        current_facts=[
            {"label": "station_count", "value": len(stations)},
            {"label": "countries", "value": countries},
            {"label": "cities", "value": cities},
        ],
        historical_context={
            "scope": "same_day_calendar_records",
            "stations": stations,  # full per-station detail for the writer
        },
        raw_signal_dump={"stations": stations, "event_id": event_id},
    )

def build_heat_records_cluster_bundle(
    stations: list[dict],
    name: ClusterName,
    *,
    event_id: str,
    when: str | None = None,
) -> StoryBundle:
    """A spatially-coherent cluster of same-day daily heat records (#414).

    Every geography label the writer may use is a carried, verifiable bundle fact:
    ``region_name`` (a documented reganom zone, or null), ``cluster_continents``
    (may be empty when the continent can't be asserted honestly), and
    ``cluster_countries``. The writer cites them verbatim and may name NO other
    region; single-cause attributions ("heat dome", blocking ridge, …) are carried
    in ``forbidden_claims`` and hard-blocked by the deterministic honesty gate.
    """
    when = when or date.today().isoformat()
    sample_cities = [s.get("city", "") for s in stations if s.get("city")][:5]
    where = name.region_name or ", ".join(name.lead_countries) or "global"
    return StoryBundle(
        signal_kind="heat_records_cluster",
        where=where,
        when=when,
        event_id=event_id,
        headline_metric={
            "label": "cities_setting_daily_records",
            "value": name.city_count,
            "unit": "cities",
        },
        current_facts=[
            {"label": "city_count", "value": name.city_count},
            {"label": "region_name", "value": name.region_name},
            {"label": "cluster_countries", "value": name.countries},
            {"label": "cluster_continents", "value": name.continents},
            {"label": "sample_cities", "value": sample_cities},
        ],
        historical_context={
            "scope": "same_day_daily_records_cluster",
            "stations": stations,  # full per-station detail for the writer
            "forbidden_claims": list(CAUSE_ATTRIBUTION_DENYLIST),
        },
        raw_signal_dump={"stations": stations, "event_id": event_id},
    )

def build_hot10_bundle(
    cities: list[dict],
    *,
    changes: list[str],
    event_id: str,
) -> StoryBundle:
    """Daily Hot 10 leaderboard.

    ``cities`` is the ranked list of {city, country, temp_high_c,
    normal_high_c, anomaly_c}. ``changes`` is the precomputed
    rank-shift / new-entry strings the writer can paraphrase.
    """

    leader = cities[0] if cities else None
    return StoryBundle(
        signal_kind="hot10",
        where=f"{leader['city']}, {leader['country']}" if leader else "global",
        when=date.today().isoformat(),
        event_id=event_id,
        headline_metric={
            "label": "top_anomaly_c",
            "value": leader["anomaly_c"] if leader else None,
            "unit": "C",
        },
        current_facts=[
            {"label": "leader_city", "value": leader["city"] if leader else None},
            {"label": "leader_country", "value": leader["country"] if leader else None},
            {"label": "leader_temp_c", "value": leader["temp_high_c"] if leader else None},
            {"label": "leader_anomaly_c", "value": leader["anomaly_c"] if leader else None},
            {"label": "city_count", "value": len(cities)},
            {"label": "cities", "value": cities},
            {"label": "rank_changes", "value": changes},
            *_audience_unit_facts(leader["country"] if leader else None),
        ],
        historical_context={"scope": "daily_top10_anomaly_leaderboard"},
        raw_signal_dump={"cities": cities, "changes": changes, "event_id": event_id},
    )
