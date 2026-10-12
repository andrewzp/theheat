"""Bounded invented-local GHCN inputs; independently replayed, never verdicts.

The original parsers and scientific/history functions remain the sole interpreter.
This module has no network client, provider, mutable baseline or state replacement.
"""
from __future__ import annotations

import base64
import bz2
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date
import gzip
import hashlib
import io
import lzma
import os
from pathlib import Path
import re
import tarfile
import tempfile

from src.commands.schema import utc_datetime
from src.data import ghcn, ghcn_db, temperature_history as history
from src.data.ghcn_format import DiffRecord
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import digest, environment, freeze, require, sha

DEPENDENCIES = "ghcn-runtime-dependencies-v1"
RAW = "ghcn-runtime-raw-v1"
INPUT = "ghcn-source-result-input-v1"
SUBMISSION = "ghcn-source-submission-v1"
RESULT = "ghcn-source-runtime-result-v1"
MAX_RAW = 8 * 1024**2
MAX_TOTAL_RAW = 128 * 1024**2
MAX_EXPANDED = 256 * 1024**2
MAX_DECODER_MEMORY = 64 * 1024**2
MAX_RECORDS = 1000000
MAX_RECEIPTS = 32
MAX_EFFECTS = 10000
MAX_TARGETS = 256
REASONS = frozenset({"current_archive_unverified", "tracked_observation_absent_from_current_archive",
    "current_archive_comparison_gap", "current_archive_comparator_changed",
    "tracked_observation_missing_current_value", "current_source_qc_or_value_revision"})
INVALIDATING = frozenset({"current_archive_comparator_changed", "current_source_qc_or_value_revision"})


def fixed(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), "ghcn_input_shape")


def field(value, key):
    return dict(present=key in value, value=freeze(value[key]) if key in value else None)


def state_dependencies(state):
    claims = history.retained_claims(state)
    require(len(claims) <= MAX_TARGETS, "ghcn_target_capacity")
    ids = [row["draft_id"] for row in claims]
    require(all(type(x) is str and x for x in ids) and len(ids) == len(set(ids)), "ghcn_target_identity")
    targets = [deepcopy(d) for d in state.get("drafts", []) if isinstance(d, dict) and d.get("id") in ids]
    require(len(targets) == len(ids), "ghcn_target_identity")
    keys = sorted({d.get("event_id") or d["id"] for d in targets})
    ledger = state.get("publish_ledger", {})
    health = state.get("source_health", {})
    require(type(ledger) is dict and type(health) is dict, "ghcn_state_dependency_invalid")
    return freeze(dict(temperature_history=field(state, "temperature_history"), claims=claims,
        tracked_points=sorted([sid, day.isoformat(), element] for sid, day, element in history.tracked_points(state)),
        targets=targets, ledger={key: field(ledger, key) for key in keys}, source_health=field(health, "ghcn")))


def detached_state(dependencies):
    state = dict(drafts=deepcopy(dependencies["targets"]), publish_ledger={}, source_health={})
    for key in ("temperature_history",):
        if dependencies[key]["present"]:
            state[key] = deepcopy(dependencies[key]["value"])
    for key, item in dependencies["ledger"].items():
        if item["present"]:
            state["publish_ledger"][key] = deepcopy(item["value"])
    if dependencies["source_health"]["present"]:
        state["source_health"]["ghcn"] = deepcopy(dependencies["source_health"]["value"])
    require(state_dependencies(state) == dependencies, "ghcn_dependency_shape")
    return state


@dataclass(frozen=True)
class Baseline:
    database: Path
    manifest: Path
    database_sha256: str
    manifest_sha256: str

    @contextmanager
    def reader(self):
        """Copy pinned bytes to a private inode; verify both files before/after use."""
        from scripts import threshold_artifacts as artifacts
        sha(self.database_sha256)
        sha(self.manifest_sha256)
        require(not self.manifest.is_symlink() and not self.database.is_symlink(), "ghcn_baseline_symlink")
        require(artifacts.digest(self.manifest, 4096)[0] == self.manifest_sha256, "ghcn_manifest_changed")
        manifest = artifacts.read_manifest(self.manifest)
        require(manifest["sha256"] == self.database_sha256, "ghcn_baseline_pin_changed")
        artifacts.verify_database(self.database, manifest)
        with tempfile.TemporaryDirectory(prefix="theheat-ghcn-baseline-") as temporary:
            target = Path(temporary) / "baseline.sqlite"
            fd = os.open(self.database, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                with os.fdopen(fd, "rb") as source, target.open("xb") as output:
                    total = 0
                    while chunk := source.read(1024**2):
                        total += len(chunk)
                        require(total <= artifacts.MAX_DB_BYTES, "ghcn_baseline_size")
                        output.write(chunk)
                target.chmod(0o400)
                artifacts.verify_database(target, manifest)
                with ghcn_db.open_db_readonly(target) as c:
                    require(c.execute("SELECT count(*) FROM stations WHERE is_active=1").fetchone()[0] <= 50000,
                            "ghcn_station_capacity")
                    stations = ghcn_db.load_active_stations(c)
                    require(len(stations) <= 50000, "ghcn_station_capacity")
                    # Bind exactly the rows used by current threshold reconstruction.
                    def rows_sha(sql):
                        hasher = hashlib.sha256()
                        for row in c.execute(sql):
                            hasher.update(p._canonical(list(row)) + b"\n")
                        return hasher.hexdigest()
                    rows = rows_sha("SELECT station_id,kind,month,day,value_c,record_year FROM thresholds ORDER BY station_id,kind,month,day")
                    provenance = rows_sha("SELECT station_id,payload_json FROM threshold_provenance ORDER BY station_id")
                descriptor = dict(database_sha256=self.database_sha256, manifest_sha256=self.manifest_sha256,
                    stations_sha256=digest(stations), threshold_rows_sha256=rows,
                    provenance_sha256=provenance, stats=artifacts.database_stats(target))
                yield target, descriptor
                artifacts.verify_database(target, manifest)
                artifacts.verify_database(self.database, manifest)
                require(artifacts.digest(self.manifest, 4096)[0] == self.manifest_sha256, "ghcn_manifest_changed")
            finally:
                # Only this owned scratch inode is changed for cleanup.
                if target.exists():
                    target.chmod(0o600)


def configuration():
    return dict(lookback_days=ghcn.DIFF_LOOKBACK_DAYS, max_obs_age_days=ghcn.MAX_OBS_AGE_DAYS,
                archive_verification_limit=ghcn.ARCHIVE_VERIFICATION_LIMIT,
                selection_bucket_hours=ghcn.ARCHIVE_SELECTION_BUCKET_HOURS)


def bounded_payload(raw, *, kind):
    """Preflight expansion without extracting paths or changing parser semantics."""
    require(type(raw) is bytes and len(raw) <= MAX_RAW, "ghcn_raw_capacity")
    decoded = raw
    if kind == "diff":
        if raw.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
                decoded = compressed.read(MAX_EXPANDED + 1)
        elif raw.startswith(b"BZh"):
            with bz2.BZ2File(io.BytesIO(raw)) as bzip:
                decoded = bzip.read(MAX_EXPANDED + 1)
        elif raw.startswith(b"\xfd7zXZ\x00"):
            parts = []
            pending = raw
            total = 0
            # Bound the dictionary allocation as well as emitted bytes. Reuse
            # XZ's concatenated-stream semantics without an unbounded decoder.
            while pending:
                decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=MAX_DECODER_MEMORY)
                compressed_input = pending
                while not decoder.eof:
                    part = decoder.decompress(compressed_input, max_length=MAX_EXPANDED + 1 - total)
                    parts.append(part)
                    total += len(part)
                    require(total <= MAX_EXPANDED, "ghcn_expansion_capacity")
                    require(decoder.eof or not decoder.needs_input, "ghcn_truncated_xz")
                    compressed_input = b""
                pending = decoder.unused_data
                unpadded = pending.lstrip(b"\x00")
                require((len(pending)-len(unpadded)) % 4 == 0, "ghcn_xz_padding")
                pending = unpadded
            decoded = b"".join(parts)
        require(len(decoded) <= MAX_EXPANDED, "ghcn_expansion_capacity")
    records = 0
    if kind == "diff":
        try:
            with tarfile.open(fileobj=io.BytesIO(decoded), mode="r:") as archive:
                count = 0
                member_bytes = 0
                for member in archive:
                    count += 1
                    require(count <= 1024 and 0 <= member.size <= MAX_EXPANDED, "ghcn_member_capacity")
                    if member.isfile():
                        member_bytes += member.size
                        require(member_bytes <= MAX_EXPANDED, "ghcn_expansion_capacity")
                        member_stream = archive.extractfile(member)
                        if member_stream is None:
                            raise ValueError("ghcn_member_unavailable")
                        data = member_stream.read(MAX_EXPANDED + 1)
                        require(len(data) <= MAX_EXPANDED, "ghcn_expansion_capacity")
                        records += data.count(b"\n") + 1
        except tarfile.ReadError:
            records = decoded.count(b"\n") + 1
    else:
        # A .dly line holds up to31 per-day records.
        records = (decoded.count(b"\n") + 1) * 31
    require(records <= MAX_RECORDS, "ghcn_record_capacity")
    return len(decoded), records


@dataclass(frozen=True)
class InventedResponse:
    kind: str
    key: str
    retrieved_at: str
    raw: bytes | None
    status: str = "success"

    def metadata(self):
        require(self.kind in {"diff", "station_archive"}, "ghcn_response_kind")
        require(type(self.key) is str, "ghcn_response_key")
        if self.kind == "diff":
            require(date.fromisoformat(self.key).isoformat() == self.key, "ghcn_response_day")
        else:
            require(re.fullmatch(r"[A-Z0-9]{11}", self.key), "ghcn_response_station")
        utc_datetime(self.retrieved_at)
        require(self.status in {"success", "missing", "failed"}, "ghcn_response_status")
        require((self.status == "success") == (type(self.raw) is bytes), "ghcn_response_status")
        return dict(kind=self.kind, key=self.key, retrieved_at=self.retrieved_at, status=self.status,
                    raw_sha256=hashlib.sha256(self.raw).hexdigest() if self.raw is not None else None,
                    failure_code=None if self.status == "success" else "source_" + self.status)


def retain_raw(repository, response):
    from src.commands.postgres_source_results import retain_exact
    environment(repository)
    require(type(response) is InventedResponse, "ghcn_response_required")
    metadata = response.metadata()
    if response.raw is not None:
        require(len(response.raw) <= MAX_RAW, "ghcn_raw_capacity")
        retain_exact(repository, RAW, metadata["raw_sha256"], dict(schema_version=1, encoding="base64",
            raw_sha256=metadata["raw_sha256"], byte_count=len(response.raw), payload=base64.b64encode(response.raw).decode("ascii")))
        bounded_payload(response.raw, kind=response.kind)
    return metadata


def read_responses(c, metadata):
    require(type(metadata) is list and len(metadata) <= MAX_RECEIPTS, "ghcn_response_capacity")
    responses, seen, total, expanded, records = [], set(), 0, 0, 0
    for row in metadata:
        fixed(row, "kind key retrieved_at status raw_sha256 failure_code")
        identity = (row["kind"], row["key"])
        require(identity not in seen, "ghcn_duplicate_response")
        seen.add(identity)
        raw = None
        if row["raw_sha256"] is not None:
            sha(row["raw_sha256"])
            _, value = p.PostgresProjectionRepository._read(c, RAW, row["raw_sha256"])
            fixed(value, "schema_version encoding raw_sha256 byte_count payload")
            require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["encoding"] == "base64"
                and type(value["byte_count"]) is int and 0 <= value["byte_count"] <= MAX_RAW
                and type(value["payload"]) is str and len(value["payload"]) <= (MAX_RAW+2)//3*4, "ghcn_raw_shape")
            raw = base64.b64decode(value["payload"], validate=True)
            require(len(raw) == value["byte_count"] and hashlib.sha256(raw).hexdigest() == row["raw_sha256"] == value["raw_sha256"], "ghcn_raw_changed")
            size, count = bounded_payload(raw, kind=row["kind"])
            total += len(raw)
            expanded += size
            records += count
            require(total <= MAX_TOTAL_RAW and expanded <= MAX_EXPANDED and records <= MAX_RECORDS, "ghcn_input_capacity")
        response = InventedResponse(row["kind"], row["key"], row["retrieved_at"], raw, row["status"])
        require(response.metadata() == row, "ghcn_response_changed")
        responses.append(response)
    return responses


class Effects:
    def __init__(self, responses):
        self.rows = []
        self.responses = responses

    def append(self, row):
        require(len(self.rows) < MAX_EFFECTS, "ghcn_effect_capacity")
        self.rows.append(freeze(dict(ordinal=len(self.rows), **row)))

    def observation(self, record, *, retrieved_at, source_revision):
        witnesses = [r.metadata() for r in self.responses if r.raw is not None
                     and hashlib.sha256(r.raw).hexdigest() == source_revision]
        require(bool(witnesses), "ghcn_observation_witness_required")
        row = asdict(record)
        row["obs_date"] = record.obs_date.isoformat()
        self.append(dict(kind="observation_revision", record=row, retrieved_at=retrieved_at,
                         source_revision=source_revision, witness=witnesses))

    def finding(self, claim, *, reason, source_revision, retrieved_at, details):
        require(reason in REASONS, "ghcn_finding_reason")
        witnesses = [r.metadata() for r in self.responses if r.kind == "diff" or r.key == claim["station_id"]]
        self.append(dict(kind="claim_finding", claim=claim, claim_sha256=digest(claim), reason=reason,
                         source_revision=source_revision, retrieved_at=retrieved_at, details=details, witness=witnesses))


def apply_effects(state, rows):
    """Only called with independently re-derived rows, never HTTP operations."""
    for row in rows:
        if row["kind"] == "observation_revision":
            record = dict(row["record"])
            record["obs_date"] = date.fromisoformat(record["obs_date"])
            history.record_observation_revision(state, DiffRecord(**record), retrieved_at=row["retrieved_at"], source_revision=row["source_revision"])
        else:
            history.record_claim_finding(state, row["claim"], reason=row["reason"], source_revision=row["source_revision"],
                retrieved_at=row["retrieved_at"], details=row["details"], verified_change=row["reason"] in INVALIDATING)


class ReplayIO:
    open_db = staticmethod(ghcn_db.open_db_readonly)

    def __init__(self, responses, config, now):
        require(config == configuration(), "ghcn_configuration_changed")
        self.lookback, self.max_age = config["lookback_days"], config["max_obs_age_days"]
        require(type(self.lookback) is int and 1 <= self.lookback <= MAX_RECEIPTS - 20, "ghcn_lookback_capacity")
        self.responses, self.now, self.used = responses, now, set()
        self.effects = Effects(responses)

    def diffs(self, dates):
        rows = [r for r in self.responses if r.kind == "diff"]
        require({r.key for r in rows} == {d.isoformat() for d in dates}, "ghcn_diff_inventory_changed")
        self.used.update((r.kind, r.key) for r in rows)
        return {date.fromisoformat(r.key):r.raw for r in rows if r.raw is not None}

    def diff_time(self, day):
        return next(r.retrieved_at for r in self.responses if r.kind == "diff" and r.key == day.isoformat())

    def archives(self, selected):
        rows = [r for r in self.responses if r.kind == "station_archive"]
        require({r.key for r in rows} == set(selected), "ghcn_archive_inventory_changed")
        for row in rows:  # Preserve explicitly retained completion order.
            require(row.retrieved_at == self.now, "ghcn_archive_time_changed")
            self.used.add((row.kind, row.key))
            yield row.key, row.raw


def derive(baseline, dependencies, responses, *, now, config):
    """One real parser/qualification execution; no caller-supplied success flags."""
    from src.orchestrator.common import _classify_ghcn_source_status
    require(type(baseline) is Baseline, "ghcn_baseline_required")
    state = detached_state(dependencies)
    runtime = ReplayIO(responses, config, now)
    metrics = dict(threshold_verification="success")
    with baseline.reader() as (path, descriptor):
        try:
            bundles, countries = ghcn.check_extreme_signals_for_stations(db_path=path, bot_state=state,
                metrics_out=metrics, _runtime=runtime, _now_fn=lambda: now,
                archive_verification_limit=config["archive_verification_limit"])
        except RuntimeError as exc:
            require(str(exc) in {"GHCN: no diff files available from NOAA", "GHCN: no observations returned; check NOAA diff endpoints"}, "ghcn_replay_unavailable")
            bundles, countries = [], []
            metrics.update(status="failed", error="ghcn_fetch_failed")
        else:
            metrics["status"] = _classify_ghcn_source_status(metrics, today=date.fromisoformat(now[:10]))
    require(runtime.used == {(r.kind, r.key) for r in responses}, "ghcn_unused_response")
    return bundles, countries, metrics, runtime.effects.rows, descriptor
