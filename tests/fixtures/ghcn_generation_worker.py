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
safe_environment()
authority=PostgresCommandAuthority(**cfg["authority"])
b=cfg["baseline"]
authority.configure_ghcn_source_results(Baseline(Path(b["database"]),Path(b["manifest"]),b["database_sha256"],b["manifest_sha256"]))
if Path(cfg["generation"]).exists():
    authority.configure_sourced_generation(private_configuration(cfg["generation"]))
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
if operation=="enroll":
    if fault=="lower_priority":
        cfg["selection"]=dict(cfg["selection"],signal_field="monthly_high")
    result=authority.retain_ghcn_generation_input(cfg["run_id"],cfg["selection"],clock=clock)
elif operation=="consume":
    result=authority.consume(operators.resolve,command_id=identity)
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
    reservation=None if operation=="deterministic" else dict(intent_id="ghcn-fixture-"+operation,job_id=spending_job(packet),
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
