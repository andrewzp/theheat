"""Invented NOAA replies: hints nominate archives and never supply observations."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import http.client
from unittest.mock import patch

from freezegun import freeze_time
import requests
import pytest
from urllib3.response import HTTPResponse as RawHTTPResponse

from dashboard.tests.fixtures.ghcn_archive_intake_producer import NOW, archive_bytes
from src.data import ghcn
from src.data import ghcn_discovery as discovery
from src.data.ghcn_db import open_db, upsert_thresholds
from src.data.ghcn_format import DiffRecord, StationThresholds, compute_thresholds, parse_dly_text
from src.data.temperature_history import record_observation_revision
from src.storage.ghcn_runtime_inputs import InventedResponse, ReplayIO, configuration
from tests.ghcn_intake_cases import SID

API = "https://www.ncei.noaa.gov/access/services/data/v1"
TARGET = "SFX00000002"
DAY = date(2026, 11, 18)
METADATA = [
    {"station_id": SID, "name": "INVENTED TRACKED STATION", "country_code": "BR",
     "country_name": "Brazil", "state": "", "lat": -10.0, "lon": -50.0},
    {"station_id": TARGET, "name": "INVENTED NEW STATION", "country_code": "ZA",
     "country_name": "South Africa", "state": "", "lat": -25.0, "lon": 28.0},
]


class Raw(BytesIO):
    def read1(self, size=-1, *, decode_content=False):
        assert not decode_content
        return super().read1(size)


class Reply:
    def __init__(self, data, status=200):
        self.content = data
        self.status_code = status
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(data))}
        self.raw = Raw(data)
        self.history = []
        self.closed = 0

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def close(self):
        self.closed += 1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


def invoke(tmp_path, *, hint_value=49, payload=None, limit=20, hint_status=200, hint_body=None,
           tracked_payload=None, runtime=False, injected=None, diff_status=404, stations=None, extra_stations=0,
           on_hint=None, calls_out=None, missing_cached_baseline=False):
    path = tmp_path / "invented.sqlite"
    extra_ids = [f"SFX{index:08d}" for index in range(3, 3 + extra_stations)]
    metadata = METADATA + [dict(METADATA[1], station_id=sid) for sid in extra_ids]
    with open_db(path) as conn:
        for meta in metadata:
            conn.execute("INSERT INTO stations (station_id,name,country_code,country_name,lat,lon,archive_years,is_active) "
                         "VALUES (?,?,?,?,?,?,?,?)", (meta["station_id"], meta["name"], meta["country_code"],
                         meta["country_name"], meta["lat"], meta["lon"], 27, 1))
        for sid in (SID, TARGET, *extra_ids):
            if missing_cached_baseline and sid == TARGET:
                continue
            baseline = archive_bytes(station=sid, target=None)
            upsert_thresholds(conn, compute_thresholds(parse_dly_text(baseline.decode())))
        conn.commit()
    state = {"drafts": [], "publish_ledger": {"invented-unknown": {"phase": "unknown"}}}
    record_observation_revision(state, DiffRecord("insert", SID, date(2000, 1, 1), "TMAX", 25),
                                retrieved_at=NOW, source_revision=sha256(archive_bytes(target=None)).hexdigest())
    before = deepcopy(state)
    calls = [] if calls_out is None else calls_out
    body = json.dumps([{"STATION": sid, "DATE": DAY.isoformat(), "TMAX": str(hint_value)}
                       for sid in (TARGET, *extra_ids)]).encode()
    hints = Reply(body if hint_body is None else hint_body, hint_status)

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url == API:
            if on_hint is not None:
                on_hint()
            return hints
        if "/superghcnd/" in url:
            return Reply(b"", diff_status)
        if url.endswith(f"/all/{SID}.dly"):
            return Reply(archive_bytes(target=None) if tracked_payload is None else tracked_payload)
        if url.endswith(f"/all/{TARGET}.dly"):
            return Reply(archive_bytes(station=TARGET) if payload is None else payload)
        for sid in extra_ids:
            if url.endswith(f"/all/{sid}.dly"):
                return Reply(archive_bytes(station=sid))
        raise AssertionError("Invented transport refuses an unplanned request")

    metrics = {}
    io = None
    if runtime:
        replies = [InventedResponse("diff", f"2026-11-{day}", NOW, None, "missing") for day in (18, 19, 20)]
        replies.append(InventedResponse("station_archive", SID, NOW, archive_bytes(target=None)))
        io = ReplayIO(replies, configuration(), NOW)
    with patch.object(ghcn.requests, "get", get), freeze_time(NOW):
        result = ghcn.check_extreme_signals_for_stations(
            stations=metadata if stations is None else stations, db_path=path, metrics_out=metrics, bot_state=state,
            _now_fn=lambda: NOW, archive_verification_limit=limit, _runtime=io, _fetch_obs_fn=injected,
        )
    assert state["drafts"] == before["drafts"] and state["publish_ledger"] == before["publish_ledger"]
    return result, metrics, calls, hints


def test_all_404_discovery_can_nominate_untracked_non_us_station_but_only_archive_values_are_facts(tmp_path):
    (bundles, _), metrics, calls, hints = invoke(tmp_path)
    found = [b for b in bundles if b.station_id == TARGET]
    assert len(found) == 1, "The active station missing from the tracked pool needs an independently verified archive"
    b = found[0]
    assert b.all_time_high.new_temp_c == 33 and b.all_time_high.new_temp_c != 49
    assert b.all_time_low.new_temp_c == -15
    assert b.country == "South Africa" and b.signal_date == DAY
    assert b.evidence["variables"]["TMAX"]["source_payload_sha256"] == sha256(archive_bytes(station=TARGET)).hexdigest()
    assert len(calls) == 33  # 30 original diff calls, ONE hint request, two archives.
    assert metrics["archive_verification_attempted"] == 2
    assert hints.closed == 1


def test_no_archive_slots_cannot_buy_hint_request(tmp_path):
    result, metrics, calls, _ = invoke(tmp_path, limit=0)
    assert result == ([], []) and metrics["archive_verification_attempted"] == 0
    assert len(calls) == 30 and all(url != API for url, _ in calls)


@pytest.mark.parametrize("payload", [
    archive_bytes(station=TARGET, qflag="S"),
    archive_bytes(station=TARGET, target=date(2026, 11, 16)),
    archive_bytes(station=TARGET, target=date(2026, 11, 22)),
    archive_bytes(station=SID),
    b"unusable invented station archive",
], ids=["qc", "stale", "future", "wrong-station", "invalid"])
def test_valid_lookup_cannot_overrule_actual_archive_refusals(tmp_path, payload):
    (bundles, _), metrics, calls, _ = invoke(tmp_path, payload=payload)
    assert not [b for b in bundles if b.station_id == TARGET]
    assert metrics["station_discovery"]["nominated_stations"] == 1
    assert len(calls) == 33


def test_lookup_does_not_authorize_record_against_thin_actual_history(tmp_path):
    payload = b"\n".join(line for line in archive_bytes(station=TARGET).splitlines()
                          if int(line[11:15]) >= 2020) + b"\n"
    (bundles, _), metrics, _, _ = invoke(tmp_path, payload=payload)
    assert metrics["station_archive_intake"]["counts"]["accepted_values"] == 2
    assert all(b.all_time_high is None and b.monthly_high is None and b.calendar_date_high is None
               for b in bundles if b.station_id == TARGET)


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500, 503])
def test_one_failed_lookup_never_retries_or_requests_the_untracked_archive(tmp_path, status):
    (bundles, _), metrics, calls, hints = invoke(tmp_path, hint_status=status)
    assert bundles == [] and hints.closed == 1
    assert len(calls) == 32 and sum(url == API for url, _ in calls) == 1
    assert not any(url.endswith(f"/all/{TARGET}.dly") for url, _ in calls)
    assert metrics["station_archive_intake"]["schema_version"] == 1
    assert metrics["station_discovery"]["status"] == "unavailable"


def test_lookup_request_is_fixed_public_origin_without_auth_redirects_or_extra_fields(tmp_path):
    _, metrics, calls, _ = invoke(tmp_path)
    kw = next(kw for url, kw in calls if url == API)
    assert kw["allow_redirects"] is False and kw["stream"] is True
    assert kw["timeout"] == 5
    assert kw["params"] == {"dataset": "daily-summaries", "startDate": "2026-11-17",
        "endDate": "2026-11-21", "dataTypes": "TMAX,TMIN", "units": "metric", "format": "json"}
    assert kw["headers"]["Accept-Encoding"] == "identity"
    prepared = requests.Request("GET", API).prepare()
    assert kw["auth"](prepared) is prepared and "Authorization" not in prepared.headers
    assert metrics["station_discovery"]["get_calls"] == 1
    assert metrics["station_archive_intake"]["scope"] == "verified_selected_station_archives"


def hint(day="2026-11-18", value="49", station=TARGET):
    return {"STATION": station, "DATE": day, "TMAX": value}


def nominate(rows):
    return discovery.nominate(json.dumps(rows).encode(), frozenset({TARGET}), known_cache(),
        today=date(2026, 11, 21), cutoff=date(2026, 11, 17), anomaly=8)


def test_identical_hints_collapse_and_conflicting_values_are_order_independent():
    candidates, counts = nominate([hint(), hint()])
    assert candidates == {TARGET} and counts["numeric_hints"] == 1
    for rows in ([hint(), hint(value="50")], [hint(value="50"), hint()]):
        candidates, counts = nominate(rows)
        assert not candidates and counts["held_stations"] == 1


@pytest.mark.parametrize("bad", [True, [], {}, "NaN", "inf", "1e300", "200", "-121"])
def test_malformed_value_keeps_its_station_identity_and_cannot_lose_to_a_valid_copy(bad):
    for rows in ([hint(value=bad), hint()], [hint(), hint(value=bad)]):
        candidates, counts = nominate(rows)
        assert not candidates and counts["held_stations"] == 1


@pytest.mark.parametrize("day", ["2026-11-16", "2026-11-22"])
def test_old_future_lookup_rows_never_nominate(day):
    assert not nominate([hint(day=day)])[0]


def test_no_global_or_missing_value_inference_from_lookup():
    assert not nominate([hint(station="USX00000003")])[0]
    assert not nominate([hint(value="-9999"), hint(value=None)])[0]
    assert nominate([hint(day="2026-11-17")])[0] == {TARGET}


@pytest.mark.parametrize("body", [b"{}", b"null", b"[1]", b"[", b"\xff", b'[{"error":"unsupported reply"}]',
    b'[{"STATION":"SFX00000002","STATION":"USX00000003"}]',
    b'[{"STATION":"SFX00000002","DATE":"2026-11-18","TMAX":NaN}]'])
def test_unsupported_lookup_frame_is_not_rescued_by_the_tracked_archive(tmp_path, body):
    result, metrics, calls, _ = invoke(tmp_path, hint_body=body)
    assert result == ([], []) and len(calls) == 32
    assert metrics["station_discovery"]["status"] == "unavailable"
    assert metrics["station_discovery"]["nominated_stations"] == 0


def fetch_reply(reply, *, clock=None):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return reply

    with patch.object(discovery.requests, "get", get):
        if clock is None:
            result = discovery.fetch_nominations(frozenset({TARGET}), known_cache(),
                today=date(2026, 11, 21), max_age_days=4, anomaly=8)
        else:
            with patch.object(discovery.time, "monotonic", clock):
                result = discovery.fetch_nominations(frozenset({TARGET}), known_cache(),
                    today=date(2026, 11, 21), max_age_days=4, anomaly=8)
    assert reply.closed == 1 and len(calls) == 1
    return result


@pytest.mark.parametrize("headers", [
    {"Content-Type": "text/html"}, {"Content-Encoding": "gzip"},
    {"Content-Length": "1"}, {"Content-Length": "999999999999999"},
    {"Transfer-Encoding": "chunked"},
])
def test_response_headers_cannot_hide_a_truncated_or_ambiguous_lookup(headers):
    reply = Reply(json.dumps([hint()]).encode())
    reply.headers.update(headers)
    candidates, metadata = fetch_reply(reply)
    assert candidates == set() and metadata["status"] == "unavailable"


def test_read_deadline_cannot_promote_the_complete_json_returned_too_late():
    clock = iter([0, 0, 16])
    candidates, metadata = fetch_reply(Reply(json.dumps([hint()]).encode()), clock=lambda: next(clock))
    assert not candidates and metadata["status"] == "unavailable"


def test_body_bound_rejects_oversized_stream_without_retry(monkeypatch):
    monkeypatch.setattr(discovery, "MAX_BYTES", 128)
    reply = Reply(json.dumps([hint()]).encode() + b" " * 129)
    reply.headers["Content-Length"] = "100"
    candidates, metadata = fetch_reply(reply)
    assert not candidates and metadata["status"] == "unavailable"


def test_operation_cancellation_still_refuses_before_the_lookup_egress():
    from src.two_bot.call_inventory import CancelToken, OperationCancelled, run_cancellable

    token = CancelToken("invented-lookup")
    token.cancel("fixture_cancel")
    with patch.object(discovery.requests, "get", side_effect=AssertionError("Cancelled source must not send")), \
         pytest.raises(OperationCancelled):
        run_cancellable(token, discovery.fetch_nominations, frozenset({TARGET}), {TARGET: None},
            today=date(2026, 11, 21), max_age_days=4, anomaly=8)


def test_failed_lookup_does_not_discard_the_existing_tracked_archive_facts(tmp_path):
    (bundles, _), metrics, calls, _ = invoke(tmp_path, hint_status=503, tracked_payload=archive_bytes())
    assert len(bundles) == 1 and bundles[0].station_id == SID
    assert bundles[0].all_time_high.new_temp_c == 33
    assert len(calls) == 32 and metrics["station_archive_intake"]["schema_version"] == 1


def test_single_archive_slot_still_rotates_both_original_lanes_across_two_buckets(tmp_path):
    selected = set()
    for index, at in enumerate(("2026-11-21T12:00:00Z", "2026-11-21T16:00:00Z")):
        child = tmp_path / str(index)
        child.mkdir()
        with patch(__name__ + ".NOW", at):
            _, metrics, calls, _ = invoke(child, limit=1)
        archives = [url.rsplit("/", 1)[1][:-4] for url, _ in calls if "/all/" in url]
        assert len(archives) == 1 and len(calls) == 32
        assert metrics["archive_verification_attempted"] == 1
        selected.update(archives)
    assert selected == {SID, TARGET}


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_lookup_never_masks_diff_auth_rate_or_server_failure(tmp_path, status):
    _, metrics, calls, _ = invoke(tmp_path, diff_status=status)
    assert len(calls) == 31 and not any(url == API for url, _ in calls)
    assert "station_discovery" not in metrics


def test_retained_runtime_with_untracked_active_station_performs_no_lookup_or_http(tmp_path):
    result, metrics, calls, _ = invoke(tmp_path, runtime=True)
    assert result == ([], []) and calls == []
    assert "station_discovery" not in metrics
    assert metrics["station_archive_intake"]["schema_version"] == 1


def test_injected_observations_with_untracked_active_station_do_not_enable_lookup(tmp_path):
    result, metrics, calls, _ = invoke(tmp_path, injected=lambda _: {})
    assert result == ([], []) and len(calls) == 1
    assert "station_discovery" not in metrics


def test_without_an_existing_active_tracked_station_the_old_scope_is_preserved(tmp_path):
    result, metrics, calls, _ = invoke(tmp_path, stations=[METADATA[1]])
    assert result == ([], []) and len(calls) == 31
    assert "station_discovery" not in metrics
    assert metrics["station_archive_intake"]["active_archives"] == 0


def test_more_than_twenty_real_nominations_cannot_expand_the_archive_request_cap(tmp_path):
    (_, _), metrics, calls, _ = invoke(tmp_path, extra_stations=24)
    assert metrics["station_discovery"]["nominated_stations"] == 25
    assert metrics["archive_verification_attempted"] == 20
    assert len(calls) == 51 and sum("/all/" in url for url, _ in calls) == 20
    assert sum(url == API for url, _ in calls) == 1
    assert metrics["archive_selection"]["tracked"]["selected_stations"] == 1


def test_new_inventory_marks_lookup_as_non_observational_and_never_a_second_independent_source():
    from dataclasses import replace
    from src.data import source_product_contracts as products

    product = "open_meteo_extreme_signals.ghcn_daily_access_hints"
    document = products.product_contract_document()
    assert document["schema"] == "theheat.source-product-contracts/v5"
    row = next(row for row in document["products"] if row["product_id"] == product)
    assert row["data_kind"] == "discovery" and row["claim_permission_granted"] is False
    assert all(row[name] is None for name in products.UNKNOWN_FIELDS)
    assert products.max_independent_source_count([product, "open_meteo_extreme_signals.ghcn_station_history"]) == 1
    archived = next(row for row in document["products"]
                    if row["product_id"] == "open_meteo_extreme_signals.ghcn_archive_observations")
    assert archived["data_kind"] == "observed_station"
    assert "reference_not_reading" not in archived["claim_restrictions"]
    assert archived["restriction_enforcement"]["record_needs_qualified_history"] == {
        "basis": "check", "reference": "src/data/ghcn.py:record_comparison_qualified"}
    assert products.max_independent_source_count([product, archived["product_id"],
        "open_meteo_extreme_signals.ghcn_station_history"]) == 1
    for schema in (products.LEGACY_SCHEMA, products.PREVIOUS_SCHEMA, products.GPM_SCHEMA, products.GHCN_SCHEMA):
        old = products.product_contract_document(schema=schema)
        assert product not in [row["product_id"] for row in old["products"]]
        products.verify_product_contract_document(old)
    legs = tuple(replace(leg, data_kind="observed_station") if leg.product_id == product else leg for leg in products.LEGS)
    with pytest.raises(ValueError, match="kind_provider"):
        products.validate_legs(legs)


def test_cancelled_lookup_response_cannot_start_even_one_later_archive_request(tmp_path):
    from src.two_bot.call_inventory import CancelToken, OperationCancelled, run_cancellable

    token = CancelToken("invented-collector")
    calls = []
    with pytest.raises(OperationCancelled, match="cancelled_while_in_flight"):
        run_cancellable(token, invoke, tmp_path, calls_out=calls,
                        on_hint=lambda: token.cancel("cancelled_while_in_flight"))
    assert len(calls) == 31 and sum(url == API for url, _ in calls) == 1
    assert all("/all/" not in url for url, _ in calls)


def test_cancellation_after_selection_is_checked_again_before_each_archive_request(tmp_path):
    from src.two_bot.call_inventory import CancelToken, OperationCancelled, run_cancellable

    token = CancelToken("invented-selected-source")
    calls = []
    original = ghcn._select_archive_stations

    def select(*args, **kwargs):
        result = original(*args, **kwargs)
        token.cancel("cancelled_after_selection")
        return result

    with patch.object(ghcn, "_select_archive_stations", select), \
         pytest.raises(OperationCancelled, match="cancelled_after_selection"):
        run_cancellable(token, invoke, tmp_path, calls_out=calls)
    assert len(calls) == 31 and all("/all/" not in url for url, _ in calls)


def known_cache():
    return {TARGET: StationThresholds(station_id=TARGET, all_time_max_c=25, all_time_min_c=15)}


def test_missing_cache_does_not_nominate_an_ordinary_lookup_value_or_displace_tracked_work(tmp_path):
    (bundles, _), metrics, calls, _ = invoke(tmp_path, hint_value=0, missing_cached_baseline=True,
                                           tracked_payload=archive_bytes())
    assert len(bundles) == 1 and bundles[0].station_id == SID
    assert metrics["station_discovery"]["nominated_stations"] == 0
    assert len(calls) == 32 and not any(url.endswith(f"/{TARGET}.dly") for url, _ in calls)


def test_one_invalid_untracked_identifier_cannot_abort_existing_tracked_checks(tmp_path):
    stations = METADATA + [dict(METADATA[1], station_id="INVALID")]
    (bundles, _), _, calls, _ = invoke(tmp_path, stations=stations, tracked_payload=archive_bytes())
    assert {b.station_id for b in bundles} == {SID, TARGET}
    assert len(calls) == 33 and not any("INVALID" in url for url, _ in calls)


def test_unrepresentable_decimal_reply_is_refused_without_aborting_tracked_archives(tmp_path):
    body = b'[{"STATION":"SFX00000002","DATE":"2026-11-18","TMAX":1e999999999999999999999}]'
    (bundles, _), metrics, calls, _ = invoke(tmp_path, hint_body=body, tracked_payload=archive_bytes())
    assert len(bundles) == 1 and bundles[0].station_id == SID
    assert metrics["station_discovery"]["status"] == "unavailable"
    assert len(calls) == 32


def test_exact_decimal_conflicts_cannot_disappear_through_float_rounding():
    a = b'{"STATION":"SFX00000002","DATE":"2026-11-18","TMAX":49}'
    b = b'{"STATION":"SFX00000002","DATE":"2026-11-18","TMAX":49.000000000000001}'
    for rows in (a + b"," + b, b + b"," + a):
        candidates, counts = discovery.nominate(b"[" + rows + b"]", frozenset({TARGET}), known_cache(),
            today=date(2026, 11, 21), cutoff=date(2026, 11, 17), anomaly=8)
        assert not candidates and counts["held_stations"] == 1


@pytest.mark.parametrize("trailer,expected", [(b"\r\n", {TARGET}), (b"", set()),
                                             (b"X-Foo: cut", set()), (b"X-Foo: valid\r\n\r\n", set())])
def test_real_stdlib_and_urllib3_chunk_reader_requires_complete_supported_trailer(trailer, expected):
    body = json.dumps([hint()]).encode()
    wire = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
            + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n" + trailer)

    class Sock:
        def makefile(self, *_args, **_kwargs):
            return BytesIO(wire)

    original = http.client.HTTPResponse(Sock())
    original.begin()
    raw = RawHTTPResponse(body=original, headers={"Transfer-Encoding": "chunked"}, status=200,
                          preload_content=False, decode_content=False)
    reply = Reply(body)
    reply.headers.pop("Content-Length")
    reply.headers["Transfer-Encoding"] = "chunked"
    reply.raw = raw
    candidates, _ = fetch_reply(reply)
    assert candidates == expected


def test_real_requests_redirect_preparation_cannot_consume_body_or_consult_netrc(monkeypatch):
    class Counted(BytesIO):
        consumed = 0

        def read(self, *args, **kwargs):
            result = super().read(*args, **kwargs)
            self.consumed += len(result)
            return result

    raw = Counted(b"x" * 96)
    response = requests.Response()
    response.status_code = 302
    response.headers.update({"Location": "https://invented.invalid/", "Content-Length": "96"})
    response.raw = raw

    class Adapter(requests.adapters.BaseAdapter):
        sent = 0

        def send(self, request, **kwargs):
            self.sent += 1
            response.request, response.url = request, request.url
            return response

        def close(self):
            pass

    session, adapter = requests.Session(), Adapter()
    session.mount("https://", adapter)
    monkeypatch.setattr(discovery, "MAX_BYTES", 16)
    with patch.object(requests.sessions, "Session", return_value=session), \
         patch.object(requests.sessions, "get_netrc_auth", return_value=None) as netrc:
        candidates, metadata = discovery.fetch_nominations(frozenset({TARGET}), known_cache(),
            today=date(2026, 11, 21), max_age_days=4, anomaly=8)
    assert not candidates and metadata["http_status"] == 302
    assert (raw.consumed, netrc.call_count, adapter.sent) == (0, 0, 1)
