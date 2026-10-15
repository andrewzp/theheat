"""Explicit local immutable reference inputs and read-only producer joins.

This adapter is not a source collector, mutable metrics store or verdict editor.
The command transaction hook is intentionally separate from input retention.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.commands.schema import utc_datetime, utc_text
from src.evaluation import coverage as e
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import environment
from src.storage.retained_reports import (ARTIFACT, RetainedReportSession, digest, identifier, sha)

OPERATION = "coverage-input-operation-v1"
MAX_VERSIONS = 512


def ref(receipt):
    return dict(namespace=receipt.namespace, snapshot_id=receipt.snapshot_id, sha256=receipt.canonical_sha256)


def record_time(receipt):
    # Repository timestamps come from PostgreSQL; never use source issue time
    # to pretend an artifact was already in the retained execution trace.
    return utc_text(datetime.fromisoformat(receipt.created_at))


def _prefix(identity):
    return digest(identifier(identity))+":"


def _lock(c, identity):
    value = int(digest(identity)[:16], 16)
    c.execute("SELECT pg_advisory_xact_lock(%s)", (value if value < 2**63 else value-2**64,))


def lock_current_heads(c, report_ids, episode_ids):
    """P21 hierarchy: all report lineage locks, then all physical episode locks."""
    for identity in sorted(set(report_ids)):
        _lock(c, identity)
    for identity in sorted(set(episode_ids)):
        _lock(c, identity)


@dataclass(frozen=True)
class CoverageSession:
    repository: p.PostgresProjectionRepository
    protocol_refs: tuple = ()
    decision_imports: tuple = ()
    report_decision_refs: tuple = ()

    def validate(self):
        environment(self.repository)
        e.require(type(self.protocol_refs) is tuple and len(self.protocol_refs) <= 16)
        e.references(list(self.protocol_refs), 16, {ARTIFACT})
        e.require(type(self.decision_imports) is tuple and len(self.decision_imports) <= 32)
        for item in self.decision_imports:
            e.fixed(item, "document_sha256 response_ref packet_ref")
            sha(item["document_sha256"])
            e.reference(item["response_ref"], {ARTIFACT})
            e.reference(item["packet_ref"], {ARTIFACT})

    @property
    def reports(self):
        return RetainedReportSession(self.repository, self.report_decision_refs)

    def read_ref(self, value):
        e.reference(value)
        receipt, document = self.repository.read(value["namespace"], value["snapshot_id"])
        e.require(ref(receipt) == value, "coverage_reference_changed")
        return receipt, document

    def artifact(self, value):
        e.reference(value, {ARTIFACT})
        receipt, document, raw = self.reports.read_artifact(value["snapshot_id"])
        e.require(ref(receipt) == value, "coverage_reference_changed")
        return receipt, document, raw

    def _head(self, c, namespace, identity):
        prefix = _prefix(identity)
        row = c.execute(f"SELECT snapshot_id FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id >= %s AND snapshot_id < %s ORDER BY snapshot_id DESC LIMIT 1",
                        (namespace, prefix, prefix[:-1]+";")).fetchone()
        if row is None:
            return None
        receipt, value = self.repository._read(c, namespace, row[0])
        e.fixed(value, "sequence document")
        e.require(type(value["sequence"]) is int and 1 <= value["sequence"] <= MAX_VERSIONS)
        e.require(row[0] == prefix+f'{value["sequence"]:010d}')
        key = "set_id" if namespace == e.SET else "decision_id"
        e.require(value["document"][key] == identity, "coverage_identity_changed")
        return receipt, value

    def decision_document(self, value):
        value = e.decision(value)
        candidates = [item for item in self.decision_imports if item["document_sha256"] == digest(value)]
        e.require(len(candidates) == 1, "coverage_human_import_untrusted")
        imported = candidates[0]
        e.require(imported["response_ref"] == value["human_response_ref"], "coverage_human_response_changed")
        _, packet, _ = self.artifact(imported["packet_ref"])
        e.require(packet["sha256"] == value["packet_sha256"], "coverage_human_packet_changed")
        _, _, raw = self.artifact(imported["response_ref"])
        e.require(bool(raw.strip()), "coverage_human_response_empty")
        for anchor in value["source_anchor_refs"]:
            _, artifact, content = self.reports.read_artifact(anchor["artifact_id"])
            e.require(artifact["sha256"] == anchor["content_sha256"] and anchor["end"] <= len(content), "coverage_human_anchor_changed")
            e.require(artifact["metadata"]["media_type"] == "text/plain", "coverage_human_anchor_type")
            try:
                content[anchor["start"]:anchor["end"]].decode("utf-8")
            except UnicodeError:
                raise e.CoverageError("coverage_human_anchor_changed") from None
        return value

    def read_decision(self, value):
        receipt, wrapper = self.read_ref(value)
        e.require(receipt.namespace == e.DECISION)
        e.fixed(wrapper, "sequence document")
        document = self.decision_document(wrapper["document"])
        with self.repository._connection() as c:
            self.repository._validate(c)
            current = self._head(c, e.DECISION, document["decision_id"])
        e.require(current and current[0] == receipt, "coverage_human_decision_superseded")
        return receipt, document

    def evaluation_decision(self, pointer):
        """Pass verified wrapper and DB receipt time, never decision recorded_at."""
        receipt, document = self.read_decision(pointer)
        _, wrapper = self.read_ref(pointer)
        e.require(wrapper["document"] == document, "coverage_retained_input_changed")
        return e.RetainedInput.create(reference=ref(receipt), wrapper=wrapper, retained_at=record_time(receipt))

    def evaluation_set(self, set_id, expected_sha=None):
        """Caller supplies the journal accepted_at cutoff to the pure evaluator."""
        receipt, document = self.read_set(set_id, expected_sha)
        _, wrapper = self.read_ref(ref(receipt))
        e.require(wrapper["document"] == document, "coverage_retained_input_changed")
        return e.RetainedInput.create(reference=ref(receipt), wrapper=wrapper, retained_at=record_time(receipt))

    def set_document(self, value):
        value = e.reference_set(value)
        protocol = value["selection_protocol"]
        e.require(protocol["protocol_ref"] in self.protocol_refs, "coverage_protocol_untrusted")
        self.artifact(protocol["protocol_ref"])
        decisions = {digest(reference): self.read_decision(reference)[1] for reference in value["human_decision_refs"]}
        subject_questions = set()
        for decision in decisions.values():
            subject = decision["subject"]
            e.require(subject["set_id"] == value["set_id"], "coverage_decision_subject_changed")
            question_key = subject["unit_id"], decision["question_id"]
            e.require(question_key not in subject_questions, "coverage_decision_ambiguous")
            subject_questions.add(question_key)
        lineages = set()
        for candidate in value["units"]:
            documents = []
            for report_ref in candidate["report_refs"]:
                e.require(report_ref["lineage_id"] not in lineages, "coverage_grouping_record_required")
                lineages.add(report_ref["lineage_id"])
                receipt, report = self.reports.read_current(report_ref["lineage_id"], report_ref["report_sha256"])
                claims = [claim for claim in report["claims"] if claim["claim_id"] in report_ref["claim_ids"]]
                e.require(len(claims) == len(report_ref["claim_ids"]), "coverage_report_claim_changed")
                documents.append((receipt, report, claims))
            # Labels retain exact source wording; Unknown is explicit absence.
            for key in ("hazard_labels", "region_memberships"):
                for label in candidate[key]:
                    matches = [(report, claims) for receipt, report, claims in documents if ref(receipt) == label["evidence_ref"]]
                    e.require(len(matches) == 1, "coverage_label_provenance_missing")
                    report, claims = matches[0]
                    allowed = report["hazards"] if key == "hazard_labels" else [claim["geography"]["reported_scope"] for claim in claims]
                    e.require(label["label"] in ["Unknown", *allowed], "coverage_label_changed")
            for key, time_value in candidate["time_fields"].items():
                if time_value is not None:
                    e.require(key != "first_available_at" and any(claim["times"].get(key) == time_value
                        for _, _, claims in documents for claim in claims), "coverage_time_provenance_missing")
            e.require(candidate["deadline"]["at"] is None, "coverage_deadline_policy_unqualified")
            for decision in decisions.values():
                if decision["subject"]["unit_id"] != candidate["unit_id"]:
                    continue
                subject = decision["subject"]
                matching = [claims for receipt, _, claims in documents if receipt.canonical_sha256 == subject["report_sha256"]]
                e.require(len(matching) == 1 and set(subject["claim_ids"]) <= {claim["claim_id"] for claim in matching[0]}, "coverage_decision_subject_changed")
                anchors = [{key: anchor[key] for key in ("artifact_id", "content_sha256", "start", "end")}
                           for claim in matching[0] if claim["claim_id"] in subject["claim_ids"] for anchor in claim["anchors"]]
                e.require(all(anchor in anchors for anchor in decision["source_anchor_refs"]), "coverage_human_anchor_changed")
            selected = candidate["relevance_decision_ref"]
            if selected is not None:
                decided = decisions[digest(selected)]
                e.require(decided["subject"]["unit_id"] == candidate["unit_id"] and decided["question_id"] != "D3-translation", "coverage_decision_subject_changed")
            elif candidate["state"] not in {"pending", "held"}:
                raise e.CoverageError("coverage_unbacked_reference_state")
            for alias in candidate["source_alias_refs"]:
                self.read_ref(alias)
            e.require(not candidate["availability_evidence_refs"], "coverage_availability_trace_unqualified")
        e.require({d["subject"]["unit_id"] for d in decisions.values()} <= {row["unit_id"] for row in value["units"]}, "coverage_decision_subject_changed")
        for quiet in value["quiet_periods"]:
            e.require(quiet["selection_protocol_ref"] in self.protocol_refs, "coverage_protocol_untrusted")
            self.artifact(quiet["selection_protocol_ref"])
            for pointer in quiet["required_source_inventory_refs"]+quiet["availability_trace_refs"]:
                self.read_ref(pointer)
        return value

    def read_set(self, set_id, expected_sha=None):
        self.validate()
        with self.repository._connection() as c:
            self.repository._validate(c)
            found = self._head(c, e.SET, set_id)
        e.require(found is not None, "coverage_set_not_found")
        receipt, wrapper = found
        e.require(expected_sha is None or receipt.canonical_sha256 == sha(expected_sha), "coverage_set_changed")
        return receipt, self.set_document(wrapper["document"])

    def retain(self, namespace, value, *, expected_head, operation_id):
        """Owner-only local import; never exposed through HTTP commands."""
        self.validate()
        e.require(namespace in {e.SET, e.DECISION})
        e.require(type(operation_id) is str and str(UUID(operation_id)) == operation_id)
        if expected_head is not None:
            sha(expected_head)
        document = self.set_document(value) if namespace == e.SET else self.decision_document(value)
        identity = document["set_id" if namespace == e.SET else "decision_id"]
        predecessor = document["previous_set_sha256" if namespace == e.SET else "previous_decision_sha256"]
        e.require(predecessor == expected_head, "coverage_predecessor_changed")
        payload = dict(namespace=namespace, document=document, expected_head=expected_head, operation_id=operation_id)
        key = digest(dict(namespace=namespace, identity=identity))+":"+operation_id
        def prior(c):
            exists = c.execute(f"SELECT 1 FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id=%s", (OPERATION, key)).fetchone()
            if not exists:
                return None
            _, saved = self.repository._read(c, OPERATION, key)
            e.require(saved["payload"] == payload, "coverage_operation_conflict")
            return saved["result"]
        try:
            with self.repository._connection(writing=True) as c:
                self.repository._validate(c)
                _lock(c, "coverage:"+namespace+":"+identity)
                result = prior(c)
                if result is not None:
                    return result
                head = self._head(c, namespace, identity)
                e.require((head[0].canonical_sha256 if head else None) == expected_head, "coverage_head_changed")
                sequence = head[1]["sequence"]+1 if head else 1
                e.require(sequence <= MAX_VERSIONS, "coverage_version_bound")
                raw, fields = p._snapshot(dict(sequence=sequence, document=document))
                receipt = self.repository._record(c, namespace, _prefix(identity)+f"{sequence:010d}", raw, fields)
                result = ref(receipt)
                raw, fields = p._snapshot(dict(payload=payload, result=result))
                self.repository._record(c, OPERATION, key, raw, fields)
            return result
        except p.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise
            with self.repository._connection() as c:
                self.repository._validate(c)
                recovered = prior(c)
            e.require(recovered is not None, "coverage_write_outcome_unknown")
            return recovered


def recorded_stage(name, receipts, cutoff, *, reasons=(), state="recorded", execution_class="retained_runtime"):
    latest = max(record_time(receipt) for receipt in receipts)
    later = utc_datetime(latest) > utc_datetime(cutoff)
    return e.stage(name, state="held" if later else state, refs=[ref(receipt) for receipt in receipts],
                   recorded_at=e.instant_time(latest), execution_class=execution_class, current_binding="current",
                   reason_codes=["later_knowledge"] if later else list(reasons))


def resolve_report_unit(session, candidate, *, cutoff, episode_reference=None, development_ref=None):
    """Exact current P21/P20 readers; no request regeneration on refresh."""
    from src.editorial.report_development import resolve_story_context
    from src.storage.physical_events import PhysicalEpisodeSession
    from src.commands.postgres_report_development import DEVELOPMENT, _item_id
    records, labels, holds = [], [], {"source_claim_unqualified"}
    for report_ref in candidate["report_refs"]:
        receipt, document = session.reports.read_current(report_ref["lineage_id"], report_ref["report_sha256"])
        records.append(receipt)
        labels.append(document["publisher"])
        selected = [claim for claim in document["claims"] if claim["claim_id"] in report_ref["claim_ids"]]
        if any(claim["translation"]["status"] == "unreviewed" for claim in selected):
            holds.add("translation_pending")
    stages = []
    if records:
        stages.append(recorded_stage("source_input_retained", records, cutoff))
    if candidate["source_class"] in {"reported", "forecast", "warning", "project", "unknown"}:
        stages.append(e.stage("scientific_evidence_qualified", state="not_applicable", reason_codes=["source_claim_unqualified"]))
    episode_receipt = None
    if episode_reference is not None:
        e.fixed(episode_reference, "lineage_id episode_id revision_sha256 claim_id")
        matches = [row for row in candidate["report_refs"] if row["lineage_id"] == episode_reference["lineage_id"] and episode_reference["claim_id"] in row["claim_ids"]]
        e.require(len(matches) == 1, "coverage_episode_report_changed")
        pointer = {key: episode_reference[key] for key in ("episode_id", "revision_sha256", "claim_id")}
        resolve_story_context(session.reports, matches[0]["lineage_id"], matches[0]["report_sha256"], pointer)
        episode_receipt, _ = PhysicalEpisodeSession(session.repository).read_current(pointer["episode_id"], expected_head=pointer["revision_sha256"])
        stages.append(recorded_stage("physical_episode_detected", [*records, episode_receipt], cutoff))
    if development_ref is not None:
        receipt, development = session.read_ref(development_ref)
        e.require(receipt.namespace == DEVELOPMENT and len(candidate["report_refs"]) == 1, "coverage_development_binding_changed")
        report = candidate["report_refs"][0]
        e.require(development["item_id"] == _item_id(report["lineage_id"]) and development["report_sha256"] == report["report_sha256"], "coverage_development_binding_changed")
        expected = None if episode_reference is None else {key: episode_reference[key] for key in ("episode_id", "revision_sha256", "claim_id")}
        e.require(development["episode_reference"] == expected, "coverage_development_binding_changed")
        # A retained item proves preparation. The separate command adapter must
        # verify an actual successful open command before claiming review_opened.
        if development["prepared_story_refs"]:
            e.require(episode_receipt is not None, "coverage_development_binding_changed")
            stages.append(recorded_stage("story_prepared", [receipt, episode_receipt, *records], cutoff))
    stages.append(e.stage("publication_confirmed", state="unsupported", reason_codes=["unsupported_trace_adapter", "publication_unknown"]))
    return stages, (labels[0] if labels else "Retained source"), sorted(holds)


def resolve_scientific_member(session, selector, *, cutoff):
    """Retained typed P18 membership only; no heatwave or runtime replay claim."""
    from src.storage.scientific_supply import ScientificSupplySession, NAMESPACE
    e.fixed(selector, "supply_ref station_id signal_date evidence_sha256")
    e.reference(selector["supply_ref"], {NAMESPACE})
    pointer = selector["supply_ref"]
    e.require(pointer["snapshot_id"].startswith("run:"), "coverage_supply_identity_changed")
    supply = ScientificSupplySession(session.repository, pointer["snapshot_id"][4:], "replay")
    receipt, bundles, _, envelope = supply.read()
    e.require(ref(receipt) == pointer, "coverage_supply_identity_changed")
    matches = [bundle for bundle in bundles if bundle.station_id == selector["station_id"] and bundle.signal_date == selector["signal_date"]]
    # Typed calendar dates may be datetime.date; compare only their exact ISO
    # calendar representation, never midnight UTC or approximate event time.
    if not matches:
        matches = [bundle for bundle in bundles if bundle.station_id == selector["station_id"] and str(bundle.signal_date) == selector["signal_date"]]
    e.require(len(matches) == 1 and digest(matches[0].evidence) == sha(selector["evidence_sha256"]), "coverage_supply_member_changed")
    status = envelope["source_outcome"]["status"]
    reasons = [] if status == "success" else ["source_failed" if status == "failed" else "source_partial"]
    return [recorded_stage("source_input_retained", [receipt], cutoff, reasons=reasons),
            e.stage("physical_episode_detected", state="held", refs=[pointer], reason_codes=["grouping_unresolved"]),
            e.stage("scientific_evidence_qualified", state="unsupported", refs=[pointer], reason_codes=["unsupported_trace_adapter"])], envelope["source_outcome"]


def verified_command(authority, c, command_id, action):
    """Exact explicit selector, never a scan by headline/country/legacy event ID."""
    e.require(type(command_id) is str and str(UUID(command_id)) == command_id)
    accepted = authority._intent(c, command_id)
    result = authority._result(c, command_id)
    e.require(accepted is not None and accepted[0].action == action and result is not None
              and result["status"] in {"applied", "unchanged"}, "coverage_command_not_completed")
    raw = c.execute("SELECT digest FROM theheat_commands.results WHERE command_id=%s", (command_id,)).fetchone()
    return accepted[0], result, [dict(namespace="command-intent-v1", snapshot_id=command_id, sha256=accepted[1]["digest"]),
                                dict(namespace="command-result-v1", snapshot_id=command_id, sha256=raw[0])], accepted[1]["accepted_at"]


def command_stage(name, result, references, accepted_at, cutoff):
    later = max(utc_datetime(accepted_at), utc_datetime(result["completed_at"])) > utc_datetime(cutoff)
    return e.stage(name, state="held" if later else "recorded", refs=references,
        recorded_at=e.instant_time(result["completed_at"]), current_binding="current",
        reason_codes=["later_knowledge"] if later else [])


def resolve_report_command(authority, c, selector, candidate, *, cutoff):
    e.fixed(selector, "command_id development_ref")
    command, result, references, accepted_at = verified_command(authority, c, selector["command_id"], "open_report_evidence")
    e.require(len(candidate["report_refs"]) == 1, "coverage_development_binding_changed")
    report = candidate["report_refs"][0]
    outcome = result["report_development"]
    e.require(command.payload["lineage_id"] == report["lineage_id"] and command.payload["report_sha256"] == report["report_sha256"]
        and outcome["lineage_id"] == report["lineage_id"] and outcome["report_sha256"] == report["report_sha256"]
        and outcome["item_sha256"] == selector["development_ref"]["sha256"] and outcome["draft_mutated"] is False
        and outcome["provider_request_created"] is False, "coverage_development_binding_changed")
    receipt, value = authority.projections._read(c, selector["development_ref"]["namespace"], selector["development_ref"]["snapshot_id"])
    e.require(ref(receipt) == selector["development_ref"] and receipt.namespace == "report-development-v1"
        and value["item_id"] == outcome["item_id"] and value["report_sha256"] == report["report_sha256"]
        and value["episode_reference"] == command.payload["episode_reference"], "coverage_development_binding_changed")
    cell = command_stage("report_review_opened", result, [*references, ref(receipt)], accepted_at, cutoff)
    if utc_datetime(record_time(receipt)) > utc_datetime(cutoff):
        cell.update(state="held", reason_codes=["later_knowledge"])
    return cell


def resolve_workflow(authority, c, selector, prepared_story_refs, *, cutoff, current_state):
    """Read existing P25/I2 provenance only when the upstream bundle is exact.

    This does not enroll cyclone/report work in a batch or acquire checker
    authority. An absent producer join is a retained unsupported stage.
    """
    from src.commands import postgres_sourced_generation as generation, postgres_candidate_admission as admission
    from src.commands import postgres_revision_checks as revisions
    from src.commands.postgres_authority import NAMESPACE
    from src.editorial.revisions import fingerprint, draft_identity, required_checks_fingerprint
    e.fixed(selector, "generation_command_id admission_input_ref admission_command_id")
    command, result, pointers, accepted_at = verified_command(authority, c, selector["generation_command_id"], "request_sourced_generation")
    _, outcome, job = generation.runner_identity(authority, c, command.command_id)
    brief_receipt, raw_brief = authority.projections._read(c, generation.INPUT, outcome["brief_id"])
    brief = generation.document(raw_brief)
    job_receipt, stored_job = authority.projections._read(c, generation.JOB, outcome["job_id"])
    e.require(stored_job == job and brief_receipt.canonical_sha256 == outcome["brief_id"], "coverage_generation_binding_changed")
    matches = [row for row in prepared_story_refs if row["bundle_sha256"] == fingerprint(brief["bundle"])
        and row["memory_sha256"] == fingerprint(job["memory"]) and row["policy_sha256"] == job["context"]["policy_sha256"]]
    e.require(len(matches) == 1, "coverage_prepared_story_binding_missing")
    pointers.extend([ref(brief_receipt), ref(job_receipt)])
    cells = [command_stage("generation_accepted", result, pointers, accepted_at, cutoff)]
    if any(utc_datetime(record_time(receipt)) > utc_datetime(cutoff) for receipt in (brief_receipt, job_receipt)):
        cells[0].update(state="held", reason_codes=["later_knowledge"])
    if selector["admission_input_ref"] is None:
        e.require(selector["admission_command_id"] is None, "coverage_candidate_binding_missing")
        return cells
    pointer = e.reference(selector["admission_input_ref"], {admission.NAMESPACE})
    receipt, value = authority.projections._read(c, pointer["namespace"], pointer["snapshot_id"])
    references = dict(admission_input_id=pointer["snapshot_id"], admission_input_sha256=pointer["sha256"],
                      **{key: value[key] for key in ("job_id", "custom_id", "candidate_id")})
    value = admission.read_input(c, references)
    e.require(ref(receipt) == pointer and value["job_id"] == outcome["job_id"] and value["custom_id"] == job["custom_id"]
        and value["plan_sha256"] == outcome["plan_sha256"] and p._canonical(value["bundle"]) == p._canonical(brief["bundle"])
        and p._canonical(value["memory"]) == p._canonical(job["memory"]), "coverage_candidate_binding_changed")
    cells.append(recorded_stage("candidate_retained", [receipt, brief_receipt, job_receipt], cutoff))
    if selector["admission_command_id"] is None:
        return cells
    cmd, saved, proof_refs, at = verified_command(authority, c, selector["admission_command_id"], "admit_checked_candidate")
    e.require(saved["status"] == "applied" and all(cmd.payload[key] == value for key, value in references.items()), "coverage_admission_binding_changed")
    outcome = saved["candidate"]
    state_receipt, state = authority.projections._read(c, NAMESPACE, str(saved["state_version"]))
    drafts = [draft for draft in state.get("drafts", []) if draft.get("id") == outcome["draft_id"]]
    e.require(len(drafts) == 1, "coverage_saved_revision_missing")
    draft = drafts[0]
    _, origin, captured = revisions.source(c, draft)
    e.require(origin["admission_command_id"] == cmd.command_id and captured == value, "coverage_admission_binding_changed")
    proof = draft["review_context"]["two_bot"]["required_checks_binding"]
    e.require(required_checks_fingerprint(proof) is not None and proof["candidate_id"] == value["candidate_id"]
        and proof["check_set_id"] == outcome["check_set_id"] and proof["completion_sha256"] == outcome["completion_sha256"], "coverage_check_completion_changed")
    proof_refs.extend([pointer, ref(state_receipt)])
    for name in ("checks_completed", "draft_saved"):
        cell = command_stage(name, saved, proof_refs, at, cutoff)
        if utc_datetime(record_time(state_receipt)) > utc_datetime(cutoff):
            cell.update(state="held", reason_codes=["later_knowledge"])
        current = [row for row in current_state.get("drafts", []) if row.get("id") == draft["id"]]
        if len(current) != 1 or draft_identity(current[0]) != draft_identity(draft):
            cell["current_binding"] = "superseded"
        cells.append(cell)
    return cells


def private_configuration(path):
    # Reuse the existing owner-only, no-symlink, strict-JSON 16KiB boundary.
    from src.commands.postgres_report_development import private_configuration as load_private
    return load_private(path)


def configuration(authority):
    load = getattr(authority, "coverage_configuration", None)
    e.require(authority.environment == "local" and callable(load), "coverage_unavailable")
    assert callable(load)
    value = p._decode(p._canonical(load()))
    e.fixed(value, "set_id set_sha256 protocol_refs decision_imports report_decision_refs selectors")
    identifier(value["set_id"])
    sha(value["set_sha256"])
    e.array(value["selectors"], 16)
    seen = set()
    for row in value["selectors"]:
        e.fixed(row, "unit_id episode_reference report_command scientific_member workflow")
        identifier(row["unit_id"])
        e.require(row["unit_id"] not in seen, "coverage_selector_ambiguous")
        seen.add(row["unit_id"])
        if row["episode_reference"] is not None:
            e.fixed(row["episode_reference"], "lineage_id episode_id revision_sha256 claim_id")
            from src.storage.physical_events import _episode
            _episode(row["episode_reference"]["episode_id"])
            sha(row["episode_reference"]["revision_sha256"])
            identifier(row["episode_reference"]["lineage_id"])
            identifier(row["episode_reference"]["claim_id"])
        if row["report_command"] is not None:
            e.fixed(row["report_command"], "command_id development_ref")
            e.require(str(UUID(row["report_command"]["command_id"])) == row["report_command"]["command_id"])
            e.reference(row["report_command"]["development_ref"], {"report-development-v1"})
        if row["scientific_member"] is not None:
            e.fixed(row["scientific_member"], "supply_ref station_id signal_date evidence_sha256")
            e.reference(row["scientific_member"]["supply_ref"], {"scientific-supply-ghcn-v1"})
            e.text(row["scientific_member"]["station_id"], 11)
            e.text(row["scientific_member"]["signal_date"], 10)
            sha(row["scientific_member"]["evidence_sha256"])
        if row["workflow"] is not None:
            e.fixed(row["workflow"], "generation_command_id admission_input_ref admission_command_id")
            for key in ("generation_command_id", "admission_command_id"):
                identity = row["workflow"][key]
                if identity is not None:
                    e.require(str(UUID(identity)) == identity)
            if row["workflow"]["admission_input_ref"] is not None:
                e.reference(row["workflow"]["admission_input_ref"], {"candidate-admission-input-v1"})
    configured_session(authority, value).validate()
    return value


def configured_session(authority, config):
    for key in ("protocol_refs", "decision_imports", "report_decision_refs"):
        e.array(config[key], 32)
    return CoverageSession(authority.projections, tuple(config["protocol_refs"]), tuple(config["decision_imports"]), tuple(config["report_decision_refs"]))


def _configured_heads(session, c, config):
    """Authority lock is held by caller. No report/episode lock is reversed."""
    _lock(c, "coverage:"+e.SET+":"+config["set_id"])
    found = session._head(c, e.SET, config["set_id"])
    e.require(found is not None and found[0].canonical_sha256 == config["set_sha256"], "coverage_set_changed")
    document = e.reference_set(found[1]["document"])
    decision_ids = []
    for pointer in document["human_decision_refs"]:
        receipt, wrapper = session.repository._read(c, pointer["namespace"], pointer["snapshot_id"])
        e.require(ref(receipt) == pointer, "coverage_reference_changed")
        decision_ids.append(e.decision(wrapper["document"])["decision_id"])
    for identity in sorted(set(decision_ids)):
        _lock(c, "coverage:"+e.DECISION+":"+identity)
    report_ids = [row["lineage_id"] for candidate in document["units"] for row in candidate["report_refs"]]
    episode_ids = [row["episode_reference"]["episode_id"] for row in config["selectors"] if row["episode_reference"] is not None]
    lock_current_heads(c, report_ids, episode_ids)
    return session.evaluation_set(config["set_id"], config["set_sha256"])


def resolve_inputs(authority, c, session, config, retained_set, *, cutoff, state):
    document = retained_set.value(e.SET)["wrapper"]["document"]
    e.require({row["unit_id"] for row in config["selectors"]} <= {row["unit_id"] for row in document["units"]}, "coverage_selector_changed")
    selected = {row["unit_id"]: row for row in config["selectors"]}
    decision_inputs = [session.evaluation_decision(pointer) for pointer in document["human_decision_refs"]]
    resolved, inputs, availability = [], [], []
    for candidate in document["units"]:
        selectors = selected.get(candidate["unit_id"], dict(episode_reference=None, report_command=None, scientific_member=None, workflow=None))
        development_ref = selectors["report_command"]["development_ref"] if selectors["report_command"] else None
        stages, label, holds = resolve_report_unit(session, candidate, cutoff=cutoff,
            episode_reference=selectors["episode_reference"], development_ref=development_ref)
        if selectors["scientific_member"] is not None:
            pointer = selectors["scientific_member"]["supply_ref"]
            e.require(not candidate["report_refs"] and selectors["episode_reference"] is None
                and pointer in candidate["source_alias_refs"], "coverage_scientific_reference_changed")
            scientific, outcome = resolve_scientific_member(session, selectors["scientific_member"], cutoff=cutoff)
            stages = [cell for cell in stages if cell["stage"] not in {row["stage"] for row in scientific}]+scientific
            # Original availability remains a separate scoped observation.
            availability.append(dict(unit_id=candidate["unit_id"], source_ref=pointer, original_status=outcome["status"],
                scope="retained_supply_run", cutoff=cutoff, recall_contribution=None))
        if selectors["report_command"] is not None:
            stages.append(resolve_report_command(authority, c, selectors["report_command"], candidate, cutoff=cutoff))
        if selectors["workflow"] is not None:
            e.require(development_ref is not None, "coverage_prepared_story_binding_missing")
            _, developed = session.read_ref(development_ref)
            stages.extend(resolve_workflow(authority, c, selectors["workflow"], developed["prepared_story_refs"], cutoff=cutoff, current_state=state))
        # Invented fixtures remain visibly invented even when their storage and
        # execution paths are real. No runtime success is a human reference.
        if document["selection_protocol"]["selection_method"] == "invented_fixture":
            stages = [dict(cell, execution_class="invented_fixture") for cell in stages]
        choices = [value for value in decision_inputs if value.value(e.DECISION)["wrapper"]["document"]["subject"]["unit_id"] == candidate["unit_id"]]
        resolved.append(e.ResolvedUnit.create(unit_id=candidate["unit_id"], source_label=label, stages=stages, decisions=choices, holds=holds))
        for cell in stages:
            inputs.extend(cell["evidence_refs"])
    unique = list({digest(pointer): pointer for pointer in inputs}.values())
    return resolved, unique, availability


def _completion_clock():
    """Trusted worker wall clock; no command/configuration clock override."""
    return datetime.now(UTC)


def prepare(authority, c, state, version, command, actor, *, now, editorial_policy):
    from src.commands.schema import authorize
    from src.editorial.policy import current_editorial_policy
    authorize(actor, command.action)
    e.require(command.action == "evaluate_reference_coverage" and actor.subject == command.actor_subject
        and actor.authentication_context == command.authentication_context, "coverage_actor_changed")
    e.require(now < utc_datetime(command.expires_at), "coverage_command_expired")
    payload = command.payload
    e.fixed(payload, "set_id expected_set_sha256 expected_state_version expected_policy_sha256")
    e.require(payload["expected_state_version"] == version and payload["expected_policy_sha256"] == digest(editorial_policy), "coverage_context_changed")
    config = configuration(authority)
    e.require(payload["set_id"] == config["set_id"] and payload["expected_set_sha256"] == config["set_sha256"], "coverage_set_changed")
    intent = authority._intent(c, command.command_id)
    e.require(intent is not None and intent[0] == command, "coverage_intent_changed")
    cutoff = intent[1]["accepted_at"]
    session = configured_session(authority, config)
    retained_set = _configured_heads(session, c, config)
    resolved, inputs, availability = resolve_inputs(authority, c, session, config, retained_set, cutoff=cutoff, state=state)
    assessment = e.evaluate(retained_set, resolved, cutoff=cutoff, evaluated_at=utc_text(now), state_version=version,
                            policy_sha256=digest(editorial_policy), input_refs=inputs)
    assessment.update(configuration_sha256=digest(config), state_sha256=digest(state), source_availability=availability)
    identity = digest(dict(set_ref=assessment["set_ref"], input_refs=assessment["input_refs"], state_sha256=assessment["state_sha256"],
        state_version=version, contract=e.CONTRACT, policy_sha256=assessment["policy_sha256"], cutoff=cutoff, configuration_sha256=digest(config)))
    assessment["assessment_id"] = identity
    assessment["command_id"] = command.command_id
    assessment["accepted_sequence"] = intent[1]["sequence"]
    e.require(len(p._canonical(assessment)) <= e.MAX_RESULT_BYTES, "coverage_result_bound")
    e.require(configuration(authority) == config and digest(current_editorial_policy()) == digest(editorial_policy), "coverage_context_changed")
    # Re-resolve current heads under the same deterministic locks before commit.
    e.require(session.evaluation_set(config["set_id"], config["set_sha256"]).encoded == retained_set.encoded, "coverage_set_changed")
    completed_at = _completion_clock()
    e.require(completed_at >= now and completed_at >= utc_datetime(cutoff), "coverage_clock_changed")
    e.require(completed_at < utc_datetime(command.expires_at), "coverage_command_expired")
    assessment["evaluated_at"] = utc_text(completed_at)
    raw, fields = p._snapshot(assessment)
    receipt = authority.projections._record(c, e.ASSESSMENT, _prefix(config["set_id"])+f'{intent[1]["sequence"]:016d}', raw, fields)
    return dict(assessment_ref=ref(receipt), assessment_id=identity, status="reference_evidence_assessed",
                draft_mutated=False, provider_request_created=False, publication_enabled=False)


def _latest_assessment(c, set_id):
    prefix = _prefix(set_id)
    row = c.execute(f"SELECT snapshot_id FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id >= %s AND snapshot_id < %s ORDER BY snapshot_id DESC LIMIT 1",
                    (e.ASSESSMENT, prefix, prefix[:-1]+";")).fetchone()
    if row is None:
        return None
    receipt, value = p.PostgresProjectionRepository._read(c, e.ASSESSMENT, row[0])
    e.require(type(value.get("accepted_sequence")) is int and 1 <= value["accepted_sequence"] <= p.MAX_INTEGER
        and row[0] == prefix+f'{value["accepted_sequence"]:016d}' and len(p._canonical(value)) <= e.MAX_RESULT_BYTES,
        "coverage_assessment_changed")
    e.require(value.get("contract") == e.CONTRACT and value.get("metrics") == dict(event_recall=None, draft_recall=None,
        publication_recall=None, timeliness=None, confirmed_misses=None, reason="denominator_not_qualified"), "coverage_assessment_changed")
    return receipt, value


def projection(authority, *, now):
    """Read saved facts only. No evaluation, model call or source refresh."""
    if not callable(getattr(authority, "coverage_configuration", None)):
        return dict(enabled=False, ready=False, currentness="unavailable", assessment=None, reference_readiness=None,
                    pending_command=None, reports=[], reasons=["coverage_unavailable"])
    from src.editorial.policy import current_editorial_policy
    config = configuration(authority)
    session = configured_session(authority, config)
    with authority.projections._connection() as c:
        authority._validate(c)
        version, state = authority._state(c, lock=True)
        latest = _latest_assessment(c, config["set_id"])
        pending_rows = c.execute("""SELECT i.command_id FROM theheat_commands.intents i LEFT JOIN theheat_commands.results r USING(command_id)
            WHERE r.command_id IS NULL AND convert_from(i.command_bytes,'UTF8')::jsonb->>'action'='evaluate_reference_coverage'
              AND convert_from(i.command_bytes,'UTF8')::jsonb->'payload'->>'set_id'=%s ORDER BY i.sequence LIMIT 2""", (config["set_id"],)).fetchall()
        pending = authority._intent(c, pending_rows[0][0])[0] if pending_rows else None
        ready, currentness, reasons, reports = True, "current", [], []
        assessment = p._decode(p._canonical(latest[1])) if latest else None
        try:
            retained = _configured_heads(session, c, config)
            document = retained.value(e.SET)["wrapper"]["document"]
            for candidate in document["units"]:
                for pointer in candidate["report_refs"]:
                    _, report = session.reports.read_current(pointer["lineage_id"], pointer["report_sha256"])
                    reports.append(dict(lineage_id=pointer["lineage_id"], source_label=report["publisher"]))
            readiness = dict(status="not_qualified", report_lineages=len({row["lineage_id"] for row in reports}),
                units_pending=len(document["units"]), human_decisions_recorded=len(document["human_decision_refs"]), quiet_periods_qualified=0,
                reasons=["denominator_not_qualified", "quiet_period_unqualified"])
            # Validate selectors/current associations without creating an assessment.
            resolve_inputs(authority, c, session, config, retained, cutoff=utc_text(now), state=state)
        except p.ProjectionError:
            raise  # Missing/corrupt storage is unavailable, not a factual correction.
        except (e.CoverageError, ValueError):
            ready, currentness, reasons = False, "refresh_required", ["source_or_reference_corrected"]
            readiness = None
        policy_sha = digest(current_editorial_policy())
        if assessment is not None and (assessment["set_ref"]["sha256"] != config["set_sha256"]
            or assessment.get("configuration_sha256") != digest(config) or assessment["state_version"] != version
            or assessment["policy_sha256"] != policy_sha or assessment.get("state_sha256") != digest(state)):
            currentness = "refresh_required"
        if assessment is not None:
            assessment["currentness"] = currentness
            if currentness != "current":
                # The saved occurrence remains historical. Its old "current"
                # label cannot promise a current binding after any context drift.
                for unit in assessment["units"]:
                    for cell in unit["stages"]:
                        if cell["current_binding"] == "current":
                            cell["current_binding"] = "unresolved"
        return dict(enabled=True, ready=ready, set_id=config["set_id"], expected_set_sha256=config["set_sha256"], expected_state_version=version,
            expected_policy_sha256=policy_sha, currentness=currentness, assessment=assessment,
            assessment_ref=ref(latest[0]) if latest else None, reference_readiness=readiness, reports=reports,
            pending_command=({key: value for key, value in pending.as_dict().items() if key in {"command_id", "action", "targets", "payload", "requested_at", "expires_at"}} if pending else None),
            pending_count_at_least=len(pending_rows), reasons=reasons)


from contextlib import contextmanager


@contextmanager
def expected_domain_failures():
    from src.commands.schema import CommandError
    from src.storage.retained_reports import ReportError
    from src.storage.cyclone_supply import CycloneSupplyError
    try:
        yield
    except (e.CoverageError, ReportError, CycloneSupplyError) as exc:
        raise CommandError(str(exc), "Coverage evidence changed or requires review. Refresh its current references.") from None
