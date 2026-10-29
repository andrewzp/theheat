"""Read-only local commitments and selected, passive request evidence.

Totals inherit the spending catalog/aggregate guarantee. Only selected intents
receive semantic replay. Immutable source links never grant editorial authority.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import timedelta
import time

from src.commands import postgres_spending as spend, spend_journal as s
from src.commands import postgres_checks as checks, check_journal as cj
from src.commands import postgres_check_observations as observations
from src.commands import postgres_sourced_generation as generation
from src.commands import postgres_synchronous_generation as sync
from src.commands.schema import DraftTarget, utc_datetime, utc_text
from src.editorial.revisions import decision_revision, draft_identity, fingerprint, text_hash
from src.storage import postgres_projection as p
from src.two_bot import check_origin, synchronous_origin
from src.two_bot import retained_usage as usage

MAX_DETAILS = 20
MAX_BYTES = 8 * 1024 * 1024
MAX_OUTPUT = 128 * 1024
SECONDS = 3.0
STATES = ("reserved", "dispatched", "uncertain", "released", "settled")
HELD = STATES[:3]
ORIGIN_FIELDS = ("brief_id", "source_run_id", "generation_id", "check_set_id", "stage", "grant_id", "request_sha256", "raw_sha256", "receipt_id")


class Limited(Exception):
    """A bounded read cannot fit; no evidence is silently truncated."""


class Deadline(Exception):
    """Snapshot completed outside its eligibility deadline."""


def require(value):
    if not value:
        raise ValueError("cost_journal_mismatch")


def shape(value, fields):
    require(type(value) is dict and set(value) == fields)


def time_order(*values):
    stamps = [spend._time(v) for v in values]
    require(stamps == sorted(stamps))


def origin(kind="unattributed", **values):
    return dict(kind=kind, **{k: values.get(k) for k in ORIGIN_FIELDS})


def unavailable(reason="journal_unavailable", *, status="unavailable"):
    return dict(schema_version=1, status=status, reason=reason)


class Read:
    """One owned transaction, one deadline and one cumulative artifact budget."""
    def __init__(self, connection, deadline, environment="local"):
        self.connection, self.deadline = connection, deadline
        self.environment = environment
        self.remaining = MAX_BYTES
        self.cache: dict = {}
        self.catalogs: set = set()

    def check(self):
        if time.monotonic() >= self.deadline:
            raise Deadline

    def execute(self, query, params=None):
        self.check()
        left = max(1, int((self.deadline-time.monotonic())*1000))
        self.connection.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                                (str(min(1500, left)), str(min(250, left))))
        result = self.connection.execute(query, params)
        self.check()
        return result

    @contextmanager
    def pipeline(self):
        # Cost reads must execute synchronously: each SQL statement receives the
        # remaining deadline before execution and is checked after it returns.
        # Delegating to the driver pipeline would check queued, unfinished SQL.
        self.check()
        yield
        self.check()

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def charge(self, size):
        require(type(size) is int and size >= 0)
        if size > self.remaining:
            raise Limited
        self.remaining -= size

    def validate(self, key, validator):
        if key not in self.catalogs:
            validator(self, self.environment)
            self.catalogs.add(key)

    def artifact(self, schema, table, digest, limit, *, minimum=0):
        s._sha(digest)
        key = (schema, table, digest)
        if key in self.cache:
            return self.cache[key]
        row = self.execute(f"SELECT byte_count,octet_length(payload) FROM {schema}.{table} WHERE sha=%s", (digest,)).fetchone()
        require(row is not None and type(row[0]) is int and minimum <= row[0] == row[1] <= limit)
        self.charge(row[0])
        raw = self.execute(f"SELECT payload FROM {schema}.{table} WHERE sha=%s", (digest,)).fetchone()[0]
        require(type(raw) is bytes and len(raw) == row[0] and p._sha(raw) == digest)
        self.cache[key] = raw
        return raw

    def document(self, table, digest):
        raw = self.artifact(checks.SCHEMA, table, digest, checks._ARTIFACTS[table], minimum=1)
        value = p._decode(raw)
        require(type(value) is dict and p._canonical(value) == raw)
        return value

    def projection(self, namespace, identity, *, optional=False):
        key = ("projection", namespace, identity)
        if key in self.cache:
            return self.cache[key]
        row = self.execute("SELECT canonical_sha,byte_count,field_count FROM theheat_projection.versions WHERE namespace=%s AND snapshot_id=%s", (namespace, identity)).fetchone()
        if row is None and optional:
            return None
        require(row is not None and type(row[1]) is int and 0 < row[1] <= p.MAX_BYTES and type(row[2]) is int and 0 <= row[2] <= p.MAX_FIELDS)
        refs = self.execute("SELECT f.name_json,a.byte_count,octet_length(a.payload) FROM theheat_projection.fields f LEFT JOIN theheat_projection.artifacts a ON a.sha=f.artifact_sha WHERE f.namespace=%s AND f.snapshot_id=%s LIMIT %s", (namespace, identity, p.MAX_FIELDS+1)).fetchall()
        require(len(refs) == row[2] and all(type(r[1]) is int and 1 <= r[1] == r[2] <= p.MAX_BYTES for r in refs))
        require(2+sum(len(r[0])+1+r[1] for r in refs)+max(0,len(refs)-1) == row[1])
        self.charge(row[1])
        receipt, value = p.PostgresProjectionRepository._read(self, namespace, identity)
        require(receipt.canonical_sha256 == row[0])
        self.cache[key] = (receipt, value)
        return receipt, value

    def admission(self, identity):
        from src.commands.postgres_authority import _command, _decode, _id, MAX_BODY, NAMESPACE
        _id(identity)
        key = ("admission_command", identity)
        if key in self.cache:
            return self.cache[key]
        join = "FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) WHERE i.command_id=%s"
        sizes = self.execute("SELECT octet_length(i.command_bytes),octet_length(r.result_bytes) "+join,(identity,)).fetchone()
        require(sizes is not None and all(type(n) is int and 0 < n <= MAX_BODY for n in sizes))
        self.charge(sum(sizes))
        row = self.execute("SELECT i.command_bytes,i.digest,r.result_bytes,r.digest,r.state_version,r.namespace,r.snapshot_id,i.accepted_at "+join,(identity,)).fetchone()
        require(row is not None and (len(row[0]),len(row[2])) == sizes)
        command, result = _command(row[0],row[1]), _decode(row[2],row[3])
        require(command.command_id == result.get("command_id") == identity and command.action == "admit_checked_candidate"
                and result.get("digest") == command.digest and result.get("actor_subject") == command.actor_subject
                and result.get("status") == "applied" and type(result.get("state_version")) is int
                and result["state_version"] == row[4] and row[5] == NAMESPACE and row[6] == str(row[4]))
        time_order(command.requested_at,row[7],result["completed_at"])
        self.cache[key] = (command,result)
        return command,result

    def dispatch(self, identity, at):
        require(self.execute("SELECT recorded_at FROM theheat_spending.events WHERE intent_id=%s AND kind='dispatched'", (identity,)).fetchone() == (spend._time(at),))


def _brief(reader, identity):
    receipt, value = reader.projection(generation.INPUT, identity)
    shape(value, generation.FIELDS)
    require(type(value["schema_version"]) is int and value["schema_version"] in (1, 2)
            and receipt.canonical_sha256 == identity and type(value["urgent"]) is bool)
    time_order(value["captured_at"], value["useful_until"])
    return value


def _source_run(reader, brief):
    if brief["schema_version"] != 2:
        return None
    from uuid import UUID
    from src.storage import ghcn_runtime_inputs, scientific_supply
    ref = brief["bundle"]["raw_signal_dump"]["ghcn_claim_view"]
    require(ref["kind"]=="ghcn_claim_view_v1" and str(UUID(ref["source_run_id"]))==ref["source_run_id"])
    for key, namespace in (("source_result",ghcn_runtime_inputs.RESULT),("runtime_input",ghcn_runtime_inputs.INPUT),("scientific_supply",scientific_supply.NAMESPACE)):
        item=ref[key]
        shape(item,{"namespace","snapshot_id","sha256"})
        require(item["namespace"]==namespace and item["snapshot_id"]=="run:"+ref["source_run_id"])
        receipt,_=reader.projection(namespace,item["snapshot_id"])
        require(receipt.canonical_sha256==item["sha256"])
    return ref["source_run_id"]


def _sync(reader, identity, selected=None):
    cache_key=("sync_envelope",identity)
    if cache_key in reader.cache:
        cached=reader.cache[cache_key]
        if selected is not None:
            require(selected["intent"]==sync.reservation(cached["job"]))
        return cached
    _, job = reader.projection(sync.JOB, identity)
    shape(job, sync.JOB_FIELDS)
    require(type(job["schema_version"]) is int and job["schema_version"] == 1 and job["origin_kind"] == synchronous_origin.ORIGIN
            and job["generation_id"] == identity and type(job["samples"]) is int and job["samples"] == 1)
    brief = _brief(reader, job["brief_id"])
    require(brief["urgent"] is True and job["brief_sha256"] == job["brief_id"] and job["bundle"] == brief["bundle"]
            and identity == "gss_"+fingerprint(dict(brief_id=job["brief_id"], **job["context"]))
            and job["intent_id"] == "writer_"+identity[4:] and sync.digest(job["request"]) == job["request_sha256"])
    for key in ("bundle", "memory", "policy"):
        require(fingerprint(job[key]) == job["context"][key+"_sha256"])
    created, deadline = utc_datetime(job["created_at"]), utc_datetime(job["useful_until"])
    require(created >= utc_datetime(brief["captured_at"]) and deadline == min(utc_datetime(brief["useful_until"]),created+timedelta(days=7))
            and (deadline-created).total_seconds() > 600)
    if selected is not None:
        require(selected["intent"] == sync.reservation(job))
    attempt = reader.projection(sync.ATTEMPT, identity, optional=True)
    result = dict(job=job, brief=brief, attempt=None, observation=None, raw=None)
    def retained():
        reader.cache[cache_key]=result
        return result
    if attempt is None:
        if selected is not None:
            require(selected["state"] in {"reserved", "released"})
        return retained()
    _, granted = attempt
    shape(granted, sync.ATTEMPT_FIELDS)
    require(type(granted["schema_version"]) is int and granted["schema_version"] == 1)
    wire = base64.b64decode(granted["wire_base64"], validate=True)
    require(0 < len(wire) <= 2_000_000 and p._sha(wire) == granted["wire_sha256"] and usage.decode(wire) == job["request"])
    require(granted["generation_id"] == identity and granted["job_sha256"] == sync.digest(job)
            and granted["intent_id"] == job["intent_id"] and granted["request_sha256"] == job["request_sha256"]
            and granted["brief_sha256"] == job["brief_sha256"] and granted["policy_sha256"] == job["context"]["policy_sha256"]
            and granted["allowance_sha256"] == job["reservation"]["estimate_sha256"]
            and granted["method"] == "POST" and granted["endpoint"] == "anthropic_messages_v1"
            and granted["grant_id"] == fingerprint({k:v for k,v in granted.items() if k not in {"grant_id","wire_base64"}}))
    reader.dispatch(job["intent_id"], granted["granted_at"])
    time_order(job["created_at"], granted["granted_at"])
    result["attempt"] = granted
    observed = reader.projection(sync.OBSERVATION, granted["grant_id"], optional=True)
    if observed is None:
        return retained()
    _, observed = observed
    shape(observed, sync.OBS_FIELDS)
    raw = base64.b64decode(observed["raw_base64"], validate=True)
    require(type(observed["schema_version"]) is int and observed["schema_version"] == 1
            and type(observed["byte_count"]) is int and len(raw) == observed["byte_count"] <= observations.MAX_RESPONSE_BYTES
            and p._sha(raw) == observed["raw_sha256"] and all(observed[k] == granted[k] for k in ("generation_id","grant_id","request_sha256","wire_sha256"))
            and type(observed["complete"]) is bool and observed["complete"] == (observed["reason"] == "received")
            and observed["reason"] in {"received","transport_unavailable","size_exceeded","time_exceeded","unsupported_content_encoding","cleanup_failed"}
            and (observed["http_status"] is None or type(observed["http_status"]) is int and 100 <= observed["http_status"] <= 599))
    time_order(granted["granted_at"], observed["observed_at"])
    result.update(observation=observed, raw=raw)
    resolution = reader.projection(sync.RESOLUTION, identity, optional=True)
    if resolution is not None:
        _, resolved = resolution
        shape(resolved,{"schema_version","generation_id","observation_sha256","parser_version","disposition","writer_result","candidate_id","usage","observed_at"})
        require(type(resolved["schema_version"]) is int and resolved["schema_version"]==1 and resolved["generation_id"]==identity
                and resolved["observation_sha256"]==sync.digest(observed) and resolved["parser_version"]=="writer_message_v1"
                and resolved["observed_at"]==observed["observed_at"] and resolved["disposition"] in {"candidate","writer_kill","ineligible"})
        result["terminal_usage"] = resolved["usage"]
    return retained()


def _packet(reader, identity):
    from src.commands import postgres_revision_checks as revisions, postgres_sync_checks as sync_checks
    extra = ",origin_kind,draft_namespace,draft_enrollment_id" if revisions.upgraded(reader) else ""
    if sync_checks.upgraded(reader):
        extra += ",sync_namespace,sync_enrollment_id"
    row = reader.execute(f"SELECT job_id,custom_id,packet_sha256,recorded_at{extra} FROM theheat_checks.sets WHERE check_set_id=%s", (identity,)).fetchone()
    require(row is not None)
    packet = reader.document("packet_artifacts", row[2])
    require(fingerprint(packet) == identity and type(packet.get("schema_version")) is int)
    version = packet["schema_version"]
    if version not in {2,3,4,5,6}:
        return None
    if version == 2:
        shape(packet, cj._PACKET_FIELDS | {"derivation", "derivation_id"})
        require(row[0:2] == (packet["job_id"],packet["custom_id"]) and (len(row)==4 or row[4]=="batch_candidate" and all(v is None for v in row[5:])))
        registration, plan = _batch_plan(reader, packet["job_id"])
        require(packet["plan_sha256"] == registration["plan_sha256"] and packet["useful_until"] == plan["useful_until"]
                and packet["policy"] == plan["policy"] and any(r["custom_id"]==packet["custom_id"] for r in plan["requests"]))
    else:
        module = check_origin if version in {3,6} else synchronous_origin
        shape(packet, module.FIELDS)
        require(len(row)>=7 and packet["origin_kind"]==module.ORIGIN and row[0] is row[1] is None and row[4]==module.ORIGIN
                and packet["enrollment_id"]==module.enrollment_id(packet) and row[3]==packet["captured_at"])
        namespace, enrollment = row[5:7] if version in {3,6} else row[7:9]
        require(namespace==module.NAMESPACE and enrollment==packet["enrollment_id"]
                and (len(row)==7 or all(v is None for v in (row[7:9] if version in {3,6} else row[5:7]))))
        receipt, retained = reader.projection(namespace,enrollment)
        require(receipt.canonical_sha256==row[2] and retained==packet)
    require(packet["required_stages"]==list(cj.STAGES) and packet["check_date"]==row[3][:10])
    time_order(row[3],packet["useful_until"])
    for key in ("bundle","memory","policy","checker_state"):
        expected=packet["checker_state_sha256"] if key=="checker_state" else packet["current_context"][key+"_sha256"]
        require(fingerprint(packet[key])==expected)
    if version in {2,4,5}:
        require(fingerprint(packet["derivation"])==packet["derivation_id"] and packet["derivation"]["text_sha256"]==packet["text_sha256"])
    if version in {3,4,5,6}:
        require(p._sha(p._canonical(packet["checker_state"]))==packet["state_sha256"])
    if version in {3,6}:
        _revision_media_envelope(packet)
    return packet,row[3]


def _revision_media_envelope(packet):
    """Historical saved-media links only; never current review or raster truth."""
    target=DraftTarget.parse(packet["draft_target"])
    drafts=packet["checker_state"].get("drafts")
    require(type(drafts) is list)
    matches=[d for d in drafts if type(d) is dict and d.get("id")==target.draft_id]
    require(len(matches)==1)
    draft=matches[0]
    require(dict(draft_id=draft["id"],**draft_identity(draft),decision_revision=decision_revision(draft))==target.as_dict()
            and packet["final_text"]==draft.get("text") and type(packet["final_text"]) is str
            and text_hash(packet["final_text"])==packet["text_sha256"]==target.text_sha256)
    attachment=draft.get("media_attachment",{})
    require(type(attachment) is dict)
    if packet["schema_version"]==3:
        require(attachment.get("schema_version")!=2)
        return
    require(type(attachment.get("schema_version")) is int and attachment["schema_version"]==2)
    media,review=packet["media"],draft.get("media_review_binding",{})
    shape(media,{"proposal_sha256","packet_sha256","review_sha256","review_command_id"})
    extra={"platform_description_sha256"} if type(review) is dict and review.get("schema_version")==2 else set()
    shape(review,{"schema_version","proposal_sha256","packet_sha256","review_sha256","command_id"}|extra)
    require(type(review["schema_version"]) is int and review["schema_version"] in (1,2)
            and type(media["review_command_id"]) is str and media["review_command_id"]==review["command_id"])
    if extra:
        s._sha(review["platform_description_sha256"])
    from src.commands.postgres_authority import _id
    _id(media["review_command_id"])
    for key in ("proposal_sha256","packet_sha256","review_sha256"):
        s._sha(media[key])
        require(media[key]==review[key])
    published=attachment.get("published",{})
    require(type(published) is dict and published.get("family")=="nws_local_standard_radar_v1")
    frame=utc_datetime(published.get("frame_minute_utc"))
    require(frame.second==frame.microsecond==0)
    frame_deadline=min(frame+timedelta(minutes=15),utc_datetime(published.get("valid_end")))
    captured=utc_datetime(packet["captured_at"])
    require(utc_datetime(published.get("useful_until"))==frame_deadline
            and captured<utc_datetime(packet["useful_until"])==min(frame_deadline,
                utc_datetime(packet["source_useful_until"]),utc_datetime(packet["provenance_useful_until"]),
                captured.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)))


def _sync_capture(reader, capture):
    """Stored writer/capture references, never candidate interpretation."""
    shape(capture,sync.INPUT_FIELDS)
    require(type(capture["schema_version"]) is int and capture["schema_version"]==2 and capture["origin_kind"]==synchronous_origin.ORIGIN)
    parent=_sync(reader,capture["generation_id"])
    _,resolution=reader.projection(sync.RESOLUTION,capture["generation_id"])
    require(parent["attempt"] is not None and parent["observation"] is not None
            and capture["grant_id"]==parent["attempt"]["grant_id"] and capture["observation_sha256"]==sync.digest(parent["observation"])
            and capture["resolution_sha256"]==sync.digest(resolution) and resolution["disposition"]=="candidate"
            and resolution["candidate_id"]==capture["candidate_id"]
            and capture["candidate_id"]==fingerprint(dict(origin_kind=synchronous_origin.ORIGIN,generation_id=capture["generation_id"],
                grant_id=capture["grant_id"],observation_sha256=capture["observation_sha256"],candidate=resolution["writer_result"]))
            and capture["request_sha256"]==parent["job"]["request_sha256"] and capture["bundle"]==parent["job"]["bundle"]
            and capture["memory"]==parent["job"]["memory"] and capture["current_context"]==parent["job"]["context"])
    time_order(parent["observation"]["observed_at"],capture["captured_at"])
    return parent,resolution


def _batch_source_capture(reader, capture, source):
    from src.commands import postgres_candidate_admission as admission, postgres_batch_results as results, batch_result_journal as r
    from src.commands import postgres_batch_worker as worker, batch_worker_journal as w
    shape(capture,admission.INPUT_FIELDS)
    require(type(capture["schema_version"]) is int and capture["schema_version"]==1
            and admission.input_id(capture["job_id"],capture["custom_id"],capture["candidate_id"])==source["admission_input_id"]
            and capture["job_id"]==source["job_id"] and capture["plan_sha256"]==source["plan_sha256"])
    registration,plan=_batch_plan(reader,capture["job_id"])
    _,job=reader.projection(generation.JOB,capture["job_id"])
    shape(job,{"brief_id","memory","context","reservation","negative_cache_input_sha","negative_cache_epoch","custom_id"})
    brief=_brief(reader,job["brief_id"])
    require(registration["plan_sha256"]==source["plan_sha256"] and job["brief_id"]==source["brief_id"]
            and plan["samples"]==1 and len(plan["requests"])==1 and brief["urgent"] is False
            and job["custom_id"]==capture["custom_id"]==plan["requests"][0]["custom_id"]
            and job["context"]==capture["current_context"]=={k:plan[k] for k in w._CONTEXT}
            and job["memory"]==capture["memory"] and fingerprint(job["memory"])==plan["memory_sha256"]
            and brief["bundle"]==capture["bundle"] and fingerprint(brief["bundle"])==plan["bundle_sha256"])
    reader.validate("results",results.validate)
    identity=capture["receipt_id"]
    size=reader.execute("SELECT octet_length(binding) FROM theheat_batch_results.receipts WHERE receipt_id=%s",(identity,)).fetchone()
    require(size is not None and 2<=size[0]<=4096)
    reader.charge(size[0])
    row=reader.execute("SELECT job_id,grant_id,metadata_sha256,results_sha256,binding,binding_sha256,recorded_at FROM theheat_batch_results.receipts WHERE receipt_id=%s",(identity,)).fetchone()
    require(row is not None and len(row[4])==size[0] and p._sha(row[4])==row[5])
    binding=p._decode(row[4])
    r._binding(binding)
    require(p._canonical(binding)==row[4] and fingerprint(binding)==identity and binding["complete"] is True
            and binding==dict(job_id=row[0],grant_id=row[1],metadata_sha256=row[2],results_sha256=row[3],complete=True)
            and row[0]==capture["job_id"])
    reader.validate("worker",worker.validate)
    submitted=reader.execute("SELECT fence,grant_id,recorded_at FROM theheat_batch_work.submissions WHERE job_id=%s",(row[0],)).fetchone()
    require(submitted is not None and submitted[1]==row[1])
    lease=reader.execute("SELECT owner,recorded_at,expires_at FROM theheat_batch_work.leases WHERE job_id=%s AND fence=%s",(row[0],submitted[0])).fetchone()
    require(lease is not None and lease[1]<=submitted[2]<lease[2]
            and row[1]==w._grant(registration,dict(owner=lease[0],fence=submitted[0]),submitted[2]))
    reader.dispatch(registration["intent_id"],submitted[2])
    time_order(registration["registered_at"],submitted[2],row[6],capture["captured_at"])
    return brief,plan["useful_until"]


def _revision_source(reader, packet):
    from src.commands.postgres_candidate_admission import NAMESPACE
    ref=packet["source_origin"]
    shape(ref,{"namespace","snapshot_id","canonical_sha256"})
    require(ref["namespace"]==check_origin.SOURCE_NAMESPACE and ref["snapshot_id"]==fingerprint(dict(draft_id=packet["draft_target"]["draft_id"])))
    receipt,source=reader.projection(ref["namespace"],ref["snapshot_id"])
    common={"schema_version","draft_id","event_id","admission_command_id","admission_input_id","admission_input_sha256",
        "brief_id","bundle_sha256","memory_sha256","source_useful_until","provenance_useful_until"}
    version=source.get("schema_version")
    if type(version) is int and version == 3:
        return _important_revision_source(reader, packet, receipt, source)
    require(type(version) is int and version in {1,2})
    shape(source,common | ({"job_id","plan_sha256"} if version==1 else {"origin_kind"}|synchronous_origin.REFERENCES))
    require(receipt.canonical_sha256==ref["canonical_sha256"] and source["draft_id"]==packet["draft_target"]["draft_id"]
            and source["event_id"]==packet["bundle"]["event_id"] and source["bundle_sha256"]==fingerprint(packet["bundle"])
            and source["memory_sha256"]==fingerprint(packet["memory"])
            and source["source_useful_until"]==packet["source_useful_until"] and source["provenance_useful_until"]==packet["provenance_useful_until"])
    command,result=reader.admission(source["admission_command_id"])
    require(result["candidate"]["draft_id"]==source["draft_id"]
            and all(command.payload[k]==source[k] for k in ("admission_input_id","admission_input_sha256")))
    captured_receipt,capture=reader.projection(NAMESPACE,source["admission_input_id"])
    require(captured_receipt.canonical_sha256==source["admission_input_sha256"]
            and capture["bundle"]==packet["bundle"] and capture["memory"]==packet["memory"])
    if version==2:
        require(source["origin_kind"]==synchronous_origin.ORIGIN and sync.input_id(capture)==source["admission_input_id"]
                and all(source[k]==capture[k] for k in synchronous_origin.REFERENCES)
                and all(command.payload[k]==capture[k] for k in ("origin_kind","generation_id","candidate_id")))
        parent,_=_sync_capture(reader,capture)
        brief,provenance=parent["brief"],parent["job"]["useful_until"]
        require(parent["job"]["brief_id"]==source["brief_id"])
    else:
        require(all(command.payload[k]==capture[k] for k in ("job_id","custom_id","candidate_id")))
        brief,provenance=_batch_source_capture(reader,capture,source)
    require(source["source_useful_until"]==brief["useful_until"] and source["provenance_useful_until"]==provenance)
    time_order(capture["captured_at"],result["completed_at"],packet["captured_at"])
    return source["brief_id"],_source_run(reader,brief)


def _check(reader, record, attempt_row):
    identity,stage,grant,binding_sha,request_sha,at = attempt_row
    loaded=_packet(reader,identity)
    if loaded is None:
        return origin(),None,"unsupported_origin"
    packet,enrolled=loaded
    binding=reader.document("binding_artifacts",binding_sha)
    shape(binding,{"check_set_id","stage","request_sha256","reservation","owner","fence","begun_at"})
    require(fingerprint(binding)==grant and binding["check_set_id"]==identity and binding["stage"]==stage
            and binding["request_sha256"]==request_sha and binding["begun_at"]==at and type(binding["fence"]) is int
            and binding["reservation"]==record["intent"] and stage in cj.STAGES and stage!="deterministic")
    intent=record["intent"]
    require(intent["job_id"]==check_origin.spending_job(packet) and intent["provider"]=="google" and intent["role"]==stage
            and intent["model"]==packet["policy"]["models"][stage] and intent["request_sha256"]==request_sha)
    reader.artifact(checks.SCHEMA,"request_artifacts",request_sha,cj.MAX_INPUT_BYTES,minimum=1)
    if packet["schema_version"]==2:
        lease=reader.execute("SELECT owner,recorded_at,expires_at FROM theheat_batch_work.leases WHERE job_id=%s AND fence=%s",(packet["job_id"],binding["fence"])).fetchone()
    else:
        from src.commands import postgres_stage_revision_checks as stages
        if stages.protocol(reader,identity)==2:
            # Bounded passive original-cap join, never active prefix/current proof.
            cap=stages.lease(reader,identity,binding["fence"])
            require(cap is not None and cap["stage"]==stage and cap["owner"]=="revision-checks:"+packet["enrollment_id"]
                and utc_datetime(cap["expires_at"])==min(utc_datetime(cap["recorded_at"])+timedelta(seconds=180),utc_datetime(packet["useful_until"])))
            lease=(cap["owner"],cap["recorded_at"],cap["expires_at"])
        else:
            lease=reader.execute("SELECT owner,recorded_at,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s AND fence=%s",(identity,binding["fence"])).fetchone()
    require(lease is not None and lease[0]==binding["owner"] and lease[1]<=at<lease[2] and enrolled<=at<packet["useful_until"] and at[:10]==packet["check_date"])
    reader.dispatch(intent["intent_id"],at)
    refs=origin("required_check",check_set_id=identity,stage=stage,grant_id=grant,request_sha256=request_sha)
    if packet["schema_version"] in {4,5}:
        capture_receipt,capture=reader.projection("candidate-admission-input-v1",packet["admission_input_id"])
        require(capture_receipt.canonical_sha256==packet["admission_input_sha256"] and sync.input_id(capture)==packet["admission_input_id"]
                and all(capture[k]==packet[k] for k in synchronous_origin.REFERENCES | {"bundle","memory","current_context"}))
        parent,resolution=_sync_capture(reader,capture)
        require(packet["candidate"]==resolution["writer_result"])
        refs.update(brief_id=parent["job"]["brief_id"],generation_id=packet["generation_id"],source_run_id=_source_run(reader,parent["brief"]))
    elif packet["schema_version"] in {3,6}:
        refs["brief_id"],refs["source_run_id"]=_revision_source(reader,packet)
    elif packet["job_id"].startswith("iv_") and _batch_plan(reader, packet["job_id"])[1]["schema_version"] == 2:
        job, brief, member, original_lease = _important_member(reader, packet)
        require(binding["owner"] == original_lease["owner"] and binding["fence"] == original_lease["fence"]
                and original_lease["recorded_at"] <= at < original_lease["expires_at"])
        _, allowance = reader.projection("important-alternate-allowance-v1", job["allowance_id"])
        require(intent == dict(allowance["check_reservations"][stage],
                intent_id="ic_"+fingerprint(dict(job_id=packet["job_id"], slot=member["slot"], stage=stage)),
                job_id=packet["job_id"], request_sha256=request_sha))
        refs.update(brief_id=job["brief_id"], generation_id=packet["job_id"], source_run_id=_source_run(reader, brief))
    else:
        saved=reader.projection(generation.JOB,packet["job_id"],optional=True)
        if saved:
            brief=_brief(reader,saved[1]["brief_id"])
            require(saved[1]["custom_id"]==packet["custom_id"] and saved[1]["context"]==packet["current_context"]
                    and saved[1]["memory"]==packet["memory"] and brief["bundle"]==packet["bundle"])
            refs.update(brief_id=saved[1]["brief_id"],generation_id=packet["job_id"])
    terminal=reader.execute("SELECT receipt_sha256,disposition,recorded_at FROM theheat_checks.receipts WHERE grant_id=%s",(grant,)).fetchone()
    terminal_usage=None
    if terminal:
        doc=reader.document("receipt_artifacts",terminal[0])
        expected=checks._receipt_doc(doc,dict(grant_id=grant,binding=binding))
        require(terminal[1] in {expected,"stale"})
        time_order(at,terminal[2])
        refs["receipt_id"]=terminal[0]
        terminal_usage=doc["usage"]
    observed=reader.execute("SELECT metadata_sha256,raw_sha256,recorded_at FROM theheat_check_executions.observations WHERE grant_id=%s",(grant,)).fetchone()
    if observed is None:
        return refs,None,"response_missing"
    encoded=reader.artifact(observations.SCHEMA,"metadata_artifacts",observed[0],4096,minimum=1)
    meta=p._decode(encoded)
    observations._metadata(meta)
    require(p._canonical(meta)==encoded and meta["check_set_id"]==identity and meta["stage"]==stage and meta["grant_id"]==grant
            and meta["request_sha256"]==request_sha and meta["raw_sha256"]==observed[1])
    time_order(at,observed[2])
    raw=reader.artifact(observations.SCHEMA,"raw_artifacts",observed[1],observations.MAX_RESPONSE_BYTES)
    refs["raw_sha256"]=observed[1]
    return refs,dict(raw=raw,observed_at=observed[2],complete=meta["complete"],terminal_usage=terminal_usage),None


def _batch_plan(reader, identity, selected=None):
    from src.commands import postgres_batch as batch, batch_journal as b
    from src.two_bot.batch_contract import MAX_PLAN_BYTES
    reader.validate("batch",batch.validate)
    row=reader.execute("SELECT plan_sha,intent_id,registered_at FROM theheat_batches.registrations WHERE job_id=%s",(identity,)).fetchone()
    require(row is not None)
    raw=reader.artifact(batch.SCHEMA,"plans",row[0],MAX_PLAN_BYTES,minimum=1)
    plan=b._plan(raw,row[0])
    require(plan["job_id"]==identity and batch._window(plan,utc_datetime(row[2])))
    if selected is not None:
        require(selected["intent"]["intent_id"]==row[1])
        b._join(plan,row[0],selected["intent"])
    return dict(job_id=identity,plan_sha256=row[0],intent_id=row[1],registered_at=row[2]),plan


def _important_command(reader, identity, action):
    """Bounded historical command join; no current authorization or execution."""
    from src.commands.postgres_authority import _command, _decode, _id, MAX_BODY, NAMESPACE
    _id(identity)
    join = "FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) WHERE i.command_id=%s"
    sizes = reader.execute("SELECT octet_length(i.command_bytes),octet_length(r.result_bytes) "+join, (identity,)).fetchone()
    require(sizes is not None and all(type(n) is int and 0 < n <= MAX_BODY for n in sizes))
    reader.charge(sum(sizes))
    row = reader.execute("SELECT i.command_bytes,i.digest,r.result_bytes,r.digest,r.state_version,r.namespace,r.snapshot_id,i.accepted_at "+join, (identity,)).fetchone()
    require(row is not None and (len(row[0]), len(row[2])) == sizes)
    command, result = _command(row[0], row[1]), _decode(row[2], row[3])
    require(command.command_id == result.get("command_id") == identity and command.action == action
            and result.get("digest") == command.digest and result.get("actor_subject") == command.actor_subject
            and result.get("status") == "applied" and type(result.get("state_version")) is int
            and result["state_version"] == row[4] and row[5] == NAMESPACE and row[6] == str(row[4]))
    time_order(command.requested_at, row[7], result["completed_at"])
    return command, result


def _important_job(reader, registration, plan, selected=None):
    from src.commands import postgres_important_variants as group, batch_worker_journal as w
    identity = registration["job_id"]
    _, job = reader.projection(group.JOB, identity)
    shape(job, {"schema_version", "brief_id", "allowance_id", "plan_sha256", "context", "memory", "policy",
        "source_useful_until", "useful_until", "created_at", "slots", "reservation", "command_id",
        "authorized_subject", "authentication_context", "negative_cache_input_sha", "negative_cache_epoch"})
    receipt, allowance = reader.projection(group.ALLOWANCE, job["allowance_id"])
    brief = _brief(reader, job["brief_id"])
    key = fingerprint(dict(brief_id=job["brief_id"], context=job["context"], allowance_sha256=job["allowance_id"]))
    reservation = dict(allowance["writer_reservation"], intent_id="writer_"+key, job_id=identity,
                       request_sha256=registration["plan_sha256"])
    require(type(job["schema_version"]) is int and job["schema_version"] == 1
            and plan["schema_version"] == 2 and plan["samples"] == 2 and len(plan["requests"]) == 2
            and identity == "iv_"+key and receipt.canonical_sha256 == job["allowance_id"] == plan["allowance_sha256"]
            and allowance == plan["allowance"] and job["plan_sha256"] == registration["plan_sha256"]
            and job["reservation"] == reservation and registration["intent_id"] == reservation["intent_id"]
            and brief["urgent"] is False and allowance["brief_id"] == allowance["brief_sha256"] == job["brief_id"]
            and brief["bundle"] == plan["bundle"] and job["memory"] == plan["memory"] and job["policy"] == plan["policy"]
            and job["context"] == allowance["context"] == {k:plan[k] for k in w._CONTEXT}
            and job["created_at"] == plan["created_at"] and job["useful_until"] == plan["useful_until"]
            and job["source_useful_until"] == brief["useful_until"]
            and job["authorized_subject"] == allowance["authorized_subject"]
            and job["authentication_context"] == allowance["authentication_context"]
            and job["slots"] == [dict(slot=i+1, custom_id=r["custom_id"], params_sha256=fingerprint(r["params"]))
                                  for i,r in enumerate(plan["requests"])])
    if selected is not None:
        require(selected["intent"] == reservation)
    command, result = _important_command(reader, job["command_id"], "request_important_variants")
    require(command.actor_subject == job["authorized_subject"] and command.authentication_context == job["authentication_context"]
            and all(command.payload[k] == v for k,v in dict(brief_id=job["brief_id"], brief_sha256=job["brief_id"],
                allowance_id=job["allowance_id"], allowance_sha256=job["allowance_id"]).items())
            and command.payload["expected_policy_sha256"] == fingerprint(job["policy"])
            and result["generation"] == dict(brief_id=job["brief_id"], job_id=identity,
                plan_sha256=job["plan_sha256"], intent_id=registration["intent_id"], generation_status="queued",
                execution_mode="important_batch", slate_id=identity, slate_sha256=p._sha(p._canonical(job))))
    _, claim = reader.projection(group.CLAIM, group.claim_id(brief, job["brief_id"]))
    require(claim == dict(schema_version=1, job_id=identity, command_id=command.command_id,
                         brief_id=job["brief_id"], allowance_id=job["allowance_id"]))
    time_order(brief["captured_at"], job["created_at"], result["completed_at"])
    return job, brief


def _important_member(reader, packet):
    """Historical per-slot membership, without re-running any editorial check."""
    from src.commands import postgres_important_variants as group, postgres_candidate_admission as admission
    registration, plan = _batch_plan(reader, packet["job_id"])
    job, brief = _important_job(reader, registration, plan)
    input_id = admission.input_id(packet["job_id"], packet["custom_id"], packet["candidate_id"])
    receipt, value = reader.projection(admission.NAMESPACE, input_id)
    shape(value, admission.INPUT_FIELDS)
    _, capture = reader.projection(group.CAPTURE, packet["job_id"])
    shape(capture, {"schema_version", "job_id", "plan_sha256", "receipt_id", "state_version", "state_sha256", "captured_at", "slots"})
    require(type(capture["schema_version"]) is int and capture["schema_version"] == 1
            and capture["job_id"] == value["job_id"] == packet["job_id"]
            and capture["plan_sha256"] == value["plan_sha256"] == job["plan_sha256"]
            and len(capture["slots"]) == 2 and [s["slot"] for s in capture["slots"]] == [1,2]
            and [{k:s[k] for k in ("slot","custom_id","params_sha256")} for s in capture["slots"]] == job["slots"]
            and admission.input_id(value["job_id"], value["custom_id"], value["candidate_id"]) == input_id
            and all(value[k] == packet[k] for k in ("candidate_id","custom_id","bundle","memory","current_context"))
            and value["bundle"] == brief["bundle"] and value["memory"] == job["memory"]
            and value["current_context"] == job["context"]
            and all(value[k] == capture[k] for k in ("receipt_id","state_version","state_sha256","captured_at")))
    matches = [s for s in capture["slots"] if s["custom_id"] == packet["custom_id"]]
    require(len(matches) == 1 and matches[0]["candidate"] is not None
            and matches[0]["candidate"]["admission_input_id"] == input_id
            and matches[0]["candidate"]["admission_input_sha256"] == receipt.canonical_sha256)
    writer = spend._record(reader, registration["intent_id"])
    require(writer is not None)
    refs, evidence, _ = _batch(reader, writer, (packet["job_id"],))
    require(evidence is not None and refs["receipt_id"] == value["receipt_id"])
    rows = [(line, usage.decode(line)) for line in evidence["raw"].splitlines()]
    matching = [(line,item) for line,item in rows if item["custom_id"] == value["custom_id"]]
    require(len(matching) == 1)
    raw, item = matching[0]
    require(p._sha(raw) == matches[0]["raw_sha256"]
            and value["candidate_id"] == fingerprint(dict(plan_sha256=value["plan_sha256"], custom_id=value["custom_id"], item=item)))
    _, lease = reader.projection(group.LEASE, packet["job_id"])
    return job, brief, matches[0], lease


def _important_revision_source(reader, packet, receipt, source):
    """Sealed historical membership for saved-revision costs, not approval."""
    from src.commands import postgres_important_variants as group, postgres_candidate_admission as admission
    shape(source, {"schema_version","origin_kind","draft_id","event_id","admission_command_id","job_id",
        "slate_sha256","admission_sha256","admission_input_id","admission_input_sha256","brief_id",
        "plan_sha256","bundle_sha256","memory_sha256","source_useful_until","provenance_useful_until"})
    require(source["origin_kind"] == group.ORIGIN and receipt.canonical_sha256 == packet["source_origin"]["canonical_sha256"]
            and source["draft_id"] == packet["draft_target"]["draft_id"] and source["event_id"] == packet["bundle"]["event_id"]
            and source["bundle_sha256"] == fingerprint(packet["bundle"]) and source["memory_sha256"] == fingerprint(packet["memory"])
            and source["source_useful_until"] == packet["source_useful_until"]
            and source["provenance_useful_until"] == packet["provenance_useful_until"])
    _, membership = reader.projection(group.ADMISSION, source["job_id"])
    shape(membership, {"schema_version","job_id","slate_sha256","admission_command_id","draft_id","selected_slot",
        "completion_snapshot","candidates","proofs","state_version","policy_sha256","admitted_at"})
    require(type(membership["schema_version"]) is int and membership["schema_version"] == 1
            and p._sha(p._canonical(membership)) == source["admission_sha256"]
            and all(membership[k] == source[k] for k in ("job_id","slate_sha256","admission_command_id","draft_id")))
    command, result = _important_command(reader, source["admission_command_id"], "admit_checked_slate")
    require(command.payload["slate_id"] == source["job_id"] and command.payload["slate_sha256"] == source["slate_sha256"]
            and command.payload["expected_completion_set_sha256"] == fingerprint(membership["completion_snapshot"])
            and command.payload["expected_state_version"] == membership["state_version"]
            and command.payload["expected_policy_sha256"] == membership["policy_sha256"]
            and result["candidate"]["draft_id"] == source["draft_id"]
            and result["candidate"]["slate_id"] == source["job_id"]
            and result["candidate"]["admission_sha256"] == source["admission_sha256"]
            and result["candidate"]["selected_slot"] == membership["selected_slot"])
    drafts = [d for d in packet["checker_state"].get("drafts", []) if d.get("id") == source["draft_id"]]
    candidates = membership["candidates"]
    require(len(drafts) == 1 and type(candidates) is list and 1 <= len(candidates) <= 2
            and drafts[0].get("candidates") == candidates
            and len({c["rank"] for c in candidates}) == len(candidates)
            and set(membership["proofs"]) == {str(c["rank"]) for c in candidates})
    selected = None
    for candidate in candidates:
        provenance = candidate["provenance"]
        loaded = _packet(reader, provenance["check_set_id"])
        require(loaded is not None)
        initial, enrolled = loaded
        require(initial["schema_version"] == 2 and initial["job_id"] == source["job_id"])
        job, brief, member, lease = _important_member(reader, initial)
        require(source["slate_sha256"] == p._sha(p._canonical(job)) and source["brief_id"] == job["brief_id"]
                and source["plan_sha256"] == job["plan_sha256"]
                and source["source_useful_until"] == job["source_useful_until"]
                and source["provenance_useful_until"] == job["useful_until"]
                and membership["policy_sha256"] == fingerprint(job["policy"]))
        input_id = admission.input_id(initial["job_id"], initial["custom_id"], initial["candidate_id"])
        input_receipt, value = reader.projection(admission.NAMESPACE, input_id)
        proofs = membership["proofs"][str(candidate["rank"])]
        require(set(proofs["stages"]) == set(cj.STAGES))
        rows = reader.execute("""SELECT a.stage,a.grant_id,a.binding_sha256,a.request_sha256,a.recorded_at,
            r.receipt_sha256,r.disposition,r.recorded_at,o.metadata_sha256,o.raw_sha256,o.recorded_at
            FROM theheat_checks.attempts a JOIN theheat_checks.receipts r USING(grant_id)
            JOIN theheat_check_executions.observations o USING(grant_id)
            WHERE a.check_set_id=%s LIMIT 5""", (provenance["check_set_id"],)).fetchall()
        require(len(rows) == 4 and {r[0] for r in rows} == set(cj.STAGES))
        actual_proofs = {}
        for stage, grant, binding_sha, request_sha, begun, terminal_sha, disposition, finished, meta_sha, raw_sha, observed in rows:
            binding = reader.document("binding_artifacts", binding_sha)
            shape(binding, {"check_set_id","stage","request_sha256","reservation","owner","fence","begun_at"})
            require(fingerprint(binding) == grant and binding["check_set_id"] == provenance["check_set_id"]
                    and binding["stage"] == stage and binding["request_sha256"] == request_sha and binding["begun_at"] == begun
                    and binding["owner"] == lease["owner"] and binding["fence"] == lease["fence"]
                    and lease["recorded_at"] <= begun < lease["expires_at"])
            terminal = reader.document("receipt_artifacts", terminal_sha)
            require(checks._receipt_doc(terminal, dict(grant_id=grant, binding=binding)) == disposition == "passed")
            metadata = p._decode(reader.artifact(observations.SCHEMA, "metadata_artifacts", meta_sha, 4096, minimum=1))
            observations._metadata(metadata)
            require(metadata["check_set_id"] == provenance["check_set_id"] and metadata["stage"] == stage
                    and metadata["grant_id"] == grant and metadata["request_sha256"] == request_sha
                    and metadata["raw_sha256"] == raw_sha and metadata["complete"] is True)
            reader.artifact(checks.SCHEMA, "request_artifacts", request_sha, cj.MAX_INPUT_BYTES, minimum=1)
            reader.artifact(observations.SCHEMA, "raw_artifacts", raw_sha, observations.MAX_RESPONSE_BYTES)
            time_order(enrolled, begun, observed, finished, membership["admitted_at"])
            actual_proofs[stage] = dict(grant_id=grant, request_sha256=request_sha,
                observation_sha256=raw_sha, receipt_sha256=terminal_sha)
        expected_proof = admission.completion_proof(provenance["check_set_id"], value, initial, actual_proofs)
        require(proofs == expected_proof and candidate["rank"] == member["slot"]
                and candidate["source"] == "retained_important_writer" and candidate["score"] is None
                and candidate["text"] == initial["derivation"]["final_text"]
                and provenance == dict(schema_version=1, job_id=source["job_id"], slot=member["slot"],
                    admission_input_id=input_id, admission_input_sha256=input_receipt.canonical_sha256,
                    candidate_id=initial["candidate_id"], derivation_id=initial["derivation_id"],
                    plan_sha256=job["plan_sha256"], custom_id=initial["custom_id"], receipt_id=value["receipt_id"],
                    completion_sha256=proofs["completion_sha256"], check_set_id=proofs["check_set_id"],
                    bundle_sha256=fingerprint(value["bundle"]), memory_sha256=fingerprint(value["memory"]),
                    policy_sha256=fingerprint(job["policy"])))
        if candidate["rank"] == membership["selected_slot"]:
            require(input_id == source["admission_input_id"] and input_receipt.canonical_sha256 == source["admission_input_sha256"])
            selected = brief
    require(selected is not None and selected["bundle"] == packet["bundle"])
    time_order(membership["admitted_at"], result["completed_at"], packet["captured_at"])
    return source["brief_id"], _source_run(reader, selected)


def _batch(reader, record, registration_row):
    from src.commands import postgres_batch_results as results, batch_result_journal as r
    from src.commands import postgres_batch_worker as worker, batch_worker_journal as w
    reader.validate("results",results.validate)
    job_id=registration_row[0]
    registration,plan=_batch_plan(reader,job_id,record)
    important = plan["schema_version"] == 2
    if important:
        job, brief = _important_job(reader, registration, plan, record)
    else:
        saved=reader.projection(generation.JOB,job_id,optional=True)
        if saved is None or plan["samples"]!=1 or len(plan["requests"])!=1:
            return origin(),None,"unsupported_origin"
        _,job=saved
        shape(job,{"brief_id","memory","context","reservation","negative_cache_input_sha","negative_cache_epoch","custom_id"})
        brief=_brief(reader,job["brief_id"])
        require(brief["urgent"] is False and job["custom_id"]==plan["requests"][0]["custom_id"]
                and job["context"]=={k:plan[k] for k in w._CONTEXT}
                and fingerprint(job["memory"])==plan["memory_sha256"] and fingerprint(brief["bundle"])==plan["bundle_sha256"]
                and all(record["intent"][k]==v for k,v in job["reservation"].items()))
    refs=origin("sourced_batch_writer",brief_id=job["brief_id"],generation_id=job_id,request_sha256=registration["plan_sha256"])
    submitted=reader.execute("SELECT fence,grant_id,recorded_at FROM theheat_batch_work.submissions WHERE job_id=%s",(job_id,)).fetchone()
    if submitted is None:
        require(record["state"] in {"reserved","released"})
        return refs,None,"not_dispatched"
    fence,grant,at=submitted
    lease=reader.execute("SELECT owner,recorded_at,expires_at FROM theheat_batch_work.leases WHERE job_id=%s AND fence=%s",(job_id,fence)).fetchone()
    require(lease is not None and lease[1]<=at<lease[2] and grant==w._grant(registration,dict(owner=lease[0],fence=fence),at))
    reader.dispatch(registration["intent_id"],at)
    refs["grant_id"]=grant
    time_order(registration["registered_at"],at)
    count=reader.execute("SELECT count(*) FROM theheat_batch_results.receipts WHERE job_id=%s",(job_id,)).fetchone()[0]
    require(count<=r.MAX_RECEIPTS)
    sizes=reader.execute("SELECT octet_length(binding) FROM theheat_batch_results.receipts WHERE job_id=%s",(job_id,)).fetchall()
    require(all(2<=v[0]<=4096 for v in sizes))
    reader.charge(sum(v[0] for v in sizes))
    rows=reader.execute("SELECT receipt_id,grant_id,metadata_sha256,results_sha256,binding,binding_sha256,recorded_at FROM theheat_batch_results.receipts WHERE job_id=%s ORDER BY receipt_id",(job_id,)).fetchall()
    retained={}
    complete_hashes=set()
    for receipt_id,grant_id,meta_sha,raw_sha,encoded,binding_sha,recorded in rows:
        binding=p._decode(encoded)
        r._binding(binding)
        require(p._canonical(binding)==encoded and p._sha(encoded)==binding_sha and fingerprint(binding)==receipt_id
                and binding==dict(job_id=job_id,grant_id=grant_id,metadata_sha256=meta_sha,results_sha256=raw_sha,complete=binding["complete"])
                and grant_id==grant)
        time_order(at,recorded)
        retained[receipt_id]=(binding,recorded)
        if binding["complete"]:
            complete_hashes.add(raw_sha)
    chosen=reader.execute("SELECT receipt_id,semantic_sha256 FROM theheat_batch_results.choices WHERE job_id=%s",(job_id,)).fetchone()
    if chosen is None:
        return refs,None,"response_missing"
    require(chosen[0] in retained)
    s._sha(chosen[1])
    if len(complete_hashes)>1:
        return refs,None,"ambiguous_response"
    binding,observed_at=retained[chosen[0]]
    if not binding["complete"]:
        return refs,None,"response_incomplete"
    adoption=reader.execute("SELECT receipt_sha256,provider_id,recorded_at FROM theheat_batch_work.adoptions WHERE job_id=%s",(job_id,)).fetchone()
    ack_count=reader.execute("SELECT count(*) FROM theheat_batch_work.acks WHERE job_id=%s",(job_id,)).fetchone()[0]
    require(ack_count<=w.MAX_RECEIPTS)
    acks=reader.execute("SELECT receipt_sha256,provider_id,recorded_at FROM theheat_batch_work.acks WHERE job_id=%s",(job_id,)).fetchall()
    ids={a[1] for a in acks if a[1] is not None}
    if adoption is None or len(ids)!=1 or adoption[1] not in ids:
        return refs,None,"ambiguous_response"
    require(any(a[0]==adoption[0] and a[1]==adoption[1] and a[2]<=adoption[2] for a in acks))
    if reader.execute("SELECT count(DISTINCT job_id) FROM theheat_batch_work.acks WHERE provider_id=%s",(adoption[1],)).fetchone()[0]!=1:
        return refs,None,"ambiguous_response"
    ack=reader.artifact(worker.SCHEMA,"ack_artifacts",adoption[0],w.MAX_ACK_BYTES)
    require(w._ack_id(ack,plan["samples"])==adoption[1])
    time_order(at,adoption[2])
    metadata=reader.artifact(results.SCHEMA,"metadata_artifacts",binding["metadata_sha256"],w.MAX_ACK_BYTES)
    raw=reader.artifact(results.SCHEMA,"result_artifacts",binding["results_sha256"],r.MAX_RESULT_BYTES)
    if important:
        meta = usage.decode(metadata)
        require(w._ack_id(metadata, 2) == adoption[1] and meta["processing_status"] == "ended"
                and meta["request_counts"]["processing"] == 0)
        lines = raw.splitlines()
        require(len(lines) <= 2)
        items = {}
        expected = {s["custom_id"] for s in job["slots"]}
        for line in lines:
            item = usage.decode(line)
            shape(item, {"custom_id", "result"})
            require(type(item["custom_id"]) is str and item["custom_id"] in expected and item["custom_id"] not in items)
            items[item["custom_id"]] = item
        require(fingerprint(items) == chosen[1])
    refs.update(raw_sha256=binding["results_sha256"],receipt_id=chosen[0])
    member = dict(batch_custom_ids=[s["custom_id"] for s in job["slots"]]) if important else dict(batch_custom_id=job["custom_id"])
    return refs,dict(raw=raw,observed_at=observed_at,complete=True,**member,batch_metadata=metadata,batch_provider_id=adoption[1]),None


def _attribution(reader, record):
    intent=record["intent"]
    has_checks=reader.execute("SELECT to_regclass('theheat_checks.attempts')").fetchone()[0] is not None
    check_rows=[]
    if has_checks:
        reader.validate("checks",observations.validate)
        check_rows=reader.execute("SELECT check_set_id,stage,grant_id,binding_sha256,request_sha256,recorded_at FROM theheat_checks.attempts WHERE intent_id=%s LIMIT 2",(intent["intent_id"],)).fetchall()
    has_batches=reader.execute("SELECT to_regclass('theheat_batches.registrations')").fetchone()[0] is not None
    batches=reader.execute("SELECT job_id FROM theheat_batches.registrations WHERE intent_id=%s LIMIT 2",(intent["intent_id"],)).fetchall() if has_batches else []
    has_sync=reader.execute("SELECT 1 FROM theheat_projection.versions WHERE namespace=%s AND snapshot_id=%s",(sync.JOB,intent["job_id"])).fetchone() is not None
    require(len(check_rows)+len(batches)+int(has_sync)<=1 or len(check_rows)==1 and has_sync and not batches)
    # A check shares its parent's job ID. The exact attempt/intent join wins;
    # a writer match additionally requires its retained intent ID below.
    if check_rows:
        return _check(reader,record,check_rows[0])
    if batches:
        return _batch(reader,record,batches[0])
    if has_sync:
        _,candidate=reader.projection(sync.JOB,intent["job_id"])
        if candidate.get("intent_id")!=intent["intent_id"]:
            return origin(),None,"unsupported_origin"
        retained=_sync(reader,intent["job_id"],record)
        refs=origin("sourced_synchronous_writer",brief_id=retained["job"]["brief_id"],generation_id=intent["job_id"],request_sha256=intent["request_sha256"],source_run_id=_source_run(reader,retained["brief"]))
        granted,observed=retained["attempt"],retained["observation"]
        if granted is None:
            return refs,None,"not_dispatched"
        refs["grant_id"]=granted["grant_id"]
        if observed is None:
            return refs,None,"response_missing"
        refs["raw_sha256"]=observed["raw_sha256"]
        return refs,dict(raw=retained["raw"],observed_at=observed["observed_at"],complete=observed["complete"],terminal_usage=retained.get("terminal_usage")),None
    return origin(),None,"unsupported_origin"


def _row(record):
    intent=record["intent"]
    return dict(intent_id=intent["intent_id"],job_id=intent["job_id"],role=intent["role"],provider=intent["provider"],requested_model=intent["model"],
        reservation_state=record["state"],reserved_at=record["reserved_at"],last_at=record["last_at"],reserve_micro_usd=str(intent["reserve_micro_usd"]),
        held_micro_usd=str(intent["reserve_micro_usd"] if record["state"] in HELD else 0),
        recorded_settlement_micro_usd=None if record["settled_micro_usd"] is None else str(record["settled_micro_usd"]),
        charge_status="recorded_settlement" if record["state"]=="settled" else "unreconciled",origin=origin(),usage=None)


def _detached_usage(value, row):
    # Canonical display only; leave original retained observation bytes intact.
    value = dict(value, observed_at=spend._time(value["observed_at"]))
    if "batch_custom_ids" in value:
        try:
            metadata = usage.decode(value["batch_metadata"])
            require(type(metadata) is dict and metadata.get("id") == value["batch_provider_id"])
            return usage.important_batch(value["raw"], value["batch_custom_ids"], stage=row["role"],
                model=row["requested_model"], observed_at=value["observed_at"])
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            return usage.empty(row["provider"], "invalid_envelope", status="invalid", observed_at=value["observed_at"], complete=True)
    if "batch_custom_id" in value:
        try:
            metadata=usage.decode(value.pop("batch_metadata"))
            require(type(metadata) is dict and metadata.get("id")==value.pop("batch_provider_id"))
            lines=[usage.decode(line) for line in value["raw"].splitlines() if line.strip()]
            require(len(lines)==1 and type(lines[0]) is dict and set(lines[0])=={"custom_id","result"}
                    and lines[0]["custom_id"]==value.pop("batch_custom_id") and type(lines[0]["result"]) is dict)
            result=lines[0]["result"]
            message=result.get("message")
            # A provider error may itself carry usage. No editorial content is
            # parsed; absent usage remains absent, not a fabricated charge.
            value["raw"]=p._canonical(message if type(message) is dict else result)
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
            return usage.empty(row["provider"],"invalid_envelope",status="invalid",observed_at=value["observed_at"],complete=True)
    return usage.extract(**value,provider=row["provider"],stage=row["role"],model=row["requested_model"])


def project(authority, *, now):
    """No supplied HTTP selectors; failure is isolated from the draft view."""
    deadline=time.monotonic()+SECONDS
    try:
        from src.commands import hosted_fixture
        if not hosted_fixture.allowed(authority):
            return unavailable("local_only")
        with authority.projections._connection() as connection:
            reader=Read(connection,deadline,authority.environment)
            authority._validate(reader)
            hosted_fixture.profile(reader, authority.environment)
            version,_,_=authority._pointer(reader,lock=True)
            stamp=spend._time(utc_text(now))
            status=spend.apply(reader,"status",{},now=stamp,environment=authority.environment)
            latest="""FROM theheat_spending.intents i LEFT JOIN LATERAL
                (SELECT kind FROM theheat_spending.events WHERE intent_id=i.intent_id ORDER BY sequence DESC LIMIT 1) e ON true"""
            counts=dict.fromkeys(STATES,0)
            for state,count in reader.execute("SELECT coalesce(e.kind,'reserved'),count(*) "+latest+" GROUP BY coalesce(e.kind,'reserved')").fetchall():
                require(state in counts and type(count) is int and 0<=count<=s.MAX_INTENTS)
                counts[state]=count
            require(sum(counts.values())==status["intent_count"])
            ids=reader.execute("SELECT i.intent_id "+latest+" ORDER BY CASE WHEN coalesce(e.kind,'reserved') IN ('reserved','dispatched','uncertain') THEN 0 ELSE 1 END,i.recorded_at DESC,i.intent_id LIMIT %s",(MAX_DETAILS,)).fetchall()
            records=[spend._record(reader,i[0]) for i in ids]
            require(all(record is not None for record in records))
            rows=[]
            detached=[]
            for record in records:
                row=_row(record)
                try:
                    refs,evidence,reason=_attribution(reader,record)
                except Limited:
                    refs,evidence,reason=origin(),None,"projection_limited"
                row["origin"]=refs
                if evidence is None:
                    row["usage"]=usage.empty(row["provider"],reason)
                else:
                    detached.append((row,evidence))
                rows.append(row)
            totals=status["totals"]
            result=dict(schema_version=1,status="available",reason=None,scope="local_shared_authority" if authority.environment == "local" else "hosted_staging_fixture",actual_bill_available=False,
                accounting_complete=False,production_enforcement=False,snapshot=dict(state_version=version,observed_at=stamp),
                integrity_scope=dict(summary="existing_catalog_constraints_aggregate",details="selected_rows_hash_and_join_checked"),
                summary=dict(configured_limits_micro_usd={key:str(status["limits"][field]) for key,field in (("daily","daily_micro_usd"),("monthly","monthly_micro_usd"),("per_job","per_job_micro_usd"))},
                    commitments_micro_usd={key:str(totals[key+"_micro_usd"]) for key in ("daily","monthly","held")},overrun_count=totals["overrun_count"],reservation_counts=counts),
                requests=rows,details_truncated=status["intent_count"]>len(rows),total_intents=status["intent_count"],shown_intents=len(rows),omitted_intents=status["intent_count"]-len(rows))
            reader.check()
        for row,evidence in detached:
            row["usage"]=_detached_usage(evidence,row)
        if time.monotonic()>=deadline:
            raise Deadline
        if len(p._canonical(result))>MAX_OUTPUT:
            return unavailable("projection_limited")
        return result
    except Deadline:
        return unavailable("projection_timeout")
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError) as exc:
        reason="not_configured" if str(exc) in {"spend_migration_required","spend_limits_not_configured"} else "journal_unavailable"
        return unavailable(reason,status="unconfigured" if reason=="not_configured" else "unavailable")
