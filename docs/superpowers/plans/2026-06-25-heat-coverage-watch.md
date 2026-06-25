# Heat Coverage Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect when @theheat's heat detector silently goes mono-regional (the GHCN US-only blind spot), by recording each surfaced heat event's geography into a persistent rolling tally and opening an advisory issue when one country/continent dominates.

**Architecture:** Geography is recorded **at the source** (`run_extreme_signals`, where heat events carry a clean `country`) into a new persistent `coverage_log` in state — decoupled from the 20-run `run_history` cap so the window is long enough to be reliable. Continent is resolved once at record time (`src/coverage.py`) and stored, so the Python sentinel check and the JS dashboard mirror just read pre-computed `{country, continent}` — no map duplication. The check is a pure function reconciled into one advisory auto-closing GitHub issue, mirroring the existing yield-watch.

**Tech Stack:** Python 3.12 (bot + sentinel, pytest), Node 24 (dashboard, `node --test`), state persisted as JSON in a GitHub gist.

## Global Constraints

- Python: `ruff check src/ scripts/` clean, `mypy src/` clean, `pytest` green (run via `.venv/bin/python -m pytest`).
- Dashboard: `node --test` green; `next build` unaffected.
- Stage only the files each task names — never `git add -A`. Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- The sentinel is a reporter, never a gate: `scripts/source_health_sentinel.py` must keep exiting 0.
- Python and JS thresholds (Task 5/7) MUST hold identical numeric values; each side asserts them in its own test.
- No bot/scoring/provider behavior changes — recording is additive and best-effort (a recording failure must never break a draft).

**Tunables (single source of truth, copied verbatim into both languages):**
`COVERAGE_WINDOW_DAYS = 21`, `COVERAGE_MIN_EVENTS = 20`, `COVERAGE_CONCENTRATION = 0.85`, `COVERAGE_DATA_FLOOR = 5`.

---

### Task 1: Country→continent artifact + generator

**Files:**
- Create: `scripts/build_country_continent.py`
- Create: `data/country_continent.json` (generated output, committed)

**Interfaces:**
- Produces: `data/country_continent.json` — `{ "<cities.csv country string>": "<continent>" }`, e.g. `{"US": "North America", "France": "Europe", "China": "Asia"}`.

- [ ] **Step 1: Write the generator**

```python
# scripts/build_country_continent.py
"""Derive country -> continent from data/cities.csv lat/lon.

cities.csv is the curated city set the Open-Meteo heat path samples, so its
country strings are exactly what heat events emit (except GHCN's "United States",
which is_us_location handles at resolve time). Re-run when cities.csv changes:
    python scripts/build_country_continent.py
"""
import csv
import json
from collections import Counter


def continent_for(lat: float, lon: float) -> str:
    if lat <= -60:
        return "Antarctica"
    if lat <= 0 and 110 <= lon <= 180:
        return "Oceania"
    if -56 <= lat <= 14 and -82 <= lon <= -34:
        return "South America"
    if lat >= 7 and -170 <= lon <= -50:
        return "North America"
    if 34 <= lat <= 72 and -25 <= lon <= 60:
        return "Europe"
    if -37 <= lat <= 37 and -20 <= lon <= 52:
        return "Africa"
    if -15 <= lat <= 82 and 25 <= lon <= 180:
        return "Asia"
    return "Unknown"


def build(cities_path: str = "data/cities.csv") -> dict[str, str]:
    votes: dict[str, Counter] = {}
    with open(cities_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            country = (row.get("country") or "").strip()
            if not country:
                continue
            cont = continent_for(float(row["lat"]), float(row["lon"]))
            votes.setdefault(country, Counter())[cont] += 1
    return {c: v.most_common(1)[0][0] for c, v in sorted(votes.items())}


if __name__ == "__main__":
    mapping = build()
    with open("data/country_continent.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    print(f"wrote data/country_continent.json ({len(mapping)} countries)")
```

- [ ] **Step 2: Generate the artifact**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat && .venv/bin/python scripts/build_country_continent.py`
Expected: `wrote data/country_continent.json (~170 countries)`. Spot-check: `US`→`North America`, `France`→`Europe`, `China`→`Asia`, `Australia`→`Oceania`.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_country_continent.py data/country_continent.json
git commit -m "feat(coverage): country->continent artifact derived from cities.csv"
```

---

### Task 2: `src/coverage.py` — continent resolution

**Files:**
- Create: `src/coverage.py`
- Test: `tests/test_coverage.py`

**Interfaces:**
- Consumes: `data/country_continent.json` (Task 1).
- Produces: `is_us_location(country: str | None) -> bool`; `resolve_continent(country: str | None) -> str` (returns a continent name or `"Unknown"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coverage.py
from src.coverage import is_us_location, resolve_continent


def test_us_forms_resolve_to_north_america():
    assert is_us_location("US") is True
    assert is_us_location("United States") is True
    assert is_us_location("Northern Mariana Islands [United States]") is True
    assert resolve_continent("United States") == "North America"
    assert resolve_continent("US") == "North America"


def test_non_us_resolves_via_map():
    assert is_us_location("United Kingdom") is False
    assert resolve_continent("France") == "Europe"
    assert resolve_continent("China") == "Asia"


def test_unknown_country_is_unknown():
    assert resolve_continent("Atlantis") == "Unknown"
    assert resolve_continent("") == "Unknown"
    assert resolve_continent(None) == "Unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_coverage.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.coverage'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/coverage.py
"""Resolve an event's country to a continent for the coverage watch.

The country -> continent map is derived from cities.csv (data/country_continent.json,
built by scripts/build_country_continent.py). US name-forms are normalised here so
both the Open-Meteo ("US") and GHCN ("United States", territory brackets) heat paths
land in North America.
"""
from __future__ import annotations

import json
import os
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
    if not c:
        return "Unknown"
    if is_us_location(c):
        return "North America"
    return _country_continent().get(c, "Unknown")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_coverage.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/coverage.py tests/test_coverage.py
git commit -m "feat(coverage): resolve_continent + is_us_location"
```

---

### Task 3: State `coverage_log` — schema, merge, record helper, prune

**Files:**
- Modify: `src/state.py` (DEFAULT_STATE ~line 75; merge-spec ~line 1740; add helpers + merge fn)
- Test: `tests/test_coverage_state.py`

**Interfaces:**
- Consumes: `src.coverage.resolve_continent` (Task 2).
- Produces:
  - `record_coverage_observation(state: BotState, *, cls: str, event_id: str, country: str | None, when: str | date | None, now: datetime | None = None) -> None` — appends `{cls, event_id, country, continent, date}` to `state["coverage_log"]`, dedups on `event_id`, prunes older than `COVERAGE_WINDOW_DAYS`. Never raises.
  - `COVERAGE_WINDOW_DAYS = 21` (module constant in `src/state.py`).
  - `_merge_coverage_log(current, incoming) -> list[dict]` registered for the `coverage_log` key.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coverage_state.py
from datetime import datetime, timezone

from src import state as state_mod
from src.state import _fresh_state, record_coverage_observation


def _now(d="2026-06-25"):
    return datetime.fromisoformat(d + "T00:00:00+00:00")


def test_record_appends_with_resolved_continent():
    s = _fresh_state()
    record_coverage_observation(s, cls="heat", event_id="e1", country="United States",
                                when="2026-06-25", now=_now())
    assert s["coverage_log"] == [
        {"cls": "heat", "event_id": "e1", "country": "United States",
         "continent": "North America", "date": "2026-06-25"}
    ]


def test_record_dedups_on_event_id():
    s = _fresh_state()
    for _ in range(2):
        record_coverage_observation(s, cls="heat", event_id="e1", country="Spain",
                                    when="2026-06-25", now=_now())
    assert len(s["coverage_log"]) == 1


def test_record_prunes_older_than_window():
    s = _fresh_state()
    record_coverage_observation(s, cls="heat", event_id="old", country="Spain",
                                when="2026-05-01", now=_now())
    record_coverage_observation(s, cls="heat", event_id="new", country="Spain",
                                when="2026-06-25", now=_now())
    ids = {r["event_id"] for r in s["coverage_log"]}
    assert ids == {"new"}  # 2026-05-01 is > 21 days before 2026-06-25


def test_record_never_raises_on_bad_input():
    s = _fresh_state()
    record_coverage_observation(s, cls="heat", event_id="e1", country=None, when=None)
    assert s["coverage_log"][0]["continent"] == "Unknown"


def test_merge_dedups_concurrent_writers():
    a = [{"cls": "heat", "event_id": "e1", "country": "US", "continent": "North America", "date": "2026-06-25"}]
    b = [{"cls": "heat", "event_id": "e1", "country": "US", "continent": "North America", "date": "2026-06-25"},
         {"cls": "heat", "event_id": "e2", "country": "Spain", "continent": "Europe", "date": "2026-06-25"}]
    merged = state_mod._merge_coverage_log(a, b)
    assert {r["event_id"] for r in merged} == {"e1", "e2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_coverage_state.py -q`
Expected: FAIL — `ImportError: cannot import name 'record_coverage_observation'`.

- [ ] **Step 3: Implement**

In `src/state.py`:

(a) Add to `DEFAULT_STATE` (next to `"run_history": [],` ~line 75):
```python
    "coverage_log": [],  # rolling per-surfaced-event geography for the coverage watch
```

(b) Add module constant near the top-of-file constants:
```python
COVERAGE_WINDOW_DAYS = 21
```

(c) Add the merge function (next to `_merge_run_history`):
```python
def _merge_coverage_log(current: list[dict], incoming: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    anonymous: list[dict] = []
    for rec in [*(current or []), *(incoming or [])]:
        rec_id = rec.get("event_id")
        if not rec_id:
            anonymous.append(dict(rec))
        else:
            by_id[rec_id] = dict(rec)  # last writer wins; identical events collapse
    return [*by_id.values(), *anonymous]
```

(d) Register it in the merge-spec map (the dict that holds `"run_history": _merge_run_history,` ~line 1740):
```python
    "coverage_log": _merge_coverage_log,
```

(e) Add the record helper (mirror `increment_data_source_failure`'s style):
```python
def record_coverage_observation(
    state: BotState,
    *,
    cls: str,
    event_id: str,
    country: str | None,
    when: "str | date | None",
    now: datetime | None = None,
) -> None:
    """Append one surfaced-event geography record; dedup on event_id; prune window.

    Best-effort: never raises (a recording failure must not break a draft).
    """
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
        log.append({
            "cls": cls,
            "event_id": event_id,
            "country": country or "",
            "continent": resolve_continent(country),
            "date": date_str,
        })
        cutoff = (now - timedelta(days=COVERAGE_WINDOW_DAYS)).date().isoformat()
        state["coverage_log"] = [r for r in log if str(r.get("date") or "") >= cutoff]
    except Exception:
        pass
```

Ensure `date`, `timedelta`, `UTC` are imported in `src/state.py` (they are used elsewhere; verify with `grep -n "from datetime" src/state.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coverage_state.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_coverage_state.py
git commit -m "feat(coverage): coverage_log state tally (record, merge, prune)"
```

---

### Task 4: Record heat geography in `run_extreme_signals`

**Files:**
- Modify: `src/orchestrator/sources/open_meteo.py` (after the per-city heat enqueue ~line 421; after the country-record enqueue ~line 711)
- Test: `tests/test_open_meteo_orchestrator.py` (add one test)

**Interfaces:**
- Consumes: `state.record_coverage_observation` (Task 3).
- Produces: a heat record in `bot_state["coverage_log"]` for every surfaced heat city + country record.

- [ ] **Step 1: Write the failing test** (append to `tests/test_open_meteo_orchestrator.py`)

```python
def test_surfaced_heat_event_records_coverage(monkeypatch):
    from datetime import date

    from src.data.open_meteo import AbsoluteExtremeEvent, ExtremeSignalBundle
    from src.orchestrator.sources import open_meteo as runner
    from src.state import _fresh_state

    ev = AbsoluteExtremeEvent(
        city="Seville", country="Spain", today_temp_c=45.1, band_label="Temperate",
        threshold_c=42.0, kind="hot", lat=37.4, lon=-6.0,
        event_id="absextreme_Seville_2026-06-25", signal_date=date(2026, 6, 25),
    )
    bundle = ExtremeSignalBundle(city="Seville", country="Spain", absolute_extreme=ev,
                                 signal_date=date(2026, 6, 25))
    bot_state = _fresh_state()
    current_run = {"id": "r1", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z", "sources": []}
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setattr(runner, "_check_city_extreme_signals", lambda cities, m: ([bundle], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", lambda *a, **k: True)

    runner.run_extreme_signals(bot_state, current_run, [], {}, {})

    recs = [r for r in bot_state["coverage_log"] if r["event_id"] == "absextreme_Seville_2026-06-25"]
    assert recs and recs[0]["cls"] == "heat" and recs[0]["continent"] == "Europe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_open_meteo_orchestrator.py::test_surfaced_heat_event_records_coverage -q`
Expected: FAIL — `coverage_log` has no matching record.

- [ ] **Step 3: Implement** — add recording at both heat enqueue sites.

After the per-city enqueue (the `if candidate_queued:` block opens at ~line 437; add at the TOP of that block, so it records whenever a heat city is surfaced):
```python
                if candidate_queued:
                    state.record_coverage_observation(
                        bot_state, cls="heat", event_id=strongest_event_id,
                        country=bundle.country, when=bundle.signal_date,
                    )
```

After the country-record enqueue succeeds (inside `if _enqueue_story_candidate(...): country_count += 1` ~line 711):
```python
            ):
                country_count += 1
                state.record_coverage_observation(
                    bot_state, cls="heat", event_id=cr.event_id,
                    country=cr.country, when=cr.signal_date,
                )
```

- [ ] **Step 4: Run tests to verify pass (and nothing regressed)**

Run: `.venv/bin/python -m pytest tests/test_open_meteo_orchestrator.py -q`
Expected: PASS (all, including the new test).

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/sources/open_meteo.py tests/test_open_meteo_orchestrator.py
git commit -m "feat(coverage): record heat geography at the enqueue sites"
```

---

### Task 5: `coverage_watch` classifier (sentinel)

**Files:**
- Modify: `scripts/source_health_sentinel.py` (add constants + classifier near `yield_watch_sources`)
- Test: `tests/test_source_health_sentinel.py` (add a class)

**Interfaces:**
- Consumes: `state["coverage_log"]` (Task 3/4), `state["run_history"]` (liveness cross-check).
- Produces: `coverage_watch(coverage_log, run_history, *, now) -> list[dict]` — returns finding dicts. Each finding: `{"cls": str, "kind": "mono_regional"|"no_data", "dominant": str, "share": float, "events": int, "distribution": dict}` (for `no_data`, `dominant`/`share` describe why).

- [ ] **Step 1: Write the failing test**

```python
# in tests/test_source_health_sentinel.py
from datetime import datetime, timezone
from scripts.source_health_sentinel import coverage_watch


def _log(country, continent, n, cls="heat", day="2026-06-25"):
    return [{"cls": cls, "event_id": f"{country}-{i}", "country": country,
             "continent": continent, "date": day} for i in range(n)]


def _alerts_run():
    return [{"id": "run_alerts_x", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z"}]


class TestCoverageWatch:
    NOW = datetime(2026, 6, 25, tzinfo=timezone.utc)

    def test_us_only_heat_flags_mono_regional(self):
        out = coverage_watch(_log("United States", "North America", 22), _alerts_run(), now=self.NOW)
        assert len(out) == 1
        f = out[0]
        assert f["kind"] == "mono_regional" and f["cls"] == "heat"
        assert f["dominant"] in ("United States", "North America") and f["share"] >= 0.85

    def test_diversified_heat_does_not_flag(self):
        log = (_log("United States", "North America", 8) + _log("Spain", "Europe", 6)
               + _log("India", "Asia", 4) + _log("Brazil", "South America", 4))
        assert coverage_watch(log, _alerts_run(), now=self.NOW) == []

    def test_below_min_events_does_not_flag(self):
        assert coverage_watch(_log("United States", "North America", 10), _alerts_run(), now=self.NOW) == []

    def test_no_data_while_drafting_flags(self):
        out = coverage_watch([], _alerts_run(), now=self.NOW)
        assert len(out) == 1 and out[0]["kind"] == "no_data"

    def test_no_data_quiet_bot_does_not_flag(self):
        assert coverage_watch([], [], now=self.NOW) == []  # no alerts runs => bot not active
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_source_health_sentinel.py::TestCoverageWatch -q`
Expected: FAIL — `ImportError: cannot import name 'coverage_watch'`.

- [ ] **Step 3: Implement** (add to `scripts/source_health_sentinel.py`)

```python
COVERAGE_WINDOW_DAYS = 21
COVERAGE_MIN_EVENTS = 20
COVERAGE_CONCENTRATION = 0.85
COVERAGE_DATA_FLOOR = 5
COVERAGE_WATCHED_CLASSES = ("heat",)  # extend per source instrumentation (Future)
COVERAGE_WATCH_TITLE = "Coverage watch: a global source may be blind to a region"
COVERAGE_WATCH_MARKER = "<!-- source-health-coverage-watch -->"


def _bot_is_drafting(run_history: list[dict] | None) -> bool:
    return any(
        str(r.get("mode") or "") in ("alerts", "both")
        for r in (run_history or [])
        if isinstance(r, Mapping)
    )


def coverage_watch(
    coverage_log: list[dict] | None,
    run_history: list[dict] | None,
    *,
    now: datetime,
) -> list[dict]:
    """Flag a watched class whose surfaced geography is mono-regional, or missing.

    Pure: continent/country are pre-computed in each record (src/coverage.py).
    """
    cutoff = (now - timedelta(days=COVERAGE_WINDOW_DAYS)).date().isoformat()
    drafting = _bot_is_drafting(run_history)
    findings: list[dict] = []
    for cls in COVERAGE_WATCHED_CLASSES:
        recs = [
            r for r in (coverage_log or [])
            if isinstance(r, Mapping) and r.get("cls") == cls
            and str(r.get("date") or "") >= cutoff
        ]
        n = len(recs)
        if n < COVERAGE_DATA_FLOOR:
            if drafting:
                findings.append({"cls": cls, "kind": "no_data", "dominant": "—",
                                 "share": 0.0, "events": n, "distribution": {}})
            continue
        if n < COVERAGE_MIN_EVENTS:
            continue
        for axis in ("country", "continent"):
            counts: dict[str, int] = {}
            for r in recs:
                key = str(r.get(axis) or "Unknown")
                counts[key] = counts.get(key, 0) + 1
            dominant, top = max(counts.items(), key=lambda kv: kv[1])
            share = top / n
            if dominant != "Unknown" and share >= COVERAGE_CONCENTRATION:
                findings.append({"cls": cls, "kind": "mono_regional", "dominant": dominant,
                                 "share": round(share, 3), "events": n,
                                 "distribution": dict(sorted(counts.items(), key=lambda kv: -kv[1]))})
                break  # one finding per class; country axis takes precedence
    return findings
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/test_source_health_sentinel.py::TestCoverageWatch -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/source_health_sentinel.py tests/test_source_health_sentinel.py
git commit -m "feat(coverage): coverage_watch classifier (mono-regional + no-data)"
```

---

### Task 6: Coverage-watch issue reconciliation (sentinel `main`)

**Files:**
- Modify: `scripts/source_health_sentinel.py` (body builder + plan/create/update/close + wire into `main`)
- Test: `tests/test_source_health_sentinel.py` (add a class)

**Interfaces:**
- Consumes: `coverage_watch` (Task 5), the existing yield-watch issue helpers as the pattern.
- Produces: `build_coverage_watch_body(findings) -> str`; `plan_coverage_watch_action(findings, open_issue) -> dict | None` returning `{"action": "create_coverage_watch"|"update_coverage_watch"|"close_coverage_watch", ...}`.

- [ ] **Step 1: Write the failing test**

```python
# in tests/test_source_health_sentinel.py
from scripts.source_health_sentinel import (
    build_coverage_watch_body, plan_coverage_watch_action, COVERAGE_WATCH_MARKER,
)


class TestCoverageWatchIssue:
    FIND = [{"cls": "heat", "kind": "mono_regional", "dominant": "United States",
             "share": 0.95, "events": 22, "distribution": {"United States": 21, "Spain": 1}}]

    def test_body_has_marker_and_proxy_note(self):
        body = build_coverage_watch_body(self.FIND)
        assert COVERAGE_WATCH_MARKER in body
        assert "United States" in body and "95" in body

    def test_create_when_findings_and_no_open_issue(self):
        action = plan_coverage_watch_action(self.FIND, None)
        assert action["action"] == "create_coverage_watch"

    def test_close_when_no_findings_and_open_issue(self):
        action = plan_coverage_watch_action([], {"number": 7, "body": COVERAGE_WATCH_MARKER})
        assert action == {"action": "close_coverage_watch", "number": 7}

    def test_noop_when_no_findings_no_issue(self):
        assert plan_coverage_watch_action([], None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_source_health_sentinel.py::TestCoverageWatchIssue -q`
Expected: FAIL — names not defined.

- [ ] **Step 3: Implement** (mirror `build_yield_watch_body` / `plan_yield_watch_action`)

```python
def build_coverage_watch_body(findings: list[dict]) -> str:
    lines = [
        COVERAGE_WATCH_MARKER,
        "**A global source may be blind to a region.**",
        "",
        "A signal class the bot is supposed to cover globally has gone mono-regional "
        "(or stopped recording geography). This is the class of failure that hid the "
        "US-only heat blind spot. Advisory; investigate whether a provider/source "
        "regressed. Auto-closes only when coverage actually diversifies.",
        "",
    ]
    for f in findings:
        if f["kind"] == "no_data":
            lines.append(f"- `{f['cls']}`: NO coverage data in the last "
                         f"{COVERAGE_WINDOW_DAYS}d while the bot is drafting "
                         f"({f['events']} records) — recording may be broken.")
        else:
            dist = ", ".join(f"{k}:{v}" for k, v in f["distribution"].items())
            lines.append(f"- `{f['cls']}`: {int(f['share'] * 100)}% concentrated in "
                         f"**{f['dominant']}** over {f['events']} events. Distribution: {dist}")
    lines.append("")
    lines.append("_Auto-maintained by the source-health sentinel coverage watch._")
    return "\n".join(lines)


def _open_coverage_watch_issue() -> dict | None:
    return _find_marker_issue(COVERAGE_WATCH_MARKER)  # reuse yield-watch lookup helper


def plan_coverage_watch_action(findings: list[dict], open_issue: dict | None) -> dict | None:
    if findings:
        body = build_coverage_watch_body(findings)
        if open_issue is None:
            return {"action": "create_coverage_watch", "body": body,
                    "labels": ["source-health-sentinel", "unknown"]}
        if _open_issue_body(open_issue).strip() != body.strip():
            return {"action": "update_coverage_watch",
                    "number": _open_issue_number(open_issue), "body": body}
        return None
    if open_issue is not None:
        return {"action": "close_coverage_watch", "number": _open_issue_number(open_issue)}
    return None
```

Note: the yield-watch uses an inline `_open_yield_watch_issue` that lists issues by title. Refactor that lookup into a shared `_find_marker_issue(marker)` (search open issues whose body contains `marker`) OR copy the title-search shape with `COVERAGE_WATCH_TITLE`. The body-marker search is more robust to title edits; if refactoring is too invasive for this task, mirror the title-search exactly. Add `_create_coverage_watch_issue` / `_update_coverage_watch_issue` / `_close_coverage_watch_issue` mirroring the three yield-watch issue functions (gh issue create/edit/close), and wire into `main()` next to the yield-watch block:

```python
    coverage_findings = coverage_watch(
        (state or {}).get("coverage_log"), (state or {}).get("run_history"),
        now=datetime.now(timezone.utc),
    )
    cov_action = plan_coverage_watch_action(coverage_findings, _open_coverage_watch_issue())
    if cov_action:
        if cov_action["action"] == "create_coverage_watch":
            _create_coverage_watch_issue(cov_action)
        elif cov_action["action"] == "update_coverage_watch":
            _update_coverage_watch_issue(cov_action)
        else:
            _close_coverage_watch_issue(cov_action["number"])
```

- [ ] **Step 4: Run tests + full sentinel suite**

Run: `.venv/bin/python -m pytest tests/test_source_health_sentinel.py -q`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add scripts/source_health_sentinel.py tests/test_source_health_sentinel.py
git commit -m "feat(coverage): reconcile coverage-watch advisory issue"
```

---

### Task 7: Dashboard JS mirror

**Files:**
- Modify: `dashboard/lib/source-health.js` (add `coverageWatch` + constants; surface in the payload)
- Test: `dashboard/tests/source-health.test.js` (add cases)

**Interfaces:**
- Consumes: `state.coverage_log`, `state.run_history`.
- Produces: `coverageWatch(coverageLog, runHistory, now)` returning the same finding shape as the Python classifier; surfaced via `buildSourceHealthPayload`.

- [ ] **Step 1: Write the failing test**

```javascript
// in dashboard/tests/source-health.test.js
import { test } from "node:test"
import assert from "node:assert/strict"
import { coverageWatch } from "../lib/source-health.js"

const NOW = new Date("2026-06-25T00:00:00Z")
const log = (country, continent, n) =>
  Array.from({ length: n }, (_, i) => ({ cls: "heat", event_id: `${country}-${i}`,
    country, continent, date: "2026-06-25" }))
const alertsRun = () => [{ id: "r", mode: "alerts", started_at: "2026-06-25T00:00:00Z" }]

test("coverageWatch flags US-only heat", () => {
  const out = coverageWatch(log("United States", "North America", 22), alertsRun(), NOW)
  assert.equal(out.length, 1)
  assert.equal(out[0].kind, "mono_regional")
  assert.ok(out[0].share >= 0.85)
})

test("coverageWatch ignores diversified heat", () => {
  const out = coverageWatch([...log("United States", "North America", 8),
    ...log("Spain", "Europe", 7), ...log("India", "Asia", 7)], alertsRun(), NOW)
  assert.deepEqual(out, [])
})

test("coverageWatch flags no-data while drafting", () => {
  assert.equal(coverageWatch([], alertsRun(), NOW)[0].kind, "no_data")
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && node --test 2>&1 | grep -i coverage`
Expected: FAIL — `coverageWatch` is not exported.

- [ ] **Step 3: Implement** (mirror the Python; identical constants)

```javascript
// dashboard/lib/source-health.js
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
  const cutoff = new Date(now.getTime() - COVERAGE_WINDOW_DAYS * 86400000)
    .toISOString().slice(0, 10)
  const drafting = botIsDrafting(runHistory)
  const findings = []
  for (const cls of COVERAGE_WATCHED_CLASSES) {
    const recs = (coverageLog || []).filter(
      (r) => r && r.cls === cls && String(r.date || "") >= cutoff)
    const n = recs.length
    if (n < COVERAGE_DATA_FLOOR) {
      if (drafting) findings.push({ cls, kind: "no_data", dominant: "—", share: 0, events: n, distribution: {} })
      continue
    }
    if (n < COVERAGE_MIN_EVENTS) continue
    for (const axis of ["country", "continent"]) {
      const counts = {}
      for (const r of recs) { const k = String(r[axis] || "Unknown"); counts[k] = (counts[k] || 0) + 1 }
      const [dominant, top] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
      const share = top / n
      if (dominant !== "Unknown" && share >= COVERAGE_CONCENTRATION) {
        findings.push({ cls, kind: "mono_regional", dominant, share: Math.round(share * 1000) / 1000,
          events: n, distribution: counts })
        break
      }
    }
  }
  return findings
}
```

Then surface it in `buildSourceHealthPayload` (add `coverage: coverageWatch(state.coverage_log, state.run_history, new Date())` to the returned object so the dashboard can render it).

- [ ] **Step 4: Run tests to verify pass**

Run: `cd dashboard && node --test 2>&1 | tail -5`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/source-health.js dashboard/tests/source-health.test.js
git commit -m "feat(coverage): dashboard mirror of the coverage watch"
```

---

## Self-Review

- **Spec coverage:** persistent tally (T3) ✓; record at source (T4) ✓; heat-only scope (T5 `COVERAGE_WATCHED_CLASSES`) ✓; country+continent dual check (T5) ✓; no-data alarm (T5) ✓; realistic thresholds (Global Constraints) ✓; advisory issue (T6) ✓; JS mirror (T7) ✓; country_continent artifact (T1) + resolve (T2) ✓; realistic regression test (T5 `test_us_only_heat_flags_mono_regional` with 22 records) ✓.
- **Placeholder scan:** Task 6 names a `_find_marker_issue` refactor with an explicit fallback (mirror the title-search) — not a placeholder, a decision with a concrete default. All other steps carry real code.
- **Type consistency:** `record_coverage_observation` keyword args match between T3 (def) and T4 (calls); finding dict shape matches between T5 (producer), T6 (consumer), T7 (mirror); constants identical across T5/T7.
- **Open risk for the reviewer:** Task 6 depends on the exact yield-watch helper names (`_open_issue_body`, `_open_issue_number`, the gh issue create/edit/close shape). The implementer must read `scripts/source_health_sentinel.py:457-686` and mirror precisely; if the yield-watch issue lookup is title-based, use `COVERAGE_WATCH_TITLE`, not a body-marker search.
