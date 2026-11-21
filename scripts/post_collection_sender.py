"""Default-off completion of a scheduled or verified automatic recovery cycle.

This grants no approval and never generates content. After the existing delay,
the unchanged due sender reloads Gist and applies its normal current checks,
revision/epoch, no-resend, spacing and daily limits.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

FLAG = "THEHEAT_POST_COLLECTION_SENDER"
DELAY_SECONDS = 65


def eligible(env, mode):
    automatic_catchup = (mode == "alerts"
        and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and env.get("GITHUB_ACTOR") == env.get("GITHUB_TRIGGERING_ACTOR") == "github-actions[bot]"
        and env.get("THEHEAT_AUTOMATIC_SELECTION_ONLY") == "1"
        and env.get("THEHEAT_VERIFIED_AUTOMATIC_CATCHUP") == "true")
    return (mode in {"alerts", "both"}
        and env.get(FLAG) == "1"
        and (env.get("GITHUB_EVENT_NAME") == "schedule" or automatic_catchup)
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_REPOSITORY") == "andrewzp/theheat"
        and env.get("GITHUB_WORKFLOW_REF") == "andrewzp/theheat/.github/workflows/bot.yml@refs/heads/main"
        and env.get("GITHUB_RUN_ATTEMPT") == "1"
        and bool(re.fullmatch(r"[1-9][0-9]{0,19}", env.get("GITHUB_RUN_ID", "")))
        and env.get("THEHEAT_PRODUCTION_PAUSED", "0") == "0"
        and env.get("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED") == "1"
        and env.get("THEHEAT_AUTOSHIP_ON_CRITIC_PASS") == "1"
        and env.get("THEHEAT_MAX_DRAFTS_PER_CYCLE") == "1"
        and env.get("THEHEAT_WRITER_SAMPLES", "1") == "1"
        and env.get("THEHEAT_REFILL_ENABLED", "0") == "0"
        and env.get("THEHEAT_CRITIC_REVISE_ENABLED", "0") == "0")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", required=True, choices=("alerts", "both", "metar_report", "observed_report",
                                                       "leaderboard", "auto_publish_due", "manual_tweet"))
    args = parser.parse_args(argv)
    if not eligible(os.environ, args.mode):
        print("Post-collection sender: inactive for this context.")
        return 0
    time.sleep(DELAY_SECONDS)
    if not eligible(os.environ, args.mode):
        print("Post-collection sender: context changed; held.")
        return 0
    # No cached state, draft IDs, text, approval or bypass arguments. The child
    # uses the same existing sender environment and its own fresh state read.
    return subprocess.run([sys.executable, "-m", "src.main", "auto_publish_due"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
