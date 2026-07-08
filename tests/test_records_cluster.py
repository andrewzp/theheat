"""Tests for src/editorial/records_cluster.py — spatial clustering of same-day
heat-record cities + honest, non-overclaiming geographic naming (#414).

Pure, deterministic, no I/O. The naming tests are the crux: a wrong region or
continent label is a geography-honesty failure, the class @theheat guards
everywhere. Cases below pin the exact failure modes codex-xhigh flagged
(Spain+Morocco purity; transcontinental Russia/Turkey continent omission).
"""

from __future__ import annotations

from src.editorial.records_cluster import (
    LINK_KM,
    MIN_CLUSTER_SIZE,
    ZONE_COUNTRIES,
    ClusterName,
    cluster_record_stations,
    name_cluster,
)
from src.data.reanalysis_anomaly import REGION_WATCHLIST


def _st(city: str, country: str, lat: float, lon: float) -> dict:
    return {"city": city, "country": country, "lat": lat, "lon": lon}


# Real-ish coordinate anchors (reused across cases).
FRANCE = [
    _st("Paris", "France", 48.86, 2.35),
    _st("Lyon", "France", 45.75, 4.85),
    _st("Marseille", "France", 43.30, 5.37),
    _st("Bordeaux", "France", 44.84, -0.58),
    _st("Toulouse", "France", 43.60, 1.44),
    _st("Nantes", "France", 47.22, -1.55),
]
DESERT_SW = [
    _st("Phoenix", "US", 33.45, -112.07),
    _st("Las Vegas", "US", 36.17, -115.14),
    _st("Tucson", "US", 32.22, -110.93),
    _st("El Paso", "US", 31.76, -106.49),
    _st("Palm Springs", "US", 33.83, -116.55),
    _st("Yuma", "US", 32.69, -114.62),
]
# A tight (~200 km span) synthetic dome for pure separation/ordering tests, so
# they exercise clustering topology rather than any one real zone's sparse
# geometry (at L=350 the real 6-city Desert SW fragments — El Paso is ~418 km
# from its nearest neighbour; dense real data fills that gap. Calibration note
# for tuning L upward, tracked separately).
SYNTH_AUS = [
    _st("Sydney", "Australia", -33.87, 151.21),
    _st("Newcastle", "Australia", -32.93, 151.78),
    _st("Wollongong", "Australia", -34.42, 150.89),
    _st("Canberra", "Australia", -35.28, 149.13),
    _st("Katoomba", "Australia", -33.71, 150.31),
    _st("Nowra", "Australia", -34.88, 150.60),
]


# --------------------------------------------------------------------------- #
# clustering
# --------------------------------------------------------------------------- #

def test_single_tight_cluster_groups_all_members():
    clusters = cluster_record_stations(FRANCE, link_km=350, min_size=6)
    assert len(clusters) == 1
    assert {s["city"] for s in clusters[0]} == {s["city"] for s in FRANCE}


def test_two_far_apart_domes_stay_separate():
    stations = FRANCE + SYNTH_AUS  # Europe vs SE Australia, ~16000 km apart
    clusters = cluster_record_stations(stations, link_km=350, min_size=6)
    assert len(clusters) == 2
    cities = [{s["city"] for s in c} for c in clusters]
    assert {s["city"] for s in FRANCE} in cities
    assert {s["city"] for s in SYNTH_AUS} in cities


def test_single_linkage_chain_forms_one_cluster():
    # A-B-C strung west→east, each neighbor ~250 km (<= link) but A..F span
    # far more than link. Single-linkage must chain them into ONE cluster.
    chain = [_st(f"c{i}", "X", 40.0, lon) for i, lon in enumerate(
        [0.0, 3.0, 6.0, 9.0, 12.0, 15.0]  # ~255 km steps at lat 40
    )]
    clusters = cluster_record_stations(chain, link_km=350, min_size=6)
    assert len(clusters) == 1
    assert len(clusters[0]) == 6


def test_gap_larger_than_link_breaks_the_chain():
    left = [_st(f"L{i}", "X", 40.0, lon) for i, lon in enumerate([0.0, 2.0, 4.0])]
    right = [_st(f"R{i}", "X", 40.0, lon) for i, lon in enumerate([40.0, 42.0, 44.0])]
    # ~3000 km gap between the two triplets → neither reaches min_size=3? use 3
    clusters = cluster_record_stations(left + right, link_km=350, min_size=3)
    assert len(clusters) == 2


def test_below_min_size_is_dropped():
    assert cluster_record_stations(FRANCE[:5], link_km=350, min_size=6) == []


def test_stations_missing_latlon_are_excluded():
    bad = FRANCE + [
        {"city": "NoCoords", "country": "France"},
        {"city": "NoneCoords", "country": "France", "lat": None, "lon": None},
        {"city": "BadCoords", "country": "France", "lat": "x", "lon": "y"},
    ]
    clusters = cluster_record_stations(bad, link_km=350, min_size=6)
    assert len(clusters) == 1
    assert "NoCoords" not in {s["city"] for s in clusters[0]}
    assert len(clusters[0]) == 6


def test_deterministic_under_input_shuffle():
    import random
    a = cluster_record_stations(FRANCE + SYNTH_AUS, link_km=350, min_size=6)
    shuffled = list(FRANCE + SYNTH_AUS)
    random.Random(12345).shuffle(shuffled)
    b = cluster_record_stations(shuffled, link_km=350, min_size=6)
    # identical grouping AND identical member ordering AND identical cluster order
    assert [[s["city"] for s in c] for c in a] == [[s["city"] for s in c] for c in b]


def test_empty_and_degenerate_inputs():
    assert cluster_record_stations([], link_km=350, min_size=6) == []
    assert cluster_record_stations([_st("solo", "X", 0, 0)], link_km=350, min_size=6) == []


# --------------------------------------------------------------------------- #
# naming — tier 1 (documented reganom zone, country-pure + contained)
# --------------------------------------------------------------------------- #

def test_all_france_cluster_named_france_zone():
    name = name_cluster(FRANCE)
    assert name.region_name == "France"
    assert name.city_count == 6
    assert name.countries == ["France"]


def test_desert_southwest_cluster_named_zone():
    name = name_cluster(DESERT_SW)
    assert name.region_name == "Desert Southwest"


def test_us_country_variant_still_matches_us_zone():
    # GHCN emits "United States"; cities.csv emits "US". Purity must normalize.
    variant = [dict(s, country="United States") for s in DESERT_SW]
    assert name_cluster(variant).region_name == "Desert Southwest"


# --------------------------------------------------------------------------- #
# naming — the crux: purity + honesty (codex P0-1 / P0-2)
# --------------------------------------------------------------------------- #

def test_spain_morocco_cluster_is_not_named_iberia():
    # Iberia's points sit one strait from Maghreb's; a distance-only namer would
    # call this "Iberia". Country purity must reject it (Morocco not in Iberia).
    stations = [
        _st("Seville", "Spain", 37.39, -5.98),
        _st("Cadiz", "Spain", 36.53, -6.29),
        _st("Malaga", "Spain", 36.72, -4.42),
        _st("Gibraltar area", "Spain", 36.14, -5.35),
        _st("Tangier", "Morocco", 35.76, -5.83),
        _st("Tetouan", "Morocco", 35.57, -5.37),
    ]
    name = name_cluster(stations)
    assert name.region_name is None
    assert name.continents == ["Africa", "Europe"]
    assert set(name.countries) == {"Spain", "Morocco"}


def test_broad_multicountry_europe_dome_gets_no_zone_name():
    # France + Belgium + Netherlands + Germany: no documented zone covers this
    # (there is no "Western Europe" watchlist zone) → must NOT coin one.
    stations = [
        _st("Paris", "France", 48.86, 2.35),
        _st("Lille", "France", 50.63, 3.06),
        _st("Brussels", "Belgium", 50.85, 4.35),
        _st("Amsterdam", "Netherlands", 52.37, 4.90),
        _st("Cologne", "Germany", 50.94, 6.96),
        _st("Frankfurt", "Germany", 50.11, 8.68),
    ]
    name = name_cluster(stations)
    assert name.region_name is None
    assert name.continents == ["Europe"]  # all unambiguously Europe
    assert "Germany" in name.countries


def test_western_russia_cluster_omits_continent():
    # resolve_continent("Russia") == "Asia", but western Russia is Europe →
    # asserting a continent would be wrong. Transcontinental ⇒ omit continent.
    stations = [
        _st("Moscow", "Russia", 55.75, 37.62),
        _st("Tver", "Russia", 56.86, 35.90),
        _st("Tula", "Russia", 54.20, 37.62),
        _st("Ryazan", "Russia", 54.63, 39.74),
        _st("Kaluga", "Russia", 54.51, 36.27),
        _st("Vladimir", "Russia", 56.13, 40.41),
    ]
    name = name_cluster(stations)
    assert name.continents == []          # omitted, not guessed
    assert name.countries == ["Russia"]


def test_turkey_cluster_omits_continent():
    stations = [
        _st("Istanbul", "Turkey", 41.01, 28.98),
        _st("Bursa", "Turkey", 40.19, 29.06),
        _st("Izmit", "Turkey", 40.77, 29.92),
        _st("Ankara", "Turkey", 39.93, 32.86),
        _st("Eskisehir", "Turkey", 39.78, 30.52),
        _st("Balikesir", "Turkey", 39.65, 27.88),
    ]
    assert name_cluster(stations).continents == []


def test_unknown_country_is_listed_but_continent_omitted():
    stations = [
        _st("A", "Neverland", 10.0, 10.0),
        _st("B", "Neverland", 10.5, 10.5),
        _st("C", "France", 48.86, 2.35),
        _st("D", "France", 45.75, 4.85),
        _st("E", "France", 43.30, 5.37),
        _st("F", "France", 44.84, -0.58),
    ]
    name = name_cluster(stations)
    assert "Neverland" in name.countries
    assert name.continents == []  # one unresolved country ⇒ omit


def test_containment_gate_rejects_pure_country_far_from_zone_points():
    # All-US, but in the Northeast — nowhere near Desert SW / Pacific NW points.
    # Country purity alone must NOT be enough to name a zone (US is huge).
    stations = [
        _st("Boston", "US", 42.36, -71.06),
        _st("New York", "US", 40.71, -74.01),
        _st("Philadelphia", "US", 39.95, -75.17),
        _st("Portland ME", "US", 43.66, -70.26),
        _st("Providence", "US", 41.82, -71.41),
        _st("Hartford", "US", 41.76, -72.67),
    ]
    name = name_cluster(stations)
    assert name.region_name is None
    assert name.continents == ["North America"]


# --------------------------------------------------------------------------- #
# naming — missing/alias country hardening (codex PR-A P0s)
# --------------------------------------------------------------------------- #

def test_blank_country_blocks_zone_name_and_continent():
    # Spain+Morocco coords but country data missing: an empty country set must
    # NOT be treated as "pure" for every zone. codex repro: this returned
    # region_name='Iberia', countries=[]. A false geography claim from no data.
    stations = [
        _st("Seville", "", 37.39, -5.98),
        _st("Cadiz", "", 36.53, -6.29),
        _st("Malaga", "", 36.72, -4.42),
        _st("Gibraltar area", "", 36.14, -5.35),
        _st("Tangier", "", 35.76, -5.83),
        _st("Tetouan", "", 35.57, -5.37),
    ]
    name = name_cluster(stations)
    assert name.region_name is None
    assert name.continents == []


def test_partial_blank_country_blocks_tier1_and_continent():
    # Real France cities + one blank-country row: can't confirm purity → no zone,
    # and the unresolved row forces the continent to be omitted.
    stations = [dict(s) for s in FRANCE[:5]] + [_st("Mystery", "", 46.0, 2.0)]
    name = name_cluster(stations)
    assert name.region_name is None
    assert name.continents == []


def test_mixed_us_aliases_count_as_one_country():
    # "US" (cities.csv) and "United States" (GHCN) are the same country. A
    # non-zone US cluster split across both aliases must not read "2 countries".
    stations = [
        _st("Boston", "US", 42.36, -71.06),
        _st("New York", "United States", 40.71, -74.01),
        _st("Philadelphia", "US", 39.95, -75.17),
        _st("Portland ME", "United States", 43.66, -70.26),
        _st("Providence", "US", 41.82, -71.41),
        _st("Hartford", "United States", 41.76, -72.67),
    ]
    name = name_cluster(stations)
    assert name.country_count == 1
    assert name.countries == ["US"]
    assert name.continents == ["North America"]


def test_mixed_us_aliases_still_match_us_zone():
    variant = [
        dict(s, country=("United States" if i % 2 else "US"))
        for i, s in enumerate(DESERT_SW)
    ]
    assert name_cluster(variant).region_name == "Desert Southwest"


def test_usa_alias_collapses_with_us():
    # data/cities.csv carries "Furnace Creek,USA" (Death Valley — Desert SW). The
    # three CONUS spellings US / USA / United States must be one country, or a
    # real Desert Southwest cluster loses its zone name.
    stations = [
        _st("Phoenix", "US", 33.45, -112.07),
        _st("Las Vegas", "United States", 36.17, -115.14),
        _st("Furnace Creek", "USA", 36.46, -116.87),
        _st("Tucson", "US", 32.22, -110.93),
        _st("Palm Springs", "United States", 33.83, -116.55),
        _st("Yuma", "USA", 32.69, -114.62),
    ]
    name = name_cluster(stations)
    assert name.countries == ["US"]
    assert name.country_count == 1
    assert name.region_name == "Desert Southwest"


def test_containment_at_exact_080_boundary_names_zone():
    # 4 of 5 France cities inside the France zone footprint = 0.80 → named.
    stations = [
        _st("Paris", "France", 48.86, 2.35),
        _st("Lyon", "France", 45.75, 4.85),
        _st("Marseille", "France", 43.30, 5.37),
        _st("Bordeaux", "France", 44.84, -0.58),
        _st("FarFlung", "France", 10.0, 10.0),  # pure country, far from zone points
    ]
    assert name_cluster(stations).region_name == "France"


def test_us_territory_cluster_omits_continent():
    # is_us_location() matches "Guam [United States]" (substring), but Guam,
    # the Northern Marianas and American Samoa are in OCEANIA, not North
    # America. A geography namer must not inherit CONUS's continent for them.
    stations = [
        _st("Hagatna", "Guam [United States]", 13.47, 144.75),
        _st("Dededo", "Guam [United States]", 13.52, 144.84),
        _st("Saipan", "Northern Mariana Islands [United States]", 15.19, 145.72),
        _st("Tinian", "Northern Mariana Islands [United States]", 15.00, 145.63),
        _st("Pago Pago", "American Samoa [United States]", -14.28, -170.70),
        _st("Tafuna", "American Samoa [United States]", -14.33, -170.72),
    ]
    name = name_cluster(stations)
    assert name.region_name is None
    assert name.continents == []  # omit, never "North America"
    assert "Guam [United States]" in name.countries


def test_conus_and_territory_mix_omits_continent():
    stations = [dict(s) for s in DESERT_SW[:5]] + [
        _st("Hagatna", "Guam [United States]", 13.47, 144.75),
    ]
    assert name_cluster(stations).continents == []  # spans NA + ambiguous → omit


def test_containment_below_080_boundary_rejects_zone():
    # 3 of 5 inside = 0.60 < 0.80 → no zone name despite country purity.
    stations = [
        _st("Paris", "France", 48.86, 2.35),
        _st("Lyon", "France", 45.75, 4.85),
        _st("Marseille", "France", 43.30, 5.37),
        _st("Far1", "France", 10.0, 10.0),
        _st("Far2", "France", 12.0, 12.0),
    ]
    assert name_cluster(stations).region_name is None


# --------------------------------------------------------------------------- #
# clustering — coordinate + determinism hardening (codex PR-A P1s)
# --------------------------------------------------------------------------- #

def test_infinite_and_out_of_range_coords_excluded():
    bad = FRANCE + [
        {"city": "Inf", "country": "France", "lat": float("inf"), "lon": 2.0},
        {"city": "OverLat", "country": "France", "lat": 200.0, "lon": 2.0},
        {"city": "OverLon", "country": "France", "lat": 45.0, "lon": 999.0},
    ]
    clusters = cluster_record_stations(bad, link_km=350, min_size=6)  # must not raise
    assert len(clusters) == 1
    assert {"Inf", "OverLat", "OverLon"}.isdisjoint({s["city"] for s in clusters[0]})


def test_deterministic_with_duplicate_sort_keys():
    # Rows identical in (lat,lon,city,country) but different payload must not
    # flip order across equivalent inputs (stable sort preserves input order).
    base = [_st(f"C{i}", "France", 48 + i * 0.01, 2 + i * 0.01) for i in range(4)]
    d1 = {"city": "Dup", "country": "France", "lat": 48.5, "lon": 2.5, "payload": "a"}
    d2 = {"city": "Dup", "country": "France", "lat": 48.5, "lon": 2.5, "payload": "b"}
    out1 = cluster_record_stations(base + [d1, d2], link_km=350, min_size=6)[0]
    out2 = cluster_record_stations(base + [d2, d1], link_km=350, min_size=6)[0]
    seq1 = [s.get("payload") for s in out1 if s["city"] == "Dup"]
    seq2 = [s.get("payload") for s in out2 if s["city"] == "Dup"]
    assert seq1 == seq2


# --------------------------------------------------------------------------- #
# naming — tier 2 shape
# --------------------------------------------------------------------------- #

def test_lead_countries_capped_and_ordered_by_record_count():
    stations = (
        [_st(f"fr{i}", "France", 48.0 + i * 0.1, 2.0) for i in range(4)]
        + [_st(f"de{i}", "Germany", 50.0 + i * 0.1, 8.0) for i in range(3)]
        + [_st(f"es{i}", "Spain", 40.0 + i * 0.1, -3.0) for i in range(2)]
        + [_st("it0", "Italy", 41.9, 12.5)]
    )
    name = name_cluster(stations)
    # sorted by (-count, name): France(4), Germany(3), Spain(2), Italy(1)
    assert name.countries == ["France", "Germany", "Spain", "Italy"]
    assert name.lead_countries == ["France", "Germany", "Spain"]  # capped at 3
    assert name.country_count == 4


def test_cluster_name_is_a_frozen_dataclass():
    name = name_cluster(FRANCE)
    assert isinstance(name, ClusterName)


# --------------------------------------------------------------------------- #
# ZONE_COUNTRIES ↔ REGION_WATCHLIST contract
# --------------------------------------------------------------------------- #

def test_zone_countries_keys_match_region_watchlist_exactly():
    watchlist_names = {r.name for r in REGION_WATCHLIST}
    assert set(ZONE_COUNTRIES) == watchlist_names, (
        "ZONE_COUNTRIES must define allowed countries for exactly the "
        "REGION_WATCHLIST zones — drift breaks tier-1 naming honesty."
    )
