# Row 14 — Two small lifts: fire geocode precision + the geographic-spread cap

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. TWO INDEPENDENT PRs. PR-A is data-labeling only (one codex
> round). PR-B touches triage selection → codex-xhigh MANDATORY.

## PR-A: Fire geocode precision (kill the coordinate-string label)

**Goal:** A FIRMS hotspot outside the ~80 `_GEO_BOXES` stops being labeled
`"22.3N, 88.1E", country="Unknown"` (`src/data/firms.py:402-414`'s fallback) — the
label a reader can't place and the writer can't qualify.

**Architecture:** Two-step fallback upgrade in `reverse_geocode_simple`: when
`_lookup_box` misses, find the nearest `data/cities.csv` place (638 rows,
`load_cities()` at `src/data/open_meteo.py:218-220`, `_haversine_km` from
`src/editorial/_regions.py:127`) within `GEOCODE_NEAR_CITY_MAX_KM = 300.0`; if found,
label `region=f"near {city}"`, `country=<city's country>`; only beyond 300 km of
every curated city does the coordinate-string fallback remain (open ocean, deep
polar — honest and rare). Cache the loaded cities at module level (the fetch loop
calls this per hotspot).

- [ ] **Failing tests** (in the firms test module): a point 100 km from a curated
city outside every box → `("near <city>", <country>)`; a mid-Pacific point → the
coordinate-string fallback unchanged; a point inside a box → box result unchanged
(boxes stay first — they carry curated editorial region names like "the Amazon
Basin" that beat "near Manaus").
- [ ] **Implement** (module-level `_CITIES_CACHE: list[dict] | None`, loaded lazily
inside the function with a try/except that degrades to the old fallback if the CSV
is unreadable — geocoding must never break the fire fetch).
- [ ] **Writer-prompt touch (paired):** the geography-qualifier rule already demands
country qualification; add one clause to the fire section's field list noting
`nearest_region` may be `"near <city>"` — cite it verbatim, never upgrade it to a
claim the fire is IN that city.
- [ ] Gates → PR (`fix(firms): nearest-city geocode fallback — no more unplaceable
coordinate labels`) → one codex round (attack: cache thread-safety under
THEHEAT_CONCURRENT_SOURCES; the 300 km bound's honesty — "near X" at 299 km is a
stretch; codex may push it to 150–200, take its number) → merge → verify the next
FIRMS cycle's out-of-box fires carry named labels.

## PR-B: The per-country spread cap in triage (flag-gated)

**Goal:** A hot day in one country can no longer fill the whole cycle: the survivor
loop gets a per-country soft cap, exactly parallel to the existing per-category and
pending-type caps — the IDEAS.md geographic-spread item, made concrete.

**Architecture:** `select_survivors` (`src/orchestrator/triage.py:214-305`) gains a
third counting dict in its survivor loop. Country comes from
`candidate.bundle.country` (`StoryBundle.country`, `src/two_bot/types.py:57`) with
fallbacks: `bundle.country or _country_from_where(bundle.where) or ""` — where
`_country_from_where` takes the last comma-segment of the `where` string ("Phoenix,
Arizona, United States" → "United States"); empty string is NEVER capped (unknown
geography must not be suppressed). Env `THEHEAT_PER_COUNTRY_CAP`, default `0` =
DISABLED (flag-gated ship; Andrew flips to `2` after watching a few cycles' spill
logs).

- [ ] **Failing tests** (beside the existing `select_survivors` tests in
`tests/test_triage.py`): cap disabled by default (5 same-country candidates → all
rank as today); cap=2 → third same-country candidate spills with
`reasons=["per_country_cap=2"]` and `kill_stage="triage_cap"`; empty-country
candidates never spill on this rule; the spill is recorded via the existing
`_record_triage_suppression` with the new reason string; ordering among survivors
otherwise unchanged (score DESC, created_at DESC).
- [ ] **Implement**: read the env in a `_per_country_cap()` helper mirroring
`_per_category_cap()` (~line 53); in the loop (after the pending-type check, before
the global-cap check) — same shape as `by_category`:

```python
        country_cap = _per_country_cap()
        # ... in the loop:
        country = _candidate_country(candidate)
        if country_cap > 0 and country:
            if by_country.get(country, 0) >= country_cap:
                spilled.append((candidate, "per_country_cap"))
                continue
```

with the increment beside the other two on admit, and `_candidate_country(c)` doing
the bundle.country/where fallback. Extend `_record_triage_suppression`'s reason
plumbing only if the reason string doesn't already flow through generically (read it
first — it takes `reason` today).
- [ ] **bot.yml passthrough** for `THEHEAT_PER_COUNTRY_CAP` (house comment pattern,
default '0').
- [ ] Version/changelog/gates → PR → codex-xhigh loop (attack: interaction ordering
with per-category and pending-type caps — a candidate spilled by country must not
also decrement other counters; the `where`-parsing fallback on bundles with
non-standard where strings; determinism under equal scores; dashboard suppression
rendering of the new reason) → merge → **live verify:** leave the cap at 0 for two
cycles (no behavior change confirmed in the ledger), then Andrew sets `2`; watch one
hot cycle's spills carry `per_country_cap=2` and the queue's country mix widen.

**Success criteria:** PR-A — zero `country="Unknown"` fire drafts in the next week's
corpus; PR-B — no cycle after activation drafts 3 signals from one country while a
qualified second-country candidate spills for global-cap reasons alone.
