#!/usr/bin/env python
"""Offline dry-run harness for Bet A phase A1 — the sourced-impact writer path.

The reganom-dryrun pattern, extended per the A1 spec: build a real FIRMS-style
fire bundle, attach a Colorado-class ``human_impact`` fixture (NIFC structured
personnel/size + a verified grounded-search fatalities entry), and run it
through the SAME gate chain the live pipeline uses — evidence contract ->
writer (with the IMPACT_GUIDANCE user-prompt rider) -> safety -> §F ->
fact-check -> critic — then print the decision-4 verdict save_draft would
reach (forced ``manual_only`` when the text cites impact, fail-closed).

Run this in Actions via workflow_dispatch (news-enrich-dryrun.yml) BEFORE
flipping ``THEHEAT_NEWS_ENRICH_ENABLED``: it proves the writer attributes,
the fact-checker tolerates attributed impact, and the forced-manual routing
fires — at zero prod state cost.

The writer is stochastic, so ``--samples N`` drafts N candidates. The writer
needs ``ANTHROPIC_API_KEY``; fact-check + critic need ``GEMINI_API_KEY``.
With no keys the harness prints what it WOULD run and exits 2 — it never
silently no-ops.

Usage::

    ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
      .venv/bin/python scripts/news_enrich_writer_dryrun.py --samples 3

    # control run — same bundle, NO impact facts attached:
    .venv/bin/python scripts/news_enrich_writer_dryrun.py --no-impact
"""

from __future__ import annotations

import argparse
import os
import sys
from copy import deepcopy
from datetime import UTC, datetime

# Allow `python scripts/news_enrich_writer_dryrun.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.firms import FireEvent  # noqa: E402
from src.editorial.newsworthiness import detect_impact_citation  # noqa: E402
from src.state import DEFAULT_STATE  # noqa: E402
from src.two_bot import critic, fact_check, memory, writer  # noqa: E402
from src.two_bot.evidence_contract import audit_story_bundle  # noqa: E402
from src.two_bot.intern import build_fire_bundle  # noqa: E402
from src.two_bot.pipeline import _forbidden_claim_violation  # noqa: E402
from src.two_bot.types import StoryBundle  # noqa: E402
from src.voice.safety import run_safety_pipeline  # noqa: E402


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


def _build_bundle(args: argparse.Namespace) -> StoryBundle:
    fire = FireEvent(
        lat=args.lat,
        lon=args.lon,
        confidence=args.confidence,
        frp=args.frp,
        nearest_city=args.nearest_city,
        country="United States",
        event_id=f"dryrun_fire_{args.nearest_city.replace(' ', '_').lower()}",
    )
    bundle = build_fire_bundle(fire)
    if args.no_impact:
        return bundle

    today = datetime.now(UTC).date().isoformat()
    # The Colorado-class fixture (spec §Testing): structured NIFC response
    # figures + a verified grounded-search fatalities entry. Every entry
    # carries the full warrant — the evidence contract blocks anything less.
    bundle.human_impact = [
        {
            "claim": f"{args.personnel:,} personnel assigned to the {args.incident} fire",
            "value": args.personnel,
            "source_name": "NIFC",
            "url": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0/query",
            "as_of": today,
        },
        {
            "claim": f"{args.fatalities} firefighters killed on the {args.incident} fire",
            "value": args.fatalities,
            "source_name": args.fatality_source,
            "url": args.fatality_url,
            "as_of": today,
        },
    ]
    return bundle


def _print_bundle(bundle: StoryBundle) -> None:
    print(f"  where ............. {bundle.where}")
    print(f"  FRP ............... {bundle.headline_metric['value']} MW")
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

    # Decision 4 — what save_draft would decide for this draft.
    review_context = {"two_bot": {
        "human_impact": bundle.human_impact,
        "cited_impact": result.cited_impact,
    }} if bundle.human_impact else {"two_bot": {}}
    citation = detect_impact_citation(tweet, review_context)
    routing = "FORCED manual_only (cited_impact)" if citation.forced else "normal approval policy"
    print(f"  [decision4] writer={citation.writer_flag} regex={citation.regex_hit} → {routing}")
    print("  ✅ SHIPS (clears evidence → writer → safety → §F → fact-check → critic)")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # Colorado-class defaults: a high-FRP US fire with a real response footprint.
    p.add_argument("--lat", type=float, default=39.1)
    p.add_argument("--lon", type=float, default=-105.4)
    p.add_argument("--frp", type=float, default=595.0)
    p.add_argument("--confidence", type=int, default=95)
    p.add_argument("--nearest-city", default="Colorado Springs")
    p.add_argument("--incident", default="Alpine", help="incident name for the impact claims")
    p.add_argument("--personnel", type=int, default=1450)
    p.add_argument("--fatalities", type=int, default=3)
    p.add_argument("--fatality-source", default="The Washington Post")
    p.add_argument("--fatality-url", default="https://www.washingtonpost.com/climate-environment/")
    p.add_argument("--no-impact", action="store_true",
                   help="control run: same bundle with NO human_impact attached")
    p.add_argument("--samples", type=int, default=3, help="number of candidate drafts")
    args = p.parse_args()

    bundle = _build_bundle(args)

    print("NEWS-ENRICH (A1) WRITER DRY-RUN — fire + human_impact")
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
