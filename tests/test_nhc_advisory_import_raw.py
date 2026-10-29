"""The normal Gist raw fallback preserves full JSON bytes before pending admission."""
import json
import subprocess

import pytest

from scripts import nhc_advisory_import as m

GIST = 'a' * 32
RAW = b' {"drafts":[],"number":1.000e+0,"negative":-0.0}\n'


def client(monkeypatch, *, truncated=True, raw=RAW, code=0):
    value = m.GitHub(GIST, 'andrewzp/theheat')
    calls = []
    gist = {'files': {'state.json': {'truncated':truncated, 'content':'incomplete' if truncated else RAW.decode()},
                      'runtime-inventory.json': {'truncated':False, 'content':'{"retained":true}'}}}
    monkeypatch.setattr(value, '_api', lambda args, body=None: json.dumps(
        gist if args[0].startswith('gists/') else {'variables':[]}).encode())

    def invoke(command, **kwargs):
        calls.append((command,kwargs))
        return subprocess.CompletedProcess(command,code,raw,b'invented error never printed')
    monkeypatch.setattr(m.subprocess,'run',invoke)
    return value, calls


def test_truncated_inline_state_uses_one_normal_fixed_file_raw_read(monkeypatch):
    value,calls=client(monkeypatch)
    files,flags=value.read()
    assert files['state.json'] == RAW
    assert files['runtime-inventory.json'] == b'{"retained":true}' and flags == {}
    assert calls == [(['gh','gist','view',GIST,'--raw','--filename','state.json'],
                      {'capture_output':True,'timeout':60})]
    assert value.patches == 0


def test_inline_content_does_not_add_a_raw_request(monkeypatch):
    value,calls=client(monkeypatch,truncated=False)
    assert value.read()[0]['state.json'] == RAW and calls == []


@pytest.mark.parametrize('raw,code,reason', [(b'',1,'github_request_failed'),
                                           (b'x'*(m.MAX_BYTES+1),0,'document_size')],ids=['failed','oversized'])
def test_failed_or_oversized_raw_read_cannot_reach_a_write(monkeypatch,raw,code,reason):
    value,calls=client(monkeypatch,raw=raw,code=code)
    with pytest.raises(m.ImportRefused) as raised:
        value.read()
    assert raised.value.code == reason and len(calls)==1 and value.patches==0


def test_expiry_during_durable_backups_consumes_attempt_without_patching(monkeypatch,tmp_path):
    from datetime import timedelta
    from src.data import nhc_advisory as source
    from tests import nhc_advisory_helpers as h
    from tests.nhc_advisory_import_helpers import CODE,FLAGS,SOURCE,encode,proposal,report
    from tests.nhc_advisory_pipeline_helpers import Transport
    monkeypatch.setattr(source,'_http_get',Transport())
    raw=encode(proposal())
    files={'state.json':b'{"drafts":[],"publish_ledger":{},"posted_events":[]}',
           'runtime-inventory.json':report()}
    clock=[h.NOW]
    patches=[]
    original=m.durable

    def durable(path,value):
        original(path,value)
        if path.name.endswith('.attempt.json'):
            clock[0]=h.CAPTURED+timedelta(minutes=30)
    monkeypatch.setattr(m,'durable',durable)
    with pytest.raises(m.ImportRefused) as raised:
        m.execute(raw,m.sha(raw),expected_state_sha256=m.sha(files['state.json']),
                  read=lambda:(dict(files),dict(FLAGS)),patch=patches.append,journal=tmp_path,
                  clock=lambda:clock[0],code_sha=CODE,source_sha=SOURCE)
    assert raised.value.code == 'nhc_advisory_operator_deadline_passed'
    assert patches == [] and len(list(tmp_path.glob('*.attempt.json'))) == 1
