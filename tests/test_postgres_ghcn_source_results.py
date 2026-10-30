"""Real local PG and authenticated HTTP; invented raw GHCN bytes only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

import pytest

from src.commands import postgres_ghcn_source_results as domain, postgres_source_results as shared
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import Operators, PreviewServer
from src.commands.schema import Command, CommandError, Principal, utc_text
from src.orchestrator.ghcn_source_result_client import GhcnSourceResultClient
from src.state import DEFAULT_STATE
from src.storage import ghcn_runtime_inputs as inputs
from src.storage.cyclone_supply import digest
from src.storage.scientific_supply import ScientificSupplySession, NAMESPACE
from tests.test_ghcn_runtime_inputs import source_bytes as source_bytes
from tests.test_ghcn_time_integrity import draft
from tests.test_postgres_command_authority import options
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_preview_command_ingress import ORIGIN, clean_environment, operator_file, http, body

BASE = 'c7197cefaa0ad611c819c2f249cf5a0059d80974'


@pytest.fixture
def configured(database, source_bytes, tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name not in clean_environment() and any(x in name for x in ('TOKEN','SECRET','PASSWORD','API_KEY','PG')):
            monkeypatch.delenv(name)
    monkeypatch.delenv('NODE_ENV', raising=False)
    _,_,params=database
    initial=deepcopy(DEFAULT_STATE)
    initial.update(drafts=[draft(event_day=source_bytes['day'],sid='USW00000000')], publish_ledger={},
        unowned={'money':None,'history':[False,0]}, source_health={'other':{'opaque':[1,None]}},run_history=[])
    owner=PostgresCommandAuthority(**options(params,params['user']))
    owner.initialize(initial,runtime_role='projection_runtime')
    authority=PostgresCommandAuthority(**options(params))
    baseline=source_bytes['baseline']
    authority.configure_ghcn_source_results(baseline)
    operators_path=operator_file(tmp_path/'operators.json')
    operators=Operators(operators_path)
    server=PreviewServer(authority,operators,port=0,origin=ORIGIN)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    client=GhcnSourceResultClient(authority.projections,f'http://127.0.0.1:{server.server_port}',ORIGIN,'editor','invented-editor')
    args=['--socket-directory',params['host'],'--database',params['dbname'],'--database-port',str(params['port']),
        '--user','projection_runtime','--operators',str(operators_path), '--ghcn-database',str(baseline.database),
        '--ghcn-manifest',str(baseline.manifest),'--ghcn-database-sha256',baseline.database_sha256,
        '--ghcn-manifest-sha256',baseline.manifest_sha256]
    def consume(command_id):
        child=subprocess.run([sys.executable,'-m','src.commands.preview_worker',*args,'--command-id',command_id],
            env=clean_environment(),capture_output=True,text=True,timeout=60)
        assert child.returncode==0, child.stdout+child.stderr
        return json.loads(child.stdout)['result']
    yield dict(client=client,authority=authority,owner=owner,initial=initial,params=params,operators=operators,
               consume=consume,source=source_bytes,server=server,port=server.server_port,args=args)
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def retained(case):
    source=case['source']
    run_id=str(uuid4())
    case['client'].capture(run_id,source['baseline'],source['responses'],producer_revision=BASE,
        source_now=source['now'],started_at=source['started_at'],completed_at=source['completed_at'])
    return run_id


def enroll(case,run_id):
    return case['client'].enroll(run_id)['command_id']


def prepared_request(case,run_id):
    script='''import json,sys
from src.commands.postgres_authority import PostgresCommandAuthority
from src.orchestrator.ghcn_source_result_client import GhcnSourceResultClient
x=json.loads(sys.argv[1]); a=PostgresCommandAuthority(**x['options'])
c=GhcnSourceResultClient(a.projections,x['endpoint'],x['origin'],'editor','invented-editor')
from src.storage.ghcn_runtime_inputs import Baseline
from pathlib import Path
b=x['baseline']; baseline=Baseline(Path(b['database']),Path(b['manifest']),b['database_sha256'],b['manifest_sha256'])
print(json.dumps(c.prepare_request(x['run'],x['selection'],baseline=baseline)))'''
    payload=dict(options=options(case['params']),endpoint=case['client'].endpoint,origin=ORIGIN,run=run_id,
        selection=dict(station_id='USW00000000',signal_date=str(case['source']['day']),signal_field='all_time_high'),
        baseline={k:str(v) for k,v in vars(case['source']['baseline']).items()})
    child=subprocess.run([sys.executable,'-c',script,json.dumps(payload)],env=clean_environment(),capture_output=True,text=True,timeout=60)
    assert child.returncode==0, child.stdout+child.stderr
    request=json.loads(child.stdout)
    return request


def test_real_http_capture_separate_consumer_atomic_history_and_writer_request(configured,record_property):
    case=configured
    run_id=retained(case)
    assert case['authority'].read()==(0,case['initial'])
    command_id=enroll(case,run_id)
    result=case['consume'](command_id)
    assert result['status']=='applied', result
    assert result['source_run']['changed_draft_ids']==[case['initial']['drafts'][0]['id']]
    version,state=case['authority'].read()
    assert version==1 and state['unowned']==case['initial']['unowned']
    assert state['drafts'][0]['text']==case['initial']['drafts'][0]['text']
    assert state['drafts'][0]['status']=='pending' and 'approval_binding' not in state['drafts'][0]
    assert state['drafts'][0]['revision_history'][0]['draft_snapshot']==case['initial']['drafts'][0]
    assert state['source_health']['other']==case['initial']['source_health']['other']
    assert case['consume'](command_id)==result
    assert case['authority'].read()==(version,state)
    request=prepared_request(case,run_id)
    record_property('invented_writer_identity',json.dumps(request,sort_keys=True))
    assert request['writer_request'] and request['provider_transport']=='not_attempted' and request['paid_grant'] is None
    assert request['draft_saved'] is False and request['callback_enrollment']=='not_supported'
    assert len(request['source_prepass']['retained_bundle_keys'])==6
    assert case['authority'].read()==(version,state)


def test_two_consumers_single_result_and_second_command_idempotency(configured):
    case=configured
    run_id=retained(case)
    identity=enroll(case,run_id)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results=list(workers.map(lambda _:case['authority'].consume(case['operators'].resolve,command_id=identity),range(2)))
    assert results[0]==results[1] and results[0]['status']=='applied'
    before=case['authority'].read()
    second=enroll(case,run_id)
    result=case['consume'](second)
    assert result['status']=='unchanged' and result['source_run']['reused'] is True
    assert case['authority'].read()==before


@pytest.mark.parametrize('fault', ['rejection', 'retained_approval'])
def test_verified_source_transition_fault_rolls_back_domain_and_state(configured, monkeypatch, fault):
    """CI only: the real source replay does not grant arbitrary draft mutations."""
    case = configured
    run_id = retained(case)
    identity = enroll(case, run_id)
    before = case['authority'].read()
    original = domain.prepare

    def escaping(*args, **kwargs):
        transition = original(*args, **kwargs)
        affected = transition.state['drafts'][0]
        assert affected['id'] in transition.outcome['changed_draft_ids']
        assert affected['status'] == 'pending'
        if fault == 'rejection':
            affected['status'] = 'rejected'
        else:
            affected['approval_binding'] = deepcopy(before[1]['drafts'][0]['approval_binding'])
        return transition

    monkeypatch.setattr(domain, 'prepare', escaping)
    with pytest.raises(RuntimeError, match='transition_not_allowed'):
        case['authority'].consume(case['operators'].resolve, command_id=identity)
    assert case['authority'].read() == before
    assert case['authority'].result(identity) is None
    with case['authority'].projections._connection() as connection:
        assert shared.optional(connection, inputs.RESULT, 'run:' + run_id) is None
    monkeypatch.setattr(domain, 'prepare', original)
    result = case['authority'].consume(case['operators'].resolve, command_id=identity)
    assert result['status'] == 'applied'
    affected = case['authority'].read()[1]['drafts'][0]
    assert affected['status'] == 'pending' and 'approval_binding' not in affected
    assert affected['text'] == before[1]['drafts'][0]['text']


def test_real_edit_during_acquisition_rejects_stale_effects(configured):
    case=configured
    run_id=retained(case)
    edit=body(case['initial']['drafts'][0])
    status,_,_=http(case['port'],'/commands',method='POST',value=edit)
    assert status==202
    assert case['consume'](edit['command_id'])['status']=='applied'
    before=case['authority'].read()
    result=case['consume'](enroll(case,run_id))
    assert result['status']=='rejected' and result['code']=='ghcn_dependency_conflict'
    assert case['authority'].read()==before
    assert case['client'].readback(run_id)['status']=='retained'


@pytest.mark.parametrize('where',['auth','expired','delayed_final','policy'])
def test_authorization_and_deadline_refusals_preserve_state(configured,monkeypatch,where):
    case=configured
    run_id=retained(case)
    identity=enroll(case,run_id)
    before=case['authority'].read()
    resolver=case['operators'].resolve
    if where=='auth':
        original=resolver('local-editor')
        def resolver(_):
            return Principal(original.subject,original.role,'different-session')
    elif where=='expired':
        monkeypatch.setattr('src.commands.postgres_authority._clock',lambda _:datetime.now(UTC)+timedelta(minutes=11))
    elif where=='policy':
        original=domain.current_editorial_policy()
        monkeypatch.setattr(domain,'current_editorial_policy',lambda:dict(original,flags={}))
    else:
        monkeypatch.setattr(shared,'completion_clock',lambda:datetime.now(UTC)+timedelta(minutes=11))
    result=case['authority'].consume(resolver,command_id=identity)
    assert result['status']=='rejected',result
    assert case['authority'].read()==before


@pytest.mark.parametrize('forgery',['effects','supply','dependency'])
def test_independent_consumer_refuses_well_shaped_caller_forgery(configured,forgery):
    case=configured
    original=retained(case)
    _,value=case['authority'].projections.read(inputs.INPUT,'run:'+original)
    _,deps=case['authority'].projections.read(inputs.DEPENDENCIES,'run:'+original)
    _,bundles,countries,envelope=ScientificSupplySession(case['authority'].projections,original,'replay').read()
    identity=str(uuid4())
    if forgery=='effects':
        value['effects'][0]['source_revision']='a'*64
        value['effects_sha256']=digest(value['effects'])
    elif forgery=='supply':
        bundles=[]
    else:
        deps['state']['targets'][0]['text']='Forged dependency text'
    dep=shared.retain_exact(case['authority'].projections,inputs.DEPENDENCIES,'run:'+identity,deps)
    metrics={**envelope['source_outcome']['counters'],**envelope['source_outcome']}
    supply=ScientificSupplySession(case['authority'].projections,identity,'capture',value['acquisition_started_at'],BASE)
    receipt,*_=supply.capture(bundles,countries,metrics)
    value.update(supply_run_id=identity,dependency_sha256=dep.canonical_sha256,supply_sha256=receipt.canonical_sha256)
    shared.retain_exact(case['authority'].projections,inputs.INPUT,'run:'+identity,value)
    before=case['authority'].read()
    result=case['consume'](enroll(case,identity))
    assert result['status']=='rejected',result
    assert case['authority'].read()==before


def test_viewer_and_origin_refused_before_capture(configured):
    case=configured
    assert http(case['port'],'/ghcn-source-context',role='viewer')[0]==403
    assert http(case['port'],'/ghcn-source-context',headers={'Origin':'http://127.0.0.1:9'})[0]==403
    assert case['authority'].read()==(0,case['initial'])


def test_late_clock_after_state_write_rolls_back_and_leaves_accepted_pending(configured,monkeypatch):
    case=configured
    identity=enroll(case,retained(case))
    before=case['authority'].read()
    original=shared.final_clock
    calls=[]
    def late(command,previous):
        calls.append(1)
        if len(calls)==3:
            raise ValueError('invented late expiry after state projection')
        return original(command,previous)
    monkeypatch.setattr(shared,'final_clock',late)
    with pytest.raises(ValueError,match='invented late expiry'):
        case['authority'].consume(case['operators'].resolve,command_id=identity)
    assert len(calls)==3 and case['authority'].read()==before and case['authority'].result(identity) is None
    monkeypatch.setattr(shared,'final_clock',original)
    assert case['consume'](identity)['status']=='applied'


@pytest.mark.parametrize('namespace',[inputs.RESULT,'command-authority-state-v1'])
def test_failure_after_domain_or_state_write_rolls_back_exactly(configured,monkeypatch,namespace):
    case=configured
    identity=enroll(case,retained(case))
    before=case['authority'].read()
    from src.commands.postgres_authority import NAMESPACE as state_namespace
    if namespace=='command-authority-state-v1':
        namespace=state_namespace
    original=case['authority'].projections._record
    def failed(c,ns,*args):
        value=original(c,ns,*args)
        if ns==namespace:
            raise RuntimeError('invented post-write loss')
        return value
    monkeypatch.setattr(case['authority'].projections,'_record',failed)
    with pytest.raises(RuntimeError,match='post-write loss'):
        case['authority'].consume(case['operators'].resolve,command_id=identity)
    assert case['authority'].read()==before and case['authority'].result(identity) is None


def test_same_context_two_runs_second_cannot_reapply_old_history(configured):
    case=configured
    first=retained(case)
    second=retained(case)
    assert case['consume'](enroll(case,first))['status']=='applied'
    before=case['authority'].read()
    result=case['consume'](enroll(case,second))
    assert result['status']=='rejected' and result['code']=='ghcn_dependency_conflict'
    assert case['authority'].read()==before


def test_source_replay_never_calls_legacy_mutable_baseline_reader(configured,monkeypatch):
    case=configured
    run_id=retained(case)
    def forbidden(*args,**kwargs):
        raise AssertionError('Mutable baseline opened')
    monkeypatch.setattr(inputs.ghcn,'open_db',forbidden)
    result=case['authority'].consume(case['operators'].resolve,command_id=enroll(case,run_id))
    assert result['status']=='applied'


def test_populated_delivery_catalog_and_unrelated_intents_do_not_fake_absence(configured):
    case=configured
    case['owner'].initialize_media_staging()
    case['owner'].initialize_delivery(now=datetime.now(UTC))
    context=case['client'].context()
    assert context['delivery']['catalog'] is not None and context['delivery']['protection_codes']==[]
    assert context['delivery']['rows']=={key:[] for key in domain.TABLE_COLUMNS}
    run_id=retained(case)
    assert case['consume'](enroll(case,run_id))['status']=='applied'


def test_delivery_catalog_install_during_replay_changes_dependency_without_state_version(configured):
    case=configured
    run_id=retained(case)
    case['owner'].initialize_media_staging()
    case['owner'].initialize_delivery(now=datetime.now(UTC))
    before=case['authority'].read()
    result=case['consume'](enroll(case,run_id))
    assert result['status']=='rejected' and result['code']=='ghcn_dependency_conflict'
    assert before==(0,case['initial']) and case['authority'].read()==before


def test_lost_http_accept_ack_resumes_frozen_request_without_source_reacquisition(configured, monkeypatch):
    case=configured
    run_id=retained(case)
    identity=str(uuid4())
    original=GhcnSourceResultClient.http
    sent=[]
    def lost(self,path,*,body=None):
        result=original(self,path,body=body)
        if body is not None:
            sent.append(deepcopy(body))
            raise TimeoutError('invented lost acceptance acknowledgment')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(GhcnSourceResultClient,'http',lost)
        with pytest.raises(TimeoutError,match='lost acceptance'):
            case['client'].enroll(run_id,command_id=identity)
    _,descriptor=case['authority'].projections.read(inputs.SUBMISSION,identity)
    assert sent==[descriptor['request']]
    assert case['client'].resume(identity)['command_id']==identity
    assert len(sent)==1 and case['consume'](identity)['status']=='applied'
    before=case['authority'].read()
    recovered=case['client'].resume(identity)['command']
    assert recovered['status']=='completed' and recovered['result']['status']=='applied'
    assert case['authority'].read()==before


def test_restore_fresh_cluster_preserves_raw_source_effects_and_pending_descriptor(configured,cluster,tmp_path,monkeypatch):
    import psycopg
    import shutil
    import tempfile
    case=configured
    done_run=retained(case)
    done=enroll(case,done_run)
    result=case['consume'](done)
    original_request=prepared_request(case,done_run)
    pending_run=retained(case)
    pending=enroll(case,pending_run)
    unsubmitted_run=retained(case)
    unsubmitted=str(uuid4())
    with monkeypatch.context() as patch:
        patch.setattr(GhcnSourceResultClient,'resume',lambda self,identity:dict(command_id=identity))
        case['client'].enroll(unsubmitted_run,command_id=unsubmitted)
    _,tool,_=cluster
    params=case['params']
    with tempfile.TemporaryDirectory(prefix='theheat-ghcn-restore-',dir='/tmp') as directory:
        root=Path(directory)
        root.chmod(0o700)
        socket=root/'socket'
        socket.mkdir(mode=0o700)
        data,dump=root/'data',root/'invented.dump'
        tool('pg_dump','-h',params['host'],'-p',str(params['port']),'-U',params['user'],'-Fc','-f',dump,params['dbname'])
        tool('initdb','-D',data,'-U','projection_owner','--auth-local=trust','--auth-host=reject','--encoding=UTF8','--no-locale')
        try:
            tool('pg_ctl','-D',data,'-l',root/'server.log','-o',f"-c listen_addresses='' -k {socket} -p 55477",'-w','start')
            with psycopg.connect(host=str(socket),port=55477,user='projection_owner',dbname='postgres',autocommit=True) as c:
                c.execute('CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT')
                c.execute('CREATE DATABASE restored_ghcn TEMPLATE template0')
            tool('pg_restore','-h',socket,'-p','55477','-U','projection_owner','-d','restored_ghcn','--exit-on-error','--single-transaction',dump)
            original_baseline=case['source']['baseline']
            database_path,manifest_path=root/'invented.sqlite',root/'invented.version'
            shutil.copyfile(original_baseline.database,database_path)
            shutil.copyfile(original_baseline.manifest,manifest_path)
            baseline=inputs.Baseline(database_path,manifest_path,original_baseline.database_sha256,original_baseline.manifest_sha256)
            authority=PostgresCommandAuthority(socket_directory=socket,port=55477,database='restored_ghcn',user='projection_runtime')
            authority.configure_ghcn_source_results(baseline)
            assert authority.read()==case['authority'].read() and authority.result(done)==result and authority.result(pending) is None
            for run_id in (done_run,pending_run,unsubmitted_run):
                for namespace in (NAMESPACE,inputs.INPUT,inputs.DEPENDENCIES):
                    assert authority.projections.read(namespace,'run:'+run_id)==case['authority'].projections.read(namespace,'run:'+run_id)
                _,value=authority.projections.read(inputs.INPUT,'run:'+run_id)
                for response in value['responses']:
                    if response['raw_sha256']:
                        assert authority.projections.read(inputs.RAW,response['raw_sha256'])==case['authority'].projections.read(inputs.RAW,response['raw_sha256'])
            for identity in (done,pending,unsubmitted):
                assert authority.projections.read(inputs.SUBMISSION,identity)==case['authority'].projections.read(inputs.SUBMISSION,identity)
            assert authority.projections.read(inputs.RESULT,'run:'+done_run)==case['authority'].projections.read(inputs.RESULT,'run:'+done_run)
            server=PreviewServer(authority,case['operators'],port=0,origin=ORIGIN)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                script='''import json,sys
from src.commands.postgres_authority import PostgresCommandAuthority
from src.orchestrator.ghcn_source_result_client import GhcnSourceResultClient
x=json.loads(sys.argv[1]); a=PostgresCommandAuthority(socket_directory=x['socket'],port=55477,database='restored_ghcn',user='projection_runtime')
c=GhcnSourceResultClient(a.projections,x['endpoint'],x['origin'],'editor','invented-editor')
print(json.dumps(c.resume(x['command_id'])))'''
                restored_case={**case,'authority':authority,
                    'client':GhcnSourceResultClient(authority.projections,f'http://127.0.0.1:{server.server_port}',ORIGIN,'editor','invented-editor'),
                    'params':dict(host=str(socket),port=55477,dbname='restored_ghcn'),
                    'source':{**case['source'],'baseline':baseline}}
                assert prepared_request(restored_case,done_run)==original_request
                for identity in (pending,unsubmitted):
                    child=subprocess.run([sys.executable,'-c',script,json.dumps(dict(socket=str(socket),endpoint=f'http://127.0.0.1:{server.server_port}',origin=ORIGIN,command_id=identity))],env=clean_environment(),capture_output=True,text=True,timeout=30)
                    assert child.returncode==0,child.stdout+child.stderr
                    assert json.loads(child.stdout)['command_id']==identity
                # Restoring PG alone never invents a baseline or reacquires data.
                database_path.rename(root/'withheld.sqlite')
                before=authority.read()
                with pytest.raises((ValueError,FileNotFoundError)):
                    authority.consume(case['operators'].resolve,command_id=pending)
                assert authority.read()==before and authority.result(pending) is None
                (root/'withheld.sqlite').rename(database_path)
                applied=authority.consume(case['operators'].resolve,command_id=pending)
                assert applied['status']=='applied' and authority.consume(case['operators'].resolve,command_id=pending)==applied
                # Replaying already-applied scientific revisions is a no-op. Only
                # each distinct run's telemetry/result advances; no history row
                # or draft revision may be counted a second time.
                second=authority.consume(case['operators'].resolve,command_id=unsubmitted)
                assert second['status']=='applied'
                assert authority.read()[1]['temperature_history']==before[1]['temperature_history']
                assert authority.read()[1]['drafts']==before[1]['drafts']
                assert authority.read()[0]==before[0]+2
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            if (data/'postmaster.pid').exists():
                tool('pg_ctl','-D',data,'-w','stop','-m','fast')


def test_actual_state_lock_delay_rechecks_expiry_before_source_effects(configured,monkeypatch):
    case=configured
    identity=enroll(case,retained(case))
    before=case['authority'].read()
    original=domain.preflight
    prepared=threading.Event()
    expired=threading.Event()
    def preflight(*args):
        value=original(*args)
        prepared.set()
        return value
    monkeypatch.setattr(domain,'preflight',preflight)
    monkeypatch.setattr('src.commands.postgres_authority._clock',lambda _:datetime.now(UTC)+timedelta(minutes=11 if expired.is_set() else 0))
    with ThreadPoolExecutor(max_workers=1) as workers:
        with case['authority'].projections._connection(writing=True) as connection:
            case['authority']._state(connection,lock=True)
            future=workers.submit(case['authority'].consume,case['operators'].resolve,command_id=identity)
            assert prepared.wait(timeout=20)
            assert not future.done()
            expired.set()
        result=future.result(timeout=30)
    assert result['status']=='rejected' and case['authority'].read()==before


def test_applied_dual_source_resolution_all_nine_views_and_tamper_refusal(configured,record_property):
    from tests.test_ghcn_source_result_producer import dual_source
    from src.two_bot import ghcn_claim_view as claim
    case=configured
    case['source']=dual_source(case['source'])
    run_id=retained(case)
    assert case['consume'](enroll(case,run_id))['status']=='applied'
    original_state=case['authority'].read()
    for field in claim.TYPES:
        selection=dict(station_id='USW00000000',signal_date=str(case['source']['day']),signal_field=field)
        resolved=claim.resolve(case['authority'],run_id,selection)
        record_property('invented_claim_'+field,json.dumps(dict(reference=resolved.reference,
            full_sha256=resolved.full_sha256,view_sha256=resolved.view_sha256,counters=resolved.counters),sort_keys=True))
        captured=claim.json_tree(resolved.view.to_dict())
        repeated=claim.resolve(case['authority'],run_id,selection)
        assert repeated.reference==resolved.reference and repeated.full_sha256==resolved.full_sha256 and repeated.view_sha256==resolved.view_sha256
        assert repeated.verify_saved(captured).to_dict()==resolved.view.to_dict()
        assert resolved.counters['view_bytes']<=32768<resolved.counters['full_story_bytes']
        assert resolved.counters['calendar_counts']=={'temperature_2m_max':366,'temperature_2m_min':366}
        for target in ('value','source','selection','limit'):
            changed=deepcopy(captured)
            if target=='value':
                changed['headline_metric']['value']+=1
            elif target=='source':
                changed['raw_signal_dump']['ghcn_claim_view']['scientific_supply']['sha256']='a'*64
            elif target=='selection':
                changed['raw_signal_dump']['ghcn_claim_view']['selection']['signal_field']='calendar_date_low'
                if field=='calendar_date_low':
                    changed['raw_signal_dump']['ghcn_claim_view']['selection']['signal_field']='calendar_date_high'
            else:
                changed['current_facts'][-1]['value']='Invented unrestricted claim.'
            with pytest.raises(ValueError,match='ghcn_claim_view_changed'):
                repeated.verify_saved(changed)
    assert case['authority'].read()==original_state


@pytest.mark.parametrize('mutation',['unselected_calendar','qc','source_hash','timestamp','selection','not_applied','missing_raw'])
def test_claim_resolver_rejects_changed_retained_source_before_writer(configured,monkeypatch,mutation):
    from src.two_bot import ghcn_claim_view as claim
    from src.storage import postgres_projection as p
    case=configured
    run_id=retained(case)
    command_id=enroll(case,run_id)
    assert case['consume'](command_id)['status']=='applied'
    selection=dict(station_id='USW00000000',signal_date=str(case['source']['day']),signal_field='all_time_high')
    original=domain.read_input
    def altered(*args,**kwargs):
        receipt,value,deps,bundles,countries,envelope=original(*args,**kwargs)
        if mutation=='unselected_calendar':
            # A changed cell outside the visible selected comparison remains
            # in the full source equality, not omitted by the compact identity.
            envelope['bundles'][0]['evidence']['baseline']['variables']['temperature_2m_max']['calendar_samples']['01-01']+=1
        elif mutation=='qc':
            value['responses'][0]['raw_sha256']='a'*64
        elif mutation=='source_hash':
            value['baseline']['database_sha256']='a'*64
        elif mutation=='timestamp':
            value['source_now']='2001-01-01T00:00:00Z'
        return receipt,value,deps,bundles,countries,envelope
    monkeypatch.setattr(domain,'read_input',altered)
    if mutation=='selection':
        selection['station_id']='USW99999999'
    elif mutation=='not_applied':
        monkeypatch.setattr(case['authority'],'_result',lambda *args:None)
    elif mutation=='missing_raw':
        original_read=p.PostgresProjectionRepository._read
        def unavailable(c,ns,key):
            if ns==inputs.RAW:
                raise p.ProjectionError('invented missing restored raw row')
            return original_read(c,ns,key)
        monkeypatch.setattr(p.PostgresProjectionRepository,'_read',staticmethod(unavailable))
    with pytest.raises((ValueError,p.ProjectionError)):
        claim.resolve(case['authority'],run_id,selection)
    assert case['authority'].result(command_id) is None if mutation=='not_applied' else case['authority'].result(command_id)['status']=='applied'


def test_expanded_input_refusal_retains_acknowledged_raw_without_state_promotion(configured,monkeypatch):
    import hashlib
    case=configured
    identity=str(uuid4())
    monkeypatch.setattr(inputs,'MAX_EXPANDED',100)
    source=case['source']
    with pytest.raises(ValueError,match='expansion_capacity'):
        case['client'].capture(identity,source['baseline'],source['responses'],producer_revision=BASE,
            source_now=source['now'],started_at=source['started_at'],completed_at=source['completed_at'])
    original=source['responses'][0].raw
    _,raw=case['authority'].projections.read(inputs.RAW,hashlib.sha256(original).hexdigest())
    import base64
    assert base64.b64decode(raw['payload'])==original
    assert case['authority'].read()==(0,case['initial'])
    with case['authority'].projections._connection() as connection:
        assert shared.optional(connection,inputs.INPUT,'run:'+identity) is None
        assert shared.optional(connection,inputs.RESULT,'run:'+identity) is None


def test_missing_current_archive_preserves_original_unverified_claim_and_raw(configured):
    case=configured
    responses=case['source']['responses']
    case['source']['responses']=[inputs.InventedResponse(r.kind,r.key,r.retrieved_at,None,'failed')
        if r.kind=='station_archive' and r.key=='USW00000000' else r for r in responses]
    run_id=retained(case)
    result=case['consume'](enroll(case,run_id))
    assert result['status']=='applied'
    state=case['authority'].read()[1]
    assert state['drafts']==case['initial']['drafts']
    findings=[row for row in state['temperature_history'].values() if row.get('kind')=='affected_claim']
    assert any(row['reason']=='current_archive_unverified' for row in findings)
    _,value=case['authority'].projections.read(inputs.INPUT,'run:'+run_id)
    assert any(row['kind']=='station_archive' and row['key']=='USW00000000' and row['status']=='failed' for row in value['responses'])


def test_monotonic_replay_budget_cannot_be_extended_by_waiting_for_state_lock(configured,monkeypatch):
    from dataclasses import replace
    case=configured
    identity=enroll(case,retained(case))
    original=domain.preflight
    def expired(*args):
        result=original(*args)
        return replace(result,valid_until=0.0)
    monkeypatch.setattr(domain,'preflight',expired)
    before=case['authority'].read()
    result=case['authority'].consume(case['operators'].resolve,command_id=identity)
    assert result['status']=='rejected' and result['code']=='ghcn_preparation_expired'
    assert case['authority'].read()==before


@pytest.mark.parametrize('drift',['edit','expiry','role'])
def test_writer_preparation_rechecks_currentness_after_complete_resolution(configured,drift):
    case=configured
    run_id=retained(case)
    assert case['consume'](enroll(case,run_id))['status']=='applied'
    script='''import json,sys
from datetime import UTC,datetime,timedelta
from pathlib import Path
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import Operators
from src.storage.ghcn_runtime_inputs import Baseline
from src.orchestrator import ghcn_source_result_client as client_module
from src.two_bot import ghcn_claim_view as claim
from tests.test_postgres_preview_command_ingress import body
x=json.loads(sys.argv[1]); a=PostgresCommandAuthority(**x['options'])
b=x['baseline']; baseline=Baseline(Path(b['database']),Path(b['manifest']),b['database_sha256'],b['manifest_sha256'])
a.configure_ghcn_source_results(baseline)
c=client_module.GhcnSourceResultClient(a.projections,x['endpoint'],x['origin'],'editor','invented-editor')
original=claim.resolve
def changed(*args):
    result=original(*args)
    if x['drift']=='edit':
        request=body(a.read()[1]['drafts'][0]); code,_=c.http('/commands',body=request); assert code==202
        assert a.consume(Operators(x['operators']).resolve,command_id=request['command_id'])['status']=='applied'
    elif x['drift']=='expiry':
        client_module.utc_now=lambda:datetime.now(UTC)+timedelta(minutes=11)
    else:
        path=Path(x['operators']); rows=json.loads(path.read_text())
        for row in rows['operators']:
            if row['username']=='editor':row['role']='viewer'
        path.write_text(json.dumps(rows))
    return result
claim.resolve=changed
try:c.prepare_request(x['run'],x['selection'],baseline=baseline)
except ValueError as exc:print(json.dumps(dict(refusal=str(exc))))
else:raise AssertionError('stale request escaped')'''
    payload=dict(options=options(case['params']),endpoint=case['client'].endpoint,origin=ORIGIN,run=run_id,
        drift=drift,operators=str(case['operators'].path),selection=dict(station_id='USW00000000',
        signal_date=str(case['source']['day']),signal_field='all_time_high'),
        baseline={k:str(v) for k,v in vars(case['source']['baseline']).items()})
    child=subprocess.run([sys.executable,'-c',script,json.dumps(payload)],env=clean_environment(),capture_output=True,text=True,timeout=60)
    assert child.returncode==0,child.stdout+child.stderr
    assert json.loads(child.stdout)['refusal']=={'edit':'ghcn_authority_changed','expiry':'ghcn_preparation_stale','role':'ghcn_context_unavailable'}[drift]
