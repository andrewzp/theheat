# Codex Code Review — PR #84 (P1 belt-and-suspenders + P3 seasonal-context)

Repo: `~/Documents/Claude/theheat` (github.com/andrewzp/theheat).
Date authored: 2026-05-12.
PR: https://github.com/andrewzp/theheat/pull/84
Branch: `p1-p3-belt-and-suspenders` (single commit `17fbfa6` on top of `48ee110`).

## Why this review exists

This PR implements two IMPROVEMENT_PLAN proposals the daily grading agent has been logging for two cycles. The author claims:

1. **P1 is pure defense** — `normalize_station_name` is idempotent, so adding it at the bundle boundary doesn't change behavior on the production path, only hardens against future drift.
2. **P3 loosens one rule that the HARD RULES section already covers** — removing the "[country]'s fire/storm/wet season peaks in [month]" ban is safe because `NO FABRICATED CONTEXT` with its 95%+ confidence gate already catches invented seasonal claims.

Both claims are plausible but unverified. Your job is to falsify them, or confirm them with evidence — not vibes.

The author also tweaked the IMPROVEMENT_PLAN's proposed P3 text mid-implementation because the proposed second example collided with the prompt's wink-kicker ban. That kind of mid-flight redesign is exactly where bugs slip in. Scrutinize the resulting paragraph for internal consistency.

## Scope

Three files in one commit:

```bash
git log -1 --stat 17fbfa6
```

- `src/two_bot/intern.py` — added `normalize_station_name()` call in 4 bundle builders
- `src/two_bot/prompts/writer_prompt.py` — removed one bullet from the "do NOT write" list, added one paragraph to the "IF historical_context IS EMPTY" section
- `tests/two_bot/test_intern.py` — 5 new tests

Read `docs/IMPROVEMENT_PLAN.md` sections P1 and P3 for the framing the author is implementing against. **Then verify the implementation matches the spec and doesn't introduce new failure modes.**

## What to focus on

Five lenses, leverage-ordered.

### 1. P3 — Did removing the seasonality ban open a real hole?

The change deletes this bullet from `writer_prompt.py` (the "IF historical_context IS EMPTY → do NOT write" list):

> - "[country]'s fire/storm/wet season peaks in [month]."

The author justifies it with: "the HARD RULES NO FABRICATED CONTEXT rule (with its 95%+ confidence gate) still catches truly invented seasonal claims."

**Verify this is actually true.** Read both:

- The deleted bullet's context (around old line 56)
- The HARD RULES section (`NO FABRICATED CONTEXT` paragraph, currently around line 85)

Specifically test these scenarios against the *current* prompt (post-P3):

- Writer gets a fire bundle from Burundi (a less-known country) with no historical_context. Writes "Burundi's fire season peaks in August." Is that blocked by the remaining HARD RULES? The writer's training-data confidence on Burundi's fire-season month is plausibly <95%, but the writer might still emit it without self-flagging.
- Writer gets a Sahel fire bundle. Writes "The Sahel dry season runs December-March." This IS well-established world knowledge. Should ship. Does the prompt clearly permit it?
- Writer gets an Iberian fire bundle. Writes "Spain's wildfire season typically peaks in August." Spain is well-known but the specific month claim is archive-style. Edge case — is the prompt clear on which side this falls?

**Hypothesis to test:** the deleted bullet was load-bearing for the middle case (less-known countries with specific month claims) and the HARD RULES alone don't catch that class. If so, the loosening over-corrects.

### 2. P3 — Internal consistency of the new paragraph

Read the new paragraph the author added (the "Seasonal context for fires is world knowledge" block) and check it against:

- **Line 80 (wink-kicker ban).** The new paragraph explicitly cites the ban: "integrate the seasonal frame into the one-clause system explanation, do not tack on a separate calendar-stamp closer." But does the writer model actually parse this distinction reliably? The ban-list on line 80 includes "It is April." — and the IMPROVEMENT_PLAN's original P3 text used exactly that shape ("It is [current month].") as a *positive* example. The author trimmed the conflicting example but the underlying tension (seasonal context vs. calendar wink) is fuzzy. Could the writer, reading both rules, hallucinate that the calendar wink IS permitted "inside the system clause"?

- **Fire exemplar #4** ("A fire in Mali is radiating 361 MW of heat... Mali sits in the Sahel; dry-season fire behavior turns on how long grasses stay cured before rain.") — this exemplar already integrates seasonal context (dry-season behavior) without naming a month. Is the new paragraph asking for *more* than the exemplar already permits? Or just clarifying what the exemplar already does?

- **THE SIGNATURE MOVE three-beat structure** (around line 22). The new paragraph asks the writer to put seasonal context INSIDE the system clause (beat 2). Does that math work — system clause is ONE compressed sentence; can it fit seasonal mechanism + the climate/geographic mechanism the exemplar shows?

**Concrete test:** draft a Sahel fire tweet (480 MW, no historical_context) under the new prompt. Show what the writer would plausibly emit. Does it look like the exemplar, or like a wink-kicker dressed up as a system clause?

### 3. P1 — Coverage gap on bundle builders

The author normalized 4 builders:

- `build_monthly_high_bundle` (intern.py:~209)
- `build_record_bundle` (intern.py:~301)
- `build_all_time_record_bundle` (intern.py:~391)
- `build_anomaly_bundle` (intern.py:~455)

Other builders in the same file that may also handle GHCN-derived city names:

- `build_country_record_bundle` — uses `cr.peak_city` and `cr.old_record_city`. If the country aggregator pulls peak cities from GHCN stations, those names could carry suffixes. Check the call path from `detect_country_records` → does it use `normalize_station_name` upstream?
- `build_record_streak_bundle` — uses `ev.city`. Does record-streak detection use GHCN as a data source? If yes, same suffix-leak risk.
- `build_simultaneous_records_bundle` — uses `station["city"]` for each station in the list. Where do those city strings come from? If GHCN, suffix risk.
- `build_fire_bundle` — uses `fire.nearest_city` — different data source (FIRMS), unlikely to have GHCN suffixes, but verify.
- `build_storm_surge_bundle`, `build_river_flood_bundle`, `build_marine_heatwave_bundle` — water-related, different data sources, but verify.

**Run this to enumerate every city/where source:**

```bash
grep -n "where=\|ev.city\|cr\.\|peak_city\|station_name\|station\[" src/two_bot/intern.py
```

For each builder NOT normalized in this PR, judge: should it be? If yes, that's a coverage gap.

### 4. P1 — `raw_signal_dump` leak

The author normalized `where` and `current_facts.city` but NOT `raw_signal_dump`. The bundle's `raw_signal_dump = asdict(ev)` captures the full event dataclass including `ev.city`.

In current production: `ghcn.py:381` sets `ev.city` to the normalized form before constructing the event, so `asdict(ev).city` is already clean. No leak. But the entire premise of this PR is "what if a future code path bypasses ghcn.py:381?" — and in *that* hypothetical, the bundle's `where` and `current_facts.city` would be clean (because of the new normalization) but `raw_signal_dump.city` would still be raw.

**Verify:**

- Does the fact-checker (`src/two_bot/fact_check.py` and `src/two_bot/prompts/fact_check_prompt.py`) read `raw_signal_dump` at all? Or only `where`, `current_facts`, `headline_metric`, `historical_context`?
- If the fact-checker DOES inspect `raw_signal_dump.city`, the P1 fix is incomplete — `where` says "Paddock Lake" but `raw_signal_dump.city` says "Paddock Lake 4 Ne", and a strict fact-checker would flag the discrepancy.
- If the fact-checker does NOT inspect `raw_signal_dump`, the leak is academic. But is there a different consumer (dashboard, memory layer, observability) that *does* read it and might surface the inconsistency to a human reviewer?

The author's defense-in-depth claim is only meaningful if the boundary is actually tight. A bundle with `where: "Paddock Lake"` and `raw_signal_dump.city: "Paddock Lake 4 Ne"` is internally inconsistent.

### 5. Tests — are they testing the right invariants?

Read the 5 new tests in `tests/two_bot/test_intern.py` (search for "normalizes_suffixed_city" and "idempotent_in_bundle"). For each:

- **Could the test pass while the production code is still broken?** Specifically, the idempotency test uses `"San Juan"` — a name with no strippable suffix. If someone removed the `normalize_station_name()` call from `build_monthly_high_bundle` entirely, would this test still pass? Yes — because `ev.city = "San Juan"` would round-trip unchanged through the builder. The test doesn't actually exercise the normalization code path; it just confirms that *if* normalization runs, it doesn't over-normalize.

- The 4 "normalizes_suffixed_city" tests DO exercise the code path (they pass raw suffixed names). They'd catch a removal. Good.

- **What's missing?** A test that uses an all-caps acronym station name like `"JFK"`. The `normalize_station_name` function has a special case for 2-3 char all-caps tokens (returns as-is). If a bundle builder somehow lowercased before normalizing, the acronym path would silently break. Should there be a test for this?

- The 4 suffixed tests use `source="ghcn"`. The idempotency test uses default `source="open_meteo"`. Is there asymmetric behavior between the two sources that could let a regression slip through one path but not the other?

### 6. Meta: process consistency

- The PR description claims `894 → 899 tests passed (+5 new)`. Verify by running `python -m pytest tests/ -q -m "not voice_replay"` on the branch.
- The PR does NOT update `CHANGELOG.md` or `IMPROVEMENT_PLAN.md` to mark P1 (belt-and-suspenders) and P3 as shipped. The author's pattern in PR #82 was to defer docs to a separate sweep commit (ad2f346 on `docs-sweep-2026-05-12-late`). Is that the intent? If so, will the daily grading agent's next refinement of IMPROVEMENT_PLAN correctly mark these as resolved, or will it re-propose them?
- Voice-regression fixtures (`tests/voice_replay/`) are excluded from the local test run. P3 changes the writer prompt — does any existing fixture exercise the path that's now permitted (fire bundle with empty historical_context expecting seasonal-context output)? If yes, the fixture's expected output may need updating. If no, there's no fixture protecting the new behavior.

## Output format

Produce findings in this shape:

```
## Finding N — <one-line title>

**Severity:** P0 / P1 / P2 / P3 (P0 = ships a regression; P3 = nit)
**Location:** file:line
**Claim:** what the author asserted (PR description or commit message)
**Evidence:** what the code actually does (quote/cite)
**Risk:** what could happen in production
**Fix:** specific change (file:line + diff sketch)
```

Order findings P0 → P3. If you find no P0/P1, say so explicitly — don't pad with nits.

If you find that the author's claims hold up under scrutiny, **say that too**. A clean review is a useful signal.

## Out of scope

- The docs-sweep commit `ad2f346` on `docs-sweep-2026-05-12-late` (not part of this PR; it's the daily grading agent's automated docs refresh).
- The four production fixes in PR #82 (already merged, already reviewed by the production data itself).
- Architecture changes (new modules, tool swaps, new data sources). This is a code-review of a 134-line patch, not a redesign.
