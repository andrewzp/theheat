"""Synthetic copy and source support only; private incumbent text never checked in."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import socket
import subprocess

import pytest

from src.evaluation import historical as evaluation, incumbent
from tests.test_ghcn_time_integrity import baseline_rows, dly


LABELS, SPECS = evaluation.load_catalog()
VARIANTS = [(spec, variant) for spec in SPECS.values() for variant in spec["variants"]]


@pytest.mark.parametrize("spec,variant", VARIANTS,
                         ids=lambda row: row.get("probe_id", row.get("case_id")))
def test_actual_pipeline_matches_explicit_expectation_without_provider_calls(spec, variant):
    observation = evaluation.run_probe(variant["tweet"], spec, pipeline_mode=True)
    assert evaluation.expected_matches(observation, variant), observation
    assert observation["provider_calls"] == observation["unexpected_boundary_attempts"] == 0
    if variant["expected_outcome"] == "targeted_rejection":
        assert observation["pipeline_kill_stage"] == "fact_check"
        assert observation["checker_boundary_reached"] == 0
    else:
        assert observation["checker_boundary_reached"] == 1


def test_missing_source_or_unrelated_failure_cannot_satisfy_targeted_case():
    variant = VARIANTS[0][1]
    assert not evaluation.expected_matches(
        {"outcome": "local_rejection", "observed_codes": ["missing_provenance"]}, variant)
    assert not evaluation.expected_matches(
        {"outcome": "verification_required", "observed_codes": variant["expected_codes"]}, variant)


@pytest.mark.parametrize("action", [
    lambda: socket.create_connection(("example.test", 443)),
    lambda: socket.getaddrinfo("example.test", 443),
    lambda: socket.socket().connect(("127.0.0.1", 443)),
    lambda: subprocess.run(["curl", "https://example.test"]),
])
def test_network_and_process_traps_fail_before_io(action):
    with pytest.raises(evaluation.OfflineViolation):
        with evaluation.offline_boundaries():
            action()


def test_unexpected_provider_boundary_cannot_be_hidden_by_exception_handler():
    from src.two_bot import writer
    with pytest.raises(evaluation.OfflineViolation):
        with evaluation.offline_boundaries():
            try:
                writer.write_tweet(None, None)
            except Exception:
                pass
    with pytest.raises(evaluation.OfflineViolation):
        with evaluation.offline_boundaries():
            try:
                writer._call_anthropic(None, None)
            except BaseException:
                pass


def test_injected_safety_model_cannot_call_provider_and_restores_required_check(monkeypatch):
    from src.voice import safety
    original_check = safety.check_llm
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "synthetic-key-never-used")
    spec, variant = VARIANTS[0]
    observation = evaluation.run_probe(variant["tweet"], spec, pipeline_mode=True)
    assert observation["provider_calls"] == 0 and observation["safety_model_evaluated"] is False
    assert safety.GEMINI_API_KEY == "synthetic-key-never-used"
    assert safety.check_llm is original_check
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    assert safety.check_llm("A synthetic fixture.")[0] is False


def test_private_text_and_diagnostics_never_escape_streams_or_report(capsys):
    from src.two_bot import pipeline
    from unittest.mock import patch
    secret = "private synthetic draft marker"
    spec = SPECS["thermal_detection_is_not_verified_wildfire"]
    with patch.object(pipeline, "_check_safety_honesty_fact", side_effect=lambda *a, **k: print(secret)):
        observation = evaluation.run_probe(secret, spec, pipeline_mode=True)
    assert secret not in json.dumps(observation)
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


def test_packet_gaps_stay_gaps_and_real_pipeline_rejects_complete_invalid_packet():
    assert evaluation.observe_packet(None)["outcome"] == "missing_retained_packet"
    assert evaluation.observe_packet({"event_id": "old"})["outcome"] == "incomplete_legacy_packet"
    packet = evaluation.structural_bundle(SPECS["thermal_detection_is_not_verified_wildfire"]).to_dict()
    packet["raw_signal_dump"] = {}
    result = evaluation.observe_packet(packet)
    assert result["outcome"] == "legacy_packet_evidence_abstention"
    assert result["provider_calls"] == 0


def test_valid_packet_is_not_counted_as_scientific_rejection():
    packet = evaluation.structural_bundle(SPECS["thermal_detection_is_not_verified_wildfire"]).to_dict()
    with pytest.raises(evaluation.OfflineViolation):
        evaluation.observe_packet(packet)


def test_catalog_cannot_drop_limits_or_duplicate_a_case(tmp_path):
    catalog = json.loads(evaluation.CATALOG.read_text())
    probes = json.loads(evaluation.PROBES.read_text())
    cat = tmp_path / "catalog.json"
    spec = tmp_path / "spec.json"
    cat.write_text(json.dumps(catalog))
    probes["cases"].append(probes["cases"][0])
    spec.write_text(json.dumps(probes))
    with pytest.raises(ValueError, match="exactly one"):
        evaluation.load_catalog(cat, spec)
    probes["cases"].pop()
    spec.write_text(json.dumps(probes))
    catalog["cases"][0]["evidence_limit"] = ""
    cat.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="limits"):
        evaluation.load_catalog(cat, spec)


@pytest.fixture
def synthetic_package(tmp_path, monkeypatch):
    state = {"drafts": [], "publish_ledger": {}, "memory": {"shipped_tweets": []}}
    corpus = {}
    for label in LABELS:
        spec = SPECS[label["case_id"]]
        for audit_id in label["audit_ids"]:
            if audit_id in corpus:
                continue
            # Copy is deliberately synthetic, including audit-like IDs. Source
            # support below is engineered; it does not replace frozen evidence.
            tweet = f"Synthetic {audit_id}: " + (spec["variants"][0]["tweet"] if spec["variants"] else "A temperature comparison.")
            if audit_id in {"T47", "T60"}:
                tweet = f"Synthetic {audit_id}: Paris hit 40°C with a wet-bulb burden."
            if audit_id == "T46":
                tweet = "Synthetic T46: A wildfire started when the convective lid broke."
            memory_only, no_receipt = audit_id == "T02", audit_id == "T30"
            event_id = f"synthetic_{audit_id}"
            if audit_id in {"T34", "T43"}:
                event_id = f"all_time_high_USS0011K13S_2026-06-{'12' if audit_id == 'T34' else '25'}"
            receipt = None if memory_only or no_receipt else str(10000 + int(audit_id[1:]))
            posted_at = None if memory_only else "2026-07-01T12:00:00Z"
            corpus[audit_id] = {"audit_id": audit_id, "event_id": event_id, "text": tweet,
                "publication_evidence": "generation_memory_only_publication_unverified" if memory_only else "posted_state_no_receipt" if no_receipt else "x_receipt",
                "posted_at": posted_at, "tweet_id": receipt, "url": f"https://x.com/i/status/{receipt}" if receipt else "",
                "live_x_check": "not_checked", "public_views_2026_09_08": None}
            if memory_only:
                state["memory"]["shipped_tweets"].append({"event_id": event_id, "tweet_text": tweet})
            else:
                state["drafts"].append({"id": f"draft-{audit_id}", "event_id": event_id, "text": tweet,
                                        "status": "posted", "posted_at": posted_at, "tweet_id": receipt})
            if receipt:
                state["publish_ledger"][event_id] = {"tweet_id": receipt}
    snapshot = incumbent._encode(state)
    for row in corpus.values():
        row["source_snapshot_sha256"] = hashlib.sha256(snapshot).hexdigest()
    paths = {}
    for key, value in (("corpus", incumbent._encode(list(corpus.values()))), ("snapshot", snapshot),
                       ("cases", evaluation.CATALOG.read_bytes())):
        paths[key] = tmp_path / f"{key}.json"
        paths[key].write_bytes(value)
    # Reuse existing P06 serializer/engineered support; June16 is explicitly
    # added so this fixture differs from its June12-only progression scenario.
    support = baseline_rows() + [(date(2026, 6, 12), "TMAX", 348, "", "T"),
        (date(2026, 6, 16), "TMAX", 360, "", "T"), (date(2026, 6, 25), "TMAX", 399, "S", "T")]
    source = tmp_path / "synthetic.dly"
    source.write_bytes(dly(support))
    monkeypatch.setattr(incumbent, "_source_files", lambda *_: {"incumbent/src/prompt.py": b"Synthetic prompt snapshot"})
    frozen = tmp_path / "frozen"
    result = incumbent.freeze(repository=tmp_path, revision="a" * 40, **paths,
        evidence={"beaver-ghcn-as-retrieved-2026-09-08.dly": source}, output=frozen)
    return frozen, result["manifest_sha256"]


def test_verified_package_joins_private_text_and_preserves_publication_uncertainty(synthetic_package, capsys):
    report, private = evaluation.evaluate(*synthetic_package)
    assert evaluation.unexpected_observations(report) == []
    assert report["provider_calls"] == 0
    assert report["runtime_source_sha256"]
    serialized = json.dumps(report)
    assert all(row["original"]["text"] not in serialized for row in private["texts"])
    t02 = [row for case in report["cases"] for row in case["retained"] if row["audit_id"] == "T02"]
    assert len(t02) == 1 and t02[0]["publication_evidence"] == "generation_memory_only_publication_unverified"
    source = next(case["source_observation"] for case in report["cases"] if "source_observation" in case)
    assert source["expectation_met"] and source["current_accepted_previous_value_c"] == 36.0
    assert source["current_accepted_previous_date"] == "2026-06-16"
    assert "publication_time_qc_unknown" in source["observed_codes"]
    assert not capsys.readouterr().out


def test_tampered_package_cannot_enter_any_runtime_probe(synthetic_package, monkeypatch):
    package, digest = synthetic_package
    (package / "corpus.json").write_text("[]")
    monkeypatch.setattr(evaluation, "run_probe", lambda *_a, **_kw: pytest.fail("Probe ran before verification"))
    with pytest.raises(ValueError, match="digest"):
        evaluation.evaluate(package, digest)


def test_private_outputs_are_ignored_new_restrictive_and_do_not_overwrite(tmp_path):
    root = tmp_path.resolve()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text(".gstack/\n")
    output = root / ".gstack/benchmarks/run-one"
    result = evaluation.write_private_results(output, {"cases": []}, {"text": "synthetic private"}, repository=root)
    assert (output.stat().st_mode & 0o777) == 0o700
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in output.iterdir())
    assert "synthetic private" not in json.dumps(result)
    with pytest.raises(ValueError, match="new"):
        evaluation.write_private_results(output, {}, {}, repository=root)
    with pytest.raises(ValueError, match="direct child"):
        evaluation.write_private_results(root / "public.json", {}, {}, repository=root)
    (root / ".gitignore").write_text("")
    with pytest.raises(ValueError, match="not ignored"):
        evaluation.write_private_results(output.with_name("not-ignored"), {}, {}, repository=root)


def test_missing_source_is_not_a_source_regression_pass(tmp_path):
    result = evaluation.source_observations(tmp_path, {})
    assert result["outcome"] == "needs_source"
    assert result.get("expectation_met") is not True
