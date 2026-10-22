"""Credentialless invented fixture; separate process preserves replay isolation."""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from datetime import UTC,datetime

import httpx
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.postgres_sourced_generation import private_configuration
from src.commands.preview_ingress import Operators,safe_environment
from src.commands.schema import canonical_json,utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.storage.ghcn_runtime_inputs import Baseline
from src.two_bot.ghcn_claim_view import prepare_execution
from src.two_bot import check_requests
from src.two_bot.check_origin import spending_job
from tests.test_postgres_synchronous_generation import transport
from tests import test_check_executor as checks
from tests.test_postgres_editor_media import fact_pass

from src.voice import safety
safety.GEMINI_API_KEY="invented-offline-key"
cfg=json.loads(Path(sys.argv[1]).read_text())
if cfg.get("t4_timing_diagnostics"):
    from tests import t4_timing_helpers as t4_timing
    t4_started = t4_timing.sample()
from tests.workflow_clock import start_child_clock
fixture_clock=start_child_clock(cfg["test_clock"])
safe_environment()
authority=PostgresCommandAuthority(**cfg["authority"])
b=cfg["baseline"]
authority.configure_ghcn_source_results(Baseline(Path(b["database"]),Path(b["manifest"]),b["database_sha256"],b["manifest_sha256"]))
if Path(cfg["generation"]).exists():
    authority.configure_sourced_generation(private_configuration(cfg["generation"]))
if cfg.get("native"):
    # Local editor media for compact-claim journeys; the native child is unchanged.
    authority.configure_editor_media(**cfg["native"])
if cfg.get("delivery"):
    authority.configure_delivery(cfg["delivery"])
operators=Operators(cfg["operators"])
assert fingerprint(current_editorial_policy())==cfg["policy_sha256"]
original=socket.socket.connect
def connect(sock,address):
    if sock.family!=socket.AF_UNIX:
        raise AssertionError("All network refused by invented worker")
    return original(sock,address)
socket.socket.connect=connect
operation,identity=sys.argv[2:4]
fault=sys.argv[4] if len(sys.argv)>4 else ""
if fault in {"preflight_replace","lock_replace","lock_sidecar"}:
    from src.two_bot import ghcn_claim_view
    import time
    if fault=="preflight_replace":
        rebuild=ghcn_claim_view._reconstruct
        def replaced_before_read(*args,**kwargs):
            path=Path(b["database"])
            replacement=path.with_suffix(".same-bytes")
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
            return rebuild(*args,**kwargs)
        ghcn_claim_view._reconstruct=replaced_before_read
    else:
        prepare=ghcn_claim_view.prepare_execution
        def pause_after_preflight(*args,**kwargs):
            result=prepare(*args,**kwargs)
            config_path=Path(sys.argv[1])
            config_path.with_suffix(".ready").write_text("ready")
            end=time.monotonic()+60
            while not config_path.with_suffix(".release").exists():
                assert time.monotonic()<end,"Local lock fixture timed out"
                time.sleep(.02)
            original_state=authority._state
            def state_with_signal(connection,*,lock=False):
                if lock:
                    config_path.with_suffix(".locking").write_text("locking")
                return original_state(connection,lock=lock)
            authority._state=state_with_signal
            return result
        ghcn_claim_view.prepare_execution=pause_after_preflight
if fault=="forged_interpreter":
    # Explicit negative fixture: retain a dishonest terminal alongside an
    # original rejecting raw response. The fresh admission worker is untouched.
    original_interpret=check_requests.interpret_observation
    def forged(*args,**kwargs):
        outcome=original_interpret(*args,**kwargs)
        if args[1]=="safety":
            assert outcome["verdict"]=="reject"
            outcome=dict(outcome,verdict="pass",result={"passed":True})
        return outcome
    check_requests.interpret_observation=forged
if fault in {"final_clock", "final_check_clock"}:
    from src.commands import postgres_candidate_admission as admission,postgres_authority as authority_module
    from src.commands.schema import utc_datetime
    from datetime import timedelta
    verify=admission.verified_completion
    def delayed(*args,**kwargs):
        result=verify(*args,**kwargs)
        with authority.projections._connection() as c:
            current_command=authority._intent(c,identity)[0]
            if fault == "final_check_clock":
                value=admission.read_input(c,current_command.payload)
                original=admission.request_for(authority,c,value)
                assert original is not None
                expires=original[0].expires_at
                assert utc_datetime(expires)<utc_datetime(current_command.expires_at)
            else:
                expires=current_command.expires_at
        authority_module._clock=lambda ignored=None:utc_datetime(expires)+timedelta(seconds=1)
        return result
    admission.verified_completion=delayed
if fault in {"final_checker_revoked", "final_checker_session"}:
    from src.commands import postgres_candidate_admission as admission
    from src.commands.schema import Principal
    verify=admission.verified_completion
    changed_session=[False]
    original_resolve=operators.resolve
    def resolving(subject):
        actor=original_resolve(subject)
        if changed_session[0] and actor is not None and subject=="local-publisher":
            return Principal(actor.subject,actor.role,"invented-changed-checker-session")
        return actor
    operators.resolve=resolving
    def checker_changed(*args,**kwargs):
        result=verify(*args,**kwargs)
        if fault=="final_checker_revoked":
            path=Path(cfg["operators"])
            rows=json.loads(path.read_text())
            rows["operators"]=[row for row in rows["operators"] if row["username"]!="publisher"]
            path.write_text(json.dumps(rows))
        else:
            changed_session[0]=True
        return result
    admission.verified_completion=checker_changed
if fault=="final_footprint":
    from src.commands import postgres_candidate_admission as admission
    verify=admission.verified_completion
    def replaced(*args,**kwargs):
        result=verify(*args,**kwargs)
        path=Path(b["database"])
        temporary=path.with_suffix(".replacement")
        temporary.write_bytes(path.read_bytes())
        temporary.replace(path)
        return result
    admission.verified_completion=replaced
if fault=="native_failure":
    # Explicit negative fixture: the fixed native child cannot start.
    from src.commands import preview_media_worker
    def failed_native(*args,**kwargs):
        raise OSError("invented native renderer failure")
    preview_media_worker.run_native=failed_native
if fault=="passive_traps":
    from src.two_bot import ghcn_claim_view
    from src.commands import postgres_checks,postgres_candidate_admission,postgres_synchronous_generation
    def forbidden(*args,**kwargs):
        raise AssertionError("Executable/scientific work in passive projection")
    for module,names in ((ghcn_claim_view,("prepare_execution","_reconstruct","baseline_footprint")),
        (postgres_checks,("_current",)),(postgres_candidate_admission,("verified_completion","checked_text")),
        (postgres_synchronous_generation,("current_candidate",))):
        for name in names:
            setattr(module,name,forbidden)
    Baseline.reader=forbidden

def clock():
    return utc_text(datetime.now(UTC))
def log(row):
    with Path(cfg["trace"]).open("a") as stream:
        stream.write(json.dumps(row,sort_keys=True)+"\n")
from src.two_bot import writer,fact_check,critic,ghcn_claim_view
from src.two_bot import check_executor
if cfg.get("t4_timing_diagnostics"):
    import atexit
    t4_timing.emit(cfg["trace"], operation, "child_startup", t4_started, t4_timing.sample())
    atexit.register(lambda: t4_timing.emit(cfg["trace"], operation, "child_lifetime", t4_started, t4_timing.sample()))
    for name in ("prepare_execution", "resolve", "_reconstruct", "_read_source", "_checkpoint"):
        t4_timing.instrument(ghcn_claim_view, name, cfg["trace"], operation, "source:" + name)
    prepare_execution = ghcn_claim_view.prepare_execution
    t4_timing.instrument(check_requests, "prepare_request", cfg["trace"], operation, "request_preparation")
    for name in ("execute_candidate_check_once", "execute_revision_check_once", "execute_sourced_generation_once", "consume"):
        t4_timing.instrument(authority, name, cfg["trace"], operation, "authority:" + name)
    t4_timing.instrument(check_executor.GoogleCheckTransport, "execute", cfg["trace"], operation, "provider")
    if operation == "consume":
        from src.commands import preview_media_worker
        for name in ("run_native", "consume_media_once"):
            t4_timing.instrument(preview_media_worker, name, cfg["trace"], operation, "native:" + name)
from src.commands.schema import utc_datetime
original_window_available=check_executor._window_available
def traced_window_available(packet,lease,now):
    available=(t4_timing.timed(cfg["trace"], operation, "preflight", original_window_available, packet, lease, now)
        if cfg.get("t4_timing_diagnostics") else original_window_available(packet,lease,now))
    log(dict(kind="check_window",operation=operation,fault=fault,now=now,
        lease_expires_at=lease["expires_at"],useful_until=packet["useful_until"],
        lease_remaining_seconds=(utc_datetime(lease["expires_at"])-utc_datetime(now)).total_seconds(),
        available=available))
    return available
check_executor._window_available=traced_window_available
for module,name,index,label in ((writer,"build_writer_user_prompt",0,"writer_view"),(fact_check,"prepare_request",1,"fact_view"),
    (critic,"prepare_request",1,"critic_view"),(fact_check,"local_rejection",2,"local_fact_full")):
    original_function=getattr(module,name)
    def traced(*args,_original=original_function,_index=index,_label=label,**kwargs):
        bundle=args[_index] if len(args)>_index else kwargs["bundle"]
        encoded=ghcn_claim_view.json_tree(bundle.to_dict())
        log(dict(kind="evidence_argument",stage=_label,sha256=fingerprint(encoded),
            byte_count=len(canonical_json(encoded).encode()),compact="ghcn_claim_view" in bundle.raw_signal_dump))
        return _original(*args,**kwargs)
    setattr(module,name,traced)
if operation=="checkpoint_probe":
    import psycopg
    from src.storage import postgres_projection
    from src.storage.scientific_supply import NAMESPACE
    from tests.test_postgres_editor_media import all_application_rows
    owner=cfg["probe_owner"]
    baseline=authority.ghcn_baseline
    original_bytes=baseline.database.read_bytes(),baseline.manifest.read_bytes()
    original_rows=all_application_rows(owner)
    reads=[]
    read_input=ghcn_claim_view.domain.read_input
    def traced_read(*args,**kwargs):
        reads.append(args[1])
        return read_input(*args,**kwargs)
    ghcn_claim_view.domain.read_input=traced_read
    prepared=prepare_execution(authority,cfg["run_id"],cfg["selection"])
    assert len(reads)==1
    for _ in range(2):
        with authority.projections._connection() as c:
            authority._validate(c)
            version,state=authority._state(c,lock=True)
            assert prepared.current(authority,c,state,version) is prepared.claim
    assert len(reads)==3 and len({id(c) for c in reads})==3
    evidence=prepared.claim.full.raw_signal_dump["evidence"]["baseline"]["variables"]
    assert all(len(value["calendar_samples"])==366 for value in evidence.values())
    assert all(value["source_missing_count"]==value["source_qc_rejected_count"]==1 for value in evidence.values())
    assert all_application_rows(owner)==original_rows
    assert (baseline.database.read_bytes(),baseline.manifest.read_bytes())==original_bytes
    # Explicit owner-corruption fixture. The same prepared context must reread
    # the source on a later transaction, not trust its earlier validated copy.
    with psycopg.connect(**owner) as c:
        c.execute("SET session_replication_role=replica")
        c.execute("UPDATE theheat_projection.versions SET canonical_sha=%s WHERE namespace=%s AND snapshot_id=%s",
                  ("f"*64,NAMESPACE,"run:"+cfg["run_id"]))
        c.execute("SET session_replication_role=origin")
    with authority.projections._connection() as c:
        authority._validate(c)
        version,state=authority._state(c,lock=True)
        try:
            prepared.current(authority,c,state,version)
        except postgres_projection.ProjectionError as error:
            assert str(error)=="corrupt_projection_identity"
        else:
            raise AssertionError("Changed source was reused from a previous transaction")
    assert len(reads)==4
    result=dict(reads=4,distinct_validated_connections=3,full_source_preserved=True,
        later_source_tamper_refused="corrupt_projection_identity")
elif operation in {"delivery_run", "delivery_refusals", "delivery_high_control"}:
    from tests import test_postgres_temperature_delivery as t4
    from src.commands import postgres_delivery as delivery
    if operation == "delivery_run":
        parameters = json.loads(fault)
        if cfg.get("t4_timing_diagnostics"):
            t4_timing.instrument(delivery, "attempt_successor", cfg["trace"], operation, "delivery:attempt_successor")
            t4_timing.instrument(delivery._OwnAttemptContext, "current", cfg["trace"], operation, "delivery:own_context")
        result = t4.child_delivery_run(authority, operators, cfg, identity, parameters)
        log(dict(kind="delivery_stage", platform=parameters["platform"], stage=parameters["stage"], result=result))
    elif operation == "delivery_refusals":
        case = dict(authority=authority, operators=operators, params=cfg["t4_owner"],
                    config=cfg, draft_id=cfg["delivery_draft_id"])
        boundaries = tuple(json.loads(fault))
        saved = None
        if boundaries == ("before_call",):
            with authority.projections._connection() as connection:
                saved = delivery.attempt(connection, delivery.read(connection, identity), "x", "upload")
        result = t4.source_refusal_matrix(dict(case=case, intent=identity, trace=[]), boundaries=boundaries, saved=saved)
    else:
        from dataclasses import replace
        from copy import deepcopy
        from src.storage.cyclone_supply import CycloneSupplyError
        proof = delivery.prepare_context(authority, draft_id=cfg["delivery_draft_id"])
        with authority.projections._connection() as connection:
            version, state = authority._state(connection, lock=True)
            assert proof.current(authority, connection, state, version) is proof.claim
            reference = deepcopy(proof.claim.reference)
            reference["selection"]["signal_field"] = "all_time_low"
            altered = replace(proof, claim=replace(proof.claim, reference=reference))
            try:
                altered.current(authority, connection, state, version)
            except (t4.CommandError, CycloneSupplyError):
                pass
            else:
                raise AssertionError("Opposite field substituted for selected high claim")
        # Use the ordinary complete local comparator evidence without rendering.
        from src.commands import postgres_editor_media as editor_media
        with authority.projections._connection() as connection:
            _, state = authority._state(connection)
            draft = next(row for row in state["drafts"] if row.get("id") == cfg["delivery_draft_id"])
            inputs = editor_media.inputs(authority, connection, draft, current_editorial_policy(), datetime.now(UTC), claim=proof.claim)
        spec = inputs["spec"]
        evidence = spec["evidence"]
        assert spec["template"] == "temperature_comparator"
        assert evidence["variable"] == "daily_maximum_temperature"
        assert evidence["points"][0]["value"] > evidence["baseline"]["point"]["value"]
        assert evidence["baseline"]["point"]["value"] == proof.claim.full.historical_context["prior_record_c"]
        result = dict(selection=proof.claim.reference["selection"], field_swap_refused=True,
            full_story_preserved=proof.claim.full_sha256 == proof.claim.reference["full_story"]["sha256"],
            comparator="all_time", direction="high")
elif operation=="enroll":
    if fault=="lower_priority":
        cfg["selection"]=dict(cfg["selection"],signal_field="monthly_high")
    result=authority.retain_ghcn_generation_input(cfg["run_id"],cfg["selection"],clock=clock)
elif operation=="consume":
    from src.commands.schema import CommandError
    try:
        result=authority.consume(operators.resolve,command_id=identity)
    except CommandError as exc:
        if exc.code!="native_preparation_required":
            raise
        from src.commands.preview_media_worker import consume_media_once
        result=consume_media_once(authority,operators.resolve,command_id=identity)
elif operation in {"deterministic","safety","fact_check","critic"} and "revision_checks" in authority.result(identity):
    # A saved draft revision's required check. The invented reservation only needs
    # the request bytes; the authority's runner resolves and fences its own context.
    check_set_id=authority.result(identity)["revision_checks"]["check_set_id"]
    packet=authority.check_execution("read",dict(check_set_id=check_set_id),now=clock())["packet"]
    reference=ghcn_claim_view.structural_view(packet["bundle"])
    claim=ghcn_claim_view.resolve(authority,reference["source_run_id"],reference["selection"])
    request=canonical_json(check_requests.prepare_request(packet,operation,resolved=claim)).encode()
    reservation=None if operation=="deterministic" else dict(intent_id="ghcn-media-"+packet["enrollment_id"][:12]+"-"+operation,
        job_id=spending_job(packet),request_sha256=hashlib.sha256(request).hexdigest(),provider="google",role=operation,
        model=packet["policy"]["models"][operation],estimate_sha256="e"*64,reserve_micro_usd=5)
    sent=[]
    def response(request):
        sent.append(request)
        if fault=="postgrant_baseline":
            path=Path(b["manifest"])
            path.write_bytes(path.read_bytes()+b"\n")
        raw=checks.envelope({"safety":"NO","fact_check":fact_pass(packet["final_text"]),"critic":checks.CRITIC_PASS}.get(operation,"NO"))
        return httpx.Response(200,stream=httpx.ByteStream(raw),request=request)
    result=authority.execute_revision_check_once(identity,operators.resolve,clock=clock,reservation=reservation,enabled=True,
        transport_options={"api_key":"invented-offline-key","http_transport":httpx.MockTransport(response)})
    for body in sent:
        log(dict(kind="model_post",stage="revision_"+operation,bytes=len(body.content),sha256=hashlib.sha256(body.content).hexdigest(),
            full_tables=b"calendar_samples" in body.content))
    log(dict(kind="revision_stage",stage=operation,packet_sha256=fingerprint(packet),packet_bundle_sha256=fingerprint(packet["bundle"]),
        view_sha256=claim.view_sha256,full_sha256=claim.full_sha256,request_bytes=len(request),
        request_full_tables=b"calendar_samples" in request,result=result))
elif operation=="projection":
    result=authority.candidate_projection(authority.generated_candidate_inputs(),now=datetime.now(UTC),resolve_principal=operators.resolve)
elif operation in {"write","capture","interpret"}:
    sent,factory=transport(dict(text=cfg["text"]))
    result=authority.execute_sourced_generation_once(identity,operators.resolve,clock=clock,operation=operation,enabled=True,transport_factory=factory)
    for body in sent:
        log(dict(kind="model_post",stage="writer",bytes=len(body),sha256=hashlib.sha256(body).hexdigest()))
else:
    check_set_id=authority.result(identity)["candidate"]["check_set_id"]
    packet=authority.check_execution("read",dict(check_set_id=check_set_id),now=clock())["packet"]
    prepared=prepare_execution(authority,cfg["run_id"],cfg["selection"])
    request=canonical_json(check_requests.prepare_request(packet,operation,resolved=prepared.claim)).encode()
    reservation=None if operation=="deterministic" else dict(intent_id="ghcn-fixture-"+check_set_id[:12]+"-"+operation,job_id=spending_job(packet),
        request_sha256=hashlib.sha256(request).hexdigest(),provider="google",role=operation,model=packet["policy"]["models"][operation],
        estimate_sha256="e"*64,reserve_micro_usd=5)
    sent=[]
    def response(request):
        sent.append(request)
        if fault=="postgrant_baseline":
            path=Path(b["manifest"])
            path.write_bytes(path.read_bytes()+b"\n")
        raw=checks.envelope({"safety":"YES" if fault=="forged_interpreter" else "NO","fact_check":fact_pass(cfg["text"]),"critic":checks.CRITIC_PASS}.get(operation,"NO"))
        return httpx.Response(200,stream=httpx.ByteStream(raw),request=request)
    result=authority.execute_candidate_check_once(identity,operators.resolve,clock=clock,reservation=reservation,enabled=True,
        transport_options=None if fault=="no_capability" else {"api_key":"invented-offline-key","http_transport":httpx.MockTransport(response)})
    for body in sent:
        log(dict(kind="model_post",stage=operation,bytes=len(body.content),sha256=hashlib.sha256(body.content).hexdigest()))
    log(dict(kind="stage",stage=operation,packet_sha256=fingerprint(packet),view_sha256=prepared.claim.view_sha256,
        full_sha256=prepared.claim.full_sha256,counters=prepared.claim.counters,request_sha256=hashlib.sha256(request).hexdigest(),result=result))
print(json.dumps(result))
