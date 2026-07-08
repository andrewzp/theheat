# Heat records-cluster — design spike (global "a heat dome broke records across [region]")

> **Protocol, not a build plan.** Read-only design pass; deliverable is a go/no-go +
> design sketch appended here. No code ships from the spike. Follow-up to issue **#414**
> and the row-13 heat-dome discussion (row 13 = US *population extent*, this = global
> *records cluster*). Answers Andrew's framing question: **how do we tell the story of a
> heat dome that breaks many records across a region — including multi-country domes,
> small countries, and flat domes with no elevation diversity?**

## The problem the spike must solve

A heat dome is a **spatial blob** that ignores political and predefined boundaries. Every
clustering unit the bot has is one of those boundaries, and each fails:

- **Country** (the existing `simultaneous_records` roll-call groups by country): a Western
  European dome fragments across France/Belgium/Netherlands/Germany/Switzerland; small
  countries (Monaco, Luxembourg, Belgium — 1–2 monitored cities) never reach any
  per-country threshold.
- **reganom's 16 `REGION_WATCHLIST` zones** (`src/data/reanalysis_anomaly.py`): a curated
  mix — `France`, `Iberia`, `United Kingdom & Ireland`, `Central Mediterranean`, … but
  **no "Western Europe," no Low Countries, no western Germany**. A broad European heat
  wave still fragments; Paris counts under "France," Brussels/Amsterdam/Cologne fall
  through.
- **US-state boxes** (`src/editorial/_regions.py`): US-only, too fine.

So the clustering must be **spatial (cross-border)**, and the resulting blob must be
**named honestly** — the hard part, because a wrong region label ("Europe" for an
Iberia+Maghreb cluster) is a geography-honesty failure, the same class the bot guards
everywhere else.

## Findings

### Q1 — Data availability: **GO (global).**
- **Daily heat records per city are already collected globally.**
  `simultaneous_record_stations` (`src/orchestrator/sources/open_meteo.py:502`) captures
  every calendar-day heat record each cycle — `{city, country, temp_c, margin_c,
  old_record_year, elevation_m, signal_date}` — from **GHCN (US-deep) + Open-Meteo
  (curated world cities incl. Europe/Asia)**. This is *why* the class can be global where
  row-13 population-extent could not: the record data is worldwide, no US-alert feed.
- **`lat`/`lon` are not in that dict today** but are known per city (city coords) — a
  one-line augmentation is the only data change needed for spatial clustering.
- **All-time / monthly per-city records** are detected as their own signals
  (`ghcn.py:442`, `open_meteo.py:757`) but are NOT collected into a clusterable list —
  including them is a small extra collection step (see Q4).

### Q2 — Clustering rule: **single-linkage by great-circle distance.**
- Group same-day (or short-window) record-breaking cities by proximity: two cities join
  the same cluster when within a link distance **L** of each other; chaining lets a
  contiguous dome (1,000–2,500 km across) form one cluster without merging two distinct
  domes. Sketch: **L ≈ 300–400 km**, tunable.
- **Minimum cluster size N** (sketch: **≥ 6–8 cities**) to clear the "many records" bar
  and stay above the noise of a couple scattered records.
- Deterministic (sort cities by (lat, lon, name); stable cluster ids) — no run-to-run
  drift (the same discipline `select_roll_call_subset` already enforces).

### Q3 — Honest naming: **tiered, country-list-safe (the honesty gate).**
Never coin a sub-continental region unless it is a *documented* zone. Label in this order,
first match wins:
1. **Cluster ⊆ one reganom `REGION_WATCHLIST` zone** → use that zone's name (a documented
   synoptic region, e.g. "the Indo-Gangetic Plain," "the Desert Southwest"). Require a
   high containment fraction (sketch ≥ 80% of cluster cities inside the zone's footprint).
2. **Else** → **"N cities across {k} countries in {continent}"**, naming the top few
   countries by record count. **Continent is always verifiable** from a city's coords
   (a coarse continent bounding-box lookup — small new util); the **country list is a
   bundle fact** (each city's country is known). Neither overclaims.
3. Cap the enumerated countries (e.g. "across 6 countries in Europe, led by France,
   Spain, and Italy").
- **Failure modes this avoids:** inventing "Western Europe" for a cluster that is really
  Iberia + Maghreb (spans into Africa); calling an Iberia-only cluster "Europe-wide."
  The continent + country-list fallback cannot mislabel because both are directly
  verifiable; the only *named region* allowed is a pre-documented reganom zone.
- The bundle carries `cluster_countries`, `cluster_continent`, `region_name_or_null`,
  `city_count`, `sample_cities` — the writer cites them verbatim; a fact-check rule pins
  "no region name beyond the carried `region_name`; continent + country list only."

### Q4 — Record tier scope: **v1 daily; tier-aware later.**
- v1 clusters **daily** records (the data already collected) — "N cities set daily highs
  across …".
- A dome pushing many cities to **monthly/all-time** highs is a bigger story; collecting
  those per-city records into the same cluster and **leading with the strongest tier
  present** is the natural v2. Keep tiers explicit in the count (never blur "daily" into
  "all-time").

### Q5 — Dedup / relationship to existing classes.
- **`simultaneous_records`** (global same-day count + country roll-call): the spatial
  cluster is the **better primitive** — the flat global count is just the degenerate
  "one big cluster" case. Recommendation: the new detector **supersedes**
  `simultaneous_records` for clustered events (fire the spatial cluster; retire or
  down-rank the global flat count) so the two don't double-cover.
- **Individual per-city records** (`all_time_high`/`monthly_high`/daily): when a city is
  part of a fired cluster, **suppress its individual *daily* draft** for that window (the
  cluster is the story). An individual **all-time** record may still merit its own draft
  even inside a cluster (bigger than the aggregate) — keep that, dedup only daily.
- **reganom (`regional_anomaly`)**: different metric (mean anomaly vs record count); may
  coexist, but if both fire for the same region+window, prefer the concrete records
  cluster. Soft dedup on (region, date).

## Go/No-Go — **GO.**
1. ✅ **Data** — daily records collected globally; lat/lon a one-line add.
2. ✅ **Clustering** — single-linkage by distance, tunable L + min-size, deterministic.
3. ✅ **Honest naming** — the crux — has a **non-overclaiming default** (continent +
   country list), with a documented-region name only when containment justifies it.

**Recommended build shape (when scheduled):** evolve `simultaneous_records` into a
**spatial-cluster detector** over the global daily-record station list (augmented with
lat/lon); single-linkage cluster (L≈350 km, N≥6); the tiered honest namer
(reganom-zone → continent+country-list); a `heat_records_cluster` bundle carrying
`city_count`/`sample_cities`/`cluster_countries`/`cluster_continent`/`region_name`; a
writer section + fact-check rule that permit ONLY the carried geography labels; dedup by
suppressing constituent daily drafts and superseding the flat global count. Editorial +
detection surface → codex-xhigh mandatory. **Global from day one** (unlike row-13 US
population-extent). Not data-gated — buildable whenever prioritized.

**Open tuning for the build (not blockers):** L and N (calibrate against a few weeks of
record-station counts); the reganom-zone containment fraction; whether v1 includes
monthly/all-time tiers.

*(No code shipped. Grounded in the codebase 2026-07-08; see #414.)*
