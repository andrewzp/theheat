# #414 — Global heat records-cluster (executable plan)

> Successor to row 13 (US population-extent, **dropped as off-brand**). Design
> spike (GO): [2026-07-08-heat-records-cluster-spike.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-07-08-heat-records-cluster-spike.md).
> Issue [#414](https://github.com/andrewzp/theheat/issues/414). Binds to
> [INDEX.md §Standing rules](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md).
> **REQUIRED SUB-SKILL:** superpowers:test-driven-development throughout.
> **Design hardened by codex-xhigh (2026-07-08): 4 P0s + 3 P1s fixed below** —
> geography purity, transcontinental continent, "heat dome" wording, suppression ordering,
> dedup-key signature, manual-only approval.

## Story

The heat-dome's many-records story, **global from day one** — it rides the already-worldwide
daily calendar-record station list (GHCN US + Open-Meteo world cities); no US-alert
dependency. That is exactly why it is on-brand where row-13 was not.

**The published copy never asserts "heat dome"** — that is an unproven synoptic *cause*, and
the bundle proves only spatially-clustered same-day daily records. The tweet states the
verifiable fact: *"record-setting heat clustered across [region] — N cities set daily highs
the same day."* "Heat dome" is the internal name for the class, not a claim the tweet makes
(codex P0-3; mirrors the fact-check rule that forbids attributing a precip cluster to a
weather system without a carried cause, fact_check_prompt.py:169-177).

## Locked design decisions

1. **New top-level `signal_kind = "heat_records_cluster"`** (NOT a sub-kind of
   `simultaneous_records`). A spatially-coherent dome is a stronger story than a scattered
   same-day count, so it gets its own scoring, threshold, writer/fact-check treatment, and
   dedup state key.
2. **Global by construction.** Clusters the worldwide daily calendar-highs (GHCN-US +
   Open-Meteo-world). NEVER narrow to the US.
3. **Ships behind a default-OFF flag** `THEHEAT_RECORDS_CLUSTER_ENABLED` (mirrors A0/A1/A2
   and every prior row): `os.environ.get(..., "") == "1"`. Flag OFF ⇒ byte-identical to
   today. Andrew flips in prod.
4. **Manual-approval only, even when enabled** (codex P1-3). This is a geography-honesty-
   sensitive class like `regional_anomaly` / `wet_bulb_extreme` — add to the manual-only set
   in `src/editorial/approval.py`; it never autoships.
5. **Supersedes the flat `simultaneous_records` on clustered dates.** When the flag is ON and
   ≥1 cluster fires for a date, the flat `simultaneous_records` draft for that same date is
   suppressed (the dome is the better primitive). No cluster on a date ⇒ existing
   `simultaneous_records` behavior is unchanged.
6. **Honest naming is the crux** (see Honesty invariants). Tiered, first match wins:
   documented reganom zone (country-**pure** + geographically contained) → else "N cities
   across {k} countries[ in {continent(s)}]". Never coin a region name; never assert a
   continent that isn't unambiguous.
7. **v1 = daily calendar records** (the data already collected). Monthly/all-time tier
   clustering is a natural v2. Out of scope for this build.

## Tuning defaults — TASTE CALLS for Andrew (module constants, calibrate later)

| Constant | Default | Meaning |
|---|---|---|
| `LINK_KM` | 350.0 | single-linkage join distance (cities within this chain into one cluster) |
| `MIN_CLUSTER_SIZE` | 6 | minimum cities to clear the "many records" bar |
| `ZONE_MEMBER_KM` | 300.0 | a city is geographically "in" a reganom zone if within this of any zone point (a **support** check, not the authority — see purity below) |
| `ZONE_CONTAINMENT_FRACTION` | 0.80 | min fraction of cluster cities geographically inside a zone (support) |
| `MAX_NAMED_COUNTRIES` | 3 | cap on countries enumerated in the tier-2 label ("led by …") |
| `heat_records_cluster` editorial threshold | ~80 | ≥ `simultaneous_records` (78); a dome is a stronger signal |

Module constants (reganom convention: detection thresholds live in code; only the enable
flag is env). Surface current values + a live writer sample to Andrew; he tunes via a fast
follow-up once we have a few weeks of cluster counts.

## Honesty invariants (never weaken) — the crux, codex-hardened

The bundle carries `city_count`, `sample_cities`, `cluster_countries` (full verifiable
list), `cluster_continents` (list, possibly empty), and `region_name` (documented reganom
zone name **or null**). Every one is a precomputed bundle fact the writer cites verbatim.

**Tier-1 naming requires PURITY, not just proximity (codex P0-1).** The reganom zones are
~6 representative *points*, and Iberia's points sit one strait from Maghreb's — so a
distance-only test can name a Spain+Morocco cluster "Iberia". Fix: a records-cluster-owned
`ZONE_COUNTRIES: dict[zone_name, frozenset[country]]` table (the documented countries of each
of the 16 zones). A cluster earns a zone name **only if** every cluster city's country ∈
`ZONE_COUNTRIES[zone]` (purity — one outside city ⇒ fall back) **and** ≥
`ZONE_CONTAINMENT_FRACTION` of its cities are within `ZONE_MEMBER_KM` of the zone's points
(geographic support — so an all-Spain cluster in the Canaries isn't "Iberia"). Country
strings must match the station data exactly (verify against `data/cities.csv` +
`is_us_location` in PR-A).

**Tier-2 continent must not mislabel transcontinental countries (codex P0-2).**
`resolve_continent("Russia")` → "Asia", so a western-Russia cluster would read "in Asia".
Fix: the **country list is the verifiable backbone** and always named; the continent is a
nicety, asserted only when unambiguous. Maintain `TRANSCONTINENTAL_COUNTRIES` (Russia,
Turkey, Kazakhstan, Egypt, …); if any cluster country is transcontinental OR resolves to
"Unknown", **omit the continent** and say only "N cities across K countries" (+ lead
countries). Otherwise take the unique `resolve_continent` set (may be >1: Spain+Morocco →
"Europe and Africa" — both named, both true).

**Enforced in three layers** (mirrors `regional_anomaly` + `country_precip_event`):
1. writer prose section in `writer_prompt.py` (what each label means; cite verbatim; the
   only named region is the carried `region_name`; if null, name only continent(s)+countries;
   **never "heat dome"** / "blocking ridge" / any single-system cause);
2. a lettered fact-check rule in `fact_check_prompt.py` (only carried geography labels; count
   is not a national total; no region beyond `region_name`; no synoptic-cause attribution);
3. `historical_context["forbidden_claims"]` populated by the bundle builder + the
   deterministic `_forbidden_claim_violation` gate in `pipeline.py:21-43` **extended to fire
   for `heat_records_cluster`** — a hard backstop listing "heat dome", "heat-dome",
   "blocking high/ridge", and (when `region_name` is null) continent-wide/"-wide" phrasings.
   NB curly-apostrophe normalization already handled in that gate.

## PR-A — foundation (pure math + data augmentation), zero behavior change

Dead-but-tested code + a harmless additive data field; nothing consumes the module until
PR-B, so no flag needed here.

**A1. Data augmentation (one line).** `src/orchestrator/sources/open_meteo.py:502` — add
`"lat": ev_cdh.lat, "lon": ev_cdh.lon` to the `simultaneous_record_stations.append({...})`
dict. `RecordEvent` already carries `lat`/`lon`, populated by BOTH providers
(`ghcn.py:481-482`, `data/open_meteo.py:741-742`) → global for free. (The independent
cluster-input collection PR-B relies on lives in the same append shape; keeping lat/lon here
also feeds the flag-off flat lane harmlessly.) Update the docstring shape notes in
`build_simultaneous_records_bundle` (temperature.py:526-529) and `select_roll_call_subset`
(simultaneous_format.py:44-52) — informational; both ignore unknown keys.

**A2. New pure module `src/editorial/records_cluster.py`:**
- `cluster_record_stations(stations, *, link_km=LINK_KM, min_size=MIN_CLUSTER_SIZE) -> list[list[dict]]`
  — filter to stations with numeric lat & lon; deterministic sort by
  `(lat, lon, city, country)`; single-linkage union-find (great-circle ≤ link_km, chained
  transitively) via `_haversine_km` reused from `src/editorial/_regions.py`; return groups
  with `len ≥ min_size`, each group sorted, groups sorted by `(-size, first-station-key)`.
  O(n²) pairwise is fine (n ≤ a few hundred/cycle).
- `name_cluster(stations) -> ClusterName` (frozen dataclass: `region_name: str | None`,
  `continents: list[str]`, `countries: list[str]` sorted by (-record_count, name),
  `lead_countries: list[str]`, `country_count`, `city_count`).
  - **Tier 1:** best zone where cluster is country-**pure** (all countries ∈
    `ZONE_COUNTRIES[zone]`) AND geographically contained (≥ `ZONE_CONTAINMENT_FRACTION`
    within `ZONE_MEMBER_KM`); tie-break (‑containment, name).
  - **Tier 2:** `region_name=None`; `continents` = unique `resolve_continent(country)` for
    all countries **iff** no country is transcontinental/Unknown, else `[]` (omit).
  - Owns `ZONE_COUNTRIES` (16 zones) + `TRANSCONTINENTAL_COUNTRIES`; reuses `REGION_WATCHLIST`
    points + `resolve_continent` — no new geo *data files*.

**A2 tests** (`tests/test_records_cluster.py`, pure, deterministic, no I/O):
- clustering: one tight cluster; two far-apart domes stay separate; a chain (A–B–C each ≤
  link, A–C > link) → one cluster (single-linkage); below-min dropped; missing-lat/lon
  excluded; shuffled input → identical output; empty/degenerate.
- naming (incl. **codex's cited failure cases**): all-France cluster → `"France"`;
  **Spain+Morocco cluster → region_name=None, continents=["Africa","Europe"]** (the
  anti-"Iberia" purity case); broad multi-country Europe dome no single zone contains →
  `region_name=None` (anti-"Western Europe"); **western-Russia cluster → continents=[]**
  (transcontinental omit, countries named); **Turkey/Istanbul → continents=[]**;
  unknown-country row → that country still listed, continent omitted; containment boundary
  (just above/below 0.80); lead-country cap + count ordering.

## PR-B — integration (bundle, detection, writer, fact-check, state), behind the flag

**B1. Bundle builder** — `src/two_bot/intern/temperature.py`:
`build_heat_records_cluster_bundle(stations, name, *, event_id, when)` →
`StoryBundle(signal_kind="heat_records_cluster", where=<region_name or continent/country
label>, when, event_id, headline_metric={label:"cities_breaking_record", value:city_count,
unit:"cities"}, current_facts=[city_count, cluster_countries, cluster_continents, region_name,
sample_cities], historical_context={scope, stations, forbidden_claims:[…]},
raw_signal_dump={stations, event_id})`. Passes `audit_story_bundle`. Export in
`intern/__init__.py` (import + `__all__`).

**B2. Scoring + threshold** — `score_heat_records_cluster(city_count, country_count,
region_name)` in `scoring/temperature.py` (a dome ≥ a scattered count; region-named or
multi-country adds novelty); `"heat_records_cluster"` `ThresholdEntry` (~80) in
`thresholds.py`; wrapper + `__all__` in `scoring/__init__.py`; re-export + `__all__` in
`orchestrator/common.py`.

**B3. Detection wiring — a PREPASS, because daily drafts enqueue mid-loop (codex P0-4/P1-1).**
Individual daily `record` candidates are enqueued *during* the per-bundle cascade
(open_meteo.py:536); the flat simultaneous block runs *after* (open_meteo.py:815). So
post-loop suppression is impossible. Fix: when `THEHEAT_RECORDS_CLUSTER_ENABLED=1`, run a
**prepass before the cascade**:
  1. Collect cluster-input rows **independently** from `bundle.calendar_date_high` for every
     bundle that has one (NOT from the cascade-winning `simultaneous_record_stations`, which
     omits cities whose all-time/monthly/anomaly signal won) — `{city, country, lat, lon,
     temp_c, signal_date, cal_event_id}`.
  2. `cluster_record_stations` per date group → clusters.
  3. Build `suppressed_daily_event_ids` = the `cal_event_id`s of clustered cities whose daily
     record would otherwise be the *individual* draft (all-time/monthly still draft — bigger
     story), and `fired_cluster_dates`.
Then in the cascade, when a `calendar_date_high` would win and its event_id ∈
`suppressed_daily_event_ids`, **skip its enqueue**. After the loop, enqueue the
`heat_records_cluster` bundles (score → `_should_draft` → new-key `is_duplicate` → build →
`_enqueue_story_candidate(legacy_type="heat_records_cluster", on_draft_success=recorder)`),
and **skip the flat `simultaneous_records`** enqueue for `fired_cluster_dates`. Flag OFF ⇒
prepass skipped, no suppression, today's path byte-identical (regression test asserts this).

**B4. State dedup key — signature hash, explicitly consulted (codex P1-2).** Generic
`is_duplicate` only inspects `posted_events` (state.py:1361), so the cluster must dedup on its
own map. Event id `heat_records_cluster_{date}_{sig}` where `sig` = short **deterministic**
`hashlib` digest of the sorted `(city, country, round(lat,1), round(lon,1))` member rows
(stable across processes; naming-independent; collision-safe for two clusters same date).
Full new-key checklist (verified on disk): `DEFAULT_STATE` (state.py) + `state_schema`
TypedDict (total=False) + `MERGE_SPEC` strategy (per-key union) + regenerate golden
(`scripts/gen_merge_golden.py`) + `_METADATA_JSON_KEYS` (sqlite_store.py — the **sqlite
persistence contract**) + `_TIER_TTLS_DAYS` + `_touch_tier` (bounded growth, #390) + recorder
fn (record-on-draft-success) + `is_duplicate`/recorder call site. Bespoke
`*_survive_sqlite_round_trip` test + merge/recorder unit tests.

**B5. Cooldown + prune maps** — `_SIGNAL_KIND_TO_CATEGORY["heat_records_cluster"]`
(two_bot/memory.py); `_PRUNE_SOURCE_KEY_BY_TYPE["heat_records_cluster"] =
"open_meteo_extreme_signals"` (orchestrator/finalize.py). Leave OUT of
`_SINGLE_COUNTRY_SIGNAL_KINDS` (multi-country by design) and forecast-tense sets.

**B6. Approval policy (codex P1-3)** — add `"heat_records_cluster"` to the manual-only set in
`src/editorial/approval.py:234` + an autoship-exclusion test (mirrors `regional_anomaly` /
`wet_bulb_extreme`).

**B7. Writer + fact-check prose** — `writer_prompt.py`: `## Heat records cluster` section
(labels' meaning, cite verbatim, region_name-or-continent rule, **no "heat dome"/single
cause**). `fact_check_prompt.py`: lettered guard after rule q, mirroring `country_precip_event`
(169-177) — only carried geography labels; no region beyond `region_name`; count is not a
national total; synoptic-cause attribution UNVERIFIABLE. `pipeline.py`: extend
`_forbidden_claim_violation` to fire for `heat_records_cluster` against `forbidden_claims`.

**B8. Registry test updates** — `test_thresholds.py`, `test_editorial_scoring.py`,
`test_orchestrator_common_shim.py`, `two_bot/test_intern.py`, `test_approval*` (autoship
exclusion), plus new detection/dedup/writer wiring tests. TDD: dryrun voice-verify a sample
cluster tweet (mirror rows 5/11).

## Test / verify strategy

- TDD every unit: PR-A pure math first (red→green), then PR-B builder/score/state/detection.
- Before every push: `.venv/bin/ruff check src/ tests/` + `.venv/bin/mypy src/` +
  `THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q` all green; fixtures
  today-relative.
- Flag-OFF regression: the same-day path is byte-identical with the flag unset (no prepass).
- codex-xhigh (looped to clean APPROVE, last round after last edit) on BOTH PRs. PR-A's review
  concretely re-validates the namer honesty (the crux). Mandatory.

## Risks

- **Mislabeling geography** (the crux) — mitigated by tier-1 country-purity + tier-2
  omit-when-ambiguous + triple honesty enforcement. Tests pin codex's Spain+Morocco and
  Russia/Turkey cases.
- **Unwarranted "heat dome" cause** — forbidden in copy (writer + fact-check + deterministic
  gate); tweet states only the clustered-records fact.
- **Double-coverage / bad suppression ordering** — the prepass computes clusters before any
  daily enqueue; supersede skips flat on clustered dates; all-time/monthly individual drafts
  survive.
- **State growth** (#390 over budget) — dedup key is TTL-pruned + a compact signature.
- **Coords gaps** — cities without lat/lon silently excluded from clustering (same as
  elevation today); acceptable for v1.
- **Tuning uncalibrated** — L/N/containment first-guess; flag stays OFF + manual-approval
  until Andrew reviews a live sample. No prod risk.

## Standing-rules compliance

One code PR each (A, B) with VERSION bump + CHANGELOG `[Unreleased]`; this plan doc + INDEX
update ride their own docs PR. `cd … && PATH=/opt/homebrew/bin:$PATH` on every command.
Claude merges (checks green → squash → verify `git log origin/main`). Honesty gates only
tighten. New DEFAULT_STATE key rides the sqlite contract test. Python↔JS mirrors: none touched
(Python-only detection; no JS classifier mirror for this class).
