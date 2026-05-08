# Session Brief

Handoff doc for picking up @theheat work. Read after `BRIEFING.md`. Newest section at top.

---

# 2026-05-08 — 13-hour debugging marathon: 4-day outage diagnosed, root-caused, fixed

## Where we landed

`main` is on `d9c84ff` (PR #47). **~813 tests passing** (was 709 at session start). Pipeline working end-to-end for the first time since 2026-05-03. **2 pending drafts in queue** (Sissonville WV + Dayton WY monthly_lows — graded B and C+ respectively). Posting still paused per the resumption-bar invariant.

**The session began with**: "we still aren't seeing drafts!"

**The session ended with**: 10 PRs landed (#38–#47), 11 CHANGELOG releases (0.3.0.0 → 0.3.10.0), structural visibility for every kill stage, and the bot generating real factually-grounded prose again.

## The bug ladder (each layer revealed by the previous fix's diagnostic surface)

| PR | What it fixed | Bug exposed by the fix |
|---|---|---|
| **#38** | Suppression ledger v1 + dashboard health-calc fix (`success` + `skipped` count as healthy) | (visibility infrastructure — no bug exposed yet) |
| **#39** | `signal_date` choking `json.dumps()` in writer/fact-check via `_json_default` ISO coercion + downstream suppression capture (`stage` field discriminator) | First post-fix run: ledger surfaces `Pipeline error: Writer returned invalid JSON` for monthly_low bundles |
| **#40** | Sonnet wraps JSON in `\`\`\`json` fences despite the prompt explicitly forbidding them — defensive parser strips them | Next run: ledger surfaces `Invalid JSON response: Let me think about this carefully.` (chain-of-thought preamble before the JSON object) |
| **#41** | `_extract_json_payload` finds first `{` and last `}` — robust to preamble + postamble + nested objects. Anthropic timeout 90s → 180s | Next run: 22-second `ReadTimeout` on monthly_low — way under 180s, so timeout-cap isn't the issue |
| **#42** | Codex bug-hunt sweep (13 findings, 0 blocker, 7 high, 6 medium, all addressed). Three new shared modules: `json_utils.py` (default + balanced extraction + comment/comma fallback), `retry.py` (`call_with_retries` exp-backoff around every LLM call), `source_status.py` (typed `SourceFetchError` / `SourceSkipped`). Wired into writer / fact-check / claim-extractor / FIRMS / fire-footprint / state.py / sqlite_store.py | Next run: retry helper logs surface `[two_bot.retry] gemini fact-check attempt 1/3 failed: ReadTimeout` — three retries failed in <300ms total. Way too fast for a 90s timeout |
| **#43** | **Root cause: `google-genai` `HttpOptions.timeout` is MILLISECONDS, not seconds.** Three sites passing `90` (= 90ms) and `180` (= 180ms) bumped to `90000` / `180000`. Confirmed against `googleapis/python-genai/google/genai/types.py`: *"Timeout for the request in milliseconds."* Regression test introspects source for any `HttpOptions(timeout=NNN)` and asserts ≥ 5000 with a loud failure message about the ms-vs-s trap | Next run: writer + fact-check now succeed end-to-end. Fact-checker rejects `"Sissonville: UNVERIFIABLE: 'Sissonville' (without '1SW') does not appear exactly in the bundle. The bundle refers to 'SISSONVILLE 1SW'"` |
| **#44** | `normalize_station_name()` in ghcn.py strips CoCoRaHS suffixes (`1SW`, `2NE`, `0.5W`), airport suffixes (`INTL AP`, `MUNI AP`), and WFO prefixes. Applied at the data-source boundary so writer + fact-check both see clean place names | Next run: fact-check accepts the normalized name but rejects new claims: `"the state 'Washington' is not in the bundle"`, `"the word 'night' is not explicitly mentioned"`, `"flowers are already up — UNVERIFIABLE"` |
| **#45** | Bundle enrichment: `state` field on event dataclasses + `expand_us_state()` (`WV` → `West Virginia`) + `_format_where()` includes state for US (`"Sissonville, West Virginia, United States"`) + `_ghcn_observation_facts()` adds `observation_kind` (`"overnight low"` / `"afternoon high"`) | Next run: **TWO PENDING DRAFTS APPEAR** (Sissonville WV + Dayton WY). Pipeline working end-to-end |
| **#46** | Fahrenheit-first audience-aware temperature formatting. `_c_to_f()` integer conversion. `_audience_unit_facts()` adds `"fahrenheit_first"` for US, `"celsius_first"` elsewhere. Bundle headline_metric carries both `value` (C) and `value_f` (integer F). Writer prompt gains a `TEMPERATURE FORMATTING` section. Anomaly delta uses 9/5 scaling only (no +32 offset) | (no new bug — verification cycle showed structural cleanliness, no new pipeline_error records) |
| **#47** | Codex review of #38–#46 caught 3 high-severity bugs the author missed: dashboard `mergeState()` was erasing Python-owned state on every approve/reject click (data loss), SQLite `_METADATA_JSON_KEYS` was dropping `memory` + `data_source_failures` on every round-trip (state loss), claim_extractor had no Gemini timeout (unbounded hang risk). All three fixed | (final) |

## The actual root cause

**`google-genai` `HttpOptions.timeout` is documented as milliseconds.** The codebase migrated from the older `google-generativeai` SDK (timeout in seconds) to `google-genai` (timeout in milliseconds) around 2026-05-03 — same window the outage started. The values didn't change but the unit did. Three sites passed bare integers (`timeout=90`, `timeout=180`) believing they were seconds; they were 90ms and 180ms — barely enough for a TLS handshake. Every Gemini fact-check call failed with `ReadTimeout` in <300ms across 3 retry attempts, silently killing every two-bot draft for **4 days** (last successful draft 2026-05-03).

The diagnostic infrastructure shipped in #38 + #42 is what made the bug findable. Without the suppression ledger and the retry helper's diagnostic prints, this would have stayed invisible indefinitely.

## What's in queue

```
2 pending drafts (graded B and C+):

1. Sissonville, West Virginia hit -2.2 °C overnight on May 4th — breaking the
   previous May low of -1.7 °C set in 2020. Coldest May night in 16 years of
   records there. Fruit trees in the Kanawha Valley were not consulted.
   --> B-grade. Voice is good (Wodehouse-passing closer), signal is borderline
       (16-yr archive, 0.5°C margin).

2. Dayton, Wyoming dropped to -9.4 °C overnight on May 5th — breaking the
   previous May low of -8.3 °C set in 2010. Coldest May night in 21 years of
   records there, by 1.1 degrees.
   --> C+ grade. Quantifies the margin but voice is flat. No hook.
```

Both pre-date PR #46 (they're locked to old `°C`-only format because event_id is in `posted_events` dedup). New signals will use F-first formatting from the start.

## Open at session end

1. **Codex review medium/low findings** — all explicitly deferred. Documented in `docs/codex-review-findings-2026-05-08.md`. See BRIEFING.md "Known Issues" section.
2. **Suppression `stage` UI rendering** — schema is wired but dashboard groups by `source` only. Highest-leverage cleanup.
3. **GHCN observed records still labeled `forecast_*_c`** in `headline_metric.label` — semantically wrong since the same dataclasses now serve both Open-Meteo (forecast) and GHCN (observed). Should split.
4. **Writer prompt tightening for speculative claims** ("Flowers are already up", "the ground froze") — these are pure hallucinations the writer should be told not to add. Bundle enrichment can't fix them.
5. **Vercel GitHub auto-deploy not firing** on pushes to main — deploys go through manual `vercel --prod`. Worth investigating.

## What is OFF the table

- Brand identity (locked at R3 v4 since 2026-05-07).
- Hot 10 leaderboard migration to GHCN (stays on Open-Meteo).
- Open-Meteo dead-code removal (kept as rollback path for at least one quarter).
- Posting unpaused (resumption bar still: majority A-grade per cycle).

---

# 2026-05-06 → 2026-05-07 — GHCN-Daily migration + brand identity locked

## Where we landed

`main` is on `bad21be` and forward through PRs #30 → #31 → #32 → #33 → #35 → #36. **709 tests passing** (was 679 at session start). Posting still paused. The signal-side migration is shipped; identity layer is locked.

## The big shifts this session

1. **Extreme-signals lane migrated from Open-Meteo to NOAA GHCN-Daily.** The bot now reads 11,907 active stations instead of 638 curated cities — 19× population expansion at $0/month. Hot 10 leaderboard explicitly stays on Open-Meteo. Feature-flagged via `THEHEAT_SIGNALS_PROVIDER` (default `ghcn` in production, `open_meteo` for fallback). Five-PR sequence: P1 foundation (parser + scripts + weekly CI workflow) → P2 detection module + 30 tests → P3 wire-up + signal_date threading + record_streaks key migration → P4 cutover + Codex fix pass → P5 stale-obs filter (post-cutover diagnostic finding) → dashboard drill-down. See CHANGELOG [0.3.0.0].

2. **The bug pile that actually mattered.**
   - **`superghcnd_diff` format misread.** Original implementation assumed flat `.dly`-shaped text; live NOAA ships a tar archive of insert/update/delete CSV members. Codex review pass (PR #33) corrected.
   - **`climatological_mean_min` missing from shipped SQLite.** The 2026-05-05 bootstrap was run before the persistence fix landed, so the asset had `climatological_mean` (TMAX) rows but no TMIN climatology — silently blocking all cold-anomaly detection. Fixed by re-bootstrap and uploaded as `thresholds-latest`. Now backed by a regression test that asserts TMIN climatology round-trips through SQLite.
   - **Stale-obs filter** (PR #35). `superghcnd_diff` files routinely contain late-arriving observations from 1-2 weeks earlier. Live diagnostic on 2026-05-06 showed every firing bundle was anomaly_hot on observations from April 24-30. Editorial age penalty correctly killed all 55 of them, producing 0 drafts — but the bot was running on noise, not news. New constant `MAX_OBS_AGE_DAYS` (default 4) sets a freshness floor.

3. **Dashboard drill-down (PR #36).** Each row in the Source Health panel now has a `▶ details` button. Click expands to: pipeline funnel (bar chart of stage drop-off — stations active → with obs → checked → raw signals → bundles → drafts) + events table (per-bundle decision rows with badges: drafted / rejected / no_qualifying_signal). Powered by a new `details: dict` field on `source_run` records. Schema is loose; conventional keys: `pipeline_metrics`, `events`, `fetch_meta`. Each source can populate what's useful.

4. **Brand identity locked at R3 v4.** Painful path: 4 rounds of designer work, several rounds of my overcorrection ("visceral fever," melting wordmarks, station-pin debate, horizon-rule signature), then back to a thermometer-bulb mark + clean Inter SemiBold wordmark + paper/ink palette + single accent (`#C2410C`) on headline numbers. Production handoff at `brand/handoff/` (consolidated to one canonical location). Includes Brand Book.html, Operator Dashboard.html, Usage Guide.html, all production PNGs (avatars, banners, favicons, OG card), all SVGs (full-color, mono, reverse, outlined). The Twitter banner the designer shipped had broken typography (font-fallback failure) AND strategic problems (newspaper masthead, "REFRESHED HOURLY" lie, fake live reading). Replaced both PNGs locally using the outlined SVGs + Chrome headless render — clean now.

5. **Coverage honesty.** GHCN-Daily covers most but not all @extremetemps records. Verified present: Phoenix Sky Harbor, MSP, Verkhoyansk, Oymyakon, Phalodi, Death Valley. **Verified missing:** Tokashiki/Okinawa, Troodos/Cyprus (Japan + Cyprus have sparse station coverage in GHCN). Closing those gaps requires hybrid feeds (JMA AMeDAS, Cyprus DoMS) — deferred to a future PR if/when a station-level Japan or Cyprus event surfaces and the bot misses it.

6. **PR housekeeping.** Closed 10 stale daily-plan / pre-GHCN refinement PRs (#11, #12, #13, #15, #18, #20, #24, #27, #28, #34). Only #29 (`expand-cities-25`) remains open — likely superseded by GHCN's 11,907-station population, but left for the user to close after deciding whether any of its 25 stations are still distinctive (Tokashiki / Troodos territory).

## Open at session end

1. **Twitter profile NOT yet updated** with the new brand assets. The user has the avatar and banner files at `brand/handoff/png/` and will upload manually when ready.
2. **#29 expand-cities-25** still open on GitHub — user's call whether to close as superseded.
3. **Watch list for first 10 alert cycles** (per the lock-in PR description): lag framing reads cleanly ("on May 4," not "today"), at least one previously-missed event class fires, `data_source_failures["ghcn"]` stays at 0, dashboard funnel shows healthy stage progression.

## What is OFF the table going into next session

- Brand identity iteration. R3 v4 is locked. Don't reopen unless something is genuinely broken.
- Hot 10 leaderboard migration to GHCN. Stays on Open-Meteo.
- The Open-Meteo dead-code removal. Kept dormant behind the feature flag for at least one quarter as the rollback path.
- The "wire service" / "publication of record" framing for the Twitter banner. Twitter banners are static images that sit for months; anything implying live data ages into a lie within 24 hours. The brand voice (in tweet copy) carries the editorial register; the static chrome stays restrained.

---

# 2026-04-26 → 2026-04-29 — Voice engine v3 + research grounding + posting paused

## Where we landed

`main` is on the voice engine v3 ship commit. **566 tests passing** (was 522 at session start). Posting paused since 2026-04-12 — deliberate quality bar set 2026-04-26: posting resumes when majority of corpus-graded drafts earn A grades. Currently 0% A-rate (Apr 29). Daily plan-refinement agent runs 15:00 UTC, refining `docs/IMPROVEMENT_PLAN.md`.

## The big shifts this session

1. **Posting bar made explicit.** "Resume posting when majority A" — pinned in BRIEFING. Applies to all future cycles. Stale drafts can't ship even when shippable; window expires.
2. **Humor research grounded the voice work.** New doc `brand/HUMOR_RESEARCH.md` (270 lines) covers the four humor theories (Kant/Schopenhauer incongruity, McGraw & Warren benign violation, relief, superiority), joke construction, comic triple, brevity + specificity, deadpan tradition (Steven Wright, Mitch Hedberg, Bob Newhart), British humor (Wodehouse rule), and Shifman meme theory. Gives every voice mechanic a name and a corpus example. **Wodehouse rule named as the most predictive principle:** the voice should never sound like it's trying to be funny.
3. **Era anchors parked at 1-in-10.** Three consecutive corpus cycles (Apr 25, 27, 29) showed 100% era-anchor deployment on records. User direction Apr 29: park at no more than 1-in-10 tweets. Voice engine v3 ships the structural gate (`_era_anchor_should_fire`, deterministic by city+year+date seed). 90% of record drafts get explicit "parked, use other vehicles" steer-away; 10% get curated content framed as "your 1-in-10 turn."
4. **Addendum-mismatch bug fixed.** `generate_all_time_record_tweet` was using `category="all_time_record"` but addenda were keyed `all_time_high`/`all_time_low` — addenda had been DORMANT. Fixed to `category=f"all_time_{kind}"`. Same for monthly. Added missing `monthly_low`, `country_low`, `record_low` addenda. The voice work that went into those addenda has now actually started applying.
5. **Daily plan-refinement agent created.** `trig_016PGeHZgEYWmeQhx1xGmYg6`, fires 15:00 UTC daily. Reads framework docs, grades drafts, refines `docs/IMPROVEMENT_PLAN.md`, opens a PR. Plan-only — does NOT implement code/prompts. User reviews, we implement together.
6. **Anchor curation cleaned.** Pruned 43 entries from `data/era_anchors.json` (politically-charged: Trump, Brexit, Capitol riot, Elon/Twitter, MeToo; mass tragedies as scaffolding: 9/11, Katrina, Hurricane Sandy, Indian Ocean tsunami; US-only sports: Cubs, Red Sox; etc). Now 205 anchors / 31 years / 6.6 avg per year, all globally legible and politically neutral.
7. **Two-bot architecture conversation opened.** User raised: separate Data Organizer (gathers + structures signals into "story bundles") from Writer (takes bundles, writes voice with great voice). Cleaner than current Gemini-generates-then-Sonnet-rewrites. Brainstorm pending.
8. **Cost reality update.** "Free tier" Gemini claim was outdated. `gemini-flash-latest` aliases to a paid preview model at $0.30/$2.50 per MTok. Current Gemini spend: ~$5–10/mo. Pin `GEMINI_MODEL=gemini-2.5-flash` to return to free tier.

User also clarified important nuances:

- **"not everything has to be a joke"** — humor mechanics are tools, not mandates. Pure data delivery is valid when the number is striking enough.
- **"the era anchor can't be used every time. it gets so old and lame"** — drove the 1-in-10 parking decision.
- **"we paused posting because the tweets sucked"** — explained the 0-pending state. Posting is a deliberate quality pause, not an operational gap.
- **"we can't post those because they aren't real time"** — drafts have time-baked content, expire fast. 14 stale pending bulk-rejected 2026-04-26.
- **"keep building and refine an improvement plan, then i can review it and we can implement together"** — sets the agent autonomy boundary. Daily agent refines plan; human + Claude implement.

## What shipped this session (chronological)

- Voice engine v2.5 (era anchors + multi-station roll-call + recalibrated rules + opener-formula ban + earned editorial heat permission) — pre-session leftover
- BRIEFING resumption-bar pin + `docs/QUALITY_TREND.md` (A-rate trend + rejection log)
- Bulk-reject 4 D-range fires + 14 stale pending drafts (queue zeroed for clean baseline)
- `brand/HUMOR_RESEARCH.md` (270 lines, sibling to VIRALITY_RESEARCH)
- Apr 27 corpus humor-lens evaluation + Apr 24 corpus re-grades (#3, #4 demoted on grammatical-referent issue)
- `data/era_anchors.json` audit + 43-entry prune
- `docs/CLAUDE_DESIGN_BRIEF.md` + `docs/claude-design-handoff/` folder (3-direction brand identity request)
- `docs/IDEAS.md` NVIDIA NIM entry (dev-only A/B harness)
- `docs/IMPROVEMENT_PLAN.md` (living plan refined daily by autonomous agent)
- Daily recurring schedule `trig_016PGeHZgEYWmeQhx1xGmYg6` for plan refinement
- Apr 29 corpus grading (3 drafts, 0% A-rate)
- **Voice engine v3 (this commit):** era-anchor 1-in-10 gate + addendum-mismatch fix + 5 record-type addenda rewrite to 6-vehicle menu + SYSTEM_PROMPT #1 vehicle-agnostic rewrite + 3 new bad-examples + 5 new gate tests

## What's pinned mid-implementation

1. **Two-bot architecture redesign.** User raised 2026-04-29; we sketched the shape (Data Organizer outputs structured story bundles; Writer takes bundles + voice). Brainstorm not yet held. Bigger lift than P1-P6 — architectural.
2. **Prompts inventory doc.** User asked for a single doc listing all bot prompts (system + per-category + helpers + safety + evaluator) with content + locations. Half-built; abandoned mid-stride when the architecture conversation opened.

## Other open threads

- **Voice rules vs @extremetemps:** the voice spec is over-engineered for breakout-viral aspiration when our genre uses ALL CAPS / editorial heat / multi-station data dumps. Voice engine v2.5 partially addresses; deeper rethink still possible.
- **`evaluator_pass=null`** on all 3 Apr 29 drafts. Either evaluator isn't writing verdict to draft state, or `EVALUATOR_ENABLED` got set false. Worth investigating.
- **Daily plan-refinement agent's first run** is tomorrow morning. Should observe the empirical effect of the v3 era-anchor gate.

## Numbers

- Tests: 522 → 566 (+44 across the session)
- Commits pushed to `main`: 12+ (era_anchors prune, HUMOR_RESEARCH, corpus updates, design brief, IDEAS, BRIEFING, QUALITY_TREND, IMPROVEMENT_PLAN, voice engine v3 — final commit pending in this session)
- Era-anchor inventory: 248 → 205 (43 pruned)
- Pending drafts: 0 (paused; would-be drafts get graded but not posted)
- API spend: $30–55/mo total stack
- Posting cadence: 0 (last post Apr 12; resumption bar majority-A not yet cleared)

## When picking up in the next session

Read in order:
1. `BRIEFING.md` (current state)
2. This file's top section (Apr 26-29 — what just happened)
3. `docs/NEXT_SESSION.md` (action menu, invariants, common commands)
4. `docs/IMPROVEMENT_PLAN.md` (living plan, P1 SHIPPED + P4-P6 active)
5. `docs/QUALITY_TREND.md` (A-rate trend)
6. `docs/DRAFT_CORPUS.md` Apr 29 + Apr 27 sections (lens evaluations + re-grades)
7. `brand/HUMOR_RESEARCH.md` (the framework)

Pull pending drafts. If new corpus needs grading, append to `DRAFT_CORPUS.md`. Then pick a menu item from `NEXT_SESSION.md` — likely either continue the voice work (P4 Wodehouse top-of-prompt), open the two-bot architecture brainstorm, or finish the prompts inventory.

---

# Session Brief — April 24, 2026

Handoff doc for picking up @theheat work. Read after `BRIEFING.md`.

## Where we landed

`main` is at `1573d15`. **522 tests passing.** Single longest session
yet — combined the fire geocoder fix, FRP floor raise, voice engine
v2 (per-category prompts + stock-formula rejector), Gemini model
upgrade to `gemini-flash-latest`, full draft-quality audit of 35
pending drafts, bulk-rejection of all 35 with full inventory archived
to `docs/DRAFT_CORPUS.md`, and an ongoing model conversation that
ended with "do it right for now, keep Sonnet."

## The big shift this session

User reviewed pending drafts and grade-distributed them honestly: 7
A/B-grade out of 35, mostly records (Sevilla, Chicago, Jacobabad,
Kathmandu, Ipoh, Medan, Hawaii). 27 fires, all formulaic. Then user
showed three @extremetemps tweets — the actual successful account in
our genre, 106K followers — which break almost every voice rule we've
codified: ALL CAPS openers, "EXTRAORDINARY" / "Mind blowing"
editorial heat, multi-station data dumps, threading.

**This is the architectural insight to preserve:** our voice spec is
optimized for *breakout-viral aspiration* (Thunberg, Hausfather,
Kalmus). The data-ticker genre we're actually in uses different
tactics. We've banned the very tools the genre leader uses. Voice
engine v2 prompt addenda partially address this — they're more
permissive of editorial heat earned by the data — but the deeper
question (multi-station roll-call format, threading, lighter telling)
is still mostly TBD.

User also clarified important nuances:

- "We don't always want to roll-call though" — but don't preclude it
  in the data structure. Roll-call should be a callable generator
  format, not the only output.
- "Maps are easy to add. The hard part is the text." → maps are
  table-stakes-but-not-the-engine; voice work is the real lever.
- "We don't want to give up our generator and evaluator model" →
  keep two-model architecture. Don't collapse to single-pass Opus.
- "I'm unemployed!" → cost matters. But: "let's do it right for now"
  → keep Sonnet 4.6 evaluator running ($25-45/mo); don't switch to
  Opus; don't switch to Haiku; just have the kill switch ready.

## What shipped this session (chronological)

1. **`22cbc8e`** — Fire reverse-geocoder upgrade. `firms.py::
   reverse_geocode_simple` was returning continent-level labels
   ("somewhere in Asia"). Replaced with a 70+ entry bounding-box
   lookup ordered most-specific to least-specific. "Eastern Siberia,
   Russia" / "Patagonia, Argentina" / "the Kazakhstan steppe" / "the
   Northern Territory, Australia" — properly named regions globally.
   `_lat_lon_to_region` and `_lat_lon_to_country` retained as thin
   wrappers for backward compat.

2. **`023c3ed`** — FRP floor raised 100 → 250 MW. Sub-200 MW fires
   produced weak copy ("a coal plant runs at 150 MW, this is one of
   those") because the math was forced. 250 MW is closer to the
   "this reads as a real incident" threshold. Plus
   `docs/VOICE_FAILURE_ANALYSIS.md` added — names five Gemini ruts
   from the corpus with concrete intervention sketches.

3. **`d99ffe4`** — `docs/DRAFT_CORPUS.md` added with 2026-04-24
   section: full inventory of all 35 pending drafts including text,
   grade, and commentary. Then bulk-rejected all 35 via direct Gist
   PATCH. Pending queue cleared. The texts remain preserved in
   the doc as the longitudinal-corpus baseline.

4. **`827a891`** — Voice engine v2: per-signal-type prompt
   addendums + stock-formula rejector. Universal prompt updated to
   explicitly ban "powers N homes," generic power-plant comparisons,
   "no name yet" closers, continent-only locations. Per-category
   addenda for fire, all_time_high/low, monthly_high, anomaly_hot,
   country_high/low, record, co2_milestone, marine_heatwave,
   ice_mass_record, fire_footprint, synthesis. Regex rejector at
   parse time as last-line defense. Removed stale Siberia
   power-plant exemplar that was teaching Gemini the bad pattern.

5. **`d0977af`** — `docs/LEVEL_UP_PLAN.md` added. **Tier ordering
   was wrong on first pass** — I had Tier 1 = "post-publish analytics
   loop" until user pointed out we don't post enough for analytics
   to mean anything. Should re-read with quality work as Tier 1 and
   analytics as Tier 2-3. Worth a revision.

6. **`e25d0f0` then `b33d4a8`** — Gemini 2.5 Flash → 3.x model upgrade.
   First attempt pinned `gemini-3.1-flash-lite-preview` (user
   correctly flagged Lite is wrong for voice work). Second iteration
   switched to the `gemini-flash-latest` alias which Google rolls to
   whatever the current best Flash is. `GEMINI_MODEL` env var lets
   prod swap to a pinned snapshot or fall back to 2.5 instantly.

7. **`fa768a4`** — Two future-lane parking entries in `docs/IDEAS.md`:
   - Grok 4 A/B as candidate generator (xAI is the only frontier
     model trained on Twitter/X data — most ideologically aligned
     with our publishing platform).
   - Fine-tune Gemma 4 / Qwen 3.5 / Llama 4 on the @extremetemps
     corpus + EXEMPLARS + our A/B drafts. The differentiated bet —
     no other climate Twitter account is doing genre-specific
     fine-tuning. ~1 week of work, ~$100-300 compute.

8. **`4f07d50`** — BRIEFING cost figure corrected $60-90 → $25-45/mo.
   Previous figure was inherited from a prior session and never
   recalibrated. Real spend verified against console.anthropic.com.

9. **`1573d15`** — Added `EVALUATOR_ENABLED` env var kill switch
   (default `true` so no behavior change). Set to `false` to skip
   the Sonnet evaluator pass and drop Anthropic spend to ~$0/mo.
   Documented in BRIEFING secrets table.

## What's pinned mid-implementation

1. **Multi-station roll-call format for `simultaneous_records`.** The
   signal currently triggers on 5+ cities globally same day but the
   generator emits a flat summary ("5 cities broke records today")
   instead of a per-station list ("26.8 Janakpur / 24.1 Dang 663m /
   20.4 Dhankuta 1192m"). User saw this gap and said do it but keep
   roll-call as one *option* among formats — not the only output.
   Implementation pinned when user redirected to models conversation.

2. **Elevation surfacing in record/anomaly generators.** Elevation
   column added to cities.csv (this session) but the generator
   prompts don't yet pull it through. Tropical-night-in-the-highlands
   stories ("never happened above 1200m") need this data in the
   prompt context.

3. **13 cities missing elevation values.** Bulk fetch hit a 429 on
   the last batch. Trivial retry — just rerun the fetch script for
   the rows where `elevation_m` is empty.

## Other open threads

- **Voice rules still over-engineered for the wrong genre.** Voice
  engine v2 helped (allows some editorial heat earned by data) but
  the @extremetemps comparison shows we may still be too prim. Worth
  another voice-prompt iteration after observing what the new model
  + new prompt produce in the next draft cycle.
- **`docs/LEVEL_UP_PLAN.md` Tier ordering is wrong.** Tier 1 should
  be quality-side (era-anchor database, regenerate-corpus, prompt
  iteration), not analytics. Worth a revision.
- **Fine-tune lane** is the most differentiated future move. Real
  data sitting unused. Parked for now per user's "do it right for
  now" pace.

## Numbers

- Tests: 501 → 522 across the session (+21)
- Commits pushed: 9 to `main`
- API spend: $25 since April 7 (~$1.50/day) — verified
- Cities tracked: 613 across 179 countries with elevation
- Pending drafts: 0 (cleared after corpus archival)

## When picking up in the next session

1. Read `BRIEFING.md` (project state)
2. Read `docs/DRAFT_CORPUS.md` 2026-04-24 section (the corpus that
   informed every voice change today)
3. Read `docs/VOICE_FAILURE_ANALYSIS.md` (named patterns)
4. Read this `SESSION_BRIEF.md` (what just happened)
5. Read `docs/NEXT_SESSION.md` (action menu for the new session)
6. Pull current pending drafts from the Gist — see whether the next
   alerts cycle output reflects voice engine v2 quality lift
