"""Offline operating-report evidence controls; no model quality assertions."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import socket
import subprocess

import pytest
import yaml

from scripts import writer_health as cli
from src import writer_health as health
from src.editorial.revisions import fingerprint, record_model_review, text_hash
from src.two_bot.usage_observations import observe_response
from tests.test_usage_observations import anthropic_response, google_response, window

NOW = datetime(2026, 10, 1, 18, tzinfo=UTC)
SHA = "a" * 64
PRIVATE = "PRIVATE_SOURCE_REASON_DRAFT_CONTENT_DO_NOT_PRINT"


def stamp(ago=0):
    return (NOW - timedelta(hours=ago)).isoformat().replace("+00:00", "Z")


def policy():
    return {
        "schema_version": 1,
        "source_sha256": SHA,
        "execution_sha256": "b" * 64,
        "models": {
            "writer": "claude-fixture",
            "writer_provider": "anthropic",
            "fact_check": "gemini-fixture",
            "critic": "gemini-fixture",
            "safety": "gemini-fixture",
        },
        "flags": {
            "critic_enabled": True,
            "critic_revise_enabled": False,
            "writer_samples": 1,
            "safety_llm_enabled": True,
        },
    }


def run(identifier="run-test", *, age=1, mode="alerts"):
    p = policy()
    return {
        "id": identifier,
        "mode": mode,
        "status": "success",
        "started_at": stamp(age + 1),
        "ended_at": stamp(age),
        "runtime_inventory": {
            "schema_version": 1,
            "mode": mode,
            "captured_at": stamp(age + 1),
            "models": deepcopy(p["models"]),
            "flags": deepcopy(p["flags"]),
            "editorial_policy": p,
            "credentials_present": {"anthropic": True, "gemini": True, "safety_gemini": True},
        },
    }


def response(*, number=1, age=1.5, provider="anthropic", model="claude-fixture", stage="writer"):
    raw = anthropic_response() if provider == "anthropic" else google_response()
    row = observe_response(stage, raw, model, provider)
    row.update(
        id=f"{number:032x}",
        observed_at=(NOW - timedelta(hours=age))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
    )
    return row


def draft(identifier="draft-test", *, age=1):
    p = policy()
    d = {
        "id": identifier,
        "created_at": stamp(age),
        "text": PRIVATE,
        "type": "offline_control",
        "event_id": "private-event-identity",
        "content_revision": 1,
        "review_context": {
            "two_bot": {
                "bundle": {"control": PRIVATE},
                "fact_check": {"passed": True},
                "critic": {"passed": True},
                "reviewed_policy_sha256": fingerprint(p),
                "reviewed_text_sha256": text_hash(PRIVATE),
                "reviewed_bundle_sha256": fingerprint({"control": PRIVATE}),
            }
        },
    }
    record_model_review(d, policy=p)
    return d


def state():
    return {
        "run_history": [run()],
        "drafts": [draft()],
        "llm_usage_observations": window(response()),
        "suppressions": [],
    }


def summarize(value, **kwargs):
    return health.summarize_writer_health(
        value, now=kwargs.get("now", NOW), current_source_sha256=kwargs.get("sha", SHA)
    )


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*a, **k):
        pytest.fail("Operating evidence reader must make no network/provider/process call")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def test_actual_sdk_response_and_bound_offline_review_remain_separate_and_private():
    value = state()
    before = json.dumps(value, sort_keys=True)
    report = summarize(value)
    assert report["runtime"]["status"] == "recent"
    assert report["provider_response"]["status"] == "recent_response"
    assert report["provider_response"]["response_to_run_or_draft_join"] == "unavailable"
    assert report["saved_output"]["bound_model_reviews"] == 1
    assert report["required_check_receipts"] == "incomplete"
    assert report["source_truth"] == "not_independently_certified"
    assert report["editorial_quality"] == "not_evaluated"
    assert report["accounting_complete"] is False and report["all_in_cost_usd"] is None
    encoded = json.dumps(report)
    assert len(encoded) < 12000 and "healthy" not in encoded
    assert all(
        s not in encoded
        for s in (
            PRIVATE,
            "run-test",
            "draft-test",
            "private-event-identity",
            "msg-fixture",
            "DO_NOT_CAPTURE",
        )
    )
    assert json.dumps(value, sort_keys=True) == before


def test_green_workflow_credentials_and_draft_counts_cannot_invent_a_response():
    value = state()
    value.pop("llm_usage_observations")
    value["run_history"][0]["drafted_count"] = 999
    report = summarize(value)
    assert report["provider_response"]["status"] == "unobserved"
    assert report["runtime"]["credential_validity"] == "unverified"


@pytest.mark.parametrize(
    "field,value",
    [("stage", "critic"), ("requested_model", "another-model"), ("provider", "google")],
)
def test_other_role_or_model_responses_cannot_certify_the_writer(field, value):
    row = response(**{field if field != "requested_model" else "model": value})
    data = state()
    data["llm_usage_observations"] = window(row)
    assert summarize(data)["provider_response"]["status"] == "unobserved"


@pytest.mark.parametrize(
    "age,expected", [(26, "recent_response"), (26.001, "stale"), (-0.001, "unobserved")]
)
def test_response_clock_boundaries(age, expected):
    value = state()
    value["llm_usage_observations"] = window(response(age=age))
    assert summarize(value)["provider_response"]["status"] == expected


@pytest.mark.parametrize("status", ["absent", "invalid"])
def test_missing_usage_does_not_erase_a_returned_response_or_invent_zero_cost(status):
    value = state()
    row = response()
    row["usage_status"] = status
    value["llm_usage_observations"] = window(row)
    result = summarize(value)
    assert result["provider_response"]["status"] == "recent_response"
    assert result["provider_response"]["missing_or_invalid_usage_responses"] == 1
    assert result["all_in_cost_usd"] is None


def test_unpriced_google_response_is_observed_without_a_price_claim():
    value = state()
    inventory = value["run_history"][0]["runtime_inventory"]
    inventory["models"].update(writer_provider="google", writer="gemini-fixture")
    value["llm_usage_observations"] = window(response(provider="google", model="gemini-fixture"))
    report = summarize(value)
    assert report["provider_response"]["status"] == "recent_response"
    assert (
        report["all_in_cost_usd"] is None
        and not report["recorded_runtime_policy_matches_current_source"]
    )


@pytest.mark.parametrize(
    "value,blocked,unknown",
    [(False, True, False), (None, False, True), (0, False, True), ("yes", False, True)],
)
def test_credential_presence_has_strict_types_and_never_means_access(value, blocked, unknown):
    data = state()
    data["run_history"][0]["runtime_inventory"]["credentials_present"]["anthropic"] = value
    result = summarize(data)["runtime"]
    assert ("writer" in result["credential_presence_blocked_stages"]) == blocked
    assert ("writer" in result["credential_presence_unknown_stages"]) == unknown
    assert result["credential_validity"] == "unverified"


def test_auto_publish_heartbeat_cannot_hide_a_stale_writer_invocation():
    value = state()
    value["run_history"] = [run("hourly", age=0, mode="auto_publish_due"), run(age=28)]
    report = summarize(value)
    assert report["runtime"]["status"] == "stale"
    assert report["provider_response"]["status"] == "configuration_stale"
    assert report["saved_output"]["bound_model_reviews"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "missing_inventory",
        "future",
        "naive",
        "wrong_mode",
        "bad_schema",
        "end_before_start",
        "bad_mode_type",
        "bad_status_type",
    ],
)
def test_bad_latest_run_cannot_fall_back_to_an_older_positive_configuration(change):
    value = state()
    row = run("latest", age=0)
    value["run_history"].insert(0, row)
    if change == "missing_inventory":
        row.pop("runtime_inventory")
    elif change == "future":
        row["ended_at"] = stamp(-1)
    elif change == "naive":
        row["runtime_inventory"]["captured_at"] = "2026-10-01T17:00:00"
    elif change == "wrong_mode":
        row["runtime_inventory"]["mode"] = "auto_publish_due"
    elif change == "bad_schema":
        row["runtime_inventory"]["schema_version"] = True
    elif change == "end_before_start":
        row["ended_at"] = stamp(3)
    elif change == "bad_mode_type":
        row["mode"] = []
    else:
        row["status"] = {}
    result = summarize(value)
    assert result["runtime"]["status"] == "unobserved"
    assert result["saved_output"]["bound_model_reviews"] == 0


@pytest.mark.parametrize("section", ["run_history", "drafts", "suppressions"])
def test_malformed_containers_are_visible(section):
    value = state()
    value[section] = PRIVATE
    report = summarize(value)
    assert any(k.endswith("invalid_container") for k in report["unavailable_context"])
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize(
    "section,limit", [("run_history", 20), ("drafts", 1024), ("suppressions", 100)]
)
def test_bounded_rows_mark_loss(section, limit):
    value = state()
    value[section] = [{"id": f"row-{i}"} for i in range(limit + 1)]
    report = summarize(value)
    assert any(k.endswith("truncated_rows") for k in report["unavailable_context"])


def test_exact_duplicates_deduplicate_and_competing_run_ids_never_choose_a_winner():
    value = state()
    value["run_history"] *= 2
    value["drafts"] *= 2
    assert summarize(value)["saved_output"]["recent_saved_outputs"] == 1
    value["run_history"][1] = deepcopy(value["run_history"][1])
    value["run_history"][1]["status"] = "failed"
    report = summarize(value)
    assert report["runtime"]["status"] == "unobserved"
    assert report["unavailable_context"]["runs_conflicting_ids"] == 1


def test_response_conflicts_and_retention_uncertainty_survive_reporting():
    value = state()
    one = response()
    two = deepcopy(one)
    two["resolved_model"] = "different"
    value["llm_usage_observations"] = window(one, two, truncated=True)
    report = summarize(value)["provider_response"]
    assert report["status"] == "conflicted_or_unobserved" and report["conflicting_ids"] == 1
    assert report["window_truncated"]


@pytest.mark.parametrize(
    "change",
    ["text", "bundle", "policy", "source", "runtime_model", "runtime_flag", "review_time_only"],
)
def test_saved_output_is_not_a_current_review_after_identity_changes(change):
    value = state()
    d = value["drafts"][0]
    if change == "text":
        d["text"] += " edited"
    elif change == "bundle":
        d["review_context"]["two_bot"]["bundle"]["control"] = "changed"
    elif change == "policy":
        d["review_binding"]["editorial_policy"]["source_sha256"] = "f" * 64
    elif change == "source":
        pass
    elif change == "runtime_model":
        value["run_history"][0]["runtime_inventory"]["models"]["writer"] = "changed-model"
    elif change == "runtime_flag":
        value["run_history"][0]["runtime_inventory"]["flags"]["writer_samples"] = 3
    else:
        d["created_at"] = stamp(27)
        d["review_binding"]["reviewed_at"] = stamp(0)
    report = summarize(value, sha="c" * 64 if change == "source" else SHA)
    assert report["saved_output"]["bound_model_reviews"] == 0
    assert report["required_check_receipts"] == "incomplete"


STAGE_CODES = [(k, v) for k, v in health.STAGES.items()] + [
    ("writer", "writer_declined_origin_unknown"),
    ("fact_check", "factual_rejection_origin_unknown"),
]


@pytest.mark.parametrize("stage,code", STAGE_CODES)
def test_joined_dispositions_keep_typed_causes_and_do_not_erase_responses(stage, code):
    value = state()
    value["suppressions"] = [
        {
            "id": "supp-private",
            "run_id": "run-test",
            "ts": stamp(1.5),
            "stage": stage,
            "reasons": [PRIVATE + " credit balance is too low"],
            "event_id": PRIVATE,
        }
    ]
    report = summarize(value)
    assert report["recorded_dispositions"][code]["count"] == 1
    assert report["provider_response"]["status"] == "recent_response"
    assert PRIVATE not in json.dumps(report)
    if stage != "budget_exhausted":
        assert "recorded_budget_exception" not in report["recorded_dispositions"]


@pytest.mark.parametrize(
    "path,code",
    [
        ("local_precheck", "local_factual_rejection"),
        ("required_checker", "required_checker_rejection"),
    ],
)
def test_checker_path_is_not_a_provider_receipt(path, code):
    value = state()
    value.pop("llm_usage_observations")
    value["suppressions"] = [
        {
            "id": "supp",
            "run_id": "run-test",
            "ts": stamp(1.5),
            "stage": "fact_check",
            "model_diagnostics": [{"stage": "fact_check", "raw_response": PRIVATE}],
            "rejected_candidate": {"verdict": {"check_path": path}},
        }
    ]
    report = summarize(value)
    assert (
        code in report["recorded_dispositions"]
        and report["provider_response"]["status"] == "unobserved"
    )


def test_writer_schema_rejection_is_not_a_clean_refusal():
    value = state()
    value["suppressions"] = [
        {
            "id": "supp",
            "run_id": "run-test",
            "ts": stamp(1.5),
            "stage": "writer",
            "model_diagnostics": [{"stage": "writer", "raw_response": PRIVATE}],
        }
    ]
    assert "writer_output_invalid" in summarize(value)["recorded_dispositions"]


@pytest.mark.parametrize("change", ["run", "early", "late", "future", "naive"])
def test_suppression_requires_an_exact_completed_run_and_time_interval(change):
    value = state()
    row = {"id": "supp", "run_id": "run-test", "ts": stamp(1.5), "stage": "budget_exhausted"}
    if change == "run":
        row["run_id"] = "another-run"
    else:
        row["ts"] = {
            "early": stamp(3),
            "late": stamp(0.5),
            "future": stamp(-1),
            "naive": "2026-10-01T17:00:00",
        }[change]
    value["suppressions"] = [row]
    report = summarize(value)
    assert not report["recorded_dispositions"] and report["unavailable_context"]


@pytest.mark.parametrize("bad", [None, [], "private", 10])
def test_invalid_root_or_clock_is_rejected(bad):
    with pytest.raises(ValueError, match="invalid_report_input"):
        summarize(bad)
    with pytest.raises(ValueError, match="invalid_report_input"):
        summarize({}, now=NOW.replace(tzinfo=None))


def test_cli_no_keys_uses_source_manifest_without_recomputing_runtime_policy(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state()))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "source_manifest", lambda: {"source_sha256": SHA})
    assert cli.main([str(path), "--now", stamp(0)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["saved_output"]["bound_model_reviews"] == 1
    assert result["required_check_receipts"] == "incomplete"


@pytest.mark.parametrize("bad", ["missing", "json", "root", "oversize", "clock"])
def test_cli_errors_are_fixed_and_never_print_input(tmp_path, monkeypatch, capsys, bad):
    path = tmp_path / "private-filename.json"
    if bad != "missing":
        path.write_text(PRIVATE if bad in ("json", "oversize") else "[]" if bad == "root" else "{}")
    if bad == "oversize":
        monkeypatch.setattr(cli, "MAX_BYTES", 5)
    args = [str(path)] + (["--now", "private-invalid-clock"] if bad == "clock" else [])
    assert cli.main(args) == 2
    output = capsys.readouterr().out
    assert (
        PRIVATE not in output
        and "private-filename" not in output
        and "private-invalid-clock" not in output
    )
    assert json.loads(output)["report"] == "unavailable"


def test_workflow_reader_has_no_model_keys_and_does_not_hide_the_positive_gate():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/voice-regression.yml"
    workflow = yaml.safe_load(path.read_text())
    job = workflow["jobs"]["canary"]
    reader = next(
        s for s in job["steps"] if s.get("name") == "Read retained writer operating evidence"
    )
    assert set(reader["env"]) == {"GH_TOKEN", "GIST_ID"}
    assert 'python scripts/writer_health.py "$STATE_PATH"' in reader["run"]
    assert "RUNNER_TEMP" in reader["run"] and "trap " in reader["run"]
    gate = job["steps"][-1]
    assert gate["if"] == "always()" and gate["run"].endswith("-m voice_canary")
    assert "schedule" in job["if"] and "pull_request" not in job["if"]


def test_equal_time_inventories_and_malformed_usage_remain_unknown():
    value = state()
    value["run_history"].append(run("other-run", age=1))
    value["llm_usage_observations"] = {"observations": PRIVATE}
    result = summarize(value)
    assert result["runtime"]["status"] == "unobserved"
    assert result["provider_response"]["window_invalid"]
    assert result["unavailable_context"]["runtime_inventory_ambiguous"] == 1
    assert PRIVATE not in json.dumps(result)


def test_boolean_writer_samples_cannot_match_integer_policy():
    value = state()
    value["run_history"][0]["runtime_inventory"]["flags"]["writer_samples"] = True
    assert summarize(value)["saved_output"]["bound_model_reviews"] == 0


@pytest.mark.parametrize("kind", ["drafts", "suppressions"])
def test_competing_draft_and_suppression_identities_are_quarantined(kind):
    value = state()
    if kind == "suppressions":
        value[kind] = [
            {"id": "supp", "run_id": "run-test", "ts": stamp(1.5), "stage": "budget_exhausted"}
        ]
    original = value[kind][0]
    value[kind].append(deepcopy(original))
    result = summarize(value)
    if kind == "drafts":
        assert result["saved_output"]["bound_model_reviews"] == 1
    else:
        assert result["recorded_dispositions"]["recorded_budget_exception"]["count"] == 1
    value[kind][1]["private_added_context"] = PRIVATE
    result = summarize(value)
    assert result["unavailable_context"][kind + "_conflicting_ids"] == 1
    assert (
        result["saved_output"]["bound_model_reviews"] == 0
        if kind == "drafts"
        else not result["recorded_dispositions"]
    )


def test_last_failure_timestamp_orders_subseconds_correctly():
    value = state()
    value["suppressions"] = [
        {"id": f"supp-{i}", "run_id": "run-test", "ts": at, "stage": "budget_exhausted"}
        for i, at in enumerate(["2026-10-01T16:30:00.000001Z", "2026-10-01T16:30:00Z"])
    ]
    assert (
        summarize(value)["recorded_dispositions"]["recorded_budget_exception"]["last_observed_at"]
        == "2026-10-01T16:30:00.000001Z"
    )
