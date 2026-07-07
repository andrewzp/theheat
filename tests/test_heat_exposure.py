"""Row 13 — heat-exposure detection layer (US population under Extreme Heat Warnings).

Pure computation over already-fetched NWS alerts joined to a vendored, public-domain
Census county-FIPS -> population map. No network in these tests.
"""

from __future__ import annotations

from src.data import heat_exposure


def test_same_to_fips_strips_portion_digit():
    # SAME is P-SS-CCC: leading digit is the "portion of county" flag (0 = whole);
    # the trailing 5 digits are the standard county FIPS regardless of the flag.
    assert heat_exposure.same_to_fips("048201") == "48201"  # Travis-style whole county
    assert heat_exposure.same_to_fips("001001") == "01001"
    assert heat_exposure.same_to_fips("148201") == "48201"  # non-zero portion -> same county
    assert heat_exposure.same_to_fips("bad") is None
    assert heat_exposure.same_to_fips("") is None
    assert heat_exposure.same_to_fips("12345") is None  # wrong length


def test_load_county_population_has_known_county():
    pop = heat_exposure.load_county_population()
    assert pop["01001"] == 61464  # Autauga County, AL (verified vs co-est2024)
    assert len(pop) > 3000
    assert all(isinstance(v, int) for v in pop.values())


def test_compute_heat_exposure_dedups_counties_filters_warnings_and_drops_unknown():
    pop = heat_exposure.load_county_population()
    a, b, c = "48201", "48113", "06037"  # Harris TX, Dallas TX, LA CA
    alerts = [
        {"event": "Extreme Heat Warning", "same": ["0" + a, "0" + b]},
        {"event": "Extreme Heat Warning", "same": ["0" + b, "0" + c]},  # b shared -> dedup
        {"event": "Heat Advisory", "same": ["001001"]},  # not a Warning -> excluded
        {"event": "Extreme Heat Warning", "same": ["075001"]},  # invalid FIPS (marine/unknown) -> dropped
    ]
    ev = heat_exposure.compute_heat_exposure(alerts, population=pop, as_of="2026-07-07T20:00:00Z")

    assert ev is not None
    assert set(ev.fips) == {a, b, c}
    assert ev.county_count == 3
    assert ev.population == pop[a] + pop[b] + pop[c]
    assert ev.warning_event == "Extreme Heat Warning"
    assert ev.as_of == "2026-07-07T20:00:00Z"
    # Deterministic provenance: fips sorted.
    assert list(ev.fips) == sorted(ev.fips)


def test_compute_heat_exposure_none_when_no_qualifying_warnings():
    pop = heat_exposure.load_county_population()
    # Only advisories / watches -> no Extreme Heat Warning population -> no event.
    assert heat_exposure.compute_heat_exposure(
        [{"event": "Heat Advisory", "same": ["001001"]}], population=pop, as_of="x"
    ) is None
    assert heat_exposure.compute_heat_exposure([], population=pop, as_of="x") is None


def test_compute_heat_exposure_sample_states_ranks_by_warned_population():
    pop = heat_exposure.load_county_population()
    # CA county (state 06) far outweighs the two TX counties (state 48).
    alerts = [
        {"event": "Extreme Heat Warning", "same": ["006037", "048201", "048113"]},
    ]
    ev = heat_exposure.compute_heat_exposure(alerts, population=pop, as_of="x")
    assert ev is not None
    # LA County alone (9.7M) > Harris+Dallas (7.6M), so CA leads the state roll-up.
    assert ev.sample_states[0] == "06"
