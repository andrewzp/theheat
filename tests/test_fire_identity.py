"""Synthetic source-day identities and retained-history containment."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.data.fire_identity import legacy_aliases, legacy_history_reason, source_event_id
from src.orchestrator.draft_save import can_draft_candidate, save_draft

NEW = 'fire_35.25_-110.50_2032-03-01_utc1'
OLD = 'fire_35.25_-110.50_2032-03-01'


def test_source_id_preserves_daily_cell_and_memory_prefix():
    assert source_event_id(35.251, -110.499, '2032-03-01T23:59:00Z') == NEW
    assert source_event_id(35.251, -110.499, '2032-03-01T00:01:00Z') == NEW
    assert NEW.split('_')[:3] == OLD.split('_')[:3]
    assert legacy_aliases(NEW) == frozenset('fire_35.25_-110.50_' + d for d in (
        '2032-02-29', '2032-03-01', '2032-03-02', '2032-03-03', '2032-03-04'))


@pytest.mark.parametrize('day', ['2031-12-31', '2032-01-01', '2032-02-29'])
@pytest.mark.parametrize('age', [0, 1, 2])
@pytest.mark.parametrize('hour', [0, 12, 23])
@pytest.mark.parametrize('offset', [-12, 0, 14])
def test_alias_window_covers_legacy_local_day(day, age, hour, offset):
    acquired = datetime.fromisoformat(day).replace(tzinfo=UTC)
    collected = acquired + timedelta(days=age, hours=hour)
    local_day = (collected + timedelta(hours=offset)).date().isoformat()
    identity = source_event_id(35.25, -110.50, acquired.isoformat().replace('+00:00', 'Z'))
    assert 'fire_35.25_-110.50_' + local_day in legacy_aliases(identity)


@pytest.mark.parametrize('identity', [None, True, 'fire_35.25_-110.50_2032-03-01',
    'fire_035.25_-110.50_2032-03-01_utc1', 'fire_91.00_1.00_2032-03-01_utc1',
    'fire_35.25_-110.50_2031-02-29_utc1', 'fire_35.25_-110.50_0001-01-01_utc1',
    'fire_35.25_-110.50_9999-12-31_utc1', NEW+'\n'])
def test_invalid_new_identity(identity):
    with pytest.raises((ValueError, RuntimeError)):
        legacy_aliases(identity)


@pytest.mark.parametrize('status', ['pending', 'approved', 'posted', 'rejected', 'expired', 'unknown', None])
def test_every_retained_draft_status_holds_without_mutation(status):
    state = {'drafts': [{'event_id': OLD, 'status': status}]}
    before = deepcopy(state)
    assert legacy_history_reason(state, NEW) == 'legacy_fire_retained_draft'
    assert state == before


@pytest.mark.parametrize('row', [None, 'unknown', {}, {'phase': 'confirmed'},
    {'phase': 'sending'}, {'phase': 'not_sent', 'tweet_id': '123'},
    {'phase': 'not_sent', 'tweet_id': False}, {'phase': 'not_sent', 'preserved_evidence_only': True},
    {'phase': 'not_sent', 'attempt_conflicts': {}},
    {'phase': 'not_sent', 'attempt_conflicts': [{'phase': 'unknown'}]},
    {'phase': 'not_sent', 'attempt_conflicts': [{'phase': 'confirmed', 'tweet_id': '123'}]},
    {'phase': 'not_sent', 'attempt_conflicts': [None]}])
def test_unresolved_or_confirmed_ledger_holds(row):
    assert legacy_history_reason({'publish_ledger': {OLD: row}}, NEW) == 'legacy_fire_history_unresolved'


@pytest.mark.parametrize('row', [{'phase': 'not_sent'}, {'phase': 'not_sent', 'tweet_id': ''},
    {'phase': 'not_sent', 'attempt_conflicts': [{'phase': 'not_sent', 'tweet_id': None}]}])
def test_explicit_not_sent_alone_clears_but_retained_draft_holds(row):
    state = {'publish_ledger': {OLD: row}}
    assert legacy_history_reason(state, NEW) is None
    state['drafts'] = [{'event_id': OLD}]
    assert legacy_history_reason(state, NEW) == 'legacy_fire_retained_draft'


def test_cyclic_and_excessive_conflicts_hold():
    row = {'phase': 'not_sent'}
    row['attempt_conflicts'] = [row]
    assert legacy_history_reason({'publish_ledger': {OLD: row}}, NEW) == 'legacy_fire_history_unresolved'
    row = {'phase': 'not_sent', 'attempt_conflicts': [{'phase': 'not_sent'} for _ in range(257)]}
    assert legacy_history_reason({'publish_ledger': {OLD: row}}, NEW) == 'legacy_fire_history_unresolved'


@pytest.mark.parametrize('state', [{'drafts': None}, {'posted_events': None}, {'publish_ledger': []},
    {'drafts': [None]}, {'drafts': [{'event_id': []}]}, {'posted_events': [None]}, None])
def test_malformed_history_does_not_clear(state):
    assert legacy_history_reason(state, NEW) == 'legacy_fire_history_unresolved'


def test_new_namespace_and_other_cells_do_not_create_five_day_cooldown():
    state = {'posted_events': [NEW, NEW.replace('03-01', '03-02'), OLD.replace('35.25', '35.26')]}
    assert legacy_history_reason(state, NEW) is None
    assert legacy_history_reason({'posted_events': [OLD]}, NEW) == 'legacy_fire_already_posted'
    assert legacy_history_reason({'drafts': None}, 'cyclone_123') is None


@pytest.mark.parametrize('state', [{'drafts': [{'event_id': OLD}]}, {'posted_events': [OLD]},
    {'publish_ledger': {OLD: {'phase': 'unknown'}}}])
def test_pre_draft_and_direct_save_hold_before_mutation(state):
    before = deepcopy(state)
    assert can_draft_candidate(state, SimpleNamespace(event_id=NEW))[0] is False
    assert save_draft('Synthetic thermal observation.', state, 'fire', NEW) is False
    assert state == before


@pytest.mark.parametrize('history', [{'posted_events': [OLD]}, {'drafts': [{'event_id': OLD, 'status': 'rejected'}]},
    {'publish_ledger': {OLD: {'phase': 'confirmed', 'tweet_id': 'receipt'}}},
    {'publish_ledger': {OLD: {'phase': 'not_sent', 'attempt_conflicts': [{'phase': 'unknown'}]}}}])
@pytest.mark.parametrize('mode', ['manual', 'auto', 'manual_route'])
def test_sender_and_due_paths_hold_before_state_write_or_platform(monkeypatch, history, mode):
    import importlib
    from unittest.mock import Mock
    from src.orchestrator import posting
    from src.state import DEFAULT_STATE
    from tests.revision_helpers import bind_reviewed_draft

    importlib.reload(posting)
    monkeypatch.setenv('THEHEAT_AUTOMATIC_PUBLICATION_ENABLED', '1')
    monkeypatch.setenv('THEHEAT_AUTOMATIC_PUBLICATION_EPOCH', 'offline-fire-history-test')
    draft = bind_reviewed_draft({'id': 'new-fire-draft', 'event_id': NEW, 'text': 'A synthetic thermal detection.',
        'status': 'pending', 'auto_approve_at': '2020-01-01T00:00:00Z',
        'approval_policy': {'mode': 'armed_auto', 'can_auto_approve': True}},
        'auto' if mode == 'auto' else 'manual', 'offline-intent' if mode != 'auto' else None)
    state = {**deepcopy(DEFAULT_STATE), **deepcopy(history)}
    state['drafts'] = [*state.get('drafts', []), draft]
    callbacks = {}
    for name in ('post_tweet', 'post_to_bluesky', 'run_safety_pipeline'):
        callbacks[name] = Mock(side_effect=AssertionError('External action must not run'))
        monkeypatch.setattr(posting, name, callbacks[name])
    write = Mock(side_effect=AssertionError('No state write'))
    monkeypatch.setattr(posting.state, 'write_state', write)
    monkeypatch.setattr(posting.state, 'check_daily_cap', lambda s: True)
    if mode == 'manual_route':
        monkeypatch.setenv('TWEET_TEXT', draft['text'])
        monkeypatch.setenv('DRAFT_ID', draft['id'])
        monkeypatch.setenv('PUBLISH_INTENT_ID', 'offline-intent')
        posting.run_manual_tweet(state)
        assert 'Fire history' in draft['post_error']
    elif mode == 'manual':
        assert posting.post_approved(draft, state) == 'failed'
        assert 'Fire history' in draft['post_error']
    else:
        posting.process_due_drafts(state)
        assert 'auto_approve_at' not in draft
        assert 'approval_binding' not in draft
    for call in [write, *callbacks.values()]:
        call.assert_not_called()
    assert state.get('publish_ledger') == history.get('publish_ledger', DEFAULT_STATE.get('publish_ledger'))


def test_enqueue_rejects_alias_before_queue_or_writer(monkeypatch):
    from unittest.mock import Mock
    from src.orchestrator import triage_queue
    from src.two_bot.intern.fire import build_fire_bundle
    from tests.fire_source_fixtures import fire_event
    bundle = build_fire_bundle(fire_event(lat=35.25, lon=-110.50))
    enqueue = Mock()
    monkeypatch.setattr(triage_queue, '_enqueue_candidate', enqueue)
    assert not triage_queue._enqueue_story_candidate({'posted_events': [OLD]}, bundle=bundle,
        event_id=NEW, score=None, source='firms', legacy_type='fire', review_context={})
    enqueue.assert_not_called()
