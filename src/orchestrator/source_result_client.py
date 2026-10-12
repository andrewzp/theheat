"""Explicit invented-local NHC producer and frozen command resumption.

The command worker is separate. No acquisition retry, provider execution,
callback ownership, queue drain, production backend or credential discovery.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
import time
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4

from src.commands import postgres_source_results as domain
from src.commands.preview_ingress import safe_environment, strict_json
from src.commands.schema import Command, MAX_COMMAND_BYTES, Principal, utc_text
from src.editorial.policy import current_editorial_policy
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import CycloneSupplySession, digest, environment, freeze, require, uuid
from src.storage.physical_events import MAX_EPISODES, PhysicalEpisodeSession


def utc_now():
    return datetime.now(UTC)


@dataclass(frozen=True)
class SourceResultClient:
    repository: p.PostgresProjectionRepository
    endpoint: str
    origin: str
    username: str = field(repr=False)
    password: str = field(repr=False)

    def validate(self):
        safe_environment()
        environment(self.repository)
        require(self.repository.environment == "local", "local_source_authority_required")
        for value in (self.endpoint, self.origin):
            parsed = urlsplit(value)
            require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port is not None
                and not any((parsed.username, parsed.password, parsed.path, parsed.query, parsed.fragment)), "local_source_endpoint_required")
        require(type(self.username) is str and type(self.password) is str and ":" not in self.username
            and 1 <= len(self.username) <= 200 and 1 <= len(self.password) <= 200, "local_source_identity_required")

    def http(self, path, *, body=None):
        self.validate()
        parsed = urlsplit(self.endpoint)
        raw = p._canonical(body) if body is not None else None
        require(raw is None or len(raw) <= MAX_COMMAND_BYTES, "source_command_bound")
        auth = base64.b64encode((self.username+":"+self.password).encode()).decode()
        connection = HTTPConnection("127.0.0.1", parsed.port, timeout=10)
        try:
            connection.request("GET" if body is None else "POST", path, body=raw,
                headers={"Authorization": "Basic "+auth, "Origin": self.origin, "Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(p.MAX_BYTES+1)
            require(len(data) <= p.MAX_BYTES, "source_readback_bound")
            value = strict_json(data)
            require(type(value) is dict, "source_readback_invalid")
            return response.status, value
        finally:
            connection.close()

    def enroll(self, run_id, *, command_id=None, now=None):
        """Explicit recovery before a descriptor may use current heads once."""
        self.validate()
        now = now or utc_now()
        command_id = uuid(command_id or str(uuid4()))
        with self.repository._connection() as c:
            self.repository._validate(c)
            prior = domain.optional(c, domain.SUBMISSION, command_id)
            if prior is not None:
                _, descriptor = domain.read_submission(self.repository, c, command_id)
                require(descriptor["supply_run_id"] == run_id, "source_submission_changed")
                return self.resume(command_id)
            receipt, value, _, advisories, _ = domain.read_input(self.repository, c, run_id)
            identities = domain.inventory(advisories)
            if len(identities) > MAX_EPISODES:
                return dict(status="held", reason="episode_inventory_bound", supply_run_id=run_id,
                    runtime_input_sha256=receipt.canonical_sha256, command_id=None)
            session = PhysicalEpisodeSession(self.repository)
            heads = {}
            for episode in identities:
                head = session._head(c, episode)
                heads[episode] = head[0].canonical_sha256 if head else None
        body = dict(command_id=command_id, action=domain.ACTION, requested_at=utc_text(now),
            expires_at=utc_text(now+timedelta(minutes=10)), targets=[], payload=dict(
                supply_run_id=run_id, supply_sha256=value["supply_sha256"], runtime_input_sha256=receipt.canonical_sha256,
                expected_episode_heads=heads, expected_policy_sha256=digest(current_editorial_policy())))
        # Validate request syntax without pretending this local value authenticates
        # the request. The real HTTP adapter supplies and rechecks actor identity.
        Command.from_request(body, Principal("local-shape-validation", "editor", "not-authentication"), environment="local", now=now)
        descriptor = dict(schema_version=1, supply_run_id=run_id, runtime_input_sha256=receipt.canonical_sha256, request=body)
        domain.retain_exact(self.repository, domain.SUBMISSION, command_id, descriptor)
        return self.resume(command_id)

    def resume(self, command_id):
        """Read, then at most one POST of the original frozen request."""
        self.validate()
        with self.repository._connection() as c:
            self.repository._validate(c)
            _, descriptor = domain.read_submission(self.repository, c, command_id)
        code, value = self.http("/commands/"+command_id)
        if code == 404 and value.get("code") == "command_not_found":
            code, value = self.http("/commands", body=descriptor["request"])
        require(code in {200, 202}, "source_command_not_acknowledged")
        recovered = value.get("recoverable_command")
        require(recovered is None or recovered == descriptor["request"], "source_command_changed")
        return dict(command_id=command_id, supply_run_id=descriptor["supply_run_id"], command=value)

    def readback(self, run_id):
        code, value = self.http("/source-runs/"+uuid(run_id))
        require(code == 200, "source_run_unavailable")
        return value

    def prepare_requests(self, run_id, *, now=None):
        """Fresh authority -> actual episode/intern/memory/writer-request seam."""
        from src.orchestrator.cyclone_episodes import prepare_episode_requests
        first = self.readback(run_id)
        require(first["status"] == "applied" and first["source_status"] == "success", "source_run_not_eligible")
        require(all(row["current"] and row["status"] in {"committed", "duplicate"} for row in first["episodes"]), "source_episode_superseded")
        code, state = self.http("/state")
        require(code == 200, "source_state_unavailable")
        at = utc_text(now or utc_now())
        requests = []
        for row in first["episodes"]:
            requests.extend(prepare_episode_requests(PhysicalEpisodeSession(self.repository), row["episode_id"], row["revision_sha256"], state["state"], now=at))
        code, current = self.http("/state")
        require(code == 200 and current["state_version"] == state["state_version"] and current["state"] == state["state"]
            and current["editorial_policy"] == state["editorial_policy"], "source_authority_changed")
        require(self.readback(run_id) == first, "source_episode_superseded")
        return dict(requests=requests, source_run=first, state_version=state["state_version"], provider_transport="not_attempted", publication_enabled=False)


@dataclass(frozen=True)
class SourceResultLane:
    client: SourceResultClient
    supply_run_id: str
    producer_revision: str
    cities: list
    clock: Callable = utc_now

    def capture_prepare(self, snapshot, fetch_fn):
        from src.data import nhc
        from src.data.source_status import SourceFetchError
        self.client.validate()
        uuid(self.supply_run_id)  # Fixed before the first source request.
        require(fetch_fn is nhc.fetch_active_cyclones, "explicit_nhc_source_required")
        # No implicit reacquisition, including after a crash before aux retention.
        with self.client.repository._connection() as c:
            self.client.repository._validate(c)
            from src.storage.cyclone_supply import NAMESPACE
            require(domain.optional(c, NAMESPACE, "run:"+self.supply_run_id) is None, "source_run_already_retained")
        cities = freeze(self.cities)
        require(type(cities) is list and len(cities) <= 50000, "source_geography_bound")
        start = utc_text(self.clock())
        monotonic_start = time.monotonic_ns()
        observations = []
        status = "success"
        try:
            advisories = fetch_fn(strict=True, retention_observer=lambda advisory, metadata: observations.append((advisory, metadata)))
        except SourceFetchError:
            advisories = [row[0] for row in observations]
            status = "failed"
        end = utc_text(self.clock())
        duration = max(0, (time.monotonic_ns()-monotonic_start)//1000000)
        # Retain observed rows even if legacy filtering removes one. This matches
        # the existing observer lane rather than manufacturing source completeness.
        retained = [row[0] for row in observations]
        require(not advisories or observations, "source_observation_missing")
        supply = CycloneSupplySession(self.client.repository, self.supply_run_id, start, self.producer_revision)
        receipt, _, _ = supply.capture(retained, {"status": status}, observations=observations)
        document = dict(schema_version=1, source="nhc", supply_run_id=self.supply_run_id,
            supply_sha256=receipt.canonical_sha256, producer_revision=self.producer_revision,
            acquisition_started_at=start, acquisition_completed_at=end, duration_ms=duration,
            cities=cities, cities_sha256=digest(cities), evidence_class="invented_local_capture")
        domain.retain_input(self.client.repository, document)
        return self.client.enroll(self.supply_run_id, now=self.clock())
