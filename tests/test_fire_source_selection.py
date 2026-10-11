"""Actual parser/runner selection with invented rows and no source/provider I/O."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import csv
import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import responses

from src.data import firms
from src.data.fire_source_contract import freshness, validate_event
from src.data.source_status import SourceFetchError, SourceSkipped
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.fire import build_fire_bundle
from tests.fire_source_fixtures import fire_event, firms_row, hms_row

N21, N20, MODIS, SNPP = 'VIIRS_NOAA21_NRT', 'VIIRS_NOAA20_NRT', 'MODIS_NRT', 'VIIRS_SNPP_NRT'
SEQUENCES = {N21: [N21, N20, MODIS], N20: [N20, N21, MODIS], MODIS: [MODIS]}
NOW = datetime(2026, 11, 2, 13, tzinfo=UTC)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def packet(product, *, empty=False):
    row = hms_row(when=NOW) if product == 'HMS' else firms_row(product, when=NOW)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(row))
    writer.writeheader()
    if not empty:
        writer.writerow(row)
    return out.getvalue()


@pytest.fixture
def collection(monkeypatch):
    monkeypatch.setattr(firms, 'datetime', Clock)
    monkeypatch.setattr(firms, 'FIRMS_API_KEY', 'synthetic-selection-key')
    monkeypatch.setattr(firms, 'reverse_geocode_simple', lambda *args: ('Synthetic place', 'US'))
    replies, calls = {}, []

    def fetch(url, **kwargs):
        product = 'HMS' if '/hms_fire' in url else url.split('/')[-3]
        calls.append(product)
        assert kwargs == {'timeout': 30}
        assert product in replies, f'Unexpected source request: {product}'
        reply = replies[product]
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)

    monkeypatch.setattr(firms, 'fetch_with_retry', fetch)
    return replies, calls


@pytest.mark.parametrize('clock', [datetime(2026, 10, 7, tzinfo=UTC), NOW-timedelta(minutes=1), NOW,
    NOW+timedelta(minutes=1), datetime(2032, 3, 1, tzinfo=UTC)])
def test_default_noaa21_success_has_one_request_and_exact_healthy_provenance(collection, monkeypatch, clock):
    monkeypatch.setattr(__import__(__name__, fromlist=['NOW']), 'NOW', clock)
    replies, calls = collection
    replies[N21] = packet(N21)
    event, = firms.fetch_fires(strict=True)
    assert calls == [N21] and event.source_leg is None
    row = validate_event(event)
    assert row.source_product == N21 and row.record['satellite'] == 'N21'
    assert build_fire_bundle(event).when == clock.isoformat(timespec='seconds').replace('+00:00', 'Z')


@pytest.mark.parametrize('source', [N21, N20, MODIS])
def test_explicit_first_product_stays_healthy(collection, source):
    replies, calls = collection
    replies[source] = packet(source)
    event, = firms.fetch_fires(source=source, strict=True)
    assert calls == [source] and event.source_leg is None
    assert validate_event(event).source_product == source


@pytest.mark.parametrize('source,target', [(N21, N20), (N21, MODIS), (N20, N21), (N20, MODIS)])
@pytest.mark.parametrize('failure', ['empty', 'timeout'])
def test_each_allowed_alternative_keeps_its_own_source_time(collection, source, target, failure):
    replies, calls = collection
    sequence = SEQUENCES[source][:SEQUENCES[source].index(target)+1]
    for product in sequence[:-1]:
        replies[product] = packet(product, empty=True) if failure == 'empty' else requests.Timeout('synthetic outage')
    replies[target] = packet(target)
    event, = firms.fetch_fires(source=source, strict=True)
    assert calls == sequence and event.source_leg == target
    row = validate_event(event)
    assert row.source_product == target and row.acquired_at == '2026-11-02T13:00:00Z'
    bundle = build_fire_bundle(event)
    assert bundle.raw_signal_dump['source_product'] == target
    assert audit_story_bundle(bundle).prompt_ready
    assert not any(f['label'] == 'evidence_grade' for f in bundle.current_facts)


@pytest.mark.parametrize('source', [N21, N20, MODIS])
def test_all_empty_never_requests_hms(collection, source):
    replies, calls = collection
    replies.update({p: packet(p, empty=True) for p in SEQUENCES[source]})
    assert firms.fetch_fires(source=source, strict=True) == []
    assert calls == SEQUENCES[source]


@pytest.mark.parametrize('empty_index', [0, 1, 2])
def test_one_reachable_empty_prevents_host_outage_inference(collection, empty_index):
    replies, calls = collection
    replies.update({p: requests.Timeout('synthetic outage') for p in SEQUENCES[N21]})
    empty = SEQUENCES[N21][empty_index]
    replies[empty] = packet(empty, empty=True)
    assert firms.fetch_fires(strict=True) == []
    assert calls == SEQUENCES[N21]


@pytest.mark.parametrize('source', [N21, N20, MODIS])
def test_all_outages_reach_hms_once_with_its_own_receipt(collection, source):
    replies, calls = collection
    replies.update({p: requests.Timeout('synthetic outage') for p in SEQUENCES[source]})
    replies['HMS'] = packet('HMS')
    event, = firms.fetch_fires(source=source, strict=True)
    assert calls == SEQUENCES[source] + ['HMS']
    assert event.source_leg == 'noaa_hms'
    assert validate_event(event).confidence_kind == 'unavailable'
    assert audit_story_bundle(build_fire_bundle(event)).prompt_ready


@pytest.mark.parametrize('failure', ['400', '401', '404', '410', 'credential403', 'schema', 'wrong_satellite'])
def test_access_or_schema_failure_does_not_hide_behind_alternatives(collection, failure):
    replies, calls = collection
    if failure == 'schema':
        replies[N21] = 'not,the,required,header\n'
    elif failure == 'wrong_satellite':
        replies[N21] = packet(N20)
    else:
        response = requests.Response()
        response.status_code = 403 if failure == 'credential403' else int(failure)
        replies[N21] = requests.HTTPError('credential rejected' if failure == 'credential403' else 'synthetic error', response=response)
    with pytest.raises(SourceFetchError):
        firms.fetch_fires(strict=True)
    assert calls == [N21]


@pytest.mark.parametrize('source', ['unknown-product', None, True, [], {}])
def test_unknown_selection_stays_a_visible_failure_without_requests(collection, source):
    with pytest.raises(SourceFetchError, match='schema drift'):
        firms.fetch_fires(source=source, strict=True)
    assert collection[1] == []


@pytest.mark.parametrize('clock', [datetime(2026, 10, 7, tzinfo=UTC), NOW-timedelta(minutes=1), NOW,
    NOW+timedelta(minutes=1), datetime(2032, 3, 1, tzinfo=UTC)])
@pytest.mark.parametrize('strict', [False, True])
@pytest.mark.parametrize('configured', [False, True])
def test_retired_explicit_selection_has_zero_requests_at_every_clock(collection, monkeypatch, clock, strict, configured):
    replies, calls = collection
    monkeypatch.setattr(__import__(__name__, fromlist=['NOW']), 'NOW', clock)
    monkeypatch.setattr(firms, 'FIRMS_API_KEY', 'synthetic-selection-key' if configured else '')
    if strict:
        with pytest.raises(SourceSkipped, match='no longer collects S-NPP; select VIIRS_NOAA21_NRT'):
            firms.fetch_fires(source=SNPP, strict=True)
    else:
        assert firms.fetch_fires(source=SNPP) == []
    assert calls == [] and replies == {}


@pytest.mark.parametrize('clock', [NOW-timedelta(days=365), NOW, NOW+timedelta(days=3650)])
@pytest.mark.parametrize('entry', [firms._fetch_fires_primary, firms._fetch_fires_product_chain])
def test_direct_collectors_cannot_bypass_retirement(collection, monkeypatch, clock, entry):
    monkeypatch.setattr(__import__(__name__, fromlist=['NOW']), 'NOW', clock)
    with pytest.raises(SourceSkipped, match='no longer collects S-NPP'):
        entry(80, 250, SNPP, 1)
    assert collection[1] == []


@pytest.mark.parametrize('leg', [None, SNPP])
def test_historical_snpp_packet_still_validates_without_mutation(leg):
    original_time = datetime(2026, 10, 7, 12, tzinfo=UTC)
    event = fire_event(when=original_time, product=SNPP, leg=leg)
    before = deepcopy(event)
    row = validate_event(event)
    assert freshness(row, original_time) == 'fresh'
    bundle = build_fire_bundle(event)
    assert bundle.raw_signal_dump['source_name'] == 'NASA FIRMS'
    assert bundle.raw_signal_dump['source_product'] == SNPP
    assert audit_story_bundle(bundle).prompt_ready
    assert event == before


@pytest.mark.parametrize('fallback', [False, True])
def test_actual_runner_reports_selected_primary_or_degraded_leg(collection, monkeypatch, fallback):
    from src.orchestrator.sources import firms as runner
    from src.editorial import newsworthiness
    replies, calls = collection
    replies[N21] = packet(N21, empty=fallback)
    if fallback:
        replies[N20] = packet(N20)
    monkeypatch.setattr(newsworthiness, 'news_boost_enabled', lambda: False)
    monkeypatch.setattr(runner, '_should_draft', lambda *args: True)
    monkeypatch.setattr(runner, 'lat_lon_to_state', lambda *args: None)
    record, enqueue, review = Mock(), Mock(return_value=True), Mock(return_value={})
    monkeypatch.setattr(runner, '_record_source_run', record)
    monkeypatch.setattr(runner, '_enqueue_story_candidate', enqueue)
    monkeypatch.setattr(runner, '_review_context', review)
    runner.run_firms({}, None)
    assert record.call_args.kwargs['status'] == ('degraded' if fallback else 'success')
    if fallback:
        assert N20 in record.call_args.kwargs['note']
    bundle = enqueue.call_args.kwargs['bundle']
    assert bundle.raw_signal_dump['source_product'] == (N20 if fallback else N21)
    assert audit_story_bundle(bundle).prompt_ready
    assert dict((f['label'], f['value']) for f in review.call_args.kwargs['facts'])['Source product'] == (N20 if fallback else N21)
    assert calls == ([N21, N20] if fallback else [N21])


@responses.activate
def test_real_retry_helper_retains_three_attempts_per_active_product(monkeypatch):
    from src.data._http import fetch_with_retry
    monkeypatch.setattr(firms, 'FIRMS_API_KEY', 'synthetic-selection-key')
    monkeypatch.setattr(firms, 'datetime', Clock)
    monkeypatch.setattr(firms, 'fetch_with_retry', fetch_with_retry)
    expected = []
    for product in SEQUENCES[N21]:
        url = f'{firms.FIRMS_URL}/synthetic-selection-key/{product}/world/1'
        for _ in range(3):
            responses.add(responses.GET, url, status=503)
            expected.append(url)
    hms_url = f'{firms.HMS_FIRE_URL}/{NOW:%Y/%m}/hms_fire{NOW:%Y%m%d}.txt'
    responses.add(responses.GET, hms_url, body=packet('HMS', empty=True), status=200)
    assert firms.fetch_fires(strict=True) == []
    assert [call.request.url for call in responses.calls] == expected + [hms_url]
