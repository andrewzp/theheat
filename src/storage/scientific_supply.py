"""Typed GHCN supply in the existing local/preview immutable PG repository.

No source acquisition, latest pointer, authority selection or source-health writes.
Capture identities and timestamps are fixed by the caller before acquisition.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
import hashlib
import re
import types
from typing import cast, get_args, get_origin, get_type_hints
from uuid import UUID

from src.commands.preview_ingress import safe_environment
from src.data import open_meteo as model
from src.storage import postgres_projection as projection

NAMESPACE = "scientific-supply-ghcn-v1"
SCHEMA_VERSION = 1
COUNTERS = (
    "stations_active", "stations_with_obs", "station_obs_pairs", "stations_checked",
    "raw_signals", "scientific_signal_bundles", "bundles_after_dedup", "country_records",
    "diff_dates_attempted", "diff_dates_fetched", "diff_dates_missing", "diff_fetch_failed",
    "archive_verification_attempted", "archive_verification_verified",
    "archive_verification_exhausted", "archive_verification_failed", "baseline_cutoff_gaps",
    "tracked_stations_unscanned", "material_revisions", "affected_claims",
)
_COMMON = "city country kind new_temp_c old_record_c old_record_year event_id signal_date state lat lon evidence"
FIELD_NAMES = {
    model.RecordEvent: set(_COMMON.split()),
    model.AllTimeRecord: set((_COMMON + " years_of_data").split()),
    model.MonthlyRecord: set((_COMMON + " years_of_data month").split()),
    model.AnomalyEvent: set("city country today_temp_c historical_mean_c anomaly_c years_of_data event_id signal_date state lat lon evidence".split()),
    model.AbsoluteExtremeEvent: set("city country today_temp_c band_label threshold_c kind lat lon event_id signal_date state data_source evidence".split()),
    model.WetBulbEvent: set("city country daily_max_tw_c tier tier_label tier_threshold_c event_id signal_date lat lon archive_max_tw_c archive_max_year archive_years evidence".split()),
    model.CountryRecord: set("country kind new_temp_c peak_city old_record_c old_record_year old_record_city years_of_data cities_sampled event_id signal_date eligible cached forecast_read evidence".split()),
}
SIGNALS = {
    "calendar_date_high": model.RecordEvent, "calendar_date_low": model.RecordEvent,
    "all_time_high": model.AllTimeRecord, "all_time_low": model.AllTimeRecord,
    "monthly_high": model.MonthlyRecord, "monthly_low": model.MonthlyRecord,
    "anomaly_hot": model.AnomalyEvent, "anomaly_cold": model.AnomalyEvent,
    "absolute_extreme": model.AbsoluteExtremeEvent, "wet_bulb_extreme": model.WetBulbEvent,
}
BUNDLE_SCALARS = set("city country today_max_c today_min_c archive_max_c archive_max_year archive_min_c archive_min_year signal_date station_id station_name lat lon evidence".split())
FIELD_NAMES[model.ExtremeSignalBundle] = BUNDLE_SCALARS | set(SIGNALS)
ENVELOPE_KEYS = set("schema_version source supply_run_id captured_at orchestrator_run_id producer_contract source_outcome bundles country_records".split())


class SupplyError(ValueError):
    """Bounded codes only; no raw state, provider or database exception text."""


def require(condition, code="invalid_scientific_supply"):
    if not condition:
        raise SupplyError(code)


def detached_json(value):
    """Reuse the repository's bounded exact JSON contract, including numeric types."""
    try:
        return projection._decode(projection._canonical(value))
    except projection.ProjectionError:
        raise SupplyError("invalid_supply_json") from None


def _day(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None)
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise SupplyError("invalid_supply_date") from None
    require(result.isoformat() == value)
    return result


def _scalar(value, annotation, *, decoding):
    if get_origin(annotation) is types.UnionType:
        options = get_args(annotation)
        if value is None and type(None) in options:
            return None
        annotation = next(item for item in options if item is not type(None))
    if annotation is date:
        if decoding:
            return _day(value)
        require(type(value) is date)
        return value.isoformat()
    if annotation is float:
        require(type(value) in {int, float})
    elif annotation is dict:
        require(type(value) is dict)
    else:
        require(annotation in {str, int, bool} and type(value) is annotation)
    return detached_json(value)


def _row(value, cls, *, decoding):
    names = FIELD_NAMES[cls]
    require({field.name for field in fields(cls)} == names, "unsupported_supply_codec")
    require(type(value) is dict if decoding else type(value) is cls)
    raw = value if decoding else vars(value)
    require(set(raw) == names)
    annotations = get_type_hints(cls)
    result: dict = {}
    for key in names:
        if cls is model.ExtremeSignalBundle and key in SIGNALS:
            child = raw[key]
            if child is None:
                result[key] = None
            elif decoding:
                require(type(child) is dict and set(child) == {"type", "fields"})
                require(child["type"] == SIGNALS[key].__name__)
                result[key] = _row(child["fields"], SIGNALS[key], decoding=True)
            else:
                result[key] = {"type": SIGNALS[key].__name__, "fields": _row(child, SIGNALS[key], decoding=False)}
        else:
            result[key] = _scalar(raw[key], annotations[key], decoding=decoding)
    return cls(**result) if decoding else result


def _unique(bundles, countries):
    keys = [(b.station_id, b.signal_date) for b in bundles]
    require(len(keys) == len(set(keys)), "duplicate_supply_identity")
    for bundle in bundles:
        require(bool(re.fullmatch(r"[A-Z0-9]{11}", bundle.station_id)), "invalid_station_identity")
        events = [getattr(bundle, key) for key in SIGNALS if getattr(bundle, key) is not None]
        identities = [(type(event).__name__, event.event_id) for event in events]
        require(len(identities) == len(set(identities)), "duplicate_supply_identity")
    country_keys = [(c.country, c.kind, c.signal_date, c.event_id) for c in countries]
    require(len(country_keys) == len(set(country_keys)), "duplicate_supply_identity")


def _outcome(metrics):
    require(type(metrics) is dict)
    status, verification = metrics.get("status"), metrics.get("threshold_verification")
    require(status in {"success", "degraded", "failed"})
    require(verification in {"success", "failure", "skipped", "cancelled", "unknown"})
    error = metrics.get("error")
    require(error in {None, "threshold_baseline_unavailable", "ghcn_fetch_failed"})
    counters = {key: metrics.get(key) for key in COUNTERS}
    require(all(value is None or (type(value) is int and value >= 0) for value in counters.values()))
    missing = metrics.get("diff_missing_dates")
    require(missing is None or type(missing) is list)
    if missing is not None:
        for day in missing:
            _day(day)
    return {"status": status, "threshold_verification": verification, "error": error,
            "counters": counters, "diff_missing_dates": detached_json(missing)}


@dataclass(frozen=True)
class ScientificSupplySession:
    repository: projection.PostgresProjectionRepository
    supply_run_id: str
    mode: str
    captured_at: str | None = None
    producer_revision: str | None = None

    def validate(self, *, mode: str):
        # Before DB/source/state access, and on every operation (not only init).
        try:
            safe_environment()
        except ValueError:
            raise SupplyError("unsafe_supply_environment") from None
        require(type(self.repository) is projection.PostgresProjectionRepository,
                "explicit_projection_repository_required")
        require(self.repository.environment in {"local", "preview"}, "production_supply_refused")
        require(self.mode == mode and mode in {"capture", "replay"}, "invalid_supply_mode")
        try:
            require(type(self.supply_run_id) is str and str(UUID(self.supply_run_id)) == self.supply_run_id,
                    "invalid_supply_run_id")
        except (ValueError, AttributeError):
            raise SupplyError("invalid_supply_run_id") from None
        if mode == "capture":
            require(type(self.producer_revision) is str and re.fullmatch(r"[0-9a-f]{40}", self.producer_revision) is not None,
                    "invalid_producer_revision")
            require(type(self.captured_at) is str and len(self.captured_at) <= 40, "invalid_capture_time")
            try:
                instant = datetime.fromisoformat(cast(str, self.captured_at).replace("Z", "+00:00"))
                require(instant.tzinfo is not None and instant.utcoffset() == timezone.utc.utcoffset(instant),
                        "invalid_capture_time")
            except ValueError:
                raise SupplyError("invalid_capture_time") from None

    @property
    def snapshot_id(self):
        return "run:" + self.supply_run_id

    def capture(self, bundles, countries, metrics, *, orchestrator_run_id=None):
        self.validate(mode="capture")
        require(orchestrator_run_id is None or (type(orchestrator_run_id) is str and 0 < len(orchestrator_run_id) <= 160))
        require(type(bundles) is list and type(countries) is list)
        bundle_rows = [_row(bundle, model.ExtremeSignalBundle, decoding=False) for bundle in bundles]
        country_rows = [_row(row, model.CountryRecord, decoding=False) for row in countries]
        _unique(bundles, countries)
        outcome = _outcome(metrics) | {"supply_empty": not bundles}
        envelope = {"schema_version": SCHEMA_VERSION, "source": "ghcn-daily",
                    "supply_run_id": self.supply_run_id, "captured_at": self.captured_at,
                    "orchestrator_run_id": orchestrator_run_id,
                    "producer_contract": {"codec": "ghcn-supply-v1", "git_commit": self.producer_revision},
                    "source_outcome": outcome,
                    "bundles": bundle_rows, "country_records": country_rows}
        envelope = detached_json(envelope)
        expected = hashlib.sha256(projection._canonical(envelope)).hexdigest()
        unknown = False
        try:
            self.repository.record(NAMESPACE, self.snapshot_id, envelope)
        except projection.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise SupplyError("supply_storage_conflict_or_unavailable") from None
            unknown = True
        # Exactly one read, including uncertain COMMIT. Never refetch or rewrite.
        try:
            result = self.read()
        except SupplyError:
            if unknown:
                raise SupplyError("supply_write_outcome_unknown") from None
            raise
        require(result[0].canonical_sha256 == expected, "supply_identity_conflict")
        return result

    def read(self):
        self.validate(mode=self.mode)
        try:
            receipt, value = self.repository.read(NAMESPACE, self.snapshot_id)
        except projection.ProjectionError:
            raise SupplyError("supply_storage_unavailable") from None
        require(type(value) is dict and set(value) == ENVELOPE_KEYS)
        require(type(value["schema_version"]) is int and value["schema_version"] == 1, "unsupported_supply_codec")
        require(value["source"] == "ghcn-daily" and value["supply_run_id"] == self.supply_run_id)
        contract = value["producer_contract"]
        require(type(contract) is dict and set(contract) == {"codec", "git_commit"})
        require(contract["codec"] == "ghcn-supply-v1")
        ScientificSupplySession(self.repository, self.supply_run_id, "capture", value["captured_at"], contract["git_commit"]).validate(mode="capture")
        run_id = value["orchestrator_run_id"]
        require(run_id is None or (type(run_id) is str and 0 < len(run_id) <= 160))
        outcome = value["source_outcome"]
        require(type(outcome) is dict and set(outcome) == {"status", "threshold_verification", "error", "counters", "diff_missing_dates", "supply_empty"})
        require(type(outcome["counters"]) is dict and set(outcome["counters"]) == set(COUNTERS))
        require(type(outcome["supply_empty"]) is bool)
        _outcome({**outcome["counters"], **outcome})
        require(type(value["bundles"]) is list and type(value["country_records"]) is list)
        bundles = [_row(row, model.ExtremeSignalBundle, decoding=True) for row in value["bundles"]]
        countries = [_row(row, model.CountryRecord, decoding=True) for row in value["country_records"]]
        require(outcome["supply_empty"] == (not bundles))
        _unique(bundles, countries)
        require(receipt.canonical_sha256 == hashlib.sha256(projection._canonical(value)).hexdigest(), "supply_identity_conflict")
        return receipt, bundles, countries, value
