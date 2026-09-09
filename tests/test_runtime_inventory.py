"""Runtime observations must describe the bot process, not inferred health."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
import json

from src import runtime_inventory, state
from src.orchestrator import cli
from src.storage import sqlite_store
from src.two_bot import critic, fact_check, writer
from src.voice import safety


NOW = datetime(2026, 9, 9, 2, 0, tzinfo=UTC)


def test_snapshot_uses_loaded_models_and_never_serializes_credentials(monkeypatch):
    secret = "sentinel-private-credential-do-not-persist"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setenv("EARTHDATA_TOKEN", secret)
    monkeypatch.setenv("UNRELATED_SECRET", secret)
    # A changed env does not reconfigure modules already loaded by the worker.
    monkeypatch.setenv("THEHEAT_WRITER_MODEL", "claude-future-env-only")
    monkeypatch.setenv("THEHEAT_FACT_CHECK_MODEL", "gemini-future-env-only")
    monkeypatch.setenv("THEHEAT_CLAIM_EXTRACT_MODEL", "unused-legacy-model")
    monkeypatch.setattr(writer, "WRITER_MODEL", "claude-loaded-writer")
    monkeypatch.setattr(writer, "WRITER_PROVIDER", "anthropic")
    monkeypatch.setattr(fact_check, "FACT_CHECKER_MODEL", "gemini-loaded-checker")
    monkeypatch.setattr(critic, "CRITIC_MODEL", "gemini-loaded-critic")
    monkeypatch.setattr(safety, "GEMINI_SAFETY_MODEL", "gemini-loaded-safety")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")

    snapshot = runtime_inventory.collect_runtime_inventory("alerts", now=NOW)

    assert snapshot["models"] == {
        "writer": "claude-loaded-writer",
        "writer_provider": "anthropic",
        "fact_check": "gemini-loaded-checker",
        "critic": "gemini-loaded-critic",
        "safety": "gemini-loaded-safety",
        "claim_extract": None,
    }
    assert snapshot["credentials_present"]["anthropic"] is True
    assert snapshot["credentials_present"]["gemini"] is True
    assert snapshot["credentials_present"]["safety_gemini"] is False
    assert snapshot["capabilities"] == {
        "claim_extraction": "inactive",
        "legacy_voice_generation": "inactive",
        "safety_llm": "inactive",
    }
    assert all(type(v) is bool for v in snapshot["credentials_present"].values())
    encoded = json.dumps(snapshot, allow_nan=False)
    assert secret not in encoded
    assert "unused-legacy-model" not in encoded
    assert "future-env-only" not in encoded
    assert "UNRELATED_SECRET" not in encoded


def test_snapshot_uses_real_flag_semantics_and_parent_kill_switch(monkeypatch):
    # These intentionally differ: autoship accepts truthy words; triage and
    # metrics accept exactly "1". A shared invented parser would lie.
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", " TRUE ")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "true")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "no")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "yes")
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "0")
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_GPM_SOURCE", "invalid-source")
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "BOTH")
    monkeypatch.setenv("THEHEAT_AQ_PM25_ENABLED", "false")
    monkeypatch.setenv("THEHEAT_AQ_DUST_ENABLED", "")

    flags = runtime_inventory.collect_runtime_inventory("both", now=NOW)["flags"]

    assert flags["autoship_on_critic_pass"] is True
    assert flags["triage_enabled"] is False
    assert flags["metrics_enabled"] is False
    assert flags["critic_enabled"] is False
    assert flags["critic_revise_enabled"] is True
    assert flags["writer_samples"] == 1
    assert flags["newsworthiness_enabled"] is False
    assert flags["news_enrich_enabled"] is False
    assert flags["news_boost_enabled"] is False
    assert flags["gpm_source"] == "opendap"
    assert flags["signals_provider"] == "both"
    assert flags["aq_pm25_enabled"] is False
    assert flags["aq_dust_enabled"] is True


def test_build_identity_backend_and_utc_time_are_observed(monkeypatch, tmp_path):
    version = tmp_path / "VERSION"
    version.write_text("0.9.108.3\n")
    monkeypatch.setattr(runtime_inventory, "_VERSION_PATH", version)
    monkeypatch.setenv("GITHUB_SHA", "A" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "34302378852")
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "")
    monkeypatch.setenv("THEHEAT_DB_PATH", str(tmp_path / "state.sqlite"))
    local_now = NOW.astimezone(timezone(timedelta(hours=-4)))

    snapshot = runtime_inventory.collect_runtime_inventory("auto_publish_due", now=local_now)

    assert snapshot["schema_version"] == 1
    assert snapshot["captured_at"] == "2026-09-09T02:00:00Z"
    assert snapshot["mode"] == "auto_publish_due"
    assert snapshot["git_sha"] == "a" * 40
    assert snapshot["github_run_id"] == "34302378852"
    assert snapshot["version"] == "0.9.108.3"
    assert snapshot["state_backend"] == "sqlite"
    assert str(tmp_path) not in json.dumps(snapshot)


def test_missing_or_invalid_build_identity_stays_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_inventory, "_VERSION_PATH", tmp_path / "missing")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    snapshot = runtime_inventory.collect_runtime_inventory("alerts", now=NOW)
    assert snapshot["git_sha"] is None
    assert snapshot["version"] is None
    assert snapshot["github_run_id"] is None

    malformed = tmp_path / "VERSION"
    malformed.write_text("not a version")
    monkeypatch.setattr(runtime_inventory, "_VERSION_PATH", malformed)
    monkeypatch.setenv("GITHUB_SHA", "untrusted arbitrary value")
    monkeypatch.setenv("GITHUB_RUN_ID", "untrusted arbitrary value")
    snapshot = runtime_inventory.collect_runtime_inventory("alerts", now=NOW)
    assert snapshot["git_sha"] is None
    assert snapshot["version"] is None
    assert snapshot["github_run_id"] is None


def test_snapshot_survives_finalize_merge_and_sqlite_run_json(tmp_path):
    snapshot = runtime_inventory.collect_runtime_inventory("alerts", now=NOW)
    bot_state = deepcopy(state.DEFAULT_STATE)
    run = state.init_run("alerts")
    run["runtime_inventory"] = snapshot
    state.finalize_run(bot_state, run)
    # Finalization freezes the snapshot, so later in-memory changes cannot
    # rewrite the historical observation.
    snapshot["flags"]["metrics_enabled"] = "changed-after-finalize"
    merged = state._merge_state(deepcopy(state.DEFAULT_STATE), bot_state)
    retained = merged["run_history"][0]["runtime_inventory"]
    assert isinstance(retained["flags"]["metrics_enabled"], bool)
    assert set(merged) == set(state.DEFAULT_STATE)

    db_path = str(tmp_path / "theheat.sqlite")
    assert sqlite_store.write_state(db_path, merged)
    loaded = sqlite_store.read_state(db_path, state.DEFAULT_STATE)
    assert loaded["run_history"][0]["runtime_inventory"] == retained


def test_cli_captures_inventory_before_dispatch_and_preserves_it_in_history(monkeypatch):
    captured = {"schema_version": 1, "captured_at": NOW.isoformat(), "mode": "alerts"}
    bot_state = deepcopy(state.DEFAULT_STATE)
    saved = []
    events = []

    def collect(mode, *, bot_state):
        events.append("capture")
        assert mode == "alerts"
        return captured

    def dispatch(current_state, *, current_run):
        events.append("dispatch")
        assert current_run["runtime_inventory"] == captured
        return current_state

    def save(current_state):
        saved.append(deepcopy(current_state))
        return True

    monkeypatch.setattr(cli.sys, "argv", ["theheat", "alerts"])
    monkeypatch.setattr(cli.state, "read_state", lambda: bot_state)
    monkeypatch.setattr(cli.state, "write_state", save)
    monkeypatch.setattr(cli.runtime_inventory, "collect_runtime_inventory", collect)
    monkeypatch.setattr(cli.credentials, "collect_credential_expiry", lambda: {})
    monkeypatch.setattr(cli.usage_ledger, "drain_into_state", lambda _: 0)
    monkeypatch.setattr(cli.budget, "record_budget_health", lambda _: cli.budget.budget_status({}))

    cli.main({"alerts": dispatch})

    assert events == ["capture", "dispatch"]
    assert saved[-1]["run_history"][0]["runtime_inventory"] == captured
    assert "runtime_inventory" not in saved[-1]
