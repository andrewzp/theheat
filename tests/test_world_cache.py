from src.orchestrator.world_cache import merge_caches, select_stale_cities


def test_merge_equal_as_of_is_field_wise_more_extreme():
    # run A warmed Madrid fully; run B fired all_time_high (provisional), same day.
    a = {"Madrid": {"city": "Madrid", "as_of": "2026-06-26",
                    "all_time_max": [44.0, 2023], "monthly_min": {"06": [8.0, 1997]}}}
    b = {"Madrid": {"city": "Madrid", "as_of": "2026-06-26",
                    "all_time_max": [45.5, 2026], "monthly_min": {"06": [9.0, 2020]}}}
    out = merge_caches(a, b)
    assert out["Madrid"]["all_time_max"] == [45.5, 2026]   # hotter high wins
    assert out["Madrid"]["monthly_min"]["06"] == [8.0, 1997]  # colder low wins
    # neither run's field was erased (the P0 bug)


def test_merge_newer_as_of_wins_and_unions_cities():
    base = {"Lyon": {"city": "Lyon", "as_of": "2026-06-20", "all_time_max": [40.0, 2019]}}
    nxt = {"Lyon": {"city": "Lyon", "as_of": "2026-06-26", "all_time_max": [39.0, 2026]},
           "Paris": {"city": "Paris", "as_of": "2026-06-26"}}
    out = merge_caches(base, nxt)
    assert out["Lyon"]["as_of"] == "2026-06-26"          # newer wins wholesale
    assert out["Lyon"]["all_time_max"] == [39.0, 2026]
    assert "Paris" in out


def test_select_stale_prefers_urgent_then_oldest_and_caps():
    world = [{"city": c, "country": "X", "lat": "0", "lon": "0"} for c in ["Madrid", "Lyon", "Zzz", "Aaa"]]
    cache = {"Madrid": {"as_of": "2026-06-25"}, "Lyon": {"as_of": "2026-04-01"}, "Aaa": {"as_of": "2026-04-01"}}
    out = select_stale_cities(cache, world, ttl_days=30, budget=2, today="2026-06-26", urgent_order=["Lyon", "Madrid"])
    names = [c["city"] for c in out]
    assert "Lyon" in names and "Madrid" not in names and len(out) == 2
