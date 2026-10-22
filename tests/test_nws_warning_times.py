"""Invented CAP clocks: message expiry is not forecast-event ending time."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest
import responses

from scripts import fresh_sample_trial as trial
from src.commands.schema import utc_text
from src.editorial.revisions import authorize_draft, record_human_review
from src.media import published_radar as radar
from src.orchestrator import nws_publication
from src.state import DEFAULT_STATE
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.disasters import build_severe_weather_bundle
from tests import published_radar_fixtures as fixture
from tests.test_nws_publication import (
    NOW as POST_NOW, boundary as boundary, draft as reviewed_draft, manual, state as saved_state,
)


def forecast(at=fixture.AT):
    item = fixture.feature(at)
    item['geometry'] = None
    item['properties'].update(
        event='Blizzard Warning', parameters={},
        headline='INVENTED: blizzard warning for a future storm',
        description='Invented forecast warning; no observed weather or impacts.',
        onset=(at + timedelta(days=1)).isoformat(),
        expires=(at + timedelta(hours=2)).isoformat(),
        ends=(at + timedelta(days=2)).isoformat(),
    )
    return item


def retained_draft(bundle):
    return {'id': 'invented-future-warning', 'type': 'severe_weather',
            'event_id': bundle.event_id, 'text': 'Invented forecast warning.',
            'review_context': {'two_bot': {'bundle': bundle.to_dict()}}}


def test_future_warning_survives_collector_builder_and_source_audit(monkeypatch):
    item = forecast()
    alert = fixture.parsed(monkeypatch, item)[0]
    envelope = alert.source_evidence
    assert envelope['feature'] == item
    assert envelope['status'] == 'held'  # Never qualification for a radar overlay.
    assert envelope['reasons'] == ['radar_source_interval_invalid']
    bundle = build_severe_weather_bundle(alert)
    assert bundle.when == utc_text(fixture.AT + timedelta(days=1))
    assert audit_story_bundle(bundle).prompt_ready
    facts = {row['label']: row['value'] for row in bundle.current_facts}
    assert facts['source_message_expires_utc'] == utc_text(fixture.AT + timedelta(hours=2))
    assert facts['forecast_event_onset_utc'] == bundle.when
    assert facts['forecast_event_end_utc'] == utc_text(fixture.AT + timedelta(days=2))
    assert 'warning_valid_end_utc' not in facts
    with pytest.raises(radar.RadarHold, match='radar_source_evidence_held'):
        radar.source(bundle.to_dict())


def test_actual_free_prepare_retains_future_warning_without_model_calls(monkeypatch, tmp_path):
    item = forecast()
    fixture.parsed(monkeypatch, item)  # Same explicit source clock for the real collector.
    monkeypatch.setattr(trial, 'binding', lambda: {'explicit_offline_binding': True})
    state = tmp_path / 'state.json'
    state.write_text(json.dumps(deepcopy(DEFAULT_STATE)))
    before = state.read_bytes()
    with responses.RequestsMock() as calls:
        calls.add(responses.GET, radar.ALERT_URL, json={'features': [item]}, status=200)
        result = trial.prepare(state, tmp_path / 'packet', fixture.AT)
        assert len(calls.calls) == 1
    assert result['candidate_count'] == 1 and result['paid_calls'] == result['posts'] == 0
    assert state.read_bytes() == before
    bundle = json.loads((tmp_path / 'packet/bundles.json').read_text())[0]
    assert bundle['raw_signal_dump']['source_evidence']['feature'] == item
    assert trial.eligible(bundle, fixture.AT)


@pytest.mark.parametrize('change', ['expired', 'future_sent', 'future_effective', 'ended',
                                   'inverted_event', 'missing_expires', 'naive_onset'])
def test_invalid_or_noncurrent_clocks_block_trial_and_sender(monkeypatch, change):
    item = forecast()
    p = item['properties']
    if change == 'expired':
        p['expires'] = (fixture.AT - timedelta(seconds=1)).isoformat()
    elif change == 'future_sent':
        p['sent'] = (fixture.AT + timedelta(seconds=1)).isoformat()
    elif change == 'future_effective':
        p['effective'] = (fixture.AT + timedelta(minutes=1)).isoformat()
    elif change == 'ended':
        p.update(onset=(fixture.AT - timedelta(minutes=1)).isoformat(),
                 ends=(fixture.AT - timedelta(seconds=1)).isoformat())
    elif change == 'inverted_event':
        p['ends'] = (fixture.AT + timedelta(hours=1)).isoformat()
    elif change == 'missing_expires':
        p['expires'] = None
    else:
        p['onset'] = '2026-06-09T12:00:00'
    alert = fixture.parsed(monkeypatch, item)[0]
    bundle = build_severe_weather_bundle(alert)
    assert not trial.eligible(bundle.to_dict(), fixture.AT)
    monkeypatch.setattr(nws_publication, '_clock', lambda: fixture.AT)
    assert nws_publication.current_nws_source(retained_draft(bundle), live=False) is not None


def test_future_warning_remains_current_only_until_message_expiry(monkeypatch):
    bundle = build_severe_weather_bundle(fixture.parsed(monkeypatch, forecast())[0])
    draft = retained_draft(bundle)
    now = {'value': fixture.AT}
    monkeypatch.setattr(nws_publication, '_clock', lambda: now['value'])
    assert nws_publication.current_nws_source(draft, live=False) is None
    now['value'] += timedelta(hours=2)
    assert nws_publication.current_nws_source(draft, live=False) == 'nws_source_expired_or_future'
    assert not trial.eligible(bundle.to_dict(), now['value'])


def test_unknown_forecast_end_is_not_replaced_with_message_expiry(monkeypatch):
    item = forecast()
    item['properties']['ends'] = None
    bundle = build_severe_weather_bundle(fixture.parsed(monkeypatch, item)[0])
    facts = {row['label']: row['value'] for row in bundle.current_facts}
    assert 'forecast_event_end_utc' not in facts
    assert 'warning_valid_end_utc' not in facts
    assert facts['source_message_expires_utc'] == utc_text(fixture.AT + timedelta(hours=2))
    assert trial.eligible(bundle.to_dict(), fixture.AT)


def test_future_catastrophic_tornado_cannot_gain_radar_qualification(monkeypatch):
    item = forecast()
    original = fixture.feature()
    item['geometry'] = original['geometry']
    item['properties'].update(event='Tornado Warning', parameters=original['properties']['parameters'])
    bundle = build_severe_weather_bundle(fixture.parsed(monkeypatch, item)[0])
    assert audit_story_bundle(bundle).prompt_ready
    with pytest.raises(radar.RadarHold, match='radar_source_evidence_held'):
        radar.source(bundle.to_dict())
    with pytest.raises(radar.RadarHold, match='radar_source_interval_invalid'):
        radar.interval(bundle.raw_signal_dump['source_evidence']['times'])


def approved_forecast():
    # Explicit invented human-review fixture, never production fallback approval.
    item = forecast(POST_NOW)
    value = reviewed_draft(item)
    value['text'] = 'NWS has issued a blizzard warning for Invented County ahead of tomorrow’s storm.'
    record_human_review(value)
    authorize_draft(value, 'manual', 'invented-forecast-intent')
    return item, value


@pytest.mark.usefixtures('automatic_publication_release')
def test_future_forecast_uses_actual_manual_sender_with_explicit_fake_platform(boundary, monkeypatch):
    _, _, send, safety, lookup = boundary
    item, value = approved_forecast()
    lookup.return_value = {'features': [item]}
    original = deepcopy(value['review_context'])
    manual(monkeypatch, value, saved_state(value))
    assert lookup.call_count == 2 and safety.call_count == 1
    send.assert_called_once_with(value['text'], media_png=None, alt_text=None)
    assert value['review_context'] == original


@pytest.mark.usefixtures('automatic_publication_release')
@pytest.mark.parametrize('during', ['before', 'lookup', 'safety'])
def test_future_event_cannot_extend_expired_message_at_real_sender(boundary, monkeypatch, during):
    clock, storage, send, safety, lookup = boundary
    item, value = approved_forecast()
    lookup.return_value = {'features': [item]}
    def expire():
        clock['now'] = POST_NOW + timedelta(hours=2)
    if during == 'before':
        expire()
    elif during == 'lookup':
        def feed():
            expire()
            return {'features': [item]}
        lookup.side_effect = feed
    else:
        def checked(_text):
            expire()
            return True, None
        safety.side_effect = checked
    saved = saved_state(value)
    manual(monkeypatch, value, saved)
    send.assert_not_called()
    storage.write_state.assert_not_called()
    assert saved['publish_ledger'] == {} and not value.get('approval_binding')
    if during != 'safety':
        safety.assert_not_called()


@pytest.mark.usefixtures('automatic_publication_release')
@pytest.mark.parametrize('field', ['onset', 'expires', 'ends'])
def test_changed_live_forecast_times_cannot_replace_reviewed_evidence(boundary, monkeypatch, field):
    _, storage, send, safety, lookup = boundary
    item, value = approved_forecast()
    changed = deepcopy(item)
    changed['properties'][field] = (POST_NOW + timedelta(days=3)).isoformat()
    lookup.return_value = {'features': [changed]}
    original = deepcopy(value['review_context'])
    saved = saved_state(value)
    manual(monkeypatch, value, saved)
    safety.assert_not_called()
    send.assert_not_called()
    storage.write_state.assert_not_called()
    assert value['review_context'] == original
    assert saved['publish_ledger'] == {} and not value.get('approval_binding')
