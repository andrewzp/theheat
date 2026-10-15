"""P14 dependency proof on genuine native-media drafts, separate from GHCN science.

This deliberately does not label a radar draft or its receipts as temperature.
The GHCN source command/lock proof lives in test_postgres_ghcn_source_results.
"""
from copy import deepcopy

import pytest

from src.commands import postgres_delivery as delivery, postgres_ghcn_source_results as ghcn
from tests import test_postgres_delivery as transport
from tests import test_postgres_editor_media as editor
from tests import test_postgres_candidate_admission as candidate
from tests.local_delivery_helpers import fixture_server
from tests.test_postgres_delivery import admitted as admitted
from tests.radar_editor_helpers import radar_case as radar_case
from tests.test_postgres_editor_media import offline_connections as offline_connections
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies


def dependency(store,targets):
    with store.projections._connection() as connection:
        store._validate(connection)
        store._state(connection,lock=True)
        return ghcn.delivery_dependency(store,connection,targets)


@pytest.mark.parametrize('mode',['normal','drop','rejected','receipt_failure'])
def test_original_parked_media_receipts_and_same_event_lookup_are_exact(admitted,core,tmp_path,monkeypatch,mode):
    case=admitted
    _,png=editor.prepare_and_attach(case)
    core[2].initialize_delivery(now=editor.AT)
    behavior={('x','create'): mode if mode!='receipt_failure' else 'normal'}
    with fixture_server(png,case['text'],mode=behavior) as (config,trace,_):
        transport.configure(case['store'],tmp_path,config)
        transport.bind_platform(case,monkeypatch)
        _,result=transport.park(case)
        assert result['status']=='applied'
        intent=result['delivery']['intent_id']
        for key in ('ANTHROPIC_API_KEY','GEMINI_API_KEY'):
            monkeypatch.delenv(key,raising=False)
        original=case['store'].read()
        target=next(d for d in original[1]['drafts'] if d['id']==case['draft_id'])
        empty=dependency(case['store'],[target])
        assert len(empty['rows']['intents'])==1 and empty['rows']['attempts']==empty['protection_codes']==[]
        for stage in ('upload','alt'):
            assert transport.run(case,intent,'x',stage)['outcome']=='confirmed'
        before_create=dependency(case['store'],[target])
        assert before_create!=empty and before_create['protection_codes']==[]
        if mode=='receipt_failure':
            original_finish=delivery.finish
            def interrupted(*args):
                original_finish(*args)
                raise RuntimeError('invented receipt commit fault after actual response')
            with monkeypatch.context() as patch:
                patch.setattr(delivery,'finish',interrupted)
                outcome=transport.run(case,intent,'x','create')
        else:
            outcome=transport.run(case,intent,'x','create')
        expected={'normal':'confirmed','drop':'unknown','rejected':'not_sent','receipt_failure':'unknown'}[mode]
        assert outcome['outcome']==expected,outcome
        after=dependency(case['store'],[target])
        assert after!=before_create and case['store'].read()==original
        assert len(after['rows']['attempts'])==3
        assert len(trace)==3 and all(row['method']=='POST' for row in trace)
        expected_code={'normal':'delivery_event_already_confirmed','drop':'delivery_prior_outcome_unknown',
                       'rejected':None,'receipt_failure':'delivery_prior_outcome_unknown'}[mode]
        assert after['protection_codes']==([] if expected_code is None else [dict(draft_id=target['id'],event_id=target['event_id'],code=expected_code)])
        # This is a legitimate predicate probe of the original intent's event,
        # not a relabelled source draft or a manufactured delivery receipt.
        sibling=deepcopy(target)
        sibling['id']='another-draft-for-same-existing-event'
        sibling_read=dependency(case['store'],[sibling])
        assert sibling_read['rows']==after['rows'] and sibling_read['artifacts']==after['artifacts']
        assert sibling_read['outcomes']==after['outcomes']
        with case['store'].projections._connection() as connection:
            if expected_code:
                with pytest.raises(delivery.CommandError) as refusal:
                    delivery.hold(connection,sibling)
                assert refusal.value.code==expected_code
            else:
                delivery.hold(connection,sibling)
        unrelated=dependency(case['store'],[dict(id='unrelated-draft',event_id='unrelated-event')])
        assert all(rows==[] for rows in unrelated['rows'].values()) and unrelated['protection_codes']==[]
        if mode=='receipt_failure':
            # The raw response is independently durable without its receipt.
            assert len(after['rows']['observations'])==3 and len(after['rows']['receipts'])==2
            recovered=transport.run(case,intent,'x','create')
            assert recovered['outcome']=='confirmed' and recovered['network_mutation'] is False
            final=dependency(case['store'],[target])
            assert len(final['rows']['receipts'])==3 and final!=after and len(trace)==3
        else:
            replay=transport.run(case,intent,'x','create')
            assert replay['outcome']==expected and replay['network_mutation'] is False and len(trace)==3
        assert case['store'].read()==original
