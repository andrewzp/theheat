"""Invented station bytes, immutable baseline and original scientific interpreter."""
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import gzip
import io
import sqlite3
import tarfile

import pytest

from scripts import threshold_artifacts as artifacts
from src.data import ghcn, ghcn_db
from src.data.ghcn_format import DailyObs, compute_thresholds
from src.storage import ghcn_runtime_inputs as inputs
from src.storage.cyclone_supply import CycloneSupplyError
from tests.test_ghcn_time_integrity import dly, draft


def raw_diff(day, stations, *, qflag=""):
    text = ''.join(f'{sid},{day:%Y%m%d},TMAX,399,,{qflag},T,\n' for sid in stations).encode()
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as archive:
        member = tarfile.TarInfo('superghcnd_insert.csv')
        member.size = len(text)
        archive.addfile(member, io.BytesIO(text))
    return out.getvalue()


@pytest.fixture
def source_bytes(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)-timedelta(seconds=3)
    day = now.date()-timedelta(days=1)
    station_ids = [f'USW{i:08d}' for i in range(9)]
    database = tmp_path/'invented.sqlite'
    with ghcn_db.open_db(database) as c:
        for i in range(1000):
            sid = f'USW{i:08d}'
            c.execute('INSERT INTO stations(station_id,name,country_code,country_name,state,lat,lon,is_active,tmax_archive_years,archive_years) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (sid, f'INVENTED STATION {i}', 'US', 'United States', 'UT', 40+i*0.05, -111., 1, 24, 24))
            ghcn_db.upsert_thresholds(c, compute_thresholds([DailyObs(sid, date(2020,day.month,day.day), 'TMAX',31.9)]))
        c.commit()
    manifest = tmp_path/'invented.version'
    fields = dict(release='thresholds-latest', sha256=artifacts.digest(database)[0], bytes=str(database.stat().st_size), **artifacts.database_stats(database))
    manifest.write_text(''.join(f'{k}={v}\n' for k,v in fields.items()))
    baseline = inputs.Baseline(database, manifest, fields['sha256'], artifacts.digest(manifest)[0])
    start_day = date(day.year-23, day.month, day.day)
    history = [(start_day+timedelta(days=n), 'TMAX', 280, '', 'T') for n in range((day-start_day).days)]
    at = now.isoformat().replace('+00:00','Z')
    responses = [inputs.InventedResponse('diff', (now.date()-timedelta(days=n)).isoformat(), at,
                    raw_diff(day, station_ids) if n == 1 else raw_diff(day, [])) for n in range(1,4)]
    for i,sid in enumerate(station_ids):
        rows = history if i != 7 else [history[0],history[-1]]
        payload = dly(rows + [(day,'TMAX',399 if i != 8 else 380,'S' if i == 6 else '', 'T')], sid)
        responses.append(inputs.InventedResponse('station_archive', sid, at, payload))
    return dict(baseline=baseline, responses=responses, day=day, now=at,
                started_at=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),
                completed_at=(now+timedelta(seconds=1)).isoformat().replace('+00:00','Z'))


def run(source_bytes, state=None):
    deps = inputs.state_dependencies(state or {})
    return inputs.derive(source_bytes['baseline'], deps, source_bytes['responses'], now=source_bytes['now'], config=inputs.configuration())


def test_actual_parser_readonly_baseline_and_six_complete_qualified_members(source_bytes):
    baseline = source_bytes['baseline']
    before = baseline.database.read_bytes(), baseline.manifest.read_bytes()
    bundles, countries, metrics, effects, descriptor = run(source_bytes)
    assert {b.station_id for b in bundles} == {f'USW{i:08d}' for i in range(6)}
    assert metrics['scientific_signal_bundles'] == 6 and metrics['threshold_verification'] == 'success'
    assert effects and all(row['kind'] == 'observation_revision' for row in effects)
    assert descriptor['stats']['active_stations'] == '1000'
    assert before == (baseline.database.read_bytes(), baseline.manifest.read_bytes())
    assert not any(baseline.database.with_name(baseline.database.name+s).exists() for s in ('-wal','-journal'))
    assert run(source_bytes) == (bundles,countries,metrics,effects,descriptor)


def test_readonly_connection_refuses_writes_without_schema_changes(source_bytes):
    with source_bytes['baseline'].reader() as (path, _), ghcn_db.open_db_readonly(path) as c:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            c.execute("UPDATE stations SET name='changed'")


@pytest.mark.parametrize('case', ['manifest','database','sidecar','replacement'])
def test_baseline_drift_refuses(source_bytes, case):
    baseline = source_bytes['baseline']
    if case == 'manifest':
        baseline.manifest.write_bytes(baseline.manifest.read_bytes()+b'\n')
    elif case == 'database':
        with sqlite3.connect(baseline.database) as c:
            c.execute("UPDATE stations SET name='different'")
    elif case == 'sidecar':
        baseline.database.with_name(baseline.database.name+'-wal').write_bytes(b'pending')
    else:
        with pytest.raises(ValueError):
            with baseline.reader():
                baseline.database.write_bytes(b'changed')
        return
    with pytest.raises(ValueError):
        run(source_bytes)


def test_effects_rederive_current_correction_without_mutating_input(source_bytes):
    original = draft(event_day=source_bytes['day'], sid='USW00000000', prior=31.9)
    state = dict(drafts=[original], publish_ledger={})
    before = deepcopy(state)
    _,_,_,effects,_ = run(source_bytes,state)
    assert state == before
    findings = [row for row in effects if row['kind'] == 'claim_finding']
    assert any(row['reason'] == 'current_archive_comparator_changed' for row in findings)
    assert all('verified_change' not in row and 'verified' not in row for row in effects)
    changed = deepcopy(state)
    inputs.apply_effects(changed,effects)
    assert changed['drafts'][0]['text'] == original['text']
    assert changed['drafts'][0]['status'] == 'pending' and 'approval_binding' not in changed['drafts'][0]
    assert changed['drafts'][0]['content_revision'] > original['content_revision']
    after = deepcopy(changed)
    inputs.apply_effects(changed,effects)
    assert changed == after


def test_changed_qc_with_posted_claim_retains_findings_without_rewriting(source_bytes):
    original = draft('posted',event_day=source_bytes['day'],sid='USW00000006')
    state = dict(drafts=[original],publish_ledger={original['event_id']:dict(tweet_id='invented',phase='confirmed')})
    _,_,_,effects,_ = run(source_bytes,state)
    assert any(row.get('reason') == 'current_source_qc_or_value_revision' for row in effects)
    inputs.apply_effects(state,effects)
    assert state['drafts'] == [original]


def test_raw_expansion_member_and_record_bounds(monkeypatch):
    monkeypatch.setattr(inputs,'MAX_EXPANDED',100)
    with pytest.raises(CycloneSupplyError,match='expansion_capacity'):
        inputs.bounded_payload(gzip.compress(b'x'*101),kind='diff')
    monkeypatch.setattr(inputs,'MAX_RECORDS',2)
    with pytest.raises(CycloneSupplyError,match='record_capacity'):
        inputs.bounded_payload(b'a\nb\nc',kind='station_archive')


def test_dependency_closes_approval_ledger_and_new_claim_but_not_unrelated_source(source_bytes):
    state = dict(drafts=[draft(event_day=source_bytes['day'],sid='USW00000000')], source_health={},publish_ledger={})
    before = inputs.state_dependencies(state)
    state['source_health']['other']={'new':True}
    assert inputs.state_dependencies(state) == before
    state['drafts'][0]['approval_binding']['extra'] = 'different'
    assert inputs.state_dependencies(state) != before


def test_xz_decoder_memory_is_bounded_before_dictionary_allocation(monkeypatch):
    import lzma
    raw=lzma.compress(b'invented tiny output\n',format=lzma.FORMAT_XZ,
        filters=[dict(id=lzma.FILTER_LZMA2,dict_size=2*1024**2)])
    monkeypatch.setattr(inputs,'MAX_DECODER_MEMORY',1024**2)
    with pytest.raises(lzma.LZMAError,match='Memory usage limit'):
        inputs.bounded_payload(raw,kind='diff')
    monkeypatch.setattr(inputs,'MAX_DECODER_MEMORY',4*1024**2)
    assert inputs.bounded_payload(raw+raw,kind='diff')==(42,3)
    assert inputs.bounded_payload(raw+b'\x00'*4+raw+b'\x00'*8,kind='diff')==(42,3)
