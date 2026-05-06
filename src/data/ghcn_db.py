"""SQLite schema and I/O for the GHCN-Daily threshold cache.

This module owns the database schema and provides read/write helpers used
by the offline bootstrap scripts and the per-cycle hot path in ghcn.py.

Schema lives here (not in scripts) so that the hot-path module and the
offline scripts share a single source of truth.

Zero external dependencies — stdlib sqlite3 only.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable

from src.data.ghcn_format import (
    ElementInventory,
    StationMeta,
    StationThresholds,
)

# ---------------------------------------------------------------------------
# Default DB path (relative to repo root).  Override via env var or arg.
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "station_thresholds.sqlite"

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stations (
    station_id    TEXT PRIMARY KEY,
    name          TEXT    NOT NULL DEFAULT '',
    country_code  TEXT    NOT NULL DEFAULT '',
    country_name  TEXT    NOT NULL DEFAULT '',
    state         TEXT    NOT NULL DEFAULT '',
    lat           REAL    NOT NULL,
    lon           REAL    NOT NULL,
    elevation_m   REAL    NOT NULL DEFAULT -999.9,
    gsn_flag      TEXT    NOT NULL DEFAULT '',
    hcn_crn_flag  TEXT    NOT NULL DEFAULT '',
    wmo_id        TEXT    NOT NULL DEFAULT '',
    tmax_first_year INTEGER,
    tmax_last_year  INTEGER,
    tmin_first_year INTEGER,
    tmin_last_year  INTEGER,
    tmax_archive_years INTEGER NOT NULL DEFAULT 0,
    tmin_archive_years INTEGER NOT NULL DEFAULT 0,
    archive_years   INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_stations_active   ON stations(is_active);
CREATE INDEX IF NOT EXISTS idx_stations_country  ON stations(country_code);

CREATE TABLE IF NOT EXISTS thresholds (
    station_id    TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    month         INTEGER,
    day           INTEGER,
    value_c       REAL    NOT NULL,
    record_year   INTEGER,
    PRIMARY KEY (station_id, kind, month, day)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def open_db(path: Path | str = DEFAULT_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that opens (and creates) the SQLite database."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_DDL)
        _migrate_schema(conn)
        conn.commit()
        yield conn
    finally:
        conn.close()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive schema fixes for existing threshold DB assets."""
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(stations)").fetchall()
    }
    if "tmax_archive_years" not in cols:
        conn.execute("ALTER TABLE stations ADD COLUMN tmax_archive_years INTEGER NOT NULL DEFAULT 0")
    if "tmin_archive_years" not in cols:
        conn.execute("ALTER TABLE stations ADD COLUMN tmin_archive_years INTEGER NOT NULL DEFAULT 0")


# ---------------------------------------------------------------------------
# Station upsert
# ---------------------------------------------------------------------------

def upsert_station(
    conn: sqlite3.Connection,
    meta: StationMeta,
    country_name: str,
    inv_rows: list[ElementInventory],
    active_year_cutoff: int,
) -> None:
    """Insert or update one station row from metadata + inventory."""
    tmax_rows = [r for r in inv_rows if r.element == "TMAX"]
    tmin_rows = [r for r in inv_rows if r.element == "TMIN"]

    tmax_first = min((r.first_year for r in tmax_rows), default=None)
    tmax_last  = max((r.last_year  for r in tmax_rows), default=None)
    tmin_first = min((r.first_year for r in tmin_rows), default=None)
    tmin_last  = max((r.last_year  for r in tmin_rows), default=None)

    tmax_archive_years = (tmax_last - tmax_first + 1) if (tmax_first and tmax_last) else 0
    tmin_archive_years = (tmin_last - tmin_first + 1) if (tmin_first and tmin_last) else 0
    archive_years = max(tmax_archive_years, tmin_archive_years)
    is_active = 1 if (
        (tmax_last is not None and tmax_last >= active_year_cutoff)
        or (tmin_last is not None and tmin_last >= active_year_cutoff)
    ) else 0

    conn.execute(
        """
        INSERT INTO stations
            (station_id, name, country_code, country_name, state, lat, lon,
             elevation_m, gsn_flag, hcn_crn_flag, wmo_id,
             tmax_first_year, tmax_last_year, tmin_first_year, tmin_last_year,
             tmax_archive_years, tmin_archive_years, archive_years, is_active)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(station_id) DO UPDATE SET
            name           = excluded.name,
            country_name   = excluded.country_name,
            state          = excluded.state,
            lat            = excluded.lat,
            lon            = excluded.lon,
            elevation_m    = excluded.elevation_m,
            gsn_flag       = excluded.gsn_flag,
            hcn_crn_flag   = excluded.hcn_crn_flag,
            wmo_id         = excluded.wmo_id,
            tmax_first_year = excluded.tmax_first_year,
            tmax_last_year  = excluded.tmax_last_year,
            tmin_first_year = excluded.tmin_first_year,
            tmin_last_year  = excluded.tmin_last_year,
            tmax_archive_years = excluded.tmax_archive_years,
            tmin_archive_years = excluded.tmin_archive_years,
            archive_years   = excluded.archive_years,
            is_active       = excluded.is_active
        """,
        (
            meta.station_id,
            meta.name,
            meta.country_code_inferred(),
            country_name,
            meta.state,
            meta.lat,
            meta.lon,
            meta.elevation_m,
            meta.gsn_flag,
            meta.hcn_crn_flag,
            meta.wmo_id,
            tmax_first, tmax_last,
            tmin_first, tmin_last,
            tmax_archive_years,
            tmin_archive_years,
            archive_years,
            is_active,
        ),
    )


# ---------------------------------------------------------------------------
# Threshold upsert
# ---------------------------------------------------------------------------

def upsert_thresholds(
    conn: sqlite3.Connection,
    t: StationThresholds,
) -> None:
    """Write all computed thresholds for one station, replacing any stale rows."""
    rows: list[tuple] = []
    sid = t.station_id

    conn.execute("DELETE FROM thresholds WHERE station_id = ?", (sid,))

    if t.all_time_max_c is not None:
        rows.append((sid, "all_time_max", None, None, t.all_time_max_c, t.all_time_max_year))
    if t.all_time_min_c is not None:
        rows.append((sid, "all_time_min", None, None, t.all_time_min_c, t.all_time_min_year))

    for m, (v, y) in t.monthly_max.items():
        rows.append((sid, "monthly_max", m, None, v, y))
    for m, (v, y) in t.monthly_min.items():
        rows.append((sid, "monthly_min", m, None, v, y))

    for (m, d), (v, y) in t.calendar_date_max.items():
        rows.append((sid, "calendar_date_max", m, d, v, y))
    for (m, d), (v, y) in t.calendar_date_min.items():
        rows.append((sid, "calendar_date_min", m, d, v, y))

    for m, mean_c in t.climatological_mean.items():
        rows.append((sid, "climatological_mean", m, None, mean_c, None))
    for m, mean_c in t.climatological_mean_min.items():
        rows.append((sid, "climatological_mean_min", m, None, mean_c, None))

    if rows:
        conn.executemany(
            """
            INSERT INTO thresholds (station_id, kind, month, day, value_c, record_year)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def load_thresholds(
    conn: sqlite3.Connection,
    station_id: str,
) -> StationThresholds | None:
    """Load all threshold rows for a station into a StationThresholds object."""
    rows = conn.execute(
        "SELECT kind, month, day, value_c, record_year FROM thresholds WHERE station_id = ?",
        (station_id,),
    ).fetchall()

    if not rows:
        return None

    t = StationThresholds(station_id=station_id)

    for kind, month, day, value_c, record_year in rows:
        if kind == "all_time_max":
            t.all_time_max_c = value_c
            t.all_time_max_year = record_year
        elif kind == "all_time_min":
            t.all_time_min_c = value_c
            t.all_time_min_year = record_year
        elif kind == "monthly_max" and month is not None:
            t.monthly_max[month] = (value_c, record_year)
        elif kind == "monthly_min" and month is not None:
            t.monthly_min[month] = (value_c, record_year)
        elif kind == "calendar_date_max" and month is not None and day is not None:
            t.calendar_date_max[(month, day)] = (value_c, record_year)
        elif kind == "calendar_date_min" and month is not None and day is not None:
            t.calendar_date_min[(month, day)] = (value_c, record_year)
        elif kind == "climatological_mean" and month is not None:
            t.climatological_mean[month] = value_c
        elif kind == "climatological_mean_min" and month is not None:
            t.climatological_mean_min[month] = value_c

    station_row = conn.execute(
        """
        SELECT archive_years, tmax_archive_years, tmin_archive_years
        FROM stations
        WHERE station_id = ?
        """,
        (station_id,),
    ).fetchone()
    if station_row:
        t.archive_years = station_row[0]
        t.tmax_archive_years = station_row[1] or 0
        t.tmin_archive_years = station_row[2] or 0

    return t


def load_active_stations(
    conn: sqlite3.Connection,
) -> list[dict]:
    """Return all active stations as dicts suitable for check_extreme_signals_for_stations."""
    rows = conn.execute(
        """
        SELECT station_id, name, country_code, country_name, state,
               lat, lon, elevation_m, archive_years,
               tmax_archive_years, tmin_archive_years
        FROM stations
        WHERE is_active = 1
        ORDER BY station_id
        """,
    ).fetchall()
    cols = ["station_id", "name", "country_code", "country_name", "state",
            "lat", "lon", "elevation_m", "archive_years",
            "tmax_archive_years", "tmin_archive_years"]
    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------------------
# Metadata / watermark
# ---------------------------------------------------------------------------

def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
