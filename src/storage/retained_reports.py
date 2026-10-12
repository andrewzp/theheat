"""Immutable local report evidence; report statements never become observations.

Only explicit retained bytes and references enter here. No URL fetch, translation,
verdict creation, state backend selection or model request is available.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
import re
from urllib.parse import urlsplit

from src.commands.schema import utc_datetime
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import environment

ARTIFACT = "retained-report-artifact-v1"
REVISION = "retained-report-revision-v1"
OPERATION = "retained-report-operation-v1"
MAX_ARTIFACT = 8 * 1024 * 1024
MAX_REPORT = 128 * 1024
MAX_EXCERPT = 16 * 1024
MAX_REVISIONS = 512
KINDS = {"reported_impact", "source_reported_observation", "forecast", "warning", "project_update", "unclassified"}
TIME_KEYS = {"event_start", "event_end", "issued_at", "published_at", "as_of", "valid_from", "valid_until"}


class ReportError(ValueError):
    """Codes only; do not expose source bytes, paths or provider errors."""


def require(condition, code="report_invalid"):
    if not condition:
        raise ReportError(code)


def text(value, limit=500, *, empty=False):
    require(type(value) is str and len(value.encode("utf-8")) <= limit and (empty or bool(value.strip())))
    return value


def sha(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None, "report_hash_invalid")
    return value


def identifier(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None)
    return value


def fixed(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()))
    return value


def digest(value):
    return p._sha(p._canonical(value))


def frozen(value):
    return p._decode(p._canonical(value))


def url(value):
    text(value, 2048)
    parsed = urlsplit(value)
    require(parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.fragment, "report_url_invalid")


def bounded_list(value, minimum, maximum):
    require(type(value) is list and minimum <= len(value) <= maximum, "report_inventory_bound")


def timestamp(value):
    if value is not None:
        fixed(value, "original utc date precision timezone")
        text(value["original"], 500)
        require(value["precision"] in {"unknown", "calendar", "instant"})
        if value["timezone"] is not None:
            text(value["timezone"], 100)
        if value["date"] is not None:
            require(type(value["date"]) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value["date"]) is not None)
            date.fromisoformat(value["date"])
        if value["utc"] is not None:
            utc_datetime(value["utc"])
        require((value["precision"] == "instant") == (value["utc"] is not None))
        require((value["precision"] == "calendar") == (value["date"] is not None))


def artifact_metadata(value):
    fixed(value, "media_type source_url retrieved_at original_artifact_id extraction")
    require(value["media_type"] in {"text/plain", "text/html", "application/pdf", "application/json"})
    if value["source_url"] is not None:
        url(value["source_url"])
    if value["retrieved_at"] is not None:
        utc_datetime(value["retrieved_at"])
    if value["original_artifact_id"] is not None:
        sha(value["original_artifact_id"])
        fixed(value["extraction"], "method version section")
        for item in value["extraction"].values():
            text(item, 300)
        require(value["media_type"] == "text/plain")
    else:
        require(value["extraction"] is None)
    require(len(p._canonical(value)) <= 8192)


def claim_subject(claim):
    """Stable subject for a retained review; never a human verdict itself."""
    value = frozen(claim)
    value.pop("source_review")
    value["translation"].pop("decision_ref")
    value["translation"].pop("status")
    return digest(value)


@dataclass(frozen=True)
class RetainedReportSession:
    repository: p.PostgresProjectionRepository
    # Trusted local packet references, not supplied in a report/HTTP command.
    # The current real packet has no completed decisions and uses the empty set.
    decision_refs: tuple = ()

    def _validate(self):
        environment(self.repository)
        require(type(self.decision_refs) is tuple and len(self.decision_refs) <= 32)

    def retain_artifact(self, raw, *, declared_sha256, metadata):
        self._validate()
        require(type(raw) is bytes and 0 < len(raw) <= MAX_ARTIFACT, "report_artifact_bound")
        require(p._sha(raw) == sha(declared_sha256), "report_artifact_changed")
        artifact_metadata(metadata)
        if metadata["original_artifact_id"] is not None:
            self.read_artifact(metadata["original_artifact_id"])
        if metadata["media_type"] != "application/pdf":
            try:
                raw.decode("utf-8")
            except UnicodeError:
                raise ReportError("report_artifact_encoding") from None
        value = dict(schema_version=1, sha256=declared_sha256, byte_count=len(raw),
                     content_base64=base64.b64encode(raw).decode("ascii"), metadata=frozen(metadata))
        # Repository checks its full16MiB canonical envelope before SQL.
        p._snapshot(value)
        return self.repository.record(ARTIFACT, digest(value), value)

    def read_artifact(self, artifact_id):
        self._validate()
        receipt, value = self.repository.read(ARTIFACT, sha(artifact_id))
        fixed(value, "schema_version sha256 byte_count content_base64 metadata")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1)
        require(receipt.canonical_sha256 == artifact_id == digest(value), "report_artifact_changed")
        require(type(value["byte_count"]) is int and 0 < value["byte_count"] <= MAX_ARTIFACT, "report_artifact_bound")
        require(type(value["content_base64"]) is str and len(value["content_base64"]) == 4*((value["byte_count"]+2)//3), "report_artifact_bound")
        artifact_metadata(value["metadata"])
        try:
            raw = base64.b64decode(value["content_base64"], validate=True)
        except (ValueError, UnicodeError):
            raise ReportError("report_artifact_encoding") from None
        require(len(raw) == value["byte_count"] and p._sha(raw) == sha(value["sha256"]), "report_artifact_changed")
        return receipt, value, raw

    def _review(self, review, claim, dimension):
        fixed(review, "status decision_ref")
        require(review["status"] in {"pending", "human_reviewed"})
        if review["status"] == "pending":
            require(review["decision_ref"] is None)
            return
        ref = review["decision_ref"]
        require(type(ref) is dict and ref in self.decision_refs, "report_review_unavailable")
        fixed(ref, "namespace snapshot_id sha256")
        require(ref["namespace"] == "report-human-decision-v1", "report_review_unavailable")
        receipt, decision = self.repository.read(ref["namespace"], sha(ref["snapshot_id"]))
        require(receipt.canonical_sha256 == sha(ref["sha256"]), "report_review_changed")
        fixed(decision, "schema_version packet_sha256 reviewer reviewed_at dimension claim_sha256 outcome")
        require(type(decision["schema_version"]) is int and decision["schema_version"] == 1)
        sha(decision["packet_sha256"])
        text(decision["reviewer"], 200)
        utc_datetime(decision["reviewed_at"])
        require(decision["dimension"] == dimension and decision["claim_sha256"] == claim_subject(claim)
                and decision["outcome"] == "reviewed", "report_review_changed")
        # This records review occurrence, never independent truth or eligibility.

    def document(self, value):
        self._validate()
        fixed(value, "schema_version lineage_id previous_report_sha256 publisher source_url hazards original_language artifact_refs upstream_lineage_refs claims limits captured_at reference_review legacy_metadata")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1)
        require(len(p._canonical(value)) <= MAX_REPORT, "report_metadata_bound")
        identifier(value["lineage_id"])
        if value["previous_report_sha256"] is not None:
            sha(value["previous_report_sha256"])
        text(value["publisher"], 300)
        url(value["source_url"])
        text(value["original_language"], 35)
        utc_datetime(value["captured_at"])
        for key, maximum in (("hazards", 16), ("limits", 32), ("upstream_lineage_refs", 8)):
            bounded_list(value[key], 0, maximum)
            for item in value[key]:
                text(item, 1000)
        refs = value["artifact_refs"]
        bounded_list(refs, 0 if value["legacy_metadata"] is not None else 1, 8)
        require(len(refs) == len(set(refs)))
        artifacts = {sha(ref): self.read_artifact(ref) for ref in refs}
        fixed(value["reference_review"], "candidate_id adjudication benchmark_eligible importance detection_deadline bot_match")
        reference = value["reference_review"]
        if reference["candidate_id"] is not None:
            identifier(reference["candidate_id"])
        require(reference["adjudication"] == "pending_human_and_source_review"
                and reference["benchmark_eligible"] is False and reference["importance"] is None
                and reference["detection_deadline"] is None and reference["bot_match"] == "not_evaluated", "report_reference_unadjudicated")
        if value["legacy_metadata"] is not None:
            require(type(value["legacy_metadata"]) is dict and len(p._canonical(value["legacy_metadata"])) <= 32768)
        bounded_list(value["claims"], 1, 32)
        seen = set()
        for claim in value["claims"]:
            fixed(claim, "claim_id kind summary anchors original_language translation source_review attribution times quantity geography identity_reference holds")
            identifier(claim["claim_id"])
            require(claim["claim_id"] not in seen)
            seen.add(claim["claim_id"])
            require(claim["kind"] in KINDS)
            text(claim["summary"], 2000)
            text(claim["original_language"], 35)
            text(claim["attribution"], 300)
            bounded_list(claim["anchors"], 0 if value["legacy_metadata"] is not None else 1, 8)
            for anchor in claim["anchors"]:
                fixed(anchor, "artifact_id content_sha256 start end text")
                require(anchor["artifact_id"] in artifacts, "report_anchor_artifact_missing")
                _, artifact, raw = artifacts[anchor["artifact_id"]]
                require(artifact["metadata"]["media_type"] == "text/plain", "report_anchor_requires_retained_text")
                require(sha(anchor["content_sha256"]) == artifact["sha256"], "report_anchor_changed")
                require(type(anchor["start"]) is int and type(anchor["end"]) is int
                        and 0 <= anchor["start"] < anchor["end"] <= len(raw)
                        and anchor["end"]-anchor["start"] <= MAX_EXCERPT, "report_anchor_bound")
                text(anchor["text"], MAX_EXCERPT)
                require(raw[anchor["start"]:anchor["end"]] == anchor["text"].encode("utf-8"), "report_anchor_changed")
            fixed(claim["times"], " ".join(TIME_KEYS))
            for time_value in claim["times"].values():
                timestamp(time_value)
            quantity = claim["quantity"]
            if quantity is not None:
                fixed(quantity, "value unit operator scope")
                require(type(quantity["value"]) in {int, float, str})
                text(quantity["unit"], 50)
                text(quantity["operator"], 50)
                require(quantity["scope"] in {"cumulative", "currently_affected", "period_total", "instantaneous", "unknown"})
            fixed(claim["geography"], "reported_scope role map_marker geometry")
            text(claim["geography"]["reported_scope"], 1000, empty=True)
            require(claim["geography"]["role"] in {"reported_footprint", "map_marker", "warning_area", "meeting_location", "unknown"})
            require(claim["geography"]["geometry"] is None, "report_geometry_unqualified")
            marker = claim["geography"]["map_marker"]
            if marker is not None:
                require(type(marker) is list and len(marker) == 2 and all(type(v) in {float, int} for v in marker)
                        and -90 <= marker[0] <= 90 and -180 <= marker[1] <= 180)
            bounded_list(claim["holds"], 0, 32)
            for hold in claim["holds"]:
                identifier(hold)
            identity = claim["identity_reference"]
            if identity is not None:
                fixed(identity, "authority source_id anchor_index")
                text(identity["authority"], 100)
                text(identity["source_id"], 100)
                require(type(identity["anchor_index"]) is int and 0 <= identity["anchor_index"] < len(claim["anchors"]))
                anchor = claim["anchors"][identity["anchor_index"]]
                require(re.search(r"(?<![A-Za-z0-9])"+re.escape(identity["source_id"])+r"(?![A-Za-z0-9])", anchor["text"]), "report_identity_anchor_changed")
            fixed(claim["translation"], "text status decision_ref")
            translation = claim["translation"]
            if translation["text"] is not None:
                text(translation["text"], MAX_EXCERPT)
            if translation["status"] == "not_needed":
                require(translation["text"] is None and translation["decision_ref"] is None
                        and claim["original_language"] == "en", "report_translation_unreviewed")
            else:
                require(translation["status"] in {"unreviewed", "human_reviewed"})
                self._review(dict(status="pending" if translation["status"] == "unreviewed" else "human_reviewed",
                                  decision_ref=translation["decision_ref"]), claim, "translation")
            self._review(claim["source_review"], claim, "source")
        return frozen(value)

    @staticmethod
    def _prefix(lineage_id):
        return digest(identifier(lineage_id))+":"

    def _head(self, c, lineage_id):
        prefix = self._prefix(lineage_id)
        row = c.execute(f"SELECT snapshot_id FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id >= %s AND snapshot_id < %s ORDER BY snapshot_id DESC LIMIT 1", (REVISION, prefix, prefix[:-1]+";")).fetchone()
        if row is None:
            return None
        receipt, wrapper = self.repository._read(c, REVISION, row[0])
        fixed(wrapper, "sequence document")
        require(type(wrapper["sequence"]) is int and 1 <= wrapper["sequence"] <= MAX_REVISIONS)
        require(row[0] == prefix+f'{wrapper["sequence"]:010d}' and wrapper["document"]["lineage_id"] == lineage_id)
        return receipt, wrapper

    def read_current(self, lineage_id, expected_sha=None):
        self._validate()
        with self.repository._connection() as c:
            self.repository._validate(c)
            head = self._head(c, lineage_id)
        require(head is not None, "report_not_found")
        receipt, wrapper = head
        require(expected_sha is None or receipt.canonical_sha256 == sha(expected_sha), "report_head_changed")
        return receipt, self.document(wrapper["document"])

    def retain_revision(self, value, *, expected_head, operation_id):
        self._validate()
        from uuid import UUID
        require(type(operation_id) is str and str(UUID(operation_id)) == operation_id)
        document = self.document(value)
        require(expected_head is None or type(expected_head) is str)
        if expected_head is not None:
            sha(expected_head)
        require(document["previous_report_sha256"] == expected_head, "report_predecessor_changed")
        lineage = document["lineage_id"]
        payload = dict(document=document, expected_head=expected_head, operation_id=operation_id)
        key = self._prefix(lineage)+operation_id
        def prior(c):
            found = c.execute(f"SELECT 1 FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id=%s", (OPERATION, key)).fetchone()
            if not found:
                return None
            _, stored = self.repository._read(c, OPERATION, key)
            require(stored["payload"] == payload, "report_operation_conflict")
            return stored["result"]
        try:
            with self.repository._connection(writing=True) as c:
                self.repository._validate(c)
                lock = int(digest(lineage)[:16], 16)
                c.execute("SELECT pg_advisory_xact_lock(%s)", (lock if lock < 2**63 else lock-2**64,))
                result = prior(c)
                if result is not None:
                    return result
                head = self._head(c, lineage)
                require((head[0].canonical_sha256 if head else None) == expected_head, "report_head_changed")
                sequence = head[1]["sequence"]+1 if head else 1
                require(sequence <= MAX_REVISIONS, "report_revision_bound")
                encoded, fields = p._snapshot(dict(sequence=sequence, document=document))
                receipt = self.repository._record(c, REVISION, self._prefix(lineage)+f'{sequence:010d}', encoded, fields)
                result = dict(lineage_id=lineage, report_sha256=receipt.canonical_sha256, sequence=sequence)
                encoded, fields = p._snapshot(dict(payload=payload, result=result))
                self.repository._record(c, OPERATION, key, encoded, fields)
            return result
        except p.ProjectionError as exc:
            if str(exc) != "write_outcome_unknown":
                raise
            with self.repository._connection() as c:
                self.repository._validate(c)
                result = prior(c)
            require(result is not None, "report_write_outcome_unknown")
            return result


def legacy_news_document(event, *, lineage_id, captured_at):
    """Passive adapter for an already returned news result; never fetch/verify.

    Legacy model/feed metadata cannot supply original excerpts, language,
    scientific provenance or event-time precision that it did not retain.
    The caller supplies an explicit local lineage; headline equality is not it.
    """
    require(type(event) is dict and len(p._canonical(event)) <= 32768, "report_legacy_bound")
    impacts = event.get("impact")
    require(type(impacts) is list and bool(impacts) and type(impacts[0]) is dict, "report_legacy_source_missing")
    source = impacts[0]
    url(source.get("url"))
    text(source.get("source_name"), 300)
    headline = text(event.get("headline"), 2000)
    identifier(lineage_id)
    utc_datetime(captured_at)
    claim = dict(claim_id="legacy-claim", kind="unclassified", summary=headline, anchors=[], original_language="und",
        translation=dict(text=None, status="unreviewed", decision_ref=None), source_review=dict(status="pending", decision_ref=None),
        attribution=source["source_name"], times=dict.fromkeys(TIME_KEYS), quantity=None,
        geography=dict(reported_scope="", role="unknown", map_marker=None, geometry=None), identity_reference=None,
        holds=["original_report_evidence_missing", "legacy_dates_unqualified", "legacy_verifier_not_adjudication"])
    return dict(schema_version=1, lineage_id=lineage_id, previous_report_sha256=None, publisher=source["source_name"],
        source_url=source["url"], hazards=[str(event.get("kind") or "unknown")], original_language="und", artifact_refs=[],
        upstream_lineage_refs=[], claims=[claim], limits=["Retained legacy result metadata only; original report and scientific semantics unavailable"],
        captured_at=captured_at, reference_review=dict(candidate_id=None, adjudication="pending_human_and_source_review",
            benchmark_eligible=False, importance=None, detection_deadline=None, bot_match="not_evaluated"), legacy_metadata=frozen(event))
