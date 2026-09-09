from copy import deepcopy
from types import SimpleNamespace
from tests.temperature_helpers import snapshot, dated_forecast
from src.data import places

def sample_identity(city, country, lat, lon):
    return {**places.resolve_place(city, country, lat, lon), "source_product": places.CACHE_PRODUCT}

from datetime import date as _date

from src.orchestrator.world_cache import apply_provisional, merge_caches, select_stale_cities

def K(city, country="Spain", lat=40.4, lon=-3.7):
    return places.cache_key(city, country, lat, lon)

def attributed(cache, country="Spain", lat=40.4, lon=-3.7):
    return {K(city, country, lat, lon): snapshot({**row, "identity": sample_identity(city, country, lat, lon)}) for city, row in cache.items()}
from src.data.world_thresholds import evaluate_city, CityThresholds


def test_merge_equal_as_of_conflicting_versions_quarantines_instead_of_mixing_extrema():
    a = {"Madrid": {"city": "Madrid", "as_of": "2026-06-26", "all_time_max": [44.0, 2023], "monthly_min": {"06": [8.0, 1997]}}}
    b = {"Madrid": {"city": "Madrid", "as_of": "2026-06-26", "all_time_max": [45.5, 2026], "monthly_min": {"06": [9.0, 2020]}}}
    out = merge_caches(attributed(a), attributed(b))
    assert K("Madrid") not in out
    assert len(out["_meta"]["baseline_conflicts"][K("Madrid")]["versions"]) == 2


def test_merge_newer_as_of_wins_and_unions_cities():
    base = {"Lyon": {"city": "Lyon", "as_of": "2026-06-20", "all_time_max": [40.0, 2019]}}
    nxt = {"Lyon": {"city": "Lyon", "as_of": "2026-06-26", "all_time_max": [39.0, 2026]},
           "Paris": {"city": "Paris", "as_of": "2026-06-26"}}
    out = merge_caches(attributed(base, "France"), attributed(nxt, "France"))
    assert out[K("Lyon", "France")]["as_of"] == "2026-06-26"          # newer wins wholesale
    assert out[K("Lyon", "France")]["all_time_max"] == [39.0, 2026]
    assert K("Paris", "France") in out


def test_select_stale_prefers_urgent_then_oldest_and_caps():
    world = [{"city": c, "country": "X", "lat": "0", "lon": "0"} for c in ["Madrid", "Lyon", "Zzz", "Aaa"]]
    # cache keyed by world_key (city|country)
    cache = {K("Madrid", "X", 0, 0): {"as_of": "2026-06-25"}, K("Lyon", "X", 0, 0): {"as_of": "2026-04-01"}, K("Aaa", "X", 0, 0): {"as_of": "2026-04-01"}}
    out = select_stale_cities(cache, world, ttl_days=30, budget=2, today="2026-06-26", urgent_order=["Lyon", "Madrid"])
    names = [c["city"] for c in out]
    assert "Lyon" in names and "Madrid" not in names and len(out) == 2


def test_provisional_does_not_change_historical_extrema_or_archive_freshness():
    from src.orchestrator.world_cache import apply_provisional_preserving_as_of
    original = attributed({"Madrid": {"city": "Madrid", "as_of": "2026-06-01", "all_time_max": [44.0, 2023]}})
    bundle = SimpleNamespace(city="Madrid", country="Spain", lat=40.4, lon=-3.7, all_time_high=SimpleNamespace(new_temp_c=50))
    for advance in (False, True):
        cache = deepcopy(original)
        apply_provisional(cache, bundle, today="2026-06-26")
        apply_provisional_preserving_as_of(cache, bundle, today="2026-06-26", advance_as_of=advance, ttl_days=30)
        assert cache == original


def test_read_cache_drops_legacy_bare_city_keys(monkeypatch):
    """One-time migration: legacy bare-city keys (pre city|country re-key) are dropped on
    read so write_cache can't merge them back and inflate cached_count."""
    import json
    from src.orchestrator import world_cache as wc

    payload = {"files": {wc.WORLD_CACHE_FILENAME: {"content": json.dumps({
        "Barcelona": {"city": "Barcelona", "as_of": "2026-06-01"},        # legacy bare key
        "Barcelona|Spain": {"city": "Barcelona", "as_of": "2026-06-20"},  # composite (kept)
        "Barcelona|Venezuela": {"city": "Barcelona", "as_of": "2026-06-20"},
        "_meta": {"cached_count": 2, "as_of": "2026-06-20"},
    })}}}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    monkeypatch.setattr(wc, "GIST_ID", "gid")
    monkeypatch.setattr(wc, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(wc, "_headers", lambda: {})
    monkeypatch.setattr(wc.requests, "get", lambda *a, **k: _Resp())

    out = wc.read_cache()
    assert set(out) == {"_meta"}
    assert out["_meta"]["quarantined_count"] == 3
    assert {row["legacy_key"] for row in out["_meta"]["identity_quarantine"].values()} == {"Barcelona", "Barcelona|Spain", "Barcelona|Venezuela"}
