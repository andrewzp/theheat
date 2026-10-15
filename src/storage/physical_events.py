"""Source-scoped cyclone episodes, immutable revisions and exact operations.

Explicit local/preview only. This is not a new state backend, identity oracle,
cross-agency alias resolver, callback owner or publication authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import re
from typing import Any

from src.data import cyclones
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import (CycloneSupplySession, assertion_key,
    decode_advisory, digest, environment, freeze, instant, require, sha, uuid)

REVISION = "physical-episode-revision-v1"
OPERATION = "physical-episode-operation-v1"
PROPOSAL = "physical-grouping-proposal-v1"
POLICY = "nhc-source-scoped-episode-v1"
MAX_EPISODES = 64
MAX_MEMBERS = 512
MAX_ALTERNATIVES = 16
EVENTS: dict[str, Any] = {cls.__name__: cls for cls in (cyclones.RapidIntensificationEvent,
          cyclones.TierCrossingEvent, cyclones.LandThreatEvent)}


def episode_id(advisory):
    """01–49 includes potential TCs; identity does not establish storm status."""
    match = re.fullmatch(r"(AL|EP)([0-9]{2})([0-9]{4})", advisory.storm_id.upper())
    if advisory.source != "nhc" or not match or not 1 <= int(match[2]) <= 49:
        return None
    if int(match[3]) < 1:
        return None
    if advisory.basin.strip().lower() not in ({"al", "atlantic"} if match[1] == "AL" else {"ep", "east pacific", "eastern pacific"}):
        return None
    return "ep1:cyclone:nhc:" + match[0]


def _episode(value):
    require(type(value) is str and re.fullmatch(r"ep1:cyclone:nhc:(?:AL|EP)(?:0[1-9]|[1-4][0-9])[0-9]{4}", value) is not None,
            "invalid_physical_episode")
    require(int(value[-4:]) > 0, "invalid_physical_episode")
    return value


def _prefix(episode):
    return digest(_episode(episode)) + ":"


def _binding(episode, revision, refs):
    return dict(schema_version=1, episode_id=episode, revision_sha256=revision,
                source_assertion_refs=refs, identity_class="source_scoped")


def validate_binding(value):
    require(type(value) is dict and set(value) == {"schema_version", "episode_id", "revision_sha256", "source_assertion_refs", "identity_class"},
            "invalid_episode_binding")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["identity_class"] == "source_scoped")
    _episode(value["episode_id"])
    sha(value["revision_sha256"])
    require(type(value["source_assertion_refs"]) is list and 1 <= len(value["source_assertion_refs"]) <= MAX_MEMBERS)
    require(len(set(value["source_assertion_refs"])) == len(value["source_assertion_refs"]))
    for ref in value["source_assertion_refs"]:
        sha(ref)
    return freeze(value)


@dataclass(frozen=True)
class EpisodeContext:
    """Resolved by the repository immediately before pure writer preparation."""
    binding_json: bytes
    known_bindings_json: bytes

    @property
    def binding(self):
        return p._decode(self.binding_json)

    def validate(self, binding):
        require(validate_binding(binding) == self.binding, "episode_context_mismatch")

    def contains(self, row):
        binding = row.get("physical_episode")
        try:
            value = validate_binding(binding)
        except (ValueError, TypeError):
            return False
        return value in p._decode(self.known_bindings_json)


def forecast_qualified(item):
    row, metadata = item["advisory"], item["metadata"]
    return (metadata["forecast_text_complete"] is True
        and metadata["source_row_sha256"] is not None
        and metadata["forecast_product_url"] is not None
        and metadata["forecast_issued_at_original"] is not None
        and instant(metadata["forecast_issued_at_original"]) == instant(row["issued_at"])
        and bool(row["advisory_number"])
        and metadata["forecast_advisory_number"] == row["advisory_number"]
        and metadata["forecast_points_sha256"] == digest(row["forecast_points"]))


def _claim(event):
    if type(event) is cyclones.TierCrossingEvent:
        return {"kind": event.kind, "to_category": event.to_category}
    if type(event) is cyclones.RapidIntensificationEvent:
        return dict(kind=event.kind, current_wind_kt=event.current_wind_kt,
                    previous_wind_kt=event.previous_wind_kt, delta_kt_24h=event.delta_kt_24h)
    require(type(event) is cyclones.LandThreatEvent)
    return dict(kind=event.kind, forecast_country=event.landmass_country)


def _detect(episode, items, previous_opportunities, cities, now):
    history = [replace(decode_advisory(item["advisory"]), storm_id=episode.rsplit(":", 1)[1]) for item in items]
    current = max(history, key=lambda advisory: instant(advisory.issued_at))
    prior_categories = [decode_advisory(item["advisory"]).category for item in items
                        if instant(item["advisory"]["issued_at"]) < instant(current.issued_at)]
    prior_highest = max(prior_categories, default=current.category)
    tiers = cyclones.detect_tier_crossings([current], {current.tracking_key: prior_highest})
    if not tiers and current.category == prior_highest:
        # Detection is not a consumption/posting receipt. An ordinary advisory
        # can refresh a still-eligible unconsumed crossing with its original
        # lower-category evidence and the same opportunity identity. A weakened
        # current storm cannot inherit an old higher-category opportunity.
        pending = [row for row in previous_opportunities
                   if row["event_type"] == "TierCrossingEvent" and row["claim"]["to_category"] == current.category]
        if pending:
            tiers = cyclones.detect_tier_crossings([current], {current.tracking_key: pending[0]["event"]["from_category"]})
    events: list[Any] = [*cyclones.detect_rapid_intensification(history), *tiers]
    current_item = next(item for item in items if instant(item["advisory"]["issued_at"]) == instant(current.issued_at))
    areas = []
    if current.lat is not None and current.lon is not None:
        areas.append(dict(kind="observed_position", lat=current.lat, lon=current.lon,
                          assertion_sha256=digest(current_item)))
    holds = []
    if current.forecast_points:
        if forecast_qualified(current_item):
            # Existing detector emits one nearest country per call. Reuse its
            # pair exclusion to enumerate remaining supported countries, bounded
            # by the retained city inventory, without changing its thresholds.
            pairs: dict = {}
            for _ in range(min(len(cities), MAX_EPISODES) + 1):
                threats = cyclones.detect_land_threats([current], pairs, cities, now=instant(now))
                if not threats:
                    break
                require(len(areas) <= MAX_EPISODES, "forecast_area_bound")
                event = threats[0]
                pairs.setdefault(current.tracking_key, []).append(cyclones._landmass_slug(event.landmass_country))
                events.append(event)
                areas.append(dict(kind="forecast_threat", country=event.landmass_country,
                    nearest_city=event.nearest_city, closest_valid_at=event.closest_valid_at,
                    forecast_points_sha256=current_item["metadata"]["forecast_points_sha256"],
                    assertion_sha256=digest(current_item)))
        else:
            holds.append("forecast_product_unresolved")
    opportunities = []
    for event in events:
        claim = _claim(event)
        identity = digest(dict(episode_id=episode, claim=claim))
        opportunities.append(dict(opportunity_id=identity, claim=claim,
            event_type=type(event).__name__, event=asdict(event)))
    return opportunities, areas, holds


@dataclass(frozen=True)
class PhysicalEpisodeSession:
    repository: p.PostgresProjectionRepository

    def _validate(self):
        environment(self.repository)

    def _head(self, connection, episode):
        prefix = _prefix(episode)
        # PK(namespace,snapshot_id), C collation and a bounded range+LIMIT.
        row = connection.execute(f"SELECT snapshot_id FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id >= %s AND snapshot_id < %s ORDER BY snapshot_id DESC LIMIT 1",
                                 (REVISION, prefix, prefix[:-1]+";")).fetchone()
        if row is None:
            return None
        receipt, value = self.repository._read(connection, REVISION, row[0])
        self._revision(value, episode)
        require(row[0] == prefix + f'{value["sequence"]:010d}', "episode_head_corrupt")
        return receipt, value

    @staticmethod
    def _revision(value, episode):
        require(type(value) is dict and set(value) == set("schema_version policy episode_id sequence previous_sha256 previous_bindings members qualified_content_sha256 latest_retained_issued_at last_qualified_opportunities state holds opportunities seen_opportunities areas correction_notices observed_at detection_context".split()), "invalid_episode_revision")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["policy"] == POLICY)
        require(value["episode_id"] == _episode(episode))
        require(type(value["sequence"]) is int and 1 <= value["sequence"] <= MAX_MEMBERS + 1)
        require((value["sequence"] == 1) == (value["previous_sha256"] is None))
        if value["previous_sha256"] is not None:
            sha(value["previous_sha256"])
        require(type(value["members"]) is list and (0 if value["state"] == "held" else 1) <= len(value["members"]) <= MAX_MEMBERS)
        require(type(value["previous_bindings"]) is list and len(value["previous_bindings"]) <= value["sequence"] - 1)
        for binding in value["previous_bindings"]:
            validate_binding(binding)
            require(binding["episode_id"] == episode)
        require(value["state"] in {"confirmed_source_identity", "held"})
        for key in ("holds", "opportunities", "last_qualified_opportunities", "seen_opportunities", "areas", "correction_notices"):
            require(type(value[key]) is list)
        refs = value["qualified_content_sha256"]
        require(type(refs) is list and len(refs) <= len(value["members"]) and len(refs) == len(set(refs)))
        for ref in refs:
            sha(ref)
        require(set(refs) <= {member["content_sha256"] for member in value["members"]})
        require(value["state"] == "held" or bool(refs))
        if value["latest_retained_issued_at"] is not None:
            instant(value["latest_retained_issued_at"])
        else:
            require(not value["members"])
        if value["observed_at"] is not None:
            instant(value["observed_at"])
        else:
            require(value["state"] == "held")
        require(type(value["detection_context"]) is dict and set(value["detection_context"]) == {"cities", "as_of"})
        instant(value["detection_context"]["as_of"])

    def read_current(self, episode, *, expected_head=None):
        self._validate()
        with self.repository._connection() as connection:
            self.repository._validate(connection)
            head = self._head(connection, episode)
        require(head is not None, "episode_not_found")
        require(expected_head is None or head[0].canonical_sha256 == sha(expected_head), "episode_head_changed")
        return head

    def _records(self, members, connection=None):
        cache = {}
        items = []
        for member in members:
            require(type(member) is dict and set(member) == {"run_id", "run_sha256", "assertion_key", "content_sha256"})
            key = (uuid(member["run_id"]), sha(member["run_sha256"]))
            if key not in cache:
                source = CycloneSupplySession(self.repository, key[0])
                cache[key] = (source.read(expected_sha=key[1]) if connection is None else
                              source.read_on_connection(connection, expected_sha=key[1]))[2]
            matches = [row for row in cache[key]["rows"] if digest(row) == sha(member["content_sha256"])]
            require(len(matches) == 1 and assertion_key(matches[0]["advisory"]) == sha(member["assertion_key"]), "episode_member_changed")
            items.append((matches[0], cache[key]["source_outcome"]["status"]))
        return items

    def _items(self, members, connection=None):
        return [item for item, _ in self._records(members, connection)]

    @staticmethod
    def _previous_bindings(previous, previous_sha):
        bindings = list(previous["previous_bindings"]) if previous else []
        if previous and previous["state"] == "confirmed_source_identity":
            bindings.append(_binding(previous["episode_id"], previous_sha, previous["qualified_content_sha256"]))
        return bindings

    def _run_plan(self, run_id, run_sha256, *, operation_id, expected_heads, now, cities, connection=None):
        self._validate()
        uuid(operation_id)
        instant(now)
        require(type(expected_heads) is dict and type(cities) is list)
        cities = freeze(cities)
        require(len(cities) <= 50000, "episode_geography_bound")
        source = CycloneSupplySession(self.repository, run_id)
        _, advisories, envelope = (source.read(expected_sha=run_sha256) if connection is None else
                                   source.read_on_connection(connection, expected_sha=run_sha256))
        groups: dict = {}
        held = []
        for advisory, item in zip(advisories, envelope["rows"], strict=True):
            episode = episode_id(advisory)
            if episode is None:
                held.append(dict(content_sha256=digest(item), reason="source_identity_unqualified"))
            else:
                groups.setdefault(episode, []).append(dict(run_id=run_id, run_sha256=run_sha256,
                    assertion_key=assertion_key(item["advisory"]), content_sha256=digest(item)))
        if len(groups) > MAX_EPISODES:
            return [], [dict(reason="episode_inventory_bound", run_id=run_id, run_sha256=run_sha256)]
        require(set(expected_heads) == set(groups), "expected_episode_heads_required")
        results = []
        for episode, members in sorted(groups.items()):
            expected = expected_heads[episode]
            if expected is not None:
                sha(expected)
            payload = freeze(dict(schema_version=1, policy=POLICY, episode_id=episode, run_id=run_id,
                run_sha256=run_sha256, operation_id=operation_id, expected_head=expected, now=now,
                cities=cities, source_status=envelope["source_outcome"]["status"]))
            results.append((payload, members))
        return results, held

    def apply_retained_run(self, run_id, run_sha256, *, operation_id, expected_heads, now, cities):
        plan, held = self._run_plan(run_id, run_sha256, operation_id=operation_id,
            expected_heads=expected_heads, now=now, cities=cities)
        return dict(episodes=[self._apply(payload, members) for payload, members in plan], held=held)

    @staticmethod
    def lock_episode(connection, episode):
        lock = int(digest(_episode(episode))[:16], 16)
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock if lock < 2**63 else lock-2**64,))

    def apply_retained_run_on_connection(self, connection, run_id, run_sha256, *, operation_id, expected_heads, now, cities):
        """All source/member reads and episode writes use one caller transaction."""
        self._validate()
        self.repository._validate(connection)
        plan, held = self._run_plan(run_id, run_sha256, operation_id=operation_id,
            expected_heads=expected_heads, now=now, cities=cities, connection=connection)
        for payload, _ in plan:
            self.lock_episode(connection, payload["episode_id"])
        # Refuse every stale head before the first effect. Exact old operations
        # retain their existing idempotent result when used by a local caller.
        for payload, _ in plan:
            key = _prefix(payload["episode_id"])+payload["operation_id"]
            if self._operation(connection, key, payload) is None:
                head = self._head(connection, payload["episode_id"])
                require(payload["expected_head"] == (head[0].canonical_sha256 if head else None), "episode_head_changed")
        return dict(episodes=[self._apply_on_connection(connection, payload, members) for payload, members in plan], held=held)

    def _operation(self, connection, key, payload):
        found = connection.execute(f"SELECT 1 FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id=%s", (OPERATION, key)).fetchone()
        if not found:
            return None
        _, value = self.repository._read(connection, OPERATION, key)
        require(type(value) is dict and set(value) == {"payload", "result"} and value["payload"] == payload, "episode_operation_conflict")
        return value["result"]

    def _apply(self, payload, incoming):
        episode = payload["episode_id"]
        key = _prefix(episode) + payload["operation_id"]
        try:
            with self.repository._connection(writing=True) as connection:
                self.repository._validate(connection)
                self.lock_episode(connection, episode)
                result = self._apply_on_connection(connection, payload, incoming)
            return result
        except p.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise
            # Exactly one read reconciliation, with the original frozen payload.
            with self.repository._connection() as connection:
                self.repository._validate(connection)
                result = self._operation(connection, key, payload)
            require(result is not None, "episode_write_outcome_unknown")
            return result

    def _apply_on_connection(self, connection, payload, incoming):
        episode = payload["episode_id"]
        key = _prefix(episode)+payload["operation_id"]
        prior_result = self._operation(connection, key, payload)
        if prior_result is not None:
            return prior_result
        head = self._head(connection, episode)
        actual = head[0].canonical_sha256 if head else None
        require(payload["expected_head"] == actual, "episode_head_changed")
        previous = head[1] if head else None
        members = list(previous["members"]) if previous else []
        known = {member["content_sha256"] for member in members}
        qualified = {digest(item) for item, status in self._records(members, connection) if status == "success"}
        for member in incoming:
            content = member["content_sha256"]
            # A later complete run may qualify previously failed-only
            # bytes. Keep both immutable provenance references, without
            # renewing the advisory issuance or duplicating facts.
            if content not in known or (payload["source_status"] == "success" and content not in qualified):
                members.append(member)
                known.add(content)
                if payload["source_status"] == "success":
                    qualified.add(content)
        recoverable = bool(previous and "source_failed" in previous["holds"]
            and payload["source_status"] == "success"
            and max(instant(item["advisory"]["issued_at"]) for item in self._items(incoming, connection))
                >= instant(previous["latest_retained_issued_at"]))
        # Full immutable source inventory already exists if this bounded
        # projection cannot grow. No pruning or arbitrary event winner.
        limit = len(members) > MAX_MEMBERS or (previous is not None and previous["sequence"] >= MAX_MEMBERS)
        if previous and "episode_member_bound" in previous["holds"]:
            result = dict(episode_id=episode, status="held", reason="episode_member_bound", revision_sha256=actual)
        elif limit:
            value = self._bounded_hold(payload, previous, actual)
            encoded, fields = p._snapshot(value)
            receipt = self.repository._record(connection, REVISION, _prefix(episode)+f'{value["sequence"]:010d}', encoded, fields)
            result = dict(episode_id=episode, status="held", reason="episode_member_bound", revision_sha256=receipt.canonical_sha256)
        elif previous and members == previous["members"] and not recoverable:
            result = dict(episode_id=episode, status="duplicate", revision_sha256=actual)
        else:
            value = self._next(payload, previous, actual, members, incoming, connection)
            encoded, fields = p._snapshot(value)
            receipt = self.repository._record(connection, REVISION, _prefix(episode)+f'{value["sequence"]:010d}', encoded, fields)
            result = dict(episode_id=episode, status="held" if value["state"] == "held" else "committed",
                          revision_sha256=receipt.canonical_sha256)
        encoded, fields = p._snapshot(dict(payload=payload, result=result))
        self.repository._record(connection, OPERATION, key, encoded, fields)
        return result

    def _bounded_hold(self, payload, previous, previous_sha):
        # Incoming membership is unassigned, not truncated. Its complete retained
        # run is bound in the notice/operation. A terminal head blocks stale use.
        bindings = self._previous_bindings(previous, previous_sha)
        value = dict(schema_version=1, policy=POLICY, episode_id=payload["episode_id"],
            sequence=previous["sequence"]+1 if previous else 1, previous_sha256=previous_sha,
            previous_bindings=bindings, members=previous["members"] if previous else [],
            state="held", holds=sorted(set((previous["holds"] if previous else []) + ["episode_member_bound"])), opportunities=[],
            seen_opportunities=previous["seen_opportunities"] if previous else [], areas=[],
            correction_notices=[dict(reason="unassigned_retained_supply", run_id=payload["run_id"],
                                     run_sha256=payload["run_sha256"])],
            observed_at=previous["observed_at"] if previous else None,
            latest_retained_issued_at=previous["latest_retained_issued_at"] if previous else None,
            qualified_content_sha256=previous["qualified_content_sha256"] if previous else [],
            last_qualified_opportunities=previous["last_qualified_opportunities"] if previous else [],
            detection_context=dict(cities=payload["cities"], as_of=payload["now"]))
        self._revision(value, payload["episode_id"])
        return value

    def _next(self, payload, previous, previous_sha, members, incoming, connection=None):
        records = self._records(members, connection)
        # Membership proves retention, not successful acquisition. Scientific
        # consumers receive only unique assertions from complete-success runs.
        items = list({digest(item): item for item, _ in records}.values())
        qualified = {digest(item): item for item, status in records if status == "success"}
        latest_retained = max(items, key=lambda item: instant(item["advisory"]["issued_at"]))["advisory"]["issued_at"]
        latest_qualified = max(qualified.values(), key=lambda item: instant(item["advisory"]["issued_at"]))["advisory"]["issued_at"] if qualified else None
        episode = payload["episode_id"]
        require(all(episode_id(decode_advisory(item["advisory"])) == episode for item in items), "episode_membership_changed")
        previous_items = self._items(previous["members"], connection) if previous else []
        holds = list(previous["holds"]) if previous and previous["state"] == "held" else []
        incoming_latest = max(instant(item["advisory"]["issued_at"]) for item in self._items(incoming, connection))
        if (payload["source_status"] == "success" and latest_qualified is not None
                and incoming_latest >= instant(latest_retained)):
            holds = [hold for hold in holds if hold != "source_failed"]
        elif payload["source_status"] != "success" or latest_qualified is None or instant(latest_qualified) < instant(latest_retained):
            holds.append("source_failed")
        if any(re.fullmatch(r"[0-9]+[A-Za-z]?", item["advisory"]["advisory_number"]) is None for item in items):
            holds.append("source_advisory_number_unresolved")
        assertions: dict = {}
        times: dict = {}
        for item in items:
            assertions.setdefault(assertion_key(item["advisory"]), set()).add(digest(item))
            times.setdefault(instant(item["advisory"]["issued_at"]), set()).add(digest(item))
        if any(len(values) > 1 for values in (*assertions.values(), *times.values())):
            holds.append("identity_or_revision_conflict")
        old_max = max((instant(item["advisory"]["issued_at"]) for item in previous_items), default=None)
        previous_content = {digest(item) for item in previous_items}
        if old_max is not None and any(instant(item["advisory"]["issued_at"]) < old_max for item in items if digest(item) not in previous_content):
            holds.append("late_evidence_derivation_review")
        if previous and previous["detection_context"]["cities"] != payload["cities"]:
            holds.append("geography_context_changed")
        seen = list(previous["seen_opportunities"]) if previous else []
        opportunities, areas, forecast_holds = ([], [], []) if holds else _detect(episode, list(qualified.values()),
            previous["last_qualified_opportunities"] if previous else [], payload["cities"], payload["now"])
        notices = list(previous["correction_notices"]) if previous else []
        if "identity_or_revision_conflict" in holds:
            notices.append(dict(reason="source_revision_conflict", old_revision_sha256=previous_sha,
                affected_opportunity_ids=seen, conflicting_content_sha256=[digest(item) for item in items]))
        previous_bindings = self._previous_bindings(previous, previous_sha)
        value = dict(schema_version=1, policy=POLICY, episode_id=episode,
            sequence=previous["sequence"]+1 if previous else 1, previous_sha256=previous_sha,
            previous_bindings=previous_bindings, members=members,
            state="held" if holds else "confirmed_source_identity", holds=sorted(set(holds+forecast_holds)),
            opportunities=opportunities, seen_opportunities=sorted(set(seen+[row["opportunity_id"] for row in opportunities])),
            areas=areas, correction_notices=notices,
            observed_at=latest_qualified, latest_retained_issued_at=latest_retained,
            qualified_content_sha256=list(qualified),
            last_qualified_opportunities=(previous["last_qualified_opportunities"] if previous else []) if holds else opportunities,
            detection_context=dict(cities=payload["cities"], as_of=payload["now"]))
        self._revision(value, episode)
        return value

    def prepare_story_context(self, episode, revision_sha):
        receipt, value = self.read_current(episode, expected_head=revision_sha)
        require(value["state"] == "confirmed_source_identity", "episode_consumer_held")
        qualified = list(dict.fromkeys(digest(item) for item, status in self._records(value["members"]) if status == "success"))
        require(qualified == value["qualified_content_sha256"], "episode_qualified_members_changed")
        self.read_current(episode, expected_head=revision_sha)
        binding = _binding(episode, receipt.canonical_sha256, qualified)
        context = EpisodeContext(p._canonical(binding), p._canonical(value["previous_bindings"]+[binding]))
        return context, value

    def retain_relationship(self, *, proposal_id, hazard, kind, evidence_refs, expected_heads, now):
        """Retain ambiguity; never resolve aliases, move members or union memory.

        A local operator may propose a relationship using exact retained evidence.
        This gives no scientific verdict. Cyclone participants are held atomically
        at all expected heads; fire/flood reports remain unconfirmed assertions.
        """
        self._validate()
        uuid(proposal_id)
        instant(now)
        require(hazard in {"cyclone", "heat", "fire", "flood"} and kind in {"split", "merge", "uncertain_identity"})
        require(type(evidence_refs) is list and 1 <= len(evidence_refs) <= MAX_ALTERNATIVES, "relationship_evidence_bound")
        require(type(expected_heads) is dict and len(expected_heads) <= MAX_ALTERNATIVES, "relationship_alternative_bound")
        require((hazard == "cyclone") == bool(expected_heads), "relationship_participants_required")
        for episode, head in expected_heads.items():
            _episode(episode)
            sha(head)
        for ref in evidence_refs:
            require(type(ref) is dict and set(ref) == {"namespace", "snapshot_id", "sha256"})
            p._identifier(ref["namespace"])
            p._identifier(ref["snapshot_id"])
            sha(ref["sha256"])
        payload = freeze(dict(schema_version=1, proposal_id=proposal_id, hazard=hazard, kind=kind,
            evidence_refs=evidence_refs, expected_heads=expected_heads, now=now,
            status="unconfirmed_relationship", evidence_class="retained_assertion_unadjudicated"))
        key = "relationship:"+proposal_id
        try:
            with self.repository._connection(writing=True) as connection:
                self.repository._validate(connection)
                for episode in sorted(expected_heads):
                    lock = int(digest(episode)[:16], 16)
                    connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock if lock < 2**63 else lock-2**64,))
                prior = self._operation(connection, key, payload)
                if prior is not None:
                    return prior
                for ref in evidence_refs:
                    receipt, _ = self.repository._read(connection, ref["namespace"], ref["snapshot_id"])
                    require(receipt.canonical_sha256 == ref["sha256"], "relationship_evidence_changed")
                outcomes = []
                for episode, expected in sorted(expected_heads.items()):
                    head = self._head(connection, episode)
                    require(head is not None and head[0].canonical_sha256 == expected, "episode_head_changed")
                    previous = head[1]
                    require(previous["sequence"] < MAX_MEMBERS and previous["members"], "relationship_revision_bound")
                    value = freeze(previous)
                    value.update(sequence=previous["sequence"]+1, previous_sha256=expected,
                        previous_bindings=self._previous_bindings(previous, expected),
                        state="held", holds=sorted(set(previous["holds"]+["relationship_resolution_required"])), opportunities=[])
                    value["correction_notices"].append(dict(reason="unconfirmed_relationship", proposal_sha256=digest(payload),
                                                          affected_opportunity_ids=previous["seen_opportunities"]))
                    self._revision(value, episode)
                    raw, fields = p._snapshot(value)
                    receipt = self.repository._record(connection, REVISION, _prefix(episode)+f'{value["sequence"]:010d}', raw, fields)
                    outcomes.append(dict(episode_id=episode, revision_sha256=receipt.canonical_sha256, status="held"))
                raw, fields = p._snapshot(payload)
                receipt = self.repository._record(connection, PROPOSAL, digest(payload), raw, fields)
                result = dict(proposal_sha256=receipt.canonical_sha256, status="unconfirmed_relationship", episodes=outcomes)
                raw, fields = p._snapshot(dict(payload=payload, result=result))
                self.repository._record(connection, OPERATION, key, raw, fields)
            return result
        except p.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise
            with self.repository._connection() as connection:
                self.repository._validate(connection)
                result = self._operation(connection, key, payload)
            require(result is not None, "episode_write_outcome_unknown")
            return result

    def retain_heat_proposals(self, supply, snapshot):
        """Actual retained P18 prepass; station proximity never proves a heatwave."""
        from src.orchestrator.sources.open_meteo import replay_retained_ghcn_supply
        self._validate()
        require(supply.repository is self.repository, "grouping_repository_mismatch")
        result = replay_retained_ghcn_supply(supply, snapshot)
        require(result["status"] == "available", "heat_supply_unavailable")
        proposals = []
        for cluster in result["cluster_candidates"]:
            value = dict(schema_version=1, hazard="heat", status="unconfirmed_grouping",
                source_run_id=supply.supply_run_id, source_receipt_sha256=result["receipt_sha256"],
                grouping=cluster, holds=["physical_episode_not_established", "source_calendar_utc_unresolved"])
            receipt = self.repository.record(PROPOSAL, digest(value), value)
            proposals.append(dict(proposal_sha256=receipt.canonical_sha256, **value))
        return dict(proposals=proposals, source_preview=result)
