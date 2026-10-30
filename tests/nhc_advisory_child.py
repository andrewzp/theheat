"""Fresh-process bootstrap for the NHC advisory journey (test-only).

Usage: ``python -m tests.nhc_advisory_child CONFIG.json`` from the checkout. It runs
ONE actual entrypoint (``scripts/nhc_advisory_trial.py``, ``scripts/nhc_advisory_import.py``
or ``python -m src.main manual_tweet``) at a frozen, ticking instant. Named fake
boundaries only, recorded to the config's record file:

- HTTP: requests' transport adapter serves the invented NHC products (the two fixed
  URLs), the invented Gist and the invented X create endpoint from the journey
  directory. Any other URL, and every raw socket connection, is refused.
- GitHub CLI: an invented ``gh`` executable on PATH (the importer's own transport).
- Models: the Gemini SDK client factory answers the safety check offline; for a trial
  execute, the writer/fact-check/critic stage functions are offline stubs that still
  dispatch through the real ``trial_budget.provider_call`` boundary (reservation and
  the live NHC guard).
- The shared trial-claim directory is redirected into the journey directory.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import runpy
import socket
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

NHC_ORIGIN = "https://www.nhc.noaa.gov"
X_CREATE = "https://api.twitter.com/2/tweets"
COPY = "Up to 3 inches of rain could trigger flash flooding and mudslides in Example Province tonight, NHC forecasts."


def _refuse(*_args, **_kwargs):
    raise AssertionError("external connection trapped")


def main(config_path: str) -> None:
    config = json.loads(Path(config_path).read_text())
    root, record_path = Path(config["dir"]), Path(config["record"])
    record: dict = {"http": [], "nhc": [], "x": [], "gist_patches": 0, "models": [], "stages": []}
    socket.socket.connect = _refuse  # type: ignore[method-assign]
    import requests
    from requests.structures import CaseInsensitiveDict

    def reply(request, status: int, body: bytes, headers: dict | None = None):
        response = requests.models.Response()
        response.status_code, response.url, response.request = status, request.url, request
        response.reason = {200: "OK", 201: "Created"}.get(status, "Invented")
        response.headers = CaseInsensitiveDict({"content-length": str(len(body)), **(headers or {})})
        response.raw, response.encoding = io.BytesIO(body), None
        return response

    pages = {"count": 0}
    gist_url = f"https://api.github.com/gists/{os.environ.get('GIST_ID', '')}"

    def send(adapter, request, **_options):
        url, method = request.url, request.method
        record["http"].append([method, url])
        if url.startswith(NHC_ORIGIN + "/"):
            assert method == "GET" and urlsplit(url).path in ("/CurrentStorms.json", "/text/MIATCPEP5.shtml")
            record["nhc"].append(url)
            if url.endswith("/CurrentStorms.json"):
                return reply(request, 200, (root / "nhc/index.json").read_bytes(), {"content-type": "application/json"})
            pages["count"] += 1
            switch = config.get("nhc_switch_after_pages")
            name = "nhc/page-corrected.html" if switch is not None and pages["count"] > switch else "nhc/page.html"
            return reply(request, 200, (root / name).read_bytes(), {"content-type": "text/html"})
        if url == gist_url:
            gist = root / "gist"
            if method == "GET":
                files = {p.name: {"content": p.read_text(), "truncated": False} for p in sorted(gist.iterdir())}
                return reply(request, 200, json.dumps({"files": files}).encode())
            assert method == "PATCH"
            for name, value in json.loads(request.body)["files"].items():
                (gist / name).write_text(value["content"])
            record["gist_patches"] += 1
            return reply(request, 200, b"{}")
        if url == X_CREATE and method == "POST":
            text = json.loads(request.body)["text"]
            record["x"].append(["create", text])
            if config.get("x_failure") == "create_lost":
                raise requests.ConnectionError("invented create response lost")
            return reply(request, 201, json.dumps({"data": {"id": "invented-x-receipt", "text": text}}).encode())
        raise AssertionError(f"unallowed invented-transport request: {method} {url}")

    requests.adapters.HTTPAdapter.send = send  # type: ignore[method-assign]
    # The production adapter now owns a credential-free subprocess for its hard
    # HTTP deadline. This invented journey explicitly replaces that transport
    # boundary so a grandchild cannot escape this process's socket/SDK traps.
    # The owned-process deadline has separate real-child tests; this journey
    # still exercises the adapter's one-request HTTP implementation and guards.
    from src.data import nhc_advisory as nhc_source
    nhc_source._http_get = nhc_source._http_get_inprocess

    from google import genai

    class _Models:
        def generate_content(self, **request):
            record["models"].append(["google", request.get("model")])
            # Explicit invented offline safety verdict: "NO" = not harmful.
            return SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP", safety_ratings=None)],
                                   prompt_feedback=None, text="NO", usage_metadata=None)

    class _Client:
        def __init__(self, *_args, **_kwargs):
            self.models = _Models()

        def close(self):
            return None

    genai.Client = _Client  # type: ignore[misc,assignment]

    import subprocess
    real_check_output = subprocess.check_output

    def check_output(args, *a, **k):
        if list(args) == ["git", "rev-parse", "--git-common-dir"]:
            return str(root / "claims-common" / ".git")
        return real_check_output(args, *a, **k)
    subprocess.check_output = check_output  # type: ignore[assignment]

    if config.get("stages"):
        _stub_stages(record, config)

    from freezegun import freeze_time
    sys.argv = [config["target"], *config["argv"]]
    code = 0
    with freeze_time(config["now"], tick=True):
        try:
            if config["kind"] == "module":
                runpy.run_module(config["target"], run_name="__main__", alter_sys=True)
            else:
                runpy.run_path(config["target"], run_name="__main__")
        except SystemExit as exc:
            code = exc.code if type(exc.code) is int else 1
        finally:
            record["exit"] = code
            record["media_modules"] = sorted(k for k in sys.modules if k.startswith("src.media.gist"))
            record_path.write_text(json.dumps(record))


def _stub_stages(record: dict, config: dict) -> None:
    """Writer, fact-check and critic: explicit offline stubs behind the real provider boundary."""
    from src.two_bot import pipeline, trial_budget
    from src.two_bot.trial_budget import MODELS
    from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
    requests = {"writer": ("anthropic", {"messages": [{"role": "user", "content": "invented"}], "max_tokens": 1024}),
                "fact_check": ("google", {"contents": "invented", "config": {}}),
                "critic": ("google", {"contents": "invented", "config": {}})}

    def via(stage, result):
        provider, request = requests[stage]

        def send(**_bounded):
            record["stages"].append(stage)
            return object()

        def run(*_args, **_kwargs):
            trial_budget.provider_call(stage, provider, {"model": MODELS[stage][1], **request}, send)
            return result
        return run
    pipeline.writer.write_tweet = via("writer", WriterResult(  # type: ignore[assignment]
        config.get("copy", COPY), None, "warning_consequence", None, None, "Explicit invented offline model response."))
    pipeline.fact_check.fact_check = via("fact_check", FactCheckResult(True, [], "Explicit offline check."))  # type: ignore[assignment]
    pipeline.critic.critic_review = via("critic", CriticResult(True, None, "Explicit offline critic."))  # type: ignore[assignment]


if __name__ == "__main__":
    main(sys.argv[1])
