"""Invented AWC source through the actual Gist handlers and manual image sender.
Only source HTTP, persistence, model and X/GitHub transports are explicit fixtures.
No hosted case, live source, paid call or public post is executed.
"""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from freezegun import freeze_time
import pytest

from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial import revisions
from src.editorial.policy import current_editorial_policy
from src.state import DEFAULT_STATE
from tests.gist_media_helpers import install_fake_x
from tests.test_awc_observed import install
from tests.test_gist_hazard_journey import ROUTE_JOURNEY, node_binary

ROOT = Path(__file__).resolve().parents[1]


def _approved_awc_route(tmp_path, monkeypatch):
    reads = install(monkeypatch)  # actual source parser/independent history gate, invented wire bytes
    policy = current_editorial_policy()
    out = tmp_path / "invented-awc-route.json"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "LC_ALL": "C", "LANG": "C",
           "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*", "THEHEAT_TEST_PYTHON": sys.executable}
    run = subprocess.run([node_binary(), "--input-type=module", "-e", ROUTE_JOURNEY, "awc", str(out), json.dumps(policy)],
                         cwd=ROOT / "dashboard", env=env, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-4000:]
    route = json.loads(out.read_text())
    return reads, policy, route


def test_awc_actual_handlers_sender_restored_history_and_no_resend(tmp_path, monkeypatch):
    reads, policy, route = _approved_awc_route(tmp_path, monkeypatch)
    assert route["browser_ok"] is True
    assert [(s["name"], s["status"]) for s in route["steps"]] == [
        ("attach", 200), ("attach_repeat", 200), ("text_only_review", 409), ("joint_review", 200),
        ("auto_approve", 409), ("approve", 200)]
    assert route["steps"][1]["revision_unchanged"] is True
    assert route["steps"][3]["review_kind"] == "human_media"
    assert len(route["dispatches"]) == 1 and route["dispatches"][0]["inputs"]["mode"] == "manual_tweet"
    assert "png_base64" not in route["raw_state"] and "iVBORw0KGgo" not in route["raw_state"]
    saved = json.loads(route["raw_state"])
    state = {**deepcopy(DEFAULT_STATE), **saved}
    draft = next(d for d in state["drafts"] if d["id"] == route["primary"])
    assert revisions.review_is_current(draft, policy=policy)
    assert revisions.approval_is_current(draft, "manual", policy=policy)
    bundle = deepcopy(draft["review_context"]["two_bot"]["bundle"])
    preview = route["preview"]
    png = base64.b64decode(preview["png_base64"])
    assert hashlib.sha256(png).hexdigest() == draft["media_attachment"]["image"]["png_sha256"]
    fake = install_fake_x(monkeypatch)
    inputs = route["dispatches"][0]["inputs"]
    for name, key in (("DRAFT_ID", "draft_id"), ("TWEET_TEXT", "tweet_text"), ("PUBLISH_INTENT_ID", "publish_intent_id")):
        monkeypatch.setenv(name, inputs[key])
    sent_at = datetime.fromtimestamp(route["clock"] / 1000, timezone.utc)
    with freeze_time(sent_at):
        fake.posting.run_manual_tweet(state)
    assert [call[0] for call in fake.calls] == ["upload", "alt", "create"]
    assert fake.calls[0][1] == png and fake.calls[1][2] == preview["delivery_text"]
    assert fake.calls[2] == ("create", draft["text"], {"media_ids": ["98765"]})
    assert fake.safety.call_count == 1  # final manual-send gate, not four fresh generation checks
    assert reads, "the independent live-source path must have read the invented HTTP fixture"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert draft["status"] == "posted"
    restored = json.loads(json.dumps(state, ensure_ascii=False))
    with freeze_time(sent_at):
        fake.posting.run_manual_tweet(restored)
    assert len(fake.calls) == 3
    manifest = json.loads((ROOT / "dashboard/lib/graphic-runtime-manifest.json").read_text())
    current = next(d for d in restored["drafts"] if d["id"] == draft["id"])
    request = {"draft_id": draft["id"], "expected_revision": {**revisions.draft_identity(current),
               "decision_revision": revisions.decision_revision(current)}, "format": "png", "delivered": True,
               "expected_policy_source_sha256": manifest["identity"]["policy_source_sha256"],
               "expected_preview_runtime_sha256": manifest["runtime_sha256"]}
    result = json.loads(build_preview(request, policy_sha=manifest["identity"]["policy_source_sha256"],
                        runtime_sha=manifest["runtime_sha256"], read_state=lambda: restored, budget=Budget()))
    assert result["schema_version"] == 6 and result["media_kind"] == "gist_awc_observed_pair_v1"
    assert base64.b64decode(result["png_base64"]) == png
    assert result["delivery_text"] == preview["delivery_text"]
    assert result["publication_approved"] is False and result["attachment"] is False
    assert current["review_context"]["two_bot"]["bundle"] == bundle


def test_awc_png_uses_only_verified_sealed_source_and_embedded_country_registry(tmp_path, monkeypatch):
    from src.data import awc_observed
    from src.media import gist_media
    from tests.test_awc_observed import NOW
    from tests.test_graphic_runtime_resources import app, fresh
    install(monkeypatch)
    bundle = awc_observed.build_bundle(awc_observed.nominate(now=NOW), now=NOW).to_dict()
    expected = gist_media.prepare_media(bundle)
    packet = tmp_path / 'invented-awc-bundle.json'
    packet.write_text(json.dumps(bundle))
    result = fresh('''
import runpy
from pathlib import Path
from hashlib import sha256
loaded=runpy.run_path(sys.argv[1])
assert loaded['PreviewHandler'] is not loaded['UnavailableHandler']
from src.media import gist_media
b=json.loads(Path(sys.argv[2]).read_text())
p=gist_media.prepare_media(b)
print(json.dumps({'sha':sha256(p['png']).hexdigest(),'alt':p['delivery_text'],'kind':p['kind'],
 'sources':[str(getattr(m,'__file__','')) for n,m in sys.modules.items() if n=='src' or n.startswith('src.')]}))
''', app(tmp_path), packet)
    assert result['kind'] == 'gist_awc_observed_pair_v1'
    assert result['sha'] == hashlib.sha256(expected['png']).hexdigest()
    assert result['alt'] == expected['delivery_text']
    assert result['sources'] and all(path.startswith(str(tmp_path / 'graphic-runtime.zip') + '/')
                                     for path in result['sources'])


def test_awc_authenticated_http_png_runs_from_sealed_runtime_only(tmp_path, monkeypatch):
    from src.media import gist_media
    from tests.gist_hazard_helpers import saved_state
    from tests.test_graphic_runtime_resources import app
    install(monkeypatch)
    state = saved_state('awc')
    draft = state['drafts'][0]
    expected = gist_media.prepare_media(draft['review_context']['two_bot']['bundle'])
    manifest = json.loads((ROOT / 'dashboard/lib/graphic-runtime-manifest.json').read_text())
    request = {'draft_id': draft['id'], 'expected_revision': {**revisions.draft_identity(draft),
               'decision_revision': revisions.decision_revision(draft)}, 'format': 'png',
               'expected_policy_source_sha256': manifest['identity']['policy_source_sha256'],
               'expected_preview_runtime_sha256': manifest['runtime_sha256']}
    packet = tmp_path / 'invented-awc-http.json'
    packet.write_text(json.dumps({'state': state, 'request': request}))
    code = r'''
import base64, hashlib, http.client, io, json, os, runpy, socket, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from freezegun import freeze_time
connect, resolve=socket.socket.connect, socket.getaddrinfo
connections=[]
def guarded_connect(self,address):
    if not isinstance(address,tuple) or address[0]!='127.0.0.1': raise AssertionError('external socket refused')
    connections.append(address[0]); return connect(self,address)
def guarded_resolve(host,*args,**kwargs):
    if host!='127.0.0.1': raise AssertionError('external DNS refused')
    return resolve(host,*args,**kwargs)
socket.socket.connect=guarded_connect;socket.getaddrinfo=guarded_resolve
loaded=runpy.run_path(sys.argv[1])
assert loaded['PreviewHandler'] is not loaded['UnavailableHandler']
from src.dashboard_preview import reader
value=json.loads(Path(sys.argv[2]).read_text());reads=[]
gist_id='ab'*20
class Response:
    status_code=200
    def __init__(self):
        self.raw=io.BytesIO(json.dumps({'id':gist_id,'files':{'state.json':{'filename':'state.json',
            'truncated':False,'content':json.dumps(value['state'])}}}).encode())
    def __enter__(self): return self
    def __exit__(self,*args): self.raw.close()
class Session:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def get(self,url,**options):
        assert url=='https://api.github.com/gists/'+gist_id
        assert options['allow_redirects'] is False and options['stream'] is True
        assert options['headers']['Authorization']=='token invented-sealed-http-token'
        reads.append(url);return Response()
reader.requests.Session=Session  # sole invented Gist HTTP boundary, strict reader still runs
os.environ.update(THEHEAT_STATE_BACKEND='gist',GIST_ID=gist_id,GITHUB_TOKEN='invented-sealed-http-token',
                  DASHBOARD_USERNAME='fixture',DASHBOARD_PASSWORD='invented')
for k in ['VERCEL','VERCEL_ENV','VERCEL_URL','DASHBOARD_AUTH_DISABLED','THEHEAT_DB_PATH']:
    os.environ.pop(k,None)
server=ThreadingHTTPServer(('127.0.0.1',0),loaded['PreviewHandler'])
worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
def call(headers):
    c=http.client.HTTPConnection(*server.server_address,timeout=5)
    c.request('POST','/api/graphic_preview',body=json.dumps(value['request']).encode(),
              headers={'Content-Type':'application/json',**headers})
    r=c.getresponse();status=r.status;body=r.read();cache=r.getheader('Cache-Control');c.close()
    assert cache=='private, no-store';return status,json.loads(body)
try:
    unauth,_=call({});assert unauth==401 and reads==[]
    auth='Basic '+base64.b64encode(b'fixture:invented').decode()
    foreign,_=call({'Authorization':auth,'Origin':'https://invented-other.invalid'})
    assert foreign==403 and reads==[]
    with freeze_time('2026-11-15T12:10:00Z'):
        status,result=call({'Authorization':auth,'Origin':'http://127.0.0.1:'+str(server.server_port)})
    assert status==200 and result['media_kind']=='gist_awc_observed_pair_v1',result
    assert result['source_context']['kind']=='awc_airport_pair' and len(result['source_context']['points'])==2
    print(json.dumps({'statuses':[unauth,foreign,status],'png_sha256':hashlib.sha256(base64.b64decode(result['png_base64'])).hexdigest(),
        'delivery_text':result['delivery_text'],'gist_fixture_reads':len(reads),'loopback_connections':len(connections),
        'sources':[str(getattr(m,'__file__','')) for n,m in sys.modules.items() if n=='src' or n.startswith('src.')]}))
finally:
    server.shutdown();server.server_close();worker.join(5);assert not worker.is_alive()
'''
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path), 'LC_ALL': 'C', 'LANG': 'C',
           'NO_PROXY': '*', 'no_proxy': '*', 'NETRC': '/dev/null'}
    run = subprocess.run([sys.executable, '-I', '-c', code, str(app(tmp_path)), str(packet)],
                         cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr[-4000:]
    result = json.loads(run.stdout)
    assert result['statuses'] == [401, 403, 200] and result['gist_fixture_reads'] >= 1
    assert result['png_sha256'] == hashlib.sha256(expected['png']).hexdigest()
    assert result['delivery_text'] == expected['delivery_text']
    assert result['sources'] and all(path.startswith(str(tmp_path / 'graphic-runtime.zip') + '/')
                                     for path in result['sources'])


def _dispatch_environment(monkeypatch, route):
    inputs = route['dispatches'][0]['inputs']
    for name, key in [('DRAFT_ID', 'draft_id'), ('TWEET_TEXT', 'tweet_text'), ('PUBLISH_INTENT_ID', 'publish_intent_id')]:
        monkeypatch.setenv(name, inputs[key])
    return datetime.fromtimestamp(route['clock'] / 1000, timezone.utc)


def test_awc_changed_primary_observation_refuses_before_intent_safety_or_upload(tmp_path, monkeypatch):
    from tests.test_awc_observed import history_xml, reports
    _, _, route = _approved_awc_route(tmp_path, monkeypatch)
    state = {**deepcopy(DEFAULT_STATE), **json.loads(route['raw_state'])}
    original = deepcopy(state['drafts'])
    changed = reports()
    changed[1][0] = 'TBBB 151200Z 00000KT CAVOK 44/20 Q1010'
    changed[1][5] = '44'
    install(monkeypatch, xml=history_xml(changed))
    fake = install_fake_x(monkeypatch)
    with freeze_time(_dispatch_environment(monkeypatch, route)):
        fake.posting.run_manual_tweet(state)
    assert fake.calls == [] and fake.persisted == [] and fake.safety.call_count == 0
    assert state['publish_ledger'] == {}
    primary = next(d for d in state['drafts'] if d['id'] == route['primary'])
    assert primary['status'] == 'pending'
    assert primary['review_context']['two_bot']['bundle'] == original[0]['review_context']['two_bot']['bundle']
    assert primary.get('approval') is None


@pytest.mark.parametrize('failure', ['create', 'empty_receipt'])
def test_awc_unknown_platform_outcome_never_resends_or_falls_back_to_text(tmp_path, monkeypatch, failure):
    _, _, route = _approved_awc_route(tmp_path, monkeypatch)
    state = {**deepcopy(DEFAULT_STATE), **json.loads(route['raw_state'])}
    fake = install_fake_x(monkeypatch)
    fake.failure = failure
    with freeze_time(_dispatch_environment(monkeypatch, route)):
        fake.posting.run_manual_tweet(state)
    assert [call[0] for call in fake.calls] == ['upload', 'alt', 'create']
    primary = next(d for d in state['drafts'] if d['id'] == route['primary'])
    assert state['publish_ledger'][primary['event_id']]['phase'] == 'unknown'
    assert primary['status'] != 'posted'
    restored = json.loads(json.dumps(state))
    with freeze_time(_dispatch_environment(monkeypatch, route)):
        fake.posting.run_manual_tweet(restored)
    assert len(fake.calls) == 3
    assert restored['publish_ledger'][primary['event_id']]['phase'] == 'unknown'


def test_awc_fractional_temperatures_and_coordinates_keep_python_js_binding(tmp_path, monkeypatch):
    from src.data import awc_observed
    from tests.gist_hazard_helpers import saved_state
    from tests.test_awc_observed import NOW, catalog, reports
    rows, stations = reports(), catalog()
    rows[0][0] = 'TAAA 151200Z M20/M25 RMK T12010250'
    rows[1][0] = 'TBBB 151200Z 45/20 RMK T04520200'
    rows[0][5], rows[1][5] = '-20.1', '45.2'
    rows[0][3], stations[0]['lat'] = '60.125', 60.125
    rows[1][3], stations[1]['lat'] = '-30.375', -30.375
    install(monkeypatch, rows=rows, stations=stations)
    bundle = awc_observed.build_bundle(awc_observed.nominate(now=NOW), now=NOW).to_dict()
    state = saved_state('awc', bundle=bundle)
    draft = state['drafts'][0]
    manifest = json.loads((ROOT / 'dashboard/lib/graphic-runtime-manifest.json').read_text())
    request = {'draft_id': draft['id'], 'expected_revision': {**revisions.draft_identity(draft),
               'decision_revision': revisions.decision_revision(draft)}, 'format': 'png',
               'expected_policy_source_sha256': manifest['identity']['policy_source_sha256'],
               'expected_preview_runtime_sha256': manifest['runtime_sha256']}
    with freeze_time(NOW):
        response = json.loads(build_preview(request, policy_sha=manifest['identity']['policy_source_sha256'],
            runtime_sha=manifest['runtime_sha256'], read_state=lambda: state, budget=Budget()))
    assert response['source_context']['points'][0]['temperature_c'] == -20.1
    assert response['source_context']['points'][1]['latitude'] == -30.375
    assert '65.3°C' in response['delivery_text']
    packet = tmp_path / 'invented-fractional-preview.json'
    packet.write_text(json.dumps({'request': request, 'response': response}))
    code = r'''
import fs from 'node:fs'
import { validateGraphicResponse } from './lib/graphic-preview.js'
const manifest=JSON.parse(fs.readFileSync('lib/graphic-runtime-manifest.json','utf8'))
const p=JSON.parse(fs.readFileSync(process.argv[1],'utf8'))
await validateGraphicResponse(p.response,p.request,manifest)
const changed=structuredClone(p.response);changed.source_context.points[0].temperature_c=-20.2
let refused=false;try{await validateGraphicResponse(changed,p.request,manifest)}catch{refused=true}
if(!refused)throw Error('changed fractional point accepted')
process.stdout.write(JSON.stringify({exact_fractional_projection:true,changed_fractional_point_refused:true}))
'''
    result = subprocess.run([node_binary(), '--input-type=module', '-e', code, str(packet)], cwd=ROOT / 'dashboard',
        env={'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path), 'LC_ALL': 'C', 'LANG': 'C'},
        text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(result.stdout)['changed_fractional_point_refused'] is True
