"""Exact typed NHC application snapshots for an explicit local episode lane.

Not a raw response archive or official-authenticity warrant. Missing source
metadata remains unknown; read-back never reacquires a source product.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import re
from uuid import UUID

from src.commands.preview_ingress import safe_environment
from src.data.cyclones import CycloneAdvisory, ForecastPoint
from src.storage import postgres_projection as p

NAMESPACE = "cyclone-supply-nhc-v1"
ADVISORY_FIELDS = set("source storm_id storm_name basin advisory_number issued_at wind_kt pressure_mb lat lon classification public_advisory_url advisory_text source_leg forecast_points".split())
POINT_FIELDS = set("valid_at lat lon max_wind_kt tau_h".split())
SIDECAR_FIELDS = set("source_row_sha256 forecast_product_url forecast_issued_at_original forecast_advisory_number forecast_text_complete forecast_points_sha256".split())


class CycloneSupplyError(ValueError):
    """Bounded codes without source or connection secrets."""


def require(condition, code="invalid_cyclone_supply"):
    if not condition:
        raise CycloneSupplyError(code)


def freeze(value):
    try:
        return p._decode(p._canonical(value))
    except p.ProjectionError:
        raise CycloneSupplyError("invalid_cyclone_json") from None


def digest(value):
    return p._sha(p._canonical(value))


def sha(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    return value


def instant(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", value) is not None,
            "invalid_cyclone_time")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise CycloneSupplyError("invalid_cyclone_time") from None


def uuid(value):
    try:
        require(type(value) is str and str(UUID(value)) == value, "invalid_cyclone_identity")
    except (ValueError, AttributeError):
        raise CycloneSupplyError("invalid_cyclone_identity") from None
    return value


def environment(repository):
    try:
        safe_environment()
    except ValueError:
        raise CycloneSupplyError("unsafe_cyclone_environment") from None
    require(type(repository) is p.PostgresProjectionRepository and repository.environment in {"local", "preview"},
            "explicit_cyclone_repository_required")


def advisory_row(advisory):
    require(type(advisory) is CycloneAdvisory)
    require({f.name for f in fields(CycloneAdvisory)} == ADVISORY_FIELDS, "unsupported_cyclone_codec")
    row = asdict(advisory)
    row["forecast_points"] = [asdict(point) for point in advisory.forecast_points]
    decode_advisory(row)
    return freeze(row)


def decode_advisory(row):
    require(type(row) is dict and set(row) == ADVISORY_FIELDS)
    for key in ADVISORY_FIELDS - {"wind_kt", "pressure_mb", "lat", "lon", "source_leg", "forecast_points"}:
        require(type(row[key]) is str and len(row[key]) <= (8000 if key == "advisory_text" else 2048))
    require(type(row["wind_kt"]) is int and 0 <= row["wind_kt"] <= 1000)
    require(row["pressure_mb"] is None or (type(row["pressure_mb"]) is int and 0 < row["pressure_mb"] <= 2000))
    require(row["source_leg"] is None or (type(row["source_leg"]) is str and len(row["source_leg"]) <= 160))
    instant(row["issued_at"])
    for key, bound in (("lat", 90), ("lon", 180)):
        require(row[key] is None or (type(row[key]) in {int, float} and -bound <= row[key] <= bound))
    require(type(row["forecast_points"]) is list and len(row["forecast_points"]) <= 128)
    require({f.name for f in fields(ForecastPoint)} == POINT_FIELDS, "unsupported_cyclone_codec")
    points = []
    for point in row["forecast_points"]:
        require(type(point) is dict and set(point) == POINT_FIELDS)
        require(type(point["valid_at"]) is str and len(point["valid_at"]) <= 80)
        for key, bound in (("lat", 90), ("lon", 180)):
            require(type(point[key]) in {int, float} and -bound <= point[key] <= bound)
        for key in ("max_wind_kt", "tau_h"):
            require(point[key] is None or (type(point[key]) is int and 0 <= point[key] <= 1000))
        points.append(ForecastPoint(**point))
    freeze(row)
    return CycloneAdvisory(**{**row, "forecast_points": tuple(points)})


def sidecar(value, row):
    if value is None:
        value = dict.fromkeys(SIDECAR_FIELDS)
    require(type(value) is dict and set(value) == SIDECAR_FIELDS)
    for key in ("source_row_sha256", "forecast_points_sha256"):
        if value[key] is not None:
            sha(value[key])
    if value["forecast_points_sha256"] is not None:
        require(value["forecast_points_sha256"] == digest(row["forecast_points"]), "forecast_points_mismatch")
    if value["forecast_issued_at_original"] is not None:
        instant(value["forecast_issued_at_original"])
    require(value["forecast_text_complete"] is None or type(value["forecast_text_complete"]) is bool)
    for key in ("forecast_advisory_number", "forecast_product_url"):
        require(value[key] is None or (type(value[key]) is str and 0 < len(value[key]) <= 2048))
    if value["forecast_product_url"] is not None:
        from src.data.nhc import _normalize_url
        require(_normalize_url(value["forecast_product_url"]) == value["forecast_product_url"], "invalid_forecast_product_url")
    if value["forecast_advisory_number"] is not None:
        require(re.fullmatch(r"[0-9]+[A-Za-z]?", value["forecast_advisory_number"]) is not None)
    return freeze(value)


def assertion_key(row):
    return digest({key: row[key] for key in ("source", "storm_id", "advisory_number", "issued_at")} | {"product": "current-storm"})


@dataclass(frozen=True)
class CycloneSupplySession:
    repository: p.PostgresProjectionRepository
    supply_run_id: str
    captured_at: str | None = None
    producer_revision: str | None = None

    def capture(self, advisories, source_outcome, *, observations=None):
        environment(self.repository)
        uuid(self.supply_run_id)
        instant(self.captured_at)
        require(type(self.producer_revision) is str and re.fullmatch(r"[0-9a-f]{40}", self.producer_revision) is not None)
        require(type(advisories) is list)
        observed: dict = {}
        for advisory, metadata in observations or []:
            key = digest(advisory_row(advisory))
            require(key not in observed or observed[key] == metadata, "source_observer_conflict")
            observed[key] = metadata
        rows = []
        for advisory in advisories:
            row = advisory_row(advisory)
            rows.append({"advisory": row, "metadata": sidecar(observed.get(digest(row)), row)})
        require(len({digest(row) for row in rows}) == len(rows), "duplicate_source_row")
        value = freeze(dict(schema_version=1, source="nhc", supply_run_id=self.supply_run_id,
            captured_at=self.captured_at, producer_revision=self.producer_revision,
            evidence_class="typed_application_snapshot", raw_response_available=False,
            source_outcome=source_outcome, rows=rows))
        validate_envelope(value, self.supply_run_id)
        try:
            self.repository.record(NAMESPACE, "run:"+self.supply_run_id, value)
        except p.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise CycloneSupplyError("cyclone_supply_write_refused") from None
        # One exact read reconciles an unknown commit; no repeat write/acquisition.
        return self.read(expected_sha=digest(value))

    def read(self, *, expected_sha=None):
        environment(self.repository)
        uuid(self.supply_run_id)
        try:
            receipt, value = self.repository.read(NAMESPACE, "run:"+self.supply_run_id)
        except p.ProjectionError:
            raise CycloneSupplyError("cyclone_supply_unavailable") from None
        validate_envelope(value, self.supply_run_id)
        require(expected_sha is None or receipt.canonical_sha256 == sha(expected_sha), "cyclone_supply_changed")
        return receipt, [decode_advisory(row["advisory"]) for row in value["rows"]], value


def validate_envelope(value, run_id):
    require(type(value) is dict and set(value) == set("schema_version source supply_run_id captured_at producer_revision evidence_class raw_response_available source_outcome rows".split()))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "unsupported_cyclone_codec")
    require(value["source"] == "nhc" and value["supply_run_id"] == run_id)
    uuid(run_id)
    instant(value["captured_at"])
    require(type(value["producer_revision"]) is str and re.fullmatch(r"[0-9a-f]{40}", value["producer_revision"]) is not None)
    require(value["evidence_class"] == "typed_application_snapshot" and value["raw_response_available"] is False)
    require(type(value["source_outcome"]) is dict and set(value["source_outcome"]) == {"status"})
    require(value["source_outcome"]["status"] in {"success", "degraded", "failed"})
    require(type(value["rows"]) is list)
    for item in value["rows"]:
        require(type(item) is dict and set(item) == {"advisory", "metadata"})
        decode_advisory(item["advisory"])
        sidecar(item["metadata"], item["advisory"])
    require(len({digest(row) for row in value["rows"]}) == len(value["rows"]), "duplicate_source_row")
