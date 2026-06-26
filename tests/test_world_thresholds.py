from src.data.world_thresholds import CityThresholds, MIN_MEAN_SAMPLES, compute_city_thresholds


def test_city_thresholds_roundtrips_through_dict():
    t = CityThresholds(
        city="Madrid", as_of="2026-06-26", years_of_data=30,
        all_time_max=(44.1, 2023), all_time_min=(-4.2, 2001),
        monthly_max={"06": (43.0, 2019)}, monthly_min={"06": (8.0, 1997)},
        monthly_mean={"06": (32.4, 17.1, 900)}, wetbulb_max=(26.0, 2022),
    )
    again = CityThresholds.from_dict(t.to_dict())
    assert again == t
    assert again.monthly_max["06"] == (43.0, 2019)
    assert MIN_MEAN_SAMPLES >= 1


def test_compute_means_use_independent_high_low_counts():
    archive = {
        "time": ["1996-06-01", "1996-06-02", "1996-06-03"],
        "temperature_2m_max": [40.0, 42.0, 41.0],   # 3 highs -> mean 41.0
        "temperature_2m_min": [10.0, None, 12.0],   # 2 lows  -> mean 11.0 (NOT /3)
        "wet_bulb_temperature_2m_max": [24.0, 25.0, 26.0],
    }
    t = compute_city_thresholds("T", archive, as_of="2026-06-26")
    mh, ml, n = t.monthly_mean["06"]
    assert mh == 41.0
    assert ml == 11.0          # 22/2, not 22/3
    assert n == 3              # sample_count = high-day count (paired-record basis)
    assert t.all_time_max[0] == 42.0 and t.all_time_min[0] == 10.0
    assert t.wetbulb_max[0] == 26.0
