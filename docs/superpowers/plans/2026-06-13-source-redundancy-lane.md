# SOURCE-REDUNDANCY LANE — Redundant Data Feeds for @theheat

> **For agentic workers:** continuation lane in the THIRTY-LOOP style. Rails, shipping mechanics, prohibitions, failure protocol inherited verbatim from `docs/superpowers/plans/2026-06-11-thirty-loop.md` §0–§5 and §8. Track state in `docs/superpowers/plans/2026-06-13-source-redundancy-PROGRESS.md`. Codex kickoff: §L below.
>
> **Provenance of this plan:** a MERGE (Andrew's decision, 2026-06-13) of two same-night drafts — `second-witness-lane.md` (independent feeds that can draft, evidence-grade-honest; Codex-reviewed, 5 P0s fixed) and `source-backup-feeds.md` (same-provider product chains + chain provenance + dashboard visibility; code-grounded). Both predecessors are superseded and deleted. The deciding rule Andrew set: **during a full host outage, an independent backup feed MAY create a draft** — tagged so it can never claim an observation it didn't make, and still gated by the manual approval queue. That is the only design that actually stops host-outage no-draft days.

**Goal:** Stop the *outage-caused* subset of no-draft days. Give each chronically-flaky NASA/gov source an ordered fallback chain whose legs are tagged with honest provenance — same-provider product alternates where they're semantically equivalent, and genuinely independent feeds (different host + institution, uncorrelated outage) where only they can cover a full host outage.

**Architecture:** One provenance foundation (R-00), then per-source chains wired into the existing public fetch function (S-13 GDACS convention — fetch fn keeps its return shape, tries legs in order, tags returned events with the leg used + an `evidence_grade`). A non-primary leg records `status="degraded"`; the bundle builder appends the grade fact to `current_facts`, which the writer/fact-check prompts already honor. Fallback-only: extra legs fire only when the prior leg fails. No editorial-bar change, no threshold change.

**Tech stack:** Python 3.12, plain `requests` via hardened `src/data/_http.py`, the existing `evidence_grade` mechanism (`src/two_bot/prompts/{writer,fact_check}_prompt.py`, `src/two_bot/intern/air_quality.py:14,24`), the existing GPM chain model (`gpm_imerg.py:158,583`) and FIRMS product param (`firms.py:65`), $0 / no-auth feeds only.

---

## §L0 — Why this lane exists, and the grading ladder every step obeys

The funnel data (7-day: 924k observed → 26k promoted → **6 drafted**; triage caps killed 135 candidates vs 65 by all quality gates) proves most no-draft days are *editorial supply*, already addressed by the shipped loop. **This lane does NOT touch editorial supply.** It attacks one narrower failure: a fast signal had a real event, but the primary feed was down. For fire/flood/precip/disaster, an outage is a *missed story*.

**"Redundant to government" reframed correctly:** nearly all climate observation traces to gov satellites/models — truly non-gov raw data barely exists. The achievable goal is **no single point of failure**: a leg whose outage is *uncorrelated* with the primary's. Two kinds qualify, and both may draft, graded honestly:
- **Same-provider product alternate** (FIRMS VIIRS_NOAA20 when SNPP is gappy; Coral CRW ERDDAP grid when station text fails). Covers *product/endpoint* gaps. Does NOT cover a full host outage (same domain).
- **Independent feed** (NOAA HMS for fire — NESDIS host + GOES instrument; Open-Meteo for precip; ReliefWeb for disasters — UN host). Covers a *full host outage*.

**The grading ladder (verified against code — `EditorialScore`/evidence-contract do NOT whitelist grade values, so grades are free-form `current_facts` entries):**

| Leg type | `source_leg` recorded | run `status` | `evidence_grade` on bundle | Writer constraint |
|---|---|---|---|---|
| Primary healthy | (none) | success | (none) | normal |
| Same-provider, semantically-equivalent product | the leg id | **degraded** | (none — faithful equivalent) | normal |
| Same-provider, different product/host | the leg id | degraded | `observed_alt_host` | may say observed; note alt source |
| Independent host, same data type (HMS, ReliefWeb) | the leg id | degraded | `observed_alt_host` | may say observed; note alt source |
| Independent model standing for an observation (Open-Meteo precip/flood) | the leg id | degraded | `model_fallback` | must NOT say "observed/measured/recorded"; frame as model estimate |

The full mechanism per witness is exactly two edits (verified): (a) teach both prompts the grade's meaning, R-00; (b) the bundle builder appends `{"label":"evidence_grade","value":<grade>}` to `current_facts` when the originating event carries that provenance.

## §L1 — Pre-made decisions (executor never chooses)

| Decision | Ruling | Why |
|---|---|---|
| May an independent backup draft? | **YES** (Andrew, 2026-06-13) — graded per the ladder, still manual-queue gated. | The only design that stops host-outage no-draft days. |
| Fallback-only vs cross-confirm | Fallback-only: a leg fires only when the prior leg fails. Cross-confirm is a future flag. | Pure outage insurance; zero behavior change when healthy. |
| Public fetch return shape | **Unchanged.** Chain/witness is internal to the existing fetch fn; returns the SAME object list. Provenance rides on event objects (a `source_leg`/`evidence_grade` field), never a tuple/struct return. | `_fetch_strict` feeds the fetcher output straight into detectors+runners (`src/orchestrator/common.py` `_fetch_strict`). |
| Which exceptions trigger the next leg | `SourceFetchError`, `requests.RequestException` (incl. Timeout/Connection) only — NOT `SourceSkipped`. | Skip = a credential is intentionally absent (`gpm_imerg.py:146`, `firms.py:79`); don't substitute a deliberately-disabled source. |
| Same-product equivalence | A same-provider product alternate is "semantically equivalent" (no grade) ONLY where the step spec says so; otherwise `observed_alt_host`. | Honesty: VIIRS NOAA-20 ≈ VIIRS SNPP; a CRW grid ≠ a CRW station text exactly. |
| New runtime dependency | STOP — Andrew's call. R-09 (sea ice) needs `netCDF4`/`pyhdf`; implement behind it, `AWAITING-ANDREW(dep:…)`, do NOT touch `requirements.txt`. | $0-stack discipline. |
| Never store payloads in state | No raw CSV/XML/JSON/HDF/NetCDF/image bytes in state — only derived scalars (≤1–2 KB). | The gist ~900 KB cliff (hit 2026-05-13). |
| Feeds OFF-LIMITS | JAXA GSMaP (SFTP), CDS/ADS `cdsapi` (async queue), GloFAS-direct (login — use Open-Meteo), Sentinel-3 SLSTR (70 MB NetCDF+OAuth), EUMETSAT (OAuth), SPEI real-time (login+lag), Scripps CO2 (URLs 404; NOAA GML healthy). | All four research passes confirmed incompatible with a $0 plain-`requests` cron. |

## §L2 — Execution queue (endpoints live-verified 2026-06-12/13; code anchors verified at main 0.9.62.0)

| Step | Target (primary, flaky rate) | Leg added | Kind | Tier | Size | Deps | Flags |
|---|---|---|---|---|---|---|---|
| R-00 | foundation | source-leg provenance + 2 evidence grades + `with_witness` helper | infra | A | M | — | [CODEX] |
| R-01 | dashboard + sentinel | chain-leg visibility (Py sentinel + JS classifier in sync) | infra | A | M | R-00 | |
| R-02 | **firms** (NASA, 5/40) | NOAA HMS independent feed (NESDIS+GOES, N. America) | independent | A | M | R-00 | |
| R-03 | **gpm_imerg** (NASA, 18/40) | Open-Meteo precip + ensemble-agreement filter | independent (model) | A | M | R-00 | [CODEX] |
| R-04 | **gdacs** (EU, 9/40) | ReliefWeb (UN OCHA) independent feed | independent | A | M | R-00 | |
| R-05 | **river_gauges** (USGS/NOAA 403s) | Open-Meteo Flood / GloFAS (model-framed) | independent (model) | A | M | R-00 | [CODEX] |
| R-06 | **firms** (product gaps) | FIRMS official product chain VIIRS_SNPP→NOAA20→NOAA21→MODIS | same-provider | A | S | R-00 | |
| R-07 | **coral_dhw** (NOAA 403s) | NOAA CRW ERDDAP `noaacrwdhwDaily` grid backs up station text | same-provider | A | M | R-00 | |
| R-08 | **gdacs** subtypes (supply) | USGS earthquakes + NHC/CPHC cyclone GIS as separate official sources | additive supply | B | L | R-00 | optional |
| R-09 | **sea_ice** (NSIDC multi-day) | OSI SAF / U. Bremen | independent | B | L | R-00 | [MINI-PLAN] dep-gated |

Order: R-00 → R-01 (infra) → R-02..R-05 (independent feeds — these STOP host-outage no-draft days; highest goal-value, R-03 gpm is the flakiest source) → R-06,R-07 (same-provider product chains — cheap, cover product gaps) → R-08 (additive supply, optional) → R-09 (dep-gated stretch). Any step may be taken once R-00 (and R-01 for anything reading the leg in the dashboard) is DONE.

---

## §L3 — Step specifications

> Format: **Why · Files · Spec · Tests · Gates · Traps.** Inherit THIRTY-LOOP §3 mechanics (branch `loop/r<NN>-<slug>`, one PR, VERSION bump, CHANGELOG, PROGRESS row in-PR) and §4 gates. Live verify-curl every new endpoint in the PR body. Verified-to-exist primaries: `gpm_imerg.fetch_daily_precip`, `firms.fetch_fires(source=…)`, `gdacs.fetch_disasters(strict=…)`, `river_gauges.fetch_river_levels`, `coral_dhw.*`, `sea_ice.*`.

### R-00 — Provenance foundation + evidence-grade vocabulary + witness helper — M [CODEX]

**Why:** every later step tags returned events with which leg served and (for non-equivalent legs) a grade. Build that once, plus the chain helper and the two prompt grades.

**Files:** create `src/data/_witness.py`; the event dataclasses the chained primaries return (grep each fetch fn's return type; add an optional `source_leg: str | None = None` and reuse the existing per-event facts path for grade — DO NOT add an `evidence_grade` field to `StoryBundle`, it has none; the grade is a `current_facts` entry the builder appends); `src/two_bot/prompts/writer_prompt.py`, `src/two_bot/prompts/fact_check_prompt.py` (grep `model_estimated`); the S-13 survey doc (`find docs -name '*mirror-survey*'`); `tests/test_witness.py`.

**Spec:** (1) `src/data/_witness.py`:
```python
def with_witness(primary, witness, *, source_key, leg_label):
    """Return primary() unchanged on success. On SourceFetchError or
    requests.RequestException (NOT SourceSkipped — let it propagate), log
    '[<source_key>] served by <leg_label>' and return witness(), which MUST
    return the same object type/shape as primary() with each event's
    source_leg set to leg_label. If witness also raises, re-raise a
    SourceFetchError chaining BOTH error strings (gdacs.py:276-277 style).
    Returns the result only — never a tuple."""
```
(2) Grade vocabulary — add to BOTH prompts, declaratively (no imperative steps; strict-JSON rule), mirroring the existing `model_estimated` wording: `observed_alt_host` ("from an independent backup host/instrument during a primary outage; treat as observed, may note the alternate source") and `model_fallback` ("from a numerical model standing in for the usual observation during an outage; do NOT write observed/measured/recorded; frame as a model estimate" — identical to `model_estimated`). (3) Provenance→telemetry: document (and provide a tiny helper for) the runner pattern that, when returned events carry a non-null `source_leg`, records `status="degraded"` with error text `served via <source_leg>` (so the sentinel + S-15 degraded handling report honestly). (4) Survey doc: append a "Verified redundancy legs (2026-06)" table with R-02..R-09 endpoints/auth/tier/verdict.

**Tests:** `test_with_witness_returns_primary_when_healthy`, `test_with_witness_falls_back_on_fetch_error`, `test_with_witness_propagates_source_skipped`, `test_with_witness_chains_both_errors`, `test_witness_event_carries_source_leg`.

**Gates:** §4 + voice-replay COLLECTION check only + existing prompt-contract tests green.

**Traps:** prompts are declarative additions; a grade matters only once a builder appends it (R-02..R-07). The `source_leg` field is additive/optional — confirm the event dataclasses serialize fine and the evidence-contract audit (`evidence_contract.py:227`) doesn't reject the extra field.

### R-01 — Dashboard + sentinel chain-leg visibility — M

**Why:** an operator (and the sentinel) must see *which leg* served, or a chronically-degraded primary silently masquerades as healthy via its backups.

**Files:** `scripts/source_health_sentinel.py` and `dashboard/lib/source-health.js` (THE sync-contract pair — same PR, both test suites: `tests/test_source_health_sentinel.py`, `dashboard/tests/source-health.test.js`); the dashboard source view (grep where source rows render) ; `docs/runbooks/source-redundancy.md` (create — fold the "unbacked sources" table here: `jtwc`, `nsidc_snow`, `sea_ice`, `copernicus_ems` get visibility/last-good, not autonomous drafts unless a verified leg exists).

**Spec:** (1) Surface `source_leg` / degraded-via-backup in the source-health payload both sides compute, so the dashboard shows e.g. `firms — degraded (served via NOAA HMS)`. (2) Keep the Python sentinel and JS classifier byte-equivalent in logic (the standing contract) — a source served only by a backup leg for N consecutive cycles is `degraded`, not `healthy`, and the sentinel may open an `unknown`/`ours` advisory if a primary is backup-served for an extended window (operator wants to know the primary is chronically down even while drafts still flow). (3) Runbook: the unbacked-source table + the operator action per source.

**Tests:** both suites: `degraded_when_served_via_backup_leg`, `healthy_when_primary_serves`, parity test that Py and JS agree on a fixture with a backup-served source.

**Gates:** §4 + both suites green + after merge: deploy + 401 check (touches dashboard).

**Traps:** this is the sentinel↔JS sync-contract pair — never change one without the other. Don't let a backup-served cycle read as fully healthy (that hides a dying primary).

### R-02 — NOAA HMS independent fire feed for firms — M

**Why:** FIRMS (NASA GESDISC family) fails 5/40 with NO host redundancy (the USFS mirror is the same domain). NOAA HMS is an independent host (`satepsanone.nesdis.noaa.gov`) AND its GOES detections are an independent *instrument* — for N. American fires it covers a full FIRMS host outage that the R-06 product chain (same host) cannot.

**Files:** `src/data/firms.py` (witness inside `fetch_fires` via R-00 helper, AFTER the R-06 product chain if both land); `src/two_bot/intern/fire.py` (grade fact ~`fire.py:42`); `tests/test_firms.py`; fixture `tests/fixtures/hms_fire_sample.txt`.

**Spec:** Endpoint (live-verified, no auth): `https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Fire_Points/Text/{YYYY}/{MM}/hms_fire{YYYYMMDD}.txt`, CSV `Lon, Lat, YearDay, Time, Satellite, Method, Ecosystem, FRP` (FRP MW, −999.0=missing). Parse with stdlib `csv`; map to the SAME hotspot object `fetch_fires` returns, `source_leg="noaa_hms"`. Same data type → `evidence_grade="observed_alt_host"`. **Coverage honesty:** N. America only — outside it the witness returns nothing and FIRMS has no fallback (state it). Assert file date within firms freshness budget (S-14).

**Tests:** `test_firms_primary_healthy_skips_hms`, `test_firms_hms_parses_fixture`, `test_firms_hms_observed_alt_host_grade`, `test_firms_hms_empty_outside_north_america`, `test_firms_frp_negative_treated_missing`.

**Gates:** §4 + fixture parse test green.

**Traps:** prefer GOES+VIIRS rows; −999.0 is missing not zero; the daily file accumulates through the day (idempotent via `is_duplicate`).

### R-03 — Open-Meteo precipitation feed for gpm_imerg — M [CODEX]

**Why:** gpm_imerg is the flakiest source (18/40; still 5/12 after the S-12 datapool→s3→opendap chain — one provider family). Only an independent feed covers a full GESDISC-family outage.

**Files:** `src/data/gpm_imerg.py` (witness inside `fetch_daily_precip`; the detector `detect_precip_records(readings, state)` ~`gpm_imerg.py:364` keeps thresholding); `src/data/open_meteo.py` (reuse idiom); `src/two_bot/intern/precipitation.py` (grade fact ~`precipitation.py:19`); `tests/test_gpm_imerg.py`.

**Spec:** Witness builds readings in the EXACT shape `fetch_daily_precip` returns, `source_leg="open_meteo"`, from `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum&past_days=1&forecast_days=0&timezone=UTC` for each city gpm scans. **Agreement gate as a RETURN-FILTER (threshold stays in the detector):** return a city's reading only if the Ensemble API `https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}&daily=precipitation_sum&past_days=1&models=icon_seamless,gfs_seamless,ecmwf_ifs025` shows ≥3 models within ~25% of the forecast value (multi-model agreement); else omit that city. `evidence_grade="model_fallback"`; `precipitation.py` appends the grade fact for `source_leg`-tagged events. Respect gpm `assert_freshness` (S-14).

**Tests:** `test_gpm_primary_healthy_skips_witness`, `test_gpm_witness_reading_shape_matches_primary`, `test_gpm_witness_omits_city_without_multimodel_agreement`, `test_gpm_witness_event_yields_model_fallback_grade`, `test_gpm_model_fallback_claiming_observed_is_killed` (fact-check fixture).

**Gates:** §4 + live verify-curl of both endpoints in PR body.

**Traps:** NWP daily precip vs satellite IMERG can disagree hugely in convection — that's why the agreement filter exists; don't loosen it. Don't invent cities gpm doesn't scan. Thresholding stays in `detect_precip_records`.

### R-04 — ReliefWeb independent disaster feed for gdacs — M

**Why:** GDACS fails 9/40 and its S-13 GeoRSS leg is the *same provider* (gdacs.org) — correlated. ReliefWeb (UN OCHA) is a fully independent host.

**Files:** create `src/data/reliefweb.py`; `src/data/gdacs.py` (witness wraps the WHOLE existing `fetch_disasters(strict=True)` — which already does API→GeoRSS internally, `gdacs.py:263,276` — adding ReliefWeb as the third leg via R-00 helper); `src/two_bot/intern/` disaster builder (grade fact); `tests/test_reliefweb.py`, `tests/test_gdacs.py`; fixture `tests/fixtures/reliefweb_disasters_sample.json`.

**Spec:** Endpoint (no auth; `appname` courtesy-required): `https://api.reliefweb.int/v2/disasters?appname=theheat&filter[field]=status&filter[value]=ongoing&fields[include][]=name&fields[include][]=type&fields[include][]=country&fields[include][]=date`. **Verify live first** with `User-Agent: (theheat-bot, contact@theheat.app)` + appname (research saw a bare-fetch 403); if still 403, STOP `BLOCKED(reliefweb-403)` with curl evidence. Map ongoing high-severity disasters to the SAME event object `fetch_disasters` returns, `source_leg="reliefweb"`. **Conservative scope:** restrict to types GDACS covers (Flood, Tropical Cyclone, Wild Fire, Drought, Earthquake) at highest severity; `evidence_grade="observed_alt_host"` + a bundle note it's a curated report during a GDACS outage; gate on report `date` within the gdacs freshness budget.

**Tests:** `test_reliefweb_parses_fixture`, `test_gdacs_falls_through_to_reliefweb_when_primary_raises`, `test_reliefweb_only_mapped_types`, `test_reliefweb_stale_report_suppressed`, `test_reliefweb_event_shape_matches_gdacs`.

**Gates:** §4 + live verify-curl (UA+appname) in PR body.

**Traps:** ReliefWeb lag (6–48 h) means it's an outage backstop, not breaking news — gate on report date. Conservative type/severity filter guards the bar; manual queue still reviews.

### R-05 — Open-Meteo Flood (modeled) feed for river_gauges — M [CODEX]

**Why:** USGS/NOAA gauges 403 against GH-Actions IPs. GloFAS via Open-Meteo is no-auth, global, independent — but modeled discharge, not observed gauge stage, so it emits a deliberately model-framed signal.

**Files:** `src/data/river_gauges.py` (witness inside `fetch_river_levels`; primary returns gauge objects with `gauge_height_ft`/`flood_stage_ft`/`above_by_ft` ~`river_gauges.py:43`); river-flood builder (grade fact); `tests/test_river_gauges.py`. **Copernicus EMS is OUT** (its activation/population/severity semantics can't be rebuilt from discharge).

**Spec:** Endpoint (live-verified): `https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lon}&daily=river_discharge&past_days=1&forecast_days=7`. Restrict to the primary's KNOWN gauge coords (GloFAS 5 km resolves only the largest nearby river, can mis-snap — never invent locations). The witness CANNOT produce ft facts → builds a model-framed event: discharge ≥ the API's 75th-percentile field AND ≥ a configured absolute floor (note the calibration assumption). Bundle omits ft facts, carries discharge+percentile, `source_leg="open_meteo_flood"`, `evidence_grade="model_fallback"`. Gate conservatively.

**Tests:** `test_riverflood_primary_healthy_skips_witness`, `test_riverflood_witness_omits_gauge_ft_facts`, `test_riverflood_witness_model_fallback_grade`, `test_riverflood_only_known_coords`, `test_riverflood_model_fallback_claiming_gauge_reading_killed`.

**Gates:** §4 + live verify-curl in PR body.

**Traps:** observed stage ≠ modeled discharge; never let a discharge number masquerade as a gauge reading; bundle must not contain ft facts. If too lossy to clear the bar in practice, acceptable — it's outage insurance, manual-queue gated.

### R-06 — FIRMS official product chain — S

**Why:** cheap product-gap insurance using the existing `source` param; a given VIIRS product can be momentarily empty/lagged while a sibling product has the data. Same host (does NOT cover a full FIRMS outage — that's R-02's job), but a real win for per-product gaps.

**Files:** `src/data/firms.py` (`fetch_fires` already takes `source: str = "VIIRS_SNPP_NRT"` at `firms.py:65`); `tests/test_firms.py`.

**Spec:** On a product returning empty/failing, try the next in chain `VIIRS_SNPP_NRT → VIIRS_NOAA20_NRT → VIIRS_NOAA21_NRT → MODIS_NRT` (all the same `area/csv` host + the bot's MAP_KEY). These are **semantically-equivalent observations** (per §L1) → record `source_leg` + `status="degraded"`, **no `evidence_grade`** (a faithful VIIRS/MODIS hotspot is a hotspot). Order chosen so the freshest sensors lead.

**Tests:** `test_firms_product_chain_advances_on_empty`, `test_firms_product_chain_records_leg_no_grade`, `test_firms_primary_product_unchanged_when_healthy`.

**Gates:** §4.

**Traps:** confidence mapping differs (VIIRS categorical l/n/h vs MODIS 0–100 — `firms.py:33`); each product's rows must go through the existing confidence normalizer. Same host means this is NOT a host-outage fix — keep R-02 as the independent leg after the chain.

### R-07 — NOAA CRW ERDDAP grid backup for coral_dhw — M

**Why:** coral_dhw 403s against the CRW station-text host; CRW also publishes the same DHW product as a gridded ERDDAP dataset (different product/path), a same-provider backup.

**Files:** `src/data/coral_dhw.py` (primary uses `coralreefwatch.noaa.gov/product/vs/data*` station text, `coral_dhw.py:19-20`); add a tested station→grid-coordinate mapping; `tests/test_coral_dhw.py`; fixture for the ERDDAP CSV.

**Spec:** Witness queries the CRW ERDDAP DHW grid (verify the live dataset id + var first: `noaacrwdhwDaily`, variable `degree_heating_week`, e.g. `https://coastwatch.pfeg.noaa.gov/erddap/griddap/noaacrwdhwDaily.csv?degree_heating_week[(last)][(lat)][(lon)]` — confirm the exact ERDDAP host/dataset live; if the dataset id differs, STOP with evidence). For each active CRW virtual station, sample the grid at its mapped lat/lon, build the SAME DHW reading object, `source_leg="crw_erddap"`. Different product/host path → `evidence_grade="observed_alt_host"`. Respect coral freshness.

**Tests:** `test_coral_primary_healthy_skips_erddap`, `test_coral_erddap_station_coord_mapping`, `test_coral_erddap_observed_alt_host_grade`, `test_coral_erddap_parses_fixture`.

**Gates:** §4 + live verify-curl of the ERDDAP dataset in PR body.

**Traps:** the station→grid coordinate mapping is the correctness core — test it; a mis-mapped reef reports the wrong reef's DHW. Grid value at a coastal cell can differ slightly from the station text — note it's the gridded product.

### R-08 — GDACS subtype substitutes (USGS quakes + NHC cyclone GIS) — L · optional

**Why:** additive supply that also hardens GDACS's blind spots — official, independent feeds for two disaster subtypes GDACS covers, as SEPARATE source keys (not hidden GDACS success).

**Files (mini-plan-ish):** create `src/data/usgs_quakes.py` (USGS earthquake GeoJSON — `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson`, no auth) and a new quake source runner; for cyclones, NHC/CPHC GIS products for covered basins (verify current endpoint); scoring + bundle + threshold + triage `legacy_type` per the THIRTY-LOOP "new signal type" checklist; tests.

**Spec:** These are NEW official sources (not witnesses) — full normal-source treatment (own source_key, scorer, threshold, bundle, manual_only policy, voice fixture). Mark **optional/low-priority** — it's supply expansion that also adds independence, but it's the heaviest step and least tied to "stop outage no-draft days." Defer unless R-02..R-07 are done and Andrew wants the extra coverage.

**Tests:** standard new-source contract tests mirroring an existing source's test file.

**Gates:** §4 + voice-replay collection green.

**Traps:** must be separate source keys with their own health rows — never fold into gdacs's success (that would hide a GDACS outage). Scope creep risk: this is the one step that touches editorial supply; keep it optional.

### R-09 — Sea-ice second source (OSI SAF / U. Bremen) — L [MINI-PLAN] · dep-gated

**Why:** NSIDC sea-ice has gone dark for *days* — the longest single-source outage class. Slow signal (S-15 last-good softens short gaps) → lowest priority, but the only true institutional gap with no Open-Meteo coverage.

**Files (mini-plan):** create `src/data/sea_ice_witness.py`; `src/data/sea_ice.py`; tests; **`requirements.txt` ONLY after Andrew clears the dep STOP.**

**Spec (constraints):** Prefer **OSI SAF via Ifremer anonymous HTTPS** (NetCDF-3): verify the live daily-NRT sea-ice-concentration path under `osi-saf.ifremer.fr`; download via `fetch_with_retry`; compute hemispheric extent (Σ cells ≥15% conc × cell area) with `netCDF4`; return the SAME shape `sea_ice` produces, `source_leg="osi_saf"`, `evidence_grade="observed_alt_host"`. Fallback: U. Bremen AMSR2 (HDF4, `pyhdf`). **`last_good` is NOT the witness** — it's S-15's degraded-telemetry path (`write(bot_state, source_key, data_date, payload)` ≤2 KB; `read(…, max_age_days)`); the evidence contract REJECTS cached facts in bundles (`evidence_contract.py:261`), so a last-good reading never becomes a candidate; the witness produces FRESH data that can. **Dependency STOP:** implement+test behind the dep, `AWAITING-ANDREW(dep:netCDF4)`, do NOT edit `requirements.txt` or merge the dep.

**Tests:** witness parse from a committed small fixture; extent correctness vs a known date; primary-healthy-skips-witness; `observed_alt_host` grade; cached last-good never enqueued.

**Gates:** §4 (dep-gated tests `xfail(dep-pending)` until the dep is approved+added).

**Traps:** never cache the grid in state — only the derived scalar extent (≤1 KB). The 15% threshold + cell-area weighting are the correctness core.

---

## §L4 — Done-ness & honesty checklist (per PR)

- Primary path byte-unchanged when healthy (a test proves the extra leg is never called on the happy path).
- Public fetch return shape unchanged; provenance rides on event `source_leg`; a non-primary leg records `degraded`; the bundle builder appends the correct `evidence_grade` per the §L0 ladder.
- Next leg fires only on `SourceFetchError`/`RequestException` (NOT `SourceSkipped`); all-fail chains every error.
- Same-provider equivalent leg → no grade; alt-host/alt-product → `observed_alt_host`; model-for-observation → `model_fallback`; a fact-check fixture proves a `model_fallback` draft claiming "observed" is KILLED.
- Coverage limits stated in the PR body (HMS=N.America; GloFAS=largest-river+modeled; ReliefWeb=lag backstop; FIRMS product chain=same host, not a host-outage fix).
- No `requirements.txt` entry without Andrew's recorded approval. Live verify-curl in the PR body for every new endpoint.

## §L5 — Superseded / cut (do NOT resurrect without re-scoping)

- **`second-witness-lane.md` + `source-backup-feeds.md`** — both merged into THIS doc and deleted; do not reference them.
- **ocean_sst witness** — cut: `fetch_global_sst` returns a global mean + multi-year archive/streak baseline a point feed can't reproduce, and its primary (climatereanalyzer, U. Maine) is already non-NOAA. Resurrect only as a real aggregation feature.
- **Global fire-drought-heat / unblocking loop S-27** — cut from this lane: it's supply expansion, not redundancy, and `detect_fire_drought_heat` is US-state-scoped (`synthesis.py:94,108,116`) — it needs a new global-region detector + global drought source (Copernicus GDO, needing `rasterio` or a WMS point-query), tracked separately.
- **GPM AWS S3 as a public mirror** — S3 is Earthdata-credentialed, not anonymous; the independent precip cover is R-03 (Open-Meteo), and the S3 leg already exists in the S-12 chain.

## §L — Codex kickoff (per-lane; paste verbatim)

> Execute the SOURCE-REDUNDANCY LANE at `/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-06-13-source-redundancy-lane.md`. Read it in full (especially §L0's grading ladder and §L1's pre-made decisions), then re-read THIRTY-LOOP `2026-06-11-thirty-loop.md` §0–§5/§8 (rails inherited verbatim) and the `-CODEX-KICKOFF.md` translation table (you are Codex — written self-review for [CODEX] gates; no recursive codex calls). Track state ONLY in `2026-06-13-source-redundancy-PROGRESS.md`. Standing authorizations: merge your own PRs once the `test` check passes (`gh pr checks <N> --watch` → `gh pr merge <N> --squash --delete-branch` → `git checkout main && git pull`); run `vercel --prod` from `dashboard/` after the dashboard-touching R-01 merges. Absolute prohibitions: no push to main; never set repo variables/secrets; never disable workflows; never edit the gist by hand; never weaken editorial gates; **never add a `requirements.txt` dependency** — R-09 STOPs and waits for Andrew; keep the sentinel↔dashboard-JS classifier in sync (R-01). Architecture rule you must not violate: the extra leg lives INSIDE the existing public fetch fn, returns the SAME object shape with `source_leg` set, fires only on `SourceFetchError`/`RequestException` (never `SourceSkipped`), and provenance reaches the writer ONLY by the bundle builder appending the correct `evidence_grade` fact per the §L0 ladder. Work R-00 then R-01 (infra), then R-02..R-05 (independent feeds — these are the whole point: they stop host-outage no-draft days), then R-06/R-07 (same-provider chains), then R-08 (optional) / R-09 (dep-gated). Obey every STOP. End each run: append the PROGRESS session-log row + print the 5-line summary.
