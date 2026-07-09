#!/usr/bin/env python
"""Offline dry-run harness for the heat records-cluster (#414) writer voice.

Reconstructs a spatially-coherent cluster of same-day heat records (an Iberia
burst by default: a mix of all-time / monthly / daily records across Spanish and
Portuguese cities), builds the REAL production bundle via ``name_cluster`` +
``build_heat_records_cluster_bundle``, and runs it through the live pipeline's
gate chain — evidence-contract -> writer -> safety -> §F forbidden-claims ->
fact-check -> critic — printing every stage so you can confirm a prompt change
"lands harder while passing fact-check + critic" before it ships. (The
evidence-contract gate runs BEFORE the writer in production, so the harness checks
it once up front and refuses to draft against a malformed bundle.)

The class fires on record SIGNIFICANCE (all-time >> monthly >> daily) and is
GLOBAL by construction (world cities enter via monthly/all-time). The published
copy must NEVER assert a cause ("heat dome", blocking ridge, …) and must keep the
tense honest to ``records_provenance`` (observed vs forecast).

The writer is stochastic, so ``--samples N`` drafts N candidates (useful for
voice iteration). The writer needs ``ANTHROPIC_API_KEY``; fact-check + critic need
``GEMINI_API_KEY``. With no keys the harness prints the bundle it WOULD run and
exits 2 — it never silently no-ops.

Usage::

    # default mixed-provenance Iberia cluster, 3 candidates:
    ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
      .venv/bin/python scripts/records_cluster_writer_dryrun.py --samples 3

    # an all-forecast, monthly-heavy world cluster:
    .venv/bin/python scripts/records_cluster_writer_dryrun.py \
      --all-time 0 --monthly 6 --daily 2 --provenance forecast
"""

from __future__ import annotations

import argparse
import os
import sys
from copy import deepcopy
from datetime import date

# Allow `python scripts/records_cluster_writer_dryrun.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.editorial.records_cluster import name_cluster  # noqa: E402
from src.state import DEFAULT_STATE  # noqa: E402
from src.two_bot import critic, fact_check, memory, writer  # noqa: E402
from src.two_bot.evidence_contract import audit_story_bundle  # noqa: E402
from src.two_bot.intern import build_heat_records_cluster_bundle  # noqa: E402
from src.two_bot.pipeline import _forbidden_claim_violation  # noqa: E402
from src.two_bot.types import StoryBundle  # noqa: E402
from src.voice.safety import run_safety_pipeline  # noqa: E402

# A pool of real Iberian cities (lat, lon) that cluster under single-linkage — enough
# to draw all-time / monthly / daily members from a plausible same-day cluster.
# Portugal sits within the first dozen so the default member counts exercise the
# multi-country (Spain + Portugal) Iberia geography, not Spain alone.
_IBERIA_POOL: list[tuple[str, str, float, float]] = [
    ("Madrid", "Spain", 40.42, -3.70), ("Toledo", "Spain", 39.86, -4.02),
    ("Valencia", "Spain", 39.47, -0.38), ("Zaragoza", "Spain", 41.65, -0.89),
    ("Barcelona", "Spain", 41.39, 2.16), ("Albacete", "Spain", 38.99, -1.86),
    ("Cordoba", "Spain", 37.89, -4.78), ("Badajoz", "Spain", 38.88, -6.97),
    ("Lisbon", "Portugal", 38.72, -9.13), ("Evora", "Portugal", 38.57, -7.91),
    ("Seville", "Spain", 37.39, -5.98), ("Ciudad Real", "Spain", 38.99, -3.93),
    ("Salamanca", "Spain", 40.97, -5.66), ("Valladolid", "Spain", 41.65, -4.72),
]


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


def _build_members(args: argparse.Namespace) -> list[dict]:
    """One fired cluster's members: all-time first, then monthly, then daily, drawn
    from the Iberian pool. ``observed`` is set per --provenance (observed=GHCN,
    forecast=Open-Meteo on-pace, mixed=alternating)."""
    tiers = (["all_time"] * args.all_time
             + ["monthly"] * args.monthly
             + ["daily"] * args.daily)
    if len(tiers) > len(_IBERIA_POOL):
        raise SystemExit(
            f"requested {len(tiers)} members but the pool has {len(_IBERIA_POOL)}"
        )
    members = []
    for i, (tier, (city, country, lat, lon)) in enumerate(zip(tiers, _IBERIA_POOL)):
        if args.provenance == "observed":
            observed = True
        elif args.provenance == "forecast":
            observed = False
        else:  # mixed
            observed = i % 2 == 0
        members.append({
            "city": city, "country": country, "lat": lat, "lon": lon,
            "tier": tier, "observed": observed,
            "temp_c": 43.0, "old_record_c": 41.5, "old_record_year": 1994,
            "margin_c": 1.5,
        })
    return members


def _print_bundle_facts(bundle: StoryBundle) -> None:
    facts = {f["label"]: f["value"] for f in bundle.current_facts}
    fc = bundle.historical_context.get("forbidden_claims", [])
    print(f"  where ................ {bundle.where}")
    print(f"  city_count ........... {facts.get('city_count')}")
    print(f"  tier_counts .......... {facts.get('tier_counts')}   <- LEAD with all-time + monthly")
    print(f"  records_provenance ... {facts.get('records_provenance')}   <- the tense contract")
    print(f"  significant_cities ... {facts.get('significant_cities')}")
    print(f"  region_name .......... {facts.get('region_name')}")
    print(f"  cluster_continents ... {facts.get('cluster_continents')}")
    print(f"  cluster_countries .... {facts.get('cluster_countries')}")
    print(f"  forbidden_claims ..... {len(fc)} phrases (cause words + off-cluster continents)")


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

    safe, reason = run_safety_pipeline(tweet)
    print(f"  [safety]    {'PASS' if safe else 'FAIL — ' + str(reason)}")
    if not safe:
        return False

    forbidden = _forbidden_claim_violation(tweet, bundle)
    print("  [§F gate]   " + ("PASS" if forbidden is None else f"FAIL — forbidden claim: {forbidden!r}"))
    if forbidden is not None:
        return False

    fc = fact_check.fact_check(tweet, [], bundle, state)
    print("  [fact_check]" + ("PASS" if fc.passed else " FAIL — " + "; ".join(fc.failures)))
    if not fc.passed:
        return False

    cr = critic.critic_review(tweet, bundle, state, shipped_recent=[])
    ok = cr.verdict == "PASS"
    print(f"  [critic]    {cr.verdict}{'' if ok else ' — ' + str(cr.kill_reason)}")
    if ok:
        print("  ✅ SHIPS (clears writer → safety → §F → fact-check → critic)")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all-time", type=int, default=2, help="number of all-time-record members")
    p.add_argument("--monthly", type=int, default=4, help="number of monthly-record members")
    p.add_argument("--daily", type=int, default=6, help="number of daily-record members")
    p.add_argument("--provenance", choices=("observed", "forecast", "mixed"), default="mixed")
    p.add_argument("--when", default=date.today().isoformat())
    p.add_argument("--samples", type=int, default=3, help="number of candidate drafts")
    args = p.parse_args()

    members = _build_members(args)
    name = name_cluster(members)
    bundle = build_heat_records_cluster_bundle(
        members, name, event_id=f"heat_records_cluster_{args.when}_dryrun", when=args.when,
    )

    print("HEAT RECORDS-CLUSTER WRITER DRY-RUN")
    print(f"writer={writer.WRITER_MODEL}  critic={critic.CRITIC_MODEL}  "
          f"fact_check={fact_check.FACT_CHECKER_MODEL}")
    print("\nBUNDLE THE WRITER SEES:")
    _print_bundle_facts(bundle)

    # Evidence-contract gate — production runs this BEFORE the writer (pipeline.py),
    # rejecting a malformed bundle before any draft. Mirror it so the harness can
    # never print SHIPS for a bundle production would refuse to generate against.
    audit = audit_story_bundle(bundle)
    if audit.prompt_ready:
        print("\n  [evidence]  PASS (prompt_ready)")
    else:
        errors = ", ".join(i.code for i in audit.issues if i.severity == "error")
        print(f"\n  [evidence]  FAIL — {errors}")
        print("  Bundle is not prompt-ready — production rejects it BEFORE the writer.")
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
