#!/usr/bin/env python3
"""Prepare an expiring private NHC-advisory sample packet; execute only after paid approval.

One explicitly nominated advisory/candidate, one writer sample and at most four
paid pipeline stage calls under the existing finite trial envelope (unchanged
128 KiB request and stage output bounds, model profile and conservative $2
reservation scenario; not an invoice ceiling). No retries, refills, substitutes,
production-state writes or publishing. Prepare makes no paid call. Each phase has
its own 32-request fixed-source NHC budget and re-reads the current advisory.
The result may contain one pending-only proposal for the separate import operator.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fresh_sample_trial import configure, digest, encoded, retain_candidate_text, save  # noqa: E402
from src.two_bot.trial_budget import (  # noqa: E402
    MAX_ESTIMATED_USD, MAX_REQUEST_BYTES, MODELS, OUTPUT_LIMITS, TrialBudget, TrialStopped, trial_scope,
)

MAX_CANDIDATES = 1
MAX_CALLS = 4
WORKFLOW = ".github/workflows/nhc-advisory-trial.yml"
PROPOSAL_SCHEMA = "theheat.nhc-advisory-pending-proposal/v1"
_TRIAL_ID = re.compile(r"[a-f0-9]{32}")


class NhcTrialBudget(TrialBudget):
    """The existing envelope narrowed to one candidate and four stage calls."""

    def begin_candidate(self, event_id: str) -> None:
        if self.candidates:
            self.stop("trial_candidate_limit")
        super().begin_candidate(event_id)

    def reserve(self, stage: str, provider: str, request: dict) -> dict:
        if len(self.calls) >= MAX_CALLS:
            self.stop("trial_retry_or_call_limit")
        return super().reserve(stage, provider, request)


def binding() -> dict:
    from scripts.fresh_sample_trial import binding as base_binding
    value = base_binding()
    value["cli_sha256"] = digest(Path(__file__).read_bytes())
    value["trial_entry_points"] = {name: digest((ROOT / name).read_bytes()) for name in (
        "scripts/claim_sample_trial.py", "scripts/package_sample_trial.py", "scripts/fresh_sample_trial.py",
        WORKFLOW)}
    value["source_code"] = {name: digest((ROOT / name).read_bytes()) for name in (
        "src/data/nhc_advisory.py", "src/editorial/nhc_advisory.py", "src/editorial/nhc_advisory_runtime.py",
        "src/two_bot/intern/nhc_advisory.py")}
    return value


def _owner(clock):
    from src.editorial.nhc_advisory_runtime import AdvisoryOwner, advisory_owner_scope
    return advisory_owner_scope(AdvisoryOwner(clock=clock))


def _nomination(raw: str):
    from src.orchestrator.sources.nhc_advisory import configured_nomination, NOMINATION_ENV
    return configured_nomination({NOMINATION_ENV: raw})


def prepare(state_path: Path, output: Path, nomination_json: str, trial_id: str, now: datetime) -> dict:
    from src.data.nhc_advisory import current_evidence
    from src.state import is_duplicate
    from src.two_bot.evidence_contract import audit_story_bundle
    from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle

    if not _TRIAL_ID.fullmatch(trial_id or ""):
        raise ValueError("trial_identity_invalid")
    selected = _nomination(nomination_json)
    output.mkdir(mode=0o700, exist_ok=False)
    raw_state = state_path.read_bytes()
    if len(raw_state) > 64 * 1024 * 1024:
        raise ValueError("trial_state_size_limit")
    state = json.loads(raw_state)
    if not isinstance(state.get("drafts"), list):
        raise ValueError("trial_state_invalid")
    with _owner(lambda: now):
        evidence = current_evidence(selected, clock=lambda: now)  # Two fixed free requests.
    bundle = build_nhc_advisory_bundle(evidence)
    retained = {row.get("event_id") for row in state["drafts"] if isinstance(row, dict)}
    eligible = (bundle.event_id not in retained and not is_duplicate(state, bundle.event_id)
                and bundle.event_id not in (state.get("publish_ledger") or {})
                and audit_story_bundle(bundle).prompt_ready)
    bundles = [bundle.to_dict()] if eligible else []
    for name, raw in (("state.json", raw_state), ("bundles.json", encoded(bundles)),
                      ("index.bin", evidence.capture.index_bytes), ("page.bin", evidence.capture.page_bytes)):
        save(output / name, raw)
    deadline = evidence.deadline
    plan = {"schema_version": 1, "source": "nhc_advisory", "trial_id": trial_id, "prepared_at": now.isoformat(),
            "packet_path": str(output.resolve()), "expires_at": min(now + timedelta(hours=1), deadline).isoformat(),
            "nomination": selected.as_dict(), "captured_at": evidence.capture.captured_at,
            "candidate_count": len(bundles), "candidate_event_ids": [b["event_id"] for b in bundles],
            "state_sha256": digest(raw_state), "bundles_sha256": digest(encoded(bundles)),
            "index_sha256": digest(evidence.capture.index_bytes), "page_sha256": digest(evidence.capture.page_bytes),
            "binding": binding(), "models": MODELS, "max_candidates": MAX_CANDIDATES, "max_paid_calls": MAX_CALLS,
            "max_request_bytes": MAX_REQUEST_BYTES, "output_token_limits": OUTPUT_LIMITS,
            "max_reserved_token_scenario_usd": str(MAX_ESTIMATED_USD), "nhc_requests_per_phase": 32,
            "invoice_ceiling_established": False, "upstream_expiry": "not_supplied_by_source",
            "operator_recheck_deadline": deadline.isoformat(),
            "limits": ["one writer sample; at most four paid stage calls; no retry/refill/substitute/revise",
                       "no production state write, review, approval, intent or publication",
                       "byte-per-input-token conservative scenario is not exact token counting",
                       "unknown charges reserved; no automatic restart; no taxes/other account usage included",
                       "operator recheck deadline is not an NHC expiry"]}
    save(output / "plan.json", encoded(plan))
    return {"plan_sha256": digest(encoded(plan)), "candidate_count": len(bundles), "expires_at": plan["expires_at"],
            "paid_calls": 0, "posts": 0}


def validate_packet(output: Path, approved_sha256: str, now: datetime):
    from src.editorial.nhc_advisory import AdvisoryCapture, validate_capture
    from src.two_bot.bundle_capture import capture_bundle
    from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle
    from src.two_bot.types import StoryBundle
    raw = (output / "plan.json").read_bytes()
    if digest(raw) != approved_sha256:
        raise ValueError("trial_approval_packet_mismatch")
    plan = json.loads(raw)
    if str(output.resolve()) != plan["packet_path"] or plan.get("source") != "nhc_advisory":
        raise ValueError("trial_packet_relocated")
    if not datetime.fromisoformat(plan["prepared_at"]) <= now < datetime.fromisoformat(plan["expires_at"]):
        raise ValueError("trial_approval_expired")
    if plan["binding"] != binding():
        raise ValueError("trial_code_or_policy_changed")
    files = {name: (output / name).read_bytes() for name in ("state.json", "bundles.json", "index.bin", "page.bin")}
    if any(digest(files[name]) != plan[key] for name, key in (
            ("state.json", "state_sha256"), ("bundles.json", "bundles_sha256"),
            ("index.bin", "index_sha256"), ("page.bin", "page_sha256"))):
        raise ValueError("trial_input_changed")
    bundles = json.loads(files["bundles.json"])
    selected = _nomination(json.dumps(plan["nomination"]))
    capture = AdvisoryCapture(files["index.bin"], files["page.bin"], plan["captured_at"])
    rebuilt = build_nhc_advisory_bundle(validate_capture(capture, selected, now=now))
    if (type(bundles) is not list or len(bundles) != MAX_CANDIDATES
            or [b["event_id"] for b in bundles] != plan["candidate_event_ids"]
            or capture_bundle(StoryBundle(**bundles[0])) != capture_bundle(rebuilt)):
        raise ValueError("trial_candidates_unavailable_or_stale")
    return json.loads(files["state.json"]), bundles, plan


def claim_execution(output: Path, approved_sha256: str, now: datetime) -> None:
    from scripts.fresh_sample_trial import claim_execution as claim
    claim(output, approved_sha256, now)


def proposal(plan: dict, bundle: dict, text: str, now: datetime) -> dict:
    """A pending, manual-only, unreviewed draft proposal; it grants no authority."""
    from dataclasses import asdict
    from src.editorial.approval import recommend_approval_policy
    from src.orchestrator.sources.nhc_advisory import NOMINATION_SCORE
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    policy = recommend_approval_policy("nhc_advisory", signal_total=NOMINATION_SCORE.total, candidate_score=None)
    draft = {"id": f"nhc_trial_{plan['trial_id']}_{plan['nomination']['storm_id'].lower()}",
             "text": text, "type": "nhc_advisory", "event_id": bundle["event_id"], "created_at": stamp,
             "updated_at": stamp, "status": "pending", "score": NOMINATION_SCORE.as_dict(),
             "approval_policy": asdict(policy), "approval_mode": "manual", "content_revision": 1,
             "decision_revision": 0, "manual_override": False,
             "review_context": {"two_bot": {"bundle": deepcopy(bundle), "signal_kind": "nhc_advisory"}}}
    return {"schema": PROPOSAL_SCHEMA, "applied": False, "trial_id": plan["trial_id"], "plan_sha256": None,
            "operator_recheck_deadline": plan["operator_recheck_deadline"], "draft": draft,
            "checks": "required pipeline checks passed in the trial; the sender reruns final safety and source checks",
            "human_reviewed": False, "approved": False}


def execute(output: Path, approved_sha256: str, now: datetime) -> dict:
    from src.editorial.nhc_advisory_runtime import guard_advisory_story
    from src.two_bot.pipeline import generate_draft
    from src.two_bot.provider_preflight import current_provider_preflight
    from src.two_bot.types import StoryBundle
    state, bundles, plan = validate_packet(output, approved_sha256, now)
    if current_provider_preflight(critic_enabled=True)["status"] == "blocked":
        raise ValueError("trial_credentials_unavailable")
    clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    with _owner(clock):
        # A changed/superseded/expired source refuses before the durable claim.
        guard_advisory_story(StoryBundle(**bundles[0]), generating=False, live=True)
        claim_execution(output, approved_sha256, now)
        with (output / "purchases.jsonl").open("x") as journal, (output / "private-pipeline.log").open("x") as log:
            os.chmod(output / "purchases.jsonl", 0o600)
            os.chmod(output / "private-pipeline.log", 0o600)

            def retain(row):
                journal.write(encoded(row).decode() + "\n")
                journal.flush()
                os.fsync(journal.fileno())
                print(json.dumps({k: row[k] for k in ("ordinal", "stage", "outcome", "reserved_estimate_usd")
                                  if k in row}), file=sys.stderr, flush=True)

            budget = NhcTrialBudget(retain, output / "STOP")
            value = bundles[0]
            detail: dict = {}
            with redirect_stdout(log), trial_scope(budget):
                budget.begin_candidate(value["event_id"])

                def observe(text: str, attempt: int) -> None:
                    try:
                        retain_candidate_text(output, value, 1, text, attempt)
                    except Exception:
                        budget.stopped = "trial_candidate_capture_failed"
                        raise RuntimeError("trial_candidate_capture_failed") from None
                try:
                    draft = generate_draft(StoryBundle(**value), state, result_out=detail, candidate_observer=observe)
                except TrialStopped:
                    draft = None
            save(output / "candidate-1.json", encoded({"event_id": value["event_id"], "draft": draft,
                                                        "checks": detail}))
    from src.two_bot.usage_ledger import drain_into_state
    usage: dict = {}
    drain_into_state(usage)
    save(output / "returned-usage.json", encoded(usage))
    if draft is not None:
        made = proposal(plan, value, draft["text"], datetime.now(timezone.utc))
        made["plan_sha256"] = approved_sha256
        save(output / "pending-proposal.json", encoded(made))
    result = {"attempted_candidates": 1, "drafts_returned": int(draft is not None),
              "paid_dispatch_reservations": len(budget.calls), "stop_reason": budget.stopped,
              "reserved_token_scenario_usd": str(budget.estimated_reserved), "actual_cost_known": False,
              "human_quality_accepted": False, "posts": 0, "production_state_writes": 0,
              "pending_proposal": draft is not None}
    save(output / "result.json", encoded(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "execute"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--trial-id")
    parser.add_argument("--approved-plan-sha256")
    args = parser.parse_args()
    try:
        configure()
        if args.action == "prepare":
            nomination_json = os.environ.get("NHC_ADVISORY_NOMINATION", "")
            if args.state is None or not args.trial_id:
                parser.error("prepare requires --state and --trial-id")
            result = prepare(args.state, args.output, nomination_json, args.trial_id, datetime.now(timezone.utc))
        else:
            if not args.approved_plan_sha256:
                parser.error("execute requires separately approved exact plan SHA256")
            result = execute(args.output, args.approved_plan_sha256, datetime.now(timezone.utc))
        print(json.dumps(result))
        return 0
    except Exception as exc:
        # No source text, secret, provider exception body or hold detail in the console.
        code = getattr(exc, "code", None) or (str(exc) if type(exc) is ValueError else None)
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__,
                          "reason": code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code) else None,
                          "paid_result_not_assumed": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
