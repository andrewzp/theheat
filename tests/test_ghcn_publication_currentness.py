"""Invented NOAA source bytes at the actual publication-source boundary."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace

import pytest
import requests

from src.data import _http
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.orchestrator import posting
from tests.ghcn_graphic_helpers import graphic_bundles, source_archive


class ArchiveResponse:
    def __init__(self, payload, url, status=200):
        self.payload, self.url, self.status_code = payload, url, status
        self.headers = {"Content-Length": str(len(payload))}
        self.closed = False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.payload), chunk_size):
            yield self.payload[offset:offset + chunk_size]

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("invented source error", response=self)


def saved_draft(bundle):
    payload = story_bundle_snapshot(bundle)
    legacy = {"open_meteo_archive_high": "all_time_high", "open_meteo_archive_low": "all_time_low",
              "monthly_high": "monthly_high", "monthly_low": "monthly_low",
              "calendar_record": "record", "calendar_record_low": "record_low"}
    return {"id": "invented-ghcn-publication", "event_id": payload["event_id"],
            "type": legacy[payload["signal_kind"]], "text": "Invented accepted station reading.",
            "review_context": {"two_bot": {"bundle": deepcopy(payload)}}}


def test_actual_publication_chain_does_not_accept_changed_current_archive(monkeypatch):
    draft = saved_draft(graphic_bundles()[-1])
    calls = []

    def response(url, **kwargs):
        calls.append((url, kwargs))
        # A source-byte change alone invalidates the captured archive revision.
        return ArchiveResponse(source_archive() + b"\n", url)

    monkeypatch.setattr(_http, "fetch_with_retry", response)
    monkeypatch.setattr(posting, "_utc_now", lambda: datetime(2026, 9, 9, 12, tzinfo=UTC))
    hold = posting._current_nws_source(draft, live=True, bot_state={})
    assert hold == "ghcn_current_archive_changed"
    assert len(calls) == 1


@pytest.fixture(scope="module")
def variants():
    return {(direction, tier): saved_draft(graphic_bundles(direction=direction, tier=tier)[-1])
            for direction in ("high", "low") for tier in ("all_time", "monthly", "calendar")}


@pytest.fixture
def archive_http(monkeypatch):
    state = {"bytes": source_archive(), "calls": [], "responses": []}

    def fetch(url, **kwargs):
        state["calls"].append((url, kwargs))
        response = ArchiveResponse(state["bytes"], url)
        state["responses"].append(response)
        return response

    monkeypatch.setattr(_http, "fetch_with_retry", fetch)
    return state


@pytest.mark.parametrize("key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar")])
def test_all_six_full_source_comparators_survive_real_current_archive_recomputation(variants, archive_http, key):
    from src.data.ghcn_publication import current_draft_hold

    draft = deepcopy(variants[key])
    original = deepcopy(draft)
    assert current_draft_hold(draft, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert not archive_http["calls"]
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert draft == original
    assert len(archive_http["calls"]) == 1
    url, args = archive_http["calls"][0]
    assert url.endswith("/" + draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["station_id"] + ".dly")
    assert args["attempts"] == 1 and args["timeout"] == 12
    assert args["allow_redirects"] is False and args["stream"] is True
    assert args["headers"]["Accept-Encoding"] == "identity"
    assert "Authorization" not in args["headers"]
    assert archive_http["responses"][0].closed


@pytest.mark.parametrize("mutation", ["missing_bundle", "wrong_event", "wrong_type", "changed_value", "changed_comparator", "reference_only", "future_retrieval"])
def test_static_invalid_record_never_fetches_or_repairs_its_source(variants, archive_http, mutation):
    from src.data.ghcn_publication import current_draft_hold

    draft = deepcopy(variants[("high", "all_time")])
    bundle = draft["review_context"]["two_bot"]["bundle"]
    if mutation == "missing_bundle":
        draft["review_context"] = {}
    elif mutation == "wrong_event":
        draft["event_id"] += "_changed"
    elif mutation == "wrong_type":
        draft["type"] = "monthly_high"
    elif mutation == "changed_value":
        bundle["headline_metric"]["value"] += 1
    elif mutation == "changed_comparator":
        bundle["raw_signal_dump"]["old_record_c"] -= 1
    elif mutation == "reference_only":
        bundle["raw_signal_dump"]["ghcn_claim_view"] = {}
    else:
        bundle["raw_signal_dump"]["evidence"]["baseline"]["retrieved_at"] = "2099-01-01T00:00:00Z"
    original = deepcopy(draft)
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is not None
    assert not archive_http["calls"]
    assert draft == original


def test_separate_live_boundaries_do_not_reuse_a_previously_accepted_archive(variants, archive_http):
    from src.data.ghcn_publication import current_draft_hold

    draft = variants[("high", "all_time")]
    clock = datetime(2026, 9, 9, 12, tzinfo=UTC)
    assert current_draft_hold(draft, live=True, now=clock) is None
    archive_http["bytes"] += b"\n"
    assert current_draft_hold(draft, live=True, now=clock) == "ghcn_current_archive_changed"
    assert len(archive_http["calls"]) == 2


@pytest.mark.parametrize("changed_cell,target,expected", [
    ((b"  418  T", b"  417  T"), 42.2, "ghcn_current_comparator_changed"),
    ((b"  422  T", b"  432  T"), 43.2, "ghcn_current_observation_changed"),
])
def test_declared_payload_hash_alone_cannot_replace_actual_observation_and_comparator(
    monkeypatch, changed_cell, target, expected,
):
    from src.data import ghcn
    from src.data.ghcn_publication import current_draft_hold

    # Build a coherent but dishonest retained baseline from another archive,
    # then declare the real archive's hash. All science still executes normally.
    from datetime import date
    from src.data.ghcn_format import DailyObs
    from src.two_bot.intern import build_all_time_record_bundle
    from tests.ghcn_graphic_helpers import AS_OF, STATION
    real = source_archive()
    changed = real.replace(*changed_cell)
    assert changed != real
    snapshot = ghcn._archive_snapshot(STATION["station_id"], changed, AS_OF)
    # Lie only about source identity, before the real qualifier and builders.
    # The retained tree is coherent but its actual reading or comparator differs.
    snapshot["source_revision"] = hashlib.sha256(real).hexdigest()
    observation = DailyObs(STATION["station_id"], date(2026, 9, 8), "TMAX", target)
    thresholds, checked = ghcn._thresholds_from_verified_archive(STATION["station_id"], [observation], snapshot)
    signals = ghcn._detect_signals_for_station(STATION, checked, thresholds)
    assert signals is not None and signals.all_time_high is not None
    forged = saved_draft(build_all_time_record_bundle(signals.all_time_high, source="ghcn"))
    assert current_draft_hold(forged, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    monkeypatch.setattr(_http, "fetch_with_retry", lambda url, **kwargs: ArchiveResponse(real, url))
    hold = current_draft_hold(forged, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC))
    assert hold == expected


@pytest.fixture
def real_http(monkeypatch):
    """Replace only Session's physical send; accounting and retry helper stay real."""
    from src.data import ghcn_publication
    state = SimpleNamespace(calls=[], sessions=[], response=None, error=None, elapsed=100.0)

    class Session:
        def __init__(self):
            self.trust_env = True
            self.closed = False
            state.sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def get(self, url, **kwargs):
            assert self.trust_env is False
            state.calls.append((url, kwargs))
            if state.error is not None:
                raise state.error
            return state.response

    state.response = ArchiveResponse(source_archive(), "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/USC99000001.dly")
    monkeypatch.setattr(ghcn_publication.requests, "Session", Session)
    monkeypatch.setattr(ghcn_publication, "time", SimpleNamespace(monotonic=lambda: state.elapsed))
    return state


def test_real_shared_http_counts_one_attempt_without_ambient_auth_or_retry(variants, real_http, monkeypatch):
    from src.data.ghcn_publication import current_draft_hold
    from src.two_bot.call_inventory import runtime_counts
    monkeypatch.setenv("HTTPS_PROXY", "http://invented.invalid:9")
    monkeypatch.setenv("NETRC", "/nonexistent/invented-netrc")
    before = runtime_counts().get("source_http_get", 0)
    assert current_draft_hold(variants[("high", "all_time")], live=True,
                              now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert runtime_counts().get("source_http_get", 0) == before + 1
    assert len(real_http.calls) == 1
    _url, options = real_http.calls[0]
    assert options["allow_redirects"] is False and options["timeout"] == 12
    assert set(options) == {"headers", "timeout", "allow_redirects", "stream"}
    assert set(options["headers"]) == {"User-Agent", "Cache-Control", "Accept-Encoding"}
    assert all(s.closed for s in real_http.sessions) and real_http.response.closed


@pytest.mark.parametrize("fault,expected", [
    ("redirect", "ghcn_current_source_unavailable"), ("wrong_url", "ghcn_current_source_unavailable"),
    ("403", "ghcn_current_source_unavailable"), ("503", "ghcn_current_source_unavailable"),
    ("timeout", "ghcn_current_source_unavailable"), ("connection", "ghcn_current_source_unavailable"),
    ("gzip", "ghcn_current_source_bound"), ("declared_large", "ghcn_current_source_bound"),
    ("bad_length", "ghcn_current_source_bound"), ("short", "ghcn_current_source_bound"),
    ("oversize", "ghcn_current_source_bound"), ("slow", "ghcn_current_source_bound"),
    ("empty", "ghcn_current_source_invalid"), ("non_ascii", "ghcn_current_source_invalid"),
    ("wrong_station", "ghcn_current_source_invalid"), ("conflicting_day", "ghcn_current_source_invalid"),
    ("target_changed", "ghcn_current_archive_changed"), ("qc_changed", "ghcn_current_archive_changed"),
    ("coverage_removed", "ghcn_current_archive_changed"),
])
def test_real_http_refusals_close_every_response_and_never_retry(variants, real_http, fault, expected):
    from src.data.ghcn_publication import current_draft_hold
    response = real_http.response
    if fault == "redirect":
        response.status_code = 302
        response.headers["Location"] = "https://invented.invalid/redirect"
    elif fault == "wrong_url":
        response.url += "?changed"
    elif fault in {"403", "503"}:
        response.status_code = int(fault)
    elif fault in {"timeout", "connection"}:
        real_http.error = requests.Timeout("invented") if fault == "timeout" else requests.ConnectionError("invented")
    elif fault == "gzip":
        response.headers["Content-Encoding"] = "gzip"
    elif fault == "declared_large":
        response.headers["Content-Length"] = "8000001"
    elif fault == "bad_length":
        response.headers["Content-Length"] = "-1"
    elif fault == "short":
        response.headers["Content-Length"] = str(len(response.payload) + 1)
    elif fault == "oversize":
        response.headers.clear()
        response.payload = b"X" * 8_000_001
    elif fault == "slow":
        original = response.iter_content
        def slow_chunks(size):
            real_http.elapsed += 12.001
            yield from original(size)
        response.iter_content = slow_chunks
    else:
        payload = response.payload
        if fault == "empty":
            payload = b""
        elif fault == "non_ascii":
            payload = b"\xff"
        elif fault == "wrong_station":
            payload = payload.replace(b"USC99000001", b"USC99000002")
        elif fault == "conflicting_day":
            row = payload.splitlines()[0]
            payload += b"\n" + row.replace(b"  280  T", b"  281  T")
        elif fault == "target_changed":
            payload = payload.replace(b"  422  T", b"  432  T")
        elif fault == "qc_changed":
            payload = payload.replace(b"  422  T", b"  422 ST")
        else:
            payload = b"\n".join(payload.splitlines()[2:])
        assert payload != response.payload
        response.payload = payload
        response.headers["Content-Length"] = str(len(payload))
    assert current_draft_hold(variants[("high", "all_time")], live=True,
                              now=datetime(2026, 9, 9, 12, tzinfo=UTC)) == expected
    assert len(real_http.calls) == 1 and all(s.closed for s in real_http.sessions)
    assert response.closed is (real_http.error is None)


@pytest.mark.parametrize("when", ["before", "during", "after_empty_stream"])
def test_cancelled_source_work_never_authorizes_or_adds_another_egress(variants, real_http, when):
    from src.data.ghcn_publication import current_draft_hold
    from src.two_bot.call_inventory import CancelToken, run_cancellable, runtime_counts
    token = CancelToken("invented-ghcn-current-source")
    response = real_http.response
    original = response.iter_content
    def chunks(size):
        token.cancel("invented deadline")
        if when != "after_empty_stream":
            yield from original(size)
    if when == "before":
        token.cancel("invented deadline")
    else:
        response.iter_content = chunks
        if when == "after_empty_stream":
            response.headers.clear()
    before = runtime_counts().get("source_http_get", 0)
    hold = run_cancellable(token, current_draft_hold, variants[("high", "all_time")],
                           live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC))
    assert hold is not None
    expected = 0 if when == "before" else 1
    assert len(real_http.calls) == expected
    assert runtime_counts().get("source_http_get", 0) == before + expected
    assert all(s.closed for s in real_http.sessions)
    if expected:
        assert hold == "ghcn_current_source_cancelled" and response.closed


def test_source_clock_rollback_is_held_after_an_otherwise_good_live_read(variants, real_http):
    from src.data.ghcn_publication import current_draft_hold
    values = iter([datetime(2026, 9, 9, 12, tzinfo=UTC), datetime(2026, 9, 9, 11, tzinfo=UTC)])
    assert current_draft_hold(variants[("high", "all_time")], live=True, now=lambda: next(values)) == "ghcn_source_clock_changed"


@pytest.mark.parametrize("clock", [False, 0, "2026-09-09", datetime(2026, 9, 9, 12)])
def test_malformed_clock_is_not_silently_replaced_with_wall_time(variants, real_http, clock):
    from src.data.ghcn_publication import current_draft_hold
    assert current_draft_hold(variants[("high", "all_time")], live=True, now=clock) == "ghcn_source_clock_invalid"
    assert not real_http.calls


def test_relabelled_record_with_unhashable_signal_is_held_without_crashing(variants, real_http):
    from src.data.ghcn_publication import current_draft_hold
    draft = deepcopy(variants[("high", "all_time")])
    bundle = draft["review_context"]["two_bot"]["bundle"]
    draft["event_id"] = bundle["event_id"] = bundle["raw_signal_dump"]["event_id"] = "changed"
    bundle["signal_kind"] = []
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) == "ghcn_retained_source_invalid"
    assert not real_http.calls


@pytest.mark.parametrize("draft", [
    {}, {"type": "flood", "event_id": "invented_other"},
    {"event_id": "era5_example", "review_context": {"two_bot": {"bundle": {
        "signal_kind": "open_meteo_archive_high", "raw_signal_dump": {"evidence": {"source_product": "era5"}}}}}},
    {"event_id": "ghcn_anomaly", "review_context": {"two_bot": {"bundle": {
        "signal_kind": "temperature_anomaly", "raw_signal_dump": {"evidence": {"source_product": "noaa-ghcn-daily-v2"}}}}}},
])
def test_nonfamily_source_contract_is_unchanged_without_http(real_http, draft):
    from src.data.ghcn_publication import current_draft_hold
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert not real_http.calls and not real_http.sessions
