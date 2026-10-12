"""Complete invented GHCN archives and the bounded request-only claim view."""
from copy import deepcopy
from datetime import timedelta
import io
import tarfile

import pytest

from src.orchestrator.two_bot_dispatch import _two_bot_bundle_for_extreme_signal
from src.storage import ghcn_runtime_inputs as inputs
from src.storage.cyclone_supply import CycloneSupplyError
from src.two_bot import ghcn_claim_view as claim
from src.two_bot.bundle_capture import capture_bundle, BundleCaptureError, MAX_BUNDLE_BYTES
from src.two_bot.candidate_derivation import retained_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from tests.test_ghcn_runtime_inputs import source_bytes as source_bytes, run
from tests.test_ghcn_time_integrity import dly


def dual_source(source):
    """Actual parsed TMAX/TMIN; missing/QC cells remain in the full source calendar."""
    source=deepcopy(source)
    day=source['day']
    start=day.replace(year=day.year-23)
    cells=[]
    for index in range((day-start).days):
        at=start+timedelta(days=index)
        cells.extend([(at,'TMAX',-9999 if index==10 else 280,'S' if index==20 else '', 'T'),
                      (at,'TMIN',-9999 if index==30 else 100,'S' if index==40 else '', 'T')])
    cells.extend([(day,'TMAX',455,'','T'),(day,'TMIN',-255,'','T')])
    for index,response in enumerate(source['responses']):
        if response.kind=='diff' and response.key==day.isoformat():
            text=''.join(f'USW{i:08d},{day:%Y%m%d},TMAX,{455 if i==0 else 399},,,T,\n' for i in range(9))
            text+=f'USW00000000,{day:%Y%m%d},TMIN,-255,,,T,\n'
            raw=text.encode()
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w:gz') as archive:
                info=tarfile.TarInfo('superghcnd_insert.csv')
                info.size=len(raw)
                archive.addfile(info,io.BytesIO(raw))
            source['responses'][index]=inputs.InventedResponse('diff',response.key,response.retrieved_at,stream.getvalue())
        elif response.kind=='station_archive' and response.key=='USW00000000':
            source['responses'][index]=inputs.InventedResponse(response.kind,response.key,response.retrieved_at,dly(cells,response.key))
    return source


@pytest.fixture
def complete_member(source_bytes):
    source=dual_source(source_bytes)
    bundles,*_=run(source)
    return source,next(b for b in bundles if b.station_id=='USW00000000')


@pytest.mark.parametrize('field',tuple(claim.TYPES))
def test_all_nine_real_scientific_selections_fit_without_losing_full_calendar(complete_member,field):
    source,member=complete_member
    event=getattr(member,field)
    assert event is not None,field
    full=_two_bot_bundle_for_extreme_signal(claim.TYPES[field],event,source='ghcn')
    assert audit_story_bundle(full).prompt_ready
    before=claim.json_tree(full.to_dict())
    selection=dict(station_id=member.station_id,signal_date=str(member.signal_date),signal_field=field)
    # A pure projection test has no applied-source authority. Only resolve()
    # constructs a usable reference after actual PG command/result validation.
    reference=dict(kind='invented-pure-projection-test',full_sha256=claim.fingerprint(before))
    view=claim.project(full,reference,selection)
    captured=capture_bundle(view)
    assert len(captured.serialized.encode())<=MAX_BUNDLE_BYTES
    assert claim.json_tree(full.to_dict())==before
    assert len(full.current_facts)==len(view.current_facts)
    assert claim.json_tree(claim.project(full,reference,selection).to_dict())==captured.payload()
    evidence=before['raw_signal_dump']['evidence']
    assert evidence['evidence_type']=='observed' and evidence['reporting_interval_known'] is False
    assert all(len(v['calendar_samples'])==366 for v in evidence['baseline']['variables'].values())
    assert all(v['source_coverage_complete'] and not v['complete'] for v in evidence['baseline']['variables'].values())
    assert all(v['source_missing_count']==v['source_qc_rejected_count']==1 for v in evidence['baseline']['variables'].values())
    assert not str(full.headline_metric['label']).startswith('forecast_')
    with pytest.raises(BundleCaptureError,match='too_large'):
        capture_bundle(full)
    with pytest.raises(ValueError,match='requires_resolved_check_context'):
        retained_bundle(captured.payload())
    # The original constructor projection is not used to hydrate either view.
    with pytest.raises(ValueError,match='roundtrip_changed'):
        retained_bundle(before)


@pytest.mark.parametrize('change',['baseline_extra','variable_extra','evidence_extra','oversize_enrichment'])
def test_compact_view_refuses_schema_growth_and_oversize_instead_of_discarding(complete_member,change):
    _,member=complete_member
    full=_two_bot_bundle_for_extreme_signal('all_time_high',member.all_time_high,source='ghcn')
    selection=dict(station_id=member.station_id,signal_date=str(member.signal_date),signal_field='all_time_high')
    if change=='baseline_extra':
        full.raw_signal_dump['evidence']['baseline']['unknown_new_science']={'may_matter':True}
    elif change=='variable_extra':
        full.raw_signal_dump['evidence']['baseline']['variables']['temperature_2m_max']['unknown_qualification']=False
    elif change=='evidence_extra':
        full.raw_signal_dump['evidence']['unknown_time_scope']='new'
    else:
        full.current_facts.append(dict(label='invented_enrichment',value='x'*MAX_BUNDLE_BYTES))
    with pytest.raises((CycloneSupplyError,BundleCaptureError)):
        capture_bundle(claim.project(full,{},selection))


def test_legacy_forecast_dispatch_remains_forecast(monkeypatch):
    from datetime import date
    from src.orchestrator.sources import open_meteo as source
    from src.state import DEFAULT_STATE
    from tests.test_open_meteo_orchestrator import _france_significant_bundles
    bundles=_france_significant_bundles(date(2026,7,8))
    from src.data.temperature_evidence import attach_evidence
    from tests.temperature_helpers import dated_forecast,snapshot
    evidence=dated_forecast(dict(max_c=41,min_c=20),'2026-07-08')['evidence']
    evidence['baseline']=snapshot(dict(as_of='2026-07-08',years_of_data=30))['baseline']
    for bundle in bundles:
        attach_evidence(bundle,evidence)
    submitted=[]
    def inspect(state,**kwargs):
        submitted.append(kwargs)
        return False
    monkeypatch.setenv('THEHEAT_SIGNALS_PROVIDER','open_meteo')
    monkeypatch.setattr(source,'_check_city_extreme_signals',lambda cities,metrics_out:(bundles,[]))
    monkeypatch.setattr(source,'_should_draft',lambda *a,**k:True)
    monkeypatch.setattr(source,'_enqueue_story_candidate',inspect)
    source.run_extreme_signals(deepcopy(DEFAULT_STATE),None,[],{},{})
    individual=[row['bundle'] for row in submitted if row['legacy_type']=='all_time_high']
    assert len(individual)==1
    assert individual[0].headline_metric['label']=='forecast_high_c'
    assert individual[0].raw_signal_dump['evidence']['evidence_type']=='forecast'
