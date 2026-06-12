#!/usr/bin/env python3
"""Regenerate the committed merge-state golden fixture from the current _merge_state.

Each case exercises one strategy type or a Codex adversarial edge. The golden test
(tests/test_state.py::TestMergeStateGolden) asserts VALUE equality, so it catches
wrong-strategy / wrong-floor wiring regressions that the structural coverage test
cannot. Run after an intentional change to merge semantics, then review the diff:

    python scripts/gen_merge_golden.py
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.state import _merge_state  # noqa: E402

# (label, base, incoming) — kept small + readable; the fixture freezes the expected merge.
CASES = [
    ("max_by_key.int.co2", {"co2_annual_count": {"2025": 4, "2026": 2}}, {"co2_annual_count": {"2026": 5, "2027": 1}}),
    ("max_by_key.int.ice_annual", {"ice_annual_count": {"2026": 3}}, {"ice_annual_count": {"2026": 7}}),
    ("max_by_key.floor_neg1.fire_tier0", {"fire_complex_tiers": {"A": 2}}, {"fire_complex_tiers": {"A": 1, "C": 0}}),
    ("max_by_key.floor_neg1.cyclone_tier0", {"cyclone_tiers": {}}, {"cyclone_tiers": {"nhc:al01": 0}}),
    ("max_by_key.str.tier_touch_ts", {"tier_touch_ts": {"fire_complex_tiers::A": "2026-06-01T00:00:00Z"}}, {"tier_touch_ts": {"fire_complex_tiers::A": "2026-06-02T00:00:00Z", "cyclone_tiers::B": "2026-06-01T00:00:00Z"}}),
    ("max_by_key.str.ice_last_seen", {"ice_mass_last_seen": {"greenland": "2026-01"}}, {"ice_mass_last_seen": {"greenland": "2026-03", "antarctica": "2025-12"}}),
    ("max_by_key.str.reganom", {"reganom_last_fired": {"sahel": "2026-05-01"}}, {"reganom_last_fired": {"sahel": "2026-06-01"}}),
    ("reduce.ice_max_loss", {"ice_mass_max_loss": {"r": {"gt": -3.0, "month": "2026-01"}}}, {"ice_mass_max_loss": {"r": {"gt": -7.0, "month": "2026-02"}}}),
    ("reduce.ice_milestone_onesided", {"ice_mass_last_milestone": {"r": -5.0}}, {"ice_mass_last_milestone": {}}),
    ("reduce.aq_newer_date", {"air_quality_pm25_tiers": {"delhi": {"tier": 2, "date": "2026-06-01"}}}, {"air_quality_pm25_tiers": {"delhi": {"tier": 1, "date": "2026-06-05"}}}),
    ("reduce.aq_higher_tier_same_date", {"air_quality_dust_tiers": {"lahore": {"tier": 1, "date": "2026-06-01"}}}, {"air_quality_dust_tiers": {"lahore": {"tier": 3, "date": "2026-06-01"}}}),
    ("reduce.flood_severity", {"flood_activation_tiers": {"EMSR1": "Minor"}}, {"flood_activation_tiers": {"EMSR1": "Major"}}),
    ("dict_overlay.daily", {"daily_tweet_count": {"2026-06-01": 3}}, {"daily_tweet_count": {"2026-06-09": 1}}),
    ("ordered_unique.posted", {"posted_events": ["a", "b"]}, {"posted_events": ["b", "c"]}),
    ("take_incoming.last_phase", {"nao_last_phase": "positive"}, {"nao_last_phase": "negative"}),
    ("take_incoming.record_streaks", {"record_streaks": {"Cairo": {"days": 2}}}, {"record_streaks": {"Cairo": {"days": 3}}}),
    ("custom.ch4_onesided", {}, {"ch4_last_milestone": 1940}),
    ("custom.ch4_both", {"ch4_last_milestone": 1900}, {"ch4_last_milestone": 1950}),
    ("custom.fire_footprint", {"fire_footprint_last_run": "2026-06-01"}, {"fire_footprint_last_run": "2026-06-02"}),
    ("custom.dsf_reset", {"data_source_failures": {"open_meteo": 4}}, {"data_source_failures": {"open_meteo": 0}}),
    ("custom.dsf_absent_keeps_base", {"data_source_failures": {"open_meteo": 4}}, {"data_source_failures": {}}),
    ("custom.ozone_peak", {"ozone_hole_last_peak": {"2026": {"area_million_km2": 22.0}}}, {"ozone_hole_last_peak": {"2026": {"area_million_km2": 25.0}}}),
    (
        "multikey.realistic",
        {
            "co2_annual_count": {"2026": 3},
            "fire_complex_tiers": {"A": 1},
            "data_source_failures": {"gpm_imerg": 2},
            "posted_events": ["e1"],
            "daily_tweet_count": {"2026-06-08": 2},
            "reganom_last_fired": {"sahel": "2026-05-01"},
        },
        {
            "co2_annual_count": {"2026": 5, "2027": 1},
            "fire_complex_tiers": {"A": 0, "B": 2},
            "data_source_failures": {"gpm_imerg": 0, "air_quality": 1},
            "posted_events": ["e1", "e2"],
            "daily_tweet_count": {"2026-06-09": 1},
            "reganom_last_fired": {"sahel": "2026-06-01"},
        },
    ),
]


def main() -> None:
    out = []
    for label, a, b in CASES:
        merged = _merge_state(a, b)
        touched = sorted(set(a) | set(b))  # store only touched keys, for a focused fixture
        out.append({"label": label, "base": a, "incoming": b, "expected": {k: merged[k] for k in touched}})
    path = REPO / "tests" / "fixtures" / "merge_state_golden.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(out)} golden cases -> {path}")


if __name__ == "__main__":
    main()
