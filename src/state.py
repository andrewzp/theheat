"""State management via GitHub Gist."""

import json
import os
from datetime import date, datetime

import requests


GIST_ID = os.environ.get("GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
STATE_FILENAME = "state.json"

DEFAULT_STATE = {
    "last_hot10": {"date": None, "cities": []},
    "streaks": {},
    "posted_events": [],
    "daily_tweet_count": {},
    "pending_confirmations": [],
    "errors": [],
}


def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def read_state() -> dict:
    if not GIST_ID or not GITHUB_TOKEN:
        return dict(DEFAULT_STATE)

    try:
        resp = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        gist = resp.json()
        content = gist["files"][STATE_FILENAME]["content"]
        return json.loads(content)
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)


def write_state(state: dict) -> bool:
    if not GIST_ID or not GITHUB_TOKEN:
        return False

    try:
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException:
        return False


def is_duplicate(state: dict, event_id: str) -> bool:
    return event_id in state.get("posted_events", [])


def record_event(state: dict, event_id: str) -> dict:
    state.setdefault("posted_events", []).append(event_id)
    # Keep only last 500 events to prevent unbounded growth
    if len(state["posted_events"]) > 500:
        state["posted_events"] = state["posted_events"][-500:]
    return state


def get_daily_count(state: dict) -> int:
    today = date.today().isoformat()
    return state.get("daily_tweet_count", {}).get(today, 0)


def increment_daily_count(state: dict) -> dict:
    today = date.today().isoformat()
    counts = state.setdefault("daily_tweet_count", {})
    counts[today] = counts.get(today, 0) + 1
    # Clean up old days
    for d in list(counts.keys()):
        if d != today:
            del counts[d]
    return state


def check_daily_cap(state: dict, cap: int = 10) -> bool:
    return get_daily_count(state) < cap


def update_streaks(state: dict, hot10_cities: list[str]) -> dict:
    today = date.today().isoformat()
    streaks = state.setdefault("streaks", {})

    for city in hot10_cities:
        if city in streaks and streaks[city]["last_seen"] >= today:
            continue
        if city in streaks:
            prev = datetime.fromisoformat(streaks[city]["last_seen"]).date()
            current = date.today()
            gap = (current - prev).days
            if gap <= 1:
                streaks[city]["consecutive_days"] += 1
            else:
                streaks[city]["consecutive_days"] = 1
            streaks[city]["last_seen"] = today
        else:
            streaks[city] = {"consecutive_days": 1, "last_seen": today}

    for city in list(streaks.keys()):
        if city not in hot10_cities:
            prev = datetime.fromisoformat(streaks[city]["last_seen"]).date()
            if (date.today() - prev).days > 1:
                del streaks[city]

    return state


def log_error(state: dict, source: str, msg: str) -> dict:
    errors = state.setdefault("errors", [])
    errors.append({
        "source": source,
        "ts": datetime.utcnow().isoformat(),
        "msg": str(msg)[:200],
    })
    # Keep last 50 errors
    if len(errors) > 50:
        state["errors"] = errors[-50:]
    return state
