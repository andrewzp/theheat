"""Actual credentialless SDK requests and parsers against an owned HTTP fixture."""
import time
import os
import signal
import io

import pytest

from src.posting import delivery_transport as transport, delivery_receipts as receipts
from src.posting.local_delivery import configuration, STAGES
from tests.local_delivery_helpers import fixture_server, value
from src.commands.schema import canonical_json

from PIL import Image

_image = io.BytesIO()
Image.new("RGB", (1, 1), "red").save(_image, format="PNG")
PNG = _image.getvalue()
TEXT = "An invented region recorded extreme heat."
ALT = "Invented graphic.\n"


def test_configuration_file_permissions_identity_and_ambient_credentials(tmp_path, monkeypatch):
    from src.posting.local_delivery import FixtureConfiguration, clean_environment, strict_json
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    path = folder / "fixture.json"
    with fixture_server(PNG, TEXT) as (config, trace, _):
        raw = canonical_json(config).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        pinned = FixtureConfiguration.load(path)
        assert pinned.read() == config
        path.chmod(0o644)
        with pytest.raises(ValueError, match="delivery_private_configuration_required"):
            pinned.read()
        path.chmod(0o600)
        folder.chmod(0o755)
        with pytest.raises(ValueError, match="delivery_private_directory_required"):
            pinned.read()
        folder.chmod(0o700)
        path.write_bytes(raw + b"\n")
        with pytest.raises(ValueError, match="delivery_configuration_changed"):
            pinned.read()
        link = folder / "link.json"
        link.symlink_to(path)
        with pytest.raises(OSError):
            FixtureConfiguration.load(link)
        with pytest.raises(ValueError, match="delivery_duplicate_key"):
            strict_json(b'{"invented":true,"invented":false}')
        for name, value in (("PGHOST", ""), ("TWITTER_ACCESS_TOKEN", "invented-secret"),
                            ("BLUESKY_PASSWORD", "invented-secret"), ("NODE_ENV", "production")):
            with monkeypatch.context() as patch:
                patch.setenv(name, value)
                with pytest.raises(ValueError):
                    clean_environment()
        assert trace == []


@pytest.mark.parametrize("changed", ["instance_id", "attempt_id", "request_sha256", "body_base64"])
def test_reconciliation_requires_exact_positive_request_and_instance(changed):
    import base64
    with fixture_server(PNG, TEXT) as (config, _, _):
        _, receipt, retained = exercise(config, "x", "upload", {})
        assert receipt["status"] == "confirmed"
        saved, observation, raw = retained[0]
        proof = dict(kind="accepted", instance_id=config["instance_id"], attempt_id=saved["attempt_id"],
            request_sha256=saved["request_sha256"], status=200, body_base64=base64.b64encode(raw).decode())
        proof[changed] = "invented-mismatch"
        response = canonical_json(proof).encode()
        observed = dict(observation, source="reconciliation", raw_sha256=receipts.digest(response))
        assert receipts.interpret(value(config, PNG), saved, observed, response) == dict(status="unknown", result=None)


def exercise(config, platform, stage, prior, *, before=None, check=lambda _:None):
    retained = []
    source = value(config, PNG)

    def begin(request, body):
        if before:
            before(request, body)
        binding = dict(attempt_id=receipts.digest(body), request_sha256=receipts.digest(canonical_json(request).encode()),
            configuration_sha256=source["configuration_sha256"], platform=platform, stage=stage, prior=prior,
            recorded_at=source["created_at"])
        return dict(dispatch_granted=True, binding=binding)

    def observe(saved, response, source_kind="response"):
        observation = dict(attempt_id=saved["attempt_id"], request_sha256=saved["request_sha256"], source=source_kind,
            reason=response["reason"], http_status=response["http_status"], complete=response["complete"],
            raw_sha256=receipts.digest(response["raw"]), recorded_at=source["created_at"])
        retained.append((saved, observation, response["raw"]))

    result = transport.execute(source, platform, stage, dict(png=PNG, alt=ALT, prior=prior, eligibility_deadline=time.monotonic()+30), begin=begin, observe=observe, check=check)
    parsed = receipts.interpret(source, *retained[-1]) if retained else None
    return result, parsed, retained


def test_actual_sdk_five_stages_and_retention_before_parsing():
    with fixture_server(PNG, TEXT) as (config, trace, accepted):
        for platform, stages in STAGES.items():
            prior = {}
            for stage in stages:
                count = len(trace)
                def before(*_):
                    assert len(trace) == count
                result, receipt, retained = exercise(config, platform, stage, prior, before=before)
                assert result["sdk_completed"], (platform, stage, result, receipt, len(trace))
                assert receipt["status"] == "confirmed", (platform, stage, receipt)
                assert len(trace) == count + 1 and len(retained) == 1
                assert retained[0][0]["attempt_id"] in accepted
                prior[stage] = receipt["result"]
        assert len(trace) == 5


@pytest.mark.parametrize("mode", ["drop", "truncated", "redirect", "oversized"])
def test_uncertain_transport_retains_evidence_without_retry(mode):
    with fixture_server(PNG, TEXT, mode=mode) as (config, trace, _):
        result, receipt, retained = exercise(config, "x", "upload", {})
        assert not result["sdk_completed"]
        assert receipt["status"] == "unknown"
        assert len(trace) == 1 and len(retained) == 1


@pytest.mark.parametrize("mode", ["error-401", "error-429", "error-500", "malformed", "wrong-id"])
def test_error_or_malformed_receipt_is_unknown_with_one_real_request(mode):
    with fixture_server(PNG, TEXT, mode=mode) as (config, trace, _):
        _, receipt, retained = exercise(config, "x", "upload", {})
        assert receipt["status"] == "unknown"
        assert len(trace) == len(retained) == 1 and retained[0][2]


def test_only_exact_fixture_nonacceptance_witness_is_not_sent():
    with fixture_server(PNG, TEXT, mode="rejected") as (config, trace, accepted):
        _, receipt, retained = exercise(config, "x", "upload", {})
        assert receipt["status"] == "not_sent" and len(trace) == 1 and len(retained) == 1 and not accepted


def test_disabled_worker_is_zero_io_and_does_not_read_clock():
    from src.commands.preview_delivery_worker import execute_delivery_once
    def refuse():
        raise AssertionError("disabled worker read clock")
    assert execute_delivery_once(None, "", "", "", None, owner="", clock=refuse)["outcome"] == "disabled"


def test_barrier_refusal_opens_no_socket():
    with fixture_server(PNG, TEXT) as (config, trace, _):
        def refuse(*_):
            raise ValueError("invented_barrier_refusal")
        result, receipt, retained = exercise(config, "x", "upload", {}, before=refuse)
        assert result == dict(sdk_completed=False, binding=None, reason="delivery_sdk_unavailable")
        assert receipt is None and retained == [] and trace == []


@pytest.mark.parametrize("failure", ["revoked", "suspended"])
def test_final_check_after_barrier_refusal_or_delayed_parent_has_no_call(failure, monkeypatch):
    real_clock = time.monotonic
    offset = [0]
    monkeypatch.setattr(transport.time, "monotonic", lambda:real_clock()+offset[0])
    with fixture_server(PNG, TEXT) as (config, trace, _):
        def check(_):
            if failure == "suspended":
                offset[0] = 60
            else:
                raise ValueError("invented_revoked_review")
        result, receipt, retained = exercise(config, "x", "upload", {}, check=check)
        assert result["binding"] is not None and not result["sdk_completed"]
        assert receipt == dict(status="not_sent", result=None)
        assert retained[0][1]["source"] == "no_call" and trace == []


def test_expired_absolute_deadline_never_launches_a_child(monkeypatch):
    with fixture_server(PNG, TEXT) as (config, trace, _):
        def refuse(*_, **__):
            raise AssertionError("expired request must not start a child")
        monkeypatch.setattr(transport.subprocess, "Popen", refuse)
        result = transport.bounded_http(config, method="POST", path=receipts.ROUTES["x", "upload"],
            body=b"invented", content_type="application/json", attempt_id="a"*64, request_sha256="b"*64,
            deadline=time.monotonic()-1)
        assert not result["complete"] and result["reason"] == "time_exceeded" and trace == []


def test_actual_child_death_after_fixture_acceptance_is_unknown_and_reaped(monkeypatch):
    child = []
    original = transport.subprocess.Popen
    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        child.append(process)
        return process
    monkeypatch.setattr(transport.subprocess, "Popen", launch)
    def kill_owned():
        os.killpg(child[0].pid, signal.SIGKILL)
    with fixture_server(PNG, TEXT, after_accept=kill_owned) as (config, trace, accepted):
        result, receipt, _ = exercise(config, "x", "upload", {})
        assert receipt["status"] == "unknown" and not result["sdk_completed"]
        assert len(trace) == len(accepted) == len(child) == 1
        assert child[0].poll() is not None


def test_stopped_child_has_no_fresh_lifetime_and_is_killed_reaped(monkeypatch):
    child = []
    original = transport.subprocess.Popen
    monkeypatch.setattr(transport, "PHASE_SECONDS", 0.4)
    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        os.killpg(process.pid, signal.SIGSTOP)
        child.append(process)
        return process
    monkeypatch.setattr(transport.subprocess, "Popen", launch)
    with fixture_server(PNG, TEXT) as (config, trace, _):
        start = time.monotonic()
        result, receipt, _ = exercise(config, "x", "upload", {})
        assert time.monotonic()-start < 1
        assert receipt["status"] == "unknown" and not result["sdk_completed"]
        assert len(child) == 1 and child[0].poll() is not None and trace == []


@pytest.mark.parametrize("mode", ["chunked_truncated", "slow_prefix"])
def test_stream_failure_retains_exact_received_prefix_and_status(mode):
    with fixture_server(PNG, TEXT, mode=mode) as (config, trace, _):
        result, receipt, retained = exercise(config, "x", "upload", {})
        assert not result["sdk_completed"] and receipt["status"] == "unknown"
        assert retained[0][2] == b"invented-prefix"
        assert retained[0][1]["http_status"] == 200 and retained[0][1]["complete"] is False
        assert len(trace) == 1


def test_late_parent_retains_original_completed_raw_response(monkeypatch):
    real_clock = time.monotonic
    offset = [0]
    monkeypatch.setattr(transport.time, "monotonic", lambda:real_clock()+offset[0])
    original = transport.subprocess.Popen
    class SuspendedParent:
        def __init__(self, *args, **kwargs):
            self.child = original(*args, **kwargs)
        def __getattr__(self, name):
            return getattr(self.child, name)
        def communicate(self, *args, **kwargs):
            output = self.child.communicate(*args, **kwargs)
            offset[0] = 60
            return output
    monkeypatch.setattr(transport.subprocess, "Popen", SuspendedParent)
    with fixture_server(PNG, TEXT) as (config, trace, accepted):
        _, receipt, retained = exercise(config, "x", "upload", {})
        assert receipt["status"] == "confirmed" and len(trace) == 1
        import base64
        proof = next(iter(accepted.values()))
        assert retained[0][2] == base64.b64decode(proof["body_base64"])


@pytest.mark.parametrize("origin", ["https://127.0.0.1:1234", "http://localhost:1234", "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://user@127.0.0.1:1234", "http://127.0.0.1:1234/"])
def test_destination_is_explicit_single_loopback_origin(origin):
    with fixture_server(PNG, TEXT) as (config, _, _):
        with pytest.raises(ValueError):
            configuration(dict(config, origin=origin))
