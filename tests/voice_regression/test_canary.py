"""Daily 3-fixture billing + voice canary.

The cheap, loud tripwire for the 2026-07-11 failure class: the Anthropic
balance hit $0 and drafting stopped SILENTLY for 2.5 days — ``bot.yml``
tolerates per-candidate writer failures, so every scheduled run stayed green
while zero drafts were produced. The nightly full suite was the only loud
signal, and the economics plan (P0.4) moved that suite off nightly cron.
This canary keeps a small daily paid heartbeat that:

  * fails RED on any UNRECOVERED provider error (billing exhaustion,
    401/403 auth, transport failures that survive call_with_retries' 3
    attempts) — API reachability is the point. A transient error the
    retry helper absorbs stays green: a recovered lane is a working lane;
  * fails RED on a MISSING key — a canary that skips reads as green;
  * asserts ≥2 of 3 fixtures produce a safety-passing tweet, with ONE
    bounded re-sample of only the fixtures that killed. The full suite's
    contract ("a clean kill is never a failure") is right for a quality
    gate — any single sampling may legitimately decline (this suite once
    spent five straight days red on exactly that) — but kills from a
    BROKEN lane (bad prompt deploy, mis-scoped key, dead model id) are
    deterministic, so requiring the failure to repeat across two
    samplings squares away the stochastic false-red while keeping the
    real-outage signal. Worst-case cost: +2 replays (~$0.05);
  * fails RED if any produced tweet violates the safety pipeline (the
    canary never blesses unsafe copy — honesty gates don't weaken here).

Cost: 3 Sonnet replays ≈ $0.08/day (+2 worst case on a re-sample);
skips Sundays (the weekly full suite covers them). Selected by the
`voice_canary` marker
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


def _sample_fixture(request, fresh_memory_slice, name, outcomes, unsafe):
    """One replay of one fixture. Returns True iff a safety-passing tweet."""
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(name)
    try:
        result = write_tweet(bundle, fresh_memory_slice)
    except Exception as exc:  # noqa: BLE001 — an UNRECOVERED provider error is the signal
        pytest.fail(
            f"provider error on {name} — billing/auth/transport outage "
            f"(the 2026-07-11 failure class): {type(exc).__name__}: {exc}"
        )
    if result.tweet is None:
        outcomes.append(f"{name}: clean kill ({result.kill_reason!r})")
        return False
    safe, reason = run_safety_pipeline(result.tweet)
    if safe:
        outcomes.append(f"{name}: produced a safety-passing tweet")
        return True
    unsafe.append(f"{name}: {reason} — {result.tweet!r}")
    outcomes.append(f"{name}: UNSAFE ({reason})")
    return False


def test_canary_api_reachable_and_writer_produces(request, fresh_memory_slice):
    assert os.environ.get("ANTHROPIC_API_KEY"), (
        "ANTHROPIC_API_KEY is missing — the canary must fail loudly, not "
        "skip: a skipped canary reads as green on the dashboard."
    )

    unsafe: list[str] = []
    outcomes: list[str] = []
    producing: set[str] = set()
    for name in CANARY_FIXTURES:
        if _sample_fixture(request, fresh_memory_slice, name, outcomes, unsafe):
            producing.add(name)

    # Bounded re-sample (codex P1): a single sampling can legitimately kill
    # — this suite once spent five straight days red on exactly that. Kills
    # from a BROKEN lane are deterministic, so only a repeated failure
    # across two samplings is a real signal. Re-sample only the killers.
    if len(producing) < MIN_PRODUCING and not unsafe:
        outcomes.append("-- below threshold; one bounded re-sample of the killers --")
        for name in [n for n in CANARY_FIXTURES if n not in producing]:
            if _sample_fixture(request, fresh_memory_slice, name, outcomes, unsafe):
                producing.add(name)

    report = "\n".join(outcomes)
    assert not unsafe, (
        "canary: writer produced copy the safety pipeline rejects:\n"
        + "\n".join(unsafe)
    )
    assert len(producing) >= MIN_PRODUCING, (
        f"canary: only {len(producing)}/{len(CANARY_FIXTURES)} fixtures "
        f"produced a safety-passing tweet (threshold {MIN_PRODUCING}) across "
        f"two samplings — the writer lane is degraded:\n{report}"
    )
