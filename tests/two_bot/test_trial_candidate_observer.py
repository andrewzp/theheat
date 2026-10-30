"""Private trial diagnostics using invented text and explicit offline model stubs."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import tarfile
from unittest.mock import Mock

import pytest

from scripts import fresh_sample_trial as trial
from src.editorial.revisions import text_hash
from src.two_bot import pipeline
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from src.voice import safety
from tests.two_bot.conftest import _bundle, _state_with_memory


@pytest.fixture
def stages(monkeypatch, configured_pipeline_providers):
    from src import main

    main._sync_compat_globals()
    calls = [Mock(return_value=WriterResult("An invented private candidate.", None, "number", None, None, "offline")),
             Mock(return_value=(True, None)), Mock(return_value=FactCheckResult(True, [], "offline")),
             Mock(return_value=CriticResult(True, None, "offline"))]
    monkeypatch.setattr(pipeline.writer, "write_tweet", calls[0])
    monkeypatch.setattr(pipeline, "run_safety_pipeline", calls[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", calls[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", calls[3])
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    return calls


def setup_execute(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    bundle = _bundle().to_dict()
    monkeypatch.setattr(trial, "validate_packet", lambda *a: (_state_with_memory(), [bundle, deepcopy(bundle)]))
    monkeypatch.setattr(trial, "eligible", lambda *a: True)
    monkeypatch.setattr(trial, "claim_execution", lambda *a: trial.save(tmp_path / "execution-started.json", b"{}"))
    return now, bundle


def test_real_agency_opener_rejection_retains_exact_selected_text_before_paid_checks(stages, monkeypatch, tmp_path, capsys):
    now, bundle = setup_execute(tmp_path, monkeypatch)
    # The second distinct fixture is never reached: a rejected first candidate
    # is sufficient for this test, without manufacturing another provider call.
    monkeypatch.setattr(trial, "validate_packet", lambda *a: (_state_with_memory(), [bundle]))
    text = "NWS: Invented Island is under a warning."
    stages[0].return_value = WriterResult(text, None, "number", None, None, "offline")
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety.run_safety_pipeline)
    result = trial.execute(tmp_path, "a" * 64, now)
    packet = json.loads((tmp_path / "candidate-1-text-1.json").read_text())
    assert packet["text"] == text and packet["text_sha256"] == text_hash(text)
    assert packet["event_id"] == bundle["event_id"]
    assert packet["bundle_sha256"] == trial.digest(trial.encoded(bundle))
    assert packet["authority"] == "diagnostic_only" and packet["checks_complete"] is False
    assert packet["human_reviewed"] is packet["approved"] is False
    assert os.stat(tmp_path / "candidate-1-text-1.json").st_mode & 0o777 == 0o600
    # The free copy gate now names the agency opener before the free safety regex would.
    assert json.loads((tmp_path / "candidate-1.json").read_text())["checks"]["kill_stage"] == "copy_gate"
    assert not stages[2].called and not stages[3].called
    assert result["drafts_returned"] == result["paid_dispatch_reservations"] == result["posts"] == 0
    assert text not in capsys.readouterr().out


def test_selected_formatted_text_observed_before_checks_without_becoming_authority(stages, monkeypatch):
    selected = "Selected private text with its source."
    monkeypatch.setattr(pipeline, "format_source_link", lambda *a: selected)
    observations = []

    def observe(text, attempt):
        assert not stages[1].called and not stages[2].called
        observations.append((text, attempt))

    result = pipeline.generate_draft(_bundle(), _state_with_memory(), candidate_observer=observe)
    assert observations == [(selected, 1)]
    assert result["text"] == selected
    assert stages[1].call_args.args[0] == stages[2].call_args.args[0] == selected
    assert [c.call_count for c in stages] == [1, 1, 1, 1]
    assert "candidate_observer" not in result and "approved" not in result


def test_slate_observer_uses_selected_candidate_not_sample_zero(stages, monkeypatch):
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    texts = ["Invented candidate one.", "Invented candidate two.", "Invented selected candidate."]
    stages[0].side_effect = [WriterResult(t, None, "number", None, None, "offline") for t in texts]
    select = Mock(return_value=CriticResult(True, None, "offline", selected_index=2))
    monkeypatch.setattr(pipeline.critic, "critic_select_slate", select)
    observed = []
    result = pipeline.generate_draft(_bundle(), _state_with_memory(), candidate_observer=lambda t, a: observed.append((t, a)))
    assert observed == [(select.call_args.args[0][2], 1)] and result["text"] == observed[0][0]


def test_optional_revision_is_observed_separately_before_its_checks(stages, monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    first = stages[0].return_value.tweet
    revised = "An invented revised candidate."
    stages[0].side_effect = [stages[0].return_value, WriterResult(revised, None, "number", None, None, "offline")]
    stages[3].side_effect = [CriticResult(False, None, "offline", verdict="REVISE", revise_instruction="A fixture edit"),
                             CriticResult(True, None, "offline")]
    observed = []

    def observe(text, attempt):
        assert stages[1].call_count == stages[2].call_count == attempt - 1
        observed.append((text, attempt))

    result = pipeline.generate_draft(_bundle(), _state_with_memory(), candidate_observer=observe)
    assert observed == [(first, 1), (revised, 2)] and result["text"] == revised
    assert [c.call_count for c in stages] == [2, 2, 2, 2]


def test_observer_exception_is_sanitized_and_blocks_downstream(stages, capsys):
    secret = "PRIVATE TEXT IN AN OBSERVER EXCEPTION"

    def unavailable(*a):
        raise OSError(secret)

    outcome = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=outcome, candidate_observer=unavailable) is None
    assert outcome["kill_stage"] == "pipeline_error"
    assert outcome["kill_reason"] == "RuntimeError: candidate_observation_failed"
    assert [c.call_count for c in stages] == [1, 0, 0, 0]
    assert secret not in capsys.readouterr().out


def test_trial_disk_failure_stops_before_checks_and_next_candidate(stages, monkeypatch, tmp_path):
    now, _ = setup_execute(tmp_path, monkeypatch)
    original = trial.save

    def fail_text_file(path, raw):
        if "-text-" in path.name:
            raise OSError("invented private disk failure")
        original(path, raw)

    monkeypatch.setattr(trial, "save", fail_text_file)
    result = trial.execute(tmp_path, "a" * 64, now)
    assert result["stop_reason"] == "trial_candidate_capture_failed"
    assert result["attempted_candidates"] == 1
    assert [c.call_count for c in stages] == [1, 0, 0, 0]
    assert (tmp_path / "execution-started.json").exists()


def test_trial_duplicate_capture_is_not_overwritten_and_stops(stages, monkeypatch, tmp_path):
    now, _ = setup_execute(tmp_path, monkeypatch)
    existing = tmp_path / "candidate-1-text-1.json"
    existing.write_bytes(b"original private diagnostic")
    result = trial.execute(tmp_path, "a" * 64, now)
    assert result["stop_reason"] == "trial_candidate_capture_failed"
    assert existing.read_bytes() == b"original private diagnostic"
    assert [c.call_count for c in stages] == [1, 0, 0, 0]


@pytest.mark.parametrize("text", ["", "x" * 4097, "\U0001f30d" * 1025, "\ud800"],
                         ids=["empty", "ascii-oversize", "utf8-oversize", "invalid-unicode"])
def test_invalid_or_oversized_text_is_not_truncated_or_written(tmp_path, text):
    with pytest.raises((ValueError, UnicodeError)):
        trial.retain_candidate_text(tmp_path, {"event_id": "invented"}, 1, text, 1)
    assert not list(tmp_path.iterdir())


def test_unicode_byte_limit_is_exact_and_default_pipeline_has_no_observer(stages, tmp_path):
    text = "\U0001f30d" * 1024
    trial.retain_candidate_text(tmp_path, {"event_id": "invented"}, 1, text, 1)
    assert json.loads((tmp_path / "candidate-1-text-1.json").read_text())["text"] == text
    result = pipeline.generate_draft(_bundle(), _state_with_memory())
    assert result["text"] == stages[0].return_value.tweet
    assert [c.call_count for c in stages] == [1, 1, 1, 1]


def test_whole_receipt_is_bounded_before_writing(tmp_path):
    with pytest.raises(ValueError, match="too_large"):
        trial.retain_candidate_text(tmp_path, {"event_id": "x" * trial.MAX_CAPTURE_BYTES}, 1, "Invented text.", 1)
    assert not list(tmp_path.iterdir())


def test_existing_encrypted_archive_includes_private_candidate_receipts(tmp_path, monkeypatch):
    from scripts import package_sample_trial as package

    directory = tmp_path / "sample-trial"
    directory.mkdir()
    text = "Invented private candidate."
    trial.retain_candidate_text(directory, {"event_id": "invented"}, 1, text, 1)
    cert = tmp_path / "invented.pem"
    cert.write_text("offline fixture only")
    monkeypatch.setattr(package, "validate_recipient", lambda *a: cert)
    encrypt = Mock()
    monkeypatch.setattr(package.subprocess, "run", encrypt)
    package.package(tmp_path, "offline fixture only")
    with tarfile.open(tmp_path / "sample-trial.tar.gz", "r:gz") as archive:
        receipt = json.load(archive.extractfile("sample-trial/candidate-1-text-1.json"))
    assert receipt["text"] == text
    argv = encrypt.call_args.args[0]
    assert argv[:3] == ["openssl", "cms", "-encrypt"]
    assert text not in " ".join(argv)
