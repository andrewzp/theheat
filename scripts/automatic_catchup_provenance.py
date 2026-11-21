"""Read-only admission of an automatic sentinel dispatch to cycle completion.

This matches GitHub's built-in child context to a successful scheduled sentinel
dispatch on the same revision. It grants no draft approval or provider access.
Unknown evidence holds completion; the normal collector and sender keep their
existing independent gates. No weather source, model, Gist or social-publishing
API is called.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import http.client
import json
import math
import os
import re
from typing import Any, Mapping

REPOSITORY = "andrewzp/theheat"
BOT_WORKFLOW = f"{REPOSITORY}/.github/workflows/bot.yml@refs/heads/main"
PARENT_WORKFLOW = ".github/workflows/source-health-sentinel.yml"
DISPATCH_STEP = "Dispatch one alerts run when the lane is stale"
MAX_BYTES = 65536
MAX_PARENT_AGE = timedelta(minutes=30)
UTC = timezone.utc
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise ValueError("timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def context_eligible(env: Mapping[str, str]) -> bool:
    parent, child = env.get("THEHEAT_AUTOMATIC_CATCHUP_RUN_ID", ""), env.get("GITHUB_RUN_ID", "")
    return (env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_REPOSITORY") == REPOSITORY
        and env.get("GITHUB_WORKFLOW_REF") == BOT_WORKFLOW
        and env.get("GITHUB_RUN_ATTEMPT") == "1"
        and env.get("GITHUB_ACTOR") == env.get("GITHUB_TRIGGERING_ACTOR") == "github-actions[bot]"
        and env.get("THEHEAT_AUTOMATIC_SELECTION_ONLY") == "1"
        and env.get("REQUESTED_MODE") == "alerts"
        and bool(_ID.fullmatch(parent)) and bool(_ID.fullmatch(child)) and parent != child
        and bool(_SHA.fullmatch(env.get("GITHUB_SHA", ""))))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite")
    return result


def _constant(value):
    raise ValueError("nonfinite")


def _get(path: str, token: str) -> dict:
    # Fixed host and numeric path segments only. http.client has neither a
    # redirect handler nor automatic retries/proxy discovery.
    connection = http.client.HTTPSConnection("api.github.com", timeout=5)
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "theheat-automatic-catchup-provenance"})
        response = connection.getresponse()
        if response.status != 200 or response.getheader("Content-Encoding", "identity") != "identity":
            raise ValueError("http")
        if response.getheader("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("content_type")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("size")
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant, parse_float=_float)
        if not isinstance(value, dict):
            raise ValueError("object")
        return value
    finally:
        connection.close()


def verify(env: Mapping[str, str], *, now: datetime | None = None) -> bool:
    """At most two metadata GETs; every refusal returns false without echoing input."""
    if not context_eligible(env) or not env.get("GH_TOKEN"):
        return False
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        return False
    parent_id, sha = int(env["THEHEAT_AUTOMATIC_CATCHUP_RUN_ID"]), env["GITHUB_SHA"]
    base = f"/repos/{REPOSITORY}/actions/runs/{parent_id}"
    try:
        parent = _get(base, env["GH_TOKEN"])
        if not (type(parent.get("id")) is int and parent["id"] == parent_id
                and parent.get("repository", {}).get("full_name") == REPOSITORY
                and parent.get("head_repository", {}).get("full_name") == REPOSITORY
                and parent.get("head_branch") == "main" and parent.get("head_sha") == sha
                and parent.get("path") == PARENT_WORKFLOW and parent.get("event") == "schedule"
                and type(parent.get("run_attempt")) is int and parent["run_attempt"] == 1):
            return False
        created = _time(parent.get("created_at"))
        if not timedelta(0) <= instant - created <= MAX_PARENT_AGE:
            return False
        listing = _get(base + "/attempts/1/jobs?per_page=100", env["GH_TOKEN"])
        count, jobs = listing.get("total_count"), listing.get("jobs")
        if type(count) is not int or not 1 <= count <= 100 or not isinstance(jobs, list) or len(jobs) != count:
            return False
        if any(not isinstance(job, dict) or type(job.get("id")) is not int for job in jobs):
            return False
        if len({job["id"] for job in jobs}) != count:
            return False
        matching = [job for job in jobs if job.get("name") == "alerts-catchup"]
        if len(matching) != 1:
            return False
        job = matching[0]
        if not (type(job.get("run_id")) is int and job["run_id"] == parent_id
                and job.get("head_sha") == sha and job.get("status") == "completed"
                and job.get("conclusion") == "success" and isinstance(job.get("steps"), list)):
            return False
        if any(not isinstance(step, dict) for step in job["steps"]):
            return False
        steps = [step for step in job["steps"] if step.get("name") == DISPATCH_STEP]
        if len(steps) != 1 or steps[0].get("status") != "completed" or steps[0].get("conclusion") != "success":
            return False
        step = steps[0]
        return (created <= _time(job.get("started_at")) <= _time(step.get("started_at"))
                <= _time(step.get("completed_at")) <= _time(job.get("completed_at")) <= instant)
    except (ValueError, TypeError, AttributeError, RecursionError, OSError, http.client.HTTPException):
        return False


def main() -> int:
    eligible = verify(os.environ)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"eligible={'true' if eligible else 'false'}\n")
    print("Automatic catch-up completion: " + ("verified." if eligible else "held."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
