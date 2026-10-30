"""Fresh-process manual sender for the two-consumer journeys (test-only bootstrap).

Usage: ``python -m tests.gist_two_consumer_sender CONFIG.json`` from the checkout.
It runs the actual ``python -m src.main manual_tweet`` CLI (argument parsing, Gist
state read, the manual sender, final state write). Named fake boundaries only: the
Gist HTTP API (one local JSON file shared with the test), the X SDK factories, the
final safety model stub, the radar NWS recheck and Bluesky (refused). The media
store is whatever THEHEAT_MEDIA_STORE selects: the real local SQLite store or the
PostgreSQL adapter over the OFFLINE protocol fixture (never a PostgreSQL server).
No network: every socket connection is refused.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import socket
import sys
from types import SimpleNamespace


def _refuse(*_args, **_kwargs):
    raise AssertionError("external connection trapped")


class _Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def main(config_path):
    config = json.loads(Path(config_path).read_text())
    socket.socket.connect = _refuse  # type: ignore[method-assign]
    if os.environ.get("THEHEAT_TEST_PG_PROTOCOL_FILE"):
        from tests import gist_pg_protocol_fixture
        gist_pg_protocol_fixture.install()
    import pytest
    import requests
    from freezegun import freeze_time

    patch = pytest.MonkeyPatch()
    gist, out = Path(config["gist_file"]), Path(config["out"])
    gist_url = f"https://api.github.com/gists/{os.environ['GIST_ID']}"
    record = {"calls": [], "patches": 0, "intent_before_upload": None, "failure": config.get("failure")}

    def get(url, headers=None, timeout=None, **_options):
        assert url == gist_url, "only the invented Gist is readable"
        return _Response({"files": {"state.json": {"content": gist.read_text(), "truncated": False}}})

    def patch_gist(url, headers=None, json=None, timeout=None, **_options):
        assert url == gist_url and list(json["files"]) == ["state.json"]
        if config.get("gist_write_failure") and record["patches"] >= config["gist_write_failure"]:
            return _Response({}, 502)
        gist.write_text(json["files"]["state.json"]["content"])
        record["patches"] += 1
        after = config.get("fault_after_intent")
        if after and record.get("reads_at_intent") is None and '"phase":"submitted"' in json["files"]["state.json"]["content"]:
            from tests import gist_pg_protocol_fixture as fixture
            record["reads_at_intent"] = fixture.counter(os.environ[fixture.ENV], "payload_reads")
            fixture.set_fault(os.environ[fixture.ENV], after)  # The store fails after the durable intent.
        return _Response({})

    patch.setattr(requests, "get", get)
    patch.setattr(requests, "patch", patch_gist)

    from src.orchestrator import common, nws_publication
    from src.posting import twitter

    failure = config.get("failure")

    def upload(*, filename, file, **_options):
        saved = json.loads(gist.read_text())
        record["intent_before_upload"] = saved["publish_ledger"].get(config["event_id"], {}).get("phase")
        data = file.read()
        (out.parent / "uploaded.png").write_bytes(data)
        record["calls"].append(["upload", hashlib.sha256(data).hexdigest(), filename])
        if failure == "upload":
            raise TimeoutError("invented upload response lost")
        return SimpleNamespace(media_id=98765)

    def alt(media_id, text, **_options):
        record["calls"].append(["alt", media_id, text])
        if failure == "alt":
            raise TimeoutError("invented alt response lost")

    def create(*, text, **options):
        record["calls"].append(["create", text, options])
        if failure == "create":
            raise TimeoutError("invented create response lost")
        if failure == "empty_receipt":
            return SimpleNamespace(data={})
        return SimpleNamespace(data={"id": "invented-x-receipt"})

    patch.setattr(twitter, "_get_client", lambda: SimpleNamespace(create_tweet=create))
    patch.setattr(twitter, "_get_upload_api", lambda: SimpleNamespace(media_upload=upload, create_media_metadata=alt))
    # src.main re-syncs these compatibility names from common into the split modules.
    patch.setattr(common, "run_safety_pipeline", lambda *_a, **_k: (True, None))
    patch.setattr(common, "post_to_bluesky", _refuse)
    features = config.get("nws_features") or ([config["nws_feature"]] if config.get("nws_feature") else None)
    if features:
        patch.setattr(nws_publication, "_active_feed", lambda: {"features": features})

    sys.argv = ["src.main", "manual_tweet"]
    code = 0
    with freeze_time(config["now"]):
        try:
            runpy.run_module("src.main", run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            code = exc.code if type(exc.code) is int else 1
    record.update(exit=code, psycopg="psycopg" in sys.modules,
                  postgres_adapter="src.media.gist_assets_postgres" in sys.modules)
    if os.environ.get("THEHEAT_TEST_PG_PROTOCOL_FILE"):
        from tests import gist_pg_protocol_fixture as fixture
        record["reads_at_end"] = fixture.counter(os.environ[fixture.ENV], "payload_reads")
    out.write_text(json.dumps(record))


if __name__ == "__main__":
    main(sys.argv[1])
