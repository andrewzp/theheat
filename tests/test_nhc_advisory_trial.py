"""Finite NHC-advisory trial: prepare (free) and execute (four reserved calls) offline."""
from datetime import timedelta
import json
from pathlib import Path
import stat

import pytest
import yaml

from scripts import claim_sample_trial, nhc_advisory_trial as trial
from src.data import nhc_advisory as source
from src.two_bot import pipeline, provider_preflight, trial_budget
from src.two_bot.trial_budget import MODELS, TrialStopped
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests import nhc_advisory_helpers as h
from tests.nhc_advisory_pipeline_helpers import COPY, Transport

ROOT = Path(__file__).resolve().parents[1]
TRIAL_ID = "0123456789abcdef0123456789abcdef"
REQUESTS = {"writer": ("anthropic", {"messages": [{"role": "user", "content": "invented"}], "max_tokens": 1024}),
            "safety": ("google", {"contents": "invented", "config": {}}),
            "fact_check": ("google", {"contents": "invented", "config": {}}),
            "critic": ("google", {"contents": "invented", "config": {}})}


@pytest.fixture
def env(monkeypatch, tmp_path):
    transport = Transport()
    monkeypatch.setattr(source, "_http_get", transport)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "invented-no-provider-access")
    monkeypatch.setenv("GEMINI_API_KEY", "invented-no-provider-access")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
    monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    for name in ("ANTHROPIC_BASE_URL", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GEMINI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    # The trial-only profile configure() applies, set reversibly for this test.
    for name, value in (("THEHEAT_WRITER_SAMPLES", "1"), ("THEHEAT_CRITIC_REVISE_ENABLED", "0"),
                        ("THEHEAT_CRITIC_ENABLED", "1"), ("THEHEAT_WRITER_MODEL", MODELS["writer"][1]),
                        ("THEHEAT_FACT_CHECK_MODEL", MODELS["fact_check"][1]),
                        ("THEHEAT_CRITIC_MODEL", MODELS["critic"][1]), ("GEMINI_SAFETY_MODEL", MODELS["safety"][1])):
        monkeypatch.setenv(name, value)
    from src.two_bot import critic, fact_check, writer
    from src.voice import safety
    for module, attr, stage in ((writer, "WRITER_MODEL", "writer"), (fact_check, "FACT_CHECKER_MODEL", "fact_check"),
                                (critic, "CRITIC_MODEL", "critic"), (safety, "GEMINI_SAFETY_MODEL", "safety")):
        monkeypatch.setattr(module, attr, MODELS[stage][1])
    common = tmp_path / "git-common"
    common.mkdir()
    import scripts.fresh_sample_trial as nws
    monkeypatch.setattr(nws.subprocess, "check_output", lambda *a, **k: str(common / ".git"))
    (common / ".git").mkdir()
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"drafts": [], "posted_events": [], "publish_ledger": {}}))
    return {"transport": transport, "state": state, "out": tmp_path / "packet", "common": common}


def prepare(env, now=h.NOW, nomination=None):
    return trial.prepare(env["state"], env["out"], json.dumps(nomination or h.nominated()), TRIAL_ID, now)


def fakes(monkeypatch, sent, *, failures=None, on_stage=None):
    failures = failures or {}

    def via(stage, result):
        provider, request = REQUESTS[stage]

        def send(**bounded):
            sent.append(stage)
            if failures.get(stage):
                raise TimeoutError("invented lost response")
            return object()

        def run(*args, **kwargs):
            if on_stage is not None:
                on_stage(stage)
            trial_budget.provider_call(stage, provider, {"model": MODELS[stage][1], **request}, send)
            return result
        return run
    monkeypatch.setattr(pipeline.writer, "write_tweet", via("writer", WriterResult(
        COPY, None, "warning_consequence", None, None, "Explicit invented offline model response.")))
    monkeypatch.setattr(pipeline, "run_safety_pipeline", via("safety", (True, None)))
    monkeypatch.setattr(pipeline.fact_check, "fact_check", via("fact_check", FactCheckResult(True, [], "Offline.")))
    monkeypatch.setattr(pipeline.critic, "critic_review", via("critic", CriticResult(True, None, "Offline.")))
    monkeypatch.setattr(provider_preflight, "current_provider_preflight", lambda **k: {"status": "configured"})


def test_prepare_is_free_bounded_and_never_mutates_state(env):
    before = env["state"].read_bytes()
    result = prepare(env)
    assert result["candidate_count"] == 1 and result["paid_calls"] == 0 and result["posts"] == 0
    assert env["transport"].calls == [source.INDEX_URL, h.URL] and env["state"].read_bytes() == before
    plan = json.loads((env["out"] / "plan.json").read_text())
    assert (plan["max_candidates"], plan["max_paid_calls"], plan["max_request_bytes"]) == (1, 4, 128 * 1024)
    assert plan["max_reserved_token_scenario_usd"] == "2" and plan["invoice_ceiling_established"] is False
    assert plan["upstream_expiry"] == "not_supplied_by_source" and plan["nhc_requests_per_phase"] == 32
    assert plan["expires_at"] <= plan["operator_recheck_deadline"]
    assert (env["out"] / "page.bin").read_bytes() == h.page()  # Exact original HTTP bytes retained privately.
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in env["out"].iterdir())


def test_retained_or_published_event_prepares_zero_candidates(env):
    from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle  # noqa: F401
    env["state"].write_text(json.dumps({"drafts": [{"event_id": "nhc_advisory:ep492026:34:rainfall"}]}))
    assert prepare(env)["candidate_count"] == 0


@pytest.mark.parametrize("trial_id", ["", "ABC", "0" * 31, "g" * 32])
def test_trial_identity_is_exact(env, trial_id):
    with pytest.raises(ValueError, match="trial_identity_invalid"):
        trial.prepare(env["state"], env["out"], json.dumps(h.nominated()), trial_id, h.NOW)


def test_execute_reserves_four_calls_and_emits_only_a_pending_proposal(env, monkeypatch):
    sha = prepare(env)["plan_sha256"]
    sent: list = []
    fakes(monkeypatch, sent)
    monkeypatch.setattr(trial, "datetime", _Clock(h.NOW + timedelta(minutes=1)))
    result = trial.execute(env["out"], sha, h.NOW + timedelta(minutes=1))
    assert sent == ["writer", "safety", "fact_check", "critic"]
    assert result["paid_dispatch_reservations"] == 4 and result["pending_proposal"] is True
    assert result["posts"] == 0 and result["production_state_writes"] == 0 and result["actual_cost_known"] is False
    rows = [json.loads(line) for line in (env["out"] / "purchases.jsonl").read_text().splitlines()]
    assert [r["outcome"] for r in rows if "stage" in r][:2] == ["reserved_before_dispatch", "response_returned"]
    made = json.loads((env["out"] / "pending-proposal.json").read_text())
    draft = made["draft"]
    assert (made["applied"], made["human_reviewed"], made["approved"]) == (False, False, False)
    assert (draft["status"], draft["approval_mode"], draft["approval_policy"]["mode"]) == ("pending", "manual",
                                                                                          "manual_only")
    assert "review_binding" not in draft and "approval_binding" not in draft and "publish_intent_id" not in draft
    assert set(draft["review_context"]) == {"two_bot"} and draft["id"] == f"nhc_trial_{TRIAL_ID}_ep492026"
    from src.editorial.nhc_advisory_runtime import AdvisoryOwner, advisory_owner_scope, current_advisory_source
    with advisory_owner_scope(AdvisoryOwner(clock=lambda: h.NOW + timedelta(minutes=2))):
        assert current_advisory_source(draft, live=False) is None  # Retained, current, attributed copy.
    # Pre-claim read + two guards per reserved call (before reservation and before dispatch).
    assert len(env["transport"].calls) == 2 + 2 + 4 * 2 * 2


def _Clock(now):
    """The script's datetime with an invented fixed now (fromisoformat etc. unchanged)."""
    from datetime import datetime

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    return Fixed


def test_a_transient_failure_is_never_retried_or_refilled(env, monkeypatch):
    sha = prepare(env)["plan_sha256"]
    sent: list = []
    fakes(monkeypatch, sent, failures={"writer": True})
    monkeypatch.setattr(trial, "datetime", _Clock(h.NOW + timedelta(minutes=1)))
    result = trial.execute(env["out"], sha, h.NOW + timedelta(minutes=1))
    assert sent == ["writer"] and result["stop_reason"] == "trial_provider_outcome_unknown"
    assert result["pending_proposal"] is False and not (env["out"] / "pending-proposal.json").exists()


def test_a_correction_mid_trial_buys_nothing_more(env, monkeypatch):
    sha = prepare(env)["plan_sha256"]
    sent: list = []

    def on_stage(stage):
        if stage == "safety":
            env["transport"].responses[h.URL] = (200, {}, h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4"))))
    fakes(monkeypatch, sent, on_stage=on_stage)
    monkeypatch.setattr(trial, "datetime", _Clock(h.NOW + timedelta(minutes=1)))
    result = trial.execute(env["out"], sha, h.NOW + timedelta(minutes=1))
    assert sent == ["writer"] and result["pending_proposal"] is False


def test_budget_refuses_a_second_candidate_and_a_fifth_call(tmp_path):
    budget = trial.NhcTrialBudget(lambda row: None, tmp_path / "STOP")
    budget.begin_candidate("one")
    with pytest.raises(TrialStopped, match="trial_candidate_limit"):
        budget.begin_candidate("two")
    budget = trial.NhcTrialBudget(lambda row: None, tmp_path / "STOP")
    budget.begin_candidate("one")
    budget.calls = [{"candidate": "one", "stage": s} for s in ("writer", "safety", "fact_check", "critic")]
    with pytest.raises(TrialStopped, match="trial_retry_or_call_limit"):
        budget.reserve("writer", "anthropic", {"model": MODELS["writer"][1], "messages": []})


@pytest.mark.parametrize("case,reason", [
    ("approval", "trial_approval_packet_mismatch"), ("relocated", "trial_packet_relocated"),
    ("expired", "trial_approval_expired"), ("binding", "trial_code_or_policy_changed"),
    ("page", "trial_input_changed"), ("bundles", "trial_input_changed"),
    ("stale-source", "nhc_advisory_superseded")])
def test_packet_tamper_expiry_and_stale_source_refuse_before_the_claim(env, monkeypatch, case, reason):
    sha = prepare(env)["plan_sha256"]
    now = h.NOW + timedelta(minutes=1)
    if case == "approval":
        sha = "0" * 64
    elif case == "relocated":
        env["out"].rename(env["out"].with_name("moved"))
        env["out"] = env["out"].with_name("moved")
    elif case == "expired":
        now = h.NOW + timedelta(minutes=30)
    elif case == "binding":
        monkeypatch.setattr(trial, "binding", lambda: {"changed": True})
    elif case == "page":
        path = env["out"] / "page.bin"
        path.chmod(0o600)
        path.write_bytes(h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4"))))
    elif case == "bundles":
        (env["out"] / "bundles.json").write_bytes(b"[]")
    elif case == "stale-source":
        env["transport"].responses[source.INDEX_URL] = (200, {}, h.index(advisory="35"))
    fakes(monkeypatch, [])
    monkeypatch.setattr(trial, "datetime", _Clock(now))
    with pytest.raises(ValueError) as refused:  # AdvisoryHold is a ValueError subclass too.
        trial.execute(env["out"], sha, now)
    assert getattr(refused.value, "code", str(refused.value)) == reason
    assert not (env["out"] / "execution-started.json").exists() and not (env["out"] / "purchases.jsonl").exists()
    assert not (env["common"] / ".gstack").exists()  # No shared claim was consumed.


def test_a_claimed_packet_cannot_be_executed_again(env, monkeypatch):
    sha = prepare(env)["plan_sha256"]
    fakes(monkeypatch, [])
    monkeypatch.setattr(trial, "datetime", _Clock(h.NOW + timedelta(minutes=1)))
    trial.execute(env["out"], sha, h.NOW + timedelta(minutes=1))
    with pytest.raises(FileExistsError):
        trial.execute(env["out"], sha, h.NOW + timedelta(minutes=2))


def test_workflow_is_flag_off_one_shot_encrypted_and_never_publishes():
    wf = yaml.load((ROOT / ".github/workflows/nhc-advisory-trial.yml").read_text(), Loader=yaml.BaseLoader)
    assert list(wf["on"]) == ["workflow_dispatch"] and wf["permissions"] == {"contents": "read", "actions": "read"}
    job = wf["jobs"]["trial"]
    condition = " ".join(job["if"].split())
    for part in ("github.run_attempt == 1", "vars.THEHEAT_PRODUCTION_PAUSED == '1'",
                 "vars.THEHEAT_NHC_ADVISORY_TRIAL_ENABLED == '1'",
                 "inputs.approval == 'APPROVE-2-USD-NHC-ADVISORY-TRIAL'"):
        assert part in condition
    steps = job["steps"]
    claim = next(i for i, s in enumerate(steps) if "claim_sample_trial.py" in s.get("run", ""))
    paid = next(i for i, s in enumerate(steps) if "ANTHROPIC_API_KEY" in s.get("env", {}))
    assert claim < paid and steps[claim]["env"]["TRIAL_WORKFLOW"] == "nhc-advisory-trial.yml"
    prepare_step = next(s for s in steps if "nhc_advisory_trial.py prepare" in s.get("run", ""))
    assert prepare_step["env"]["NHC_ADVISORY_NOMINATION"] == "${{ inputs.nomination }}"
    assert "inputs.nomination" not in prepare_step["run"]  # Never shell-interpolated.
    assert steps[-1]["with"]["path"] == "${{ runner.temp }}/sample-trial.cms"
    assert steps[-2]["run"] == "python scripts/package_sample_trial.py"
    text = (ROOT / ".github/workflows/nhc-advisory-trial.yml").read_text()
    for forbidden in ("src.main", "manual_tweet", "bot.yml", "gh variable set", "gh gist edit", "schedule:"):
        assert forbidden not in text


@pytest.mark.parametrize("workflow,title", [("fresh-sample-trial.yml", "Fresh sample "),
                                            ("nhc-advisory-trial.yml", "NHC advisory sample ")])
def test_claim_is_per_workflow_first_id_only(workflow, title):
    env = {"TRIAL_ID": TRIAL_ID, "GITHUB_RUN_ATTEMPT": "1", "APPROVED_COMMIT_SHA": "a" * 40, "GITHUB_SHA": "a" * 40,
           "GITHUB_REPOSITORY": "invented/repo", "GITHUB_RUN_ID": "7"}
    seen = []

    def api(path):
        seen.append(path)
        return {"total_count": 1, "workflow_runs": [{"id": 7, "display_title": title + TRIAL_ID}]}
    claim_sample_trial.claim(env, api, workflow=workflow)
    assert f"/workflows/{workflow}/runs" in seen[0]
    with pytest.raises(ValueError, match="already_claimed"):
        claim_sample_trial.claim({**env, "GITHUB_RUN_ID": "8"}, api, workflow=workflow)
    with pytest.raises(ValueError, match="workflow_unsupported"):
        claim_sample_trial.claim(env, api, workflow="bot.yml")
