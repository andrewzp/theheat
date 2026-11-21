"""Invented prior-record contradictions at actual factual/pipeline consumers.

Only SDK factories are faked in generation tests. A matching local floor is
not a completed model verdict, and no test sends or establishes weather truth.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
import re
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from src.data.temperature_evidence import ghcn_record_point_failures
from src.state import DEFAULT_STATE
from src.two_bot import ghcn_claim_contract as compact, pipeline
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.ghcn_readable_warrant import prepare_bundle
from tests import ghcn_graphic_helpers as helpers
from tests.ghcn_claim_contract_helpers import reference
from tests.test_observed_copy_guard_journey import _models

VARIANTS = [(d, t) for d in ('high', 'low') for t in ('all_time', 'monthly', 'calendar')]
FORMS = ('full', 'readable', 'compact')


def _cell(payload, year, month, element, day, value):
    prefix = f'{helpers.STATION["station_id"]}{year:04d}{month:02d}{element}'.encode()
    rows = payload.splitlines()
    selected = [i for i, row in enumerate(rows) if row.startswith(prefix)]
    assert len(selected) == 1
    i = selected[0]
    offset = 21 + (day - 1) * 8
    rows[i] = rows[i][:offset] + f'{value:5d}'.encode() + rows[i][offset+5:]
    return b'\n'.join(rows)


@pytest.fixture(scope='module')
def archive():
    # Different all-time/month/calendar comparators from the REAL archive
    # parser/threshold/detector/builders. No hand-authored passing warrant.
    payload = helpers.source_archive()
    for element, archive, calendar in [('TMAX', 390, 370), ('TMIN', -150, -80)]:
        payload = _cell(payload, 2021, 1, element, 1, archive)
        payload = _cell(payload, 2020, 9, element, 3, calendar)
    return payload


@pytest.fixture(scope='module')
def records(archive):
    with patch.object(helpers, 'source_archive', return_value=archive):
        result = {key: helpers.graphic_bundles(direction=key[0], tier=key[1]) for key in VARIANTS}
    for key, bundles in result.items():
        assert ghcn_record_point_failures(bundles[0]) == [], key
        assert audit_story_bundle(bundles[0]).prompt_ready, key
    return result


def variant(records, key, form='full'):
    bundle = deepcopy(records[key][0])
    if form == 'readable':
        return prepare_bundle(bundle)
    if form == 'compact':
        direction, tier = key
        field = f'{tier}_{direction}' if tier != 'calendar' else f'calendar_date_{direction}'
        ref = reference(bundle, field)
        return compact.project(bundle, ref, ref['selection'])
    return bundle


def copy_for(bundle, *, value=None, year=None, unit='C', precision=1):
    raw = bundle.raw_signal_dump
    old = Decimal(str(raw['old_record_c']))
    if unit == 'F':
        old = old * Decimal('1.8') + 32
    if value is None:
        value = format(old.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN), 'f')
    year = raw['old_record_year'] if year is None else year
    return (f'Graphic Fixture {raw["new_temp_c"]}°C on 3 September: {_label(bundle)} '
            f'in the available GHCN archive through 2026-09-02; previous record {value}°{unit} in {year}.')


def _label(bundle):
    adjective = bundle.raw_signal_dump['kind']
    if bundle.signal_kind.startswith('open_meteo_archive_'):
        return f'archive {adjective}'
    if bundle.signal_kind.startswith('monthly_'):
        return f'September record {adjective}'
    return f'record {adjective} for {int(bundle.when[-2:])} September'


@pytest.mark.parametrize('key', VARIANTS)
@pytest.mark.parametrize('form', FORMS)
@pytest.mark.parametrize('wrong', ('value', 'year'))
def test_explicit_wrong_previous_record_refuses_at_actual_local_factual_consumer(records, key, form, wrong):
    bundle = variant(records, key, form)
    raw = bundle.raw_signal_dump
    copy = copy_for(bundle, value=str(raw['old_record_c']+5) if wrong == 'value' else None,
                    year=raw['old_record_year']-7 if wrong == 'year' else None)
    result = pipeline.fact_check.local_rejection(copy, [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and not result.passed
    assert any('previous_record_' + ('value' if wrong == 'value' else 'year') + '_mismatch' in r for r in result.failures)


@pytest.mark.parametrize('key', VARIANTS)
@pytest.mark.parametrize('form', FORMS)
def test_matching_prior_record_still_needs_normal_factual_verification(records, key, form):
    bundle = variant(records, key, form)
    assert pipeline.fact_check.local_rejection(copy_for(bundle), [], bundle, deepcopy(DEFAULT_STATE)) is None


@pytest.mark.parametrize('key', VARIANTS)
@pytest.mark.parametrize('unit,precision', [('C', 0), ('C', 2), ('F', 0), ('F', 1), ('F', 2)])
def test_display_precision_and_unit_conversion_preserve_matching_statement(records, key, unit, precision):
    bundle = variant(records, key)
    text = copy_for(bundle, unit=unit, precision=precision)
    assert pipeline.fact_check.local_rejection(text, [], bundle, deepcopy(DEFAULT_STATE)) is None
    signed = re.sub(r'(?<!\d)-(?=\d+(?:\.\d+)?°)', '−', text)
    assert pipeline.fact_check.local_rejection(signed, [], bundle, deepcopy(DEFAULT_STATE)) is None


@pytest.mark.parametrize('key', VARIANTS)
def test_wrong_prior_refuses_before_paid_checks_and_enabled_editorial_pass(monkeypatch, records, key):
    bundle = deepcopy(records[key][-1])
    raw = bundle.raw_signal_dump
    text = (f'Graphic Fixture {raw["new_temp_c"]}°C on 8 September: {_label(bundle)} '
            f'in the available GHCN archive through 2026-09-07; previous record {raw["old_record_c"]+5}°C.')
    models = _models(monkeypatch, copy=text)
    outcome = {}
    with freeze_time('2026-09-09T12:00:00Z', tick=True):
        result = pipeline.generate_draft(bundle, deepcopy(DEFAULT_STATE), result_out=outcome)
    assert result is None
    assert models.stages() == ['writer'], outcome
    assert outcome['kill_stage'] == 'fact_check'
    assert 'previous_record_value_mismatch' in outcome['kill_reason']


@pytest.mark.parametrize('key', VARIANTS)
def test_matching_prior_reaches_every_required_checker_once(monkeypatch, records, key):
    bundle = deepcopy(records[key][-1])
    raw = bundle.raw_signal_dump
    text = (f'Graphic Fixture {raw["new_temp_c"]}°C on 8 September: {_label(bundle)} '
            f'in the available GHCN archive through 2026-09-07; previous record {raw["old_record_c"]}°C in {raw["old_record_year"]}.')
    models = _models(monkeypatch, copy=text)
    outcome = {}
    with freeze_time('2026-09-09T12:00:00Z', tick=True):
        result = pipeline.generate_draft(bundle, deepcopy(DEFAULT_STATE), result_out=outcome)
    assert result is not None, outcome
    assert result['text'] == text
    assert models.stages() == ['writer', 'safety', 'fact_check', 'critic']


def _with_clause(bundle, clause):
    return copy_for(bundle).split('; previous record', 1)[0] + '; ' + clause + '.'


@pytest.mark.parametrize('anchor', ['previous record', 'prior record', 'the previous record', 'beating the previous record', 'previous all-time record', 'previous station record', 'previous archive record'])
@pytest.mark.parametrize('connector', [' ', ' of ', ' was ', ' stood at ', ': ', '= '])
def test_recognized_positive_value_grammar_cannot_reuse_a_stale_number(records, anchor, connector):
    bundle = variant(records, ('high', 'all_time'))
    text = _with_clause(bundle, anchor+connector+'34.0°C in 2020')
    result = pipeline.fact_check.local_rejection(text, [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and any('previous_record_value_mismatch' in r for r in result.failures)


@pytest.mark.parametrize('wording', ['previous record in 2013', 'prior record from 2013', 'the previous record was set in 2013', 'prior record 39°C set in 2013'])
def test_explicit_year_alone_or_after_a_value_is_bound(records, wording):
    bundle = variant(records, ('high', 'all_time'))
    result = pipeline.fact_check.local_rejection(_with_clause(bundle, wording), [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and any('previous_record_year_mismatch' in r for r in result.failures)


@pytest.mark.parametrize('wording', [
    'previous record was not 34°C in 2020', 'not the previous record 34°C in 2020',
    'if the previous record was 34°C in 2020', 'previous record 34°C or 35°C',
    '"previous record 34°C in 2020"', 'previous record about 34°C in 2020',
    'previous record 34–35°C in 2020', 'previous record 34.000°C in 2020',
    'previous record thirty-four degrees in 2020',
    'an old record 38°C in 2020', 'former record 38°C in 2020',
    'a previous record 38°C in 2020', 'the previous record 38°C in 2020 was overturned',
    "the station's previous record 38°C in 2020",
])
def test_outside_bounded_assertion_grammar_still_reaches_required_model_boundary(records, wording):
    from src.evaluation.historical import VerificationRequired, offline_boundaries

    bundle = variant(records, ('high', 'all_time'))
    with offline_boundaries() as calls:
        with pytest.raises(VerificationRequired):
            pipeline.fact_check.fact_check(_with_clause(bundle, wording), [], bundle, deepcopy(DEFAULT_STATE))
        assert calls['checker_boundary_reached'] == 1
        assert calls['unexpected_boundary_attempts'] == 0


@pytest.mark.parametrize('prefix', ['"a quoted older claim"', 'no earlier source comparison', 'if a later revision appears'])
def test_another_clause_cannot_mask_a_recognizable_wrong_comparator(records, prefix):
    bundle = variant(records, ('high', 'all_time'))
    text = _with_clause(bundle, prefix+'; previous record 34°C in 2020')
    result = pipeline.fact_check.local_rejection(text, [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and any('previous_record_value_mismatch' in r for r in result.failures)


def test_explicit_definite_previous_record_clause_is_recognized(records):
    bundle = variant(records, ('high', 'all_time'))
    result = pipeline.fact_check.local_rejection(_with_clause(bundle, 'the previous record 34°C in 2020'), [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and any('previous_record_value_mismatch' in r for r in result.failures)


@pytest.mark.parametrize('key,scope', [(('high', 'monthly'), 'all-time'), (('low', 'calendar'), 'monthly')])
def test_a_different_explicit_comparison_scope_is_never_bound_to_the_selected_one(records, key, scope):
    from src.evaluation.historical import VerificationRequired, offline_boundaries

    bundle = variant(records, key)
    with offline_boundaries() as calls:
        with pytest.raises(VerificationRequired):
            pipeline.fact_check.fact_check(_with_clause(bundle, f'previous {scope} record 34°C in 2020'), [], bundle, deepcopy(DEFAULT_STATE))
        assert calls['checker_boundary_reached'] == 1 and calls['unexpected_boundary_attempts'] == 0


@pytest.mark.parametrize('key', VARIANTS)
def test_matching_year_and_unrelated_numbers_dates_plus_sign_do_not_false_reject(records, key):
    bundle = variant(records, key)
    old = bundle.raw_signal_dump['old_record_c']
    year = bundle.raw_signal_dump['old_record_year']
    value = f'{old:+.2f}'
    text = _with_clause(bundle, f'context 1999, 2026-09-03 and 41°C; previous record {value}°C in {year}')
    assert pipeline.fact_check.local_rejection(text, [], bundle, deepcopy(DEFAULT_STATE)) is None


@pytest.mark.parametrize('field', ['value', 'year', 'history'])
def test_caller_projections_cannot_replace_the_selected_baseline_scalar(records, field):
    bundle = variant(records, ('high', 'all_time'))
    if field == 'value':
        bundle.raw_signal_dump['old_record_c'] += 5
    elif field == 'year':
        bundle.raw_signal_dump['old_record_year'] -= 7
    else:
        bundle.historical_context['prior_record_c'] += 5
    assert not audit_story_bundle(bundle).prompt_ready
    result = pipeline.fact_check.local_rejection(copy_for(bundle), [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and not result.passed
    assert any('previous_record_unqualified' in r for r in result.failures)


def test_display_comparison_does_not_inherit_ambient_decimal_precision(records):
    from decimal import localcontext

    bundle = variant(records, ('high', 'all_time'))
    text = copy_for(bundle, unit='F', precision=1)
    with localcontext() as context:
        context.prec = 2
        assert pipeline.fact_check.local_rejection(text, [], bundle, deepcopy(DEFAULT_STATE)) is None


def test_an_older_record_is_not_misbound_to_the_immediately_preceding_one(records, archive):
    from src.data import ghcn
    from src.data.ghcn_format import DailyObs
    from src.evaluation.historical import VerificationRequired, offline_boundaries

    snapshot = ghcn._archive_snapshot(helpers.STATION['station_id'], archive, helpers.AS_OF)
    thresholds, accepted = ghcn._thresholds_from_verified_archive(helpers.STATION['station_id'],
        [DailyObs(helpers.STATION['station_id'], date(2021, 1, 1), 'TMAX', 39.0)], snapshot)
    earlier = ghcn._detect_signals_for_station(helpers.STATION, accepted, thresholds).all_time_high
    assert earlier is not None and earlier.old_record_c == 38.0 and earlier.old_record_year == 2020
    bundle = variant(records, ('high', 'all_time'))
    assert bundle.raw_signal_dump['old_record_c'] == 39.0 and bundle.raw_signal_dump['old_record_year'] == 2021
    with offline_boundaries() as calls:
        with pytest.raises(VerificationRequired):
            pipeline.fact_check.fact_check(_with_clause(bundle, 'an old record 38°C in 2020'), [], bundle, deepcopy(DEFAULT_STATE))
        assert calls['checker_boundary_reached'] == 1 and calls['unexpected_boundary_attempts'] == 0


@pytest.mark.parametrize('clause', [
    'The archived bulletin read “New high; previous record 38°C in 2020.”',
    'The archived bulletin read "New high; previous record 38°C in 2020."',
    "The archived bulletin read 'New high; previous record 38°C in 2020.'",
    'Previous record 38°C in 2020?',
    'Previous record 38°C in 2020; was that correct?',
    'Previous record 38°C in 2020; or was it 39°C?',
    'The archived note (New high; previous record 38°C in 2020.)',
    'The archived note [New high; previous record 38°C in 2020.]',
    'The archived note (nested [New high; previous record 38°C in 2020.])',
])
def test_quoted_or_question_context_survives_clause_boundaries(records, clause):
    from src.evaluation.historical import VerificationRequired, offline_boundaries

    bundle = variant(records, ('high', 'all_time'))
    with offline_boundaries() as calls:
        with pytest.raises(VerificationRequired):
            pipeline.fact_check.fact_check(_with_clause(bundle, clause), [], bundle, deepcopy(DEFAULT_STATE))
        assert calls['checker_boundary_reached'] == 1 and calls['unexpected_boundary_attempts'] == 0


@pytest.mark.parametrize('context', [
    'Archived text “New high; previous record 38°C in 2020.”;',
    'Archived text "New high; previous record 38°C in 2020.";',
    'Previous record 38°C in 2020?',
])
def test_separate_affirmative_comparator_after_quote_or_question_still_refuses(records, context):
    bundle = variant(records, ('high', 'all_time'))
    result = pipeline.fact_check.local_rejection(_with_clause(bundle, context+' previous record 34°C in 2021'), [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and any('previous_record_value_mismatch' in r for r in result.failures)
    assert not any('previous_record_year_mismatch' in r for r in result.failures)


@pytest.mark.parametrize('quotes', [('“', '”'), ('"', '"'), ("'", "'")])
@pytest.mark.parametrize('ending', ['.', '!', '?'])
def test_direct_sentence_after_terminal_punctuation_inside_quote_is_checked(records, quotes, ending):
    bundle = variant(records, ('high', 'all_time'))
    opening, closing = quotes
    context = f'The archived note read {opening}New high; previous record 38°C in 2020{ending}{closing} '
    result = pipeline.fact_check.local_rejection(_with_clause(bundle, context+'Previous record 34°C in 2021'), [], bundle, deepcopy(DEFAULT_STATE))
    assert result is not None and any('previous_record_value_mismatch' in r for r in result.failures)
    assert not any('previous_record_year_mismatch' in r for r in result.failures)


def test_quoted_terminal_punctuation_at_physical_end_still_needs_model(records):
    from src.evaluation.historical import VerificationRequired, offline_boundaries

    bundle = variant(records, ('high', 'all_time'))
    prefix = copy_for(bundle).split('; previous record', 1)[0]
    text = prefix+'; The archived note read “New high; previous record 38°C in 2020.”'
    with offline_boundaries() as calls:
        with pytest.raises(VerificationRequired):
            pipeline.fact_check.fact_check(text, [], bundle, deepcopy(DEFAULT_STATE))
        assert calls['checker_boundary_reached'] == 1 and calls['unexpected_boundary_attempts'] == 0
