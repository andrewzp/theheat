"""Owned no-network children prove total timeout, framing and clean environment."""
import base64
import json
import subprocess
import sys
import time

import pytest

from src.data import nhc_advisory as source
from src.editorial.nhc_advisory import AdvisoryHold
from tests import nhc_advisory_helpers as h


def test_slow_headers_or_buffered_trickle_cannot_outlive_total_timeout(monkeypatch):
    real_run = subprocess.run
    receipts = []

    def stand_in(command, **kwargs):
        # The child does no network; an unending trickle is still killed and waited.
        receipts.append((command, kwargs))
        return real_run([sys.executable, '-I', '-c',
                         'import time,sys\nwhile True:\n sys.stdout.write(".");sys.stdout.flush();time.sleep(.02)'],
                        **kwargs)
    monkeypatch.setattr(source.subprocess, 'run', stand_in)
    monkeypatch.setattr(source, 'REQUEST_SECONDS', .25)
    started = time.monotonic()
    with pytest.raises(AdvisoryHold) as raised:
        source._http_get(h.URL, limit=100)
    assert raised.value.code == 'nhc_advisory_source_slow'
    assert time.monotonic() - started < 5
    assert len(receipts) == 1 and receipts[0][1]['timeout'] == .25
    assert receipts[0][1]['stderr'] is subprocess.DEVNULL


def test_owned_child_gets_a_product_identity_not_a_url_or_credentials(monkeypatch):
    calls = []
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'invented-secret-never-inherited')
    monkeypatch.setenv('GEMINI_API_KEY', 'invented-secret-never-inherited')
    monkeypatch.setenv('HTTPS_PROXY', 'http://invented.invalid')

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'status':200, 'headers':{'content-length':'3'}, 'body':base64.b64encode(b'abc').decode()}).encode())
    monkeypatch.setattr(source.subprocess, 'run', run)
    assert source._http_get(h.URL, limit=100) == (200, {'content-length':'3'}, b'abc')
    command, options = calls[0]
    assert command[0] == sys.executable and command[1:3] == ['-I', '-c']
    assert command[-2:] == ['EP5', '100'] and h.URL not in command
    assert options['timeout'] == 20 and options['check'] is False
    assert set(options['env']) == {'PATH','LANG','LC_ALL','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE'}
    assert all('invented' not in v for v in options['env'].values())


@pytest.mark.parametrize('url', ['https://evil.example/CurrentStorms.json',
                               'https://www.nhc.noaa.gov/text/MIATCPEP5.shtml?extra=1',
                               'file:///tmp/x'])
def test_child_refuses_unsupported_source_before_process_creation(monkeypatch, url):
    monkeypatch.setattr(source.subprocess, 'run', lambda *a, **k: pytest.fail('must not spawn'))
    with pytest.raises(AdvisoryHold):
        source._http_get(url, limit=100)


@pytest.mark.parametrize('raw,code', [
    (b'{"hold":"nhc_advisory_source_slow"}', 'nhc_advisory_source_slow'),
    (b'{"hold":"secret body"}', 'nhc_advisory_source_unavailable'),
    (b'partial', 'nhc_advisory_source_unavailable'),
    (b'{"status":200,"headers":{},"body":"????"}', 'nhc_advisory_source_unavailable'),
    (b'{"status":200,"headers":{},"body":"YWJjZA=="}', 'nhc_advisory_response_bound'),
    (b'{"status":200,"headers":{"arbitrary":"secret"},"body":""}', 'nhc_advisory_source_unavailable'),
])
def test_child_partial_or_bad_response_never_becomes_source_evidence(monkeypatch, raw, code):
    monkeypatch.setattr(source.subprocess, 'run', lambda command, **k: subprocess.CompletedProcess(command, 0, raw))
    with pytest.raises(AdvisoryHold) as raised:
        source._http_get(h.URL, limit=3)
    assert raised.value.code == code and str(raised.value) == code
