from __future__ import annotations

from src.data.air_quality import DustEvent, PM25HazardEvent
from src.two_bot.intern.air_quality import build_dust_event_bundle, build_pm25_hazard_bundle


def _pm25_event() -> PM25HazardEvent:
    return PM25HazardEvent(
        city="Lahore",
        country="Pakistan",
        lat=31.5,
        lon=74.3,
        date="2026-06-08",
        pm25_24h_mean=150.0,
        tier=1,
        who_multiple=10.0,
        us_aqi_daily_max=210,
        event_id="pm25_lahore_2026-06-08_tier1",
    )


def _dust_event(
    aod_daily_max: float | None = 0.65,
    *,
    dust_daily_max: float = 2000.0,
    pm10_24h_mean: float | None = None,
    who_pm10_multiple: float | None = None,
) -> DustEvent:
    return DustEvent(
        city="Khartoum",
        country="Sudan",
        lat=15.6,
        lon=32.5,
        date="2026-06-08",
        dust_daily_max=dust_daily_max,
        tier=2,
        aod_daily_max=aod_daily_max,
        event_id="dust_khartoum_2026-06-08_tier2",
        pm10_24h_mean=pm10_24h_mean,
        who_pm10_multiple=who_pm10_multiple,
    )


def _fact(bundle, label: str):
    return next(fact for fact in bundle.current_facts if fact["label"] == label)


def test_build_pm25_hazard_bundle_fields():
    bundle = build_pm25_hazard_bundle(_pm25_event())

    assert bundle.signal_kind == "air_quality_hazard"
    assert bundle.where == "Lahore, Pakistan"
    assert bundle.headline_metric["label"] == "pm25_24h_mean_ug_m3"
    assert bundle.headline_metric["value"] == 150.0


def test_build_pm25_hazard_bundle_evidence_grade():
    bundle = build_pm25_hazard_bundle(_pm25_event())

    assert _fact(bundle, "evidence_grade")["value"] == "model_estimated"


def test_build_pm25_hazard_bundle_station_grade_facts():
    event = _pm25_event()
    event = PM25HazardEvent(
        **{
            **event.__dict__,
            "evidence_grade": "model_corroborated_by_station",
            "station_name": "Lahore Jail Road",
            "station_pm25_ug_m3": 172.0,
            "station_distance_km": 4.2,
        }
    )
    bundle = build_pm25_hazard_bundle(event)

    assert _fact(bundle, "evidence_grade")["value"] == "model_corroborated_by_station"
    assert _fact(bundle, "station_name")["value"] == "Lahore Jail Road"
    assert _fact(bundle, "station_pm25_ug_m3")["value"] == 172.0
    assert _fact(bundle, "station_distance_km")["value"] == 4.2


def test_build_pm25_hazard_bundle_who_guideline():
    bundle = build_pm25_hazard_bundle(_pm25_event())

    assert _fact(bundle, "who_24h_guideline_ug_m3")["value"] == 15
    assert _fact(bundle, "who_multiple")["value"] == 10.0


def test_build_dust_event_bundle_fields():
    bundle = build_dust_event_bundle(_dust_event())

    assert bundle.signal_kind == "dust_event"
    assert bundle.where == "Khartoum, Sudan"
    assert bundle.headline_metric["label"] == "dust_daily_max_ug_m3"
    assert bundle.headline_metric["value"] == 2000


def test_build_dust_event_bundle_aod_none():
    bundle = build_dust_event_bundle(_dust_event(aod_daily_max=None))

    assert _fact(bundle, "aerosol_optical_depth")["value"] is None


def test_build_dust_event_bundle_carries_who_pm10_anchor():
    event = _dust_event(dust_daily_max=2400.0, pm10_24h_mean=900.0,
                        who_pm10_multiple=20.0)
    bundle = build_dust_event_bundle(event)
    facts = {f["label"]: f.get("value") for f in bundle.current_facts}
    assert facts["pm10_24h_mean_ug_m3"] == 900.0
    assert facts["who_pm10_multiple"] == 20.0
    assert facts["who_pm10_24h_guideline_ug_m3"] == 45


def test_build_dust_event_bundle_omits_anchor_when_absent():
    event = _dust_event(dust_daily_max=2400.0, pm10_24h_mean=None,
                        who_pm10_multiple=None)
    bundle = build_dust_event_bundle(event)
    labels = [f["label"] for f in bundle.current_facts]
    assert "pm10_24h_mean_ug_m3" not in labels
    assert "who_pm10_multiple" not in labels
