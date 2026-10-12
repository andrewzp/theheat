"""Real source HTTP/PG, isolated replay and one invented SDK/check/draft journey."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from src.commands.schema import utc_text
from src.commands.postgres_sourced_generation import private_configuration
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.voice import safety
from tests import test_postgres_ghcn_source_results as source
from tests.test_ghcn_runtime_inputs import source_bytes as source_bytes
from tests.test_ghcn_source_result_producer import dual_source
from tests.test_postgres_command_authority import options
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_preview_command_ingress import clean_environment, http
from tests.test_postgres_sourced_generation import allowance_document
from tests.test_spend_journal import LIMITS

ROOT=Path(__file__).resolve().parents[1]
CHILD=ROOT/"tests/fixtures/ghcn_generation_worker.py"


@pytest.fixture
def ghcn_case(database,source_bytes,tmp_path,monkeypatch):
    monkeypatch.setattr(safety,"GEMINI_API_KEY","invented-offline-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED","1")
    original_draft=source.draft
    # The preexisting invented history belongs to a different station. The
    # selected member retains both complete variables, all missing/QC cells.
    monkeypatch.setattr(source,"draft",lambda **kw:original_draft(**dict(kw,sid="USW00000008")))
    generator=source.configured.__wrapped__(database,dual_source(source_bytes),tmp_path,monkeypatch)
    case=next(generator)
    case["environment"]={**clean_environment(),"THEHEAT_CRITIC_ENABLED":"1","PYTHONDONTWRITEBYTECODE":"1"}
    def consume_source(identity):
        child=subprocess.run([sys.executable,"-c",'from src.voice import safety; safety.GEMINI_API_KEY="invented-offline-key"; from src.commands.preview_worker import main; raise SystemExit(main())',*case["args"],"--command-id",identity],
            env=case["environment"],capture_output=True,text=True,timeout=60)
        assert child.returncode==0,child.stdout+child.stderr
        return json.loads(child.stdout)["result"]
    case["consume"]=consume_source
    run=source.retained(case)
    result=consume_source(source.enroll(case,run))
    assert result["status"]=="applied",result
    case["source_result"]=result
    now=datetime.now(UTC)
    owner=case["owner"]
    for method in ("initialize_spending","initialize_batches","initialize_batch_workers","initialize_batch_results","initialize_candidate_checks","initialize_check_executions"):
        getattr(owner,method)()
    owner.initialize_synchronous_checks(now=now)
    case["authority"].spending("configure",LIMITS,now=utc_text(now))
    config=dict(authority=options(case["params"]),baseline={k:str(v) for k,v in vars(case["source"]["baseline"]).items()},
        operators=str(tmp_path/"operators.json"),generation=str(tmp_path/"generation.json"),run_id=run,
        selection=dict(station_id="USW00000000",signal_date=str(case["source"]["day"]),signal_field="all_time_high"),
        text="INVENTED STATION 0 reached 45.5°C, its highest reading in the 24-year station archive.",
        policy_sha256=fingerprint(current_editorial_policy()),trace=str(tmp_path/"trace.jsonl"))
    config_path=tmp_path/"worker.json"
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    case.update(config=config,config_path=config_path)
    refs=worker(case,"enroll")
    reserve=case["authority"].retain_generation_reservation(allowance_document(refs["brief_id"],now=now,schema_version=2,
        execution_mode="synchronous",samples=1,max_attempts=1,read_budget_seconds=180))
    path=Path(config["generation"])
    path.write_text(json.dumps(dict(schema_version=2,current_inputs=[refs["brief_id"]],reservations=dict(batch=None,synchronous=reserve))))
    path.chmod(0o600)
    case["authority"].configure_sourced_generation(private_configuration(path))
    case["refs"]=refs
    yield case
    try:
        next(generator)
    except StopIteration:
        pass


def worker(case,operation,identity="",fault=""):
    child=subprocess.run([sys.executable,str(CHILD),str(case["config_path"]),operation,identity,fault],cwd=ROOT,
        env=case["environment"],capture_output=True,text=True,timeout=120)
    assert child.returncode==0,child.stdout+child.stderr
    return json.loads(child.stdout.splitlines()[-1])


def command(case,action,refs):
    now=datetime.now(UTC)
    return dict(command_id=str(uuid4()),action=action,requested_at=utc_text(now),expires_at=utc_text(now+timedelta(hours=1)),targets=[],payload=refs)


def submit(case,body,role="editor",fault=""):
    status,result,_=http(case["port"],"/commands",method="POST",value=body,role=role)
    assert status==202,result
    return worker(case,"consume",body["command_id"],fault)


def test_actual_source_http_one_writer_four_checks_pending_draft(ghcn_case,record_property,cluster,tmp_path):
    case=ghcn_case
    before=case["authority"].read()
    assert worker(case,"enroll")==case["refs"]
    lower=subprocess.run([sys.executable,str(CHILD),str(case["config_path"]),"enroll","","lower_priority"],cwd=ROOT,
        env=case["environment"],capture_output=True,text=True,timeout=120)
    assert lower.returncode!=0 and "ghcn_selection_not_dispatch_winner" in lower.stderr
    assert case["authority"].read()==before
    status,listing,_=http(case["port"],"/generation")
    assert status==200 and listing["briefs"][0]["status"]=="pending_validation",listing
    brief=listing["briefs"][0]
    body=command(case,"request_sourced_generation",{k:brief[k] for k in ("brief_id","brief_sha256","expected_state_version","expected_policy_sha256")})
    result=submit(case,body)
    assert result["status"]=="applied",result
    assert worker(case,"write",body["command_id"])["outcome"]=="response_retained"
    assert worker(case,"write",body["command_id"])["outcome"]=="reconciliation_required"
    captured=worker(case,"capture",body["command_id"])
    assert captured["outcome"]=="candidate_ready",captured
    check=command(case,"request_candidate_checks",captured["candidate"])
    requested=submit(case,check,role="publisher")
    assert requested["status"]=="unchanged",requested
    for stage in ("deterministic","safety","fact_check","critic"):
        pending=worker(case,"projection",fault="passive_traps")[0]
        assert pending["expected_completion_sha256"] is None and not pending["required_checks_completed"]
        if stage=="safety":
            blocked=worker(case,stage,check["command_id"],"no_capability")
            assert blocked["outcome"]=="blocked" and blocked["reason"]=="local_check_transport_required"
            manifest=case["source"]["baseline"].manifest
            saved_manifest=manifest.read_bytes()
            retained=worker(case,stage,check["command_id"],"postgrant_baseline")
            assert retained["outcome"]=="reconciliation_required",retained
            passive=case["authority"].check_execution("read",dict(check_set_id=requested["candidate"]["check_set_id"]),now=utc_text(datetime.now(UTC)))
            assert passive["attempts"]["safety"]["observation"]["complete"] is True
            assert not passive["attempts"]["safety"].get("terminal")
            manifest.write_bytes(saved_manifest)
        completed=worker(case,stage,check["command_id"])
        assert completed["outcome"]=="completed" and completed["checks"]["stages"][stage]=="passed",completed
    if os.environ.get("P25_I3_EVIDENCE_DIR"):
        directory=Path(os.environ["P25_I3_EVIDENCE_DIR"])
        directory.mkdir(parents=True,exist_ok=True)
        packet=case["authority"].check_execution("read",dict(check_set_id=requested["candidate"]["check_set_id"]),now=utc_text(datetime.now(UTC)))["packet"]
        from src.commands.postgres_sourced_generation import INPUT
        _,brief_value=case["authority"].projections.read(INPUT,case["refs"]["brief_id"])
        (directory/"invented-origin-packets.json").write_text(json.dumps(dict(brief=brief_value,packet=packet)))
    projected=worker(case,"projection",fault="passive_traps")[0]
    assert projected["required_checks_completed"] is False and projected["status"]=="checks_recorded",projected
    refs=dict(captured["candidate"],**{k:projected[k] for k in ("check_set_id","expected_completion_sha256")})
    # Independent original writer and checker actors, and exact operator input
    # allowlist, are checked again by the worker, not blessed by the listing.
    operators=Path(case["config"]["operators"])
    original_operators=operators.read_bytes()
    for subject in ("editor","publisher"):
        attempt=command(case,"admit_checked_candidate",refs)
        status,_,_=http(case["port"],"/commands",method="POST",value=attempt,role="publisher")
        assert status==202
        changed=json.loads(original_operators)
        changed["operators"]=[r for r in changed["operators"] if r["username"]!=subject]
        operators.write_text(json.dumps(changed))
        rejected=worker(case,"consume",attempt["command_id"])
        assert rejected["status"]=="rejected" and rejected["code"]=="forbidden",rejected
        assert case["authority"].read()==before
        operators.write_bytes(original_operators)
    generation=Path(case["config"]["generation"])
    original_generation=generation.read_bytes()
    config=json.loads(original_generation)
    config["current_inputs"]=[]
    removed_after_accept=command(case,"admit_checked_candidate",refs)
    status,_,_=http(case["port"],"/commands",method="POST",value=removed_after_accept)
    assert status==202
    generation.write_text(json.dumps(config))
    status,blocked,_=http(case["port"],"/commands",method="POST",value=command(case,"admit_checked_candidate",refs))
    assert status==409 and blocked["code"]=="candidate_not_allowlisted"
    refused=worker(case,"consume",removed_after_accept["command_id"])
    assert refused["status"]=="rejected" and refused["code"]=="generation_source_superseded",refused
    generation.write_bytes(original_generation)
    for fault,code in (("final_clock","command_expired"),("final_footprint","ghcn_baseline_changed")):
        refused=submit(case,command(case,"admit_checked_candidate",refs),fault=fault)
        assert refused["status"]=="rejected" and refused["code"]==code,refused
        assert case["authority"].read()==before
    admit=command(case,"admit_checked_candidate",refs)
    # The command is durable but not yet consumed when the entire populated
    # application database is restored into a newly initialized owned cluster.
    status,_,_=http(case["port"],"/commands",method="POST",value=admit)
    assert status==202
    admitted=restore_and_admit(case,cluster,tmp_path,admit)
    # The original cluster can independently resolve its same retained command.
    assert worker(case,"consume",admit["command_id"])["candidate"]==admitted["candidate"]
    assert admitted["status"]=="applied",admitted
    original_result=worker(case,"consume",admit["command_id"])
    assert original_result["candidate"]==admitted["candidate"]
    after=case["authority"].read()
    assert after[0]==before[0]+1
    draft=next(d for d in after[1]["drafts"] if d["id"]==admitted["candidate"]["draft_id"])
    assert draft["text"]==case["config"]["text"] and draft["status"]=="pending"
    assert not any(k in draft for k in ("approval_binding","tweet_id","publish_intent_id"))
    assert [d for d in after[1]["drafts"] if d["id"]!=draft["id"]]==before[1]["drafts"]
    trace=[json.loads(line) for line in Path(case["config"]["trace"]).read_text().splitlines()]
    assert [row["stage"] for row in trace if row["kind"]=="model_post"]==["writer","safety","fact_check","critic"]
    views={row["view_sha256"] for row in trace if row["kind"]=="stage"}
    fulls={row["full_sha256"] for row in trace if row["kind"]=="stage"}
    assert len(views)==len(fulls)==1 and views!=fulls
    for label in ("writer_view","fact_view","critic_view","local_fact_full"):
        values=[row for row in trace if row["kind"]=="evidence_argument" and row["stage"]==label]
        assert values,label
        assert {row["sha256"] for row in values}==(fulls if label=="local_fact_full" else views)
        assert all(row["compact"] is (label!="local_fact_full") for row in values)
    record_property("ghcn_generation_trace",json.dumps(trace,sort_keys=True))
    if os.environ.get("P25_I3_EVIDENCE_DIR"):
        Path(os.environ["P25_I3_EVIDENCE_DIR"],"identity-trace.json").write_text(json.dumps(dict(trace=trace,admitted=admitted),sort_keys=True))


def restore_and_admit(case,cluster,tmp_path,admit):
    import psycopg
    import tempfile
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_editor_media import all_application_rows
    params=case["params"]
    before=case["authority"].read()
    rows=all_application_rows(params)
    _,tool,_=cluster
    with tempfile.TemporaryDirectory(prefix="theheat-ghcn-writer-",dir="/tmp") as directory:
        root=Path(directory)
        root.chmod(0o700)
        socket=root/"socket"
        socket.mkdir(mode=0o700)
        data,dump=root/"data",root/"invented.dump"
        tool("pg_dump","-h",params["host"],"-p",str(params["port"]),"-U",params["user"],"-Fc","-f",dump,params["dbname"])
        tool("initdb","-D",data,"-U","projection_owner","--auth-local=trust","--auth-host=reject","--encoding=UTF8","--no-locale")
        try:
            tool("pg_ctl","-D",data,"-l",root/"server.log","-o",f"-c listen_addresses='' -k {socket} -p 55477","-w","start")
            with psycopg.connect(host=str(socket),port=55477,user="projection_owner",dbname="postgres",autocommit=True) as c:
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                c.execute("CREATE DATABASE restored_ghcn_writer TEMPLATE template0")
            tool("pg_restore","-h",socket,"-p","55477","-U","projection_owner","-d","restored_ghcn_writer","--exit-on-error","--single-transaction",dump)
            restored_params=dict(host=str(socket),port=55477,user="projection_owner",dbname="restored_ghcn_writer")
            authority=PostgresCommandAuthority(**options(restored_params))
            assert authority.read()==before and all_application_rows(restored_params)==rows
            config={**case["config"],"authority":options(restored_params)}
            path=tmp_path/"restored-worker.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            restored=dict(case,authority=authority,params=restored_params,config=config,config_path=path)
            result=worker(restored,"consume",admit["command_id"])
            assert result["status"]=="applied",result
            final=all_application_rows(restored_params)
            assert worker(restored,"consume",admit["command_id"])==result
            assert all_application_rows(restored_params)==final
            for name in rows:
                if name[0] not in {"theheat_commands","theheat_projection","theheat_checks"}:
                    assert final[name]==rows[name],name
            with case["authority"].projections._connection() as c:
                source_rows=c.execute("SELECT namespace,snapshot_id,canonical_sha FROM theheat_projection.versions ORDER BY 1,2").fetchall()
            with authority.projections._connection() as c:
                restored_rows=c.execute("SELECT namespace,snapshot_id,canonical_sha FROM theheat_projection.versions ORDER BY 1,2").fetchall()
            assert set(source_rows)<=set(restored_rows)
            return result
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl","-D",data,"-m","fast","-w","stop")


@pytest.mark.parametrize("fault",["preflight_replace","lock_replace","lock_sidecar"])
def test_original_baseline_fence_survives_replay_and_real_lock_wait(ghcn_case,fault,tmp_path):
    import time
    case=ghcn_case
    status,listing,_=http(case["port"],"/generation")
    assert status==200
    brief=listing["briefs"][0]
    body=command(case,"request_sourced_generation",{k:brief[k] for k in ("brief_id","brief_sha256","expected_state_version","expected_policy_sha256")})
    status,_,_=http(case["port"],"/commands",method="POST",value=body)
    assert status==202
    before=case["authority"].read()
    if fault=="preflight_replace":
        result=worker(case,"consume",body["command_id"],fault)
    else:
        ready=case["config_path"].with_suffix(".ready")
        release=case["config_path"].with_suffix(".release")
        locking=case["config_path"].with_suffix(".locking")
        output=tmp_path/"locked-child.log"
        with output.open("w") as stream:
            child=subprocess.Popen([sys.executable,str(CHILD),str(case["config_path"]),"consume",body["command_id"],fault],
                cwd=ROOT,env=case["environment"],stdout=stream,stderr=subprocess.STDOUT)
            def wait(path):
                end=time.monotonic()+60
                while not path.exists() and child.poll() is None and time.monotonic()<end:
                    time.sleep(.02)
                assert path.exists(),output.read_text()
            try:
                wait(ready)
                with case["authority"].projections._connection(writing=True) as c:
                    case["authority"]._state(c,lock=True)
                    release.write_text("release")
                    wait(locking)
                    baseline=case["source"]["baseline"].database
                    if fault=="lock_replace":
                        replacement=baseline.with_suffix(".new")
                        replacement.write_bytes(baseline.read_bytes())
                        replacement.replace(baseline)
                    else:
                        Path(str(baseline)+"-wal").write_bytes(b"")
                assert child.wait(timeout=60)==0,output.read_text()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
        result=json.loads(output.read_text().splitlines()[-1])
    assert result["status"]=="rejected" and result["code"]=="ghcn_baseline_changed",result
    assert case["authority"].read()==before
    with case["authority"].projections._connection() as c:
        assert c.execute("SELECT count(*) FROM theheat_spending.events WHERE kind='dispatched'").fetchone()[0]==0


def test_matching_looking_recorded_receipts_never_replace_fresh_interpretation(ghcn_case):
    case=ghcn_case
    status,listing,_=http(case["port"],"/generation")
    assert status==200
    brief=listing["briefs"][0]
    body=command(case,"request_sourced_generation",{k:brief[k] for k in ("brief_id","brief_sha256","expected_state_version","expected_policy_sha256")})
    assert submit(case,body)["status"]=="applied"
    assert worker(case,"write",body["command_id"])["outcome"]=="response_retained"
    captured=worker(case,"capture",body["command_id"])
    check=command(case,"request_candidate_checks",captured["candidate"])
    assert submit(case,check)["status"]=="unchanged"
    for stage in ("deterministic","safety","fact_check","critic"):
        done=worker(case,stage,check["command_id"],"forged_interpreter" if stage=="safety" else "")
        assert done["checks"]["stages"][stage]=="passed",done
    row=worker(case,"projection",fault="passive_traps")[0]
    assert row["status"]=="checks_recorded" and not row["required_checks_completed"]
    before=case["authority"].read()
    admit=command(case,"admit_checked_candidate",dict(captured["candidate"],**{k:row[k] for k in ("check_set_id","expected_completion_sha256")}))
    result=submit(case,admit)
    assert result["status"]=="rejected" and result["code"]=="check_receipt_not_exact",result
    assert case["authority"].read()==before
