#!/usr/bin/env python
"""Offline dry-run harness for the regional-anomaly ("reganom") writer voice.

The handoff lamented that there was no way to regenerate a reganom draft without
a prod gist reset + an `alerts` dispatch. This is that tool: it reconstructs a
``RegionalAnomalyEvent`` (the France just-ended heatwave by default), builds the
real production bundle, and runs the draft through the SAME gate chain the live
pipeline uses — writer -> safety -> §F forbidden-claims -> fact-check -> critic —
printing every stage so you can confirm a prompt change "lands harder while
passing fact-check + critic" before it ships.

The writer is stochastic, so ``--samples N`` drafts N candidates (useful for
voice iteration). The writer needs ``ANTHROPIC_API_KEY``; fact-check + critic
need ``GEMINI_API_KEY``. With no keys the harness prints what it WOULD run and
exits 2 — it never silently no-ops.

Usage::

    # full France default, 3 candidates:
    ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
      .venv/bin/python scripts/reganom_writer_dryrun.py --samples 3

    # another region / tune the event:
    .venv/bin/python scripts/reganom_writer_dryrun.py \
      --region Iberia --anomaly 9.4 --zscore 3.1 --days 6 \
      --window-start 2026-07-01 --window-end 2026-07-06 --latest-day 2026-07-07
"""

from __future__ import annotations

import argparse
import os
import sys
from copy import deepcopy
from datetime import date

# Allow `python scripts/reganom_writer_dryrun.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.reanalysis_anomaly import RegionalAnomalyEvent  # noqa: E402
from src.state import DEFAULT_STATE  # noqa: E402
from src.two_bot import critic, fact_check, memory, writer  # noqa: E402
from src.two_bot.intern import build_regional_anomaly_bundle  # noqa: E402
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


def _build_event(args: argparse.Namespace) -> RegionalAnomalyEvent:
    region = args.region
    return RegionalAnomalyEvent(
        region=region,
        region_slug=region.replace(" ", "_"),
        cities_sampled=args.cities,
        mean_anomaly_c=args.anomaly,
        mean_zscore=args.zscore,
        fraction_exceeding=args.fraction,
        sustained_days=args.days,
        window_start=args.window_start,
        window_end=args.window_end,
        event_id=f"reganom_{region.replace(' ', '_')}_{args.window_end}",
        signal_date=date.fromisoformat(args.window_end),
        latest_complete_day=args.latest_day,
    )


def _print_bundle_facts(bundle: StoryBundle) -> None:
    h = bundle.headline_metric
    facts = {f["label"]: f["value"] for f in bundle.current_facts}
    print(f"  where ............. {bundle.where}")
    print(f"  value (raw) ....... {h['value']}°C")
    print(f"  value_rounded_c ... {h.get('value_rounded_c')}°C   <- what the tweet should cite")
    print(f"  cities_sampled .... {h['cities_sampled']}")
    print(f"  mean_zscore ....... {facts.get('mean_zscore')}σ")
    print(f"  window ............ {facts.get('window_start')} → {facts.get('window_end')}")
    print(f"  sustained_days .... {facts.get('sustained_days')}")
    print(f"  ended_days_ago .... {facts.get('ended_days_ago')}  "
          f"({'ENDED → past tense required' if facts.get('ended_days_ago') else 'ongoing → present tense ok'})")


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
    verdict = cr.verdict
    ok = verdict == "PASS"
    print(f"  [critic]    {verdict}{'' if ok else ' — ' + str(cr.kill_reason)}")
    if ok:
        print("  ✅ SHIPS (clears writer → safety → §F → fact-check → critic)")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # France just-ended heatwave defaults (mirrors the 2026-06-28 draft).
    p.add_argument("--region", default="France")
    p.add_argument("--cities", type=int, default=6)
    p.add_argument("--anomaly", type=float, default=11.53, help="mean_anomaly_c (raw, 2dp)")
    p.add_argument("--zscore", type=float, default=2.8)
    p.add_argument("--fraction", type=float, default=0.9)
    p.add_argument("--days", type=int, default=8)
    p.add_argument("--window-start", default="2026-06-20")
    p.add_argument("--window-end", default="2026-06-27")
    p.add_argument("--latest-day", default="2026-06-28", help="latest complete ERA5 day (drives ended_days_ago)")
    p.add_argument("--samples", type=int, default=3, help="number of candidate drafts")
    args = p.parse_args()

    event = _build_event(args)
    bundle = build_regional_anomaly_bundle(event)

    print(f"REGANOM WRITER DRY-RUN — {args.region}")
    print(f"writer={writer.WRITER_MODEL}  critic={critic.CRITIC_MODEL}  "
          f"fact_check={fact_check.FACT_CHECKER_MODEL}")
    print("\nBUNDLE THE WRITER SEES:")
    _print_bundle_facts(bundle)

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
