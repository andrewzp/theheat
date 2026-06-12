from __future__ import annotations

"""SQLite-backed persistence for bot state snapshots."""

import json
import sqlite3
from pathlib import Path

from src.two_bot.json_utils import json_default


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posted_events (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS daily_tweet_count (
    day TEXT PRIMARY KEY,
    count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS streaks (
    city TEXT PRIMARY KEY,
    consecutive_days INTEGER NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    event_id TEXT,
    type TEXT,
    status TEXT,
    created_at TEXT,
    approved_at TEXT,
    posted_at TEXT,
    auto_approve_at TEXT,
    approval_mode TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    mode TEXT,
    status TEXT,
    started_at TEXT,
    ended_at TEXT,
    source_count INTEGER,
    failure_count INTEGER,
    drafted_count INTEGER,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_runs (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    source TEXT,
    status TEXT,
    duration_ms INTEGER,
    observed INTEGER,
    promoted INTEGER,
    drafted INTEGER,
    error TEXT,
    note TEXT,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS errors (
    seq INTEGER PRIMARY KEY,
    source TEXT,
    ts TEXT,
    msg TEXT,
    payload_json TEXT NOT NULL
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"), default=json_default)


# Lane-added state keys that weren't in the original sqlite schema.
# Rather than growing the schema once per new key, these round-trip via
# the ``metadata`` key-value table as JSON blobs. Order-sensitive: the
# first seven are the Apr 18 extreme-signals state, then lanes 1-4 in
# merge order.
_METADATA_JSON_KEYS = (
    "co2_annual_count",
    "ch4_annual_count",
    "ch4_last_milestone",
    "nao_annual_count",
    "ao_annual_count",
    "pdo_annual_count",
    "nao_last_phase",
    "ao_last_phase",
    "pdo_last_phase",
    "ozone_hole_last_peak",
    "ozone_hole_annual_count",
    "city_all_time_max",
    "city_all_time_min",
    "city_monthly_max",
    "city_monthly_min",
    "record_streaks",
    "ocean_sst_streak",
    "ice_mass_max_loss",
    "ice_mass_last_milestone",
    "ice_mass_last_seen",
    "ice_annual_count",
    "precip_daily_records",
    "precip_recent_by_city",
    "snow_daily_swe_gain_records",
    "snow_recent_by_station",
    "snow_annual_count",
    "seasonal_snow_records",
    "fire_complex_tiers",
    "coral_dhw_last_tier",
    "coral_dhw_annual_count",
    # Air-quality per-city tier dedup (PR #194) — must persist, else a SQLite
    # load drops the per-city tier guard and re-fires the same AQ tier.
    "air_quality_pm25_tiers",
    "air_quality_dust_tiers",
    # Regional SST anomaly dedup (PR #198) — both must persist, else a
    # SQLite-sourced load drops the per-region tier guard + per-year count,
    # re-firing the same basin tier or resetting the annual counter.
    "sst_anom_last_tier",
    "sst_anom_annual_count",
    "cyclone_tiers",
    "cyclone_wind_history",
    "cyclone_annual_count",
    "flood_activation_tiers",
    "tier_touch_ts",
    "flood_annual_count",
    "fire_footprint_last_run",
    "synthesis_components",
    "synthesis_cooldown",
    "suppressions",
    # The two-bot repetition guard (memory.shipped_tweet_texts +
    # used_era_anchors + used_peer_comparisons) AND the structural
    # source-failure counters were both lost on every sqlite-backed
    # round-trip. Found 2026-05-08 via codex review.
    "memory",
    "data_source_failures",
    "source_health",
    # Reanalysis regional-anomaly onset guard — must persist (§E) so a sustained
    # spell stays suppressed across restarts. The transient _reganom_live_cache is
    # intentionally absent (like _triage_queue): it is rebuilt each cycle.
    "reganom_last_fired",
    # NOTE: bot_state["_triage_queue"] is intentionally NOT in this list.
    # The triage queue is a per-cron transient; persisting it would cause
    # stale candidates to re-process next cycle. Guard pair: pop-at-entry
    # in run_alerts.py + absence from this list. See spec § 6.
)


def is_empty(db_path: str) -> bool:
    with _connect(db_path) as conn:
        counts = [
            conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            for table in (
                "metadata",
                "posted_events",
                "daily_tweet_count",
                "streaks",
                "drafts",
                "runs",
                "errors",
            )
        ]
        return sum(counts) == 0


def read_state(db_path: str, default_state: dict) -> dict:
    state = json.loads(json.dumps(default_state, default=json_default))
    with _connect(db_path) as conn:
        last_hot10_row = conn.execute(
            "SELECT value_json FROM metadata WHERE key = 'last_hot10'"
        ).fetchone()
        if last_hot10_row:
            state["last_hot10"] = json.loads(last_hot10_row["value_json"])

        # Lane-added JSON blobs — persisted via the metadata table so the
        # schema stays additive. Missing rows fall back to default_state.
        for key in _METADATA_JSON_KEYS:
            row = conn.execute(
                "SELECT value_json FROM metadata WHERE key = ?", (key,)
            ).fetchone()
            if row:
                state[key] = json.loads(row["value_json"])

        state["posted_events"] = [
            row["event_id"]
            for row in conn.execute(
                "SELECT event_id FROM posted_events ORDER BY seq ASC"
            ).fetchall()
        ]

        state["daily_tweet_count"] = {
            row["day"]: row["count"]
            for row in conn.execute(
                "SELECT day, count FROM daily_tweet_count ORDER BY day ASC"
            ).fetchall()
        }

        state["streaks"] = {
            row["city"]: {
                "consecutive_days": row["consecutive_days"],
                "last_seen": row["last_seen"],
            }
            for row in conn.execute(
                "SELECT city, consecutive_days, last_seen FROM streaks ORDER BY city ASC"
            ).fetchall()
        }

        state["drafts"] = [
            json.loads(row["payload_json"])
            for row in conn.execute(
                "SELECT payload_json FROM drafts ORDER BY seq ASC"
            ).fetchall()
        ]

        run_rows = conn.execute(
            "SELECT * FROM runs ORDER BY seq ASC"
        ).fetchall()
        source_rows = conn.execute(
            "SELECT * FROM source_runs ORDER BY run_id ASC, seq ASC"
        ).fetchall()
        source_map: dict[str, list[dict]] = {}
        for row in source_rows:
            source_map.setdefault(row["run_id"], []).append(json.loads(row["payload_json"]))

        state["run_history"] = []
        for row in run_rows:
            payload = json.loads(row["payload_json"])
            payload["sources"] = source_map.get(row["run_id"], payload.get("sources", []))
            state["run_history"].append(payload)

        state["errors"] = [
            json.loads(row["payload_json"])
            for row in conn.execute(
                "SELECT payload_json FROM errors ORDER BY seq ASC"
            ).fetchall()
        ]

    return state


def write_state(db_path: str, state: dict) -> bool:
    try:
        with _connect(db_path) as conn:
            conn.execute("BEGIN")

            conn.execute("DELETE FROM metadata")
            conn.execute(
                "INSERT INTO metadata (key, value_json) VALUES (?, ?)",
                ("last_hot10", _json(state.get("last_hot10", {"date": None, "cities": []}))),
            )
            for key in _METADATA_JSON_KEYS:
                if key in state:
                    conn.execute(
                        "INSERT INTO metadata (key, value_json) VALUES (?, ?)",
                        (key, _json(state[key])),
                    )

            conn.execute("DELETE FROM posted_events")
            conn.executemany(
                "INSERT INTO posted_events (seq, event_id) VALUES (?, ?)",
                [
                    (index, event_id)
                    for index, event_id in enumerate(state.get("posted_events", []))
                ],
            )

            conn.execute("DELETE FROM daily_tweet_count")
            conn.executemany(
                "INSERT INTO daily_tweet_count (day, count) VALUES (?, ?)",
                [
                    (day, count)
                    for day, count in state.get("daily_tweet_count", {}).items()
                ],
            )

            conn.execute("DELETE FROM streaks")
            conn.executemany(
                "INSERT INTO streaks (city, consecutive_days, last_seen) VALUES (?, ?, ?)",
                [
                    (city, details.get("consecutive_days", 0), details.get("last_seen"))
                    for city, details in state.get("streaks", {}).items()
                ],
            )

            conn.execute("DELETE FROM drafts")
            conn.executemany(
                """
                INSERT INTO drafts
                (draft_id, seq, event_id, type, status, created_at, approved_at, posted_at,
                 auto_approve_at, approval_mode, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        draft.get("id"),
                        index,
                        draft.get("event_id"),
                        draft.get("type"),
                        draft.get("status"),
                        draft.get("created_at"),
                        draft.get("approved_at"),
                        draft.get("posted_at"),
                        draft.get("auto_approve_at"),
                        draft.get("approval_mode"),
                        _json(draft),
                    )
                    for index, draft in enumerate(state.get("drafts", []))
                ],
            )

            conn.execute("DELETE FROM source_runs")
            conn.execute("DELETE FROM runs")
            for run_index, run in enumerate(state.get("run_history", [])):
                run_id = run.get("id")
                conn.execute(
                    """
                    INSERT INTO runs
                    (run_id, seq, mode, status, started_at, ended_at, source_count,
                     failure_count, drafted_count, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        run_index,
                        run.get("mode"),
                        run.get("status"),
                        run.get("started_at"),
                        run.get("ended_at"),
                        run.get("source_count", len(run.get("sources", []))),
                        run.get("failure_count", 0),
                        run.get("drafted_count", 0),
                        _json({**run, "sources": []}),
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO source_runs
                    (run_id, seq, source, status, duration_ms, observed, promoted, drafted,
                     error, note, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            source_index,
                            source.get("source"),
                            source.get("status"),
                            source.get("duration_ms", 0),
                            source.get("observed", 0),
                            source.get("promoted", 0),
                            source.get("drafted", 0),
                            source.get("error"),
                            source.get("note"),
                            _json(source),
                        )
                        for source_index, source in enumerate(run.get("sources", []))
                    ],
                )

            conn.execute("DELETE FROM errors")
            conn.executemany(
                "INSERT INTO errors (seq, source, ts, msg, payload_json) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        index,
                        error.get("source"),
                        error.get("ts"),
                        error.get("msg"),
                        _json(error),
                    )
                    for index, error in enumerate(state.get("errors", []))
                ],
            )

            conn.commit()
        return True
    except (sqlite3.Error, TypeError, ValueError):
        return False
