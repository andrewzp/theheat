# Row 13 — Heat-dome / population-exposure class: the design spike (read-only)

> **⛔ SUPERSEDED 2026-07-08 — the GO below is void.** This class is US-only by
> construction (NWS alerts + US Census), and **US-only/US-focused coverage is off-brand
> for @theheat, a global account.** Abandoned; PR-A (#415) reverted. The heat-dome story
> is the **global records-cluster** — see
> [2026-07-08-heat-records-cluster-spike.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-07-08-heat-records-cluster-spike.md)
> (#414). Kept for the record only.

> **Protocol, not a build plan.** Timebox: one session. Deliverable: a go/no-go with a
> design sketch, appended to THIS file under "Findings". No code ships from the spike.
> Any session (or a lesser model) can run it — every step is read-only investigation.

**The story class we can't see:** "200M+ Americans under extreme-heat alerts" led the
world's front page the first week of July 2026; the bot had no path to it. Every heat
signal is a point/sampled-city metric; nothing aggregates ALERT EXTENT × POPULATION.

## Questions the spike must answer (with evidence links pasted into Findings)

1. **US half — does the NWS alerts feed carry enough?** The bot already fetches
   `api.weather.gov/alerts/active` (`src/data/nws_alerts.py`; currently a 9-type
   allow-list including Extreme Heat Warning). Answer from the live API + docs:
   (a) do alert objects carry affected-zone IDs (`geocode`/`UGC`/`affectedZones`)?
   (b) is there a static, downloadable zone→population table (NWS zone shapefiles ×
   census; or does the CAP payload itself carry population)? (c) what would "N million
   under Extreme Heat Warning/Watch" cost to compute per cycle — fetch size, zone
   count, a cached zone-population file's size?
2. **Honesty shape:** is the claim "N million people were under extreme-heat warnings"
   constructable from feed facts alone (zone populations summed), and what are the
   double-counting traps (overlapping zones, Watch vs Warning, marine zones)? What
   precision is honest (round to the nearest 10M)?
3. **World half — is there any equivalent?** MeteoAlarm (Europe) awareness levels;
   anything machine-readable elsewhere? If the world half is thin, is a US-only class
   acceptable given the coverage-watch will flag mono-country patterns (it watches
   heat already) — or does US-only violate the global-coverage bar? (Note: reganom
   already covers the world's regional-heat story; the exposure class may honestly be
   US-first the way `fire_footprint` is, with the world half via row 10's feeds.)
4. **Threshold shape:** what makes an exposure reading EXTRAORDINARY vs routine
   summer? (Sketch: a floor like ≥50M under Warning-tier, or a percentile vs a rolling
   baseline the state would keep — which needs state design.) One draft per event-peak,
   dedup like tier crossings?
5. **Overlap check:** does this duplicate `severe_weather` (which already passes
   Extreme Heat Warning through per-alert, threshold 58)? The new class is the
   AGGREGATE story; confirm the dedup story between one mega-alert draft and many
   per-alert drafts.

## Method

- Read `src/data/nws_alerts.py` + one live `curl` of the active-alerts API with an
  Extreme Heat filter; paste a trimmed sample alert JSON into Findings.
- WebSearch/WebFetch for the zone-population dataset question (NWS public zone
  shapefiles; census gridded population; any ready-made zone-pop CSV) — cite exact
  URLs and licenses.
- Write the go/no-go: GO requires (1) zone→population resolvable from static public
  data ≤ a few MB cached, (2) the honest claim constructable per §2, (3) a defensible
  extraordinariness floor per §4. NO-GO or DEFER otherwise, with the specific blocker
  named.

## Findings

**Spike run 2026-07-07 (read-only, timeboxed one session). Verdict: GO — US-first,
county-scoped.** The aggregate "population under extreme-heat warnings" class is
buildable **cheaply and honestly** for the US half. The world half is thin (no public
population feed), so US-first is the recommendation — consistent with `fire_footprint`
being US-first and reganom already carrying the world's regional-heat story.

### Q1 — Does the NWS feed carry enough? **YES.**
- **Zone IDs present.** Every active alert's `properties.geocode` carries `UGC`
  (forecast-zone codes, e.g. `FLZ008`) and `SAME` (6-digit county codes); `affectedZones`
  lists `https://api.weather.gov/zones/forecast/<UGC>` URLs. Verified live 2026-07-07
  against `api.weather.gov/alerts/active`. **No population field on the alert.**
- **Zone→population: a cheap static join exists (construct it; no ready-made CSV).** The
  defensible path is **`SAME` county-FIPS → US Census county population**, because the
  county FIPS are already on every land alert:
  - `SAME` is `P-SS-CCC` (P = portion-of-county, 0 = whole; SS = state FIPS; CCC = county
    FIPS). Strip the leading digit → 5-digit county FIPS = Census `STATE(2)||COUNTY(3)`
    (e.g. `048201`→`48201`→Travis County, TX).
  - **Census CO-EST2024 county file** —
    `https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/totals/co-est2024-alldata.csv`
    — **1.69 MB, text/csv, PUBLIC DOMAIN, last-modified 2025-03-13; verified HTTP 200 +
    header/rows this session.** Column `POPESTIMATE2024`; filter `SUMLEV=050` (county
    rows — `SUMLEV=040` are state totals, exclude). A Vintage-2025 equivalent is also live.
  - No public UGC-zone→population CSV exists (checked NWS GIS + IEM). True zone-level
    population would need the 24.6 MB zone-polygon shapefile × Census block data
    (GB-scale) — not worth it for a $0 bot. The NWS Zone-County Correlation file
    (`.../County/bp18mr25.dbx`, 338 KB) is an optional UGC→FIPS fallback for the rare
    alert lacking `SAME`.
- **Cost: near-zero marginal.** The bot already fetches active alerts once/cycle
  (`src/data/nws_alerts.py` `fetch_alerts`). The aggregate is a local sum over
  already-fetched `SAME` codes against the cached 1.7 MB CSV — no per-zone API calls, no
  new network/LLM cost. Cache refresh: Census ~yearly (March), correlation ~2×/year.

### Q2 — Honesty shape: **constructable, with county-scoped wording.**
- **Honest claim:** "the **N counties** under an active Extreme Heat Warning are **home
  to** about X million people." NOT "X million people are under the warning" — the
  SAME→county join attributes each county's WHOLE population even when only a sub-county
  forecast zone is warned, so it is an **upper bound**. County-scoped wording matches how
  the number was computed.
- **Double-counting traps (all handleable):** (a) **dedup over DISTINCT 5-digit FIPS** —
  a county appears across many alerts/zones; (b) **exclude marine zones** (no county
  `SAME` / no population); (c) **Warning-tier only** — never sum Watch + Warning +
  Advisory; (d) **exclude `SUMLEV=040`** state rows; (e) PR municipios (FIPS 72) are in
  both files — decide whether a US-heat headline includes PR.
- **Precision:** round to the nearest 5–10 M ("about 120 million"). The extent is the
  story, not a false-precise count.

### Q3 — World half: **THIN → US-first.**
- **MeteoAlarm** (EUMETNET, 38 European NMHSs) publishes machine-readable CAP/Atom feeds
  + a REST API (`api.meteoalarm.org`) with awareness levels (yellow/orange/red) and a
  "High Temperature" hazard — but **no population figures**. A European "N million" would
  need a separate MeteoAlarm-region→population join (GHSL / Eurostat NUTS), materially
  harder than the US county-FIPS path (MeteoAlarm regions aren't census units).
- No other ready continental heat-alert-extent-with-population source found.
- **Verdict:** US-only is acceptable here (the bot already ships `fire_footprint`
  US-first; reganom carries the world's regional-heat story). A later add-on could cite a
  MeteoAlarm red-heat-region COUNT (not population).

### Q4 — Threshold shape: **needs a state-kept baseline (the one real build dependency).**
- Summer routinely puts tens of millions under heat alerts, so a naive floor over-fires.
  - **Simple (v1):** a high fixed floor on Warning-tier population (sketch: ≥ ~75–100 M
    under Extreme Heat Warning), one draft per event-peak, dedup on the peak like a tier
    crossing.
  - **Better:** a percentile vs a rolling baseline the state keeps (peak warned-population
    per day) — more honest "extraordinary vs routine," but **requires state design** (a
    new `DEFAULT_STATE` key riding the sqlite persistence-contract test).
- Everything else is a cached-lookup + sum; this is the only genuine design work.

### Q5 — Overlap with `severe_weather`: **needs a dedup rule.**
- The existing class scores Extreme Heat Warning **per-alert** via `score_severe_weather()`
  (`src/editorial/scoring/disasters.py:17`). The new class is the **aggregate**. When the
  aggregate fires, the per-alert Extreme Heat Warning `severe_weather` drafts for that
  window must be **suppressed** (the mega-story IS the story; never ship both the
  aggregate and its constituents). Define this dedup seam before building.

### GO/NO-GO — **GO (US-first).**
The protocol's three GO gates:
1. ✅ zone→population from static public data ≤ a few MB cached — **1.69 MB Census CSV,
   public domain, verified.**
2. ✅ honest claim constructable — **yes, with county-scoped "N counties home to X
   million" wording.**
3. ⚠️ defensible extraordinariness floor — **partial: a fixed high floor works for v1; a
   rolling-baseline percentile (needs state design) is the honest target.**

**Recommended build shape (when scheduled):** a new heat-exposure source runner that,
from the already-fetched active alerts, sums distinct-FIPS county population (Warning-tier
only, marine excluded) against a cached Census CSV; emits one aggregate bundle when the
warned population crosses the floor; suppresses the constituent per-alert heat
`severe_weather` drafts for the window; honest county-scoped wording; rounds to the
nearest 5–10 M; keeps a state peak-baseline for the threshold. US-first; world-half
deferred (MeteoAlarm carries no population). Editorial + state surface → codex-xhigh
mandatory. Not gated on data accumulation — buildable whenever prioritized.

*(No code shipped from the spike. Evidence links verified live 2026-07-07; parallel
evidence-gathering workflow `wf_4cd6285f-40d`.)*
