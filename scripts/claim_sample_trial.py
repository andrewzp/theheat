"""Refuse reruns/duplicate trial IDs using durable GitHub run metadata, no writes."""
import json
import os
from pathlib import Path
import re
import subprocess


def claim(env, api):
    identity = env["TRIAL_ID"]
    if not re.fullmatch(r"[a-f0-9]{32}", identity) or env.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("sample_trial_identity_or_attempt_invalid")
    payload = api(f"repos/{env['GITHUB_REPOSITORY']}/actions/workflows/fresh-sample-trial.yml/runs?event=workflow_dispatch&per_page=100")
    if payload["total_count"] > 100:
        raise ValueError("sample_trial_history_window_exceeded")
    matching = [row["id"] for row in payload["workflow_runs"]
                if row.get("display_title") == "Fresh sample " + identity]
    if not matching or min(matching) != int(env["GITHUB_RUN_ID"]):
        raise ValueError("sample_trial_already_claimed_or_not_observed")


if __name__ == "__main__":
    from package_sample_trial import validate_recipient
    validate_recipient(Path(os.environ["RUNNER_TEMP"]), os.environ["RECIPIENT_CERTIFICATE"])
    claim(os.environ, lambda path: json.loads(subprocess.check_output(["gh", "api", path], timeout=30)))
    print("First execution of approved trial ID; reruns and duplicates refused.")
