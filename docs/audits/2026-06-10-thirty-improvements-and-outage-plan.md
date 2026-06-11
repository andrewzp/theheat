# @theheat — 30 Improvements + Source-Outage Resilience Plan

**2026-06-10 · Full-codebase audit (6 parallel exploration passes + production telemetry) · main at 0.9.22.0**

Every improvement is ranked largest → smallest and tied to the experience of the **consumer of the content** — the follower reading @theheat on X/Bluesky, with the operator console treated as the instrument that protects that reader. Production evidence: gist `state.json` telemetry (7-day rolling window), sentinel issue history, and file:line verification of every load-bearing claim.

---

## Part 1 — The 30 improvements (largest → smallest)

### Tier 1: Architectural (XL/L)

**1. Unified resilient fetch layer (XL).** Today 12+ fetchers (`gdacs.py:96`, `enso.py:35`, `co2.py:34`, `nsidc_snow.py:59`, `sea_ice.py:54`, `nws_alerts.py:57`, `water_levels.py:75`, `ocean.py:83`, `fire_footprint.py:108`, `drought.py:35`, `open_meteo.py:233+`) call bare `requests.get` with **one attempt and zero retries**; the shared `fetch_with_retry` (`src/data/_http.py:30`) has no jitter, opens a new TCP connection per request (no `Session`), and treats every 403 as instantly fatal. Migrate every fetcher onto one hardened transport: retry-with-jitter, connection pooling, 403/429-aware second attempt for known-WAF gov hosts, unified User-Agent. *Reader impact: this is most of the outage plan's Phase 1 — last week GDACS went dark 9/40 cycles on bare single-attempt fetches a polite retry would likely have recovered. (FIRMS, which already retries via `firms.py:84` and still failed 5/40, shows what sustained outages look like — that class is what Phase 2's mirrors are for.) GDACS is a breaking-news-class source; every recovered cycle is a disaster story reaching the feed in the same 4-hour window it happened.*

**2. Editorial supply engine: multi-draft best-of + critic rewrite loop (XL).** The writer makes exactly one attempt per candidate (`pipeline.py:84-227`); the critic is PASS/KILL only, explicitly noted as v1 (`critic.py:16-19`). Generate N=3 drafts per surviving candidate (system prompt is already cached — marginal cost is output tokens only), let the critic pick the strongest; give the critic a structured REVISE verdict for repairable flaws (dead system clause, wink-kicker) with one writer retry. *Reader impact: editorial supply is THE posting bottleneck — `drafts_pending=0` most days. This multiplies A-grade output from the same scarce signals without lowering the bar; it is the most direct path to the feed actually having content, which is the entire consumer experience.*

**3. Stale-tolerance + freshness honesty (L).** No source serves last-good data when a fetch fails — a failed cycle is a silent zero. Meanwhile only 8 of 23 sources call `assert_freshness` (`src/data/_freshness.py:25`); the other 15 (incl. firms, sea_ice, drought, gdacs, ice_mass, nws_alerts, river_gauges) record `success` even if the upstream silently returns week-old data. Add a last-good cache in state for slow-moving sources (CO2, ENSO, sea ice, ice mass, snow — data that changes daily/monthly), served with explicit data-dates and used for detection continuity only (streaks, baselines), never "happening now" claims; add freshness assertions everywhere else. *Reader impact: streak and record detection stop breaking during 1–3-cycle blips (no falsely reset baselines → no missed or wrong records), and a stale upstream can never quietly produce a tweet implying today's data is from last Thursday.*

**4. Multi-endpoint redundancy chains (L).** Only gpm_imerg has a fallback architecture (`_gpm_grid_source_chain`, `gpm_imerg.py:590`) — and its production chain is `("datapool",)` with **no secondary** before the legacy per-city OPeNDAP fall-through, even though the s3 path is fully built. Verified: gpm still failed 5 of its last 12 runs on datapool. One caveat the code surfaces (Codex finding): the s3 path mints credentials from the **same host datapool uses** (`_s3credentials.py:25`), so `datapool→s3` mitigates partial outages, not a full host black-hole — pre-mint/cache the creds early in the cycle and keep OPeNDAP as the genuinely independent last resort. Add the GDACS GeoRSS feed as a fallback for the failing `gdacsapi` tier; survey official mirrors for the 403 cluster (coralreefwatch, USGS water services vs `api.water.noaa.gov` — river_gauges already knows both hosts). *Reader impact: a single NASA/NOAA endpoint outage stops being a 4-hour content blackout for that signal — precipitation records, disaster alerts, and coral tiers keep flowing through the mirror.*

**5. Engagement feedback loop (XL).** Zero engagement data is ever read back — no `get_tweet`/public_metrics calls exist anywhere. Weekly job: fetch likes/RT/bookmark counts for the last ~30 shipped tweets into `memory.shipped_tweet_metrics`, surface per-category averages on the dashboard, eventually weight editorial exemplars. *Reader impact: the bot currently learns nothing from what readers actually engage with; closing this loop tunes topic mix and framing to demonstrated reader interest instead of editorial intuition alone.*

**6. Synthesis expansion: global fire-drought-heat + SST×coral compound (L).** Exactly one synthesis rule exists (`RULE_FIRE_DROUGHT_HEAT`, US-only via USDM drought data; `src/editorial/synthesis.py:20`). Add an international drought component (Copernicus) to globalize it, and a marine compound: reef DHW ≥ Alert 2 + basin SST anomaly ≥ +2°C = "why this reef is cooking" story. *Reader impact: synthesis events are the highest-bar content class (threshold 82) — the "Wait, what?" compound stories that single sources can't tell. The Amazon, southern Europe, and the Sahel produce fire-drought-heat compounds every year that the bot is currently structurally blind to.*

**7. Concurrent source execution + cycle deduplication (L).** The 27 source runners execute strictly sequentially (`run_alerts.py:84-130`) with no per-source wall-clock budget; one slow NASA endpoint delays everything behind it, and the 12:00 UTC `both` mode fetches all Open-Meteo city temps twice (alerts + leaderboard). Parallelize independent fetchers (data-layer already proves the pattern internally with ThreadPoolExecutors), enforce a per-source budget — and model it as a small DAG, not a flat pool: `run_synthesis` consumes fire/drought/heat components written by the FIRMS, drought, and Open-Meteo runners, so component producers must complete before synthesis runs. *Reader impact: detection→publish latency shrinks; events land in the feed while the news is live, and a hung host can no longer push a whole cycle into the 20-minute job timeout.*

**8. Decompose `common.py` (L, backlog bet #3).** 1687 lines, star-imported into 30 files, 171-entry `__all__`, plus the `_sync_compat_globals()` runtime monkeypatching mechanism (`src/main.py:36-45`). Twelve coherent clusters already identified (cyclone helpers alone are ~235 lines). *Reader impact: indirect but compounding — every new signal type and every outage fix lands faster and with less regression risk in a codebase where the core module isn't a god-object.*

**9. Hot 10 image card + alt text (L).** Tweets are text-only — `create_tweet(text=text)` (`src/posting/twitter.py:38`), no media path exists. The hot10 bundle already carries everything a bar chart needs (per-city temp, normal, anomaly). Server-side SVG→PNG, uploaded with proper alt-text generated from the same bundle. *Reader impact: a visual anomaly ranking is instantly graspable mid-scroll where a text list gets skimmed past; alt text keeps the data accessible to screen-reader users — currently they get nothing visual ever.*

**10. Record-store caps + state pruning (L, backlog bet #2 expanded).** `snow_daily_swe_gain_records` (~252 KB) and `precip_daily_records` grow unboundedly (station×calendar-day keys never evicted); `memory.shipped_tweets` has **no cap at all** (`state.py:446-461`); tier-dedup dicts for dead fires/storms/floods accumulate forever; old-year annual-count keys never pruned. State already hit GitHub's ~900 KB inline-content truncation cliff once (2026-05-13, three failed runs) and sits at 980 KB now. *Reader impact: crossing the gist cliff again means failed cycles and a dark feed; staying lean keeps every read-merge-write fast and safe — and the dedup memory that prevents readers seeing repeat tweets lives in this same file.*

**11. Dashboard `page.js` refactor (L, backlog bet #6).** 2,499 lines, ~640 lines of inline CSS, pure client-side render with a blocking "loading..." first paint. *Reader impact: indirect — this is the operator's instrument for approving drafts and catching pipeline problems; a maintainable console means faster approvals and faster incident response, which the reader experiences as a timely, error-free feed.*

### Tier 2: Reliability & trust (M)

**12. Double-post hardening (M).** If both state writes fail after a successful post (`cli.py:51-58`), the posted draft stays `pending` in the durable store and **will be re-posted** on the next hourly pass. Persist the returned `tweet_id` durably before/alongside the main state write; add an optimistic-lock version field to gist writes (two queued workflow runs can currently last-write-wins each other on `take_incoming` keys). *Reader impact: a follower seeing the same tweet twice is the fastest way to lose the "precision instrument" trust the voice is built on.*

**13. Whole-cycle liveness alarm (M).** No workflow has an `if: failure()` step (verified across all 4); a cycle that crashes before writing state is invisible to the sentinel (it reads per-source health from the last successful state write). Add a failure-notification step to bot.yml and teach the sentinel to check the newest `run_history` timestamp — alarm if >5h old. *Reader impact: today the bot can silently go dark for days (it has before — the grading routine froze 12 days unnoticed); this guarantees a dark feed is a paged incident within hours, not a discovery.*

**14. Sentinel stale-success detection (M).** The sentinel classifies only fetch failures; a source "succeeding" with empty or stale data stays green forever. Pair with #3's freshness assertions and add an editorial-yield dimension (a source with zero observed events for N× its normal cadence gets flagged). *Reader impact: closes the last invisible outage class — sources that look healthy while contributing nothing, starving the feed without any alarm.*

**15. Air-quality ground-station corroboration (M).** PM2.5/dust candidates are model-estimated (CAMS), so the writer must hedge ("CAMS model data") and candidates rarely clear the bar. Corroborate against co-located OpenAQ/AirNow ground stations; upgrade `evidence_grade` to `model_corroborated_by_station` when they agree. *Reader impact: unlocks an entire signal category (the most human-relevant one — air people are breathing right now) at full editorial confidence instead of permanent hedge-mode.*

**16. Coral reef-system angle library (M).** Coral DHW is the highest-volume candidate source, but every bundle carries the same fixed structure, so 7-of-8 drafts die to template convergence at the critic. Add per-reef-system context facts (current systems, bleaching history, ecosystem stakes) to the bundle. *Reader impact: instead of one survivor from each coral batch, readers get distinct, mechanism-rich reef stories — more supply from data already fetched.*

**17. Record margin-percentile framing (M).** Bundles carry the old record and archive depth but not how the margin ranks historically; `station_thresholds.sqlite` already stores the distribution. Inject "largest margin in this station's 31-year archive" style facts. *Reader impact: "broken by 0.2°C" and "shattered by the largest margin ever recorded there" are different stories — this gives the writer the astonishment dimension the editorial bar actually runs on.*

**18. Engagement-window scheduling (M).** `auto_approve_at` is a pure review-hold timer (`common.py:1097`); nothing prevents a 3 AM ET publish. Window due-times into high-attention hours by audience timezone. *Reader impact: the same tweet at 8 AM ET reaches multiples of its 3 AM audience; timing is free distribution.*

**19. air_quality fan-out redesign (M).** 638 cities in 13 chunks reliably trips per-minute 429s (current health: 2 ok / 5 degraded); #212's recovery passes help but the shape is fragile. Investigate larger batch requests, spreading chunks across the cycle, or the commercial tier. *Reader impact: degraded AQ cycles mean exactly the cities mid-crisis (the newsworthy ones) can be the ones missing — full sweeps make the next Delhi/Lahore episode detectable every cycle.*

**20. ETag/conditional requests for government CSVs (M).** Zero conditional-request support exists; NOAA/CPC/NSIDC CSV endpoints serve `Last-Modified`/`ETag`. *Reader impact: 304s cut cycle time and per-IP request pressure on exactly the hosts whose WAFs keep 403-ing the bot — fewer outages by being a politer client.*

**21. SQLite backend decision (M, backlog bet #4).** ~600 dead lines maintained in sync with every state evolution, or a one-env-var CI smoke to make it a real fallback. Decide: wire or delete. *Reader impact: indirect — either an escape hatch from gist-size failures (the cliff in #10) or 600 fewer lines that can silently rot under the state file the whole feed depends on.*

**22. Source links on life-safety tweets (M).** Cyclone bundles carry `public_advisory_url` but tweets never include links. Append the NHC/JTWC advisory URL when characters allow; consider canonical source URLs for record claims. *Reader impact: "can I verify this?" is exactly the mental state the voice creates — a source link on a Cat-4 landfall converts assertion into authority and gives readers an action that matters.*

**23. Orchestrator test gaps + voice fixture expansion (M).** `co_ops`, `nifc`, `marine` runners have no orchestrator-level tests; voice-regression fixtures miss the newest bundle types (precipitation, air-quality, dust, synthesis, marine heatwave). *Reader impact: the untested paths are precisely where a silent skip-condition bug or a prompt regression ships a bad draft to the queue — these tests are the reader's last automated line of defense.*

### Tier 3: Sharp small wins (S)

**24. Reganom activation (S — Andrew's go).** `THEHEAT_REGANOM_ENABLED` is the one-variable flip on a fully built, 5-layer-defended detector. *Reader impact: a new class of story (whole-region multi-day anomalies) that single-city records structurally miss — the largest supply unlock available per unit of work.*

**25. Inter-tweet spacing guard (S).** `process_due_drafts` posts every due draft back-to-back in one pass (`posting.py:160-205`). Add a minimum-gap check (e.g., 15 min). *Reader impact: three simultaneous tweets read as a malfunctioning firehose; spacing preserves the "one extraordinary thing at a time" curation promise.*

**26. Hot 10 audience-unit fix (S).** `build_hot10_bundle` is the only temperature bundle that doesn't inject `_audience_unit_facts` (verified — used at `temperature.py:74/168/226/307` but absent from the hot10 builder at :508+). *Reader impact: a US-led leaderboard can ship Celsius-first to a °F audience — a small thing that reads as foreign and costs trust in a data brand.*

**27. Dashboard truth fixes (S).** Three verified bugs: `todayCount` reads an arbitrary date key (`page.js:1470`), `stateError` is captured but never rendered (a failed gist read looks like an empty pipeline), and the Hot 10 card shows day-old data with no staleness cue; plus "updated Xm ago" conflates fetch-time with data-time. *Reader impact: the operator approves and triages based on these numbers — wrong daily counts and invisible state failures translate directly into wrong publishing decisions readers see.*

**28. Trim the dashboard payload + visibility-gated polling (S/M).** `/api/dashboard` ships the entire ~1 MB state blob every 30 s (`route.js:134`), including a dozen heavy keys the client never reads; polling continues on hidden tabs. *Reader impact: indirect — a console that's fast on a phone gets checked more often, and the wasted GitHub API budget currently being burned is the same budget state writes depend on.*

**29. Sentinel 403-classification fix (S).** `_UPSTREAM_RE` matches bare `403` as external, but a 403 from Earthdata is an expired credential — ours. Tighten the heuristic (host-aware or token-keyword-aware) in **both** the Python sentinel and the JS classifier (sync contract). *Reader impact: a mislabeled credential expiry sits in the "external, leave it" bucket while a real, fixable outage starves the feed.*

**30. Dev-hygiene bundle (S).** The dead `drafted` plumbing across all 22 runners (every source reports `drafted=0` to telemetry — the dashboard's per-source contribution metric is wrong); no `[tool.pytest.ini_options]` (the `voice_replay` marker is unregistered outside its conftest); no README quickstart; `PIPELINE.md` Stage Glossary still documents the pre-May-4 generator pipeline; `THEHEAT_CRITIC_ENABLED` has no bot.yml passthrough (critic can't be killed without a deploy); `refresh-thresholds.yml` on older action versions. *Reader impact: each is small friction or a small lie in the instruments — together they slow every future fix the reader is waiting on.*

---

## Part 1½ — How the 30 items map to the outage plan

The 30-item list is the **ranked menu** (everything worth doing, by size); Part 2 below is the **sequenced program** (the outage-shaped slice of that menu, ordered with measurement gates). The join:

| Outage-plan phase | Where it lives in the 30 items |
|---|---|
| Phase 0 — See it | #13 (whole-cycle liveness + `if: failure()`), #14 (stale-success detection). The `error_class` field + 14-day telemetry series exists only in the plan — measurement substrate for the gates, not a standalone improvement. |
| Phase 1 — Absorb | #1 (unified resilient fetch layer), with #20 (ETag/conditional requests) as the politeness adjunct. |
| Phase 2 — Reroute | #4 (multi-endpoint redundancy chains), leaning on bet #5's runner abstraction so chains become config. |
| Phase 3 — Remember | #3 (last-good cache + freshness honesty, with provenance + compactness rules). |
| Phase 4 — Protect | #7 (concurrent DAG execution + budgets); circuit-breaker mechanics live only in the plan. |

Phase gates (the `rg requests.get` structural gate, the gdacs −60% effect gate, chaos tests, creds pre-minting) exist only on the plan side — they are acceptance criteria, not improvements. Items 2, 5–6, 8–12, 15–19, 21–30 are deliberately not in the plan: editorial supply, publishing, state, dashboard, and hygiene work unrelated to outages.

---

## Part 2 — The source-outage resilience plan

### What "constant outages" actually is (7-day production evidence)

| Source | Failed cycles | Error class | Host |
|---|---|---|---|
| gpm_imerg | 18/40 (still 5/12 **after** the datapool switch) | ConnectTimeout | NASA GES DISC |
| gdacs | 9/40 | Max retries / connection | www.gdacs.org |
| firms | 5/40 | Connection | NASA FIRMS |
| jtwc | 3/40 | **403** | metoc.navy.mil |
| river_gauges | 3/40 | **403** | USGS waterservices |
| copernicus_ems | 3/40 | **403** | rapidmapping.emergency.copernicus.eu |
| coral_dhw | 2/40 | **403** | coralreefwatch.noaa.gov |
| air_quality | 5/7 runs degraded | 429 per-city | open-meteo AQ |

Seven sentinel incidents in six days, all `external`/`unknown`, all auto-closed on recovery. Even "clean" days have alert cycles with 1–3 source failures.

**Failure taxonomy:** ① science-host capacity (timeouts/5xx from NASA-class infrastructure), ② intermittent WAF 403s from gov/military hosts against shared GitHub-runner egress IPs, ③ per-city rate limiting, plus two *invisible* classes: ④ stale-data-as-success (15 sources have no freshness check) and ⑤ whole-cycle crash (sentinel-blind, no failure notification).

**Why external blips become content gaps (the part we control):**
- 12+ fetchers: one attempt, no retry. A single TCP reset = that source dark for 4 hours.
- `fetch_with_retry`: no jitter (synchronized retry spikes), no connection reuse, and **never retries 4xx** — a transient WAF 403 is instantly fatal.
- One fallback endpoint exists in the entire system (gpm), and its production chain has no secondary even though s3 is built.
- Zero last-good reuse; zero freshness honesty for most sources.

### The reframe

We cannot make NASA, NOAA, or the Navy reliable. The goal is **outage-indifference**: no single-host failure should cost followers a story or cost the operator an honest picture. Five layers: **see → absorb → reroute → remember → protect.**

### Phase 0 — See it (S; immediate)
Add an `error_class` field (timeout/5xx/403/429/dns) to `SourceHealthRun` (`state_schema.py:131` — `record_source_health` currently whitelists numeric metrics only) plus a compact **14-day class-counter series** alongside the 7-day window, so later phase gates are actually measurable. Whole-cycle liveness in the sentinel: check the newest **`alerts`/`both`** run against the alert schedule — *not* the newest `run_history` entry, because hourly `auto_publish_due` runs keep that timestamp perpetually fresh and would mask a dead alerts lane. Add an `if: failure()` issue-opening step to bot.yml. *Gate (honest arithmetic): a crashed alerts lane becomes a GitHub issue within one missed alert slot + one sentinel pass (≤ ~9h at current cadences; move the sentinel to hourly if that's too slow). This phase is also the measurement substrate for everything below.*

### Phase 1 — Absorb (M; the 80/20)
One hardened transport for all 27 sources: migrate every bare `requests.get` in `src/data/` onto `fetch_with_retry` (the full inventory is bigger than the headline list — it includes the Open-Meteo paths at `open_meteo.py:233/502`, the GPM per-city fetches at `gpm_imerg.py:510/763`, and CO-OPS at `water_levels.py:75`); add full jitter; shared `requests.Session` with pooling (fewer handshakes on exactly the hosts that time out); a 403/429-aware single extra attempt after a long jittered delay (15–45 s) **scoped to the known-WAF host list** so real auth failures still fail fast and stay classified `ours`. *Structural gate: `rg "requests\.get\(" src/data/` returns only an explicit, commented exception list. Effect gate: gdacs failed-cycle rate down ≥60% over two weeks of Phase-0 telemetry (gdacs isolates the migration effect — FIRMS already retries, so it's excluded from this gate).*

### Phase 2 — Reroute (M)
Fallback chains where mirrors exist, encoded as per-source config in the runner skeleton — this is where backlog bet #5 (source-runner abstraction) earns its keep: fallbacks become a table, not 25 hand-rolled variants. Specifics: gpm `datapool→s3→opendap` with **credentials pre-minted/cached early in the cycle**, because s3 credential minting hits the same host as datapool (`_s3credentials.py:25`) — s3 covers partial outages; OPeNDAP (different host) remains the independent last resort. GDACS GeoRSS fallback for the failing API tier; mirror survey for the 403 cluster (coralreefwatch mirrors, USGS↔NWPS for river gauges). *Gate: chaos test per chained source — black-hole the primary; the cycle still produces that source's data through a path verified independent of the primary host.*

### Phase 3 — Remember (M)
Last-good cache in state for slow-movers (CO2, ENSO, sea ice, ice mass, snow, climate indices) with two hard design rules from the Codex review: **(a) provenance** — cached rows carry `from_cache: true` + their real `data_date`, runners update continuity state from them but **never enqueue drafts** from cached rows (today's runners detect events from whatever readings arrive, and dedup records only post-draft — without the flag, a cache would originate stale drafts); **(b) compactness** — cache derived baselines/latest readings, never raw payloads (sea_ice parses a full historical CSV; the gist already hit its ~900 KB truncation cliff once). For record streaks specifically, the streak store lives on the GHCN/Open-Meteo path (`record_streaks`, pruned at the end of that runner) — the targeted fix is **skip streak pruning on failed GHCN cycles**, not caching that path. `assert_freshness` for the 15 unguarded sources so stale-success becomes an explicit degraded state the sentinel can see. *Gate: a simulated 3-cycle NOAA outage produces zero false streak resets and zero drafts originating from cached rows.*

### Phase 4 — Protect the cycle (L; trigger on evidence)
Circuit breaker (N consecutive timeout-class failures → skip for a cool-down) and per-source wall-clock budgets, then concurrent execution as a **DAG** (synthesis runs after its component producers — FIRMS/drought/Open-Meteo). Status mechanics matter: `_rebuild_source_health` normalizes unknown statuses to `failed` (`state.py:1220`), so a breaker skip must be recorded as `skipped` + breaker metadata (or a first-class status added across state, sentinel, **and the dashboard JS classifier** per the sync contract) — otherwise the breaker poisons the very telemetry it protects. *Trigger: only if Phase 0 telemetry shows cycle-duration pressure; don't build it speculatively.*

### Explicitly deferred (Andrew's calls)
- **Egress identity** (self-hosted runner / stable-IP proxy): the only true fix for IP-reputation 403s, but costs money and ops surface. Decide only if Phase 1's polite-retry doesn't clear the 403 cluster — measured, not assumed.
- **Paid data tiers** (open-meteo commercial for AQ): decide after observing post-#212 recovery behavior.
- **State backend** (bet #4) is reliability-adjacent but a separate decision; not outage-coupled.

### Sequencing & provenance
Phase 0+1 ≈ one PR-train session; Phase 2 a second; Phase 3 a third. Each phase independently shippable behind the existing 1,631-test suite, each with a measurable gate, each observable through the sentinel that already exists. **This plan has already had one cross-model adversarial pass:** Codex (read-only, repo access) returned 11 findings — 3 P0s (liveness masking by hourly publish runs, datapool/s3 shared credential host, `skipped_breaker` normalizing to `failed`) and 8 P1s — all verified against code and incorporated above. Repeat the Codex design review before each implementation phase per standing rule.

*Consumer framing: GDACS and FIRMS alone went dark 14 cycles last week — those are the breaking-news sources. Every recovered cycle is a story reaching readers within the same 4-hour window the event happened, instead of never.*
