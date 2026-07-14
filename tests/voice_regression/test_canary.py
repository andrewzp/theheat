"""Daily 3-fixture billing + voice canary.

The cheap, loud tripwire for the 2026-07-11 failure class: the Anthropic
balance hit $0 and drafting stopped SILENTLY for 2.5 days — ``bot.yml``
tolerates per-candidate writer failures, so every scheduled run stayed green
while zero drafts were produced. The nightly full suite was the only loud
signal, and the economics plan (P0.4) moved that suite off nightly cron.
This canary keeps a small daily paid heartbeat that:

  * fails RED on ANY provider error (billing exhaustion, 401/403 auth,
    transport failures) — API reachability is the point;
  * fails RED on a MISSING key — a canary that skips reads as green;
  * asserts ≥2 of 3 fixtures produce a safety-passing tweet. The full
    suite's contract ("a clean kill is never a failure") is right for a
    quality gate — any ONE fixture may legitimately decline on a given
    sampling — but three simultaneous kills on three historically strong
    bundles means the writer lane is broken (bad prompt deploy, mis-scoped
    key, dead model id), which is exactly what a canary must catch;
  * fails RED if any produced tweet violates the safety pipeline (the
    canary never blesses unsafe copy — honesty gates don't weaken here).

Cost: 3 Sonnet replays ≈ $0.08/day. Selected by the `voice_canary` marker
(the daily canary job); also carries `voice_replay` so the default hermetic
CI suite keeps deselecting it and the weekly full run includes it.
"""

from __future__ import annotations

import os

import pytest

from src.voice.safety import run_safety_pipeline

pytestmark = [
    pytest.mark.voice_replay,
    pytest.mark.voice_canary,
    pytest.mark.allow_network,
]

# Three historically reliable producers across three signal families
# (station temperature record / atmospheric milestone / ocean). Tunable:
# swap a fixture if its bundle goes stale, but keep the families diverse —
# a single-family canary can go quiet for editorial, not operational,
# reasons.
CANARY_FIXTURES = [
    "verkhoyansk_monthly_high_bundle",
    "co2_milestone_bundle",
    "marine_heatwave_bundle",
]

MIN_PRODUCING = 2


def test_canary_api_reachable_and_writer_produces(request, fresh_memory_slice):
    assert os.environ.get("ANTHROPIC_API_KEY"), (
        "ANTHROPIC_API_KEY is missing — the canary must fail loudly, not "
        "skip: a skipped canary reads as green on the dashboard."
    )
    from src.two_bot.writer import write_tweet

    produced = 0
    unsafe: list[str] = []
    outcomes: list[str] = []
    for name in CANARY_FIXTURES:
        bundle = request.getfixturevalue(name)
        try:
            result = write_tweet(bundle, fresh_memory_slice)
        except Exception as exc:  # noqa: BLE001 — ANY provider error is the signal
            pytest.fail(
                f"provider error on {name} — billing/auth/transport outage "
                f"(the 2026-07-11 failure class): {type(exc).__name__}: {exc}"
            )
        if result.tweet is None:
            outcomes.append(f"{name}: clean kill ({result.kill_reason!r})")
            continue
        safe, reason = run_safety_pipeline(result.tweet)
        if safe:
            produced += 1
            outcomes.append(f"{name}: produced a safety-passing tweet")
        else:
            unsafe.append(f"{name}: {reason} — {result.tweet!r}")
            outcomes.append(f"{name}: UNSAFE ({reason})")

    report = "\n".join(outcomes)
    assert not unsafe, (
        "canary: writer produced copy the safety pipeline rejects:\n"
        + "\n".join(unsafe)
    )
    assert produced >= MIN_PRODUCING, (
        f"canary: only {produced}/{len(CANARY_FIXTURES)} fixtures produced a "
        f"safety-passing tweet (threshold {MIN_PRODUCING}) — the writer lane "
        f"is degraded:\n{report}"
    )
