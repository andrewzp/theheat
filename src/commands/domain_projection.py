"""Versioned read-only domain inspection, with original owners and opaque artifacts.

This is a view, never a ledger, importer, source qualifier or publication gate.
Explicit external packets attest only to caller-supplied artifact integrity.
"""
from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, ValidationError

from src.commands.schema import utc_datetime
from src.storage import postgres_projection as pg

MAX_RECORDS = 128
MAX_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_OBJECTS = 10000
Json: TypeAlias = None | bool | int | float | str | list['Json'] | dict[str, 'Json']
Number: TypeAlias = StrictInt | StrictFloat


class DomainProjectionError(ValueError):
    """Bounded diagnostics, without raw evidence or local paths."""


def require(ok: bool, code: str = "unsupported_domain_shape") -> None:
    if not ok:
        raise DomainProjectionError(code)


class Closed(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


class OwnerRef(Closed):
    owner: str = Field(min_length=1, max_length=200)
    namespace: str = Field(min_length=1, max_length=200)
    record_id: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(default="", max_length=2000)


class OwnerPacket(Closed):
    schema_version: Literal[1]
    owner: str = Field(min_length=1, max_length=200)
    namespace: str = Field(min_length=1, max_length=200)
    record_id: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_base64: str = Field(max_length=4 * ((MAX_BYTES + 2) // 3))


class TimeValue(Closed):
    kind: Literal["instant", "source_calendar_date", "interval", "unknown"]
    original: str | None = None
    start: str | None = None
    end: str | None = None
    timezone: str | None = None


class Place(Closed):
    kind: Literal["place"] = "place"
    place_id: str
    sampling_point_id: str
    country_code: str
    city: str
    lat: Number
    lon: Number


class SourceRun(Closed):
    kind: Literal["source_run"] = "source_run"
    source: str
    run_id: str
    captured_at: TimeValue
    outcome: Literal["success", "degraded", "failed"]
    product: str
    evidence_class: str


class Observation(Closed):
    kind: Literal["observation"] = "observation"
    subject_id: str
    variable: str
    value: Number
    unit: str
    product: str
    evidence_class: str
    time: TimeValue
    interval: TimeValue
    place_id: str | None = None


class BaselineRevision(Closed):
    kind: Literal["baseline_revision"] = "baseline_revision"
    database_sha256: str
    manifest_sha256: str
    stations_sha256: str
    threshold_rows_sha256: str
    provenance_sha256: str
    scope: Literal["retained_threshold_database_not_certified_record"]


class PhysicalEventRevision(Closed):
    kind: Literal["physical_event_revision"] = "physical_event_revision"
    episode_id: str
    sequence: StrictInt
    previous_sha256: str | None
    state: Literal["confirmed_source_identity", "held"]
    observed_at: TimeValue
    policy: str


class ClaimRevision(Closed):
    kind: Literal["claim_revision"] = "claim_revision"
    claim_id: str
    claim_type: str
    assertion_class: Literal["threshold", "available_sample_comparator", "reported_impact", "forecast", "warning", "source_reported_observation", "physical_episode_opportunity", "source_assertion"]
    evidence_class: str
    scope: str
    time: TimeValue
    value: Number | None = None
    unit: str | None = None


class DraftRevision(Closed):
    kind: Literal["draft_revision"] = "draft_revision"
    entity_id: str
    legacy_id: str
    revision_id: str
    content_revision: StrictInt
    text_sha256: str
    evidence_sha256: str


class Review(Closed):
    kind: Literal["review"] = "review"
    review_id: str
    job_id: str
    receipt_id: str
    fence: StrictInt
    recorded_at: TimeValue
    review_class: Literal["retained_machine_result_review"]


class CheckExecution(Closed):
    kind: Literal["check_execution"] = "check_execution"
    check_set_id: str
    grant_id: str | None
    job_id: str
    stage: str
    request_sha256: str | None
    observation_sha256: str | None
    receipt_sha256: str | None
    disposition: Literal["pending", "unresolved", "passed", "rejected", "error", "unavailable", "stale"]


class Job(Closed):
    kind: Literal["job"] = "job"
    job_id: str
    plan_sha256: str
    intent_id: str
    registered_at: TimeValue
    useful_until: TimeValue


Core: TypeAlias = Place | SourceRun | Observation | BaselineRevision | PhysicalEventRevision | ClaimRevision | DraftRevision | Review | CheckExecution | Job


class Relationship(Closed):
    role: str
    target: OwnerRef
    disposition: Literal["present_in_inspection", "missing", "conflicting", "opaque"]
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Extension(Closed):
    namespace: str
    schema_version: StrictInt
    supported_projection: str | None
    artifact: OwnerRef
    # Values remain in the exact artifact, never merged into reserved core fields.
    disposition: Literal["retained_source_specific", "opaque_unverified"]


class DomainObject(Closed):
    schema_version: Literal[1] = 1
    reference: OwnerRef
    core: Core = Field(discriminator="kind")
    extensions: tuple[Extension, ...]
    relationships: tuple[Relationship, ...] = ()
    qualification: Literal["unverified"] = "unverified"
    publication_authorized: Literal[False] = False
    disposition: Literal["projected_unverified", "conflicting_identity"] = "projected_unverified"


@dataclass(frozen=True)
class Record:
    reference: OwnerRef
    raw: bytes
    provenance: Literal["local_journal_read", "caller_supplied_integrity_only"]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs: list[tuple[str, Json]]) -> dict[str, Json]:
    result: dict[str, Json] = {}
    for key, value in pairs:
        require(key not in result, "ambiguous_domain_json")
        result[key] = value
    return result


def decode(raw: bytes) -> dict:
    require(type(raw) is bytes and len(raw) <= MAX_BYTES, "domain_artifact_bound")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        require(type(value) is dict)
        # Bound depth/nodes and reject nonfinite values, unsafe integer codecs,
        # surrogate strings and Python bool-as-number coercions before projection.
        pg._canonical(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise DomainProjectionError("invalid_domain_json") from None


def projection_packet(receipt: pg.ProjectionReceipt, value: dict, *, owner: str) -> dict:
    """Export an explicitly obtained owner read; never open any repository here.

    The receiving file does not prove that this function or an owner was used.
    PG canonical application bytes are not original provider response bytes.
    """
    raw = pg._canonical(value)
    require(digest(raw) == receipt.canonical_sha256, "domain_export_hash_mismatch")
    return OwnerPacket(schema_version=1, owner=owner, namespace=receipt.namespace,
        record_id=receipt.snapshot_id, sha256=receipt.canonical_sha256,
        payload_base64=base64.b64encode(raw).decode("ascii")).model_dump()


def read_packets(paths: Sequence[str]) -> tuple[Record, ...]:
    require(len(paths) <= MAX_RECORDS, "domain_record_count_bound")
    records = []
    total = 0
    for path in paths:
        # Read at most one bounded envelope; stat alone has a growth race.
        with Path(path).open("rb") as stream:
            encoded = stream.read(2 * MAX_BYTES + 1)
        total += len(encoded)
        require(len(encoded) <= 2 * MAX_BYTES and total <= MAX_TOTAL_BYTES, "domain_input_byte_bound")
        try:
            envelope = decode_envelope(encoded)
            require(type(envelope.get("schema_version")) is int)
            packet = OwnerPacket.model_validate(envelope)
            raw = base64.b64decode(packet.payload_base64, validate=True)
            require(len(raw) <= MAX_BYTES and digest(raw) == packet.sha256, "domain_artifact_hash_mismatch")
            records.append(Record(OwnerRef(owner=packet.owner, namespace=packet.namespace,
                record_id=packet.record_id, sha256=packet.sha256), raw, "caller_supplied_integrity_only"))
        except (ValidationError, ValueError, UnicodeError):
            raise DomainProjectionError("invalid_domain_record_envelope") from None
    return tuple(records)


def decode_envelope(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        require(type(value) is dict)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise DomainProjectionError("invalid_domain_record_envelope") from None


def _ref(record: Record, locator: str = "") -> OwnerRef:
    return record.reference.model_copy(update={"locator": locator})


def _instant(value: str | None) -> TimeValue:
    if value is None:
        return TimeValue(kind="unknown")
    require(type(value) is str)
    utc_datetime(value)
    return TimeValue(kind="instant", original=value, timezone="UTC")


def _calendar(value: str) -> TimeValue:
    require(type(value) is str and date.fromisoformat(value).isoformat() == value)
    return TimeValue(kind="source_calendar_date", original=value)


def _fixed(value: dict, keys: str) -> None:
    require(type(value) is dict and set(value) == set(keys.split()))


def _sha(value: str) -> str:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    return value


def _object(record: Record, locator: str, core: Core, targets: Sequence[tuple[str, OwnerRef]] = ()) -> DomainObject:
    return DomainObject(reference=_ref(record, locator), core=core,
        extensions=(Extension(namespace=record.reference.namespace, schema_version=1,
            supported_projection=core.kind, artifact=_ref(record, locator), disposition="retained_source_specific"),),
        relationships=tuple(Relationship(role=role, target=target, disposition="missing") for role, target in targets))


def _ghcn(record: Record, value: dict) -> list[DomainObject]:
    from src.data import open_meteo as model
    from src.data.ghcn import GHCN_SOURCE_PRODUCT
    from src.storage import scientific_supply as supply
    _fixed(value, "schema_version source supply_run_id captured_at orchestrator_run_id producer_contract source_outcome bundles country_records")
    require(value["source"] == "ghcn-daily" and str(UUID(value["supply_run_id"])) == value["supply_run_id"])
    require(record.reference.record_id == "run:" + value["supply_run_id"])
    _fixed(value["producer_contract"], "codec git_commit")
    require(value["producer_contract"]["codec"] == "ghcn-supply-v1")
    require(re.fullmatch(r"[0-9a-f]{40}", value["producer_contract"]["git_commit"]) is not None)
    outcome = value["source_outcome"]
    _fixed(outcome, "status threshold_verification error counters diff_missing_dates supply_empty")
    require(type(outcome["supply_empty"]) is bool and outcome["supply_empty"] == (not value["bundles"]))
    require(set(outcome["counters"]) == set(supply.COUNTERS))
    supply._outcome({**outcome["counters"], **outcome})
    bundles = [supply._row(row, model.ExtremeSignalBundle, decoding=True) for row in value["bundles"]]
    countries = [supply._row(row, model.CountryRecord, decoding=True) for row in value["country_records"]]
    supply._unique(bundles, countries)
    objects = [_object(record, "", SourceRun(source="ghcn-daily", run_id=value["supply_run_id"],
        captured_at=_instant(value["captured_at"]), outcome=outcome["status"], product=GHCN_SOURCE_PRODUCT,
        evidence_class="typed_application_snapshot"))]
    for index, row in enumerate(value["bundles"]):
        locator = f"/bundles/{index}"
        interval = row["evidence"]
        require(interval.get("evidence_type") == "observed" and interval.get("source_product") == GHCN_SOURCE_PRODUCT
            and interval.get("unit") == "C" and interval.get("station_id") == row["station_id"]
            and interval.get("valid_date") == row["signal_date"])
        start, end = interval.get("valid_start"), interval.get("valid_end")
        known = interval.get("reporting_interval_known") is True
        require(not known or (type(start) is str and type(end) is str))
        time = TimeValue(kind="interval", start=start, end=end, timezone="UTC") if known else TimeValue(kind="unknown")
        if known:
            _instant(start)
            _instant(end)
        for variable, field in (("TMAX", "today_max_c"), ("TMIN", "today_min_c")):
            if row[field] is not None:
                objects.append(_object(record, locator + "/" + field, Observation(subject_id=row["station_id"],
                    variable=variable, value=row[field], unit=interval["unit"], product=interval["source_product"], evidence_class=interval["evidence_type"],
                    time=_calendar(row["signal_date"]), interval=time), [("source_run", _ref(record))]))
        for signal in supply.SIGNALS:
            child = row[signal]
            if child is not None:
                fields = child["fields"]
                baseline = fields["evidence"].get("baseline", {})
                metric = fields.get("new_temp_c", fields.get("today_temp_c", fields.get("daily_max_tw_c")))
                objects.append(_object(record, locator + "/" + signal, ClaimRevision(claim_id=fields["event_id"],
                    claim_type=signal, assertion_class="threshold" if signal in {"absolute_extreme", "wet_bulb_extreme"} else "available_sample_comparator",
                    evidence_class="source_asserted_observed", scope=baseline.get("comparison_scope", "unspecified"),
                    time=_calendar(row["signal_date"]), value=metric, unit=interval["unit"]), [("observation", _ref(record, locator + ("/today_min_c" if signal.endswith("low") or signal == "anomaly_cold" else "/today_max_c")))]))
    for index, row in enumerate(value["country_records"]):
        objects.append(_object(record, f"/country_records/{index}", ClaimRevision(claim_id=row["event_id"],
            claim_type=row["kind"], assertion_class="available_sample_comparator", evidence_class="source_assertion", scope="country_record_assertion_not_certification",
            time=_calendar(row["signal_date"]), value=row["new_temp_c"], unit="C"), [("source_run", _ref(record))]))
    return objects


def _cyclone(record: Record, value: dict) -> list[DomainObject]:
    from src.storage import cyclone_supply as supply
    supply.validate_envelope(value, value["supply_run_id"])
    require(record.reference.record_id == "run:" + value["supply_run_id"])
    objects = [_object(record, "", SourceRun(source="nhc", run_id=value["supply_run_id"],
        captured_at=_instant(value["captured_at"]), outcome=value["source_outcome"]["status"],
        product="nhc-advisory", evidence_class=value["evidence_class"]))]
    for index, item in enumerate(value["rows"]):
        row = item["advisory"]
        objects.append(_object(record, f"/rows/{index}", Observation(subject_id=row["storm_id"], variable="wind_kt",
            value=row["wind_kt"], unit="kt", product="nhc-advisory", evidence_class="source_reported_observation",
            time=_instant(row["issued_at"]), interval=TimeValue(kind="unknown")), [("source_run", _ref(record))]))
    return objects


def _physical(record: Record, value: dict) -> list[DomainObject]:
    from src.storage import physical_events as events
    events.PhysicalEpisodeSession._revision(value, value["episode_id"])
    require(record.reference.record_id == events._prefix(value["episode_id"]) + f'{value["sequence"]:010d}')
    targets = [("source_run", OwnerRef(owner="src.storage.cyclone_supply", namespace="cyclone-supply-nhc-v1",
        record_id="run:" + row["run_id"], sha256=row["run_sha256"])) for row in value["members"]]
    if value["previous_sha256"] is not None:
        targets.append(("previous_revision", OwnerRef(owner=record.reference.owner, namespace=record.reference.namespace,
            record_id=events._prefix(value["episode_id"]) + f'{value["sequence"] - 1:010d}', sha256=value["previous_sha256"])))
    objects = [_object(record, "", PhysicalEventRevision(episode_id=value["episode_id"], sequence=value["sequence"],
        previous_sha256=value["previous_sha256"], state=value["state"], observed_at=_instant(value["observed_at"]),
        policy=value["policy"]), targets)]
    members = tuple(Relationship(role="source_assertion", target=targets[index][1], disposition="missing",
        content_sha256=_sha(member["content_sha256"]), source_identity_sha256=_sha(member["assertion_key"]))
        for index, member in enumerate(value["members"]))
    objects[0] = objects[0].model_copy(update={"relationships": objects[0].relationships + members})
    for index, row in enumerate(value["opportunities"]):
        require(type(row) is dict and set(row) == {"opportunity_id", "claim", "event_type", "event"})
        require(row["opportunity_id"] == events.digest(dict(episode_id=value["episode_id"], claim=row["claim"])))
        objects.append(_object(record, f"/opportunities/{index}", ClaimRevision(claim_id=_sha(row["opportunity_id"]),
            claim_type=row["event_type"], assertion_class="physical_episode_opportunity", evidence_class="source_scoped_derivation", scope="physical_episode_opportunity",
            time=_instant(value["observed_at"])), [("physical_event_revision", _ref(record))]))
    return objects


def _baseline(record: Record, value: dict) -> list[DomainObject]:
    _fixed(value, "schema_version source supply_run_id producer_revision dependency_sha256 baseline supply_sha256 acquisition_started_at acquisition_completed_at duration_ms source_now responses effects effects_sha256 evidence_class")
    require(value["source"] == "ghcn-daily" and value["evidence_class"] == "invented_local_capture")
    require(record.reference.record_id == "run:" + str(UUID(value["supply_run_id"])))
    baseline = value["baseline"]
    _fixed(baseline, "database_sha256 manifest_sha256 stations_sha256 threshold_rows_sha256 provenance_sha256 stats")
    core = BaselineRevision(database_sha256=_sha(baseline["database_sha256"]), manifest_sha256=_sha(baseline["manifest_sha256"]),
        stations_sha256=_sha(baseline["stations_sha256"]), threshold_rows_sha256=_sha(baseline["threshold_rows_sha256"]),
        provenance_sha256=_sha(baseline["provenance_sha256"]),
        scope="retained_threshold_database_not_certified_record")
    target = OwnerRef(owner="src.storage.scientific_supply", namespace="scientific-supply-ghcn-v1",
        record_id="run:" + value["supply_run_id"], sha256=_sha(value["supply_sha256"]))
    dependency = OwnerRef(owner="src.storage.ghcn_runtime_inputs", namespace="ghcn-runtime-dependencies-v1",
        record_id="run:" + value["supply_run_id"], sha256=_sha(value["dependency_sha256"]))
    return [_object(record, "/baseline", core, [("source_run", target), ("runtime_dependencies", dependency)])]


def _reports(record: Record, value: dict) -> list[DomainObject]:
    from src.storage import retained_reports as reports
    _fixed(value, "sequence document")
    require(type(value["sequence"]) is int and 1 <= value["sequence"] <= reports.MAX_REVISIONS)
    document = value["document"]
    _fixed(document, "schema_version lineage_id previous_report_sha256 publisher source_url hazards original_language artifact_refs upstream_lineage_refs claims limits captured_at reference_review legacy_metadata")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1)
    require(record.reference.record_id == reports.RetainedReportSession._prefix(document["lineage_id"]) + f'{value["sequence"]:010d}')
    require(type(document["claims"]) is list and 1 <= len(document["claims"]) <= reports.MAX_REVISIONS)
    objects = []
    for index, claim in enumerate(document["claims"]):
        _fixed(claim, "claim_id kind summary anchors original_language translation source_review attribution times quantity geography identity_reference holds")
        require(claim["kind"] in reports.KINDS)
        _fixed(claim["times"], "event_start event_end issued_at published_at as_of valid_from valid_until")
        for time in claim["times"].values():
            reports.timestamp(time)
        time = claim["times"]["as_of"] or claim["times"]["event_start"]
        stamp = TimeValue(kind="unknown")
        if time is not None:
            kind: Literal["source_calendar_date", "instant", "unknown"] = "source_calendar_date" if time["precision"] == "calendar" else "instant" if time["precision"] == "instant" else "unknown"
            stamp = TimeValue(kind=kind,
                original=time["original"], start=time["utc"], timezone=time["timezone"])
        quantity = claim["quantity"]
        if quantity is not None:
            _fixed(quantity, "value unit operator scope")
        targets = [("report_artifact", OwnerRef(owner="src.storage.retained_reports", namespace=reports.ARTIFACT,
            record_id=_sha(ref), sha256=ref)) for ref in document["artifact_refs"]]
        objects.append(_object(record, f"/document/claims/{index}", ClaimRevision(claim_id=reports.identifier(claim["claim_id"]),
            claim_type=claim["kind"], assertion_class=claim["kind"] if claim["kind"] in {"reported_impact", "forecast", "warning", "source_reported_observation"} else "source_assertion",
            evidence_class="unverified_imported_report_assertion", scope="reported_assertion",
            time=stamp, value=quantity["value"] if quantity else None, unit=quantity["unit"] if quantity else None), targets))
    return objects


def _place(record: Record, value: dict) -> list[DomainObject]:
    from src.data import places
    rows = [row for row in places.registry() if row["place_id"] == record.reference.record_id]
    require(len(rows) == 1 and pg._canonical(rows[0]) == pg._canonical(value), "place_registry_conflict")
    return [_object(record, "", Place(place_id=value["place_id"], city=value["city"], country_code=value["country_code"],
        sampling_point_id=places.sampling_point_id(value["lat"], value["lon"]), lat=value["lat"], lon=value["lon"]))]


PROJECTORS = {
    ("src.data.places", "place-registry-v1"): _place,
    ("src.storage.scientific_supply", "scientific-supply-ghcn-v1"): _ghcn,
    ("src.storage.cyclone_supply", "cyclone-supply-nhc-v1"): _cyclone,
    ("src.storage.physical_events", "physical-episode-revision-v1"): _physical,
    ("src.storage.ghcn_runtime_inputs", "ghcn-source-result-input-v1"): _baseline,
    ("src.storage.retained_reports", "retained-report-revision-v1"): _reports,
}


def inspect_records(records: Sequence[Record], objects: Sequence[DomainObject] = ()) -> dict:
    """Derive bounded views. Unsupported records survive without core permissions."""
    require(len(records) <= MAX_RECORDS, "domain_record_count_bound")
    require(sum(len(record.raw) for record in records) <= MAX_TOTAL_BYTES, "domain_input_byte_bound")
    projected = list(objects)
    artifacts, opaque = [], []
    identities: dict[tuple[str, str, str], set[str]] = {}
    native = {(obj.reference.owner, obj.reference.namespace, obj.reference.record_id, obj.reference.sha256) for obj in objects}
    for record in records:
        ref = record.reference
        require(len(record.raw) <= MAX_BYTES and digest(record.raw) == ref.sha256, "domain_artifact_hash_mismatch")
        identities.setdefault((ref.owner, ref.namespace, ref.record_id), set()).add(ref.sha256)
        artifacts.append(dict(reference=ref.model_dump(), payload_base64=base64.b64encode(record.raw).decode("ascii"),
            byte_count=len(record.raw), provenance=record.provenance))
        if record.provenance == "local_journal_read" and (ref.owner, ref.namespace, ref.record_id, ref.sha256) in native:
            continue
        projector = PROJECTORS.get((ref.owner, ref.namespace))
        reason = "unknown_namespaced_extension"
        if projector:
            try:
                value = decode(record.raw)
                require(type(value.get("schema_version", 1)) is int and value.get("schema_version", 1) == 1)
                added = projector(record, value)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                reason = "malformed_or_unsupported_namespaced_extension"
            else:
                require(len(projected) + len(added) <= MAX_OBJECTS, "domain_object_count_bound")
                projected.extend(added)
                continue
        opaque.append(dict(reference=ref.model_dump(), disposition="opaque_unverified", reason=reason,
            supported_projection=None, publication_authorized=False))
    require(len(projected) <= MAX_OBJECTS, "domain_object_count_bound")
    refs = {obj.reference.model_dump_json() for obj in projected}
    retained = {record.reference.model_dump_json() for record in records}
    artifacts_by_ref = {record.reference.model_dump_json(): record for record in records}
    updated = []
    for obj in projected:
        relationships = []
        for relation in obj.relationships:
            target = relation.target
            candidates = identities.get((target.owner, target.namespace, target.record_id), set())
            if candidates and candidates != {target.sha256}:
                disposition = "conflicting"
            elif target.model_dump_json() in refs:
                disposition = "present_in_inspection"
            elif target.model_dump_json() in retained:
                disposition = "opaque"
            else:
                disposition = "missing"
            if relation.content_sha256 is not None and disposition == "present_in_inspection":
                from src.storage.cyclone_supply import assertion_key
                source = decode(artifacts_by_ref[target.model_dump_json()].raw)
                matches = [(index, row) for index, row in enumerate(source["rows"])
                    if digest(pg._canonical(row)) == relation.content_sha256]
                if len(matches) != 1 or assertion_key(matches[0][1]["advisory"]) != relation.source_identity_sha256:
                    disposition = "conflicting"
                else:
                    target = target.model_copy(update={"locator": f"/rows/{matches[0][0]}"})
            relationships.append(relation.model_copy(update={"disposition": disposition, "target": target}))
        key = (obj.reference.owner, obj.reference.namespace, obj.reference.record_id)
        conflict = len(identities.get(key, set())) > 1
        updated.append(obj.model_copy(update={"relationships": tuple(relationships),
            "disposition": "conflicting_identity" if conflict else "projected_unverified"}).model_dump(mode="json"))
    return dict(schema_version=1, read_only=True, production_authority=False,
        provenance="external_packets_prove_local_artifact_integrity_only_not_owner_authentication_or_currentness",
        source_truth_verified=False, publication_authorized=False, required_checks_completed=False,
        artifacts=artifacts, objects=updated, unprojected=opaque,
        conflicts=[dict(owner=key[0], namespace=key[1], record_id=key[2], sha256=sorted(hashes))
            for key, hashes in sorted(identities.items()) if len(hashes) > 1])


def inspect_journal(connection: sqlite3.Connection, external: Sequence[Record] = ()) -> dict:
    """Read current installed SQLite owners, without migration or clock/status writes."""
    from src.commands import domain_journal as journal
    from src.commands import batch_journal as jobs, check_journal as checks
    from src.commands import check_execution_journal as execution
    from src.editorial.revisions import fingerprint
    objects: list[DomainObject] = []
    records: list[Record] = list(external)

    def artifact(sha: str) -> OwnerRef:
        raw = journal.read_artifact(connection, sha)
        ref = OwnerRef(owner="src.commands.domain_journal", namespace="domain_artifacts", record_id=sha, sha256=sha)
        if not any(record.reference == ref for record in records):
            records.append(Record(ref, raw, "local_journal_read"))
        return ref

    for row in connection.execute("SELECT r.*,e.legacy_id FROM domain_revisions r JOIN domain_entities e USING(entity_id) ORDER BY r.revision_id"):
        identity = decode(row["identity_json"].encode("utf-8"))
        raw = journal._json_bytes([row["entity_id"], identity])
        require(digest(raw) == row["revision_id"] and identity["content_revision"] == row["content_revision"]
            and identity["text_sha256"] == row["text_sha256"] and identity["evidence_sha256"] == row["evidence_sha256"], "changed_draft_revision")
        ref = OwnerRef(owner="src.commands.domain_journal", namespace="domain_revisions", record_id=row["revision_id"], sha256=row["revision_id"])
        record = Record(ref, raw, "local_journal_read")
        records.append(record)
        targets = [("text_artifact", artifact(row["text_sha256"])), ("evidence_artifact", artifact(row["evidence_artifact_sha256"]))]
        objects.append(_object(record, "", DraftRevision(entity_id=row["entity_id"], legacy_id=row["legacy_id"],
            revision_id=row["revision_id"], content_revision=row["content_revision"], text_sha256=row["text_sha256"], evidence_sha256=row["evidence_sha256"]), targets))
        # Complete exact snapshots already have their own retained artifact IDs.
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "batch_jobs" in tables:
        for row in connection.execute("SELECT job_id FROM batch_jobs ORDER BY job_id"):
            value = jobs.read(connection, row[0])
            raw = journal.read_artifact(connection, value["plan_sha256"])
            record = Record(OwnerRef(owner="src.commands.batch_journal", namespace="batch_jobs", record_id=row[0], sha256=digest(raw)), raw, "local_journal_read")
            records.append(record)
            objects.append(_object(record, "", Job(job_id=row[0], plan_sha256=value["plan_sha256"], intent_id=value["intent_id"],
                registered_at=_instant(value["registered_at"]), useful_until=_instant(value["useful_until"]))))
    if "check_sets" in tables and connection.execute("SELECT 1 FROM check_sets LIMIT 1").fetchone():
        checks.validate(connection)
        for row in connection.execute("SELECT * FROM check_sets ORDER BY check_set_id"):
            packet = checks._packet(connection, row["check_set_id"])
            raw = journal.read_artifact(connection, row["packet_sha256"])
            record = Record(OwnerRef(owner="src.commands.check_journal", namespace="check_sets", record_id=row["check_set_id"], sha256=digest(raw)), raw, "local_journal_read")
            records.append(record)
            for stage in checks.STAGES:
                attempt = checks._attempt(connection, row["check_set_id"], stage)
                terminal = connection.execute("SELECT * FROM check_receipts WHERE grant_id=?", (attempt["grant_id"],)).fetchone() if attempt else None
                observation = connection.execute("SELECT * FROM check_observations WHERE grant_id=?", (attempt["grant_id"],)).fetchone() if attempt and "check_observations" in tables else None
                targets = []
                if attempt and "check_execution_schema" in tables:
                    request_raw = execution.read_request(connection, row["check_set_id"], stage, attempt["grant_id"])
                    require(digest(request_raw) == attempt["binding"]["request_sha256"], "changed_check_request")
                if attempt:
                    targets.append(("request_artifact", artifact(attempt["binding"]["request_sha256"])))
                if observation:
                    response_raw = execution.read_response(connection, row["check_set_id"], stage, attempt["grant_id"])
                    require(digest(response_raw) == observation["raw_sha256"], "changed_check_observation")
                    targets.append(("observation_artifact", artifact(observation["raw_sha256"])))
                    artifact(observation["metadata_sha256"])
                if terminal:
                    targets.append(("receipt_artifact", artifact(terminal["receipt_sha256"])))
                core = CheckExecution(check_set_id=row["check_set_id"], job_id=packet["job_id"], stage=stage,
                    grant_id=attempt["grant_id"] if attempt else None, request_sha256=attempt["binding"]["request_sha256"] if attempt else None,
                    receipt_sha256=terminal["receipt_sha256"] if terminal else None, observation_sha256=observation["raw_sha256"] if observation else None,
                    disposition=checks._stage_status(connection, attempt))
                target = next((obj.reference for obj in objects if isinstance(obj.core, Job) and obj.core.job_id == packet["job_id"]), None)
                objects.append(_object(record, "/stages/" + stage, core, ([("job", target)] if target else []) + targets))
    if "batch_result_reviews" in tables:
        for row in connection.execute("SELECT * FROM batch_result_reviews ORDER BY review_id"):
            raw = journal.read_artifact(connection, row["report_sha256"])
            document = decode(raw)
            require(fingerprint(document["binding"]) == row["review_id"] == document["review_id"], "changed_review_binding")
            binding = document["binding"]
            require(binding["job_id"] == row["job_id"] and binding["receipt_id"] == row["receipt_id"]
                and type(binding["fence"]) is int and binding["fence"] == row["fence"]
                and binding["reviewed_at"] == row["recorded_at"], "changed_review_binding")
            record = Record(OwnerRef(owner="src.commands.batch_result_journal", namespace="batch_result_reviews", record_id=row["review_id"], sha256=digest(raw)), raw, "local_journal_read")
            records.append(record)
            target = next((obj.reference for obj in objects if isinstance(obj.core, Job) and obj.core.job_id == row["job_id"]), None)
            objects.append(_object(record, "", Review(review_id=row["review_id"], job_id=row["job_id"], receipt_id=row["receipt_id"],
                fence=row["fence"], recorded_at=_instant(row["recorded_at"]), review_class="retained_machine_result_review"), [("job", target)] if target else []))
    # These owner reads are validated in place. Do not reinterpret immutable import
    # snapshots or historical assertions as typed source/claim/check records.
    for row in connection.execute("SELECT snapshot_id,artifact_sha256 FROM domain_snapshots ORDER BY snapshot_id"):
        records.append(Record(OwnerRef(owner="src.commands.domain_journal", namespace="domain_snapshots",
            record_id=row["snapshot_id"], sha256=row["artifact_sha256"]), journal.read_artifact(connection, row["artifact_sha256"]), "local_journal_read"))
    output = inspect_records(records, objects)
    output["snapshot_artifacts"] = [dict(row) for row in connection.execute(
        "SELECT snapshot_id,artifact_sha256,origin,origin_id FROM domain_snapshots ORDER BY snapshot_id")]
    output["retained_occurrence_dispositions"] = [dict(row) for row in connection.execute(
        "SELECT occurrence_id,snapshot_id,locator,artifact_sha256,disposition,issues_json FROM domain_occurrences ORDER BY occurrence_id")]
    return output
