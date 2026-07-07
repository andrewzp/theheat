# @theheat Front-Page Parity Plan — the leveling-up program

> **STATUS (2026-07-07): ADOPTED — #382 merged with Andrew's explicit go.**
> Rows 3/4/5 MERGED the same day (#384/#385/#386/#388 + the #387 A1-gate fix);
> **the A0 master flag is LIVE (12:59:59Z)** — FPP + A3 evidence clocks running.
> Current row statuses live in
> [front-page-parity/INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md);
> live flag/verification state in the latest handoff.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans for the fully-specified first move; every
> other row gets its own plan doc (brainstorm → write-plan → codex-xhigh) when it reaches
> the front of the queue. Steps use checkbox (`- [ ]`) syntax for tracking. This is the
> successor PROGRAM plan to
> [2026-07-03-three-pillar-upgrade-plan.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-07-03-three-pillar-upgrade-plan.md)
> (rows 1–8 all MERGED), written against Andrew's 2026-07-06 question: *"are our tweets
> going to be amazing and interesting and representative of what's happening around the
> world?"*

**Goal:** Make the honest answer to that question "yes, and here is the number that
proves it" — by turning on the built-but-dark selection machinery, closing the event-class
gaps where the world's biggest stories live, raising the voice floor on every signal type
to the proven four-moves standard, un-jamming the queue where good drafts currently die,
and measuring both bars (front-page parity + A-rate) so "amazing" stops being vibes.

**Architecture:** Five tracks sharing the established discipline (default-OFF flags,
codex-xhigh on gate-touching diffs, live dispatch verification, honesty gates only ever
strengthened). Track 0 is flag flips of already-codex-approved machinery — near-zero cost,
highest leverage, everything else compounds on it. Tracks 1–4 are PR-sized moves, each
gated by the evidence the previous ones produce.

**Tech Stack:** unchanged — Python 3.12, GitHub Actions cron + `gh`, Gist state, Sonnet
writer / Gemini Flash fact-check / Gemini 2.5 Pro critic, Next.js dashboard (Vercel).

## Global Constraints

- CI gate = `test` job: `ruff check src/ tests/` AND `mypy src/` AND `pytest` AND dashboard build; local canary (`THEHEAT_TIME_TRAVEL_DAYS=90`) before every push; fixture dates today-relative.
- codex-xhigh (`< /dev/null`, background, ONE backgrounding layer, looped to clean APPROVE, LAST round after LAST edit) on any diff touching editorial gates / posting / state / storage.
- Never weaken honesty gates. Every impact figure needs source+url+as_of (the iron constraint). Every new citable form is a pre-computed bundle value.
- Ship behavior changes behind default-OFF repo variables → live dispatch verify → flip → watch a full cycle. One-flip rollback documented per flag.
- Dispatch-workflow inputs reach shells via `INPUT_*` env only (#380).
- Stage only your own files; docs as their own PR; Andrew never merges (Claude merges on green, verifies the squash on origin/main).
- The writer is the metered Anthropic API — new LLM work states its per-cycle call budget.
- Python↔JS mirrors (sentinel ↔ `dashboard/lib/source-health.js`) change together, with mirror tests.

---

## The honest answer first

**Not yet — on all three of VISION.md's bars — and the system's own instruments say so
precisely.** The good news: roughly half the fix is already built, codex-approved, and
sitting behind unset flags.

1. **Representative?** No. The 2026-07-04/06 queue-vs-world review: the world's front
   page was a US heat dome (200M+ under alerts), Colorado's 8th-largest fire in history,
   1,300+ European heat deaths (WHO), and two typhoons — the queue held two station
   records, a duplicate-city pair, two false precip records, and an evergreen air-quality
   item. Zero fire drafts, zero cyclone drafts. Bavi produced five intensification drafts
   that died unreviewed, then went silent at peak (no `cyclone_land_threat` class — #375).
   The Europe death toll had **no path into the bot at all** (no mortality sensor; Bet A
   v2 is the path, gated on gap-flag evidence that can't accumulate until the master flag
   flips).
2. **Amazing/interesting?** Not consistently. The bot's own daily grading instrument
   (A–F corpus, resumption bar = >50% A-rate) reads **20% on the latest graded cycle**
   (Jul 5; peak 80% on Jun 29, n=5). The failure modes are *named and quantified* in
   [docs/IMPROVEMENT_PLAN.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/IMPROVEMENT_PLAN.md)
   (daily-plan branch): P_tier — internal detection taxonomy leaking into tweets
   ("the absolute extreme threshold for the northern subtropical band"; 10 instances,
   4 signal types, hard-caps grades at B); P_dust — 11 of 11 dust drafts missing the WHO
   anchor, and the root cause is a data gap, not writer taste: the sibling PM2.5 bundle
   pre-computes `who_multiple` and its drafts state it unprompted, while
   `build_dust_event_bundle` carries no such field — **the writer cannot cite what the
   bundle doesn't hold** (codex-verified); P_close — closers that
   state accumulation instead of consequence (16 cycles); P9 — precip opener template +
   restate-math. Meanwhile the four-moves pattern demonstrably works: the graded A- drafts
   (Siberia permafrost fire, Bavi RI, Loxahatchee) all execute it. It covers 2 of ~25
   signal families (reganom #349, fires #379).
3. **Do the good ones ship?** Often no. Drafting volume is fine (~132k observations/day;
   triage + refill live) — the loss is downstream: everything with human stakes is
   `manual_only` (correctly), and the manual queue is where Bavi died. The grading corpus
   and its fixes have lived on an unmerged branch for 29 cycles; the grading routine has
   skipped its staleness-reject action 38 consecutive times (no write path). And nothing
   measures the reader side: engagement capture exists in code
   (`src/data/twitter_metrics.py`) but the flag has never been set.

**The two numbers this plan manages to:** **FPP (front-page parity)** — of the verified
major extreme-weather events the news lane surfaces each week, the fraction we (a)
detected, (b) drafted, (c) posted — and **A-rate** (existing bar, >50%). Honest scope
(codex): FPP v0 measures parity **on the verticals the lane retrieves** (fire +
heat_mortality, ≤10 events/cycle in v1 — the denominator widens with row 10), and it
needs a **weekly snapshot rollup**, not a free query — `news_events` and
`candidates_log` are 7-day rolling windows and the existing matcher is the conservative
news-gap heuristic, so row 8 archives each week's events + match outcomes at rollup
time. First real FPP number ≈ one week after the master flip.

---

## The leverage-ordered queue (the plan at a glance)

| # | Move | Track | Effort | Risk | Depends on |
|---|---|---|---|---|---|
| 1 | **Flip `THEHEAT_NEWSWORTHINESS_ENABLED=1`** → live-verify A0 (citations, news-gap sanity). Starts the FPP + A3-evidence clock. | 0 | XS (Andrew) | Low (zero editorial surface) | — |
| 2 | **Enrich → boost flips, spec order** (re-run news-enrich-dryrun green first) → impact-carrying drafts in manual review; `news_boost=` in the ledger | 0 | XS (Andrew) | Low (one-flip rollback) | 1 |
| 3 | **Merge the daily-plan corpus to main + arm the grader's write path** — the quality instrument reconnects to the repo | 3 | S | Low | — |
| 4 | **Voice: P_tier + P_dust paired prompt+intern PR** (internal-taxonomy ban + a pre-computed dust WHO anchor the bundle currently lacks; E1 pairing discipline) — *first move, fully specified below* | 2 | S→M | Med (editorial gates; codex) | — |
| 5 | **#375 `cyclone_land_threat` event class** — forecast-track proximity → one `manual_only` draft per storm-landmass pair | 1 | M | Med (new state + editorial surface; codex) | — |
| 6 | **Review-loop v0** — daily editor brief (top-N pending, grades, approve links) + dashboard needs-me-now ordering; the queue stops being where stories die | 3 | M | Low (read-only + notification) | 3 helps |
| 7 | **E1-per-type: precipitation four-moves** (+ retire P9 with its paired rules; `writer_dryrun --type precipitation_extreme`) | 2 | M | Med (codex) | 4 pattern |
| 8 | **FPP weekly rollup** — weekly SNAPSHOT job archiving that week's `news_events` + match outcomes (rolling windows lose them) → one parity issue + dashboard card; scope stated on the card (lane verticals only, v1 fire + heat_mortality) | 4 | S | Low (read-only) | 1 |
| 9 | **Engagement capture ON** — one-line `bot.yml` passthrough for `THEHEAT_METRICS_ENABLED` (missing today — the 2026-06-13 handoff documented this; `gh variable set` alone is a no-op), flip, then generalize `tweet_metrics` polling beyond Hot 10 and feed the grading corpus (FUTURE_STATE's eval-set) | 4 | S→M | Low | — |
| 10 | **Boost beyond fire + feeds beyond NIFC** (heat/cyclone classes; WHO EURO surveillance, ReliefWeb when appname approved, NWS/NHC-as-news) | 1 | M | Med | 2 verified live |
| 11 | **E1-per-type: marine/coral + cyclone four-moves** (coral template convergence is the documented failure family) | 2 | M | Med (codex) | 7 |
| 12 | **A3 (Bet A v2): new-coverage-trigger** — draft the story the sensors never saw (the Europe death-toll class), `manual_only`, strictest verification | 1 | L | High (codex; new drafting origin) | 2–4 weeks of gap-flag evidence from 1 |
| 13 | **Heat-dome / population-exposure class design spike** — "N million under extreme-heat warnings" from NWS zones (+ reganom for the world half); build only if the spike closes the data question | 1 | M (spike S) | Med | spike first |
| 14 | **Fire geocode precision + geographic-spread triage tiebreaker** (IDEAS backlog; kills "somewhere in Asia" labels; prevents mono-region days) | 1/2 | S each | Low | — |

> **Per-row implementation plans (execution granularity for every build row):**
> [docs/superpowers/plans/front-page-parity/INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> — one self-contained TDD plan per row, written for a zero-context implementer, plus
> the track-0 flip runbook, the gated A3 design skeleton, and the heat-dome spike
> protocol.

Rationale for the order: rows 1–2 are the root-cause machine already built and reviewed —
every week they stay dark, the Congo-vs-Colorado failure class continues and the A3
evidence clock hasn't started. Row 3 reconnects the quality instrument before more voice
work banks on it. Row 4 is the highest-evidence-per-effort voice fix in the backlog
(11/11 and 10-instance failure modes, fix shapes proven by sibling types). Row 5 is this
week's live gap (Bavi-class storms recur all season). Row 6 attacks the single largest
waste in the system — good drafts dying unreviewed — without weakening any gate. Rows
7–14 then broaden coverage, voice, and measurement on the pattern the earlier rows prove.

**Explicitly NOT in this plan (standing, tracked elsewhere):** the trust floor (#346
dup-city, #372 remainder, #324 claim/warrant — Andrew's open review calls; false records
are anti-"amazing" and those threads stay live), the Sonnet 5 writer swap (PARKED,
handoff §Parked), and the FUTURE_STATE Postgres/editorial-desk migration (the long arc;
row 6 is its v0 without the datastore bet).

---

## Track 0 — Turn on what's built (Andrew; the classifier owns flips)

**Wrong today:** the newsworthiness lane, sourced-impact enrichment, and near-miss boost
— the direct fixes for both named VISION failures — are merged, codex-looped, and
live-dryrun-verified, and none of it runs. All three flags are unset as of 2026-07-06.
**Good looks like:** spec-order rollout (master → enrich → boost), each step live-verified
per [the 2026-07-06-night handoff](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-07-06-night.md)
§Bet A rollout, one-flip rollback each. Also Andrew's: the GHCN autoship ceiling call
(`THEHEAT_AUTOSHIP_MAX_AGE_H` 36→96h — today no GHCN record can ever auto-ship; a
deliberate "records stay manual" choice is fine, but it should be a *choice*).

## Track 1 — See the whole front page (event classes + coverage)

**Wrong today:** structural blind spots exactly where the biggest stories live. No
sustained cyclone-land-threat class (#375 — Bavi went silent at peak). No mortality path
(A3, evidence-gated). Boost is fire-only. `fire_footprint` is US-only (NIFC; GWIS has no
JSON API). NWS severe-weather is US-only and Emergency-tier-only. No population-exposure
heat class ("200M under alerts" is not a signal today). Basin records exist in code but
ship with an empty archive table (structurally dormant). **Good looks like:** the
news-gap watch reads quiet most weeks because the biggest world stories keep matching a
detected, drafted, posted event — and FPP trends up. Steps: rows 5 → 10 → 12 → 13 → 14,
each its own plan doc + codex loop; A3 only after the gap-flag evidence says which
verticals actually miss.

## Track 2 — Voice floor to the A-bar (every type writes like the best type)

**Wrong today:** 20% A-rate against a >50% bar, with the failure modes named, counted,
and — for two of them — already proven fixable by sibling types (air_quality states the
WHO anchor unprompted; dust never does; the Bavi A- avoided the P_tier trap its sibling
C+ fell into). The four-moves + paired-fact-check + dryrun pattern is proven twice
(reganom #349, fires #379). **Good looks like:** every signal family has a four-moves
section, every loosening has a paired gate, every prompt change is provable offline via
`writer_dryrun --type <kind>`, and the A-rate bar is visibly managed on main (row 3).
Steps: row 4 (below) → 7 → 11 → then temperature-records/air-quality per the same
pattern; row 14's geocode fix feeds fire quality.

## Track 3 — Ship what's written (the queue is product, not plumbing)

**Wrong today:** the manual queue is where the highest-stakes drafts (fires, cyclones,
impact tweets — soon Bet A's enriched drafts) go to age out. The queue watch (#364) now
alarms at 24h, but alarming isn't reviewing. The grading routine can't act on its own
staleness findings (38 consecutive write-skips) and its corpus has been off-main for 29
cycles. **Good looks like:** a daily editor brief lands wherever Andrew reads (top-N
pending ranked by grade × freshness × FPP-relevance, one-tap dashboard links), the
dashboard leads with "what needs me now," staleness rejection actually fires, and the
corpus lives on main. Steps: row 3 → row 6 → then the parked
dashboard-recently-posted feed (visibility into what actually shipped — the false Barrow
tweet sat unnoticed for a month).

## Track 4 — Measure both bars (so the answer stops being vibes)

**Wrong today:** no reader-side signal at all (engagement lane dormant), no
representativeness number (news-gap watch ships with the master flip but nothing rolls it
up), A-rate invisible outside a branch. **Good looks like:** a weekly FPP number with the
three-stage funnel (detected/drafted/posted vs verified world events), per-tweet
engagement riding the grading corpus (FUTURE_STATE's "eval set from actual performance"),
and A-rate on the dashboard strip. Steps: row 8 → row 9 → fold both into the daily brief
(row 6).

---

## First move, fully specified — Row 4: the P_tier + P_dust paired voice PR

The E1 pattern applied to the two highest-evidence failure modes. One PR, editorial-gate
+ intern diff → codex-xhigh mandatory. Per-cycle LLM budget: zero new calls (prompt +
bundle-field work; one optional dryrun dispatch).

**Corrected data contract (codex P0s, rounds 1 AND 2 on this plan):**
`who_multiple` exists ONLY on PM2.5 bundles (`build_pm25_hazard_bundle`);
`DustEvent`/`build_dust_event_bundle` carry no WHO anchor at all — which is WHY 11/11
dust drafts lack it. AND the anchor cannot be built from the `dust` variable itself:
Open-Meteo's `dust` is mineral/Saharan dust specifically, a SEPARATE hourly variable
from `pm10` — no 24h-average standard applies to `dust` (the 2026-06-08 air-quality
design kept dust daily-max for exactly this reason). The honest anchor is
**co-measured PM10**: add `pm10` to the existing hourly fetch for dust-tier cities,
compute its 24-hour MEAN, and anchor mean-vs-mean against the WHO 2021 PM10 24h AQG
(45 μg/m³) — a real PM10 claim tied to the dust event ("during the event, PM10
averaged 20× the WHO 24-hour guideline"), never "dust is PM10" and never a daily-max
against a mean guideline. **Budget check in-row:** adding one hourly variable raises
the Open-Meteo request weight on a sweep that already runs near its per-minute limit —
verify coverage stays ≥ `AQ_MIN_COVERAGE` (90%) with the recovery passes, else scope
the pm10 add-on to dust-candidate cities only.

**Files:**
- Modify: `src/data/air_quality.py` (fetch adds `pm10` hourly; `DustEvent` gains `pm10_24h_mean_ug_m3` + `who_pm10_multiple` = pm10_mean/45.0, both computed at fetch)
- Modify: `src/two_bot/intern/air_quality.py` (`build_dust_event_bundle` carries `pm10_24h_mean_ug_m3`, `who_pm10_multiple`, `who_pm10_24h_guideline_ug_m3: 45` facts)
- Modify: `src/two_bot/prompts/writer_prompt.py` (WHAT NEVER SHIPS bullet + dust-anchor convention)
- Modify: `src/two_bot/prompts/fact_check_prompt.py` (rule m — the pairing)
- Modify: `src/two_bot/prompts/critic_prompt.py` (P_tier kill-condition bullet — the critic graded these B, it should kill them)
- Modify: `scripts/writer_dryrun.py` (add `--type dust` fixture; DEFAULTS entry)
- Test: `tests/two_bot/test_air_quality_intern.py` (dust anchor fields), `tests/two_bot/test_prompts.py` (new classes), `tests/test_writer_dryrun.py` (dust fixture)

**Interfaces:**
- Consumes: the existing `DustEvent` fetch path (hourly dust series → daily max; add the 24h mean beside it); `band_label` fact on absolute_extreme bundles (`src/two_bot/intern/temperature.py:347`); the `_frp_tier` reader-facing tier-word convention (kept — see the distinction below).
- Produces: `who_pm10_multiple` on dust bundles; writer-prompt bullet **"DETECTION PLUMBING IS NOT A FACT"**; fact-check rule (m); critic kill example `internal_taxonomy_leak`; `writer_dryrun --type dust`.

**The load-bearing distinction (write it into the prompt verbatim-ish):** what stays
citable is (a) **observed actuals** — the storm's real `delta_kt_24h` ("winds climbing
40 kt in 24 hours" — the corpus's Bavi A- did exactly this), and (b) **bundle-designed
reader anchors** — `frp_tier` words INCLUDING the existing sanctioned
`frp_tier_floor_mw` phrasing ("above the 100 MW high-intensity threshold"), canonical
published scales (Saffir-Simpson, DHW alert levels, Beaufort), and the WHO multiples.
What is banned is citing the **detector's own configuration as authority**: `band_label`
("the northern subtropical band"), per-class editorial score thresholds, and trigger
definitions ("the rapid-intensification threshold is 30 kt in 24 hours" — the corpus's
Bavi C+ did exactly this). Same number, different claim: the observed delta is a fact
about the storm; the trigger definition is a fact about the bot.

- [ ] **Step 1: Write the failing intern test** (in `tests/two_bot/test_air_quality_intern.py`, where the air-quality intern tests live)

```python
def test_build_dust_event_bundle_carries_who_pm10_anchor():
    """P_dust root cause: the dust bundle carried no WHO anchor (PM2.5's
    who_multiple never applied to dust). Anchor is co-measured PM10,
    mean-vs-mean: 24h PM10 mean against the WHO 2021 PM10 24h guideline
    (45 μg/m³) — never the `dust` variable itself, which is not PM10."""
    event = _dust_event(daily_max=2400.0, pm10_24h_mean=900.0)  # helper mirrors existing fixtures
    bundle = build_dust_event_bundle(event)
    facts = {f["label"]: f.get("value") for f in bundle.current_facts}
    assert facts["pm10_24h_mean_ug_m3"] == 900.0
    assert facts["who_pm10_24h_guideline_ug_m3"] == 45
    assert facts["who_pm10_multiple"] == 20.0  # 900 / 45, pre-computed
```

- [ ] **Step 2: Write the failing prompt tests** — every assertion targets NEW exact
phrases (codex P1: `who_multiple`/`dust_event` already appear in the PM2.5 conventions,
so generic presence checks would pass vacuously before the change):

```python
class TestDetectionPlumbingBan:
    """P_tier (10 instances, 4 signal types, grade-capping at B): internal
    detection taxonomy leaking into tweets."""

    def test_writer_bullet_present(self):
        assert "DETECTION PLUMBING IS NOT A FACT" in WRITER_SYSTEM_PROMPT
        assert "band_label" in WRITER_SYSTEM_PROMPT  # new — not in the prompt today

    def test_observed_actuals_stay_sanctioned(self):
        # The ban must carve out the storm's real delta and the designed anchors.
        assert "a fact about the storm" in WRITER_SYSTEM_PROMPT
        assert "above the 100 MW high-intensity threshold" in WRITER_SYSTEM_PROMPT  # pre-existing, must survive

    def test_fact_check_pairing(self):
        assert "the bot's config is not a citable fact" in FACT_CHECK_SYSTEM_PROMPT.lower()
        assert "band_label" in FACT_CHECK_SYSTEM_PROMPT

    def test_critic_kill_condition(self):
        assert "internal_taxonomy_leak" in CRITIC_SYSTEM_PROMPT


class TestDustWhoAnchor:
    def test_dust_anchor_move_present(self):
        assert "who_pm10_multiple" in WRITER_SYSTEM_PROMPT      # new field, new text
        assert "who_pm10_multiple" in FACT_CHECK_SYSTEM_PROMPT  # exact-match pairing
```

- [ ] **Step 3: Run to verify failure** — two commands (one selector each):
`.venv/bin/python -m pytest tests/two_bot/test_air_quality_intern.py -k who_pm10 -v` →
FAIL (field absent); `.venv/bin/python -m pytest tests/two_bot/test_prompts.py -k
"Plumbing or DustWho" -v` → FAIL (strings absent).

- [ ] **Step 4: Implement the fetcher + intern fields** (`pm10` added to the hourly
request; 24h mean computed where the hourly series is in hand; bundle facts as in
Step 1; PM2.5 path untouched; coverage re-verified ≥90% per the budget check above).

- [ ] **Step 5: Writer prompt — the WHAT NEVER SHIPS bullet** (after the tier-explainers
bullet, which it generalizes):

```markdown
- **DETECTION PLUMBING IS NOT A FACT.** The bot's own detection configuration —
  latitude-band names (`band_label`, e.g. "the northern subtropical band"), per-class
  editorial score thresholds, detector trigger definitions ("the rapid-intensification
  threshold is 30 kt in 24 hours") — is how the bot decided to LOOK, not something a
  reader can verify anywhere. Never cite it. What stays: observed actuals (the storm's
  real `delta_kt_24h` — "winds climbing 40 kt in 24 hours" is a fact about the storm,
  not the bot) and bundle-designed reader anchors (`frp_tier` words including "above
  the 100 MW high-intensity threshold", Saffir-Simpson, DHW alert levels, Beaufort,
  the WHO multiples). Test: is this a fact about the WORLD a reader could look up, or
  a fact about this bot's configuration? World: cite. Bot: never.
```

Plus the dust convention: for `dust_event` bundles, `who_pm10_multiple` is the scale
anchor — *"during the event, PM10 averaged 20× the WHO 24-hour guideline"* — cite it
verbatim; the claim is about co-measured PM10, never about the `dust` value itself,
and never a daily max against the 24h-mean guideline.

- [ ] **Step 6: Fact-check rule (m), the pairing**

```markdown
**m) Detection plumbing — the bot's config is not a citable fact.** Latitude-band
names (`band_label`), per-class editorial score thresholds, and detector trigger
definitions ("the rapid-intensification threshold is 30 kt in 24 hours") are internal
configuration: UNVERIFIABLE as tweet claims — a reader cannot verify the bot's config.
Distinguish: the OBSERVED `delta_kt_24h` ("winds climbed 40 kt in 24 hours") is
BUNDLE_FACT and fully citable; so are canonical published scales (Saffir-Simpson,
NOAA DHW alert levels, Beaufort), the bundle-designed `frp_tier` phrasings, and the
WHO multiples (`who_multiple`, `who_pm10_multiple`) — verify those against the bundle
values exactly as always.
```

- [ ] **Step 7: Critic kill-condition bullet + example** — under Voice/craft, with the
corpus's Doha phrasing as the concrete example; add `"internal_taxonomy_leak: cites the
detector's band/threshold config as if it were a published scale"` to the kill_reason
examples.

- [ ] **Step 8: Dryrun `--type dust`** — DEFAULTS: Phalodi-class fixture (dust daily-max
2,400 μg/m³, PM10 24h mean 900 → `who_pm10_multiple` 20.0); wire into `_build_bundle` +
workflow choice list; extend `tests/test_writer_dryrun.py` with the fixture-shape test
(anchor fields present, evidence contract PASS).

- [ ] **Step 9: Full local gates** — `ruff check src/ tests/ scripts/writer_dryrun.py` +
`mypy src/` + `THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q` → all green.

- [ ] **Step 10: Commit → PR → codex-xhigh loop to clean APPROVE (last round after last
edit) → merge on green → dispatch `writer-dryrun --type dust` for the live voice check.**

**Success criteria for the row:** next graded cycles show P_tier instances → 0 and dust
drafts carrying the WHO anchor; both proposals move to Resolved in IMPROVEMENT_PLAN.md.

---

## Decisions Andrew owns (the plan's blocking inputs)

1. **The three Bet A flips** (rows 1–2) — the whole plan's compounding base. The
   classifier owns prod flags; everything is staged for spec-order rollout.
2. **Review-loop shape** (row 6): where should the daily editor brief land — X DM,
   email, dashboard-only, or a phone-notification channel? (Build follows the answer.)
3. **Engagement capture** (row 9): confirm the X API tier in use exposes per-tweet
   `public_metrics` at our volume (the dormant lane assumed it; verify before flipping).
4. **GHCN autoship ceiling** (`THEHEAT_AUTOSHIP_MAX_AGE_H` 36→96) — records currently
   never auto-ship; choice, not accident.
5. **Standing:** #324 claim/warrant review; #346 dup-city direction; `SELFHEAL_PAT`
   (#309). The trust floor is what keeps "amazing" from being undermined by one false
   record.
