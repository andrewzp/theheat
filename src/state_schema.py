"""TypedDict schema for ``bot_state`` — the durable orchestrator state.

Mirrors ``src/state.DEFAULT_STATE`` exactly. New lanes add keys here first;
``_normalize_state`` in ``state.py`` backfills older gist payloads at read.
``total=False`` at the top level so older payloads (predating recent lane
additions) still type-check — the durable wire format is append-only, never
breaking.

Nested TypedDicts cover dicts with known internal shapes. Dynamic-keyed
dicts (city -> record, region -> entry, etc.) stay as ``dict[str, T]``
where ``T`` is the nested TypedDict.
"""
from __future__ import annotations

from typing import TypedDict


class Hot10Snapshot(TypedDict, total=False):
    """The most recent global Hot 10 leaderboard tweeted."""

    date: str | None
    cities: list[str]


class StreakEntry(TypedDict):
    """Hot-10 appearance streak per city."""

    consecutive_days: int
    last_seen: str


class RecordStreakEntry(TypedDict, total=False):
    """Consecutive daily-record breaks for a single city or GHCN station."""

    days: int
    start_date: str
    last_date: str
    peak_temp_c: float
    updated_at: str


class OceanSSTStreak(TypedDict, total=False):
    """Global ocean SST archive-high streak (single-row state)."""

    seeded: bool
    last_milestone_fired: int | None


class CycloneWindObservation(TypedDict, total=False):
    """Single retained tropical-cyclone intensity observation."""

    issued_at: str
    wind_kt: int


class MemoryState(TypedDict, total=False):
    """Two-bot memory layer carried across runs (see src/two_bot/memory.py)."""

    ongoing_events: list[dict]
    used_era_anchors: list[str]
    used_peer_comparisons: list[str]
    used_framings: list[str]
    shipped_tweets: list[dict]


class CoverageRecord(TypedDict):
    """Single surfaced-event geography record for the rolling coverage watch."""

    cls: str
    event_id: str
    country: str
    continent: str
    date: str


class CityRecord(TypedDict):
    """Single extreme reading for a city — all-time or per-month."""

    temp_c: float
    year: int


class IceMassLoss(TypedDict):
    """GRACE-FO worst-month mass-delta for a region (negative gt = loss)."""

    gt: float
    month: str


class PrecipRecord(TypedDict, total=False):
    """Observed precipitation record for a city/calendar-day key."""

    mm: float
    year: int
    date: str


class RecentPrecipRow(TypedDict):
    """Rolling city precipitation row used for multi-day accumulations."""

    date: str
    mm: float


class SnowRecord(TypedDict, total=False):
    """Observed SWE record for a station key."""

    mm: float
    year: int
    date: str
    years_of_archive: int


class RecentSnowRow(TypedDict):
    """Rolling station SWE-gain row used for multi-day snow events."""

    date: str
    mm: float


class DroughtSnapshot(TypedDict, total=False):
    """Latest USDM drought snapshot — entries are state-level rows."""

    updated_at: str
    entries: list[dict]


class SynthesisComponents(TypedDict, total=False):
    """Cross-source synthesis evidence: per-state fires + heats, drought.

    Inner event dicts are heterogeneous (record_synthesis_component allows
    arbitrary metadata kwargs), so the inner element type stays as a plain
    ``dict`` rather than a nested TypedDict.
    """

    fires: dict[str, list[dict]]
    heats: dict[str, list[dict]]
    corals: dict[str, list[dict]]
    sst_anomalies: dict[str, list[dict]]
    drought_snapshot: DroughtSnapshot | None


class SourceHealthRun(TypedDict, total=False):
    """Single source-health observation retained in the 7-day window."""

    ts: str
    status: str
    error: str | None
    error_class: str
    duration_ms: int
    observed: int
    promoted: int
    triaged_in: int
    triaged_out: int
    writer_attempted: int
    drafted: int


class SourceHealth(TypedDict, total=False):
    """Rolling per-source health counters and last-known problem state."""

    success: int
    degraded: int
    failed: int
    skipped: int
    total_duration_ms: int
    avg_duration_ms: int | None
    max_duration_ms: int
    total_observed: int
    total_promoted: int
    total_triaged_in: int
    total_triaged_out: int
    total_writer_attempted: int
    total_drafted: int
    last_success_ts: str | None
    last_error: str | None
    last_error_ts: str | None
    runs: list[SourceHealthRun]


class TweetMetric(TypedDict):
    """Public engagement metrics for one posted X tweet."""

    at: str
    likes: int
    retweets: int
    replies: int


class AirQualityTier(TypedDict):
    """Last successfully drafted air-quality tier for one city/date."""

    tier: int
    date: str


class CredentialExpiry(TypedDict, total=False):
    """Derived expiry for one tracked credential (the dashboard counter source).

    Holds only the derived expiry date, never the token. Recomputed each run by
    ``src.credentials.collect_credential_expiry`` so the dashboard can warn
    before a credential silently expires.
    """

    label: str
    expires_at: str  # ISO-8601 UTC, e.g. "2026-08-22T15:18:07Z"
    source: str  # how the expiry was derived (e.g. "jwt")


class BotState(TypedDict, total=False):
    """Top-level durable state for the @theheat orchestrator.

    Loaded by ``state.read_state`` from the active backend (gist or sqlite).
    Written via ``state.write_state``, which routes through ``_merge_state``
    to survive concurrent writers. All keys are NotRequired (``total=False``)
    because schema additions ship monthly and old payloads must keep loading.
    """

    last_hot10: Hot10Snapshot
    streaks: dict[str, StreakEntry]
    posted_events: list[str]
    daily_tweet_count: dict[str, int]
    co2_annual_count: dict[str, int]
    ch4_annual_count: dict[str, int]
    ch4_last_milestone: int | None
    nao_annual_count: dict[str, int]
    ao_annual_count: dict[str, int]
    pdo_annual_count: dict[str, int]
    nao_last_phase: str | None
    ao_last_phase: str | None
    pdo_last_phase: str | None
    ozone_hole_last_peak: dict[str, dict]
    ozone_hole_annual_count: dict[str, int]
    air_quality_pm25_tiers: dict[str, AirQualityTier]
    air_quality_dust_tiers: dict[str, AirQualityTier]
    drafts: list[dict]
    run_history: list[dict]
    errors: list[dict]
    suppressions: list[dict]
    memory: MemoryState
    city_all_time_max: dict[str, CityRecord]
    city_all_time_min: dict[str, CityRecord]
    city_monthly_max: dict[str, dict[str, CityRecord]]
    city_monthly_min: dict[str, dict[str, CityRecord]]
    record_streaks: dict[str, RecordStreakEntry]
    data_source_failures: dict[str, int]
    source_health: dict[str, SourceHealth]
    credential_expiry: dict[str, CredentialExpiry]
    last_good_readings: dict[str, dict]
    publish_ledger: dict[str, dict]
    tweet_metrics: dict[str, TweetMetric]
    _state_rev: int
    ocean_sst_streak: OceanSSTStreak
    ice_mass_max_loss: dict[str, IceMassLoss]
    ice_mass_last_milestone: dict[str, float]
    ice_mass_last_seen: dict[str, str]
    ice_annual_count: dict[str, int]
    precip_daily_records: dict[str, PrecipRecord]
    precip_recent_by_city: dict[str, list[RecentPrecipRow]]
    snow_daily_swe_gain_records: dict[str, SnowRecord]
    snow_recent_by_station: dict[str, list[RecentSnowRow]]
    snow_annual_count: dict[str, int]
    seasonal_snow_records: dict[str, SnowRecord]
    fire_complex_tiers: dict[str, int]
    coral_dhw_last_tier: dict[str, int]
    coral_dhw_annual_count: dict[str, int]
    sst_anom_last_tier: dict[str, int]
    sst_anom_annual_count: dict[str, int]
    reganom_last_fired: dict[str, str]
    cyclone_tiers: dict[str, int]
    cyclone_wind_history: dict[str, list[CycloneWindObservation]]
    cyclone_annual_count: dict[str, int]
    flood_activation_tiers: dict[str, str]
    tier_touch_ts: dict[str, str]
    flood_annual_count: dict[str, int]
    fire_footprint_last_run: str | None
    synthesis_components: SynthesisComponents
    synthesis_cooldown: dict[str, dict[str, str]]
    coverage_log: list[CoverageRecord]
    # Newsworthiness lane (Bet A phase 0): retrieved cited world events + the
    # rolling enqueued-candidate registry the news-gap watch matches against.
    news_events: list[dict]
    candidates_log: list[dict]
