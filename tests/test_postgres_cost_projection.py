"""Actual local journal/HTTP cost readback; no provider or billing operations."""
from datetime import timedelta

from src.commands import postgres_cost_projection as cost, postgres_spending as spend
from src.commands.schema import utc_datetime, utc_text
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_command_authority import make_authority as make_authority, core as core
from tests.test_spend_journal import NOW, LIMITS, intent, call
from tests.stage_revision_check_helpers import install_revision_protocol


def test_unknown_reserved_settled_and_released_totals(store,monkeypatch):
    call(store,"reserve",intent())
    before=store.read()
    value=store.local_cost_projection(now=utc_datetime(NOW))
    assert value["status"]=="available",value
    assert value["summary"]["commitments_micro_usd"]["held"]=="60"
    assert value["requests"][0]["recorded_settlement_micro_usd"] is None
    assert value["requests"][0]["origin"]["kind"]=="unattributed"
    call(store,"dispatch")
    call(store,"uncertain")
    assert store.local_cost_projection(now=utc_datetime(NOW)+timedelta(days=100))["summary"]["commitments_micro_usd"]["held"]=="60"
    call(store,"settle",dict(intent_id="attempt-1",amount_micro_usd=0,evidence_sha256="a"*64))
    value=store.local_cost_projection(now=utc_datetime(NOW))
    assert value["requests"][0]["recorded_settlement_micro_usd"]=="0" and value["summary"]["commitments_micro_usd"]["held"]=="0"
    assert store.read()==before


def test_twenty_selected_only_and_exact_aggregate(core,monkeypatch):
    authority,_,owner,_=core
    owner.initialize_spending()
    call(authority,"configure",{**LIMITS,"daily_micro_usd":10**12,"monthly_micro_usd":10**12,"per_job_micro_usd":10**12})
    for i in range(25):
        call(authority,"reserve",intent(f"i{i:02}",amount=i+1,job=f"j{i}"))
    original=spend._record
    seen=[]
    def selected(c,identity):
        assert identity in {f"i{i:02}" for i in range(20)}
        seen.append(identity)
        return original(c,identity)
    monkeypatch.setattr(spend,"_record",selected)
    value=authority.local_cost_projection(now=utc_datetime(NOW))
    assert value["status"]=="available",value
    assert value["shown_intents"]==20 and value["omitted_intents"]==5 and value["details_truncated"]
    assert value["summary"]["commitments_micro_usd"]["held"]==str(sum(range(1,26)))
    assert len(seen)==len(set(seen))==20


def test_cost_failure_and_deadline_do_not_change_state(core,store,monkeypatch):
    assert store.local_cost_projection(now=utc_datetime(NOW))["requests"]==[]
    monkeypatch.setattr(cost,"SECONDS",0)
    assert store.local_cost_projection(now=utc_datetime(NOW))==cost.unavailable("projection_timeout")
    assert store.read()==(0,core[1])


# Reuse real existing producers; no cost-only fake grant or 'verified' flag.
import json
import os
from pathlib import Path
import subprocess
from datetime import UTC, datetime

import pytest

from src.commands import postgres_sourced_generation as generation, postgres_synchronous_generation as sync
from tests import test_postgres_sourced_generation as batch_source
from tests import test_postgres_synchronous_generation as sync_source
from tests import test_postgres_ghcn_generation as ghcn
from tests.test_postgres_ghcn_generation import ghcn_case as ghcn_case, source_bytes as source_bytes
from tests.workflow_clock import positive_workflow_clock as positive_workflow_clock
from tests.test_postgres_sourced_generation import sourced as sourced
from tests.test_postgres_synchronous_generation import urgent as urgent
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_postgres_preview_command_ingress import http


@pytest.fixture(autouse=True)
def _stable_ghcn_positive_time(request):
    # The reused GHCN fixture must share its clock before source_bytes is built.
    # Other cost scenarios retain their existing clocks.
    if "ghcn_case" in request.fixturenames:
        request.getfixturevalue("positive_workflow_clock")
    yield


@pytest.fixture
def store(core):
    authority,_,owner,_=core
    for method in ("initialize_spending","initialize_batches","initialize_batch_workers","initialize_batch_results","initialize_candidate_checks","initialize_check_executions"):
        getattr(owner,method)()
    call(authority,"configure",LIMITS)
    return authority


def passive_traps(monkeypatch):
    from src.commands import postgres_checks, postgres_check_observations, postgres_sync_checks, postgres_batch_results
    from src.two_bot import writer, batch_contract, check_origin, synchronous_origin
    def forbidden(*args,**kwargs):
        pytest.fail("Executable editorial reader reached from cost projection")
    from src.two_bot import ghcn_claim_view
    from src.storage.ghcn_runtime_inputs import Baseline
    monkeypatch.setattr(Baseline,"reader",forbidden)
    for module,names in ((ghcn_claim_view,("prepare_execution","_reconstruct","baseline_footprint")),(postgres_checks,("_packet","_current","_stages")),
        (postgres_check_observations,("_read","_scoped_attempt","read_request","read_response")),
        (postgres_sync_checks,("packet","current")),(sync,("job","attempt","observation","resolution","verify_candidate","project","interpret")),
        (generation,("document","current","writer_usage")),(postgres_batch_results,("index","_receipts","evaluate")),
        (writer,("_parse_writer_json",)),(batch_contract,("interpret_writer_message",)),
        (check_origin,("packet_verification","validate_revision")),(synchronous_origin,("validate",))):
        for name in names:
            monkeypatch.setattr(module,name,forbidden)


def test_actual_batch_writer_passive_cost(sourced,monkeypatch):
    assert batch_source.request(sourced)["status"]=="applied"
    reserved=sourced["store"].local_cost_projection(now=batch_source.NOW)
    assert reserved["requests"][0]["usage"]["reason"]=="not_dispatched"
    sent,factory=batch_source.transport(sourced)
    assert batch_source.run(sourced,"submit",factory)["outcome"]=="submitted"
    assert sourced["store"].local_cost_projection(now=batch_source.NOW)["requests"][0]["usage"]["reason"]=="response_missing"
    assert batch_source.run(sourced,"collect",factory)["outcome"]=="reviewed"
    before=sourced["store"].read()
    with monkeypatch.context() as local:
        passive_traps(local)
        value=sourced["store"].local_cost_projection(now=batch_source.NOW)
    assert value["status"]=="available",value
    row=value["requests"][0]
    assert row["origin"]["kind"]=="sourced_batch_writer" and row["usage"]["counts"]["input_tokens"]==17,row
    assert row["usage"]["counts"]["cache_creation.ephemeral_1h_input_tokens"]==50
    assert len(sent)==3 and sourced["store"].read()==before


def test_actual_sync_writer_and_four_check_grants_passive_cost(urgent,monkeypatch):
    assert batch_source.request(urgent)["status"]=="applied"
    sent,factory=sync_source.transport(urgent)
    assert batch_source.run(urgent,"write",factory)["outcome"]=="response_retained"
    sync_source.checked(urgent,monkeypatch)
    authority=urgent["store"]
    before=authority.read()
    with monkeypatch.context() as local:
        passive_traps(local)
        value=authority.local_cost_projection(now=sync_source.candidate.AT)
    assert value["status"]=="available",value
    assert len(value["requests"])==4
    assert {r["role"] for r in value["requests"]}=={"writer","safety","fact_check","critic"}
    assert len({r["origin"]["grant_id"] for r in value["requests"]})==4
    assert all(r["usage"]["status"] in {"present","absent"} for r in value["requests"]),value
    assert len(sent)==1 and authority.read()==before


def test_actual_ghcn_source_writer_checks_draft_cost_http(ghcn_case,monkeypatch,tmp_path,cluster):
    case=ghcn_case
    status,listing,_=http(case["port"],"/generation")
    assert status==200
    brief=listing["briefs"][0]
    start=ghcn.command(case,"request_sourced_generation",{k:brief[k] for k in ("brief_id","brief_sha256","expected_state_version","expected_policy_sha256")})
    assert ghcn.submit(case,start)["status"]=="applied"
    assert ghcn.worker(case,"write",start["command_id"])["outcome"]=="response_retained"
    captured=ghcn.worker(case,"capture",start["command_id"])
    check=ghcn.command(case,"request_candidate_checks",captured["candidate"])
    assert ghcn.submit(case,check,role="publisher")["status"]=="unchanged"
    for stage in ("deterministic","safety","fact_check","critic"):
        assert ghcn.worker(case,stage,check["command_id"])["outcome"]=="completed"
    projected=ghcn.worker(case,"projection",fault="passive_traps")[0]
    refs=dict(captured["candidate"],**{k:projected[k] for k in ("check_set_id","expected_completion_sha256")})
    assert ghcn.submit(case,ghcn.command(case,"admit_checked_candidate",refs))["status"]=="applied"
    authority=case["authority"]
    from tests.test_postgres_editor_media import all_application_rows
    before=authority.read()
    journal_before=all_application_rows(case["params"])
    with monkeypatch.context() as local:
        passive_traps(local)
        value=authority.local_cost_projection(now=datetime.now(UTC))
    assert value["status"]=="available",value
    assert len(value["requests"])==4 and all(r["origin"]["brief_id"]==case["refs"]["brief_id"] for r in value["requests"])
    assert len({r["origin"]["grant_id"] for r in value["requests"]})==4
    assert all(r["origin"]["raw_sha256"] is not None for r in value["requests"])
    response=http(case["port"],role="viewer")
    assert response[0]==200 and response[2]["Cache-Control"]=="private, no-store"
    assert response[1]["local_cost"]["requests"]==value["requests"]
    assert before==authority.read()
    assert all(r["origin"]["source_run_id"]==case["config"]["run_id"] for r in value["requests"])
    cost_component_http(case,case["port"],value,tmp_path/"cost-http.json")
    assert all_application_rows(case["params"])==journal_before
    restored_readback(case,value,cluster,tmp_path)
    if os.environ.get("THEHEAT_COST_TRACE"):
        path=Path(os.environ["THEHEAT_COST_TRACE"])
        path.write_text(json.dumps(dict(schema_version=1,source_refs=case["refs"],source_run_id=case["config"]["run_id"],
            request_command=start,check_command=check,cost=value,asserted_native_journey=False,
            http_component_restart_fresh_pg_restore="passed",all_application_rows_unchanged=True),sort_keys=True,indent=2)+"\n")



def restored_readback(case,expected,cluster,tmp_path):
    import tempfile
    import threading
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    from src.commands.preview_ingress import PreviewServer
    from tests.test_postgres_command_authority import options
    from tests.test_postgres_editor_media import all_application_rows
    from tests.test_postgres_preview_command_ingress import ORIGIN
    params=case["params"]
    before=all_application_rows(params)
    original_authority=case["server"].authority
    # Restart the authority with no generation configuration or baseline. This
    # cost read must still explain the original requests, not rerun the source.
    reopened=PostgresCommandAuthority(**options(params))
    try:
        case["server"].authority=reopened
        assert http(case["port"],role="viewer")[1]["local_cost"]["requests"]==expected["requests"]
    finally:
        case["server"].authority=original_authority
    assert all_application_rows(params)==before
    _,tool,_=cluster
    with tempfile.TemporaryDirectory(prefix="theheat-cost-restore-",dir="/tmp") as directory:
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
                c.execute("CREATE DATABASE restored_cost TEMPLATE template0")
            tool("pg_restore","-h",socket,"-p","55477","-U","projection_owner","-d","restored_cost","--exit-on-error","--single-transaction",dump)
            restored_params=dict(host=str(socket),port=55477,user="projection_owner",dbname="restored_cost")
            assert all_application_rows(restored_params)==before
            authority=PostgresCommandAuthority(**options(restored_params))
            server=PreviewServer(authority,case["operators"],port=0,origin=ORIGIN)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                actual=http(server.server_port,role="viewer")
                assert actual[0]==200
                value=actual[1]["local_cost"]
                assert {k:v for k,v in value.items() if k!="snapshot"}=={k:v for k,v in expected.items() if k!="snapshot"}
                assert value["snapshot"]["state_version"]==expected["snapshot"]["state_version"]
                cost_component_http(case,server.server_port,value,tmp_path/"restore-cost-http.json")
                assert all_application_rows(restored_params)==before
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl","-D",data,"-m","fast","-w","stop")
    assert all_application_rows(params)==before


def cost_component_http(case,port,value,config):
    import shutil
    config.write_text(json.dumps(dict(endpoint=f"http://127.0.0.1:{port}",origin=case.get("origin","http://127.0.0.1:3035"),expected=value)))
    node=os.environ.get("THEHEAT_TEST_NODE") or shutil.which("node")
    assert node,"Node is required for the actual cost HTTP/component journey"
    run=subprocess.run([node,"--test","tests/local-cost-evidence.test.js"],cwd=Path(__file__).resolve().parents[1]/"dashboard",
        env={**case["environment"],"THEHEAT_COST_TEST_CONFIG":str(config)},capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr


def test_projection_budget_preflights_before_body_fetch(store,monkeypatch):
    call(store,"reserve",intent())
    with monkeypatch.context() as local:
        local.setattr(cost,"MAX_BYTES",0)
        value=store.local_cost_projection(now=utc_datetime(NOW))
    assert value["status"]=="available" and value["summary"]["commitments_micro_usd"]["held"]=="60"
    with store.projections._connection() as connection:
        import time
        reader=cost.Read(connection,time.monotonic()+3)
        reader.remaining=0
        reader.charge(0)
        with pytest.raises(cost.Limited):
            reader.charge(1)


def test_selected_corruption_is_unavailable_without_repair(store,monkeypatch):
    call(store,"reserve",intent())
    before=store.read()
    def corrupt(*_):
        raise ValueError("invented private corrupt payload must not escape")
    monkeypatch.setattr(spend,"_record",corrupt)
    assert store.local_cost_projection(now=utc_datetime(NOW))==cost.unavailable()
    assert store.read()==before


def test_read_waits_on_existing_pointer_and_returns_unavailable_on_timeout(store,core):
    import psycopg
    with psycopg.connect(**{**core[3],"autocommit":False}) as c:
        c.execute("SELECT version FROM theheat_commands.state WHERE singleton=1 FOR UPDATE")
        assert store.local_cost_projection(now=utc_datetime(NOW))["status"]=="unavailable"
    assert store.local_cost_projection(now=utc_datetime(NOW))["status"]=="available"


from tests.test_postgres_editor_media import admitted as admitted, offline_connections as offline_connections
from tests.native_profile_helpers import native_dependencies as native_dependencies


@pytest.mark.parametrize('admitted',['modis'],indirect=True)
def test_actual_saved_media_and_batch_check_cost(admitted,monkeypatch):
    from tests import test_postgres_editor_media as media
    media.prepare_and_attach(admitted)
    media.complete_revision(admitted,monkeypatch)
    authority=admitted['store']
    before=authority.read()
    with monkeypatch.context() as local:
        passive_traps(local)
        value=authority.local_cost_projection(now=media.AT)
    assert value['status']=='available',value
    assert len(value['requests'])==7
    assert sum(r['origin']['kind']=='required_check' for r in value['requests'])==6
    assert len({r['origin']['check_set_id'] for r in value['requests'] if r['role']!='writer'})==2
    assert all(r['origin']['brief_id']==admitted['refs']['brief_id'] for r in value['requests'])
    assert before==authority.read()


def test_selected_check_never_replays_unselected_parent_or_siblings(urgent,monkeypatch):
    batch_source.request(urgent)
    _,factory=sync_source.transport(urgent)
    batch_source.run(urgent,'write',factory)
    sync_source.checked(urgent,monkeypatch)
    at=sync_source.candidate.AT+timedelta(seconds=1)
    from src.commands.schema import utc_text
    for i in range(19):
        call(urgent['store'],'reserve',intent(f'new-{i:02}',amount=1,job=f'news-{i}',role='news'),at=utc_text(at))
    original=spend._record
    selected={f'new-{i:02}' for i in range(19)}|{'sync-check-critic'}
    seen=[]
    def record(c,identity):
        assert identity in selected,'Unselected spending replay: '+identity
        seen.append(identity)
        return original(c,identity)
    with monkeypatch.context() as local:
        passive_traps(local)
        local.setattr(spend,'_record',record)
        value=urgent['store'].local_cost_projection(now=at)
    assert value['status']=='available',value
    assert set(seen)==selected and len(seen)==20
    assert value['total_intents']==23 and value['omitted_intents']==3
    assert value['summary']['commitments_micro_usd']['held']=='54'
    row=next(r for r in value['requests'] if r['role']=='critic')
    assert row['origin']['brief_id']==urgent['refs']['brief_id'] and row['origin']['kind']=='required_check'


@pytest.mark.parametrize('mode',['invalid_editorial','missing_usage','zero_usage','truncated','lost'])
def test_sync_unknown_response_and_usage_survive_without_replay(urgent,monkeypatch,mode):
    from src.two_bot.provider_http import anthropic_httpx
    raw=(anthropic_httpx().ReadTimeout('invented lost response') if mode=='lost' else b'{"usage":' if mode=='truncated' else
        json.dumps(dict(content=[dict(type='text',text='not an editorial result')],model='invented-model',
            **({} if mode=='missing_usage' else dict(usage=dict(input_tokens=0 if mode=='zero_usage' else 7,output_tokens=0))))).encode())
    batch_source.request(urgent)
    sent,factory=sync_source.transport(urgent,raw=raw)
    batch_source.run(urgent,'write',factory)
    before=urgent['store'].read()
    with monkeypatch.context() as local:
        passive_traps(local)
        first=urgent['store'].local_cost_projection(now=batch_source.NOW)
        second=urgent['store'].local_cost_projection(now=batch_source.NOW+timedelta(days=90))
    assert first['status']=='available',first
    row=first['requests'][0]
    assert row==second['requests'][0] and row['held_micro_usd']=='20'
    assert row['recorded_settlement_micro_usd'] is None
    if mode in {'invalid_editorial','zero_usage'}:
        assert row['usage']['status']=='present' and row['usage']['counts']['input_tokens']==(0 if mode=='zero_usage' else 7)
    elif mode=='missing_usage':
        assert row['usage']['status']=='absent' and row['usage']['counts']['input_tokens'] is None
    else:
        assert row['usage']['status'] in {'invalid','unavailable'} and row['usage']['counts']['input_tokens'] is None
    assert len(sent)==1 and urgent['store'].read()==before


def test_selected_join_faults_are_known_unavailable_not_partial_totals(urgent,monkeypatch):
    from copy import deepcopy
    batch_source.request(urgent)
    _,factory=sync_source.transport(urgent)
    batch_source.run(urgent,'write',factory)
    sync_source.checked(urgent,monkeypatch)
    authority=urgent['store']
    before=authority.read()
    original=cost.Read.document
    projection=cost.Read.projection
    for kind in ('owner','fence','request','reservation','packet','input','parent'):
        def document(self,table,digest):
            value=deepcopy(original(self,table,digest))
            if table=='binding_artifacts':
                if kind=='owner':
                    value['owner']='changed-owner'
                if kind=='fence':
                    value['fence']+=1
                if kind=='request':
                    value['request_sha256']='d'*64
                if kind=='reservation':
                    value['reservation']['reserve_micro_usd']+=1
            if table=='packet_artifacts' and kind=='packet':
                value['required_stages']=[]
            return value
        def retained(self,namespace,identity,**kwargs):
            value=projection(self,namespace,identity,**kwargs)
            if value and (kind=='input' and namespace=='candidate-admission-input-v1' or kind=='parent' and namespace==sync.JOB):
                value=(value[0],deepcopy(value[1]))
                value[1]['current_context' if kind=='input' else 'context']['memory_sha256']='f'*64
            return value
        with monkeypatch.context() as local:
            passive_traps(local)
            local.setattr(cost.Read,'document',document)
            local.setattr(cost.Read,'projection',retained)
            assert authority.local_cost_projection(now=sync_source.candidate.AT)==cost.unavailable(),kind
    assert authority.read()==before


def test_batch_many_receipts_metadata_only_ambiguity_and_budget(sourced,monkeypatch):
    from src.commands import postgres_batch_results as results, batch_result_journal as result_journal
    from src.storage import postgres_projection as p
    from tests.test_batch_result_journal import retain
    from src.commands.schema import utc_text
    batch_source.request(sourced)
    _,factory=batch_source.transport(sourced)
    batch_source.run(sourced,'submit',factory)
    batch_source.run(sourced,'collect',factory)
    authority=sourced['store']
    job=sourced['result']['generation']['job_id']
    with authority.projections._connection() as c:
        grant_id=c.execute('SELECT grant_id FROM theheat_batch_work.submissions WHERE job_id=%s',(job,)).fetchone()[0]
        meta,raw=c.execute('SELECT m.payload,r.payload FROM theheat_batch_results.receipts t JOIN theheat_batch_results.metadata_artifacts m ON m.sha=t.metadata_sha256 JOIN theheat_batch_results.result_artifacts r ON r.sha=t.results_sha256 WHERE job_id=%s',(job,)).fetchone()
    grant=dict(job_id=job,grant_id=grant_id)
    # Sixteen retained results include fifteen large incomplete results. Only
    # the original chosen complete body may be fetched by a passive cost GET.
    for i in range(15):
        huge=(str(i)+'x'*(result_journal.MAX_RESULT_BYTES-2)).encode()
        retain(authority,grant,huge,meta=meta,complete=False,at=utc_text(batch_source.NOW))
    before=authority.read()
    original=cost.Read.artifact
    seen=[]
    def artifact(self,schema,table,digest,*args,**kwargs):
        if schema==results.SCHEMA and table=='result_artifacts':
            assert digest==p._sha(raw),'Unchosen raw body loaded'
            seen.append(digest)
        return original(self,schema,table,digest,*args,**kwargs)
    with monkeypatch.context() as local:
        passive_traps(local)
        local.setattr(cost.Read,'artifact',artifact)
        value=authority.local_cost_projection(now=batch_source.NOW)
    assert value['status']=='available' and value['requests'][0]['usage']['status']=='present',value
    assert seen==[p._sha(raw)] and before==authority.read()
    with monkeypatch.context() as local:
        passive_traps(local)
        local.setattr(cost,'MAX_BYTES',1)
        def no_body(c,*args):
            pytest.fail('Projection body fetched beyond the cumulative allowance')
        local.setattr(p.PostgresProjectionRepository,'_read',no_body)
        value=authority.local_cost_projection(now=batch_source.NOW)
    assert value['status']=='available' and value['requests'][0]['usage']['reason']=='projection_limited'
    assert value['summary']['commitments_micro_usd']['held']=='20'


def test_batch_same_raw_hash_deduplicates_but_conflicting_complete_hash_is_unknown(sourced,monkeypatch):
    from src.storage import postgres_projection as p
    from tests.test_batch_result_journal import retain
    from src.commands.schema import utc_text
    batch_source.request(sourced)
    _,factory=batch_source.transport(sourced)
    batch_source.run(sourced,'submit',factory)
    batch_source.run(sourced,'collect',factory)
    authority=sourced['store']
    job=sourced['result']['generation']['job_id']
    with authority.projections._connection() as c:
        grant_id=c.execute('SELECT grant_id FROM theheat_batch_work.submissions WHERE job_id=%s',(job,)).fetchone()[0]
        meta,raw=c.execute('SELECT m.payload,r.payload FROM theheat_batch_results.receipts t JOIN theheat_batch_results.metadata_artifacts m ON m.sha=t.metadata_sha256 JOIN theheat_batch_results.result_artifacts r ON r.sha=t.results_sha256 WHERE job_id=%s',(job,)).fetchone()
    grant=dict(job_id=job,grant_id=grant_id)
    meta=p._canonical(dict(json.loads(meta),invented_duplicate=True))
    retain(authority,grant,raw,meta=meta,at=utc_text(batch_source.NOW))
    first=authority.local_cost_projection(now=batch_source.NOW)
    assert first['status']=='available' and first['requests'][0]['usage']['counts']['input_tokens']==17,first
    retain(authority,grant,raw+b'\n',meta=meta,at=utc_text(batch_source.NOW))
    with monkeypatch.context() as local:
        passive_traps(local)
        original=cost.Read.artifact
        def no_raw(self,schema,table,*args,**kwargs):
            assert table!='result_artifacts'
            return original(self,schema,table,*args,**kwargs)
        local.setattr(cost.Read,'artifact',no_raw)
        value=authority.local_cost_projection(now=batch_source.NOW)
    assert value['status']=='available' and value['requests'][0]['usage']['reason']=='ambiguous_response',value
    assert value['summary']['commitments_micro_usd']['held']=='20'


def test_supported_reservation_waits_for_cost_pointer_snapshot(store,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered,started,committed=threading.Event(),threading.Event(),threading.Event()
    original=spend.apply
    def gated(c,action,payload,**kwargs):
        if action=='status' and threading.current_thread().name.startswith('cost-reader'):
            entered.set()
            assert started.wait(1)
            assert not committed.wait(.08),'Writer bypassed the shared pointer lock'
        return original(c,action,payload,**kwargs)
    monkeypatch.setattr(spend,'apply',gated)
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='cost-reader') as pool:
        future=pool.submit(store.local_cost_projection,now=utc_datetime(NOW))
        assert entered.wait(2)
        def writer():
            started.set()
            call(store,'reserve',intent())
            committed.set()
        thread=threading.Thread(target=writer)
        thread.start()
        snapshot=future.result(timeout=5)
        thread.join(5)
    assert committed.is_set() and not thread.is_alive()
    assert snapshot['status']=='available' and snapshot['total_intents']==0
    assert store.local_cost_projection(now=utc_datetime(NOW))['summary']['commitments_micro_usd']['held']=='60'


from tests.test_postgres_preview_command_ingress import preview as preview


def test_auth_before_cost_and_missing_journal_isolated_from_drafts(preview,monkeypatch):
    port,authority,initial,*_=preview
    assert http(port,role='viewer')[1]['local_cost']['status'] in {'unconfigured','unavailable'}
    reads=[]
    def unavailable(**_):
        reads.append(True)
        return cost.unavailable()
    monkeypatch.setattr(authority,'local_cost_projection',unavailable)
    assert http(port,headers={'Authorization':''})[0]==401
    assert http(port,headers={'Origin':'https://invalid.example'})[0]==403
    assert reads==[]
    status,value,_=http(port,role='viewer')
    assert status==200 and value['state']==initial and value['local_cost']==cost.unavailable()
    assert len(reads)==1
    assert http(port,'/state',method='POST',role='viewer',value={})[0] in {403,404}
    assert len(reads)==1


def test_real_catalog_and_role_drift_refuse_without_read_side_repair(store,core):
    import psycopg
    call(store,'reserve',intent())
    before=store.read()
    with psycopg.connect(**{**core[3],"autocommit":True}) as owner:
        owner.execute('GRANT UPDATE ON theheat_spending.intents TO projection_runtime')
        assert store.local_cost_projection(now=utc_datetime(NOW))==cost.unavailable()
        # The GET did not repair the owner's explicit fixture-only fault.
        assert owner.execute("SELECT has_table_privilege('projection_runtime','theheat_spending.intents','UPDATE')").fetchone()==(True,)
        owner.execute('REVOKE UPDATE ON theheat_spending.intents FROM projection_runtime')
    assert store.local_cost_projection(now=utc_datetime(NOW))['status']=='available'
    assert store.read()==before


def test_real_settlement_overrun_release_and_window_totals(store):
    call(store,'reserve',intent(amount=20))
    call(store,'reserve',intent('repair',amount=5,job='other',role='repair'))
    call(store,'release',dict(intent_id='repair'))
    call(store,'dispatch')
    call(store,'settle',dict(intent_id='attempt-1',amount_micro_usd=21,evidence_sha256='f'*64))
    at=utc_datetime(NOW)
    value=store.local_cost_projection(now=at)
    totals=call(store,'status',{})['totals']
    assert value['summary']['commitments_micro_usd']=={k:str(totals[k+'_micro_usd']) for k in ('daily','monthly','held')}
    assert value['summary']['overrun_count']==1 and value['summary']['reservation_counts']['released']==1
    released=next(r for r in value['requests'] if r['intent_id']=='repair')
    assert released['held_micro_usd']=='0' and released['recorded_settlement_micro_usd'] is None
    rollover=store.local_cost_projection(now=at+timedelta(days=100))
    assert rollover['summary']['commitments_micro_usd']==dict(daily='0',monthly='0',held='0')
    assert rollover['summary']['overrun_count']==1


def test_passive_join_raw_lease_and_time_faults(urgent,monkeypatch):
    batch_source.request(urgent)
    _,factory=sync_source.transport(urgent)
    batch_source.run(urgent,'write',factory)
    sync_source.checked(urgent,monkeypatch)
    original=cost.Read.execute
    for fault in ('lease_owner','lease_window','raw_sha','receipt_time','observation_time','attempt_grant'):
        seen=[]
        class Changed:
            def __init__(self,cursor,query):
                self.cursor,self.query=cursor,query
            def fetchone(self):
                row=self.cursor.fetchone()
                if row is None:
                    return row
                values=list(row)
                if 'FROM theheat_checks.draft_leases' in self.query and fault.startswith('lease_'):
                    values[0 if fault=='lease_owner' else 2]='wrong-owner' if fault=='lease_owner' else '2000-01-01T00:00:00.000000Z'
                elif 'FROM theheat_check_executions.observations' in self.query and fault in {'raw_sha','observation_time'}:
                    values[1 if fault=='raw_sha' else 2]='a'*64 if fault=='raw_sha' else '2000-01-01T00:00:00.000000Z'
                elif 'FROM theheat_checks.receipts' in self.query and fault=='receipt_time':
                    values[2]='2000-01-01T00:00:00.000000Z'
                else:
                    return row
                seen.append(True)
                return tuple(values)
            def fetchall(self):
                rows=self.cursor.fetchall()
                if fault=='attempt_grant' and 'FROM theheat_checks.attempts' in self.query and rows:
                    values=list(rows[0])
                    values[2]='b'*64
                    seen.append(True)
                    return [tuple(values)]
                return rows
        def execute(self,query,params=None):
            return Changed(original(self,query,params),query)
        with monkeypatch.context() as local:
            passive_traps(local)
            local.setattr(cost.Read,'execute',execute)
            assert urgent['store'].local_cost_projection(now=sync_source.candidate.AT)==cost.unavailable(),fault
        assert seen,fault


def test_usage_parse_is_after_owned_connection_closes(urgent,monkeypatch):
    from contextlib import contextmanager
    batch_source.request(urgent)
    _,factory=sync_source.transport(urgent)
    batch_source.run(urgent,'write',factory)
    connection=urgent['store'].projections._connection
    active=[]
    @contextmanager
    def tracked(**kwargs):
        with connection(**kwargs) as c:
            active.append(True)
            try:
                yield c
            finally:
                active.pop()
    original=cost.usage.extract
    parsed=[]
    def extract(*args,**kwargs):
        assert not active,'Usage parsed under SQL lock'
        parsed.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(urgent['store'].projections,'_connection',tracked)
    monkeypatch.setattr(cost.usage,'extract',extract)
    assert urgent['store'].local_cost_projection(now=batch_source.NOW)['status']=='available'
    assert parsed==[True]


def test_late_detached_usage_and_wire_limit_are_unavailable(urgent,monkeypatch):
    batch_source.request(urgent)
    _,factory=sync_source.transport(urgent)
    batch_source.run(urgent,'write',factory)
    original=cost.usage.extract
    clock=[10.0]
    def extract(*args,**kwargs):
        result=original(*args,**kwargs)
        clock[0]+=4
        return result
    with monkeypatch.context() as local:
        local.setattr(cost.time,'monotonic',lambda:clock[0])
        local.setattr(cost.usage,'extract',extract)
        assert urgent['store'].local_cost_projection(now=batch_source.NOW)==cost.unavailable('projection_timeout')
    with monkeypatch.context() as local:
        local.setattr(cost,'MAX_OUTPUT',1)
        assert urgent['store'].local_cost_projection(now=batch_source.NOW)==cost.unavailable('projection_limited')


def test_batch_detached_extra_duplicate_wrong_custom_envelopes_are_invalid():
    from src.storage import postgres_projection as p
    row=dict(provider='anthropic',role='writer',requested_model='invented')
    valid=dict(custom_id='one',result=dict(type='succeeded',message=dict(usage=dict(input_tokens=0))))
    for values in ([valid,valid],[],[dict(valid,custom_id='other')]):
        result=cost._detached_usage(dict(raw=b'\n'.join(p._canonical(v) for v in values),observed_at=spend._time(NOW),complete=True,
            batch_custom_id='one',batch_metadata=b'{"id":"batch"}',batch_provider_id='batch'),row)
        assert result['status']=='invalid' and result['counts']['input_tokens'] is None


def test_actual_google_terminal_disagreement_preserves_hold(urgent,monkeypatch):
    from copy import deepcopy
    batch_source.request(urgent)
    _,factory=sync_source.transport(urgent)
    batch_source.run(urgent,'write',factory)
    sync_source.checked(urgent,monkeypatch)
    original=cost.Read.document
    seen=[]
    def document(self,table,digest):
        value=original(self,table,digest)
        if table=='receipt_artifacts' and value['usage'] is not None:
            assert value['usage']['promptTokenCount']==19
            value=deepcopy(value)
            value['usage']['promptTokenCount']=99
            seen.append(True)
        return value
    before=urgent['store'].read()
    with monkeypatch.context() as local:
        passive_traps(local)
        local.setattr(cost.Read,'document',document)
        value=urgent['store'].local_cost_projection(now=sync_source.candidate.AT)
    assert value['status']=='available' and len(seen)==3,value
    assert value['summary']['commitments_micro_usd']['held']=='35'
    assert all(r['usage']['status']=='invalid' and r['usage']['counts']['prompt_token_count'] is None for r in value['requests'] if r['role']!='writer')
    assert value['requests'][0]['recorded_settlement_micro_usd'] is None
    assert urgent['store'].read()==before


def source_origin_counterexamples(case,monkeypatch):
    from copy import deepcopy
    from dataclasses import replace
    from uuid import uuid4
    import time
    from src.storage import postgres_projection as p
    from src.two_bot.check_origin import SOURCE_NAMESPACE
    authority=case['store']
    with authority.projections._connection() as c:
        raw=c.execute("SELECT a.payload FROM theheat_checks.sets s JOIN theheat_checks.packet_artifacts a ON a.sha=s.packet_sha256 WHERE s.origin_kind='saved_draft_revision_v1'").fetchone()[0]
        packet=p._decode(raw)
        reader=cost.Read(c,time.monotonic()+3)
        source_receipt,source=reader.projection(SOURCE_NAMESPACE,packet['source_origin']['snapshot_id'])
    fields={'schema_version':99,'admission_command_id':str(uuid4()),'admission_input_id':'a'*64,'admission_input_sha256':'b'*64}
    fields.update({'job_id':'changed-job','plan_sha256':'d'*64} if source['schema_version']==1 else {'generation_id':'gss_'+'a'*64,'grant_id':'b'*64,'resolution_sha256':'c'*64})
    original=cost.Read.projection
    for field,value in fields.items():
        changed=deepcopy(source)
        changed[field]=value
        changed_receipt=replace(source_receipt,canonical_sha256=p._sha(p._canonical(changed)))
        changed_packet=deepcopy(packet)
        changed_packet['source_origin']['canonical_sha256']=changed_receipt.canonical_sha256
        def projection(self,namespace,identity,**kwargs):
            if namespace==SOURCE_NAMESPACE:
                return changed_receipt,changed
            return original(self,namespace,identity,**kwargs)
        with monkeypatch.context() as local:
            passive_traps(local)
            local.setattr(cost.Read,'projection',projection)
            with authority.projections._connection() as c:
                with pytest.raises(ValueError):
                    cost._revision_source(cost.Read(c,time.monotonic()+3),changed_packet)


def media_history_readback(case,core,cluster,tmp_path,monkeypatch):
    import threading
    from src.commands.postgres_authority import PostgresCommandAuthority
    from src.commands.preview_ingress import PreviewServer,Operators
    from tests.test_postgres_preview_command_ingress import clean_environment,operator_file,ORIGIN
    from tests.test_postgres_command_authority import options
    from tests import test_postgres_editor_media as media
    from src.commands import preview_media_worker
    assert media.action(case,'edit_revision',{'text':'Edited invented wording after the retained media checks.'})[1]['status']=='applied'
    source_origin_counterexamples(case,monkeypatch)
    # A new operator adapter has no current allowlist/renderer configuration;
    # historical cost evidence must survive that restart and elapsed expiry.
    reopened=PostgresCommandAuthority(**options(core[3]))
    with monkeypatch.context() as local:
        for key in tuple(os.environ):
            if key not in clean_environment() and ('TOKEN' in key or 'SECRET' in key or 'PASSWORD' in key or 'API_KEY' in key or key.startswith('PG')):
                local.delenv(key)
        local.delenv('NODE_ENV',raising=False)
        operators=Operators(operator_file(tmp_path/'cost-history-operators.json'))
        server=PreviewServer(reopened,operators,port=0,origin=ORIGIN)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        record=dict(case,params=core[3],server=server,port=server.server_port,operators=operators,environment=clean_environment())
        try:
            with local.context() as guarded:
                passive_traps(guarded)
                guarded.setattr(preview_media_worker,'run_native',lambda *a,**k:pytest.fail('Cost read invoked renderer'))
                value=reopened.local_cost_projection(now=media.AT+timedelta(days=100))
            assert value['status']=='available',value
            assert len(value['requests'])==7
            restored_readback(record,value,cluster,tmp_path)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


@pytest.mark.parametrize('admitted',['modis'],indirect=True)
def test_corrected_batch_media_source_after_edit_restart_and_restore(admitted,core,cluster,tmp_path,monkeypatch):
    from tests import test_postgres_editor_media as media
    media.prepare_and_attach(admitted)
    media.complete_revision(admitted,monkeypatch)
    media_history_readback(admitted,core,cluster,tmp_path,monkeypatch)


def test_corrected_sync_media_source_after_edit_restart_and_restore(urgent,core,cluster,tmp_path,monkeypatch,native_dependencies):
    from tests import test_postgres_editor_media as media
    batch_source.request(urgent)
    _,factory=sync_source.transport(urgent)
    batch_source.run(urgent,'write',factory)
    sync_source.checked(urgent,monkeypatch)
    core[2].initialize_media_staging()
    core[2].initialize_media_commands()
    urgent['store'].configure_editor_media(**native_dependencies,scratch=tmp_path/'native')
    install_revision_protocol(core[2], now=media.AT)
    media.prepare_and_attach(urgent)
    media.complete_revision(urgent,monkeypatch)
    media_history_readback(urgent,core,cluster,tmp_path,monkeypatch)


@pytest.mark.parametrize('original,canonical',[
    ('2026-09-29T12:00:00Z','2026-09-29T12:00:00.000000Z'),
    ('2026-09-29T12:00:00.000000Z','2026-09-29T12:00:00.000000Z'),
    ('2026-09-29T12:00:00.12Z','2026-09-29T12:00:00.120000Z'),
    ('2026-09-29T12:00:00.123456Z','2026-09-29T12:00:00.123456Z'),
])
def test_detached_usage_display_canonical_time_preserves_evidence(original,canonical):
    raw=b'{"usage":{"input_tokens":11,"output_tokens":7}}'
    detached=dict(raw=raw,observed_at=original,complete=True)
    result=cost._detached_usage(detached,dict(provider='anthropic',role='writer',requested_model='invented'))
    assert result['status']=='present' and result['observed_at']==canonical
    assert result['counts']['input_tokens']==11
    assert detached==dict(raw=raw,observed_at=original,complete=True)


@pytest.mark.parametrize('original',['bad','2026-02-30T12:00:00Z','2026-09-29T12:00:00.1234567Z',None])
def test_detached_usage_display_refuses_malformed_time(original):
    with pytest.raises(ValueError):
        cost._detached_usage(dict(raw=b'{}',observed_at=original,complete=True),
            dict(provider='anthropic',role='writer',requested_model='invented'))


from tests.test_postgres_published_media import radar_case as radar_case


def published_cost_traps(local):
    from src.commands import postgres_published_media, postgres_editor_media, preview_media_worker
    from src.media import published_radar
    passive_traps(local)
    def forbidden(*args,**kwargs):
        pytest.fail('Passive cost read invoked published source, eligibility or raster work')
    for module,names in ((postgres_published_media,('current','read')),
        (postgres_editor_media,('inputs','parked')),(preview_media_worker,('run_native',)),
        (published_radar,('document','source','make_spec','validate_spec','convert'))):
        for name in names:
            local.setattr(module,name,forbidden)
    original=cost.Read.artifact
    def no_media(self,schema,table,*args,**kwargs):
        assert not schema.startswith('theheat_media')
        return original(self,schema,table,*args,**kwargs)
    local.setattr(cost.Read,'artifact',no_media)


def test_published_check_cost_metadata_window_and_unknown_holds(radar_case,core,monkeypatch):
    from copy import deepcopy
    from src.commands import postgres_revision_checks, postgres_sync_checks
    from src.editorial.revisions import fingerprint
    from src.storage import postgres_projection as p
    from tests import test_postgres_published_media as published, test_postgres_editor_media as editor
    case=radar_case
    published.attach(case)
    editor.complete_revision(case,monkeypatch)
    authority=case['store']
    with authority.projections._connection() as c:
        rows=c.execute('SELECT payload FROM theheat_checks.packet_artifacts').fetchall()
    packet=next(json.loads(row[0]) for row in rows if json.loads(row[0]).get('schema_version')==6)
    def draft(value):
        return next(d for d in value['checker_state']['drafts'] if d['id']==case['draft_id'])
    def published_metadata(value):
        return draft(value)['media_attachment']['published']
    mutations={
        'family':lambda v:published_metadata(v).update(family='unknown_family'),
        'attachment_version':lambda v:draft(v)['media_attachment'].update(schema_version=1),
        'published_on_packet3':lambda v:v.update(schema_version=3),
        'frame_precision':lambda v:published_metadata(v).update(frame_minute_utc='2026-09-29T11:59:01Z'),
        'frame_arithmetic':lambda v:published_metadata(v).update(frame_minute_utc='2026-09-29T11:58:00Z'),
        'valid_end':lambda v:published_metadata(v).update(valid_end='2026-09-29T12:10:00Z'),
        'published_deadline':lambda v:published_metadata(v).update(useful_until='2026-09-29T12:13:00Z'),
        'packet_deadline':lambda v:v.update(useful_until='2026-09-29T12:13:00Z'),
        'invalid_time':lambda v:published_metadata(v).update(valid_end=None),
        'missing_published':lambda v:draft(v)['media_attachment'].pop('published'),
        'media_hash':lambda v:v['media'].update(review_sha256='f'*64),
        'review_command':lambda v:v['media'].update(review_command_id='00000000-0000-0000-0000-000000000000'),
        'target':lambda v:v['draft_target'].update(decision_revision=v['draft_target']['decision_revision']+1),
    }
    with monkeypatch.context() as local:
        published_cost_traps(local)
        cost._revision_media_envelope(packet)
        for name,mutate in mutations.items():
            altered=deepcopy(packet)
            mutate(altered)
            with pytest.raises(ValueError):
                cost._revision_media_envelope(altered)
        # Construct a detached stored-envelope reader, with every hash recomputed,
        # to prove that new versions stay unsupported instead of aliasing packet6.
        unsupported=deepcopy(packet)
        unsupported['schema_version']=7
        digest=p._sha(p._canonical(unsupported))
        class Envelope:
            def execute(self,*args):return self
            def fetchone(self):return (None,None,digest,unsupported['captured_at'],'saved_draft_revision_v1','draft-check-enrollment-v1',unsupported['enrollment_id'],None,None)
            def document(self,*args):return unsupported
        local.setattr(postgres_revision_checks,'upgraded',lambda _:True)
        local.setattr(postgres_sync_checks,'upgraded',lambda _:True)
        assert cost._packet(Envelope(),fingerprint(unsupported)) is None
    # Real original grants/leases remain validated, independently of the pure
    # metadata counterexamples above. No changed producer or fake authority.
    before=editor.all_application_rows(core[3])
    original=cost.Read.document
    for fault in ('owner','fence','request','enrollment'):
        def document(self,table,digest):
            value=deepcopy(original(self,table,digest))
            if table=='binding_artifacts' and value['check_set_id']==fingerprint(packet):
                if fault=='owner':
                    value['owner']='wrong-owner'
                if fault=='fence':
                    value['fence']+=1
                if fault=='request':
                    value['request_sha256']='f'*64
            if table=='packet_artifacts' and value.get('schema_version')==6 and fault=='enrollment':
                value['enrollment_id']='f'*64
            return value
        with monkeypatch.context() as local:
            published_cost_traps(local)
            local.setattr(cost.Read,'document',document)
            assert authority.local_cost_projection(now=editor.AT)==cost.unavailable(),fault
    original_packet=cost._packet
    def future(c,identity):
        loaded=original_packet(c,identity)
        return None if loaded and loaded[0]['schema_version']==6 else loaded
    with monkeypatch.context() as local:
        published_cost_traps(local)
        local.setattr(cost,'_packet',future)
        held=authority.local_cost_projection(now=editor.AT)
    assert held['status']=='available' and held['summary']['commitments_micro_usd']['held']=='50'
    assert sum(r['usage']['reason']=='unsupported_origin' for r in held['requests'])==3
    assert editor.all_application_rows(core[3])==before
    at=editor.AT+timedelta(seconds=1)
    for i in range(19):
        call(authority,'reserve',intent(f'radar-news-{i:02}',amount=1,job=f'radar-news-job-{i}',role='news'),at=utc_text(at))
    with authority.projections._connection() as c:
        check_intent=c.execute('SELECT intent_id FROM theheat_checks.attempts WHERE check_set_id=%s ORDER BY intent_id LIMIT 1',(fingerprint(packet),)).fetchone()[0]
    selected={f'radar-news-{i:02}' for i in range(19)}|{check_intent}
    record=spend._record
    seen=[]
    def selected_only(c,identity):
        assert identity in selected,'Unselected parent/sibling replay: '+identity
        seen.append(identity)
        return record(c,identity)
    with monkeypatch.context() as local:
        published_cost_traps(local)
        local.setattr(spend,'_record',selected_only)
        value=authority.local_cost_projection(now=at)
    assert value['status']=='available',value
    assert set(seen)==selected and len(seen)==20
    assert value['total_intents']==26 and value['omitted_intents']==6
    assert value['summary']['commitments_micro_usd']['held']=='69'
    check=next(r for r in value['requests'] if r['intent_id']==check_intent)
    assert check['origin']['brief_id']==case['refs']['brief_id'] and check['usage']['status']=='present'
    assert len(case['provider_requests'])==1
