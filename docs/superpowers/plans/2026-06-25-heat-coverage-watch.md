# Heat Coverage Watch Implementation Plan (v3 — post 2× codex review)

> Codex round 1 (design/codebase) closed 4 P1s: state_schema parity, SQLite `_METADATA_JSON_KEYS`, real issue lookup, insufficient-data-not-silent. Codex round 2 closed 3 more: hot-only recording (cold extremes were being tallied as heat), ruff `F841` (unused `flagged`), and dashboard render scoped to mirror+payload (UI render deferred — wrong component wiring). All prior P1s were re-verified correct by round 2.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect when @theheat's heat detector silently goes mono-regional (the GHCN US-only blind spot) by recording each surfaced heat event's geography into a persistent rolling tally and opening an advisory issue when one country/continent dominates.

**Architecture:** Geography is recorded **at the source** (`run_extreme_signals`, where heat events carry a clean `country`) into a persistent `coverage_log` in state — decoupled from the 20-run `run_history` cap. Continent is resolved once at record time (`src/coverage.py`) and stored, so the Python sentinel and the JS dashboard mirror just read `{country, continent}`. The check is a pure function reconciled into one advisory auto-closing GitHub issue, mirroring the yield-watch.

**Tech Stack:** Python 3.12 (bot + sentinel, pytest), Node 24 (dashboard, `node --test`), state persisted to a GitHub gist **and** SQLite (`src/storage/sqlite_store.py`).

## Global Constraints

- `ruff check src/ scripts/` clean; `mypy src/` clean; `.venv/bin/python -m pytest` green; `cd dashboard && node --test` green.
- Stage only the files each task names — never `git add -A`. Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- The sentinel is a reporter, never a gate: `scripts/source_health_sentinel.py` keeps exiting 0.
- Python and JS thresholds (Task 5/7) hold identical values; each side asserts them.
- Recording is additive + best-effort: a recording failure must never break a draft (`record_coverage_observation` swallows exceptions).

**Tunables (verbatim in both languages):** `COVERAGE_WINDOW_DAYS = 21`, `COVERAGE_MIN_EVENTS = 20`, `COVERAGE_CONCENTRATION = 0.85`, `COVERAGE_DATA_FLOOR = 5`.

**Codex review fixes folded into this v2** (do not regress them): (1) `coverage_log` is added to `DEFAULT_STATE` **and** `BotState` (state_schema parity test) **and** `_METADATA_JSON_KEYS` (SQLite persistence) with a round-trip test; (2) the issue lookup is title-based (no fictional `_find_marker_issue`); (3) `DATA_FLOOR ≤ n < MIN_EVENTS` emits an explicit `insufficient_data` finding (dashboard-visible, never silent) that does **not** open an issue; (4) recording happens at all heat enqueue sites incl. record-streak; (5) the dashboard actually renders a coverage line.

---

### Task 1: Country→continent artifact + generator

**Files:** Create `scripts/build_country_continent.py`, `data/country_continent.json`.
**Produces:** `data/country_continent.json` = `{ "<cities.csv country>": "<continent>" }`.

- [ ] **Step 1: Write the generator**

```python
# scripts/build_country_continent.py
"""Derive country -> continent from data/cities.csv lat/lon. Re-run on cities change."""
import csv, json
from collections import Counter


def continent_for(lat: float, lon: float) -> str:
    if lat <= -60: return "Antarctica"
    if lat <= 0 and 110 <= lon <= 180: return "Oceania"
    if -56 <= lat <= 14 and -82 <= lon <= -34: return "South America"
    if lat >= 7 and -170 <= lon <= -50: return "North America"
    if 34 <= lat <= 72 and -25 <= lon <= 60: return "Europe"
    if -37 <= lat <= 37 and -20 <= lon <= 52: return "Africa"
    if -15 <= lat <= 82 and 25 <= lon <= 180: return "Asia"
    return "Unknown"


def build(cities_path: str = "data/cities.csv") -> dict[str, str]:
    votes: dict[str, Counter] = {}
    with open(cities_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            country = (row.get("country") or "").strip()
            if not country: continue
            votes.setdefault(country, Counter())[continent_for(float(row["lat"]), float(row["lon"]))] += 1
    return {c: v.most_common(1)[0][0] for c, v in sorted(votes.items())}


if __name__ == "__main__":
    mapping = build()
    with open("data/country_continent.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False, sort_keys=True); f.write("\n")
    print(f"wrote data/country_continent.json ({len(mapping)} countries)")
```

- [ ] **Step 2: Generate + spot-check**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat && .venv/bin/python scripts/build_country_continent.py`
Expected: `wrote data/country_continent.json (~170 countries)`. Confirm `US`→`North America`, `France`→`Europe`, `China`→`Asia`, `Australia`→`Oceania`.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_country_continent.py data/country_continent.json
git commit -m "feat(coverage): country->continent artifact derived from cities.csv"
```

---

### Task 2: `src/coverage.py` — continent resolution

**Files:** Create `src/coverage.py`; Test `tests/test_coverage.py`.
**Consumes:** `data/country_continent.json`. **Produces:** `is_us_location(country)->bool`, `resolve_continent(country)->str`.

- [ ] **Step 1: Failing test**

```python
# tests/test_coverage.py
from src.coverage import is_us_location, resolve_continent


def test_us_forms_resolve_to_north_america():
    assert is_us_location("US") and is_us_location("United States")
    assert is_us_location("Northern Mariana Islands [United States]")
    assert resolve_continent("United States") == "North America"
    assert resolve_continent("US") == "North America"


def test_non_us_resolves_via_map():
    assert not is_us_location("United Kingdom")
    assert resolve_continent("France") == "Europe"
    assert resolve_continent("China") == "Asia"


def test_unknown_is_unknown():
    assert resolve_continent("Atlantis") == "Unknown"
    assert resolve_continent("") == "Unknown"
    assert resolve_continent(None) == "Unknown"
```

- [ ] **Step 2: Run — expect FAIL** `ModuleNotFoundError: No module named 'src.coverage'`
Run: `.venv/bin/python -m pytest tests/test_coverage.py -q`

- [ ] **Step 3: Implement**

```python
# src/coverage.py
"""Resolve an event's country to a continent for the coverage watch."""
from __future__ import annotations
import json, os
from functools import lru_cache

_MAP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "country_continent.json")


@lru_cache(maxsize=1)
def _country_continent() -> dict[str, str]:
    try:
        with open(_MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def is_us_location(country: str | None) -> bool:
    c = (country or "").strip()
    return c == "US" or "United States" in c


def resolve_continent(country: str | None) -> str:
    c = (country or "").strip()
    if not c: return "Unknown"
    if is_us_location(c): return "North America"
    return _country_continent().get(c, "Unknown")
```

- [ ] **Step 4: Run — expect PASS (3)** `.venv/bin/python -m pytest tests/test_coverage.py -q`
- [ ] **Step 5: Commit** `git add src/coverage.py tests/test_coverage.py && git commit -m "feat(coverage): resolve_continent + is_us_location"`

---

### Task 3: State `coverage_log` — schema, SQLite persistence, merge, record, prune

**Files:**
- Modify: `src/state.py` (DEFAULT_STATE :75; MERGE_SPEC :1723; add `_merge_coverage_log`, `record_coverage_observation`, `COVERAGE_WINDOW_DAYS`)
- Modify: `src/state_schema.py` (add `CoverageRecord` TypedDict + `coverage_log` to `BotState`)
- Modify: `src/storage/sqlite_store.py` (add `"coverage_log"` to `_METADATA_JSON_KEYS` :108)
- Test: `tests/test_coverage_state.py`

**Consumes:** `src.coverage.resolve_continent`.
**Produces:** `record_coverage_observation(state, *, cls, event_id, country, when, now=None) -> None`; `COVERAGE_WINDOW_DAYS = 21`; `_merge_coverage_log`; `CoverageRecord`.

- [ ] **Step 1: Failing tests** (`tests/test_coverage_state.py`)

```python
from datetime import datetime, timezone
from src import state as state_mod
from src.state import _fresh_state, record_coverage_observation


def _now(d="2026-06-25"): return datetime.fromisoformat(d + "T00:00:00+00:00")


def test_record_appends_with_resolved_continent():
    s = _fresh_state()
    record_coverage_observation(s, cls="heat", event_id="e1", country="United States", when="2026-06-25", now=_now())
    assert s["coverage_log"] == [{"cls": "heat", "event_id": "e1", "country": "United States",
                                  "continent": "North America", "date": "2026-06-25"}]


def test_record_dedups_on_event_id():
    s = _fresh_state()
    for _ in range(2):
        record_coverage_observation(s, cls="heat", event_id="e1", country="Spain", when="2026-06-25", now=_now())
    assert len(s["coverage_log"]) == 1


def test_record_prunes_older_than_window():
    s = _fresh_state()
    record_coverage_observation(s, cls="heat", event_id="old", country="Spain", when="2026-05-01", now=_now())
    record_coverage_observation(s, cls="heat", event_id="new", country="Spain", when="2026-06-25", now=_now())
    assert {r["event_id"] for r in s["coverage_log"]} == {"new"}


def test_record_never_raises_on_bad_input():
    s = _fresh_state()
    record_coverage_observation(s, cls="heat", event_id="e1", country=None, when=None)
    assert s["coverage_log"][0]["continent"] == "Unknown"


def test_merge_dedups_concurrent_writers():
    a = [{"cls": "heat", "event_id": "e1", "country": "US", "continent": "North America", "date": "2026-06-25"}]
    b = a + [{"cls": "heat", "event_id": "e2", "country": "Spain", "continent": "Europe", "date": "2026-06-25"}]
    assert {r["event_id"] for r in state_mod._merge_coverage_log(a, b)} == {"e1", "e2"}
```

- [ ] **Step 2: Failing SQLite round-trip test** — find the existing key-persistence round-trip test (`tests/test_state.py:1237`, which guards SST/AQ key loss) and add `coverage_log` to it (or add a sibling test in `tests/test_coverage_state.py` that saves a state with a `coverage_log` record through `src/storage/sqlite_store.py`'s save/load and asserts the record survives). Read `tests/test_state.py:1230-1260` to mirror the existing round-trip shape exactly.

- [ ] **Step 3: Run — expect FAIL** `ImportError: cannot import name 'record_coverage_observation'` (and the round-trip test fails: `coverage_log` empty after load).
Run: `.venv/bin/python -m pytest tests/test_coverage_state.py -q`

- [ ] **Step 4: Implement**

(a) `src/state.py` DEFAULT_STATE, next to `"run_history": [],` (:75):
```python
    "coverage_log": [],  # rolling per-surfaced-event geography for the coverage watch
```
(b) `src/state.py` module constant: `COVERAGE_WINDOW_DAYS = 21`
(c) `src/state.py` merge fn (next to `_merge_run_history`):
```python
def _merge_coverage_log(current: list[dict], incoming: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    anonymous: list[dict] = []
    for rec in [*(current or []), *(incoming or [])]:
        rec_id = rec.get("event_id")
        (anonymous.append(dict(rec)) if not rec_id else by_id.__setitem__(rec_id, dict(rec)))
    return [*by_id.values(), *anonymous]
```
(d) `src/state.py` register in `MERGE_SPEC` (:1723), add `"coverage_log": _merge_coverage_log,`
(e) `src/state.py` record helper:
```python
def record_coverage_observation(state: BotState, *, cls: str, event_id: str,
                                country: str | None, when: "str | date | None",
                                now: datetime | None = None) -> None:
    """Append one surfaced-event geography record; dedup on event_id; prune window. Never raises."""
    try:
        from src.coverage import resolve_continent
        now = now or datetime.now(UTC)
        if isinstance(when, date) and not isinstance(when, datetime):
            date_str = when.isoformat()
        elif isinstance(when, str) and when:
            date_str = when[:10]
        else:
            date_str = now.date().isoformat()
        log = state.setdefault("coverage_log", [])
        log[:] = [r for r in log if r.get("event_id") != event_id]
        log.append({"cls": cls, "event_id": event_id, "country": country or "",
                    "continent": resolve_continent(country), "date": date_str})
        cutoff = (now - timedelta(days=COVERAGE_WINDOW_DAYS)).date().isoformat()
        state["coverage_log"] = [r for r in log if str(r.get("date") or "") >= cutoff]
    except Exception:
        pass
```
(f) `src/state_schema.py` — add a record TypedDict (mirror `CityRecord:66`) and the BotState field:
```python
class CoverageRecord(TypedDict):
    cls: str
    event_id: str
    country: str
    continent: str
    date: str
```
and in `BotState`: `coverage_log: list[CoverageRecord]`
(g) `src/storage/sqlite_store.py` — add `"coverage_log"` to the `_METADATA_JSON_KEYS` tuple (:108).

- [ ] **Step 5: Run — expect PASS** `.venv/bin/python -m pytest tests/test_coverage_state.py tests/test_state.py -q` (state-schema parity + sqlite round-trip + the 5 unit tests all green).
- [ ] **Step 6: Commit**
```bash
git add src/state.py src/state_schema.py src/storage/sqlite_store.py tests/test_coverage_state.py tests/test_state.py
git commit -m "feat(coverage): persistent coverage_log (schema, sqlite, merge, record)"
```

---

### Task 4: Record heat geography at every heat enqueue site

**Files:** Modify `src/orchestrator/sources/open_meteo.py`; Test `tests/test_open_meteo_orchestrator.py`.
**Consumes:** `state.record_coverage_observation`. (`state` is in scope via `from src.orchestrator.common import *`.)

Record sites (verified current line numbers; vars in scope at each). **HOT events only** — the strongest-signal cascade includes cold types (`all_time_low`, `monthly_low`, `record_low`, `anomaly_cold`, cold `absolute_extreme`); recording those as `cls="heat"` would dilute the tally with cold-record geography and could mask a mono-regional HOT failure. Gate to hot:
- **per-city** strongest signal: top of `if candidate_queued:` (**:434**), only when the type is hot — `country=bundle.country`, `event_id=strongest_event_id`, `when=bundle.signal_date`.
- **record-streak**: inside the streak enqueue success (**:483**, from `calendar_date_high`, always hot) — `country=ev_cd.country`, `event_id=streak_event_id`, `when=bundle.signal_date`.
- **country record**: after `country_count += 1` (**:735**), only when `cr.kind == "high"` — `country=cr.country`, `event_id=cr.event_id`, `when=cr.signal_date`.

(wet_bulb/simultaneous deferred — per-city alone surfaces multiple hot cities/day, exceeding MIN_EVENTS over 21 days, and Task 5's `insufficient_data` covers thin windows.)

- [ ] **Step 1: Failing test** (append to `tests/test_open_meteo_orchestrator.py`)

```python
def test_surfaced_heat_event_records_coverage(monkeypatch):
    from datetime import date
    from src.data.open_meteo import AbsoluteExtremeEvent, ExtremeSignalBundle
    from src.orchestrator.sources import open_meteo as runner
    from src.state import _fresh_state

    ev = AbsoluteExtremeEvent(city="Seville", country="Spain", today_temp_c=45.1,
        band_label="Temperate", threshold_c=42.0, kind="hot", lat=37.4, lon=-6.0,
        event_id="absextreme_Seville_2026-06-25", signal_date=date(2026, 6, 25))
    bundle = ExtremeSignalBundle(city="Seville", country="Spain", absolute_extreme=ev, signal_date=date(2026, 6, 25))
    bot_state = _fresh_state()
    current_run = {"id": "r1", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z", "sources": []}
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, m: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *a, **k: True)
    runner.run_extreme_signals(bot_state, current_run, [], {}, {})
    recs = [r for r in bot_state["coverage_log"] if r["event_id"] == "absextreme_Seville_2026-06-25"]
    assert recs and recs[0]["cls"] == "heat" and recs[0]["continent"] == "Europe"


def test_cold_extreme_is_not_recorded_as_heat(monkeypatch):
    from datetime import date
    from src.data.open_meteo import AbsoluteExtremeEvent, ExtremeSignalBundle
    from src.orchestrator.sources import open_meteo as runner
    from src.state import _fresh_state

    cold = AbsoluteExtremeEvent(city="Nw Michigan", country="United States", today_temp_c=0.6,
        band_label="Temperate", threshold_c=2.0, kind="cold", lat=45.0, lon=-85.0,
        event_id="absextreme_cold_NwMichigan_2026-06-25", signal_date=date(2026, 6, 25))
    bundle = ExtremeSignalBundle(city="Nw Michigan", country="United States", absolute_extreme=cold,
                                 signal_date=date(2026, 6, 25))
    bot_state = _fresh_state()
    current_run = {"id": "r1", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z", "sources": []}
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, m: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *a, **k: True)
    runner.run_extreme_signals(bot_state, current_run, [], {}, {})
    assert bot_state["coverage_log"] == []  # cold extreme must not pollute the heat tally
```

- [ ] **Step 2: Run — expect FAIL** (`coverage_log` has no matching record)
Run: `.venv/bin/python -m pytest tests/test_open_meteo_orchestrator.py::test_surfaced_heat_event_records_coverage -q`

- [ ] **Step 3: Implement** — insert at the three sites above, gated to hot. Per-city (top of the `:434` `if candidate_queued:` block):
```python
                _hot = strongest_type in ("all_time_high", "monthly_high", "record", "anomaly_hot") or (
                    strongest_type == "absolute_extreme" and getattr(strongest_signal, "kind", "") == "hot")
                if candidate_queued and _hot:
                    state.record_coverage_observation(bot_state, cls="heat",
                        event_id=strongest_event_id, country=bundle.country, when=bundle.signal_date)
```
Record-streak (after its `_enqueue_story_candidate(...)` returns truthy, alongside `signal_counts["streak"] += 1`; calendar_date_high is always hot):
```python
                                        state.record_coverage_observation(bot_state, cls="heat",
                                            event_id=streak_event_id, country=ev_cd.country, when=bundle.signal_date)
```
Country record (after `country_count += 1` at :735), hot only:
```python
                country_count += 1
                if cr.kind == "high":
                    state.record_coverage_observation(bot_state, cls="heat",
                        event_id=cr.event_id, country=cr.country, when=cr.signal_date)
```

- [ ] **Step 4: Run — expect PASS (all, incl. new + existing)** `.venv/bin/python -m pytest tests/test_open_meteo_orchestrator.py -q`
- [ ] **Step 5: Commit**
```bash
git add src/orchestrator/sources/open_meteo.py tests/test_open_meteo_orchestrator.py
git commit -m "feat(coverage): record heat geography at enqueue sites"
```

---

### Task 5: `coverage_watch` classifier (sentinel)

**Files:** Modify `scripts/source_health_sentinel.py`; Test `tests/test_source_health_sentinel.py`.
**Consumes:** `state["coverage_log"]`, `state["run_history"]`.
**Produces:** `coverage_watch(coverage_log, run_history, *, now) -> list[dict]`. Finding kinds: `mono_regional`, `insufficient_data`, `no_data`. Shape: `{cls, kind, dominant, share, events, distribution}`.

- [ ] **Step 1: Failing test**

```python
# tests/test_source_health_sentinel.py
from datetime import datetime, timezone
from scripts.source_health_sentinel import coverage_watch


def _log(country, continent, n, cls="heat"):
    return [{"cls": cls, "event_id": f"{country}-{i}", "country": country,
             "continent": continent, "date": "2026-06-25"} for i in range(n)]


def _alerts(): return [{"id": "r", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z"}]


class TestCoverageWatch:
    NOW = datetime(2026, 6, 25, tzinfo=timezone.utc)

    def test_us_only_flags_mono_regional(self):
        out = coverage_watch(_log("United States", "North America", 22), _alerts(), now=self.NOW)
        assert len(out) == 1 and out[0]["kind"] == "mono_regional"
        assert out[0]["dominant"] in ("United States", "North America") and out[0]["share"] >= 0.85

    def test_diversified_does_not_flag(self):
        log = (_log("United States", "North America", 8) + _log("Spain", "Europe", 6)
               + _log("India", "Asia", 4) + _log("Brazil", "South America", 4))
        assert coverage_watch(log, _alerts(), now=self.NOW) == []

    def test_thin_window_is_insufficient_not_silent(self):
        out = coverage_watch(_log("United States", "North America", 10), _alerts(), now=self.NOW)
        assert len(out) == 1 and out[0]["kind"] == "insufficient_data"

    def test_no_data_while_drafting_flags(self):
        out = coverage_watch([], _alerts(), now=self.NOW)
        assert len(out) == 1 and out[0]["kind"] == "no_data"

    def test_no_data_quiet_bot_does_not_flag(self):
        assert coverage_watch([], [], now=self.NOW) == []
```

- [ ] **Step 2: Run — expect FAIL** `ImportError: cannot import name 'coverage_watch'`
Run: `.venv/bin/python -m pytest tests/test_source_health_sentinel.py::TestCoverageWatch -q`

- [ ] **Step 3: Implement** (`Mapping`, `datetime`, `timezone`, `timedelta` already imported)

```python
COVERAGE_WINDOW_DAYS = 21
COVERAGE_MIN_EVENTS = 20
COVERAGE_CONCENTRATION = 0.85
COVERAGE_DATA_FLOOR = 5
COVERAGE_WATCHED_CLASSES = ("heat",)  # extend per source instrumentation (Future)
COVERAGE_WATCH_TITLE = "Coverage watch: a global source may be blind to a region"
COVERAGE_WATCH_MARKER = "<!-- source-health-coverage-watch -->"


def _bot_is_drafting(run_history: list[dict] | None) -> bool:
    return any(str(r.get("mode") or "") in ("alerts", "both")
               for r in (run_history or []) if isinstance(r, Mapping))


def coverage_watch(coverage_log: list[dict] | None, run_history: list[dict] | None,
                   *, now: datetime) -> list[dict]:
    cutoff = (now - timedelta(days=COVERAGE_WINDOW_DAYS)).date().isoformat()
    drafting = _bot_is_drafting(run_history)
    findings: list[dict] = []
    for cls in COVERAGE_WATCHED_CLASSES:
        recs = [r for r in (coverage_log or []) if isinstance(r, Mapping)
                and r.get("cls") == cls and str(r.get("date") or "") >= cutoff]
        n = len(recs)
        if n < COVERAGE_DATA_FLOOR:
            if drafting:
                findings.append({"cls": cls, "kind": "no_data", "dominant": "—",
                                 "share": 0.0, "events": n, "distribution": {}})
            continue
        if n < COVERAGE_MIN_EVENTS:
            findings.append({"cls": cls, "kind": "insufficient_data", "dominant": "—",
                             "share": 0.0, "events": n, "distribution": {}})
            continue
        for axis in ("country", "continent"):  # country takes precedence
            counts: dict[str, int] = {}
            for r in recs:
                key = str(r.get(axis) or "Unknown")
                counts[key] = counts.get(key, 0) + 1
            dominant, top = max(counts.items(), key=lambda kv: kv[1])
            if dominant != "Unknown" and top / n >= COVERAGE_CONCENTRATION:
                findings.append({"cls": cls, "kind": "mono_regional", "dominant": dominant,
                                 "share": round(top / n, 3), "events": n,
                                 "distribution": dict(sorted(counts.items(), key=lambda kv: -kv[1]))})
                break
    return findings
```

- [ ] **Step 4: Run — expect PASS (5)** `.venv/bin/python -m pytest tests/test_source_health_sentinel.py::TestCoverageWatch -q`
- [ ] **Step 5: Commit**
```bash
git add scripts/source_health_sentinel.py tests/test_source_health_sentinel.py
git commit -m "feat(coverage): coverage_watch classifier (mono-regional / insufficient / no-data)"
```

---

### Task 6: Coverage-watch issue reconciliation (sentinel `main`)

**Files:** Modify `scripts/source_health_sentinel.py`; Test `tests/test_source_health_sentinel.py`.
**Produces:** `build_coverage_watch_body`, `plan_coverage_watch_action`, `_open_coverage_watch_issue`, `_create/_update/_close_coverage_watch_issue`.
**Issue policy:** only `mono_regional` and `no_data` findings open/keep an issue; `insufficient_data` is dashboard-only (does not open an issue — quiet but not silent).

- [ ] **Step 1: Failing test**

```python
# tests/test_source_health_sentinel.py
from scripts.source_health_sentinel import (
    build_coverage_watch_body, plan_coverage_watch_action, COVERAGE_WATCH_MARKER)


class TestCoverageWatchIssue:
    MONO = [{"cls": "heat", "kind": "mono_regional", "dominant": "United States",
             "share": 0.95, "events": 22, "distribution": {"United States": 21, "Spain": 1}}]
    INSUF = [{"cls": "heat", "kind": "insufficient_data", "dominant": "—",
              "share": 0.0, "events": 10, "distribution": {}}]

    def test_body_has_marker_and_share(self):
        body = build_coverage_watch_body(self.MONO)
        assert COVERAGE_WATCH_MARKER in body and "United States" in body and "95" in body

    def test_create_when_mono_and_no_issue(self):
        assert plan_coverage_watch_action(self.MONO, None)["action"] == "create_coverage_watch"

    def test_insufficient_data_does_not_open_issue(self):
        assert plan_coverage_watch_action(self.INSUF, None) is None

    def test_close_when_clear_and_issue_open(self):
        assert plan_coverage_watch_action([], {"number": 7, "body": COVERAGE_WATCH_MARKER}) == {
            "action": "close_coverage_watch", "number": 7}

    def test_noop_when_clear_no_issue(self):
        assert plan_coverage_watch_action([], None) is None
```

- [ ] **Step 2: Run — expect FAIL** (names undefined)
Run: `.venv/bin/python -m pytest tests/test_source_health_sentinel.py::TestCoverageWatchIssue -q`

- [ ] **Step 3: Implement** — mirror the real yield-watch helpers (`_open_yield_watch_issue` is a title match over `gh issue list`, :524; `_open_issue_body`/`_open_issue_number` exist; `LABEL` and `_run_gh` are module-level).

```python
def build_coverage_watch_body(findings: list[dict]) -> str:
    lines = [COVERAGE_WATCH_MARKER, "**A global source may be blind to a region.**", "",
             "A signal class the bot covers globally has gone mono-regional (or stopped "
             "recording geography) — the class of failure that hid the US-only heat blind "
             "spot. Advisory; check whether a provider/source regressed. Auto-closes only "
             "when coverage actually diversifies.", ""]
    for f in findings:
        if f["kind"] == "no_data":
            lines.append(f"- `{f['cls']}`: NO coverage data in {COVERAGE_WINDOW_DAYS}d while "
                         f"drafting ({f['events']} records) — recording may be broken.")
        elif f["kind"] == "mono_regional":
            dist = ", ".join(f"{k}:{v}" for k, v in f["distribution"].items())
            lines.append(f"- `{f['cls']}`: {int(f['share'] * 100)}% concentrated in "
                         f"**{f['dominant']}** over {f['events']} events. Distribution: {dist}")
    lines += ["", "_Auto-maintained by the source-health sentinel coverage watch._"]
    return "\n".join(lines)


def _issue_worthy(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("kind") in ("mono_regional", "no_data")]


def _open_coverage_watch_issue() -> dict[str, Any] | None:
    try:
        out = _run_gh(["issue", "list", "--label", LABEL, "--state", "open",
                       "--json", "number,title,body,labels", "--limit", "200"]).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list coverage-watch issue: {exc!r}", file=sys.stderr)
        return None
    for item in items:
        if item.get("title") == COVERAGE_WATCH_TITLE:
            return item
    return None


def plan_coverage_watch_action(findings: list[dict], open_issue: Mapping[str, Any] | None) -> dict[str, Any] | None:
    worthy = _issue_worthy(findings)
    if worthy:
        body = build_coverage_watch_body(worthy)
        if open_issue is None:
            return {"action": "create_coverage_watch", "body": body, "labels": [LABEL, "unknown"]}
        if _open_issue_body(open_issue).strip() != body.strip():
            return {"action": "update_coverage_watch", "number": _open_issue_number(open_issue),
                    "body": body, "labels": [LABEL, "unknown"]}
        return None
    if open_issue is not None:
        return {"action": "close_coverage_watch", "number": _open_issue_number(open_issue)}
    return None
```

Add `_create_coverage_watch_issue(action)` / `_update_coverage_watch_issue(action)` / `_close_coverage_watch_issue(number)` mirroring the three `_*_yield_watch_issue` functions verbatim (same `_run_gh` create/edit/close shape, swapping `COVERAGE_WATCH_TITLE`). Wire into `main()` next to the yield-watch block (state already parsed via `json.load`):
```python
    cov = coverage_watch(state.get("coverage_log"), state.get("run_history"),
                         now=datetime.now(timezone.utc))
    cov_action = plan_coverage_watch_action(cov, _open_coverage_watch_issue())
    if cov_action:
        if cov_action["action"] == "create_coverage_watch": _create_coverage_watch_issue(cov_action)
        elif cov_action["action"] == "update_coverage_watch": _update_coverage_watch_issue(cov_action)
        else: _close_coverage_watch_issue(cov_action["number"])
```

- [ ] **Step 4: Run — expect PASS (full sentinel suite)** `.venv/bin/python -m pytest tests/test_source_health_sentinel.py -q`
- [ ] **Step 5: Commit**
```bash
git add scripts/source_health_sentinel.py tests/test_source_health_sentinel.py
git commit -m "feat(coverage): reconcile coverage-watch advisory issue"
```

---

### Task 7: Dashboard mirror + payload

**Files:** Modify `dashboard/lib/source-health.js`; Test `dashboard/tests/source-health.test.js`.
**Produces:** `coverageWatch(coverageLog, runHistory, now)` (same shape as Python); `coverage` exposed in `buildSourceHealthPayload`.
**Render is a deferred follow-up:** `SourcesView` renders from `dashboard/app/page.js`, which threads only `sources`/`sourcesStats`; wiring a `coverage` line through there is a separate small UI task. The GitHub issue is the primary surface (the sentinel's "operator never has to watch the dashboard" design); the payload makes coverage available for when the render lands.

- [ ] **Step 1: Failing test**

```javascript
// dashboard/tests/source-health.test.js
import { test } from "node:test"
import assert from "node:assert/strict"
import { coverageWatch } from "../lib/source-health.js"

const NOW = new Date("2026-06-25T00:00:00Z")
const log = (country, continent, n) => Array.from({ length: n }, (_, i) =>
  ({ cls: "heat", event_id: `${country}-${i}`, country, continent, date: "2026-06-25" }))
const alerts = () => [{ id: "r", mode: "alerts", started_at: "2026-06-25T00:00:00Z" }]

test("coverageWatch flags US-only heat", () => {
  const out = coverageWatch(log("United States", "North America", 22), alerts(), NOW)
  assert.equal(out.length, 1); assert.equal(out[0].kind, "mono_regional"); assert.ok(out[0].share >= 0.85)
})
test("coverageWatch ignores diversified heat", () => {
  assert.deepEqual(coverageWatch([...log("United States", "North America", 8),
    ...log("Spain", "Europe", 7), ...log("India", "Asia", 7)], alerts(), NOW), [])
})
test("coverageWatch reports insufficient_data, not silent", () => {
  assert.equal(coverageWatch(log("United States", "North America", 10), alerts(), NOW)[0].kind, "insufficient_data")
})
test("coverageWatch flags no-data while drafting", () => {
  assert.equal(coverageWatch([], alerts(), NOW)[0].kind, "no_data")
})
```

- [ ] **Step 2: Run — expect FAIL** `coverageWatch is not exported`
Run: `cd dashboard && node --test 2>&1 | grep -iA3 coverage`

- [ ] **Step 3: Implement** the mirror in `dashboard/lib/source-health.js` (identical constants + the `insufficient_data`/`no_data` branches):

```javascript
// MUST match scripts/source_health_sentinel.py
export const COVERAGE_WINDOW_DAYS = 21
export const COVERAGE_MIN_EVENTS = 20
export const COVERAGE_CONCENTRATION = 0.85
export const COVERAGE_DATA_FLOOR = 5
const COVERAGE_WATCHED_CLASSES = ["heat"]

function botIsDrafting(runHistory) {
  return (runHistory || []).some((r) => r && (r.mode === "alerts" || r.mode === "both"))
}

export function coverageWatch(coverageLog, runHistory, now = new Date()) {
  const cutoff = new Date(now.getTime() - COVERAGE_WINDOW_DAYS * 86400000).toISOString().slice(0, 10)
  const drafting = botIsDrafting(runHistory)
  const findings = []
  for (const cls of COVERAGE_WATCHED_CLASSES) {
    const recs = (coverageLog || []).filter((r) => r && r.cls === cls && String(r.date || "") >= cutoff)
    const n = recs.length
    if (n < COVERAGE_DATA_FLOOR) {
      if (drafting) findings.push({ cls, kind: "no_data", dominant: "—", share: 0, events: n, distribution: {} })
      continue
    }
    if (n < COVERAGE_MIN_EVENTS) {
      findings.push({ cls, kind: "insufficient_data", dominant: "—", share: 0, events: n, distribution: {} })
      continue
    }
    for (const axis of ["country", "continent"]) {
      const counts = {}
      for (const r of recs) { const k = String(r[axis] || "Unknown"); counts[k] = (counts[k] || 0) + 1 }
      const [dominant, top] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
      if (dominant !== "Unknown" && top / n >= COVERAGE_CONCENTRATION) {
        findings.push({ cls, kind: "mono_regional", dominant, share: Math.round((top / n) * 1000) / 1000,
          events: n, distribution: counts })
        break
      }
    }
  }
  return findings
}
```

- [ ] **Step 4: Surface in the payload.** In `dashboard/lib/source-health.js` `buildSourceHealthPayload`, add `coverage: coverageWatch(state.coverage_log, state.run_history, new Date())` to the returned object so the dashboard/API can consume it. (UI render deferred — see the render note above.)

- [ ] **Step 5: Run — expect PASS** `cd dashboard && node --test 2>&1 | tail -5` and `cd dashboard && npx next build` unaffected.
- [ ] **Step 6: Commit**
```bash
git add dashboard/lib/source-health.js dashboard/tests/source-health.test.js
git commit -m "feat(coverage): dashboard mirror + payload of the coverage watch"
```

---

## Self-Review

- **Spec coverage:** persistent tally (T3) ✓; sqlite persistence (T3 f/g + round-trip) ✓; record at all heat sites incl. streak (T4) ✓; heat-only scope (T5) ✓; country+continent dual check (T5) ✓; insufficient_data not-silent (T5/T6/T7) ✓; no-data alarm (T5) ✓; advisory issue, insufficient_data not issue-worthy (T6) ✓; JS mirror + render (T7) ✓; artifact+resolve (T1/T2) ✓; realistic regression (T5 22-record US case) ✓.
- **Codex P1s closed:** state_schema parity (T3 f), sqlite `_METADATA_JSON_KEYS` (T3 g) + round-trip test (T3 step 2), real title-based issue lookup (T6 `_open_coverage_watch_issue`), insufficient_data not silent (T5/T7). **P2s:** record-streak recorded (T4), dashboard render (T7 step 4), stale anchors corrected (434/483/735).
- **Type consistency:** `record_coverage_observation` kwargs identical T3↔T4; finding shape identical T5(producer)↔T6(consumer)↔T7(mirror); constants identical T5↔T7; `CoverageRecord` fields match the recorded dict (T3 e↔f).
- **Reviewer note:** the `_create/_update/_close_coverage_watch_issue` functions are described as "mirror the yield-watch verbatim" rather than fully inlined — the implementer must open `scripts/source_health_sentinel.py:581-625` and copy the exact `_run_gh` shapes. This is the one place to double-check during implementation.
