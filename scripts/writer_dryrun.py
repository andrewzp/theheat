#!/usr/bin/env python
"""Offline dry-run harness for writer voice work, one signal type at a time.

E1 (plan row 8) generalizes the reganom-dryrun pattern to a ``--type`` switch
with per-type fixtures — fires first, the richest test of A1's sourced-impact
path. Each type builds the REAL production bundle (via the same intern the
live pipeline uses) and runs candidates through the SAME gate chain —
evidence contract -> writer (IMPACT_GUIDANCE rider when impact rides) ->
safety -> §F -> fact-check -> critic — printing every stage plus the
decision-4 routing verdict, so a fire-section prompt change is proven to
"land harder while passing fact-check + critic" before it ships.

Types:

- ``fire`` — a FIRMS-style hotspot (Colorado-class defaults: 595 MW,
  very_high tier). Default attaches the A1 Colorado-class ``human_impact``
  fixture (NIFC personnel + verified fatalities); ``--no-impact`` for the
  control run.
- ``fire_footprint`` — a NAMED NIFC-style complex crossing an acreage tier
  (Sierra Complex, 103,400 ha -> tier 2 / 100,000 ha crossed). Impact
  entries name THE complex (matcher-consistency); ``--no-impact`` to drop.

The reganom voice keeps its own harness (scripts/reganom_writer_dryrun.py);
scripts/news_enrich_writer_dryrun.py remains THE pre-flip gate for
``THEHEAT_NEWS_ENRICH_ENABLED`` and is deliberately untouched by this tool.

The writer is stochastic, so ``--samples N`` drafts N candidates. The writer
needs ``ANTHROPIC_API_KEY``; fact-check + critic need ``GEMINI_API_KEY``.
With no keys the harness prints what it WOULD run and exits 2 — it never
silently no-ops.

Usage::

    ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
      .venv/bin/python scripts/writer_dryrun.py --type fire --samples 3

    # named-complex tier crossing, no impact attached:
    .venv/bin/python scripts/writer_dryrun.py --type fire_footprint --no-impact
"""

from __future__ import annotations

import argparse
import os
import sys
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

# Allow `python scripts/writer_dryrun.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.air_quality import DUST_TIERS, DustEvent, _tier  # noqa: E402
from src.data.cyclones import LandThreatEvent  # noqa: E402
from src.data.fire_footprint import FireComplex, _classify_tier  # noqa: E402
from src.data.firms import FireEvent  # noqa: E402
from src.data.gpm_imerg import PrecipExtremeEvent  # noqa: E402
from src.editorial.newsworthiness import detect_impact_citation  # noqa: E402
from src.state import DEFAULT_STATE  # noqa: E402
from src.two_bot import critic, fact_check, memory, writer  # noqa: E402
from src.two_bot.evidence_contract import audit_story_bundle  # noqa: E402
from src.two_bot.intern import build_cyclone_land_threat_bundle, build_dust_event_bundle, build_fire_bundle, build_fire_footprint_bundle, build_precipitation_bundle  # noqa: E402
from src.two_bot.pipeline import _forbidden_claim_violation  # noqa: E402
from src.two_bot.types import StoryBundle  # noqa: E402
from src.voice.safety import run_safety_pipeline  # noqa: E402

# Fixture defaults, importable by tests (tests/test_writer_dryrun.py builds a
# Namespace straight from this dict so fixture drift fails offline, not in a
# paid workflow run).
DEFAULTS: dict = {
    "type": "fire",
    "samples": 3,
    "no_impact": False,
    # fire (hotspot) — the A1 Colorado-class shape.
    "lat": 39.1,
    "lon": -105.4,
    "frp": 595.0,
    "confidence": 95,
    "nearest_city": "Colorado Springs",
    "country": "United States",
    # fire_footprint (named complex) — crosses the 100,000 ha tier.
    "name": "Sierra Complex",
    "hectares": 103400.0,
    "region": "California",
    "footprint_country": "US",
    "start_days_ago": 21,
    # human_impact fixture knobs (both types).
    "incident": None,  # None -> "Alpine" for fire, the complex name for footprint
    "personnel": 1450,
    "fatalities": 3,
    "fatality_source": "The Washington Post",
    "fatality_url": "https://www.washingtonpost.com/climate-environment/",
    # dust — the Phalodi-class shape (P_dust: tier-2 dust WITH the co-measured
    # PM10 WHO anchor; 900/45 = 20.0×). Dust ignores the impact knobs — no
    # human_impact fixture exists for dust (the A1 matcher has no dust lane).
    "dust_daily_max": 2400.0,
    "pm10_24h_mean": 900.0,
    "dust_city": "Phalodi",
    "dust_country": "India",
    "dust_lat": 27.13,
    "dust_lon": 72.36,
    # cyclone_land_threat (Bavi-class) knobs. Forecast-tense fixture; never
    # attaches human_impact (a forecast has no toll — the impact knobs are
    # ignored for this type).
    "storm_name": "BAVI",
    "storm_wind_kt": 135,
    "landmass": "Taiwan",
    "landmass_city": "Taipei",
    "distance_nm": 25.0,
    "tau_h": 48,
    "forecast_wind_kt": 95,
    # precipitation_extreme (Astana-class) knobs
    "precip_location": "Astana",
    "precip_country": "Kazakhstan",
    "precip_mm": 358.0,
    "precip_period_days": 7,
    "precip_threshold_mm": 300.0,
    "record_path": False,
    "country_cluster": False,
}

_NIFC_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)


def _empty_state() -> dict:
    """A DEFAULT_STATE with empty memory — no shipped tweets, no reuse pressure."""
    state = deepcopy(DEFAULT_STATE)
    state["memory"] = {
        "ongoing_events": [],
        "used_era_anchors": [],
        "used_peer_comparisons": [],
        "used_framings": [],
        "shipped_tweets": [],
    }
    return state


def _attach_impact(bundle: StoryBundle, args: argparse.Namespace, incident: str) -> None:
    """The Colorado-class human_impact fixture (A1 spec §Testing): structured
    NIFC response figures + a verified grounded-search fatalities entry.
    Every entry carries the full warrant — the evidence contract blocks less."""
    today = datetime.now(UTC).date().isoformat()
    bundle.human_impact = [
        {
            "claim": f"{args.personnel:,} personnel assigned to the {incident}",
            "value": args.personnel,
            "source_name": "NIFC",
            "url": _NIFC_URL,
            "as_of": today,
        },
        {
            "claim": f"{args.fatalities} firefighters killed on the {incident}",
            "value": args.fatalities,
            "source_name": args.fatality_source,
            "url": args.fatality_url,
            "as_of": today,
        },
    ]


def _build_bundle(args: argparse.Namespace) -> StoryBundle:
    if args.type == "cyclone_land_threat":
        # Forecast-tense fixture — never attaches human_impact (a forecast
        # has no toll; the impact knobs are ignored for this type).
        lt = LandThreatEvent(
            source="jtwc", storm_id="05W", storm_name=args.storm_name,
            basin="WP", advisory_number="024",
            issued_at=datetime.now(UTC).isoformat(),
            current_wind_kt=args.storm_wind_kt,
            landmass_country=args.landmass, nearest_city=args.landmass_city,
            min_distance_nm=args.distance_nm, closest_valid_at="dryrun",
            closest_tau_h=args.tau_h,
            forecast_wind_kt_at_closest=args.forecast_wind_kt,
            event_id="dryrun_land_threat_05w",
        )
        return build_cyclone_land_threat_bundle(lt)
    if args.type == "precipitation_extreme":
        # Never attaches human_impact (see DEFAULTS comment for dust) — the
        # --no-impact / impact knobs are ignored for this type. record_path
        # and country_cluster pick between three disjoint fixture shapes: a
        # threshold-crossing multi_day_accumulation (alert_threshold_mm, no
        # record fields), a daily_record with an archive previous_record_mm
        # (#372 — a static trigger presented as "the previous record" is a
        # false-record claim no downstream gate can catch), or a
        # country_precip_event cluster (city_count monitored cities each
        # broke a daily record; no per-city record fields ride it — codex P1).
        if args.country_cluster:
            event = PrecipExtremeEvent(
                kind="country_precip_event",
                location=args.precip_country,
                country=args.precip_country,
                date=datetime.now(UTC).date().isoformat(),
                mm_total=args.precip_mm,
                period_days=1,
                deviation_from_record_mm=None,
                previous_record_mm=None,
                previous_record_year=None,
                lat=51.17,
                lon=71.43,
                city_count=12,
                sample_cities=["Astana", "Karaganda", "Pavlodar"],
                event_id="dryrun_precip_country_kazakhstan",
                alert_threshold_mm=None,
            )
            return build_precipitation_bundle(event)
        record = bool(args.record_path)
        event = PrecipExtremeEvent(
            kind="daily_record" if record else "multi_day_accumulation",
            location=args.precip_location,
            country=args.precip_country,
            date=datetime.now(UTC).date().isoformat(),
            mm_total=args.precip_mm,
            period_days=1 if record else args.precip_period_days,
            deviation_from_record_mm=148.0 if record else None,
            previous_record_mm=210.0 if record else None,
            previous_record_year=2013 if record else None,
            lat=51.17,
            lon=71.43,
            city_count=1,
            sample_cities=[args.precip_location],
            event_id="dryrun_precip_astana",
            alert_threshold_mm=None if record else args.precip_threshold_mm,
        )
        return build_precipitation_bundle(event)
    if args.type == "dust":
        # No _attach_impact for dust — the fixture never carries human_impact
        # (see DEFAULTS comment). The --no-impact / impact knobs are ignored.
        who_multiple = (
            round(args.pm10_24h_mean / 45.0, 1)
            if args.pm10_24h_mean is not None else None
        )
        event = DustEvent(
            city=args.dust_city,
            country=args.dust_country,
            lat=args.dust_lat,
            lon=args.dust_lon,
            date=datetime.now(UTC).date().isoformat(),
            dust_daily_max=args.dust_daily_max,
            tier=_tier(args.dust_daily_max, DUST_TIERS),
            aod_daily_max=None,
            event_id=f"dryrun_dust_{args.dust_city.lower()}",
            pm10_24h_mean=args.pm10_24h_mean,
            who_pm10_multiple=who_multiple,
        )
        return build_dust_event_bundle(event)
    if args.type == "fire_footprint":
        hectares = float(args.hectares)
        fc = FireComplex(
            complex_id="dryrun_cx_001",
            name=args.name,
            country=args.footprint_country,
            region=args.region,
            hectares=hectares,
            start_date=date.today() - timedelta(days=args.start_days_ago),
            tier=_classify_tier(hectares),
            event_id="dryrun_ff_cx_001",
        )
        bundle = build_fire_footprint_bundle(fc)
        incident = args.incident or args.name
    else:
        fire = FireEvent(
            lat=args.lat,
            lon=args.lon,
            confidence=args.confidence,
            frp=args.frp,
            nearest_city=args.nearest_city,
            country=args.country,
            event_id=f"dryrun_fire_{args.nearest_city.replace(' ', '_').lower()}",
        )
        bundle = build_fire_bundle(fire)
        incident = args.incident or "Alpine fire"
    if not args.no_impact:
        # Fixture claims name the incident the way real retrieval would —
        # the complex_name for a named complex; a news-supplied incident
        # name for a nameless hotspot (the A1 matcher's unambiguous case).
        _attach_impact(bundle, args, incident)
    return bundle


def _print_bundle(bundle: StoryBundle) -> None:
    facts = {f["label"]: f.get("value") for f in bundle.current_facts}
    print(f"  signal_kind ....... {bundle.signal_kind}")
    print(f"  where ............. {bundle.where}")
    h = bundle.headline_metric
    print(f"  headline .......... {h['label']} = {h['value']} {h.get('unit', '')}".rstrip())
    if bundle.signal_kind == "fire":
        print(f"  frp_tier .......... {facts.get('frp_tier')} (floor {facts.get('frp_tier_floor_mw')} MW)")
    elif bundle.signal_kind == "dust_event":
        print(f"  dust_daily_max .... {facts.get('dust_daily_max_ug_m3')} μg/m³ (tier {facts.get('tier')})")
        print(f"  pm10 24h mean ..... {facts.get('pm10_24h_mean_ug_m3')} μg/m³")
        print(f"  WHO PM10 multiple . {facts.get('who_pm10_multiple')}× (guideline {facts.get('who_pm10_24h_guideline_ug_m3')} μg/m³)")
    elif bundle.signal_kind == "cyclone_land_threat":
        print(f"  storm ............. {facts.get('storm_name')} ({facts.get('current_wind_kt')} kt, Cat {facts.get('saffir_simpson_category')})")
        print(f"  landmass .......... {facts.get('landmass_country')} (near {facts.get('nearest_city')})")
        print(f"  closest approach .. {facts.get('min_distance_nm')} NM within {facts.get('closest_tau_h')}h")
        print(f"  forecast wind ..... {facts.get('forecast_wind_kt_at_closest')} kt at closest")
    elif bundle.signal_kind == "precipitation_extreme":
        print(f"  rainfall_mm ....... {facts.get('rainfall_mm')} mm over {facts.get('period_days')} day(s)")
        if facts.get("event_kind") == "country_precip_event":
            print(f"  city_count ........ {facts.get('city_count')} monitored cities (each broke a daily record)")
            print(f"  heaviest single-city {facts.get('rainfall_mm')} mm")
        elif facts.get("previous_record_mm") is not None:
            print(f"  record ............ previous record {facts.get('previous_record_mm')} mm "
                  f"({facts.get('previous_record_year')}) · deviation +{facts.get('deviation_from_record_mm')} mm")
        else:
            print(f"  alert_threshold ... {facts.get('alert_threshold_mm')} mm")
    else:
        print(f"  complex_name ...... {facts.get('complex_name')}")
        print(f"  tier crossed ...... {facts.get('tier_hectares')} ha")
        print(f"  area approx ....... {facts.get('area_km2_approx')} km² / {facts.get('area_acres_approx')} acres")
    if bundle.human_impact:
        print(f"  human_impact ...... {len(bundle.human_impact)} entries:")
        for entry in bundle.human_impact:
            print(f"    - {entry['claim']} (per {entry['source_name']}, as of {entry['as_of']})")
    else:
        print("  human_impact ...... (none — control run)")


def _run_one(bundle: StoryBundle, state: dict, idx: int) -> bool:
    """Draft once and run the gate chain. Returns True iff it would ship."""
    print(f"\n{'─' * 72}\nCANDIDATE {idx}")
    mem = memory.build_memory_slice(state, bundle)
    result = writer.write_tweet(bundle, mem)

    if result.tweet is None:
        print(f"  WRITER KILL: {result.kill_reason}")
        return False

    tweet = result.tweet
    print(f"  DRAFT ({len(tweet)} chars):\n    {tweet}\n")
    if bundle.human_impact:
        print(f"  writer cited_impact self-report: {result.cited_impact}")

    safe, reason = run_safety_pipeline(tweet)
    print(f"  [safety]    {'PASS' if safe else 'FAIL — ' + str(reason)}")
    if not safe:
        return False

    forbidden = _forbidden_claim_violation(tweet, bundle)
    print("  [§F gate]   " + ("PASS" if forbidden is None else f"FAIL — forbidden claim: {forbidden!r}"))
    if forbidden is not None:
        return False

    fc = fact_check.fact_check(tweet, [], bundle, state)
    print("  [fact_check] " + ("PASS" if fc.passed else "FAIL — " + "; ".join(fc.failures)))
    if not fc.passed:
        return False

    cr = critic.critic_review(tweet, bundle, state, shipped_recent=[])
    verdict = cr.verdict
    ok = verdict == "PASS"
    print(f"  [critic]    {verdict}{'' if ok else ' — ' + str(cr.kill_reason)}")
    if not ok:
        return False

    if bundle.human_impact:
        # Decision 4 — what save_draft would decide for this draft.
        review_context = {"two_bot": {
            "human_impact": bundle.human_impact,
            "cited_impact": result.cited_impact,
        }}
        citation = detect_impact_citation(tweet, review_context)
        routing = "FORCED manual_only (cited_impact)" if citation.forced else "normal approval policy"
        print(f"  [decision4] writer={citation.writer_flag} regex={citation.regex_hit} → {routing}")
    print("  ✅ SHIPS (clears evidence → writer → safety → §F → fact-check → critic)")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--type", choices=("fire", "fire_footprint", "dust", "cyclone_land_threat", "precipitation_extreme"), default=DEFAULTS["type"])
    p.add_argument("--samples", type=int, default=DEFAULTS["samples"], help="number of candidate drafts")
    p.add_argument("--no-impact", dest="no_impact", action="store_true",
                   help="control run: same bundle with NO human_impact attached")
    # fire (hotspot) knobs
    p.add_argument("--lat", type=float, default=DEFAULTS["lat"])
    p.add_argument("--lon", type=float, default=DEFAULTS["lon"])
    p.add_argument("--frp", type=float, default=DEFAULTS["frp"])
    p.add_argument("--confidence", type=int, default=DEFAULTS["confidence"])
    p.add_argument("--nearest-city", default=DEFAULTS["nearest_city"])
    p.add_argument("--country", default=DEFAULTS["country"])
    # fire_footprint (named complex) knobs
    p.add_argument("--name", default=DEFAULTS["name"], help="complex_name for --type fire_footprint")
    p.add_argument("--hectares", type=float, default=DEFAULTS["hectares"])
    p.add_argument("--region", default=DEFAULTS["region"])
    p.add_argument("--footprint-country", default=DEFAULTS["footprint_country"])
    p.add_argument("--start-days-ago", type=int, default=DEFAULTS["start_days_ago"],
                   help="complex start_date = today - N days (today-relative; never hardcode)")
    # human_impact fixture knobs
    p.add_argument("--incident", default=DEFAULTS["incident"],
                   help='incident name for impact claims (default: "the Alpine fire" / "the <complex name>")')
    p.add_argument("--personnel", type=int, default=DEFAULTS["personnel"])
    p.add_argument("--fatalities", type=int, default=DEFAULTS["fatalities"])
    p.add_argument("--fatality-source", default=DEFAULTS["fatality_source"])
    p.add_argument("--fatality-url", default=DEFAULTS["fatality_url"])
    # dust knobs
    p.add_argument("--dust-daily-max", dest="dust_daily_max", type=float,
                   default=DEFAULTS["dust_daily_max"])
    p.add_argument("--pm10-24h-mean", dest="pm10_24h_mean", type=float,
                   default=DEFAULTS["pm10_24h_mean"],
                   help="co-measured PM10 24h mean; the WHO anchor (45 μg/m³ AQG)")
    p.add_argument("--dust-city", dest="dust_city", default=DEFAULTS["dust_city"])
    p.add_argument("--dust-country", dest="dust_country", default=DEFAULTS["dust_country"])
    p.add_argument("--dust-lat", dest="dust_lat", type=float, default=DEFAULTS["dust_lat"])
    p.add_argument("--dust-lon", dest="dust_lon", type=float, default=DEFAULTS["dust_lon"])
    # cyclone_land_threat knobs
    p.add_argument("--storm-name", dest="storm_name", default=DEFAULTS["storm_name"])
    p.add_argument("--storm-wind-kt", dest="storm_wind_kt", type=int,
                   default=DEFAULTS["storm_wind_kt"])
    p.add_argument("--landmass", dest="landmass", default=DEFAULTS["landmass"])
    p.add_argument("--landmass-city", dest="landmass_city", default=DEFAULTS["landmass_city"])
    p.add_argument("--distance-nm", dest="distance_nm", type=float,
                   default=DEFAULTS["distance_nm"])
    p.add_argument("--tau-h", dest="tau_h", type=int, default=DEFAULTS["tau_h"])
    p.add_argument("--forecast-wind-kt", dest="forecast_wind_kt", type=int,
                   default=DEFAULTS["forecast_wind_kt"])
    # precipitation_extreme knobs
    p.add_argument("--precip-location", dest="precip_location", default=DEFAULTS["precip_location"])
    p.add_argument("--precip-country", dest="precip_country", default=DEFAULTS["precip_country"])
    p.add_argument("--precip-mm", dest="precip_mm", type=float, default=DEFAULTS["precip_mm"])
    p.add_argument("--precip-period-days", dest="precip_period_days", type=int,
                   default=DEFAULTS["precip_period_days"])
    p.add_argument("--precip-threshold-mm", dest="precip_threshold_mm", type=float,
                   default=DEFAULTS["precip_threshold_mm"])
    p.add_argument("--record-path", dest="record_path", action="store_true",
                   default=DEFAULTS["record_path"],
                   help="daily_record fixture shape (previous_record_mm) instead of "
                        "the default multi_day_accumulation (alert_threshold_mm)")
    p.add_argument("--country-cluster", dest="country_cluster", action="store_true",
                   default=DEFAULTS["country_cluster"],
                   help="country_precip_event fixture shape (city_count monitored "
                        "cities each broke a daily record) instead of the default "
                        "multi_day_accumulation (alert_threshold_mm)")
    args = p.parse_args()

    if args.record_path and args.country_cluster:
        p.error("--record-path and --country-cluster are mutually exclusive")

    bundle = _build_bundle(args)

    print(f"WRITER DRY-RUN — type={args.type}")
    print(f"writer={writer.WRITER_MODEL}  critic={critic.CRITIC_MODEL}  "
          f"fact_check={fact_check.FACT_CHECKER_MODEL}")
    print("\nBUNDLE THE WRITER SEES:")
    _print_bundle(bundle)

    audit = audit_story_bundle(bundle)
    errors = [i.code for i in audit.issues if i.severity == "error"]
    print(f"\n  [evidence contract] {'PASS' if audit.prompt_ready else 'FAIL — ' + ', '.join(errors)}")
    if not audit.prompt_ready:
        return 1

    missing = [k for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"\n⚠️  Cannot run the live gate chain — missing env: {', '.join(missing)}")
        print("    (writer needs ANTHROPIC_API_KEY; fact-check + critic need GEMINI_API_KEY)")
        return 2

    state = _empty_state()
    ships = sum(_run_one(bundle, state, i + 1) for i in range(args.samples))
    print(f"\n{'═' * 72}\n{ships}/{args.samples} candidates would ship.")
    return 0 if ships else 1


if __name__ == "__main__":
    raise SystemExit(main())
