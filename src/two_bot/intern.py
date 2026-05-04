"""Stage 1: deterministic story-bundle assembly for each signal type.

Every signal type that generates a tweet has a bundle builder here. The
intern is the only stage that touches raw data shapes — everything
downstream (writer, claim extractor, fact-check, memory) operates on
the canonical ``StoryBundle``. When a new signal source ships, add its
builder to this file; do not let raw dataclasses leak into the writer.
"""

from dataclasses import asdict
from datetime import date

from src.data.co2 import CO2Milestone
from src.data.firms import FireEvent
from src.data.fire_footprint import FireComplex, TIERS_HECTARES
from src.data.gdacs import GlobalDisasterEvent
from src.data.ice_mass import IceMassRecord
from src.data.nws_alerts import SevereWeatherAlert
from src.data.ocean import ExtremeWaveEvent
from src.data.ocean_sst import MarineHeatwaveStreakEvent
from src.data.open_meteo import (
    AllTimeRecord,
    AnomalyEvent,
    CountryRecord,
    MonthlyRecord,
    RecordEvent,
    RecordStreakEvent,
)
from src.data.river_gauges import FloodEvent
from src.data.sea_ice import SeaIceRecord
from src.data.water_levels import StormSurgeEvent
from src.two_bot.types import StoryBundle

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def build_fire_bundle(fire: FireEvent) -> StoryBundle:
    """Assemble a pure-facts StoryBundle for a fire signal."""

    return StoryBundle(
        signal_kind="fire",
        where=fire.nearest_city or fire.country,
        when=date.today().isoformat(),
        event_id=fire.event_id,
        headline_metric={"label": "FRP", "value": fire.frp, "unit": "MW"},
        current_facts=[
            {"label": "satellite_confidence", "value": fire.confidence, "unit": "%"},
            {"label": "country", "value": fire.country},
            {"label": "nearest_region", "value": fire.nearest_city},
            {"label": "lat", "value": fire.lat},
            {"label": "lon", "value": fire.lon},
        ],
        historical_context={},
        raw_signal_dump={
            "lat": fire.lat,
            "lon": fire.lon,
            "confidence": fire.confidence,
            "frp": fire.frp,
            "nearest_city": fire.nearest_city,
            "country": fire.country,
            "event_id": fire.event_id,
        },
    )


def build_monthly_high_bundle(ev: MonthlyRecord) -> StoryBundle:
    """Assemble a StoryBundle for a monthly high-temperature record signal."""

    month_name = _MONTH_NAMES[ev.month] if 1 <= ev.month <= 12 else str(ev.month)
    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    metric_label = "forecast_high_c" if ev.kind == "high" else "forecast_low_c"
    return StoryBundle(
        signal_kind=f"monthly_{ev.kind}",
        where=where,
        when=date.today().isoformat(),
        event_id=ev.event_id,
        headline_metric={
            "label": metric_label,
            "value": ev.new_temp_c,
            "unit": "C",
        },
        current_facts=[
            {"label": "city", "value": ev.city},
            {"label": "country", "value": ev.country},
            {"label": "month", "value": month_name},
            {"label": "kind", "value": ev.kind},
        ],
        historical_context={
            "prior_record_c": ev.old_record_c,
            "prior_record_year": ev.old_record_year,
            "archive_years": ev.years_of_data,
            "month": month_name,
            "margin_c": round(ev.new_temp_c - ev.old_record_c, 2),
        },
        raw_signal_dump=asdict(ev),
    )


def build_country_record_bundle(cr: CountryRecord) -> StoryBundle:
    """Assemble a StoryBundle for a country-level archive-record signal."""

    return StoryBundle(
        signal_kind=f"country_{cr.kind}",
        where=cr.country,
        when=date.today().isoformat(),
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


def build_record_bundle(ev: RecordEvent) -> StoryBundle:
    """Assemble a StoryBundle for a calendar-day record signal.

    "Calendar-day record" means a city is forecast to break the previous
    record for *this specific date* (e.g. May 3). These signals fire
    routinely in temperate climates, so the editorial bar should be high
    — the writer's discipline (and the empty-margin guard) decides
    whether it ships, not the absolute temperature.
    """

    margin_c = round(ev.new_temp_c - ev.old_record_c, 2)
    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    return StoryBundle(
        signal_kind="calendar_record",
        where=where,
        when=date.today().isoformat(),
        event_id=ev.event_id,
        headline_metric={
            "label": "forecast_high_c",
            "value": ev.new_temp_c,
            "unit": "C",
        },
        current_facts=[
            {"label": "city", "value": ev.city},
            {"label": "country", "value": ev.country},
            {"label": "calendar_date", "value": date.today().isoformat()},
        ],
        historical_context={
            "prior_record_c": ev.old_record_c,
            "prior_record_year": ev.old_record_year,
            "margin_c": margin_c,
            "scope": "calendar_date_only",
        },
        raw_signal_dump=asdict(ev),
    )


def build_severe_weather_bundle(alert: SevereWeatherAlert) -> StoryBundle:
    """Assemble a StoryBundle for an NWS severe-weather alert.

    ``historical_context`` is intentionally empty: NWS alerts carry no
    archive comparison, so the writer must rely on the empty-context
    discipline already in the prompt.
    """

    return StoryBundle(
        signal_kind="severe_weather",
        where=alert.area,
        when=date.today().isoformat(),
        event_id=alert.event_id,
        headline_metric={"label": "event_type", "value": alert.event_type},
        current_facts=[
            {"label": "event_type", "value": alert.event_type},
            {"label": "area", "value": alert.area},
            {"label": "severity", "value": alert.severity},
            {"label": "max_wind_gust", "value": alert.max_wind_gust},
            {"label": "max_hail_size", "value": alert.max_hail_size},
            {"label": "tornado_detection", "value": alert.tornado_detection},
            {"label": "description", "value": alert.description},
            {"label": "sender_name", "value": alert.sender_name},
        ],
        historical_context={},
        raw_signal_dump=asdict(alert),
    )


# =====================================================================
# Open-Meteo extreme-signals types
# =====================================================================


def build_all_time_record_bundle(ev: AllTimeRecord) -> StoryBundle:
    """City broke (or is forecast to break) its archive-record temperature.

    Highest-tier temperature signal — a ``+0.5C over a 50-year archive``
    is a real headline. The writer should treat the archive span as the
    rarity peg.
    """

    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    return StoryBundle(
        signal_kind=f"open_meteo_archive_{ev.kind}",
        where=where,
        when=date.today().isoformat(),
        event_id=ev.event_id,
        headline_metric={
            "label": "forecast_high_c" if ev.kind == "high" else "forecast_low_c",
            "value": ev.new_temp_c,
            "unit": "C",
        },
        current_facts=[
            {"label": "city", "value": ev.city},
            {"label": "country", "value": ev.country},
            {"label": "kind", "value": ev.kind},
        ],
        historical_context={
            "prior_record_c": ev.old_record_c,
            "prior_record_year": ev.old_record_year,
            "archive_years": ev.years_of_data,
            "archive_start_year": date.today().year - ev.years_of_data,
            "archive_window_only": True,
            "kind": ev.kind,
            "margin_c": round(ev.new_temp_c - ev.old_record_c, 2),
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
        raw_signal_dump=asdict(ev),
    )


def build_anomaly_bundle(ev: AnomalyEvent) -> StoryBundle:
    """Today's reading is far above (or below) the historical mean."""

    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    kind = "hot" if ev.anomaly_c >= 0 else "cold"
    return StoryBundle(
        signal_kind=f"anomaly_{kind}",
        where=where,
        when=date.today().isoformat(),
        event_id=ev.event_id,
        headline_metric={
            "label": "anomaly_c",
            "value": ev.anomaly_c,
            "unit": "C",
        },
        current_facts=[
            {"label": "city", "value": ev.city},
            {"label": "country", "value": ev.country},
            {"label": "today_c", "value": ev.today_temp_c},
            {"label": "historical_mean_c", "value": ev.historical_mean_c},
        ],
        historical_context={
            "historical_mean_c": ev.historical_mean_c,
            "anomaly_c": ev.anomaly_c,
            "archive_years": ev.years_of_data,
            "scope": "monthly_baseline",
        },
        raw_signal_dump=asdict(ev),
    )


def build_record_streak_bundle(ev: RecordStreakEvent) -> StoryBundle:
    """A city has broken its daily record N consecutive days."""

    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    return StoryBundle(
        signal_kind="record_streak",
        where=where,
        when=date.today().isoformat(),
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


# =====================================================================
# Fire footprint (NIFC perimeters)
# =====================================================================


def build_fire_footprint_bundle(fc: FireComplex) -> StoryBundle:
    """A wildfire perimeter has crossed a tier threshold (acreage)."""

    where = f"{fc.region}, {fc.country}" if fc.region and fc.country else (fc.region or fc.country)
    name = fc.name or "Unnamed complex"
    tier_hectares = (
        TIERS_HECTARES[min(fc.tier, len(TIERS_HECTARES) - 1)]
        if fc.tier >= 0 and TIERS_HECTARES
        else None
    )
    return StoryBundle(
        signal_kind="fire_footprint",
        where=where or "Unknown",
        when=date.today().isoformat(),
        event_id=fc.event_id,
        headline_metric={
            "label": "burned_area_ha",
            "value": fc.hectares,
            "unit": "hectares",
        },
        current_facts=[
            {"label": "complex_name", "value": name},
            {"label": "region", "value": fc.region},
            {"label": "country", "value": fc.country},
            {"label": "hectares", "value": fc.hectares},
            {"label": "tier", "value": fc.tier},
            {"label": "tier_hectares", "value": tier_hectares, "unit": "hectares"},
            {"label": "start_date", "value": fc.start_date.isoformat() if fc.start_date else None},
        ],
        historical_context={},
        raw_signal_dump={
            "complex_id": fc.complex_id,
            "name": fc.name,
            "country": fc.country,
            "region": fc.region,
            "hectares": fc.hectares,
            "start_date": fc.start_date.isoformat() if fc.start_date else None,
            "tier": fc.tier,
            "tier_hectares": tier_hectares,
            "event_id": fc.event_id,
        },
    )


# =====================================================================
# CO2 milestones
# =====================================================================


def build_co2_milestone_bundle(milestone: CO2Milestone) -> StoryBundle:
    """Atmospheric CO2 crossed a round-number threshold."""

    return StoryBundle(
        signal_kind="co2_milestone",
        where="Mauna Loa Observatory",
        when=milestone.date,
        event_id=milestone.event_id,
        headline_metric={
            "label": "ppm",
            "value": milestone.actual_ppm,
            "unit": "ppm",
        },
        current_facts=[
            {"label": "ppm_crossed", "value": milestone.ppm_crossed},
            {"label": "actual_ppm", "value": milestone.actual_ppm},
            {"label": "measurement_date", "value": milestone.date},
        ],
        historical_context={
            "scope": "atmospheric_co2_threshold_crossed",
            "preindustrial_baseline_ppm": 280,
        },
        raw_signal_dump=asdict(milestone),
    )


# =====================================================================
# Global disasters (GDACS)
# =====================================================================


def build_global_disaster_bundle(disaster: GlobalDisasterEvent) -> StoryBundle:
    """A live-running natural disaster surfaced via GDACS."""

    return StoryBundle(
        signal_kind="global_disaster",
        where=disaster.country or "Unknown",
        when=date.today().isoformat(),
        event_id=disaster.event_id,
        headline_metric={
            "label": "severity",
            "value": disaster.severity,
        },
        current_facts=[
            {"label": "disaster_type", "value": disaster.disaster_type},
            {"label": "name", "value": disaster.name},
            {"label": "country", "value": disaster.country},
            {"label": "severity", "value": disaster.severity},
            {"label": "alert_score", "value": disaster.alert_score},
            {"label": "severity_value", "value": disaster.severity_value},
            {"label": "severity_unit", "value": disaster.severity_unit},
            {"label": "population_affected", "value": disaster.population_affected},
            {"label": "description", "value": disaster.description},
        ],
        historical_context={},
        raw_signal_dump=asdict(disaster),
    )


# =====================================================================
# Sea ice / ice mass / marine
# =====================================================================


def build_sea_ice_bundle(record: SeaIceRecord) -> StoryBundle:
    """A polar sea-ice extent reading set a new record."""

    return StoryBundle(
        signal_kind="sea_ice_record",
        where=f"{record.hemisphere} hemisphere",
        when=record.date,
        event_id=record.event_id,
        headline_metric={
            "label": "extent_million_km2",
            "value": record.extent_million_km2,
            "unit": "million_km2",
        },
        current_facts=[
            {"label": "hemisphere", "value": record.hemisphere},
            {"label": "extent_million_km2", "value": record.extent_million_km2},
            {"label": "record_type", "value": record.record_type},
            {"label": "date", "value": record.date},
        ],
        historical_context={
            "previous_extent": record.previous_extent,
            "previous_year": record.previous_year,
            "scope": f"satellite_archive_{record.record_type}",
        },
        raw_signal_dump=asdict(record),
    )


def build_ice_mass_bundle(
    record: IceMassRecord,
    *,
    years_of_record: int | None = None,
    archive_start_year: int | None = None,
) -> StoryBundle:
    """GRACE ice mass loss / cumulative milestone for a polar region."""

    return StoryBundle(
        signal_kind="ice_mass_record",
        where=record.region,
        when=date.today().isoformat(),
        event_id=record.event_id,
        headline_metric={
            "label": "monthly_delta_gt" if record.monthly_delta_gt is not None else "current_mass_gt",
            "value": record.monthly_delta_gt if record.monthly_delta_gt is not None else record.current_mass_gt,
            "unit": "Gt",
        },
        current_facts=[
            {"label": "region", "value": record.region},
            {"label": "kind", "value": record.kind},
            {"label": "month", "value": record.month},
            {"label": "monthly_delta_gt", "value": record.monthly_delta_gt},
            {"label": "current_mass_gt", "value": record.current_mass_gt},
            {"label": "years_of_record", "value": years_of_record},
        ],
        historical_context={
            "previous_worst_gt": record.previous_worst_gt,
            "previous_worst_month": record.previous_worst_month,
            "threshold_gt": record.threshold_gt,
            "years_of_record": years_of_record,
            "archive_start_year": archive_start_year,
            "scope": "grace_satellite_archive",
        },
        raw_signal_dump=asdict(record),
    )


def build_marine_heatwave_bundle(mhw: MarineHeatwaveStreakEvent) -> StoryBundle:
    """A streak milestone in the global ocean SST anomaly record."""

    return StoryBundle(
        signal_kind="marine_heatwave",
        where="Global ocean (60°S–60°N)",
        when=mhw.date,
        event_id=mhw.event_id,
        headline_metric={
            "label": "streak_days",
            "value": mhw.days,
            "unit": "days",
        },
        current_facts=[
            {"label": "kind", "value": mhw.kind},
            {"label": "streak_days", "value": mhw.days},
            {"label": "today_c", "value": mhw.today_c},
            {"label": "peak_anomaly_c", "value": mhw.peak_anomaly_c},
        ],
        historical_context={
            "archive_max_c": mhw.archive_max_c,
            "archive_max_year": mhw.archive_max_year,
            "archive_years": mhw.years_of_data,
            "scope": "noaa_oisst_global_archive",
        },
        raw_signal_dump=asdict(mhw),
    )


# =====================================================================
# Hydrology (rivers / coastal / waves)
# =====================================================================


def build_river_flood_bundle(flood: FloodEvent) -> StoryBundle:
    """A USGS river gauge crossed its flood-stage threshold."""

    return StoryBundle(
        signal_kind="river_flood",
        where=flood.location,
        when=flood.date,
        event_id=flood.event_id,
        headline_metric={
            "label": "above_flood_stage_ft",
            "value": flood.above_by_ft,
            "unit": "ft",
        },
        current_facts=[
            {"label": "river", "value": flood.river},
            {"label": "location", "value": flood.location},
            {"label": "gauge_height_ft", "value": flood.gauge_height_ft},
            {"label": "flood_stage_ft", "value": flood.flood_stage_ft},
            {"label": "above_by_ft", "value": flood.above_by_ft},
        ],
        historical_context={},
        raw_signal_dump=asdict(flood),
    )


def build_storm_surge_bundle(surge: StormSurgeEvent) -> StoryBundle:
    """A NOAA tide station observed water level far above prediction."""

    where = f"{surge.station_name}, {surge.state}" if surge.state else surge.station_name
    return StoryBundle(
        signal_kind="storm_surge",
        where=where,
        when=surge.date,
        event_id=surge.event_id,
        headline_metric={
            "label": "surge_anomaly_m",
            "value": surge.anomaly_m,
            "unit": "m",
        },
        current_facts=[
            {"label": "station_name", "value": surge.station_name},
            {"label": "state", "value": surge.state},
            {"label": "observed_m", "value": surge.observed_m},
            {"label": "predicted_m", "value": surge.predicted_m},
            {"label": "anomaly_m", "value": surge.anomaly_m},
        ],
        historical_context={},
        raw_signal_dump=asdict(surge),
    )


def build_extreme_wave_bundle(wave: ExtremeWaveEvent) -> StoryBundle:
    """Open-Meteo marine forecast shows extreme wave heights."""

    where = f"{wave.location} ({wave.ocean})" if wave.ocean else wave.location
    return StoryBundle(
        signal_kind="extreme_wave",
        where=where,
        when=wave.date,
        event_id=wave.event_id,
        headline_metric={
            "label": "wave_height_m",
            "value": wave.wave_height_m,
            "unit": "m",
        },
        current_facts=[
            {"label": "location", "value": wave.location},
            {"label": "ocean", "value": wave.ocean},
            {"label": "wave_height_m", "value": wave.wave_height_m},
        ],
        historical_context={},
        raw_signal_dump=asdict(wave),
    )


# =====================================================================
# Drought / ENSO / Synthesis (compound)
# =====================================================================


def build_drought_bundle(updates: list[dict], *, event_id: str) -> StoryBundle:
    """US Drought Monitor rolled up across affected states.

    ``updates`` is the list of state-level drought dicts main.py
    assembles from DroughtUpdate dataclasses (state, d3_pct, d4_pct,
    total_drought_pct).
    """

    def _severity(row: dict) -> float:
        return float(row.get("d3_pct") or 0) + float(row.get("d4_pct") or 0)

    worst = max(updates, key=_severity) if updates else {}
    worst_value = round(_severity(worst), 1) if worst else 0.0
    return StoryBundle(
        signal_kind="drought",
        where="United States",
        when=date.today().isoformat(),
        event_id=event_id,
        headline_metric={
            "label": "worst_extreme_exceptional_pct",
            "value": worst_value,
            "unit": "%",
        },
        current_facts=[
            {"label": "state_count", "value": len(updates)},
            {"label": "worst_state", "value": worst.get("state")},
            {"label": "worst_d3_pct", "value": worst.get("d3_pct")},
            {"label": "worst_d4_pct", "value": worst.get("d4_pct")},
            {"label": "states", "value": updates},
        ],
        historical_context={"scope": "us_drought_monitor_weekly"},
        raw_signal_dump={"states": updates, "event_id": event_id},
    )


def build_enso_bundle(transition: dict) -> StoryBundle:
    """An ENSO phase transition (or significant ONI move).

    ``transition`` is the dict main.py constructs from the latest
    two ENSO readings (status_from, status_to, oni_value, season,
    event_id).
    """

    status_from = transition.get("from_status", transition.get("status_from"))
    status_to = transition.get("to_status", transition.get("status_to"))
    return StoryBundle(
        signal_kind="enso",
        where="Equatorial Pacific (Niño 3.4)",
        when=date.today().isoformat(),
        event_id=transition.get("event_id", ""),
        headline_metric={
            "label": "oni_value",
            "value": transition.get("oni_value"),
            "unit": "C",
        },
        current_facts=[
            {"label": "season", "value": transition.get("season")},
            {"label": "status_from", "value": status_from},
            {"label": "status_to", "value": status_to},
            {"label": "oni_value", "value": transition.get("oni_value")},
            {"label": "previous_duration_months", "value": transition.get("previous_duration_months")},
        ],
        historical_context={"scope": "noaa_oni_3month_running_mean"},
        raw_signal_dump=transition,
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
        ],
        historical_context={"scope": "daily_top10_anomaly_leaderboard"},
        raw_signal_dump={"cities": cities, "changes": changes, "event_id": event_id},
    )


def build_synthesis_bundle(synthesis: dict) -> StoryBundle:
    """Cross-source compound story (e.g. fire + drought + heat in one region).

    ``synthesis`` is the dict main.py builds from the cross-source scorer
    (region, kind, components, total_score, event_id, headline).
    """

    components = synthesis.get("components") or []
    return StoryBundle(
        signal_kind=f"synthesis_{synthesis.get('kind', 'compound')}",
        where=synthesis.get("region", "Unknown"),
        when=date.today().isoformat(),
        event_id=synthesis.get("event_id", ""),
        headline_metric={
            "label": "synthesis_score",
            "value": synthesis.get("total_score"),
        },
        current_facts=[
            {"label": "region", "value": synthesis.get("region")},
            {"label": "synthesis_kind", "value": synthesis.get("kind")},
            {"label": "component_count", "value": len(components)},
            {"label": "components", "value": components},
        ],
        historical_context={
            "scope": "cross_source_synthesis",
            "synthesis_kind": synthesis.get("kind"),
        },
        raw_signal_dump=synthesis,
    )
