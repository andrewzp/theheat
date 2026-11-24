"""Local/preview retention and resolution of dated source-mapped fire footprints.

No fetcher, production enrollment, publication permission or cross-source alias
resolution. Operator-retained origin is not independent provider authentication.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import re

from src.data import nifc_perimeter as source
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import digest, environment, instant, require, sha, uuid

CAPTURE = "mapped-fire-capture-v1"
OWNER = "mapped-fire-source-owner-v1"
REVISION = "mapped-fire-episode-v1"
OPERATION = "mapped-fire-operation-v1"
POLICY = "nifc-dated-mapped-footprints-v1"
MAX_MEMBERS = 64
_CONTEXT = object()


def episode_id(incident: str) -> str:
    require(source._uuid(incident) == incident, "invalid_fire_incident")
    return "ep1:fire:nifc:" + incident


def _episode(value):
    require(type(value) is str and value.startswith("ep1:fire:nifc:"), "invalid_fire_episode")
    require(episode_id(value.removeprefix("ep1:fire:nifc:")) == value, "invalid_fire_episode")
    return value


def _prefix(value):
    return digest(_episode(value)) + ":"


def _binding(episode, revision, members):
    return dict(schema_version=1, episode_id=episode, revision_sha256=revision,
                source_assertion_refs=sorted({row["source_revision_sha256"] for row in members}),
                identity_class="source_mapped_fire")


def validate_binding(value):
    require(type(value) is dict and set(value) == {
        "schema_version", "episode_id", "revision_sha256", "source_assertion_refs", "identity_class"},
        "invalid_fire_binding")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["identity_class"] == "source_mapped_fire", "invalid_fire_binding")
    _episode(value["episode_id"])
    sha(value["revision_sha256"])
    refs = value["source_assertion_refs"]
    require(type(refs) is list and 1 <= len(refs) <= MAX_MEMBERS
            and all(type(ref) is str for ref in refs) and refs == sorted(set(refs)), "invalid_fire_binding")
    for ref in refs:
        sha(ref)
    return p._decode(p._canonical(value))


def _record(connection, namespace, key, value):
    encoded, fields = p._snapshot(value)
    return p.PostgresProjectionRepository._record(connection, namespace, key, encoded, fields)


def _map_view(record):
    return dict(source_product=source.PRODUCT, source_url=source.SOURCE_URL,
        incident_id=record.incident_id, polygon_id=record.polygon_id,
        polygon_source=record.polygon_source, mapping_method=record.mapping_method, source_name=record.name,
        polygon_captured_at=record.polygon_captured_at, source_area_acres=record.source_area_acres,
        geometry_sha256=record.geometry_sha256, source_revision_sha256=record.source_revision_sha256)


def _derive(episode, records):
    """Recompute from retained source bytes, never a stored eligibility label.

    Conservative spatial guard: >5% source-recorded acreage AND >5% signed-ring
    coordinate-area change, with distinct canonical geometry. The latter is
    only a map-change guard, not measured ground area or a fire-growth estimate.
    """
    by_time: dict = {}
    unique: dict[str, source.Perimeter] = {}
    for row in records:
        require(episode_id(row.incident_id) == episode, "fire_member_identity_changed")
        by_time.setdefault(row.polygon_captured_at, set()).add(row.source_revision_sha256)
        unique.setdefault(row.source_revision_sha256, row)
    holds = []
    clocks = [instant(row.polygon_captured_at) for row in records]
    if clocks != sorted(clocks):
        holds.append("late_dated_map_review_required")
    if any(len(values) > 1 for values in by_time.values()):
        holds.append("conflicting_dated_maps")
    if len({(row.polygon_source, row.mapping_method) for row in unique.values()}) > 1:
        holds.append("map_source_or_method_changed")
    ordered = sorted(unique.values(), key=lambda row: (instant(row.polygon_captured_at), row.source_revision_sha256))
    opportunities = []
    anchor = None
    for row in ordered:
        if anchor is None or (row.geometry_sha256 != anchor.geometry_sha256
                and abs(row.source_area_acres - anchor.source_area_acres) / anchor.source_area_acres > .05
                and abs(row.geometry_area_index - anchor.geometry_area_index) / anchor.geometry_area_index > .05):
            identity = digest(dict(episode_id=episode, policy=POLICY,
                previous_map=anchor.source_revision_sha256 if anchor else None,
                current_map=row.source_revision_sha256))
            opportunities.append(dict(opportunity_id=identity, current_map=row.source_revision_sha256,
                previous_map=anchor.source_revision_sha256 if anchor else None))
            anchor = row
    return dict(holds=sorted(holds), maps=[_map_view(row) for row in ordered],
                opportunities=[] if holds else opportunities)


@dataclass(frozen=True)
class FireEpisodeSession:
    repository: p.PostgresProjectionRepository

    def retain_capture(self, raw, *, capture_id, captured_at, producer_revision, source_url):
        environment(self.repository)
        uuid(capture_id)
        require(type(producer_revision) is str and re.fullmatch(r"[0-9a-f]{40}", producer_revision),
                "invalid_fire_producer")
        capture = source.decode_capture(raw, source_url=source_url, captured_at=captured_at)
        value = dict(schema=source.SCHEMA, capture_id=capture_id, source_url=source_url,
            captured_at=capture.captured_at, producer_revision=producer_revision,
            evidence_class="operator_retained_capture", raw_sha256=capture.raw_sha256,
            raw_base64=base64.b64encode(capture.raw_bytes).decode("ascii"))
        try:
            with self.repository._connection(writing=True) as connection:
                self.repository._validate(connection)
                for row in sorted(capture.perimeters, key=lambda row: digest([row.polygon_source, row.polygon_id])):
                    _record(connection, OWNER, digest([row.polygon_source, row.polygon_id]),
                        dict(source=row.polygon_source, polygon_id=row.polygon_id, incident_id=row.incident_id))
                _record(connection, CAPTURE, capture_id, value)
        except p.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise
        # An unknown acknowledgement gets one exact read, never a repeat write.
        return self.read_capture(capture_id, expected_sha=digest(value))

    def read_capture(self, capture_id, *, expected_sha, connection=None):
        environment(self.repository)
        uuid(capture_id)
        sha(expected_sha)
        receipt, value = (self.repository.read(CAPTURE, capture_id) if connection is None
                          else self.repository._read(connection, CAPTURE, capture_id))
        require(receipt.canonical_sha256 == expected_sha, "fire_capture_changed")
        require(type(value) is dict and set(value) == set(
            "schema capture_id source_url captured_at producer_revision evidence_class raw_sha256 raw_base64".split()),
            "invalid_fire_capture")
        require(value["schema"] == source.SCHEMA and value["capture_id"] == capture_id
            and value["evidence_class"] == "operator_retained_capture"
            and type(value["producer_revision"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", value["producer_revision"]), "invalid_fire_capture")
        require(type(value["raw_base64"]) is str and len(value["raw_base64"]) <= (source.MAX_BYTES + 2) // 3 * 4,
                "invalid_fire_capture")
        try:
            raw = base64.b64decode(value["raw_base64"], validate=True)
        except (ValueError, TypeError):
            raise ValueError("invalid_fire_capture") from None
        require(base64.b64encode(raw).decode("ascii") == value["raw_base64"], "invalid_fire_capture")
        capture = source.decode_capture(raw, source_url=value["source_url"], captured_at=value["captured_at"])
        require(capture.raw_sha256 == sha(value["raw_sha256"]), "fire_capture_bytes_changed")
        if connection is None:
            with self.repository._connection() as owner_connection:
                self.repository._validate(owner_connection)
                self._owners(owner_connection, capture)
        else:
            self._owners(connection, capture)
        return receipt, capture

    def _owners(self, connection, capture):
        for row in capture.perimeters:
            _, owner = self.repository._read(connection, OWNER, digest([row.polygon_source, row.polygon_id]))
            require(owner == dict(source=row.polygon_source, polygon_id=row.polygon_id, incident_id=row.incident_id),
                    "fire_polygon_owner_changed")

    def _head(self, connection, episode):
        prefix = _prefix(episode)
        found = connection.execute(f"SELECT snapshot_id FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id >= %s AND snapshot_id < %s ORDER BY snapshot_id DESC LIMIT 1",
            (REVISION, prefix, prefix[:-1] + ";")).fetchone()
        if found is None:
            return None
        receipt, value = self.repository._read(connection, REVISION, found[0])
        require(type(value) is dict and set(value) == {
            "schema_version", "policy", "episode_id", "sequence", "previous_sha256", "members", "derived"},
            "invalid_fire_revision")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["policy"] == POLICY and value["episode_id"] == episode, "invalid_fire_revision")
        require(type(value["sequence"]) is int and 1 <= value["sequence"] <= MAX_MEMBERS
            and found[0] == prefix + f'{value["sequence"]:010d}', "invalid_fire_revision")
        require((value["sequence"] == 1) == (value["previous_sha256"] is None), "invalid_fire_revision")
        if value["previous_sha256"] is not None:
            sha(value["previous_sha256"])
        records = self._records(value["members"], episode, connection)
        require(_derive(episode, records) == value["derived"], "fire_derivation_changed")
        return receipt, value

    def _records(self, members, episode, connection):
        require(type(members) is list and 1 <= len(members) <= MAX_MEMBERS, "fire_member_bound")
        records, cache = [], {}
        for member in members:
            require(type(member) is dict and set(member) == {
                "capture_id", "capture_sha256", "source_revision_sha256"}, "invalid_fire_member")
            key = (uuid(member["capture_id"]), sha(member["capture_sha256"]))
            if key not in cache:
                cache[key] = self.read_capture(key[0], expected_sha=key[1], connection=connection)[1]
            matches = [row for row in cache[key].perimeters
                if episode_id(row.incident_id) == episode
                and row.source_revision_sha256 == sha(member["source_revision_sha256"])]
            require(len(matches) == 1, "fire_member_changed")
            records.append(matches[0])
        require(len({row.source_revision_sha256 for row in records}) == len(records), "duplicate_fire_member")
        return records

    def read_current(self, episode, *, expected_head=None):
        environment(self.repository)
        _episode(episode)
        with self.repository._connection() as connection:
            self.repository._validate(connection)
            head = self._head(connection, episode)
        require(head is not None, "fire_episode_not_found")
        require(expected_head is None or head[0].canonical_sha256 == sha(expected_head), "fire_head_changed")
        return head

    def apply_capture(self, capture_id, capture_sha256, incident_id, *, expected_head, operation_id):
        environment(self.repository)
        uuid(capture_id)
        sha(capture_sha256)
        uuid(operation_id)
        episode = episode_id(incident_id)
        if expected_head is not None:
            sha(expected_head)
        payload = dict(capture_id=capture_id, capture_sha256=capture_sha256, episode_id=episode,
                       expected_head=expected_head, operation_id=operation_id, policy=POLICY)
        operation_key = _prefix(episode) + operation_id
        try:
            with self.repository._connection(writing=True) as connection:
                self.repository._validate(connection)
                lock = int(digest(episode)[:16], 16)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock if lock < 2**63 else lock - 2**64,))
                previous_operation = self._operation(connection, operation_key, payload)
                if previous_operation is not None:
                    return previous_operation
                head = self._head(connection, episode)
                require(expected_head == (head[0].canonical_sha256 if head else None), "fire_head_changed")
                capture = self.read_capture(capture_id, expected_sha=capture_sha256, connection=connection)[1]
                matches = [row for row in capture.perimeters if row.incident_id == incident_id]
                require(len(matches) == 1, "fire_incident_not_in_capture")
                incoming = matches[0]
                members = list(head[1]["members"]) if head else []
                if any(row["source_revision_sha256"] == incoming.source_revision_sha256 for row in members):
                    result = dict(episode_id=episode, status="duplicate", revision_sha256=expected_head)
                else:
                    require(len(members) < MAX_MEMBERS, "fire_member_bound")
                    members.append(dict(capture_id=capture_id, capture_sha256=capture_sha256,
                                        source_revision_sha256=incoming.source_revision_sha256))
                    derived = _derive(episode, self._records(members, episode, connection))
                    value = dict(schema_version=1, policy=POLICY, episode_id=episode,
                        sequence=head[1]["sequence"] + 1 if head else 1, previous_sha256=expected_head,
                        members=members, derived=derived)
                    receipt = _record(connection, REVISION, _prefix(episode) + f'{value["sequence"]:010d}', value)
                    result = dict(episode_id=episode, status="held" if derived["holds"] else "committed",
                                  revision_sha256=receipt.canonical_sha256)
                _record(connection, OPERATION, operation_key, dict(payload=payload, result=result))
            return result
        except p.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise
            with self.repository._connection() as connection:
                self.repository._validate(connection)
                reconciled = self._operation(connection, operation_key, payload)
            require(reconciled is not None, "fire_write_outcome_unknown")
            return reconciled

    def _operation(self, connection, key, payload):
        found = connection.execute(f"SELECT 1 FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id=%s",
                                   (OPERATION, key)).fetchone()
        if found is None:
            return None
        _, value = self.repository._read(connection, OPERATION, key)
        require(type(value) is dict and set(value) == {"payload", "result"}
                and value["payload"] == payload, "fire_operation_conflict")
        return value["result"]

    def prepare_story_context(self, episode, revision_sha256, *, now):
        clock = source._instant(now)
        receipt, value = self.read_current(episode, expected_head=revision_sha256)
        require(not value["derived"]["holds"], "fire_episode_held")
        # All historical bindings are rebuilt from the actual immutable chain.
        known = []
        with self.repository._connection() as connection:
            self.repository._validate(connection)
            previous_sha = None
            for sequence in range(1, value["sequence"] + 1):
                prior, revision = self.repository._read(connection, REVISION, _prefix(episode) + f'{sequence:010d}')
                records = self._records(revision["members"], episode, connection)
                for member in revision["members"]:
                    capture = self.read_capture(member["capture_id"], expected_sha=member["capture_sha256"],
                                                connection=connection)[1]
                    require(source._instant(capture.captured_at) <= clock
                        and all(instant(row.polygon_captured_at) <= clock for row in capture.perimeters
                                if episode_id(row.incident_id) == episode), "fire_future_evidence")
                require(revision["policy"] == POLICY and revision["episode_id"] == episode
                    and revision["sequence"] == sequence and revision["previous_sha256"] == previous_sha
                    and revision["derived"] == _derive(episode, records), "fire_chain_changed")
                if not revision["derived"]["holds"]:
                    known.append(_binding(episode, prior.canonical_sha256, revision["members"]))
                previous_sha = prior.canonical_sha256
        require(previous_sha == receipt.canonical_sha256, "fire_chain_changed")
        self.read_current(episode, expected_head=revision_sha256)
        binding = _binding(episode, receipt.canonical_sha256, value["members"])
        return FireEpisodeContext(self, p._canonical(binding), p._canonical(known), now, _CONTEXT), value


@dataclass(frozen=True)
class FireEpisodeContext:
    """Closed, live repository-backed resolver; a binding dictionary grants nothing."""
    session: FireEpisodeSession = field(repr=False, compare=False)
    binding_json: bytes
    known_bindings_json: bytes
    as_of: str
    _seal: object = field(repr=False, compare=False)

    @property
    def binding(self):
        return p._decode(self.binding_json)

    def validate(self, binding):
        require(type(self.session) is FireEpisodeSession and self._seal is _CONTEXT, "resolved_fire_context_required")
        require(validate_binding(binding) == self.binding, "fire_context_mismatch")
        fresh, value = self.session.prepare_story_context(binding["episode_id"], binding["revision_sha256"], now=self.as_of)
        require(fresh.binding_json == self.binding_json and fresh.known_bindings_json == self.known_bindings_json,
                "fire_context_changed")
        return value

    def contains(self, row):
        # Only exact, receipt-backed publication memory can be a published-text
        # reference. Source map history comes from the repository, never rows.
        if not self.published_reference(row):
            return False
        try:
            binding = validate_binding(row.get("physical_episode"))
        except (ValueError, TypeError):
            return False
        return binding in p._decode(self.known_bindings_json)

    @staticmethod
    def published_reference(row):
        return (type(row) is dict and type(row.get("tweet_id")) is str
            and re.fullmatch(r"[1-9][0-9]{0,24}", row["tweet_id"]) is not None
            and row.get("delivery_state", "published") == "published"
            and row.get("publish_outcome") in (None, "confirmed"))

    def map_memory(self):
        value = self.validate(self.binding)
        return dict(physical_episode=self.binding, dated_source_maps=value["derived"]["maps"],
            claim_limit="Dated source-mapped footprints only; no fire growth, continuous burning, duration, final area or cross-border impacts inferred.")
