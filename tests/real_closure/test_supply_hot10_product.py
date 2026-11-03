"""Hot10 consumers of the selected normals product: ranking, bulletin, claims, native graphic and preview.

``THEHEAT_HOT10_NORMALS_PRODUCT`` unset keeps the Meteostat path exactly; the exact
value ``noaa-ghcnd-monthly-mean-tmax-v1`` ranks only against that product's own
installed file, every row and the bulletin name the product, the image and both
descriptions say "mean daily maximum, 1991-2020" with NOAA GHCN-Daily attribution,
and nothing is ever mixed, relabelled or called the world's hottest places.
Forecasts and normals are invented; the real loaders, qualifier, bundle builder,
claim floor, adapter, renderer and preview projection run unmodified.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest

from src.data import ghcnd_monthly_normals as gn, hot10_baselines, open_meteo, places
from src.dashboard_preview import preview
from src.editorial import hot10_contract as contract
from src.media import gist_hazard_media as media, hot10_graphic_adapter as adapter
from src.two_bot import hot10_claims
from src.two_bot.intern import build_hot10_bundle
from tests import gist_hazard_helpers as gh, live_content_harness as h
from tests.real_closure import supply_ghcnd_fixture as gf

NOW = gh.HOT10_CAPTURE


def _ghcnd_normals(tmp_path: Path, cities=h.CITIES, **overrides) -> dict:
    path = gf.write_rows(tmp_path / gn.INSTALLED_NAME, gf.installed_rows(NOW.month, cities, **overrides))
    return gn.load_normals(path)


def _ghcnd_story(tmp_path: Path, cities=h.CITIES):
    result = contract.qualify(h.city_temps(NOW, cities), _ghcnd_normals(tmp_path, cities), sampled=len(cities),
                              now=NOW, product=contract.GHCND_PRODUCT)
    assert result["complete"], result["universe"]
    return build_hot10_bundle(result["rows"], changes=[], event_id=f"hot10_{NOW.date().isoformat()}",
                              universe=result["universe"])


def _ghcnd_bundle(tmp_path: Path, cities=h.CITIES) -> dict:
    return _ghcnd_story(tmp_path, cities).to_dict()


def _refingerprint(bundle: dict) -> dict:
    for row in bundle["raw_signal_dump"]["cities"]:
        row["row_fingerprint"] = contract.row_fingerprint(row)
    return bundle


# ---------------------------------------------------------------------------
# the flag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [(None, "meteostat-normals-point-v1"), ("", "meteostat-normals-point-v1"),
                                            ("meteostat-normals-point-v1", "meteostat-normals-point-v1"),
                                            ("noaa-ghcnd-monthly-mean-tmax-v1", "noaa-ghcnd-monthly-mean-tmax-v1")])
def test_flag_selects_exactly_one_product(value, expected):
    environ = {} if value is None else {hot10_baselines.FLAG: value}
    assert hot10_baselines.selected_product(environ) == expected == hot10_baselines.inventory_value(environ)


@pytest.mark.parametrize("value", ["1", "ghcnd", "NOAA-GHCND-MONTHLY-MEAN-TMAX-V1", " meteostat-normals-point-v1",
                                   "noaa-ghcnd-monthly-mean-tmax-v1,meteostat-normals-point-v1"])
def test_any_other_flag_value_is_refused_not_defaulted(value):
    with pytest.raises(hot10_baselines.UnknownNormalsProduct):
        hot10_baselines.selected_product({hot10_baselines.FLAG: value})
    assert hot10_baselines.inventory_value({hot10_baselines.FLAG: value}) == "invalid"


# ---------------------------------------------------------------------------
# ranking and bulletin
# ---------------------------------------------------------------------------

def test_legacy_default_bulletin_keeps_its_product_wording_and_shape():
    bundle = gh.hot10_bundle()
    raw = bundle["raw_signal_dump"]
    assert raw["evidence"]["baseline_product"] == "meteostat-normals-point-v1"
    assert raw["universe"]["ranked_by"] == contract.RANKED_BY and "GHCN" not in str(bundle)
    assert set(raw["cities"][0]["baseline"]) == {"source_product", "period_start", "period_end", "retrieved_at",
                                                 "sampling_point_id", "month", "revision_id"}
    spec = adapter.hot10_graphic_spec(bundle, expected_bundle_sha256=media.fingerprint(bundle), synthetic=True)
    assert spec["evidence"]["source_label"] == adapter.SOURCE_LABEL and "baseline_wording" not in spec["evidence"]
    assert set(preview.hot10_source_context(spec["evidence"])) == {"kind", "local_days", "qualified_cities",
                                                                   "sampled_cities", "rows"}
    prepared = media.prepare_media(bundle, synthetic=True)
    assert "Open-Meteo forecasts, Meteostat normals; " in prepared["delivery_text"]
    assert "Normals: meteostat-normals-point-v1." in prepared["full_text"]


def test_ghcnd_ranking_names_its_product_station_and_sampled_universe(tmp_path):
    bundle = _ghcnd_bundle(tmp_path)
    raw = bundle["raw_signal_dump"]
    assert contract.validate_bundle(bundle) == []
    assert raw["evidence"]["baseline_product"] == contract.GHCND_PRODUCT
    assert raw["universe"]["ranked_by"] == contract.GHCND_RANKED_BY
    assert "not a record maximum" in raw["universe"]["baseline_scope"]
    assert raw["universe"]["scope"] == contract.UNIVERSE_SCOPE  # sampled cities, not the world's hottest places
    assert (raw["universe"]["qualified_cities"], raw["universe"]["sampled_cities"]) == (13, 14)
    for row in raw["cities"]:
        assert row["baseline"]["source_product"] == contract.GHCND_PRODUCT
        assert row["baseline"]["statistic"] == "mean_daily_maximum"
        assert (row["baseline"]["period_start"], row["baseline"]["period_end"]) == (1991, 2020)
        assert row["baseline"]["station_id"].startswith("XQW") and row["baseline"]["distance_km"] == 5.56
    facts = {fact["label"]: fact["value"] for fact in bundle["current_facts"]}
    assert facts["baseline_product"] == contract.GHCND_PRODUCT
    assert "not a monthly record maximum" in facts["baseline_statistic"]
    assert "not a record maximum" in facts["claim_limit"] and facts["ranking"][0]["normal_years"] == 30


def test_selected_ghcnd_never_ranks_a_meteostat_normal(tmp_path):
    legacy = tmp_path / "legacy.csv"
    h.write_normals(legacy, h.normal_rows(NOW.month))
    result = contract.qualify(h.city_temps(NOW), open_meteo.load_normals(str(legacy)), sampled=14, now=NOW,
                              product=contract.GHCND_PRODUCT)
    assert result["rows"] == [] and not result["complete"]
    assert result["universe"]["excluded"] == {"ambiguous_normal": 1, "missing_normal": 1, "unqualified_normal": 12}
    # ... and the default product never ranks a GHCND normal either.
    reverse = contract.qualify(h.city_temps(NOW), _ghcnd_normals(tmp_path), sampled=14, now=NOW)
    assert reverse["rows"] == [] and reverse["universe"]["excluded"]["unqualified_normal"] == 13


def test_fewer_than_ten_qualified_ghcnd_places_hold_the_bulletin(tmp_path):
    nine = h.CITIES[:9]
    result = contract.qualify(h.city_temps(NOW, nine), _ghcnd_normals(tmp_path, nine), sampled=9, now=NOW,
                              product=contract.GHCND_PRODUCT)
    assert len(result["rows"]) == 9 and result["complete"] is False


@pytest.mark.parametrize("override", [{"statistic": "monthly_record_maximum"}, {"period_start": "1981",
                                                                              "period_end": "2010"},
                                      {"years_used": "23"}, {"distance_km": "35.5"}])
def test_a_record_period_or_coverage_drift_is_not_a_qualified_normal(tmp_path, override):
    rows = gf.installed_rows(NOW.month)
    for row in rows:
        row.update(override)
    normals: dict = {}
    for row in rows:  # bypass the loader's own refusal to prove the contract's
        identity = {"sampling_point_id": row["sampling_point_id"]}
        key = places.event_location_key(row["city"], row["country"], row["lat"], row["lon"], place_id=row["place_id"])
        meta = gn.provenance(row, identity)
        meta.update({k: v if k == "statistic" else int(v) for k, v in override.items()
                     if k in ("statistic", "period_start", "period_end")})
        normals.setdefault(key, {"_meta": {}})
        normals[key][NOW.month], normals[key]["_meta"][NOW.month] = float(row["mean_tmax_c"]), meta
    result = contract.qualify(h.city_temps(NOW), normals, sampled=14, now=NOW, product=contract.GHCND_PRODUCT)
    assert result["rows"] == [] and result["universe"]["excluded"].get("unqualified_normal") == 13


def test_mixed_products_and_swapped_wording_are_refused(tmp_path):
    bundle = _ghcnd_bundle(tmp_path)
    mixed = deepcopy(bundle)
    mixed["raw_signal_dump"]["cities"][4]["baseline"] = {
        **{k: v for k, v in mixed["raw_signal_dump"]["cities"][4]["baseline"].items()
           if k in ("period_start", "period_end", "retrieved_at", "sampling_point_id", "month", "revision_id")},
        "source_product": contract.BASELINE_PRODUCT}
    failures = contract.validate_bundle(_refingerprint(mixed))
    assert "baseline_mixed" in failures and "row_unqualified" in failures
    relabelled = deepcopy(bundle)
    relabelled["raw_signal_dump"]["evidence"]["baseline_product"] = contract.BASELINE_PRODUCT
    assert "baseline_mixed" in contract.validate_bundle(relabelled)
    reworded = deepcopy(bundle)
    reworded["raw_signal_dump"]["universe"]["ranked_by"] = contract.RANKED_BY
    assert "universe" in contract.validate_bundle(reworded)
    rows = deepcopy(bundle["raw_signal_dump"]["cities"])
    rows[3]["baseline"]["source_product"] = contract.BASELINE_PRODUCT
    with pytest.raises(ValueError, match="hot10_baseline_product_mixed"):
        build_hot10_bundle(rows, changes=[], event_id="hot10_x", universe=bundle["raw_signal_dump"]["universe"])


@pytest.mark.parametrize("copy,expected", [
    ("Riyadh tops the world's hottest forecast list among 14 sampled cities.", "not absolute heat"),
    ("A record forecast high in Riyadh, top of 14 sampled cities.", "not a record"),
])
def test_claim_floor_keeps_sampled_and_not_record_limits_for_the_ghcnd_bulletin(tmp_path, copy, expected):
    bundle = _ghcnd_story(tmp_path)
    assert any(expected in failure for failure in hot10_claims.claim_failures(copy, bundle))
    fine = "Forecast highs: Riyadh is 9.2C above its normal, top of 14 sampled cities."
    assert hot10_claims.claim_failures(fine, bundle) == []


# ---------------------------------------------------------------------------
# native graphic, descriptions and the dashboard preview projection
# ---------------------------------------------------------------------------

def test_ghcnd_graphic_and_descriptions_carry_attribution_and_mean_daily_maximum_wording(tmp_path):
    bundle = _ghcnd_bundle(tmp_path)
    spec = adapter.hot10_graphic_spec(bundle, expected_bundle_sha256=media.fingerprint(bundle), synthetic=False)
    evidence = spec["evidence"]
    assert evidence["source_label"] == adapter.SOURCE_LABELS[contract.GHCND_PRODUCT]
    assert evidence["baseline_wording"] == "mean daily maximum, 1991-2020"
    assert evidence["rows"][0]["normal_station"]["station_id"].startswith("XQW")
    prepared = media.prepare_media(bundle, synthetic=True)
    delivery, full = prepared["delivery_text"], prepared["full_text"]
    assert "mean daily maximum, 1991-2020" in delivery and "NOAA GHCN-Daily" in delivery
    assert "13 qualified of 14 sampled cities" in delivery and "world's hottest places" in delivery
    assert "Meteostat" not in delivery + full and "not a record" in delivery
    assert "not a record maximum" in full and "station XQW" in full and "30 years" in full
    assert prepared["png"].startswith(b"\x89PNG") and prepared["descriptor"]["source"]["baseline_product"] \
        == contract.GHCND_PRODUCT
    context = preview.hot10_source_context(evidence)
    assert context["baseline_product"] == contract.GHCND_PRODUCT
    assert context["baseline_wording"] == "mean daily maximum, 1991-2020"
    assert adapter.source_label(contract.GHCND_PRODUCT).startswith("Open-Meteo forecast · NOAA GHCN-Daily")
    with pytest.raises(adapter.Hot10GraphicRefused):
        adapter.source_label("meteostat-normals-point-v2")


def test_the_ghcnd_image_is_a_different_text_projection_of_the_same_template(tmp_path):
    legacy = media.prepare_media(gh.hot10_bundle(), synthetic=True)
    ghcnd = media.prepare_media(_ghcnd_bundle(tmp_path), synthetic=True)
    assert legacy["descriptor"]["template"] == ghcnd["descriptor"]["template"] == adapter.TEMPLATE
    assert legacy["descriptor"]["template_version"] == ghcnd["descriptor"]["template_version"]
    assert legacy["png"] != ghcnd["png"]


# ---------------------------------------------------------------------------
# the real Hot10 run
# ---------------------------------------------------------------------------

@pytest.fixture
def leaderboard(monkeypatch):
    from src.orchestrator import hot10 as orchestrator
    from src.state import DEFAULT_STATE

    calls: dict = {"enqueued": [], "legacy_normals": 0, "fetched": 0}
    cities = h.catalogue_rows([name for name, _zone, _kind in h.CITIES])

    def legacy_normals(*_a, **_k):
        calls["legacy_normals"] += 1
        return {}

    def fetch(_cities):
        calls["fetched"] += 1
        return h.city_temps(NOW)

    monkeypatch.setattr(open_meteo, "load_cities", lambda *a, **k: cities)
    monkeypatch.setattr(open_meteo, "load_normals", legacy_normals)
    monkeypatch.setattr(open_meteo, "fetch_all_city_temps", fetch)
    monkeypatch.setattr(orchestrator, "_utc_now", lambda: NOW + timedelta(minutes=5))
    monkeypatch.setattr(orchestrator, "_enqueue_story_candidate", lambda state, **kw: calls["enqueued"].append(kw))
    monkeypatch.setattr(orchestrator, "_drain_and_write_triage_queue", lambda *a, **k: None)

    def run():
        state = deepcopy(DEFAULT_STATE)
        current: dict = {"sources": []}
        orchestrator.run_leaderboard(state, current)
        return state, current
    return calls, run


def test_run_with_the_ghcnd_flag_ranks_only_that_file_and_reviews_it_as_such(tmp_path, monkeypatch, leaderboard):
    calls, run = leaderboard
    installed = gf.write_rows(tmp_path / gn.INSTALLED_NAME, gf.installed_rows(NOW.month))
    monkeypatch.setattr(gn, "DEFAULT_INSTALLED", installed)
    monkeypatch.setenv(hot10_baselines.FLAG, gn.PRODUCT)
    _state, current = run()
    assert calls["legacy_normals"] == 0 and len(calls["enqueued"]) == 1
    queued = calls["enqueued"][0]
    assert queued["bundle"].raw_signal_dump["evidence"]["baseline_product"] == gn.PRODUCT
    review = queued["review_context"]
    assert review["source"] == "Open-Meteo forecast + NOAA GHCN-Daily station mean daily maximum, 1991-2020"
    labels = {fact["label"]: fact["value"] for fact in review["facts"]}
    assert labels["Baseline product"] == gn.PRODUCT and labels["Qualified universe"] == "13 of 14 sampled"


def test_run_with_the_ghcnd_flag_and_no_installed_file_holds_without_fallback(tmp_path, monkeypatch, leaderboard):
    calls, run = leaderboard
    monkeypatch.setattr(gn, "DEFAULT_INSTALLED", tmp_path / "absent" / gn.INSTALLED_NAME)
    monkeypatch.setenv(hot10_baselines.FLAG, gn.PRODUCT)
    _state, current = run()
    assert calls["legacy_normals"] == 0 and calls["enqueued"] == []
    note = next(s for s in current["sources"] if s["source"] == "leaderboard")["note"]
    assert note.startswith("hot10_short_slate: 0 of 10") and f"baseline {gn.PRODUCT} file absent" in note


def test_run_default_still_reads_the_meteostat_loader_only(monkeypatch, leaderboard):
    calls, run = leaderboard
    monkeypatch.delenv(hot10_baselines.FLAG, raising=False)
    monkeypatch.setattr(gn, "load_normals", lambda *a, **k: pytest.fail("GHCND file read on the default path"))
    run()
    assert calls["legacy_normals"] == 1


def test_run_with_an_unknown_flag_value_refuses_before_any_forecast_fetch(monkeypatch, leaderboard):
    calls, run = leaderboard
    monkeypatch.setenv(hot10_baselines.FLAG, "ghcnd")
    state, current = run()
    assert calls["fetched"] == 0 and calls["legacy_normals"] == 0 and calls["enqueued"] == []
    source = next(s for s in current["sources"] if s["source"] == "leaderboard")
    assert source["status"] == "failed" and "hot10_normals_product_unknown" in source["error"]
