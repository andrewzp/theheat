from tests.temperature_helpers import snapshot, dated_forecast, complete_archive, provider_payload
from src.data import places

def sample_identity(city, country, lat, lon):
    return {**places.resolve_place(city, country, lat, lon), "source_product": places.CACHE_PRODUCT}

"""Tests for the world-half eval/warm/consolidate path (_run_world_cached_half).

Covers the eval-gating fix (archive saturation must NOT starve forecast evaluation),
refute-before-emit (a fresh archive refutes a stale-cache record before it is emitted or
stamped), freshness honesty (a record fired against still-stale climatology keeps a stale
as_of so the city stays warm-eligible), and the city|country re-key that stops
genuinely-distinct same-name cities (Barcelona ES vs VE) from conflating.

The world cache, forecast map, and provisional stamp are all keyed by
``world_cache.world_key(city, country)``; ``bundle.city`` stays the bare display name.
"""
from datetime import date, timedelta
import json
import responses

from src.data.open_meteo import AbsoluteExtremeEvent
from src.data.openmeteo_budget import OpenMeteoSaturated
from src.data.world_thresholds import CityThresholds
from src.orchestrator import world_cache
from src.orchestrator.sources import open_meteo as runner

TODAY = date(2026, 6, 16)
ISO = TODAY.isoformat()
STALE_ISO = (TODAY - timedelta(days=60)).isoformat()
MM = f"{TODAY.month:02d}"
YEAR = TODAY.year
ARCH_YEAR = 2010
DAY = f"{ARCH_YEAR}-{MM}-01"


def K(city, country="Spain"):
    return world_cache.world_key(city, country, *((41.39, 2.16) if city == "Barcelona" and country == "Spain" else (10.14, -64.69) if city == "Barcelona" else (37.4, -6.0)))


def _thresh(city, as_of, *, all_time_max=None, all_time_min=None, monthly_max=None,
            monthly_min=None, monthly_mean=None, wetbulb_max=None, years=30):
    return CityThresholds(
        city=city, as_of=as_of, years_of_data=years,
        all_time_max=all_time_max, all_time_min=all_time_min,
        monthly_max=monthly_max or {}, monthly_min=monthly_min or {},
        monthly_mean=monthly_mean or {}, wetbulb_max=wetbulb_max,
    ).to_dict()


def _city(name, country="Spain", lat="37.4", lon="-6.0"):
    return {"city": name, "country": country, "lat": lat, "lon": lon}


def _arch(*, max_c=None, min_c=None, tw=None):
    a = {"time": [DAY]}
    if max_c is not None:
        a["temperature_2m_max"] = [max_c]
    if min_c is not None:
        a["temperature_2m_min"] = [min_c]
    if tw is not None:
        a["wet_bulb_temperature_2m_max"] = [tw]
    return complete_archive(a, valid_date=ISO)


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def _fc_map(mapping):
    # mapping is keyed by bare city; the runner looks up world_key, so emit composite keys
    # (mirrors the real fetch_forecasts_batch).
    def f(cities):
        return {K(c["city"], c["country"]): mapping[c["city"]] for c in cities if c["city"] in mapping}
    return f


def _run(monkeypatch, world_cities, seed_cache, *, forecasts=None, archive=None,
         abs_extreme=None, country=None, meta_prev=None, real_country=False, real_clock=False):
    """Run _run_world_cached_half with patched IO. seed_cache is keyed by world_key.

    Returns (om_bundles, om_country, store, metrics).
    """
    class FixtureDate(date):
        @classmethod
        def today(cls):
            return TODAY

    # Keep fixtures and the actual cache runner on one clock, including when
    # a full CI run crosses midnight between test collection and execution.
    monkeypatch.setattr(runner, "date", FixtureDate)
    clock = [0.0]

    def advance(seconds):
        clock[0] += seconds

    if not real_clock:
        monkeypatch.setattr(runner.staging, "clock", lambda: clock[0])
        monkeypatch.setattr(runner, "time", type("FixtureTime", (), {"sleep": staticmethod(advance)}))
    store = dict(seed_cache)
    for c in world_cities:
        key = world_cache.world_key(c["city"], c["country"], c["lat"], c["lon"])
        if key in store:
            store[key] = snapshot({**store[key], "identity": sample_identity(c["city"], c["country"], c["lat"], c["lon"])})
    if meta_prev is not None:
        store["_meta"] = {"cached_count": meta_prev, "as_of": STALE_ISO}
    monkeypatch.setattr(world_cache, "read_cache", lambda: dict(store))

    def _write(c):
        store.clear()
        store.update(c)
        return True

    monkeypatch.setattr(world_cache, "write_cache", _write)
    def fetch_forecast(cities, *, on_attempt):
        on_attempt()
        return {key: dated_forecast(value, ISO) for key, value in forecasts(cities).items()}

    def fetch_archive(city, *, reserve_attempt, attempts, deadline_at):
        reserve_attempt(235)
        return archive(city)

    if forecasts is not None:
        monkeypatch.setattr("src.data.open_meteo.fetch_forecasts_batch", fetch_forecast)
    if archive is not None:
        monkeypatch.setattr(runner, "_fetch_city_archive", fetch_archive)
    monkeypatch.setattr("src.data.open_meteo.detect_absolute_extreme",
                        abs_extreme or (lambda *a, **k: None))
    if not real_country:
        monkeypatch.setattr("src.data.open_meteo.detect_country_records",
                            country or (lambda *a, **k: []))
    metrics: dict = {}
    om_bundles, om_country = runner._run_world_cached_half(world_cities, metrics)
    return om_bundles, om_country, store, metrics


# --- 0. HEADLINE (P1a): distinct same-name cities do NOT conflate
def test_distinct_same_name_cities_do_not_conflate(monkeypatch):
    # Barcelona/Spain and Barcelona/Venezuela are different cities sharing a name. Both
    # fresh-cached with their own thresholds; each gets its own forecast. They must NOT
    # share a cache entry or a forecast.
    seed = {
        K("Barcelona", "Spain"): _thresh("Barcelona", ISO, all_time_max=(40.0, 2000)),
        K("Barcelona", "Venezuela"): _thresh("Barcelona", ISO, all_time_max=(40.0, 2000)),
    }
    cities = [_city("Barcelona", country="Spain", lat="41.39", lon="2.16"),
              _city("Barcelona", country="Venezuela", lat="10.14", lon="-64.69")]

    def forecasts(batch):
        # Spain runs hot (45 > 40 -> record); Venezuela does not (30 < 40 -> none).
        out = {}
        for c in batch:
            hot = c["country"] == "Spain"
            out[K(c["city"], c["country"])] = {
                "max_c": 45.0 if hot else 30.0, "min_c": 12.0, "tw_max_c": 10.0}
        return out

    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed, forecasts=forecasts,
        archive=_raise(AssertionError("fresh cities must not warm")))
    spain = [b for b in om_bundles if b.country == "Spain" and b.all_time_high]
    ven = [b for b in om_bundles if b.country == "Venezuela"]
    assert len(spain) == 1                                   # Spain Barcelona fired its own record
    assert ven == []                                        # Venezuela Barcelona did NOT (own forecast)
    assert K("Barcelona", "Spain") in store and K("Barcelona", "Venezuela") in store
    assert store[K("Barcelona", "Spain")]["all_time_max"] == [40.0, 2000]  # forecast never stamped
    assert store[K("Barcelona", "Venezuela")]["all_time_max"] == [40.0, 2000]  # untouched


# --- 1. Eval runs despite warm/archive saturation (headline defect) + split flags + OR + single-fetch
def test_eval_runs_despite_warm_archive_saturation(monkeypatch):
    seed = {
        K("C1"): _thresh("C1", ISO, all_time_max=(40.0, 2000)),
        K("C2"): _thresh("C2", ISO, all_time_max=(40.0, 2000)),
    }
    cities = [_city("C1"), _city("C2"), _city("Aaa_ok"), _city("Zzz_429")]
    fc_calls = {"n": 0}

    def forecasts(batch):
        fc_calls["n"] += 1
        return {K(c["city"], c["country"]): {"max_c": 45.0, "min_c": 12.0, "tw_max_c": 10.0} for c in batch}

    def archive(c):
        if c["city"] == "Zzz_429":
            raise OpenMeteoSaturated("archive 429")
        return _arch(max_c=46.0)

    om_bundles, _om_country, store, m = _run(
        monkeypatch, cities, seed, meta_prev=2, forecasts=forecasts, archive=archive)
    assert m["forecast_attempted"] == 2
    assert m["coverage_ratio"] == round(2 / 4, 3)
    assert m["eval_saturated"] is False
    assert m["warm_saturated"] is True
    assert m["warm_provider_saturated"] is True and m["warm_deferral"] is None
    assert m["saturated"] is True
    assert m["cached_count"] == 3                  # C1, C2 + warmed Aaa_ok
    assert m["status"] != "degraded"
    assert {b.city for b in om_bundles} == {"C1", "C2"}
    assert all(b.all_time_high is not None for b in om_bundles)
    assert fc_calls["n"] == 1


# --- 2. Eval saturation degrades
def test_eval_saturation_degrades(monkeypatch):
    seed = {K("C1"): _thresh("C1", ISO, all_time_max=(40.0, 2000))}
    cities = [_city("C1")]
    om_bundles, _c, _store, m = _run(
        monkeypatch, cities, seed,
        forecasts=_raise(OpenMeteoSaturated("forecast 429")),
        archive=_raise(OpenMeteoSaturated("archive 429")))
    assert m["eval_saturated"] is True
    assert m["saturated"] is True
    assert m["status"] == "degraded"
    assert om_bundles == []


# --- 3. Complete fresh source archive confirms a scoped forecast comparison
def test_stale_record_confirmed_by_fresh_archive(monkeypatch):
    seed = {K("C"): _thresh("C", STALE_ISO, all_time_max=(44.0, 2000))}
    cities = [_city("C")]
    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({"C": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=lambda c: _arch(max_c=46.0))
    assert any(b.all_time_high is not None for b in om_bundles)
    assert store[K("C")]["all_time_max"] == [46.0, ARCH_YEAR]
    assert store[K("C")]["as_of"] == ISO


# --- 4. Stale-cache record REFUTED by fresh archive emits NO record (P1 #1, the hazard)
def test_stale_record_refuted_by_fresh_archive(monkeypatch):
    seed = {
        K("Hi"): _thresh("Hi", STALE_ISO, all_time_max=(44.0, 2000)),
        K("Lo"): _thresh("Lo", STALE_ISO, all_time_min=(-12.0, 2000)),
    }
    cities = [_city("Hi"), _city("Lo")]

    def archive(c):
        return _arch(max_c=46.0) if c["city"] == "Hi" else _arch(min_c=-16.0)

    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({
            "Hi": {"max_c": 45.5, "min_c": 0.0, "tw_max_c": 10.0},
            "Lo": {"max_c": 5.0, "min_c": -14.0, "tw_max_c": 10.0},
        }),
        archive=archive)
    assert not any(b.all_time_high is not None for b in om_bundles)
    assert not any(b.all_time_low is not None for b in om_bundles)
    assert store[K("Hi")]["all_time_max"] == [46.0, ARCH_YEAR]
    assert store[K("Lo")]["all_time_min"] == [-16.0, ARCH_YEAR]


# --- 5a. No stale-field carry-over (warm succeeds -> fresh climatology wins)
def test_no_stale_field_carryover_warm_success(monkeypatch):
    seed = {K("C"): _thresh("C", STALE_ISO, all_time_max=(44.0, 2000),
                            monthly_mean={MM: (20.0, 10.0, 50)}, wetbulb_max=(30.0, 2005))}
    cities = [_city("C")]
    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({"C": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=lambda c: _arch(max_c=46.0, min_c=12.0, tw=28.0))
    assert store[K("C")]["all_time_max"] == [46.0, ARCH_YEAR]
    mean = store[K("C")]["monthly_mean"][MM]
    assert mean[0] < 46 and mean[1] > 12 and mean[2] > 1 and mean[3] > 1
    assert store[K("C")]["wetbulb_max"] == [28.0, ARCH_YEAR]
    assert any(b.all_time_high is not None for b in om_bundles)


# --- 5b. Warm fails: historical entry untouched and stale record lane withheld
def test_no_stale_field_carryover_warm_fails(monkeypatch):
    seed = {K("C"): _thresh("C", STALE_ISO, all_time_max=(44.0, 2000),
                            monthly_mean={MM: (20.0, 10.0, 50)}, wetbulb_max=(30.0, 2005))}
    cities = [_city("C")]
    om_bundles, _c, store, m = _run(
        monkeypatch, cities, seed, meta_prev=1,
        forecasts=_fc_map({"C": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=_raise(OpenMeteoSaturated("archive 429")))
    assert store[K("C")]["all_time_max"] == [44.0, 2000]
    assert store[K("C")]["monthly_mean"][MM] == [20.0, 10.0, 50, 50]
    assert store[K("C")]["wetbulb_max"] == [30.0, 2005]
    assert store[K("C")]["as_of"] == STALE_ISO
    assert not any(b.all_time_high is not None for b in om_bundles)
    assert m["record_comparisons_withheld"] == 1
    assert m["warm_saturated"] is True


# --- 6. Freshness honesty: stale record-bearing city NOT warmed keeps stale as_of
def test_freshness_honesty_not_warmed_keeps_stale_as_of(monkeypatch):
    seed = {
        K("Aaa"): _thresh("Aaa", STALE_ISO, all_time_max=(44.0, 2000)),
        K("Bbb"): _thresh("Bbb", STALE_ISO, all_time_max=(44.0, 2000)),
    }
    cities = [_city("Aaa"), _city("Bbb")]

    def archive(c):
        if c["city"] == "Bbb":
            raise OpenMeteoSaturated("archive 429")
        return _arch(max_c=46.0)

    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed, meta_prev=2,
        forecasts=_fc_map({
            "Aaa": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0},
            "Bbb": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0},
        }),
        archive=archive)
    assert store[K("Aaa")]["as_of"] == ISO
    assert store[K("Bbb")]["as_of"] == STALE_ISO
    assert world_cache._is_stale(store[K("Bbb")], ttl_days=30, today=ISO) is True
    assert {b.city for b in om_bundles if b.all_time_high} == {"Aaa"}


# --- 7. Snapshot-before-warm / 1-run lag for a previously-missing city
def test_snapshot_before_warm_one_run_lag(monkeypatch):
    seed = {K("C"): _thresh("C", ISO, all_time_max=(40.0, 2000))}
    cities = [_city("C"), _city("M")]
    om_bundles, _c, store, m = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({
            "C": {"max_c": 45.0, "min_c": 12.0, "tw_max_c": 10.0},
            "M": {"max_c": 45.0, "min_c": 12.0, "tw_max_c": 10.0},
        }),
        archive=lambda c: _arch(max_c=50.0))
    assert m["forecast_attempted"] == 1
    assert K("M") in store
    assert m["coverage_ratio"] == round(1 / 2, 3)
    assert {b.city for b in om_bundles} == {"C"}


# --- 10. Steady-state cached record path: as_of advances to today
def test_steady_state_cached_record_advances_as_of(monkeypatch):
    seed = {K("C"): _thresh("C", ISO, all_time_max=(40.0, 2000))}
    cities = [_city("C")]
    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({"C": {"max_c": 45.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=_raise(AssertionError("warm must not run for a fresh city")))
    assert store[K("C")]["all_time_max"] == [40.0, 2000]
    assert store[K("C")]["as_of"] == ISO
    assert any(b.all_time_high is not None for b in om_bundles)


# --- 17. Edge cases: cold cache, empty world_cities
def test_cold_cache_bootstrap_success(monkeypatch):
    cities = [_city("M1"), _city("M2")]
    _b, _c, _store, m = _run(
        monkeypatch, cities, {},
        forecasts=_fc_map({}),
        archive=lambda c: _arch(max_c=46.0))
    assert m["forecast_attempted"] == 0
    assert m["coverage_ratio"] == 0.0
    assert m["cached_count"] == 2
    assert m["status"] == "success"


def test_empty_world_cities(monkeypatch):
    _b, _c, _store, m = _run(
        monkeypatch, [], {},
        forecasts=_fc_map({}),
        archive=_raise(AssertionError("no archive for empty world")))
    assert m["coverage_ratio"] == 1.0
    assert m["status"] == "success"


# --- 19. Non-record signal (absolute_extreme) survives CONSOLIDATE; as_of untouched
def test_non_record_signal_survives_no_as_of_advance(monkeypatch):
    seed = {K("C"): _thresh("C", STALE_ISO, all_time_max=(50.0, 2000))}
    cities = [_city("C")]
    ev = AbsoluteExtremeEvent(
        city="C", country="Spain", today_temp_c=45.0, band_label="Temperate",
        threshold_c=42.0, kind="hot", lat=37.4, lon=-6.0,
        event_id="absextreme_C", signal_date=TODAY)
    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({"C": {"max_c": 45.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=_raise(OpenMeteoSaturated("archive 429")),
        abs_extreme=lambda *a, **k: ev)
    assert any(b.absolute_extreme is not None for b in om_bundles)
    assert not any(b.all_time_high is not None for b in om_bundles)
    assert store[K("C")]["as_of"] == STALE_ISO
    assert store[K("C")]["all_time_max"] == [50.0, 2000]


# --- 20. Country records reflect POST-WARM truth (refute-before-emit at country level)
def test_country_record_refuted_then_confirmed_over_post_warm(monkeypatch):
    seed = {K("A"): _thresh("A", STALE_ISO, all_time_max=(44.0, 2000)),
            K("B"): _thresh("B", STALE_ISO, all_time_max=(44.0, 2000))}
    cities = [_city("A", country="Spain"), _city("B", country="Spain")]

    _b, om_country, _s, _m = _run(
        monkeypatch, cities, dict(seed), real_country=True,
        forecasts=_fc_map({"A": {"max_c": 45.5, "min_c": 12.0, "tw_max_c": 10.0},
                           "B": {"max_c": 45.5, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=lambda c: _arch(max_c=46.0))
    assert not any(r.country == "Spain" and r.kind == "high" for r in om_country)

    _b2, om_country2, _s2, _m2 = _run(
        monkeypatch, cities, dict(seed), real_country=True,
        forecasts=_fc_map({"A": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0},
                           "B": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=lambda c: _arch(max_c=46.0))
    assert any(r.country == "Spain" and r.kind == "high" for r in om_country2)


# --- 21. event_id disambiguation: same-name cities in different countries -> distinct ids
def test_event_id_disambiguated_by_country():
    from src.data.world_thresholds import evaluate_city
    cached = CityThresholds(city="Barcelona", as_of=ISO, years_of_data=30,
                            all_time_max=(40.0, 2000)).to_dict()
    fc = dated_forecast({"max_c": 45.0, "min_c": 12.0, "tw_max_c": 10.0}, ISO)
    cached["identity"] = sample_identity("Barcelona", "Spain", 41.39, 2.16)
    es = evaluate_city("Barcelona", "Spain", fc, CityThresholds.from_dict(snapshot(cached)),
                       lat=41.39, lon=2.16, today=TODAY)
    cached["identity"] = sample_identity("Barcelona", "Venezuela", 10.14, -64.69)
    ve = evaluate_city("Barcelona", "Venezuela", fc, CityThresholds.from_dict(snapshot(cached)),
                       lat=10.14, lon=-64.69, today=TODAY)
    assert es.all_time_high.event_id != ve.all_time_high.event_id
    assert places.event_identity(es.all_time_high.event_id)["place_id"] != places.event_identity(ve.all_time_high.event_id)["place_id"]


def test_record_refresh_cap_withholds_unreconciled_candidate_with_visible_reason(monkeypatch):
    monkeypatch.setattr(runner, "WORLD_WARM_BUDGET", 1)
    seed = {K(city): _thresh(city, STALE_ISO, all_time_max=(44.0, 2000)) for city in ("A", "B")}
    calls = []
    def archive(city):
        calls.append(city["city"])
        return _arch(max_c=46)
    bundles, _, _, metrics = _run(monkeypatch, [_city("A"), _city("B")], seed,
        forecasts=_fc_map({city: {"max_c": 47, "min_c": 12} for city in ("A", "B")}), archive=archive)
    assert calls == ["A"]
    assert {bundle.city for bundle in bundles if bundle.all_time_high} == {"A"}
    assert metrics["record_refresh_candidates"] == 2 and metrics["record_comparisons_withheld"] == 1
    assert metrics["withheld_record_candidates"][0]["city"] == "B"
    assert metrics["withheld_record_candidates"][0]["reason"] == "unreconciled_archive_cutoff"
    assert metrics["status"] == "degraded"


def test_saturated_warming_reaches_one_uncached_city_after_top_record_refresh(monkeypatch):
    from src.data.openmeteo_budget import OpenMeteoBudget

    class FourWarmSlots(OpenMeteoBudget):
        warm_waits = 0

        def next_available_delay(self, weight):
            if weight == 235:
                self.warm_waits += 1
                if self.warm_waits > 4:
                    raise OpenMeteoSaturated("Invented four-attempt WARM budget")
            return super().next_available_delay(weight)

    monkeypatch.setattr(runner, "OpenMeteoBudget", FourWarmSlots)
    cached = ["A", "B", "C", "D", "E"]
    cities = [_city(name) for name in [*cached, "F"]]
    seed = {K(name): _thresh(name, STALE_ISO, all_time_max=(44.0, 2000)) for name in cached}
    archives = []

    def archive(city):
        archives.append(city["city"])
        return _arch(max_c=46.0)

    bundles, _, store, metrics = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({name: {"max_c": 47.0, "min_c": 12.0} for name in cached}),
        archive=archive,
    )

    assert archives == ["A", "F", "B", "C"]
    assert metrics["warm_attempted"] == 4 and metrics["warm_saturated"]
    assert metrics["forecast_attempted"] == metrics["record_refresh_candidates"] == 5
    assert K("F") in store and metrics["cached_count"] == 6
    assert {bundle.city for bundle in bundles if bundle.all_time_high} == {"A", "B", "C"}
    assert {row["city"] for row in metrics["withheld_record_candidates"]} == {"D", "E"}


def _mock_archive_transport(monkeypatch, *statuses):
    from src.data.bounded_http import BoundedTransport, Response, TransportOutcome

    calls = []
    remaining = iter(statuses)
    body = json.dumps(provider_payload({"daily": _arch(max_c=46.0)})).encode()

    def get(transport, url):
        assert transport.limits.max_requests == 1 and transport.limits.max_redirects == 0
        status = next(remaining)
        calls.append((status, runner.staging.now(), url))
        if status >= 500:
            raise TransportOutcome("provider_error", status=status)
        return Response(url, url, status, {}, body, len(body))

    monkeypatch.setattr(BoundedTransport, "get", get)
    return calls


@responses.activate
def test_transient_record_refresh_leaves_next_real_http_attempt_for_bootstrap(monkeypatch):
    forecast_url = runner.open_meteo.BASE_URL + "/forecast"
    seed = {K("Record"): _thresh("Record", STALE_ISO, all_time_max=(44.0, 2000))}
    forecast = provider_payload({"daily": {"temperature_2m_max": [47.0]}}, ISO)
    responses.get(forecast_url, json=forecast)
    archives = _mock_archive_transport(monkeypatch, 503, 200)

    bundles, _, store, metrics = _run(monkeypatch, [_city("Record"), _city("Missing")], seed)

    assert [call.response.status_code for call in responses.calls] == [200]
    assert [row[0] for row in archives] == [503, 200]
    assert metrics["warm_attempt_reservations"] == metrics["warm_attempted"] == 2
    assert metrics["warm_reserved_weight"] == 470 and metrics["warm_failures"] == 1
    assert K("Missing") in store and store[K("Record")]["as_of"] == STALE_ISO
    assert metrics["forecast_attempted"] == 1 and metrics["record_comparisons_withheld"] == 1
    assert not any(bundle.all_time_high for bundle in bundles)


@responses.activate
def test_physical_archive_retry_is_reserved_and_paces_later_city(monkeypatch):
    from src.data import _http

    monkeypatch.setattr(_http, "_sleep_before_retry", lambda *_: None)
    archives = _mock_archive_transport(monkeypatch, 503, 200, 200)

    _, _, store, metrics = _run(monkeypatch, [_city("A"), _city("B")], {})

    assert [row[1] for row in archives] == [0, 0, 60]
    assert metrics["warm_attempted"] == 2 and metrics["warm_attempt_reservations"] == 3
    assert metrics["warm_reserved_weight"] == 705
    assert K("A") in store and K("B") in store


@responses.activate
def test_staged_deadline_defers_archive_and_keeps_forecast_result(monkeypatch):
    from src.two_bot.call_inventory import CancelToken, run_cancellable

    forecast = provider_payload({"daily": {"temperature_2m_max": [47.0]}}, ISO)
    responses.get(runner.open_meteo.BASE_URL + "/forecast", json=forecast)
    token = CancelToken("world_fixture", deadline=34, clock=runner.staging.now)
    seed = {K("Record"): _thresh("Record", ISO, all_time_max=(44.0, 2000))}

    bundles, _, store, metrics = run_cancellable(
        token, _run, monkeypatch, [_city("Record"), _city("Missing")], seed,
    )

    assert len(responses.calls) == 1
    assert metrics["warm_deferral"] == "elapsed" and metrics["warm_attempt_reservations"] == 0
    assert metrics["warm_provider_saturated"] is False
    assert metrics["forecast_attempted"] == 1 and K("Missing") not in store
    assert any(bundle.all_time_high for bundle in bundles)


@responses.activate
def test_forecast_retry_weight_is_shared_with_archive_pacing(monkeypatch):
    from src.data import _http

    monkeypatch.setattr(_http, "_sleep_before_retry", lambda *_: None)
    forecast_url = runner.open_meteo.BASE_URL + "/forecast"
    cached = [f"Cached-{i}" for i in range(6)]
    seed = {K(city): _thresh(city, ISO, all_time_max=(44.0, 2000)) for city in cached}
    forecast = provider_payload({"daily": {"temperature_2m_max": [35.0]}}, ISO)
    responses.get(forecast_url, status=503)
    responses.get(forecast_url, json=[forecast] * len(cached))
    archives = _mock_archive_transport(monkeypatch, 200, 200)

    _, _, _, metrics = _run(monkeypatch, [_city(city) for city in [*cached, "A", "B"]], seed)

    assert [call.response.status_code for call in responses.calls] == [503, 200]
    assert [row[1] for row in archives] == [0, 60]
    assert metrics["forecast_attempted"] == len(cached)
    assert metrics["warm_attempt_reservations"] == 2 and metrics["warm_reserved_weight"] == 470


@responses.activate
def test_admitted_archive_trickle_stops_and_consolidates_without_retry(monkeypatch):
    import socket
    import threading

    from src.data.bounded_http import BoundedTransport
    from src.two_bot.call_inventory import CancelToken, run_cancellable

    forecast = provider_payload({"daily": {"temperature_2m_max": [47.0]}}, ISO)
    responses.get(runner.open_meteo.BASE_URL + "/forecast", json=forecast)
    monkeypatch.setattr(runner.open_meteo, "ARCHIVE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setattr(runner.open_meteo, "ARCHIVE_REQUEST_TIMEOUT", 0.15)
    stop = threading.Event()
    connection_attempts = []
    requests_seen = []

    client, server = socket.socketpair()
    with client, server:
        server.settimeout(1)

        def connect(_transport, _addresses):
            connection_attempts.append(True)
            return client

        def trickle():
            try:
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = server.recv(4096)
                    if not chunk:
                        return
                    request += chunk
                requests_seen.append(request)
                server.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 500\r\n\r\n")
                while not stop.wait(0.01):
                    server.sendall(b" ")
            except OSError:
                return

        monkeypatch.setattr(BoundedTransport, "_connect", connect)
        fixture = threading.Thread(target=trickle)
        fixture.start()
        try:
            seed = {K("Record"): _thresh("Record", ISO, all_time_max=(44.0, 2000))}
            started = runner.staging.now()
            token = CancelToken("world_fixture", deadline=started + 6, clock=runner.staging.now)
            bundles, _, store, metrics = run_cancellable(
                token, _run, monkeypatch, [_city("Record"), _city("Missing")], seed, real_clock=True,
            )
            assert runner.staging.now() - started < 1
        finally:
            stop.set()
            fixture.join(timeout=2)

    assert not fixture.is_alive()
    assert len(connection_attempts) == len(requests_seen) == 1
    assert requests_seen[0].startswith(b"GET /v1/archive?")
    assert metrics["warm_deferral"] == "request_deadline"
    assert metrics["warm_attempt_reservations"] == 1 and metrics["warm_reserved_weight"] == 235
    assert not token.cancelled and K("Missing") not in store
    assert any(bundle.all_time_high for bundle in bundles)
