"""One retained invented-local GHCN run through the actual shared HTTP authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import time
from uuid import uuid4

from src.commands import postgres_ghcn_source_results as domain, postgres_source_results as shared
from src.commands.schema import Command, Principal, canonical_json, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.orchestrator.source_result_client import SourceResultClient, utc_now
from src.storage import ghcn_runtime_inputs as inputs
from src.storage.cyclone_supply import digest, require, uuid
from src.storage.scientific_supply import ScientificSupplySession


@dataclass(frozen=True)
class GhcnSourceResultClient(SourceResultClient):
    def context(self):
        code, value = self.http("/ghcn-source-context")
        require(code == 200, "ghcn_context_unavailable")
        return value

    def capture(self, run_id, baseline, responses, *, producer_revision, source_now, started_at, completed_at):
        """Real parser only; response fixtures carry bytes, never verified effects."""
        self.validate()
        uuid(run_id)
        require(type(baseline) is inputs.Baseline, "ghcn_baseline_required")
        require(type(responses) is list and len(responses) <= inputs.MAX_RECEIPTS
                and all(type(r) is inputs.InventedResponse for r in responses), "ghcn_response_capacity")
        require(utc_datetime(started_at) <= utc_datetime(source_now) <= utc_datetime(completed_at), "ghcn_capture_time")
        require(all(utc_datetime(started_at) <= utc_datetime(r.retrieved_at) <= utc_datetime(completed_at) for r in responses), "ghcn_capture_time")
        with self.repository._connection() as c:
            self.repository._validate(c)
            require(shared.optional(c, inputs.DEPENDENCIES, "run:"+run_id) is None, "ghcn_run_already_started")
        context = self.context()
        require(context["baseline_pins"] == dict(database_sha256=baseline.database_sha256, manifest_sha256=baseline.manifest_sha256), "ghcn_baseline_changed")
        dep_receipt = shared.retain_exact(self.repository, inputs.DEPENDENCIES, "run:"+run_id, context)
        anchor = time.monotonic_ns()
        # Preserve bytes and read them back before any scientific interpretation.
        metadata = [inputs.retain_raw(self.repository, r) for r in responses]
        with self.repository._connection() as c:
            self.repository._validate(c)
            retained = inputs.read_responses(c, metadata)
        bundles, countries, metrics, effects, descriptor = inputs.derive(baseline, context["state"], retained,
            now=source_now, config=context["configuration"])
        supply = ScientificSupplySession(self.repository, run_id, "capture", started_at, producer_revision)
        receipt, _, _, _ = supply.capture(bundles, countries, metrics)
        value = dict(schema_version=1, source="ghcn-daily", supply_run_id=run_id, producer_revision=producer_revision,
            dependency_sha256=dep_receipt.canonical_sha256, baseline=descriptor, supply_sha256=receipt.canonical_sha256,
            acquisition_started_at=started_at, acquisition_completed_at=completed_at,
            duration_ms=max(0,(time.monotonic_ns()-anchor)//1000000), source_now=source_now,
            responses=metadata, effects=effects, effects_sha256=digest(effects), evidence_class="invented_local_capture")
        shared.retain_exact(self.repository, inputs.INPUT, "run:"+run_id, value)
        return dict(supply_run_id=run_id, runtime_input_sha256=digest(value), provider_transport="not_attempted")

    def enroll(self, run_id, *, command_id=None, now=None):
        self.validate()
        uuid(run_id)
        at = now or utc_now()
        command_id = uuid(command_id or str(uuid4()))
        with self.repository._connection() as c:
            self.repository._validate(c)
            prior = shared.optional(c, inputs.SUBMISSION, command_id)
            if prior is not None:
                require(prior[1]["supply_run_id"] == run_id, "ghcn_submission_changed")
                return self.resume(command_id)
            receipt, value = self.repository._read(c, inputs.INPUT, "run:"+run_id)
        body = dict(command_id=command_id, action=domain.ACTION, requested_at=utc_text(at),
            expires_at=utc_text(at+timedelta(minutes=10)), targets=[], payload=dict(supply_run_id=run_id,
                supply_sha256=value["supply_sha256"], runtime_input_sha256=receipt.canonical_sha256,
                dependency_sha256=value["dependency_sha256"], expected_policy_sha256=digest(current_editorial_policy())))
        Command.from_request(body, Principal("local-shape-validation", "editor", "not-authentication"), environment="local", now=at)
        shared.retain_exact(self.repository, inputs.SUBMISSION, command_id, dict(schema_version=1,
            supply_run_id=run_id, runtime_input_sha256=receipt.canonical_sha256, request=body))
        return self.resume(command_id)

    def resume(self, command_id):
        self.validate()
        with self.repository._connection() as c:
            self.repository._validate(c)
            _, descriptor = domain.read_submission(c, command_id)
        code, value = self.http("/commands/"+command_id)
        if code == 404 and value.get("code") == "command_not_found":
            code, value = self.http("/commands", body=descriptor["request"])
        require(code in {200,202}, "ghcn_command_not_acknowledged")
        require(value.get("recoverable_command") in (None, descriptor["request"]), "ghcn_command_changed")
        return dict(command_id=command_id, supply_run_id=descriptor["supply_run_id"], command=value)

    def readback(self, run_id):
        code, value = self.http("/ghcn-source-runs/"+uuid(run_id))
        require(code == 200, "ghcn_run_unavailable")
        return value

    def prepare_request(self, run_id, selection, *, baseline, now=None):
        """Fresh post-correction memory + existing qualification/intern/writer seam."""
        from src.orchestrator.sources import open_meteo as source
        from src.commands.postgres_authority import PostgresCommandAuthority
        from src.two_bot.ghcn_claim_view import resolve
        from src.two_bot.bundle_capture import capture_bundle
        from src.two_bot.memory import build_memory_slice
        from src.two_bot.writer import anthropic_writer_request, build_writer_user_prompt, WRITER_PROVIDER
        self.validate()
        inputs.fixed(selection, "station_id signal_date signal_field")
        first = self.readback(run_id)
        require(first["status"] == "applied" and first["source_status"] == "success", "ghcn_source_not_eligible")
        before = self.context()
        require(not before["delivery"]["protection_codes"], "ghcn_delivery_protected")
        code, current = self.http("/state")
        require(code == 200, "ghcn_state_unavailable")
        at = now or utc_now()
        with self.repository._connection() as c:
            self.repository._validate(c)
            _, value = self.repository._read(c, inputs.INPUT, "run:"+run_id)
            _, result = self.repository._read(c, inputs.RESULT, "run:"+run_id)
            _, descriptor = domain.read_submission(c, result["command_id"])
        require(max(utc_datetime(value["acquisition_completed_at"]), utc_datetime(descriptor["request"]["requested_at"])) <= at < utc_datetime(descriptor["request"]["expires_at"]), "ghcn_preparation_stale")
        supply = ScientificSupplySession(self.repository, run_id, "replay")
        # Existing main-thread/single-process and suppression isolation is retained.
        preview = source.replay_retained_ghcn_supply(supply, current["state"], routing_mode="ghcn")
        require(preview["status"] == "available", "ghcn_prepass_unavailable")
        require(any(r["station_id"] == selection["station_id"] and r["signal_date"] == selection["signal_date"]
                    for r in preview["individual_bundle_keys"]), "ghcn_individual_not_selected")
        _, bundles, _, _ = supply.read()
        chosen = [b for b in bundles if b.station_id == selection["station_id"] and b.signal_date.isoformat() == selection["signal_date"]]
        require(len(chosen) == 1 and 0 <= (at.date()-chosen[0].signal_date).days <= inputs.ghcn.MAX_OBS_AGE_DAYS, "ghcn_observation_stale")
        require(WRITER_PROVIDER == "anthropic", "ghcn_writer_provider_unsupported")
        # Reuse this exact local repository and operator-pinned baseline. Paths
        # never arrive through HTTP or the reference-bearing claim view.
        authority = PostgresCommandAuthority(socket_directory=self.repository.socket_directory,
            database=self.repository.database,user=self.repository.user,port=self.repository.port,
            environment=self.repository.environment)
        authority.configure_ghcn_source_results(baseline)
        resolved = resolve(authority,run_id,selection)
        bundle = resolved.view
        captured = capture_bundle(bundle)
        memory = build_memory_slice(current["state"], bundle, now=at)
        request = anthropic_writer_request(build_writer_user_prompt(bundle, memory))
        code, final = self.http("/state")
        finished = now or utc_now()
        require(at <= finished < utc_datetime(descriptor["request"]["expires_at"]), "ghcn_preparation_stale")
        require(code == 200 and final["state_version"] == current["state_version"] and final["state"] == current["state"]
                and final["editorial_policy"] == current["editorial_policy"] and self.context() == before
                and self.readback(run_id) == first, "ghcn_authority_changed")
        return dict(writer_request=request, bundle=captured.payload(), memory=memory.to_dict(),
            capture_scope="selected_ghcn_claim_view_v1", full_source=resolved.reference,
            full_story_sha256=resolved.full_sha256, claim_view_sha256=resolved.view_sha256,
            input_sizes={**resolved.counters, "writer_request_bytes":len(canonical_json(request).encode())},
            source_run=first, source_prepass=preview, bundle_sha256=digest(captured.payload()), memory_sha256=digest(memory.to_dict()),
            policy_sha256=digest(current["editorial_policy"]), provider_transport="not_attempted", paid_grant=None,
            draft_saved=False, callback_enrollment="not_supported", publication_enabled=False)
