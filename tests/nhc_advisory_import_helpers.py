"""Invented NHC trial proposals, runtime reports and imported states for import, dashboard and journey tests."""
from copy import deepcopy
import json

from scripts import nhc_advisory_import as m, nhc_advisory_trial as trial
from src.editorial.nhc_advisory import validate_capture
from src.state import DEFAULT_STATE
from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle
from tests import nhc_advisory_helpers as h
from tests.nhc_advisory_pipeline_helpers import COPY

TRIAL_ID = "0123456789abcdef0123456789abcdef"
DRAFT_ID = f"nhc_trial_{TRIAL_ID}_{h.STORM.lower()}"
CODE = "a" * 40
SOURCE = "b" * 64
FLAGS = {"THEHEAT_PRODUCTION_PAUSED": "1", "THEHEAT_WRITER_SAMPLES": "1",
         **{k: "0" for k in ("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS",
                             "THEHEAT_CRITIC_REVISE_ENABLED", "THEHEAT_SELFHEAL_REPAIR_ENABLED")}}
INVENTED_POLICY = {"schema_version": 1, "execution_sha256": "c" * 64, "source_sha256": SOURCE,
                   "models": {"critic": "critic-model", "fact_check": "fact-model", "safety": "safety-model",
                              "writer": "writer-model", "writer_provider": "anthropic"},
                   "flags": {"writer_samples": 1, "critic_enabled": True, "critic_revise_enabled": False,
                             "safety_llm_enabled": True}}


def report(captured=h.NOW, code=CODE, policy=None) -> bytes:
    """A configuration-only runtime report as the importer reads it from the Gist."""
    return json.dumps({"schema_version": 1, "kind": "configuration_only", "collection_paused": True,
                       "runtime_inventory": {"mode": "runtime_report", "git_sha": code,
                                             "captured_at": captured.isoformat(),
                                             "editorial_policy": deepcopy(policy or INVENTED_POLICY),
                                             "flags": {"automatic_publication_enabled": False, "writer_samples": 1,
                                                       "critic_enabled": True, "critic_revise_enabled": False},
                                             "credentials_present": {"safety_gemini": True}}}).encode()


def proposal(*, text=COPY, **draft_changes) -> dict:
    """The actual trial proposal shape for the invented advisory (pending, manual-only, unreviewed)."""
    evidence = validate_capture(h.capture(), h.selected(), now=h.NOW)
    bundle = build_nhc_advisory_bundle(evidence).to_dict()
    plan = {"trial_id": TRIAL_ID, "nomination": h.nominated(),
            "operator_recheck_deadline": evidence.deadline.strftime("%Y-%m-%dT%H:%M:%SZ")}
    made = trial.proposal(plan, bundle, text, h.NOW)
    made["plan_sha256"] = "d" * 64
    made["draft"].update(draft_changes)
    return made


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode()


def production_policy() -> dict:
    """This checkout's policy under the deployed profile (one sample, critic on, no revise, safety LLM)."""
    import pytest
    from src.editorial.policy import current_editorial_policy
    with pytest.MonkeyPatch.context() as patch:
        for name, value in (("THEHEAT_WRITER_SAMPLES", "1"), ("THEHEAT_CRITIC_ENABLED", "1"),
                            ("THEHEAT_CRITIC_REVISE_ENABLED", "0")):
            patch.setenv(name, value)
        patch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
        policy = current_editorial_policy()
    assert policy is not None
    return policy


def imported_state(runtime=None):
    """DEFAULT_STATE with the proposal inserted by the actual import plan; no human action recorded."""
    policy = production_policy()
    raw = encode(proposal())
    files = {"state.json": json.dumps(deepcopy(DEFAULT_STATE)).encode(),
             "runtime-inventory.json": report(policy=policy)}
    content, *_ = m.plan(raw, m.sha(raw), files, FLAGS, h.NOW, CODE, policy["source_sha256"])
    state = json.loads(content)
    if runtime is not None:
        row = deepcopy(runtime)
        row["runtime_inventory"]["editorial_policy"] = policy
        state["run_history"] = [row]
    return state, policy
