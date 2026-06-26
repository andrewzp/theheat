from src.data.world_thresholds import CityThresholds, MIN_MEAN_SAMPLES


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
