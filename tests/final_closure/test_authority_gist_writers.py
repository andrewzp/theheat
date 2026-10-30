"""E1 — every production Gist writer is inventoried with its actual guard, and the
direct world-cache writer refuses instead of replacing retained data.

Invented cache rows and a fake GitHub transport; no network, no Gist.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
import requests

from src.commands import writer_fencing as fencing
from src.orchestrator import world_cache
from src.two_bot import call_inventory as inv

ROOT = Path(__file__).resolve().parents[2]
# Primitive -> files that may contain it. Each file must have an inventory row.
PY_GIST_WRITE = re.compile(r"\bwrite_state\(|requests\.patch\(|--method\", \"PATCH|api\(\"PATCH\"")
JS_GIST_WRITE = re.compile(r"method:\s*\"PATCH\"")


def _inventory_files() -> set[str]:
    files = set()
    for row in fencing.WRITERS:
        site = row.call_site.split(":", 1)[0]
        files.add(site if "/" in site else site.replace(".", "/") + ".py")
    return files


def test_every_file_with_a_gist_write_primitive_has_an_inventory_row():
    found = set()
    for base in ("src", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            text = path.read_text()
            if PY_GIST_WRITE.search(text) and "gists" in text or re.search(r"\bwrite_state\(", text):
                found.add(str(path.relative_to(ROOT)))
    for base in ("dashboard/lib", "dashboard/app"):
        for path in (ROOT / base).rglob("*.js"):
            if JS_GIST_WRITE.search(path.read_text()):
                found.add(str(path.relative_to(ROOT)))
    # The state module defines the writer; the SQLite store is not the Gist.
    found -= {"src/storage/sqlite_store.py"}
    assert found - _inventory_files() == set(), "Gist writer without an inventory row"
    # The writers named by the closure review are present with their real guards.
    names = {row.name: row for row in fencing.WRITERS}
    for name in ("dashboard_reconciliation", "world_threshold_cache", "runtime_report", "reject_all_drafts",
                 "bot_run_final_save", "publish_intent", "post_feedback"):
        assert name in names and names[name].fenced is False


def test_cutover_stays_blocked_while_any_gist_writer_remains():
    result = fencing.compatibility("command_authority_postgres")
    blocked = {row["writer"] for row in result["blockers"] if row["code"] == "gist_writer_not_rerouted"}
    assert not result["compatible"] and result["activation"] == "not_performed" and not result["gist_transactional"]
    assert {"world_threshold_cache", "runtime_report", "post_feedback", "dashboard_reconciliation"} <= blocked


class _Transport:
    def __init__(self, get_outcomes):
        self.get_outcomes, self.patches = list(get_outcomes), []

    def get(self, url, **_kwargs):
        outcome = self.get_outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        response = requests.Response()
        response.status_code, response._content = outcome
        return response

    def patch(self, url, json=None, **_kwargs):
        self.patches.append(json)
        response = requests.Response()
        response.status_code, response._content = 200, b"{}"
        return response


def _gist(files):
    return 200, json.dumps({"files": files}).encode()


@pytest.fixture
def transport(monkeypatch):
    holder = {}

    def install(outcomes):
        holder["t"] = _Transport(outcomes)
        monkeypatch.setattr(world_cache, "GIST_ID", "invented-gist")
        monkeypatch.setattr(world_cache, "GITHUB_TOKEN", "invented-not-a-credential")
        monkeypatch.setattr(world_cache.requests, "get", holder["t"].get)
        monkeypatch.setattr(world_cache.requests, "patch", holder["t"].patch)
        return holder["t"]
    return install


@pytest.mark.parametrize("failure", [requests.ConnectionError("invented"), (500, b"{}"), (200, b"not json"),
                                     "truncated_raw_failure", "non_object"])
def test_an_unreadable_remote_cache_is_never_replaced(transport, failure):
    """Counterexample on the released base: a failed read became {} and the PATCH replaced the cache."""
    if failure == "truncated_raw_failure":
        outcomes = [_gist({world_cache.WORLD_CACHE_FILENAME: {"truncated": True, "raw_url": "https://invented.invalid/raw"}}),
                    requests.Timeout("invented")]
    elif failure == "non_object":
        outcomes = [_gist({world_cache.WORLD_CACHE_FILENAME: {"content": "[1, 2]"}})]
    else:
        outcomes = [failure]
    fake = transport(outcomes)
    assert world_cache.write_cache({"invented-key": {"invented": 1}}) is False
    assert fake.patches == []


def test_an_absent_cache_file_is_empty_and_every_request_is_counted(transport):
    fake = transport([_gist({})])
    before = inv.runtime_counts().get("gist_state", 0)
    assert world_cache.write_cache({}) is True
    assert len(fake.patches) == 1 and world_cache.WORLD_CACHE_FILENAME in fake.patches[0]["files"]
    assert inv.runtime_counts()["gist_state"] == before + 2  # One GET and one PATCH, never free.


def test_read_cache_keeps_its_lenient_reader_contract(transport):
    transport([requests.ConnectionError("invented")])
    assert world_cache.read_cache() == {}
