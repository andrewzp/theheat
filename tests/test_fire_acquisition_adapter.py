"""Invented CSVs exercise source adapter chronology and bounded diagnostics."""
from datetime import UTC, datetime, timedelta
import csv
import io
from types import SimpleNamespace
import traceback

import pytest
import requests

from src.data import firms
from src.data.fire_source_contract import FIRMS_PRODUCTS, HMS_PRODUCT, validate_event
from src.data.source_status import SourceFetchError
from tests.fire_source_fixtures import firms_row as source_row, hms_row

ACTIVE_PRODUCTS = ("VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT")


def firms_row(product="VIIRS_NOAA21_NRT", **kwargs):
    return source_row(product, **kwargs)

REFERENCE = datetime(2032, 3, 1, 0, 1, 42, tzinfo=UTC)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return REFERENCE.astimezone(tz) if tz is not None else REFERENCE.replace(tzinfo=None)


def csv_text(rows, fields=None):
    out = io.StringIO()
    fields = fields or list(rows[0])
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


@pytest.fixture(autouse=True)
def no_real_collection(monkeypatch):
    monkeypatch.setattr(firms, 'datetime', Clock)
    monkeypatch.setattr(firms, 'FIRMS_API_KEY', 'SYNTHETIC_MAP_KEY')
    monkeypatch.setattr(firms, 'reverse_geocode_simple', lambda *args: ('Synthetic region', 'US'))
    monkeypatch.setattr(firms, 'fetch_with_retry', lambda *a, **k: pytest.fail('Unexpected source request'))


def collect(monkeypatch, rows, product="VIIRS_NOAA21_NRT"):
    text = csv_text(rows)
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(text=text)
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    result = (firms._fetch_fires_hms(250) if product == HMS_PRODUCT else
              firms._fetch_fires_primary(80, 250, product, 2))
    assert len(calls) == 1
    return result


@pytest.mark.parametrize('product', ACTIVE_PRODUCTS)
def test_real_adapter_retains_yesterday_source_minute(monkeypatch, product):
    yesterday = REFERENCE - timedelta(minutes=2)
    event, = collect(monkeypatch, [firms_row(product, when=yesterday)], product)
    assert event.acquired_at == '2032-02-29T23:59:00Z'
    assert event.event_id.endswith('_2032-02-29_utc1')
    assert event.source_leg is None
    validate_event(event)


def test_fresh_low_value_row_cannot_refresh_stale_high_value(monkeypatch, capsys):
    stale = firms_row(when=REFERENCE-timedelta(days=3))
    low = {**firms_row(when=REFERENCE), 'frp': '1'}
    assert collect(monkeypatch, [stale, low]) == []
    assert 'stale=1' in capsys.readouterr().out


@pytest.mark.parametrize('change', [{'acq_time': '2400'}, {'satellite': 'N20'},
    {'frp': 'nan'}, {'acq_date': ''}, {'acq_date': '2032-03-02'}, {'acq_time': '0002'}])
def test_bad_row_does_not_destroy_valid_row(monkeypatch, change):
    valid = firms_row(when=REFERENCE)
    event, = collect(monkeypatch, [{**valid, **change}, valid])
    validate_event(event)


@pytest.mark.parametrize('delta', [-3, 1])
def test_wholly_out_of_time_response_fails_freshness(monkeypatch, delta):
    with pytest.raises(SourceFetchError, match='freshness check failed'):
        collect(monkeypatch, [firms_row(when=REFERENCE+timedelta(days=delta))])


def test_hms_file_date_is_distinct_from_row_acquisition(monkeypatch):
    event, = collect(monkeypatch, [hms_row(when=REFERENCE-timedelta(minutes=2))], HMS_PRODUCT)
    assert event.acquired_at == '2032-02-29T23:59:00Z'
    assert event.acquisition_provenance['source_url'].endswith('/2032/03/hms_fire20320301.txt')
    assert event.source_leg == 'noaa_hms'
    validate_event(event)


def test_hms_missing_frp_and_outside_region_are_valid_unselected(monkeypatch):
    row = hms_row(when=REFERENCE)
    assert collect(monkeypatch, [{**row, 'FRP': '-999.0'}, {**row, 'Lon': '100'}], HMS_PRODUCT) == []


@pytest.mark.parametrize('text', ['', 'latitude,longitude\n1,2\n',
    'latitude,latitude\n1,2\n', 'Lat,Lon,FRP\n1,2,3\n'])
def test_bad_header_fails_schema(text):
    with pytest.raises(SourceFetchError, match='schema drift'):
        firms._qualified_rows(text, "VIIRS_NOAA21_NRT", REFERENCE)


def test_empty_and_malformed_rows_are_different():
    row = firms_row(when=REFERENCE)
    header = csv_text([], list(row))
    assert firms._qualified_rows(header, "VIIRS_NOAA21_NRT", REFERENCE) == []
    with pytest.raises(SourceFetchError, match='no structurally valid'):
        firms._qualified_rows(header+'1,2\n', "VIIRS_NOAA21_NRT", REFERENCE)


@pytest.mark.parametrize('source,days', [('invented', 1), (HMS_PRODUCT, 1), ("VIIRS_NOAA21_NRT", True),
    ("VIIRS_NOAA21_NRT", 0), ("VIIRS_NOAA21_NRT", 6)])
def test_invalid_request_never_fetches(source, days):
    with pytest.raises(SourceFetchError, match='schema drift'):
        firms.fetch_fires(source=source, days=days, strict=True)


@pytest.mark.parametrize('status,count', [(400, 1), (401, 1), (403, 4), (404, 1),
    (410, 1), (429, 4), (500, 4), (503, 4)])
def test_public_http_failures_are_redacted_after_preserved_fallbacks(monkeypatch, status, count, capsys):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = status
        raise requests.HTTPError(f'{status} Server Error for url: {url} RAW_BODY_MARKER', response=response)
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    with pytest.raises(SourceFetchError) as caught:
        firms.fetch_fires(strict=True)
    assert len(calls) == count
    formatted = ''.join(traceback.format_exception(caught.value)) + capsys.readouterr().out
    assert 'SYNTHETIC_MAP_KEY' not in formatted
    assert 'RAW_BODY_MARKER' not in formatted
    assert firms.FIRMS_URL not in formatted
    assert 'fetch failed' in str(caught.value)


@pytest.mark.parametrize('error', [requests.Timeout('SYNTHETIC_MAP_KEY RAW_BODY_MARKER'),
    requests.ConnectionError('SYNTHETIC_MAP_KEY RAW_BODY_MARKER')])
def test_transport_and_witness_failures_are_redacted(monkeypatch, error):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        raise error
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    with pytest.raises(SourceFetchError) as caught:
        firms.fetch_fires(strict=True)
    assert len(calls) == 4
    assert 'SYNTHETIC_MAP_KEY' not in ''.join(traceback.format_exception(caught.value))
    assert 'RAW_BODY_MARKER' not in str(caught.value)


@pytest.mark.parametrize('status', [400, 401, 403, 404, 410, 429, 503])
def test_runner_failure_diagnostics_never_export_request_secrets(monkeypatch, status, capsys):
    import json
    from unittest.mock import Mock
    from src.orchestrator.sources import firms as runner
    def fetch(url, **kwargs):
        response = requests.Response()
        response.status_code = status
        raise requests.HTTPError(f'{status} for url: {url} RAW_BODY_MARKER', response=response)
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    record, errors = Mock(), Mock()
    monkeypatch.setattr(runner, '_record_source_run', record)
    monkeypatch.setattr(runner.state, 'log_error', errors)
    runner.run_firms({}, {'id': 'synthetic-run'})
    assert record.call_args.kwargs['status'] == 'failed'
    exported = json.dumps(record.call_args.kwargs) + str(errors.call_args) + capsys.readouterr().out
    assert 'SYNTHETIC_MAP_KEY' not in exported and 'RAW_BODY_MARKER' not in exported
    assert firms.FIRMS_URL not in exported


def test_runner_missing_configuration_is_skipped_without_backup(monkeypatch):
    from unittest.mock import Mock
    from src.orchestrator.sources import firms as runner
    monkeypatch.setattr(firms, 'FIRMS_API_KEY', '')
    record = Mock()
    monkeypatch.setattr(runner, '_record_source_run', record)
    runner.run_firms({}, None)
    assert record.call_args.kwargs['status'] == 'skipped'


def test_runner_review_and_news_use_source_time_and_typed_confidence(monkeypatch):
    from unittest.mock import Mock
    from src.orchestrator.sources import firms as runner
    from src.editorial import newsworthiness
    from tests.fire_source_fixtures import fire_event
    event = fire_event(when=REFERENCE-timedelta(days=1), frp=1500)
    monkeypatch.setattr(runner, '_fetch_strict', lambda *a, **k: [event])
    monkeypatch.setattr(runner.state, 'is_duplicate', lambda *a: False)
    monkeypatch.setattr(runner, '_should_draft', lambda *a: True)
    monkeypatch.setattr(runner, 'lat_lon_to_state', lambda *a: None)
    monkeypatch.setattr(newsworthiness, 'news_boost_enabled', lambda: True)
    news, review, enqueue, record = Mock(return_value={}), Mock(return_value={}), Mock(), Mock()
    monkeypatch.setattr(newsworthiness, 'plan_fire_boosts', news)
    monkeypatch.setattr(runner, '_review_context', review)
    monkeypatch.setattr(runner, '_enqueue_story_candidate', enqueue)
    monkeypatch.setattr(runner, '_record_source_run', record)
    runner.run_firms({}, None)
    assert news.call_args.args[1][0]['when'] == '2032-02-29'
    facts = review.call_args.kwargs['facts']
    assert any(f['value'] == 'high' for f in facts)
    assert not any(f['value'] == '95%' for f in facts)
    assert any(f['value'] == event.acquired_at for f in facts)
    assert enqueue.call_args.kwargs['bundle'].when == event.acquired_at
    assert record.call_args.kwargs['status'] == 'success'


def test_runner_legacy_hold_is_visible_and_remains_in_news_identity_batch(monkeypatch, capsys):
    from unittest.mock import Mock
    from src.orchestrator.sources import firms as runner
    from src.editorial import newsworthiness
    from tests.fire_source_fixtures import fire_event
    event = fire_event()
    monkeypatch.setattr(runner, '_fetch_strict', lambda *a, **k: [event])
    monkeypatch.setattr(newsworthiness, 'news_boost_enabled', lambda: True)
    news, enqueue, record = Mock(return_value={}), Mock(), Mock()
    monkeypatch.setattr(newsworthiness, 'plan_fire_boosts', news)
    monkeypatch.setattr(runner, '_enqueue_story_candidate', enqueue)
    monkeypatch.setattr(runner, '_record_source_run', record)
    runner.run_firms({'posted_events': [event.event_id.removesuffix('_utc1')]}, None)
    assert news.call_args.args[1][0]['id'] == event.event_id
    enqueue.assert_not_called()
    assert 'legacy_fire_already_posted=1' in capsys.readouterr().out
    assert record.call_args.kwargs['observed'] == 1 and record.call_args.kwargs['promoted'] == 0


def test_credential_related_403_stays_nonwitnessable_and_redacted(monkeypatch):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError(f'403 credential rejected: {url} RAW_BODY_MARKER', response=response)
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    with pytest.raises(SourceFetchError) as caught:
        firms.fetch_fires(strict=True)
    assert len(calls) == 1
    assert 'SYNTHETIC_MAP_KEY' not in ''.join(traceback.format_exception(caught.value))
    assert str(caught.value).endswith('HTTP 403')


def test_exhausted_products_then_malformed_hms_has_bounded_schema_diagnostic(monkeypatch):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if '/hms_fire' in url:
            return SimpleNamespace(text='SYNTHETIC_MAP_KEY,RAW_BODY_MARKER\n1,2\n')
        raise requests.Timeout(f'{url} RAW_BODY_MARKER')
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    with pytest.raises(SourceFetchError) as caught:
        firms.fetch_fires(strict=True)
    assert len(calls) == 4
    assert 'schema drift' in str(caught.value)
    formatted = ''.join(traceback.format_exception(caught.value))
    assert 'SYNTHETIC_MAP_KEY' not in formatted and 'RAW_BODY_MARKER' not in formatted


def test_unknown_failure_is_visible_without_exporting_exception_body(monkeypatch):
    def fetch(*args, **kwargs):
        raise RuntimeError('SYNTHETIC_MAP_KEY RAW_BODY_MARKER')
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    with pytest.raises(SourceFetchError, match='unknown failure') as caught:
        firms.fetch_fires(strict=True)
    assert 'SYNTHETIC_MAP_KEY' not in ''.join(traceback.format_exception(caught.value))
