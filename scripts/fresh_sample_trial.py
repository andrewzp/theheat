#!/usr/bin/env python3
"""Prepare an expiring private NWS sample packet; execute only after paid approval.

No production state writes or publishing imports. No paid calls in prepare mode.
Execution uses the existing writer/check pipeline with one-attempt trial limits.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.two_bot.trial_budget import (  # noqa: E402
    MAX_CALLS, MAX_CANDIDATES, MAX_ESTIMATED_USD, MAX_REQUEST_BYTES,
    MODELS, OUTPUT_LIMITS, TrialBudget, trial_scope,
)


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def configure() -> None:
    # Explicit trial-only profile, included in the requested approval. Never
    # write dotenv, repository variables, production state or caller config.
    for name in ("ANTHROPIC_BASE_URL", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GEMINI_BASE_URL"):
        if os.environ.get(name):
            raise ValueError("trial_custom_endpoint_unsupported")
    os.environ.update(THEHEAT_WRITER_SAMPLES="1", THEHEAT_CRITIC_REVISE_ENABLED="0",
                      THEHEAT_CRITIC_ENABLED="1", THEHEAT_WRITER_MODEL=MODELS["writer"][1],
                      THEHEAT_FACT_CHECK_MODEL=MODELS["fact_check"][1],
                      THEHEAT_CRITIC_MODEL=MODELS["critic"][1],
                      GEMINI_SAFETY_MODEL=MODELS["safety"][1])


def binding() -> dict:
    from src.editorial.policy import current_editorial_policy
    policy = current_editorial_policy()
    if policy is None:
        raise ValueError("trial_policy_unavailable")
    expected_models = {stage: model for stage, (_, model) in MODELS.items()}
    expected_models["writer_provider"] = "anthropic"
    if (policy["models"] != expected_models or policy["flags"]["writer_samples"] != 1
            or policy["flags"]["critic_revise_enabled"] is not False
            or policy["flags"]["critic_enabled"] is not True):
        raise ValueError("trial_loaded_profile_mismatch")
    # Credential presence is checked independently, not a prompt/source identity.
    policy = deepcopy(policy)
    policy["flags"].pop("safety_llm_enabled", None)
    return {"policy": policy, "cli_sha256": digest(Path(__file__).read_bytes()),
            "budget_sha256": digest((ROOT / "src/two_bot/trial_budget.py").read_bytes())}


def eligible(bundle: dict, now: datetime) -> bool:
    from src.media.published_radar import interval, source_envelope
    try:
        e = bundle["raw_signal_dump"]["source_evidence"]
        if e != source_envelope(e["feature"], e["captured_at"]):
            return False
        sent = datetime.fromisoformat(e["times"]["sent"]["utc"].replace("Z", "+00:00"))
        _, end = interval(e["times"])
        expires = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (bundle["signal_kind"] == "severe_weather"
                and bundle["event_id"] == "nws_" + e["source_alert_id"]
                and e["source_url"] == "https://api.weather.gov/alerts/active"
                and timedelta(0) <= now - sent <= timedelta(hours=6) and now < expires)
    except (KeyError, TypeError, ValueError):
        return False


def prepare(state_path: Path, output: Path, now: datetime) -> dict:
    from src.data.nws_alerts import fetch_alerts
    from src.editorial.scoring import score_severe_weather
    from src.state import is_duplicate
    from src.two_bot.evidence_contract import audit_story_bundle
    from src.two_bot.intern import build_severe_weather_bundle

    output.mkdir(mode=0o700, exist_ok=False)
    raw_state = state_path.read_bytes()
    if len(raw_state) > 64 * 1024 * 1024:
        raise ValueError("trial_state_size_limit")
    state = json.loads(raw_state)
    if not isinstance(state.get("drafts"), list):
        raise ValueError("trial_state_invalid")
    # One existing NWS acquisition (at most its three free HTTP attempts).
    alerts = fetch_alerts(strict=True)
    alerts.sort(key=lambda a: (-score_severe_weather(a.event_type, a.severity).total, a.event_id))
    bundles: list[dict] = []
    kinds: set[str] = set()
    for alert in alerts:
        if len(bundles) >= MAX_CANDIDATES:
            break
        if (alert.event_type in kinds or is_duplicate(state, alert.event_id)
                or not score_severe_weather(alert.event_type, alert.severity).passes):
            continue
        bundle = build_severe_weather_bundle(alert)
        if not eligible(bundle.to_dict(), now) or not audit_story_bundle(bundle).prompt_ready:
            continue
        kinds.add(alert.event_type)
        bundles.append(bundle.to_dict())
    save(output / "state.json", raw_state)
    save(output / "bundles.json", encoded(bundles))
    plan = {"schema_version": 1, "prepared_at": now.isoformat(), "packet_path": str(output.resolve()),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "candidate_count": len(bundles), "candidate_event_ids": [b["event_id"] for b in bundles],
            "state_sha256": digest(raw_state), "bundles_sha256": digest(encoded(bundles)),
            "binding": binding(), "models": MODELS, "max_candidates": MAX_CANDIDATES,
            "max_paid_calls": MAX_CALLS, "max_request_bytes": MAX_REQUEST_BYTES,
            "output_token_limits": OUTPUT_LIMITS,
            "max_reserved_token_scenario_usd": str(MAX_ESTIMATED_USD),
            "invoice_ceiling_established": False, "pricing_verified_on": "2026-10-15",
            "pricing_sources": ["https://platform.claude.com/docs/en/about-claude/pricing",
                                "https://ai.google.dev/gemini-api/docs/pricing"],
            "limits": ["one paid attempt per candidate/stage", "no refill/revise/publishing/state writes",
                       "byte-per-input-token conservative scenario is not exact token counting",
                       "unknown charges reserved; no automatic restart", "no taxes/other account usage included"]}
    save(output / "plan.json", encoded(plan))
    return {"plan_sha256": digest(encoded(plan)), "candidate_count": len(bundles),
            "expires_at": plan["expires_at"], "paid_calls": 0, "posts": 0}


def validate_packet(output: Path, approved_sha256: str, now: datetime):
    raw = (output / "plan.json").read_bytes()
    if digest(raw) != approved_sha256:
        raise ValueError("trial_approval_packet_mismatch")
    plan = json.loads(raw)
    if str(output.resolve()) != plan["packet_path"]:
        raise ValueError("trial_packet_relocated")
    if not datetime.fromisoformat(plan["prepared_at"]) <= now < datetime.fromisoformat(plan["expires_at"]):
        raise ValueError("trial_approval_expired")
    if plan["binding"] != binding():
        raise ValueError("trial_code_or_policy_changed")
    state_raw, bundle_raw = (output / "state.json").read_bytes(), (output / "bundles.json").read_bytes()
    if digest(state_raw) != plan["state_sha256"] or digest(bundle_raw) != plan["bundles_sha256"]:
        raise ValueError("trial_input_changed")
    bundles = json.loads(bundle_raw)
    if (type(bundles) is not list or not 1 <= len(bundles) <= MAX_CANDIDATES
            or len({b["event_id"] for b in bundles}) != len(bundles)
            or [b["event_id"] for b in bundles] != plan["candidate_event_ids"]
            or not all(eligible(b, now) for b in bundles)):
        raise ValueError("trial_candidates_unavailable_or_stale")
    return json.loads(state_raw), bundles


def claim_execution(output: Path, approved_sha256: str, now: datetime) -> None:
    # Shared across worktrees, so moving/copying a packet cannot replay approval.
    common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"],
                                     cwd=ROOT, text=True, timeout=5).strip()
    shared = (ROOT / common).resolve().parent / ".gstack/fresh-sample-trial-claims"
    shared.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt = encoded({"plan_sha256": approved_sha256, "packet": str(output.resolve()), "at": now.isoformat()})
    save(shared / (approved_sha256 + ".json"), receipt)
    save(output / "execution-started.json", receipt)


def execute(output: Path, approved_sha256: str, now: datetime) -> dict:
    from src.two_bot.pipeline import generate_draft
    from src.two_bot.provider_preflight import current_provider_preflight
    from src.two_bot.types import StoryBundle
    state, bundles = validate_packet(output, approved_sha256, now)
    if current_provider_preflight(critic_enabled=True)["status"] == "blocked":
        raise ValueError("trial_credentials_unavailable")
    # O_EXCL + fsync before any purchase; repeated clicks/restarts cannot resume.
    claim_execution(output, approved_sha256, now)
    with (output / "purchases.jsonl").open("x") as journal, (output / "private-pipeline.log").open("x") as log:
        os.chmod(output / "purchases.jsonl", 0o600)
        os.chmod(output / "private-pipeline.log", 0o600)

        def retain(row):
            journal.write(encoded(row).decode() + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            # Safe receipt survives even if the runner dies before encryption.
            # Never print request/source/history/draft text or credential values.
            print(json.dumps({k: row[k] for k in ("ordinal", "stage", "outcome", "reserved_estimate_usd") if k in row}),
                  file=sys.stderr, flush=True)

        budget = TrialBudget(retain, output / "STOP")
        results = []
        with redirect_stdout(log), trial_scope(budget):
            for value in bundles:
                # Each source is rechecked immediately before its writer purchase.
                if not eligible(value, datetime.now(timezone.utc)):
                    budget.stopped = "trial_source_expired"
                    break
                budget.begin_candidate(value["event_id"])
                detail: dict = {}
                draft = generate_draft(StoryBundle(**value), state, result_out=detail)
                results.append({"event_id": value["event_id"], "draft": draft, "checks": detail})
                save(output / f"candidate-{len(results)}.json", encoded(results[-1]))
                if budget.stopped:
                    break
        from src.two_bot.usage_ledger import drain_into_state
        usage: dict = {}
        drain_into_state(usage)
        save(output / "returned-usage.json", encoded(usage))
        result = {"attempted_candidates": len(results), "drafts_returned": sum(r["draft"] is not None for r in results),
                  "paid_dispatch_reservations": len(budget.calls), "stop_reason": budget.stopped,
                  "reserved_token_scenario_usd": str(budget.estimated_reserved),
                  "actual_cost_known": False, "human_quality_accepted": False, "posts": 0,
                  "production_state_writes": 0}
        save(output / "result.json", encoded(result))
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "execute"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--approved-plan-sha256")
    args = parser.parse_args()
    try:
        configure()
        if args.action == "prepare":
            if args.state is None:
                parser.error("prepare requires --state (private retained snapshot)")
            result = prepare(args.state, args.output, datetime.now(timezone.utc))
        else:
            if not args.approved_plan_sha256:
                parser.error("execute requires separately approved exact plan SHA256")
            result = execute(args.output, args.approved_plan_sha256, datetime.now(timezone.utc))
        print(json.dumps(result))
        return 0
    except Exception as exc:
        # No source text, secret or provider exception body in the public console.
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__, "paid_result_not_assumed": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
