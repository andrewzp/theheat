#!/usr/bin/env python3
"""Publish configuration evidence to one Gist file; never generate or publish content."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FILENAME = "runtime-inventory.json"
MAX_BYTES = 128 * 1024


class ReportError(RuntimeError):
    pass


def encode(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def build_report(env: dict[str, str], *, now: datetime | None = None) -> dict:
    from src.runtime_inventory import collect_runtime_inventory
    if (env.get("GITHUB_REF") != "refs/heads/main" or env.get("THEHEAT_PRODUCTION_PAUSED") != "1"
            or env.get("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0") == "1"):
        raise ReportError("runtime_report_requires_pause")
    sha, run, attempt = (env.get(k, "") for k in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
    if (sha != env.get("EXPECTED_COMMIT_SHA") or not re.fullmatch(r"[a-f0-9]{40}", sha)
            or not re.fullmatch(r"[0-9]{1,32}", run) or not re.fullmatch(r"[1-9][0-9]{0,5}", attempt)):
        raise ReportError("runtime_report_identity_invalid")
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ReportError("runtime_report_clock_invalid")
    # This existing collector reads loaded constants; it never calls models or sources.
    snapshot = collect_runtime_inventory("runtime_report", now=at)
    policy = snapshot.get("editorial_policy")
    if (not policy or policy["flags"]["writer_samples"] != 1
            or policy["flags"]["critic_revise_enabled"] is not False
            or policy["flags"]["critic_enabled"] is not True
            or snapshot["git_sha"] != sha or snapshot["github_run_id"] != run
            or snapshot["flags"]["automatic_publication_enabled"] is not False):
        raise ReportError("runtime_report_loaded_profile_invalid")
    snapshot["flags"] = {k: snapshot["flags"][k] for k in (
        "writer_samples", "critic_enabled", "critic_revise_enabled", "automatic_publication_enabled")}
    # Unloaded platform/source credentials are unknown, not absent. No posting keys enter this job.
    snapshot["credentials_present"] = {k: snapshot["credentials_present"][k] for k in (
        "anthropic", "gemini", "safety_gemini", "github_state")}
    snapshot["capabilities"] = {"safety_llm": snapshot["capabilities"]["safety_llm"]}
    result = {"schema_version": 1, "kind": "configuration_only", "id": f"config-{run}-{attempt}",
              "run_attempt": int(attempt), "started_at": snapshot["captured_at"],
              "collection_paused": True, "runtime_inventory": snapshot}
    if len(encode(result).encode()) > MAX_BYTES:
        raise ReportError("runtime_report_size_limit")
    return result


def read_report(file) -> dict | None:
    if file is None:
        return None
    if not isinstance(file, dict):
        raise ReportError("runtime_report_existing_file_invalid")
    content = file.get("content")
    if file.get("truncated") or not isinstance(content, str) or len(content.encode()) > MAX_BYTES:
        raise ReportError("runtime_report_existing_file_unavailable")
    try:
        value = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise ReportError("runtime_report_existing_file_invalid") from exc
    if (not isinstance(value, dict) or value.get("kind") != "configuration_only"
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1):
        raise ReportError("runtime_report_existing_file_invalid")
    return value


def publish_report(report: dict, api) -> dict:
    content = encode(report)
    current = read_report(api("GET", None))
    if current:
        if current.get("id") == report["id"]:
            if current != report:
                raise ReportError("runtime_report_identity_conflict")
            return {"status": "already_confirmed", "report_id": report["id"]}
        try:
            newer = datetime.fromisoformat(current["started_at"].replace("Z", "+00:00"))
            captured = datetime.fromisoformat(report["started_at"].replace("Z", "+00:00"))
            if newer >= captured:
                raise ReportError("runtime_report_newer_evidence_exists")
        except (KeyError, ValueError, TypeError) as exc:
            raise ReportError("runtime_report_existing_clock_invalid") from exc
    # The fixed single-file PATCH cannot include state.json, drafts, approvals or ledgers.
    payload = {"files": {FILENAME: {"content": content}}}
    try:
        api("PATCH", payload)
    except Exception:
        pass  # One readback may confirm a lost acknowledgment; never resend the PATCH.
    try:
        observed = read_report(api("GET", None))
    except Exception as exc:
        raise ReportError("runtime_report_write_unconfirmed") from exc
    if observed != report:
        raise ReportError("runtime_report_write_unconfirmed")
    return {"status": "confirmed", "report_id": report["id"],
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "state_json_written": False, "provider_calls": 0}


def github_api(gist: str, env: dict[str, str]):
    child = dict(env, GH_TOKEN=env["GITHUB_TOKEN"])
    def call(method: str, payload):
        if method == "GET":
            args = ["gh", "api", "--hostname", "github.com", f"gists/{gist}",
                    "--jq", f'{{runtime_report_file:(.files["{FILENAME}"] // null)}}']
            data = None
        elif (method == "PATCH" and isinstance(payload, dict) and set(payload) == {"files"}
              and isinstance(payload["files"], dict) and set(payload["files"]) == {FILENAME}
              and isinstance(payload["files"][FILENAME], dict) and set(payload["files"][FILENAME]) == {"content"}
              and isinstance(payload["files"][FILENAME]["content"], str)
              and len(payload["files"][FILENAME]["content"].encode()) <= MAX_BYTES):
            args = ["gh", "api", "--hostname", "github.com", "--method", "PATCH", f"gists/{gist}",
                    "--input", "-", "--silent"]
            data = json.dumps(payload)
        else:
            raise ReportError("runtime_report_disallowed_operation")
        response = subprocess.run(args, input=data, text=True, capture_output=True, timeout=30, env=child, check=True)
        if len(response.stdout.encode()) > MAX_BYTES * 2:
            raise ReportError("runtime_report_response_size_limit")
        if method == "GET":
            try:
                envelope = json.loads(response.stdout)
            except (TypeError, ValueError) as exc:
                raise ReportError("runtime_report_response_invalid") from exc
            if (not isinstance(envelope, dict) or set(envelope) != {"runtime_report_file"}
                    or envelope["runtime_report_file"] is not None and not isinstance(envelope["runtime_report_file"], dict)):
                raise ReportError("runtime_report_response_invalid")
            return envelope["runtime_report_file"]
        return None
    return call


def main() -> int:
    try:
        env = dict(os.environ)
        gist = env.get("GIST_ID", "")
        if not re.fullmatch(r"[a-f0-9]{20,64}", gist) or not env.get("GITHUB_TOKEN"):
            raise ReportError("runtime_report_storage_unconfigured")
        result = publish_report(build_report(env), github_api(gist, env))
        print(json.dumps(result))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, ReportError) else type(exc).__name__
        print(json.dumps({"status": "unconfirmed", "reason": code, "no_automatic_retry": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
