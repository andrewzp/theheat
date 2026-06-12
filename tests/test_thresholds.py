import ast
from pathlib import Path

import pytest

import src.editorial.scoring as scoring
from src.editorial.thresholds import THRESHOLDS, get_threshold


SCORING_DIR = Path("src/editorial/scoring")

EXPECTED_THRESHOLD_KEYS_BY_FUNCTION = {
    "score_all_time_record": {"all_time_record"},
    "score_anomaly": {"anomaly"},
    "score_absolute_extreme": {"absolute_extreme"},
    "score_ch4_milestone": {"ch4_milestone"},
    "score_co2_milestone": {"co2_milestone"},
    "score_coral_bleaching": {"coral_bleaching"},
    "score_country_record": {"country_high", "country_low"},
    "score_cyclone_basin_record": {"cyclone_basin_record"},
    "score_cyclone_landfall": {"cyclone_landfall"},
    "score_cyclone_rapid_intensification": {"cyclone_rapid_intensification"},
    "score_cyclone_tier_crossing": {"cyclone_tier_crossing"},
    "score_dust_event": {"dust_event"},
    "score_drought": {"drought", "drought_empty"},
    "score_enso_transition": {"enso"},
    "score_extreme_wave": {"extreme_wave"},
    "score_fire_event": {"fire"},
    "score_fire_footprint": {"fire_footprint"},
    "score_global_disaster": {"global_disaster"},
    "score_global_flood": {"global_flood"},
    "score_hot10": {"hot10"},
    "score_ice_mass_event": {"ice_mass_record"},
    "score_marine_heatwave": {"marine_heatwave"},
    "score_regional_sst_anomaly": {"regional_sst_anomaly"},
    "score_regional_anomaly": {"regional_anomaly"},
    "score_monthly_record": {"monthly_record"},
    "score_oscillation_extreme": {"oscillation_extreme"},
    "score_oscillation_transition": {"oscillation_transition"},
    "score_ozone_hole_peak": {"ozone_hole_peak"},
    "score_pm25_hazard": {"air_quality_hazard"},
    "score_precipitation_extreme": {"precipitation_extreme"},
    "score_record_event": {"record"},
    "score_record_low_event": {"record_low"},
    "score_record_streak": {"record_streak"},
    "score_river_flood": {"river_flood"},
    "score_sea_ice_record": {"sea_ice_record"},
    "score_seasonal_snow_record": {"seasonal_snow_record"},
    "score_severe_weather": {"severe_weather"},
    "score_simultaneous_records": {"simultaneous_records"},
    "score_snow_extreme": {"snow_extreme"},
    "score_storm_surge": {"storm_surge"},
    "score_synthesis_fire_drought_heat": {"synthesis_fire_drought_heat"},
    "score_synthesis_marine_compound": {"synthesis_marine_compound"},
    "score_wet_bulb_extreme": {"wet_bulb_extreme"},
}


def _scoring_modules() -> list[Path]:
    return sorted(
        path
        for path in SCORING_DIR.glob("*.py")
        if path.name not in {"__init__.py", "_shared.py"}
    )


def _threshold_keys_in_scoring_modules() -> dict[str, set[str]]:
    keys_by_function: dict[str, set[str]] = {}
    for path in _scoring_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("score_"):
                keys_by_function[node.name] = set()
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id == "get_threshold"
                    ):
                        arg = child.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            keys_by_function[node.name].add(arg.value)
                        elif (
                            isinstance(arg, ast.JoinedStr)
                            and node.name == "score_country_record"
                        ):
                            keys_by_function[node.name].update({"country_high", "country_low"})
                        else:
                            raise AssertionError(
                                f"{path}:{node.name} uses a non-literal threshold key"
                            )
    return keys_by_function


def test_registry_covers_every_public_score_function():
    public_score_functions = {
        name for name in scoring.__all__ if name.startswith("score_")
    }

    assert set(EXPECTED_THRESHOLD_KEYS_BY_FUNCTION) == public_score_functions
    assert set(THRESHOLDS) == {
        key
        for keys in EXPECTED_THRESHOLD_KEYS_BY_FUNCTION.values()
        for key in keys
    }


def test_score_functions_use_registry_thresholds():
    keys_by_function = _threshold_keys_in_scoring_modules()

    assert keys_by_function == EXPECTED_THRESHOLD_KEYS_BY_FUNCTION


def test_no_inline_score_gate_thresholds_remain():
    for path in _scoring_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "_build_score"):
                continue
            threshold_keywords = [kw for kw in node.keywords if kw.arg == "threshold"]
            assert len(threshold_keywords) == 1, f"{path} has a _build_score call without one gate"
            threshold_value = threshold_keywords[0].value
            assert isinstance(threshold_value, ast.Call), f"{path} still has an inline threshold"
            assert isinstance(threshold_value.func, ast.Name)
            assert threshold_value.func.id == "get_threshold"


def test_registry_entries_are_valid():
    for key, entry in THRESHOLDS.items():
        assert isinstance(entry.category, str)
        assert entry.category
        assert isinstance(entry.threshold, int), key
        assert 0 <= entry.threshold <= 100, key
        assert entry.rationale.strip(), key


def test_get_threshold_raises_for_unknown_category():
    with pytest.raises(KeyError):
        get_threshold("not_a_real_score_category")
