"""W11.1 / W11.6 — every spend route consumes its declaration; background lanes are exact opt-in.

Invented transports only: DNS/connect are trapped, SDK/session factories are fakes.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
import requests

from src.two_bot import call_inventory as inv
from tests import live_content_harness as h

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    h.trap_network(monkeypatch.setattr)


def _source(module_path: str) -> str:
    if module_path.startswith(".github/"):
        return (ROOT / module_path).read_text()
    return (ROOT / (module_path.replace(".", "/") + ".py")).read_text()


def _literal_calls(name: str) -> list[tuple[str, str, int]]:
    """(file, first string argument, line) for every literal call of ``name`` in production code."""
    found = []
    for base in ("src", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == name
                        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    found.append((str(path.relative_to(ROOT)), node.args[0].value, node.lineno))
    return found


def test_every_production_provider_call_uses_a_declared_stage_and_provider():
    calls = [(f, stage, line) for f, stage, line in _literal_calls("provider_call")]
    assert calls, "provider_call sites must exist"
    for path, stage, line in calls:
        declared = inv.DECLARATIONS.get(stage)
        assert declared is not None and stage != "undeclared_provider_call", (path, line, stage)
    # The provider literal is the second argument; it must be a declared provider for that stage.
    for source in (ROOT / "src").rglob("*.py"):
        for match in re.finditer(r'provider_call\("([a-z_]+)", "([a-z]+)"', source.read_text()):
            assert match.group(2) in inv.DECLARATIONS[match.group(1)].providers, (source, match.group(0))


def test_every_consume_literal_is_declared_and_every_declaration_is_consumed_at_its_call_site():
    consumed = {stage for _f, stage, _l in _literal_calls("consume")}
    assert consumed <= set(inv.DECLARATIONS)
    provider_stages = {stage for _f, stage, _l in _literal_calls("provider_call")}
    for stage, declared in inv.DECLARATIONS.items():
        module, _, function = declared.call_site.partition(":")
        text = _source(module)
        assert function.split(".")[-1] in text, (stage, declared.call_site)
        if stage == "undeclared_provider_call":
            assert "consume_provider_stage" in text
        elif declared.background_lane and declared.physical_call in ("workflow_agent",):
            assert "REPAIR_ENABLED\" != \"1\"" in text and "repair_allowed == 'true'" in text
        elif declared.background_lane == "paid_evaluation":
            assert "background_lane" in text, stage
        elif declared.background_lane == "paid_pr_replay":
            assert "vars.THEHEAT_PAID_PR_REPLAY_ENABLED == '1'" in text
        elif stage in provider_stages:
            assert stage in consumed or "consume_provider_stage" in _source("src.two_bot.trial_budget")
        else:
            assert f'consume("{stage}"' in text or f'call_stage="{stage}"' in text or stage == "source_http_get", stage
    assert {"x_metrics_read", "gist_state", "bluesky_publish", "x_publish", "threshold_acquisition"} <= consumed
    assert 'call_stage="news_verification_page"' in _source("src.data.newsworthiness")


def test_pricing_is_never_zero_and_inventory_disclaims_actual_cost():
    report = inv.inventory()
    assert report["actual_cost_known"] is False and report["invoice_reconciled"] is False
    assert {row["pricing"] for row in report["declarations"]} <= {"estimate_partial", "unknown"}
    assert all(row["actual_cost_known"] is False and row["unpriced_dimensions"] for row in report["declarations"])
    for operation, stages in inv.OPERATIONS.items():
        assert set(stages) <= set(inv.DECLARATIONS), operation


def test_undeclared_provider_stage_is_counted_unpriced_never_dropped():
    before = inv.runtime_counts().get("undeclared_provider_call", 0)
    with inv.operation_scope("alerts") as join:
        from src.two_bot.trial_budget import provider_call
        assert provider_call("invented_stage", "google", {"model": "invented"}, lambda **_: "ok") == "ok"
    assert inv.runtime_counts()["undeclared_provider_call"] == before + 1
    row = inv.operation_cost_row("alerts", join=join)
    assert row["requests"]["by_stage"]["undeclared_provider_call"]["pricing"] == "unknown"
    assert row["unpriced_requests"] == 1
    with pytest.raises(inv.UndeclaredCallError):
        inv.consume("invented_stage")
    with pytest.raises(inv.UndeclaredCallError):
        inv.consume("writer", provider="invented")


class _Session:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def get(self, url, **kwargs):
        self.calls += 1
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _ok(status=200):
    response = requests.Response()
    response.status_code, response._content = status, b"invented"
    return response


def test_fetch_with_retry_consumes_each_physical_attempt_and_refuses_undeclared_stage(monkeypatch):
    from src.data import _http
    session = _Session([requests.ConnectionError("invented"), requests.Timeout("invented"), _ok()])
    monkeypatch.setattr(_http, "_get_session", lambda: session)
    monkeypatch.setattr(_http, "_sleep_before_retry", lambda *_: None)
    attempts = []
    before = inv.runtime_counts().get("source_http_get", 0)
    assert _http.fetch_with_retry("https://example.invalid/data", on_attempt=lambda: attempts.append(1)).status_code == 200
    assert session.calls == 3 and len(attempts) == 3
    assert inv.runtime_counts()["source_http_get"] == before + 3
    with pytest.raises(inv.UndeclaredCallError):
        _http.fetch_with_retry("https://example.invalid/data", call_stage="invented_stage")
    assert session.calls == 3  # Refused before any egress.


def test_metrics_lane_requires_exact_one_before_client_construction(monkeypatch):
    from src.data import twitter_metrics
    constructed = []

    class Client:
        def __init__(self, **kwargs):
            constructed.append(kwargs)
            self.session = SimpleNamespace(close=lambda: None)

        def get_tweets(self, **kwargs):
            return SimpleNamespace(data=[{"id": "1", "public_metrics": {"like_count": 2}}])

    monkeypatch.setattr(twitter_metrics.tweepy, "Client", Client)
    for name in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
        monkeypatch.setattr(twitter_metrics, name, "invented")
    for value in (None, "", "0", "true", "1 ", "yes"):
        if value is None:
            monkeypatch.delenv("THEHEAT_METRICS_ENABLED", raising=False)
        else:
            monkeypatch.setenv("THEHEAT_METRICS_ENABLED", value)
        assert twitter_metrics.fetch_metrics(["1"]) == {} and constructed == []
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    before = inv.runtime_counts().get("x_metrics_read", 0)
    assert set(twitter_metrics.fetch_metrics(["1"])) == {"1"} and len(constructed) == 1
    assert inv.runtime_counts()["x_metrics_read"] == before + 1


def test_paid_evaluation_script_refuses_before_any_provider(monkeypatch, capsys):
    import scripts.writer_dryrun as dryrun
    from src.two_bot import writer

    def forbidden(*_a, **_k):
        raise AssertionError("provider path reached")

    monkeypatch.setattr(writer, "write_tweet", forbidden)
    monkeypatch.setattr("sys.argv", ["writer_dryrun.py"])
    for value in (None, "true", "0"):
        if value is None:
            monkeypatch.delenv("THEHEAT_PAID_EVALUATION_ENABLED", raising=False)
        else:
            monkeypatch.setenv("THEHEAT_PAID_EVALUATION_ENABLED", value)
        assert dryrun.main() == 2
    assert "no provider call made" in capsys.readouterr().out
    for name in ("scripts.reganom_writer_dryrun", "scripts.news_enrich_writer_dryrun"):
        assert 'require_background_lane("paid_evaluation")' in _source(name)
        importlib.import_module(name)


def test_voice_regression_paid_runs_keep_their_exact_job_gates_and_default_deselection():
    text = (ROOT / ".github/workflows/voice-regression.yml").read_text()
    assert text.count("vars.THEHEAT_PAID_EVALUATION_ENABLED == '1'") == 2
    assert "vars.THEHEAT_PAID_PR_REPLAY_ENABLED == '1'" in text
    assert "addopts = \"-m 'not voice_replay'" in (ROOT / "pyproject.toml").read_text()


def test_paid_workflow_steps_mirror_the_exact_flag_and_selfheal_gates_before_the_agent():
    for name in ("writer-dryrun", "reganom-dryrun", "news-enrich-dryrun"):
        text = (ROOT / f".github/workflows/{name}.yml").read_text()
        assert "vars.THEHEAT_PAID_EVALUATION_ENABLED == '1'" in text
        assert "THEHEAT_PAID_EVALUATION_ENABLED: ${{ vars.THEHEAT_PAID_EVALUATION_ENABLED }}" in text
    heal = (ROOT / ".github/workflows/workflow-self-heal.yml").read_text()
    gate, agent = heal.index('elif [ "$REPAIR_ENABLED" != "1" ]'), heal.index("anthropics/claude-code-action")
    assert gate < agent and "if: needs.gate.outputs.repair_allowed == 'true'" in heal[:agent]


def test_lane_names_are_exact_flags_and_pr_replay_needs_paid_evaluation():
    assert inv.BACKGROUND_LANES == {"metrics": "THEHEAT_METRICS_ENABLED",
                                    "paid_evaluation": "THEHEAT_PAID_EVALUATION_ENABLED",
                                    "paid_pr_replay": "THEHEAT_PAID_PR_REPLAY_ENABLED",
                                    "selfheal_repair": "THEHEAT_SELFHEAL_REPAIR_ENABLED"}
    assert inv.background_lane_enabled("paid_pr_replay", {"THEHEAT_PAID_PR_REPLAY_ENABLED": "1"}) is False
    assert inv.background_lane_enabled("paid_pr_replay", {"THEHEAT_PAID_PR_REPLAY_ENABLED": "1",
                                                          "THEHEAT_PAID_EVALUATION_ENABLED": "1"}) is True
    with pytest.raises(inv.BackgroundLaneDisabled):
        inv.require_background_lane("metrics", {"THEHEAT_METRICS_ENABLED": "TRUE"})
    with pytest.raises(inv.UndeclaredCallError):
        inv.background_lane_enabled("invented_lane", {})
