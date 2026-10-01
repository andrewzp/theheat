"""Positive writer canary, blocked until its source fixtures are qualified.

The current packets explicitly contain invented values. Their valid structure is
not positive evidence: correct factual refusals must not be called an outage or
re-sampled with paid calls. Preflight reports this monitor as blocked before any
provider access. It never skips to green or certifies the writer as healthy.

A future independently qualified packet needs an exact hash and reviewed validity
window below. The intended two-of-three production threshold and safety checks
remain. Ordinary retained responses can separately show provider reachability;
this test cannot infer source truth, complete check success or useful copy from
those responses, usage counts, credential presence or a green workflow.

voice_replay keeps this live entry point excluded from hermetic CI. Offline tests
exercise its boundaries only with explicit provider and safety call traps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.editorial.revisions import fingerprint
from src.two_bot.retry import BudgetExhaustedError

import pytest

from src.voice.safety import run_safety_pipeline

pytestmark = [
    pytest.mark.voice_replay,
    pytest.mark.voice_canary,
    pytest.mark.allow_network,
]

# Explicit synthetic negative/control fixtures. No packet is qualified as
# positive production evidence; retain every fixture_only/provenance label.
CANARY_FIXTURES = [
    "verkhoyansk_monthly_high_bundle",
    "co2_milestone_bundle",
    "marine_heatwave_bundle",
]

MIN_PRODUCING = 2


@dataclass(frozen=True)
class FixtureQualification:
    bundle_sha256: str
    source_as_of: datetime
    valid_until: datetime
    evidence_review: str


# Code-reviewed qualification records only, never supplied by the packet itself.
# Empty deliberately: no independent source qualification has been established.
# Adding one requires the primary packet, permitted claim and time-window review;
# an exact hash binds that decision but does not prove it scientifically correct.
QUALIFIED_POSITIVE_FIXTURES: dict[str, FixtureQualification] = {}


def _positive_fixture_issue(name, bundle, now):
    raw = bundle.raw_signal_dump
    if isinstance(raw, dict):
        provenance = " ".join(str(raw.get(k, "")) for k in ("source_name", "fixture_note"))
        if raw.get("fixture_only") is not None or any(
            marker in provenance.lower() for marker in ("synthetic", "invented", "not a verified")
        ):
            return "synthetic_fixture"
    qualification = QUALIFIED_POSITIVE_FIXTURES.get(name)
    if qualification is None:
        return "positive_fixture_unqualified"
    if not qualification.evidence_review or fingerprint(bundle.to_dict()) != qualification.bundle_sha256:
        return "qualification_mismatch"
    start, end = qualification.source_as_of, qualification.valid_until
    if (start.tzinfo is None or end.tzinfo is None
            or not start <= now <= end or not timedelta(0) < end - start <= timedelta(hours=24)):
        return "qualification_not_current"
    return None


def _preflight_fixtures(request, *, now=None):
    """Reject malformed or unqualified positive evidence before every paid call."""
    from src.two_bot.evidence_contract import audit_story_bundle

    bundles = {name: request.getfixturevalue(name) for name in CANARY_FIXTURES}
    failures = []
    eligibility = []
    now = now or datetime.now(UTC)
    for name, bundle in bundles.items():
        audit = audit_story_bundle(bundle)
        failures.extend(f"{name}: {issue.code}" for issue in audit.issues if issue.severity == "error")
        issue = _positive_fixture_issue(name, bundle, now) if audit.prompt_ready else None
        if issue:
            eligibility.append(f"{name}: {issue}")
    if failures:
        pytest.fail("canary fixture contract failed before provider calls; repair synthetic inputs:\n" + "\n".join(failures))
    if eligibility:
        pytest.fail(
            "monitor_blocked / fixture_ineligible before provider calls; "
            "provider_reachability=unobserved; response_schema=unobserved; "
            "writer_quality=unknown. Qualify positive source evidence; do not retry invented packets:\n"
            + "\n".join(eligibility)
        )
    return bundles


def _sample_fixture(bundle, fresh_memory_slice, name, outcomes, unsafe):
    """One replay of one fixture. Returns True iff a safety-passing tweet."""
    from src.two_bot.writer import write_tweet

    try:
        result = write_tweet(bundle, fresh_memory_slice)
    except BudgetExhaustedError:
        pytest.fail(f"canary: {name}: provider_budget_exhausted; writer_quality=unknown", pytrace=False)
    except Exception:  # noqa: BLE001 — preserve failure without inventing its cause
        pytest.fail(f"canary: {name}: writer_call_failed; cause=unclassified; writer_quality=unknown", pytrace=False)
    if result.failure_diagnostic is not None:
        pytest.fail(f"canary: {name}: writer_output_invalid; response_schema=failed; writer_quality=unknown", pytrace=False)
    if result.tweet is None:
        outcomes.append(f"{name}: writer_declined; no positive quality observation")
        return False
    try:
        safe, _reason = run_safety_pipeline(result.tweet)
    except Exception:  # noqa: BLE001 — an unavailable required check is never a pass
        pytest.fail(f"canary: {name}: safety_call_failed; cause=unclassified; writer_quality=unknown", pytrace=False)
    if safe is True:
        outcomes.append(f"{name}: produced a safety-passing tweet")
        return True
    unsafe.append(f"{name}: safety_not_passed; positive check incomplete")
    outcomes.append(f"{name}: SAFETY_NOT_PASSED")
    return False


def test_canary_api_reachable_and_writer_produces(request, fresh_memory_slice):
    bundles = _preflight_fixtures(request)
    assert os.environ.get("ANTHROPIC_API_KEY"), (
        "provider_credentials_missing: ANTHROPIC_API_KEY; provider_reachability=unobserved; "
        "writer_quality=unknown"
    )

    unsafe: list[str] = []
    outcomes: list[str] = []
    producing: set[str] = set()
    for name in CANARY_FIXTURES:
        if _sample_fixture(bundles[name], fresh_memory_slice, name, outcomes, unsafe):
            producing.add(name)

    # Only independently qualified packets can reach this legacy bounded
    # positive probe. Known synthetic packets are rejected before all requests.
    if len(producing) < MIN_PRODUCING and not unsafe:
        outcomes.append("-- below threshold; one bounded re-sample of the killers --")
        for name in [n for n in CANARY_FIXTURES if n not in producing]:
            if _sample_fixture(bundles[name], fresh_memory_slice, name, outcomes, unsafe):
                producing.add(name)

    report = "\n".join(outcomes)
    assert not unsafe, (
        "canary: required safety did not pass; no positive quality proof:\n"
        + "\n".join(unsafe)
    )
    assert len(producing) >= MIN_PRODUCING, (
        f"canary: only {len(producing)}/{len(CANARY_FIXTURES)} fixtures "
        f"produced a safety-passing tweet (threshold {MIN_PRODUCING}) across "
        f"two samplings — positive_generation_unproven; cause=unclassified:\n{report}"
    )
