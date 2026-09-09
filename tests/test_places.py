"""Scientific identity regressions from the September 8 reproduced collisions."""

from copy import deepcopy
import csv
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data import places, open_meteo, air_quality
from src.data.place_migration import migrate_cache
from src.data.world_thresholds import compute_city_thresholds, evaluate_city, CityThresholds
from src.orchestrator import world_cache
from src.orchestrator.sources import open_meteo as runner
from src.orchestrator.sources.air_quality import _should_emit_tier, _set_city_tier
from src.orchestrator.draft_save import can_draft_candidate, save_draft
from src.editorial.scoring import EditorialScore
from src.two_bot.intern.temperature import build_all_time_record_bundle
from src.two_bot.memory import _event_base


def pair(name):
    with (places.DATA / "cities.csv").open() as handle:
        return [r for r in csv.DictReader(handle) if r["city"] == name]


def threshold(row, high=40):
    return compute_city_thresholds(
        row["city"],
        {"time": ["2000-09-08"], "temperature_2m_max": [high], "temperature_2m_min": [10]},
        as_of=date.today().isoformat(),
        country=row["country"],
        lat=row["lat"],
        lon=row["lon"],
    )


@pytest.mark.parametrize("name", ["Barcelona", "Hyderabad", "Valencia"])
def test_real_pair_end_to_end_without_network(name, monkeypatch):
    """Both real rows retain their own response, comparator, event and editorial gate."""
    rows = pair(name)
    cache = {
        places.cache_key(r["city"], r["country"], r["lat"], r["lon"]): threshold(
            r, 40 + i * 10
        ).to_dict()
        for i, r in enumerate(rows)
    }
    payload = [
        {
            "daily": {
                "temperature_2m_max": [45 + i * 10],
                "temperature_2m_min": [20],
                "wet_bulb_temperature_2m_max": [10],
            }
        }
        for i in range(2)
    ]
    monkeypatch.setattr(
        open_meteo, "fetch_with_retry", lambda *a, **k: SimpleNamespace(json=lambda: payload)
    )
    monkeypatch.setattr(world_cache, "read_cache", lambda: deepcopy(cache))
    saved = {}
    monkeypatch.setattr(world_cache, "write_cache", lambda value: saved.update(value) or True)
    monkeypatch.setattr(
        runner,
        "_fetch_city_archive",
        lambda *a: pytest.fail("fresh attributed cache must not warm"),
    )
    bundles, _ = runner._run_world_cached_half(rows, {})
    records = [b.all_time_high for b in bundles]
    assert len(records) == 2
    assert [r.new_temp_c for r in records] == [45, 55]
    assert [r.old_record_c for r in records] == [40, 50]
    assert len({r.event_id for r in records}) == 2
    assert len({_event_base(r.event_id) for r in records}) == 2
    state = {"drafts": [], "posted_events": []}
    for record in records:
        bundle = build_all_time_record_bundle(record)
        assert places.event_identity(record.event_id).items() <= bundle.raw_signal_dump.items()
        candidate = SimpleNamespace(
            event_id=record.event_id,
            city=record.city,
            tweet_date="2026-09-08",
            score=SimpleNamespace(total=80),
            cooldown_exempt=False,
        )
        assert can_draft_candidate(state, candidate)[0]
        assert save_draft(
            "A reviewable draft.",
            state,
            "all_time_high",
            record.event_id,
            city=record.city,
            tweet_date="2026-09-08",
            review_context={"two_bot": {"bundle": bundle.to_dict()}},
        )
    assert len(state["drafts"]) == 2
    state["drafts"][0]["status"] = "posted"
    state["posted_events"].append(records[0].event_id)
    assert not can_draft_candidate(state, SimpleNamespace(event_id=records[0].event_id))[0]
    # A fresh-date second-place candidate is not blocked by the first-place city cooldown.
    assert can_draft_candidate(
        state,
        SimpleNamespace(
            event_id=records[1].event_id.replace("2026-", "2027-"),
            city=name,
            tweet_date="2027-09-08",
        ),
    )[0]
    assert len([k for k in saved if k != "_meta"]) == 2


@pytest.mark.parametrize("name", ["Barcelona", "Hyderabad"])
def test_direct_detectors_use_same_identity_contract(name, monkeypatch):
    rows = pair(name)
    forecasts = {"daily": {"temperature_2m_max": [50], "temperature_2m_min": [10]}}
    archive = {
        "daily": {"time": ["2000-09-08"], "temperature_2m_max": [30], "temperature_2m_min": [20]}
    }
    monkeypatch.setattr(
        open_meteo,
        "fetch_with_retry",
        lambda url, **k: SimpleNamespace(json=lambda: archive if "archive" in url else forecasts),
    )
    bundles = [
        open_meteo.detect_extreme_signals(float(r["lat"]), float(r["lon"]), r["city"], r["country"])
        for r in rows
    ]
    assert all(b.all_time_high for b in bundles)
    assert len({b.all_time_high.event_id for b in bundles}) == 2
    assert all(
        places.event_identity(b.absolute_extreme.event_id) for b in bundles if b.absolute_extreme
    )


@pytest.mark.parametrize("name", ["Amsterdam", "Brazzaville", "Dubai", "Hong Kong", "Kinshasa"])
def test_aliases_share_place_but_not_unproven_baselines(name, tmp_path):
    raw = pair(name)
    identities = [places.place_for_row(r) for r in raw]
    assert len({p["place_id"] for p in identities}) == 1
    path = tmp_path / "cities.csv"
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0]))
        writer.writeheader()
        writer.writerows(list(reversed(raw)))
    loaded = places.load_cities(str(path))
    assert len(loaded) == 1
    registered = next(r for r in places.registry() if r["place_id"] == identities[0]["place_id"])
    assert (loaded[0]["lat"], loaded[0]["lon"]) == (registered["lat"], registered["lon"])
    if name != "Brazzaville":
        assert identities[0]["sampling_point_id"] != identities[1]["sampling_point_id"]


def test_whole_inventory_and_canonical_country_aliases():
    assert len(places.load_cities()) == 633
    assert len({p["place_id"] for p in places.load_cities()}) == 633
    assert places.country_key("Netherlands") == places.country_key("The Netherlands") == "NL"
    assert places.country_key("UAE") == places.country_key("United Arab Emirates") == "AE"
    assert places.country_key("DR Congo") != places.country_key("Congo")


def test_same_name_same_country_different_points_and_coordinate_revision():
    a = places.resolve_place("Springfield", "US", 40, -100)
    b = places.resolve_place("Springfield", "US", 41, -100)
    assert a["place_id"] != b["place_id"]
    old = places.resolve_place("Barcelona", "Spain")
    revised = places.resolve_place("Barcelona", "Spain", 41.4, 2.17, place_id=old["place_id"])
    assert old["place_id"] == revised["place_id"]
    assert old["sampling_point_id"] != revised["sampling_point_id"]
    row = pair("Barcelona")[0]
    with pytest.raises(ValueError, match="sampling provenance"):
        evaluate_city(
            "Barcelona",
            "Spain",
            {"max_c": 60},
            threshold(row),
            lat=41.4,
            lon=2.17,
            today=date.today(),
        )


@pytest.mark.parametrize("lat,lon", [(float("nan"), 0), (0, float("inf")), (91, 0), (0, -181)])
def test_invalid_coordinates_fail(lat, lon):
    with pytest.raises(ValueError):
        places.resolve_place("Bad", "US", lat, lon)


def test_cache_quarantine_idempotence_merge_and_coverage():
    row = pair("Barcelona")[0]
    key = places.cache_key(row["city"], row["country"], row["lat"], row["lon"])
    original = {
        "Barcelona": {"city": "Barcelona", "all_time_max": [80, 2026]},
        "Barcelona|Spain": {"city": "Barcelona", "as_of": "2026-09-08"},
        key: threshold(row).to_dict(),
    }
    preserved = deepcopy(original)
    once = migrate_cache(original)
    assert original == preserved
    assert once == migrate_cache(once)
    assert once["_meta"]["cached_count"] == 1
    assert once["_meta"]["quarantined_count"] == 2
    merged = world_cache.merge_caches(once, original)
    assert set(merged) == {key, "_meta"}
    assert merged["_meta"]["quarantined_count"] == 2
    bad = deepcopy(once[key])
    bad["identity"]["lon"] = 60
    assert list(migrate_cache({key: bad})) == ["_meta"]
    with pytest.raises(ValueError, match="sampling provenance"):
        evaluate_city(
            "Barcelona",
            "Spain",
            {"max_c": 60},
            CityThresholds(city="Barcelona", as_of="2026-09-08", years_of_data=30),
            lat=41.39,
            lon=2.16,
            today=date.today(),
        )


@pytest.mark.parametrize("name", ["Barcelona", "Hyderabad"])
def test_air_quality_tier_and_normals_stay_independent(name):
    rows = pair(name)
    state = {}
    events = []
    temps = []
    normals = {}
    for i, row in enumerate(rows):
        obs = air_quality.CityAirQuality(
            row["city"],
            row["country"],
            float(row["lat"]),
            float(row["lon"]),
            "2026-09-08",
            250,
            None,
            None,
            200,
            None,
        )
        events.append(air_quality.detect_pm25_hazard(obs))
        key = places.event_location_key(row["city"], row["country"], row["lat"], row["lon"])
        temps.append(
            open_meteo.CityTemp(
                row["city"], row["country"], float(row["lat"]), float(row["lon"]), 40 + i * 10
            )
        )
        normals[key] = {date.today().month: 30 + i * 10}
    first = events[0]
    key = places.event_location_key(first.city, first.country, first.lat, first.lon)
    _set_city_tier(state, "air_quality_pm25_tiers", key, first.tier, first.date)
    second = events[1]
    assert _should_emit_tier(
        state,
        tier_key="air_quality_pm25_tiers",
        city_slug=places.event_location_key(second.city, second.country, second.lat, second.lon),
        tier=second.tier,
        event_date=second.date,
        event_id=second.event_id,
    )
    result = open_meteo.compute_anomalies(temps, normals)
    assert [r.anomaly_c for r in result] == [10, 10]
    assert open_meteo.compute_anomalies(temps, {name: {date.today().month: 0}}) == []


def test_legacy_published_receipts_immutable_and_attribution_specific(monkeypatch):
    rows = pair("Barcelona")
    events = []
    for r in rows:
        events.append(
            evaluate_city(
                r["city"],
                r["country"],
                {"max_c": 60},
                threshold(r),
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                today=date(2026, 9, 8),
            ).all_time_high
        )
    old = "alltime_high_Barcelona_2026-09-08"
    state = {
        "posted_events": [old],
        "publish_ledger": {old: {"tweet_id": "receipt", "phase": "confirmed"}},
        "drafts": [
            {
                "status": "posted",
                "event_id": old,
                "text": "Original published wording",
                "tweet_id": "receipt",
                "review_context": {"two_bot": {"bundle": {"raw_signal_dump": rows[0]}}},
            }
        ],
    }
    original = deepcopy(state)
    assert places.legacy_publication_status(state, events[0].event_id) == "duplicate"
    assert places.legacy_publication_status(state, events[1].event_id) == "clear"
    assert state == original
    state["drafts"] = []
    assert places.legacy_publication_status(state, events[0].event_id) == "ambiguous"
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
    assert save_draft("Review this claim.", state, "all_time_high", events[0].event_id)
    assert state["drafts"][0]["approval_mode"] == "manual"
    assert state["drafts"][0]["forced_manual"] == "ambiguous_legacy_place"
    assert state["publish_ledger"] == original["publish_ledger"]


def test_automatic_legacy_identity_gate_does_not_modify_evidence():
    draft = {
        "event_id": "monthly_high_Barcelona_2026_09",
        "text": "Original",
        "last_publish_attempt_at": "uncertain",
    }
    saved = deepcopy(draft)
    assert places.requires_identity_review(draft)
    assert draft == saved
    assert not places.requires_identity_review(
        {"event_id": "monthly_high_USW00023183_09_2026-09-08"}
    )
    assert not places.requires_identity_review(
        {
            "event_id": "alltime_high_"
            + places.event_location_key("Barcelona", "Spain")
            + "_2026-09-08"
        }
    )


def test_short_forecast_batch_cannot_shift_values_to_other_city(monkeypatch):
    rows = pair("Barcelona")
    monkeypatch.setattr(
        open_meteo,
        "fetch_with_retry",
        lambda *a, **k: SimpleNamespace(json=lambda: [{"daily": {"temperature_2m_max": [50]}}]),
    )
    assert open_meteo.fetch_forecasts_batch(rows) == {}


def test_country_coverage_does_not_double_count_aliases():
    readings = [
        open_meteo.ExtremeSignalBundle(
            city="Amsterdam",
            country=country,
            today_max_c=45,
            archive_max_c=40,
            archive_max_year=2000,
        )
        for country in ["Netherlands", "The Netherlands"]
    ]
    assert open_meteo.detect_country_records(readings) == []


def test_explicit_identity_rejects_conflicting_country():
    place = places.resolve_place("Barcelona", "Spain")
    with pytest.raises(ValueError, match="conflicts"):
        places.resolve_place("Barcelona", "Venezuela", 41.39, 2.16, place_id=place["place_id"])


def test_normals_loader_excludes_legacy_and_validates_point(tmp_path):
    row = places.resolve_place("Barcelona", "Spain")
    path = tmp_path / "normals.csv"
    fields = [
        "city",
        "country",
        "place_id",
        "sampling_point_id",
        "lat",
        "lon",
        "month",
        "avg_high_c",
    ]
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"city": "Barcelona", "month": 9, "avg_high_c": 99})
        writer.writerow(
            {**{k: v for k, v in row.items() if k in fields}, "month": 9, "avg_high_c": 25}
        )
    normals = open_meteo.load_normals(str(path))
    assert normals == {places.event_location_key("Barcelona", "Spain"): {9: 25}}


def test_precip_history_separates_satellite_and_model_samples():
    from dataclasses import replace
    from src.data.gpm_imerg import CityPrecipReading, _city_key

    row = CityPrecipReading("Barcelona", "Spain", 41.39, 2.16, "2026-09-08", 55, "late", "event")
    assert _city_key(row) != _city_key(replace(row, source_product="open_meteo"))


def test_changed_place_evidence_invalidates_p02_review():
    from src.editorial.revisions import (
        record_human_review,
        authorize_draft,
        review_is_current,
        approval_is_current,
    )

    a, b = pair("Barcelona")
    draft = {
        "text": "Review this claim.",
        "event_id": "example",
        "review_context": {"two_bot": {"bundle": {"raw_signal_dump": a}}},
    }
    record_human_review(draft)
    authorize_draft(draft, "manual")
    assert approval_is_current(draft, "manual")
    draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"] = b
    assert not review_is_current(draft)
    assert not approval_is_current(draft, "manual")


def test_unicode_alias_normalization_preserves_registry_identity():
    import unicodedata

    canonical = places.resolve_place("Abū Ghurayb", "Iraq")
    decomposed = unicodedata.normalize("NFD", "Abū Ghurayb").upper()
    assert places.resolve_place(decomposed, "IQ")["place_id"] == canonical["place_id"]
