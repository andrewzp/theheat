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

from src.data.open_meteo import AbsoluteExtremeEvent
from src.data.openmeteo_budget import OpenMeteoSaturated
from src.data.world_thresholds import CityThresholds
from src.orchestrator import world_cache
from src.orchestrator.sources import open_meteo as runner

TODAY = date.today()
ISO = TODAY.isoformat()
STALE_ISO = (TODAY - timedelta(days=60)).isoformat()
MM = f"{TODAY.month:02d}"
YEAR = TODAY.year
ARCH_YEAR = 2010
DAY = f"{ARCH_YEAR}-{MM}-01"


def K(city, country="Spain"):
    return world_cache.world_key(city, country)


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
    return a


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


def _run(monkeypatch, world_cities, seed_cache, *, forecasts, archive,
         abs_extreme=None, country=None, meta_prev=None, real_country=False):
    """Run _run_world_cached_half with patched IO. seed_cache is keyed by world_key.

    Returns (om_bundles, om_country, store, metrics).
    """
    store = dict(seed_cache)
    if meta_prev is not None:
        store["_meta"] = {"cached_count": meta_prev, "as_of": STALE_ISO}
    monkeypatch.setattr(world_cache, "read_cache", lambda: dict(store))

    def _write(c):
        store.clear()
        store.update(c)
        return True

    monkeypatch.setattr(world_cache, "write_cache", _write)
    monkeypatch.setattr("src.data.open_meteo.fetch_forecasts_batch", forecasts)
    monkeypatch.setattr(runner, "_fetch_city_archive", archive)
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
    assert store[K("Barcelona", "Spain")]["all_time_max"] == [45.0, YEAR]    # stamped
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


# --- 3. Stale-cache record CONFIRMED by fresh archive emits + stamps
def test_stale_record_confirmed_by_fresh_archive(monkeypatch):
    seed = {K("C"): _thresh("C", STALE_ISO, all_time_max=(44.0, 2000))}
    cities = [_city("C")]
    om_bundles, _c, store, _m = _run(
        monkeypatch, cities, seed,
        forecasts=_fc_map({"C": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=lambda c: _arch(max_c=46.0))
    assert any(b.all_time_high is not None for b in om_bundles)
    assert store[K("C")]["all_time_max"] == [47.0, YEAR]
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
    assert store[K("C")]["all_time_max"] == [47.0, YEAR]
    assert store[K("C")]["monthly_mean"][MM] == [46.0, 12.0, 1]
    assert store[K("C")]["wetbulb_max"] == [28.0, ARCH_YEAR]
    assert any(b.all_time_high is not None for b in om_bundles)


# --- 5b. Warm fails -> entry untouched except stamped record fields; as_of preserved
def test_no_stale_field_carryover_warm_fails(monkeypatch):
    seed = {K("C"): _thresh("C", STALE_ISO, all_time_max=(44.0, 2000),
                            monthly_mean={MM: (20.0, 10.0, 50)}, wetbulb_max=(30.0, 2005))}
    cities = [_city("C")]
    om_bundles, _c, store, m = _run(
        monkeypatch, cities, seed, meta_prev=1,
        forecasts=_fc_map({"C": {"max_c": 47.0, "min_c": 12.0, "tw_max_c": 10.0}}),
        archive=_raise(OpenMeteoSaturated("archive 429")))
    assert store[K("C")]["all_time_max"] == [47.0, YEAR]
    assert store[K("C")]["monthly_mean"][MM] == [20.0, 10.0, 50]
    assert store[K("C")]["wetbulb_max"] == [30.0, 2005]
    assert store[K("C")]["as_of"] == STALE_ISO
    assert any(b.all_time_high is not None for b in om_bundles)
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
    assert {b.city for b in om_bundles if b.all_time_high} == {"Aaa", "Bbb"}


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
    assert store[K("C")]["all_time_max"] == [45.0, YEAR]
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
    fc = {"max_c": 45.0, "min_c": 12.0, "tw_max_c": 10.0}
    es = evaluate_city("Barcelona", "Spain", fc, CityThresholds.from_dict(cached),
                       lat=41.39, lon=2.16, today=TODAY)
    ve = evaluate_city("Barcelona", "Venezuela", fc, CityThresholds.from_dict(cached),
                       lat=10.14, lon=-64.69, today=TODAY)
    assert es.all_time_high.event_id != ve.all_time_high.event_id
    assert "Spain" in es.all_time_high.event_id and "Venezuela" in ve.all_time_high.event_id
