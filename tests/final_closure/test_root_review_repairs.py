"""Concrete checkpoint counterexamples; invented data and no external I/O."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import replace
import hashlib
import inspect
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest

from src.commands.schema import CommandError
from src.commands.sqlite_authority import SQLiteAuthority
from src.data import bounded_http, coral_dhw, meteostat_normals as mn, source_access, threshold_rebuild as rebuild
from src.orchestrator import world_cache
from src.two_bot import call_inventory as inv, copy_gates
from tests.final_closure.test_authority_gist_writers import transport as fake_gist_transport
from tests.final_closure.test_supply_normals_transport import NOW, _csv, _station, world, limits
from tests.two_bot.conftest import _bundle, configured_pipeline_providers  # noqa: F401

transport = fake_gist_transport
FALSY_METADATA: tuple[object, ...] = (None, {}, [], "")


@pytest.mark.parametrize("envelope", [{}, {"files": None}, {"files": []}, *[
    {"files": {world_cache.WORLD_CACHE_FILENAME: value}} for value in FALSY_METADATA]])
def test_malformed_gist_envelope_never_becomes_established_absence(transport, envelope):
    fake = transport([(200, json.dumps(envelope).encode())])
    assert world_cache.write_cache({}) is False
    assert fake.patches == []


def test_backup_hash_cannot_authenticate_an_uncheckpointed_wal(tmp_path):
    store = SQLiteAuthority(tmp_path / "original.sqlite")
    store.initialize({"drafts": [], "publish_ledger": {}})
    report = store.backup(tmp_path / "backup.sqlite")
    with sqlite3.connect(report["path"]) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        # Capture the standalone bytes after changing the journal header; the
        # subsequent application state exists only in WAL, under the same hash.
        raw = open(report["path"], "rb").read()
        digest = hashlib.sha256(raw).hexdigest()
        writer.execute("UPDATE authority_state SET version=19")
        writer.commit()
        assert hashlib.sha256(open(report["path"], "rb").read()).hexdigest() == digest
        with pytest.raises(CommandError, match="standalone|sidecar"):
            SQLiteAuthority(report["path"]).verify_backup(expected_sha256=digest)


def cached_provider(cancel):
    provider = mn.MeteostatBulkProvider(now=lambda: NOW)
    provider.bind(bounded_http.Limits(2, 10000, 10000, 10, 0),
                  deadline_at=__import__("time").monotonic() + 10, cancel=cancel)
    provider._stations = mn.parse_stations(_csv([_station("ZZ001", 10, 20, 100)]))[0]
    provider._files["ZZ001"] = ("ok", [(1991, 2020, m, 30.0) for m in range(1, 13)], {})
    return provider


@pytest.mark.parametrize("when", ["entry", "selection"])
def test_cached_normals_never_escape_cancellation(monkeypatch, when):
    cancel = threading.Event()
    provider = cached_provider(cancel)
    if when == "entry":
        cancel.set()
    else:
        original = mn.select_stations
        def select(*args, **kwargs):
            result = original(*args, **kwargs)
            cancel.set()
            return result
        monkeypatch.setattr(mn, "select_stations", select)
    with pytest.raises(bounded_http.TransportStop, match="cancelled"):
        provider.fetch(10, 20, 1991, 2020)


def test_normals_cancellation_after_return_never_promotes_partition_or_candidate(tmp_path, monkeypatch):
    from src.data import normals_acquisition
    cancel = threading.Event()
    provider = cached_provider(cancel)
    _cities, installed, plan = world(tmp_path, names=("Riyadh",))
    def fetch(*args):
        frame = mn.NormalsFrame({m: 30.0 for m in range(1, 13)}, {})
        cancel.set()
        return frame
    monkeypatch.setattr(provider, "fetch", fetch)
    out = tmp_path / "acquisition"
    result = normals_acquisition.acquire(plan, out, provider, limits(), installed_path=installed, cancel=cancel)
    assert result["status"] == "incomplete"
    assert not list((out / "partitions").glob("*.json"))
    assert not (out / "candidate/normals.csv").exists()


def test_actual_nested_coral_pool_preserves_parent_cancellation(monkeypatch):
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    result = {}
    monkeypatch.setattr(coral_dhw, "_fetch_regional_bytes", lambda *a, **k: (b"", {"retrieved_at": "invented"}))
    monkeypatch.setattr(coral_dhw.regional_contract, "decode_index", lambda *a, **k: (
        [SimpleNamespace(stress_level="Alert", region_id="invented")], {}))
    def station(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        try:
            inv.consume("source_http_get", join=False)
            result["late"] = "sent"
        except inv.OperationCancelled:
            result["late"] = "refused"
        finally:
            done.set()
        return SimpleNamespace()
    monkeypatch.setattr(coral_dhw, "_fetch_station_latest", station)
    def run():
        with ThreadPoolExecutor(1) as executor:
            future = inv.submit_in_context(executor, coral_dhw._fetch_coral_dhw_primary)
            assert entered.wait(5)
            token.cancel("review_deadline")
            release.set()
            future.result(5)
    token = inv.CancelToken("coral-review")
    inv.run_cancellable(token, run)
    assert done.is_set() and result["late"] == "refused"


def test_supported_danger_morphology_and_substantive_diagnosis_are_not_killed():
    bundle = replace(_bundle(), raw_signal_dump={"warning_text": "Dangerous high surf is expected along Sample Coast."})
    assert copy_gates.copy_rejection("Sample Coast faces dangerously high surf, the service warns.", bundle) is None
    assert copy_gates.copy_rejection("Sample Bay reached 31°C, a sign of coral bleaching confirmed in the survey.", bundle) is None


@pytest.mark.parametrize("evidence", [
    {"unrelated_event": {"warning_text": "Dangerous high surf"}},
    {"description": "Dangerous high surf"},
    {"warning_text": "No dangerous surf is expected."},
])
def test_arbitrary_metadata_or_negated_warning_never_provides_danger_support(evidence):
    bundle = replace(_bundle(), raw_signal_dump=evidence)
    result = copy_gates.copy_rejection("Mali faces dangerous surf.", bundle)
    assert result is not None and result.startswith("invented_danger")


@pytest.mark.usefixtures("configured_pipeline_providers")
def test_warning_paraphrase_is_uncertain_and_keeps_every_required_check(monkeypatch):
    from tests.final_closure.test_editorial_copy_gates import _writer_responds, _state
    from src.two_bot import pipeline, fact_check
    from src.two_bot.types import CriticResult, FactCheckResult
    from unittest.mock import Mock
    original = _bundle()
    bundle = replace(original, raw_signal_dump={**original.raw_signal_dump,
        "warning_text": "Strong thermal readings are expected in Mali."})
    text = "Mali thermal power is 361 MW, with dangerous readings expected."
    assert copy_gates.copy_rejection(text, bundle) is None
    assert any(note.code == "danger_wording_needs_source" for note in copy_gates.copy_notes(text, bundle))
    # Existing transport-injected parser and all required boundaries; never a
    # production model fallback. Fact and safety remain authoritative.
    _writer_responds(monkeypatch, text)
    safety = Mock(return_value=(True, None))
    factual = Mock(return_value=FactCheckResult(True, [], "offline fixture"))
    critic = Mock(return_value=CriticResult(True, None, "offline fixture"))
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety)
    monkeypatch.setattr(fact_check, "fact_check", factual)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    pipeline.generate_draft(bundle, _state())
    assert [model.call_count for model in (safety, factual, critic)] == [1, 1, 1]


@pytest.mark.parametrize("flag", [False, None])
def test_gpm_never_promises_disabled_or_unknown_backoff(flag):
    fixture = json.loads((Path(__file__).parent / "fixtures/supply_gpm_access.json").read_text())
    case = fixture["cases"]["refused_backoff"]
    state = case["state"]
    latest = max(state["run_history"], key=lambda run: run["started_at"])
    latest["runtime_inventory"] = {"schema_version": 1, "captured_at": latest["started_at"], "flags": {
        "earthdata_refusal_backoff_enabled": flag}}
    result = source_access.gpm_access_health(state, now=datetime.fromisoformat(case["as_of"].replace("Z", "+00:00")))
    assert result["stage"] != "refused_backoff" and result["backoff"] is None
    assert "retried only after" not in result["public_text"]


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_threshold_archive_cancellation_interrupts_owned_io_and_never_promotes(tmp_path, phase):
    cancel = threading.Event()
    transport = bounded_http.BoundedTransport(bounded_http.Limits(2, 1000, 1000, 5, 0),
        allowed_origins=["https://example.invalid"], cancel=cancel)
    class Response:
        status_code, headers = 200, {"Content-Length": "8", "ETag": '"one"'}
        closed = False
        def iter_content(self, **kwargs):
            yield b"half"
            cancel.set()
            time.sleep(1)
            yield b"more"
        def close(self):
            self.closed = True
    response = Response()
    class Session:
        def get(self, *args, **kwargs):
            if phase == "headers":
                cancel.set()
                time.sleep(1)
            return response
    started = time.monotonic()
    dest = tmp_path / "archive.tar.gz"
    options: dict[str, Any] = {"check": transport.check} if "check" in inspect.signature(rebuild.fetch_archive).parameters else {}
    outcome = rebuild.fetch_archive(dest, session=Session(), max_bytes=8, expected_bytes=8,
        deadline_seconds=5, max_retries=0, **options)
    assert outcome["status"] == "incomplete" and outcome["reasons"] == ["cancelled"]
    assert time.monotonic() - started < 0.8
    assert not dest.exists() and not dest.with_name(dest.name + ".receipt.json").exists()
    if phase == "body":
        assert response.closed and dest.with_name(dest.name + ".part").read_bytes() == b"half"


def test_threshold_archive_uses_remaining_whole_command_deadline(monkeypatch, tmp_path):
    from tests.final_closure.test_supply_threshold_inputs import _files, _listing
    files = _files()
    base = rebuild.BASE_URL
    def response(url, body):
        return bounded_http.Response(url, url, 200, {}, body, len(body))
    plan = rebuild.resolve_fetch_plan(response(base, _listing(files)),
        response(base + "ghcnd-version.txt", files["ghcnd-version.txt"]), base_url=base)
    class Transport:
        def get(self, url):
            return response(url, files[url.removeprefix(base)])
        def remaining(self):
            return 7.0  # Text phase has already used 53 of the 60 seconds.
        def check(self):
            pass
        def snapshot(self):
            return {}
    seen = {}
    def archive(*args, **kwargs):
        seen.update(kwargs)
        return {"status": "incomplete", "reasons": ["deadline"]}
    monkeypatch.setattr(rebuild, "fetch_archive", archive)
    rebuild.fetch_inputs(plan, tmp_path / "inputs", transport=Transport(), archive_session=object(),
        archive_deadline_seconds=60, max_retries=0)
    assert seen["deadline_seconds"] <= 7
