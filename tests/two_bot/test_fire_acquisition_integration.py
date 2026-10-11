"""Qualified synthetic thermal evidence at every writing/checking boundary."""
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.data.fire_evidence import validate_bundle, fire_bundle_failures, temporal_claim_failures
from src.data.fire_source_contract import FIRMS_PRODUCTS, HMS_PRODUCT
from src.two_bot import writer, fact_check, pipeline
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.fire import build_fire_bundle
from src.two_bot.multisignal import attach_related_signals
from src.two_bot.scientific_claims import scientific_claim_failures
from src.two_bot.types import MemorySlice, RelatedSignal, StoryBundle, WriterResult, FactCheckResult, CriticResult
from tests.fire_source_fixtures import fire_event

pytestmark = pytest.mark.usefixtures('configured_pipeline_providers')


def thermal(**kwargs):
    return build_fire_bundle(fire_event(**kwargs))


def other():
    return StoryBundle(signal_kind='drought', where='Mali', country='ML', when='2032-03-01',
        event_id='drought_synthetic', headline_metric={'label': 'severity', 'value': 'severe'},
        current_facts=[{'label': 'country', 'value': 'ML'}], raw_signal_dump={'source_name': 'Synthetic drought fixture'})


def candidates(*bundles):
    return [SimpleNamespace(bundle=b, event_id=b.event_id, score=SimpleNamespace(total=80)) for b in bundles]


@pytest.mark.parametrize('product', [*FIRMS_PRODUCTS, HMS_PRODUCT])
def test_complete_bundle_qualifies_with_typed_confidence(product):
    bundle = thermal(product=product)
    row = validate_bundle(bundle)
    assert audit_story_bundle(bundle).prompt_ready
    confidence = next(f for f in bundle.current_facts if f['label'] == 'satellite_confidence')
    assert confidence['value'] == row.confidence_value
    assert ('unit' in confidence) == (product == 'MODIS_NRT')
    assert bundle.raw_signal_dump['frp_source'] == row.frp
    assert bundle.when == row.acquired_at


@pytest.mark.parametrize('field,value', [('when', '2032-03-01'), ('event_id', 'legacy_fire'),
    ('signal_kind', 'drought'), ('headline_metric', {'label': 'FRP', 'value': 999, 'unit': 'MW'}),
    ('current_facts', []), ('raw_signal_dump', {})])
def test_mutated_primary_buys_no_writer_or_checker_calls(monkeypatch, field, value):
    bundle = thermal()
    setattr(bundle, field, value)
    writer_call, checker_call = Mock(), Mock()
    monkeypatch.setattr(writer, '_call_writer_provider', writer_call)
    monkeypatch.setattr(fact_check, '_call_gemini', checker_call)
    assert not audit_story_bundle(bundle).prompt_ready
    assert writer.write_tweet(bundle, MemorySlice()).tweet is None
    assert not fact_check.fact_check('A thermal detection measured 361 MW.', [], bundle, {}).passed
    writer_call.assert_not_called()
    checker_call.assert_not_called()


@pytest.mark.parametrize('field,value', [('acquired_at', '2032-03-01T00:02:00Z'),
    ('source_leg', 'invented'), ('source_product', 'MODIS_NRT'), ('confidence', 95),
    ('confidence_kind', 'numeric'), ('lat', True), ('frp_source', 361.1), ('frp', 361.1),
    ('source_date', '2032-02-29'), ('acquisition_precision', 'second'), ('acquisition_provenance', None)])
def test_source_projection_mutations_fail(field, value):
    bundle = thermal()
    bundle.raw_signal_dump[field] = value
    assert fire_bundle_failures(bundle)
    assert scientific_claim_failures('A thermal detection measured 361 MW.', bundle)


def test_receipt_and_related_summary_detach_and_share_no_mutable_source():
    event = fire_event()
    bundle = build_fire_bundle(event)
    host = other()
    attach_related_signals(candidates(host, bundle))
    related, = host.related_signals
    assert related.acquisition_evidence == event.acquisition_provenance
    assert related.when == event.acquired_at
    event.acquisition_provenance['record']['frp'] = '999'
    bundle.raw_signal_dump['acquisition_provenance']['record']['frp'] = '998'
    assert not fire_bundle_failures(host)
    assert fire_bundle_failures(bundle)


@pytest.mark.parametrize('field,value', [('when', '2032-03-02T00:01:00Z'), ('event_id', 'thermal_other'),
    ('signal_kind', 'drought'), ('acquisition_evidence', None),
    ('headline_metric', {'label': 'FRP', 'value': 999, 'unit': 'MW'})])
def test_mutated_related_signal_fails_audit_and_direct_check(monkeypatch, field, value):
    host = other()
    attach_related_signals(candidates(host, thermal()))
    setattr(host.related_signals[0], field, value)
    call = Mock()
    monkeypatch.setattr(fact_check, '_call_gemini', call)
    assert not audit_story_bundle(host).prompt_ready
    assert not fact_check.fact_check('Two separate reports.', [], host, {}).passed
    call.assert_not_called()


def test_day_only_legacy_summary_unqualified_and_not_attached():
    host = other()
    old = thermal()
    old.when = '2032-03-01'
    attach_related_signals(candidates(host, old))
    assert host.related_signals == []
    host.related_signals = [RelatedSignal('fire_old', 'fire', 'Mali', '2032-03-01', {'label': 'FRP', 'value': 361, 'unit': 'MW'})]
    assert fire_bundle_failures(host)


def test_same_cell_conflicting_overpasses_quarantine_related_summary():
    host = other()
    first = thermal()
    second = thermal(when=datetime(2032, 3, 1, 0, 2, tzinfo=UTC))
    assert first.event_id == second.event_id
    attach_related_signals(candidates(host, first, second))
    assert host.related_signals == []


@pytest.mark.parametrize('phrase', ['simultaneous', 'simultaneously', 'concurrent', 'concurrently',
    'at the same time', 'at the same moment', 'at the same instant', 'same overpass',
    'same scan', 'same satellite overpass', 'same satellite scan', 'SAME—SATELLITE\nSCAN',
    'not simultaneous', '"simultaneous"'])
@pytest.mark.parametrize('related', [False, True])
def test_temporal_language_blocked_before_direct_checker(monkeypatch, phrase, related):
    bundle = thermal()
    if related:
        host = other()
        attach_related_signals(candidates(host, bundle))
        bundle = host
    call = Mock()
    monkeypatch.setattr(fact_check, '_call_gemini', call)
    assert temporal_claim_failures(phrase, bundle)
    assert not fact_check.fact_check('Two detections: '+phrase+'.', [], bundle, {}).passed
    call.assert_not_called()


def test_nonthermal_and_legitimate_enumeration_not_blocked():
    assert temporal_claim_failures('Concurrent measurements.', other()) == []
    for text in ['Two detections on the same day.', 'The same week, another reading.',
                 'Two separate measurements together in this list.', 'A scanner measured thermal power.']:
        assert temporal_claim_failures(text, thermal()) == []


def test_legacy_history_blocks_direct_and_shadow_before_writer(mock_writer):
    bundle = thermal()
    state = {'posted_events': [bundle.event_id.removesuffix('_utc1')]}
    outcome = {}
    assert pipeline.generate_draft(bundle, state, result_out=outcome) is None
    assert outcome['kill_stage'] == 'fire_history'
    assert pipeline.generate_shadow_draft(bundle, state) is None
    mock_writer.assert_not_called()


def test_legitimate_enumeration_reaches_every_required_check(mock_writer, mock_fact_check, mock_critic, mock_safety):
    bundle = thermal()
    attach_related_signals(candidates(bundle, other()))
    mock_writer.return_value = WriterResult(tweet='A 361 MW thermal detection in Mali; a separate drought report followed.',
        kill_reason=None, angle_chosen='plain_number', era_anchor_used=None, peer_comparison_used=None, reasoning='synthetic')
    mock_fact_check.return_value = FactCheckResult(True, [], 'synthetic', [])
    mock_critic.return_value = CriticResult(True, None, 'synthetic')
    outcome = {}
    assert pipeline.generate_draft(bundle, {}, result_out=outcome) is not None, outcome
    for call in (mock_writer, mock_fact_check, mock_critic, mock_safety):
        call.assert_called_once()


def test_nonthermal_serialization_remains_six_fields():
    signal = RelatedSignal('drought_a', 'drought', 'Mali', '2032-03-01', {'label': 'severity', 'value': 'severe'}, 'ML')
    assert set(signal.to_dict()) == {'event_id', 'signal_kind', 'where', 'when', 'headline_metric', 'country'}
    assert deepcopy(signal).to_dict() == signal.to_dict()


def test_retained_checker_roundtrip_preserves_related_receipt_and_identity():
    from src.editorial.revisions import fingerprint
    from src.two_bot.candidate_derivation import retained_bundle
    host = other()
    attach_related_signals(candidates(host, thermal()))
    packet = host.to_dict()
    restored = retained_bundle(packet)
    assert fingerprint(restored.to_dict()) == fingerprint(packet)
    assert not fire_bundle_failures(restored)
    packet['related_signals'][0]['acquisition_evidence']['record']['frp'] = '999'
    assert not fire_bundle_failures(restored)
    assert fire_bundle_failures(retained_bundle(packet))


def test_old_fire_constructor_is_retained_but_never_given_an_invented_time():
    from src.data.firms import FireEvent
    old = FireEvent(13.5, -4.2, 95, 361.0, 'Mali', 'ML', 'fire_13.50_-4.20_2026-07-01')
    bundle = build_fire_bundle(old)
    assert old.acquired_at is None and old.acquisition_provenance is None
    assert bundle.when == '' and bundle.raw_signal_dump['confidence'] is None
    assert not audit_story_bundle(bundle).prompt_ready
