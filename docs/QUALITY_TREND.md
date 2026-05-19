# Quality Trend & Rejection Log

Two views of the same thing: **are the bot's tweets getting better over time, or not.**

## The resumption bar

> **Posting resumes when the majority of corpus-graded drafts in a cycle earn A grades.**
> Set 2026-04-26. Posting paused until then.

We grade drafts on an A through F rubric in `docs/DRAFT_CORPUS.md` (the longitudinal corpus archive). This file pulls the headline metric out of every grading cycle so trend is visible at a glance, plus logs rejection events so the "what got cut" history is traceable.

## A-grade rate by cycle

| Date | Drafts | A | B | C | D/F | A-rate | ≥50%? | Notes |
|------|-------:|--:|--:|--:|---:|------:|:-----:|-------|
| 2026-04-24 | 35 | 3 | 6 | 6 | 20 | **9%** | ✗ | Pre-voice-engine-v2 baseline. Most rejects were continent-only locations + "powers N homes" formulas. |
| 2026-04-25 | 7 | 3 | 3 | 1 | 0 | **43%** | ✗ | First post-v2 cycle. Largest single jump. Era anchors landing for the first time. |
| 2026-04-27 | 11 | 1 | 5 | 1 | 4 | **9%** | ✗ | Regression. Banned-formula opener variants returned via Sonnet rewrite path. Era anchors over-deployed. Plus one political-anchor (Elon, since pruned). Humor-lens evaluation surfaced what's failing. |
| 2026-04-29 | 3 | 0 | 2 | 0 | 0 | **0%** | ✗ | Three records, all using era anchors — third cycle with this pattern. User direction same day: park era anchors at 1-in-10. Voice engine v3 shipped: gate + addendum-mismatch fix + SYSTEM_PROMPT vehicle-agnostic rewrite. Next 3 cycles will show whether the gate empirically works. |
| 2026-05-12 | 0 | — | — | — | — | **—** | ✗ | No pending drafts (queue empty). All four production kills diagnosed and fixed: PR #82 (station-name regex for `4 NE` + ANG suffix), PR #80 (FRP bundle-side rounding), PR #82 (ocean_sst User-Agent header), PR #82 (river_gauges graceful degradation). PR #76 also added writer-side length-cap retry + KILL; PR #82 added JSON-parse retry + KILL. The 18:39 UTC alerts run is the first cycle against the fixes — first chance for fresh drafts to reach pending under the new voice + guardrails. Andrew also manually rejected Mankato cold record 2026-05-11 with voice direction: "defensive 'A record is a record' closer" (now banned via PR #74 HARD RULE). |
| 2026-05-13 | 4 | 0 | 1 | 3 | 0 | **0%** | ✗ | First graded two-bot cycle. 3 fire drafts (Mali, Campeche, Mongolia) all used identical formula opener + seasonal-explanation structure — fire template convergence identified as new failure mode (P6). Chuuk FSM monthly_high (76-year record) is the one B: clean data, no Wodehouse violation, but expository second sentence instead of a punchline. P3 self-kill failure not observed (positive). FRP bundle rounding (#80) confirmed working (309.6, 364.7, 307.6 MW values clean). |
| 2026-05-19 | 14 | 3 | 6 | 5 | 0 | **21%** | ✗ | First graded coral_bleaching batch (9 drafts). 3 A-: Madagascar (DHW contrast-reveal "persistence is what kills"), Galapagos (upwelling-failure + double mortality threshold), Costa Rica Pacific (no-upwelling "nowhere to drain"). 4 B+: Fiji/Nauru/Austral Islands coral + Siberia fire (P6 template broken; timing incongruity embedded). 2 B-: Bethel ME monthly_low + Stahl Peak snow extreme (5× record understated). 5 C/C+: 2 sub-threshold coral + Southern Borneo (low floor threshold) + Nooksack (station artifact "Mf Nooksack") + BC fire (stale). New proposals: P7 coral opener formula convergence, P8 snow ratio as punchline. P5 partially confirmed (fire drafts lack named mechanics). |

**Trend interpretation:**
The Apr 25 jump to 43% was real but came from a small cohort (7 drafts) and didn't sustain into Apr 27. The Apr 27 regression has named causes (Sonnet rewrite path, verb-list gap in opener regex, era-anchor over-deployment, political anchor curation error). All four have proposed fixes documented in `docs/DRAFT_CORPUS.md` Apr 27 implications section. Next data point: tomorrow's scheduled grader (fires 2026-04-27 06:00 UTC) on the Apr 26-27 cycle output under v2.5 + post-humor-lens fixes.

We've been in the 9-43% band for three cycles. Need to clear 50% sustained.

## Rejection events

Drafts that got rejected, with dates.

### 2026-05-19 — Staleness bulk-reject: skipped (gh CLI not found in cloud env)

**Why:** 1 draft identified for staleness rejection: `draft_20260514_211447_164` (BC fire,
"burning today" baked from 2026-05-14T21:14Z — 114 hours old at grading). Bulk-reject
attempted via `gh api -X PATCH gists/...` — `gh` command not found in managed remote
execution environment. Operator action required: reject `draft_20260514_211447_164` via
dashboard or direct Gist edit. Additional observation: 7 coral drafts (Drafts 7–13) are
4–7 days old with present-tense DHW accumulation claims ("has accumulated X°C-weeks") that
may no longer reflect current DHW values; they lack explicit "today" language and were not
bulk-rejected per policy, but operator should review for accuracy before posting.

### 2026-05-13 — Staleness bulk-reject: not needed (no stale drafts)

**Why:** 4 pending drafts, all within 48 hours of creation (oldest: 2026-05-12T18:03Z,
~16 hours at time of grading). None contain real-time-baked content ("forecast to hit
today", "It is May 13", etc.) — fire drafts use present-tense satellite-detection framing
with no date baked in; Chuuk monthly_high references "May 9" as the observation date of
a record, not as "today." No staleness rejection triggered. Gist write not attempted.

### 2026-05-12 — Staleness bulk-reject: skipped (0 pending drafts)

**Why:** No pending drafts in queue; nothing to evaluate for staleness. Gist write not
attempted. Operator note resolved end-of-day 2026-05-12: both source degradations
(`ocean_sst` infinite redirects, `river_gauges` empty responses) are now fixed in PR #82
(User-Agent header + graceful degradation respectively). The four classes of writer/fact-
check kills that produced 0 drafts today are also addressed (PR #82 station-name regex,
PR #80 FRP bundle-side rounding, PR #76 length retry + KILL, PR #82 JSON-parse retry +
KILL). The texts and full grading commentary live in `docs/DRAFT_CORPUS.md`. This section
logs the rejection EVENT (when, why, count) so the operational history is traceable.

### 2026-04-26 — Bulk-reject 14 stale pending drafts

**Why:** All 14 drafts had real-time content baked into their text ("forecast to hit X today" / "set just last year in 2024" / "It is April 26"). Posted now they would read as wrong-day, past-tense, or confused. The window closed. Plus posting is paused until the resumption bar is cleared, so even fresh-baked versions of these wouldn't ship today. Rejected to clean the queue and give tomorrow's grader a clean baseline.

The 14 rejected drafts (preserved here for longitudinal comparison; full grading commentary in `docs/DRAFT_CORPUS.md`):

| Draft ID | Created | Type | Grade | Text |
|---|---|---|---|---|
| `draft_20260424_075424_119` | 2026-04-24 | fire | A- | New South Wales. A 327 MW fire today. The bushfire season here used to know when to quit. It's April. |
| `draft_20260424_154638_122` | 2026-04-24 | record | B+ | Kampung Baru Subang, Malaysia forecast to hit 94.1F today. The calendar date record from 1998 was 89.6F. Back then, Windows 98 was new. |
| `draft_20260424_190831_123` | 2026-04-24 | record | A- | Navi Mumbai is on pace for 106.7F today. That's 4.5F hotter than its record for this date, set just last year in 2024. |
| `draft_20260425_043325_124` | 2026-04-25 | record | B+ | Lucknow is forecast to hit 110.8F today. That beats its calendar record from 1999. Before Y2K was a real worry. |
| `draft_20260425_074401_125` | 2026-04-25 | record | B | Manchester forecast: 68.7F today. That beats the previous record for this date by nearly 3 degrees. The old mark of 66.0F was set in 2004, the year before YouTube. |
| `draft_20260425_184310_126` | 2026-04-25 | fire | A- | 404 MW of fire in Mali's Western Sahel. The land has been parched for months, and the HOT season has barely started. It's April. |
| `draft_20260425_184356_127` | 2026-04-25 | fire | C+ | A fire burning in Mali right now is radiating 404 MW of heat. The last rain fell there in October. That was 6 months ago. |
| `draft_20260426_222756_129` | 2026-04-26 | record | B+ | Petaling Jaya is forecast to hit 93.6F today. The record for this date was 89.2F — set in 2023, back when Hollywood writers were on strike. That gap is 4.4 degrees. |
| `draft_20260426_222959_130` | 2026-04-26 | fire | A- | Mali's Western Sahel is burning. A 291 MW fire is active in a landscape where the burning season typically peaks in January and ends by February. It is April 26. |
| `draft_20260426_223024_131` | 2026-04-26 | fire | B+ | 379 megawatts of heat radiating from the State of Mexico highlands right now. Satellite confidence: 95%. The summer monsoon that extinguishes these fires is still weeks away. |
| `draft_20260427_120825_132` | 2026-04-27 | record | C+ | Jacobabad is forecast to hit 114.1F today. The old record for this date was 112.1F. That record was set in 2022. It has only been the record since Elon Musk bought Twitter. |
| `draft_20260427_193214_134` | 2026-04-27 | monthly_high | B | Bukit Rahman Putra is forecast to hit 94.5F today. If it holds, that breaks an April record that has stood since 2016 — the year Pokémon GO had everyone walking outside. The new high: 94.5F. The old one: 93.7F. |
| `draft_20260427_230708_137` | 2026-04-27 | fire | B- | A 298 MW fire signature just appeared in central Mexico. Satellite confidence is 95 percent. The historical peak for fire activity in this region is still three weeks away. The rainy season does not typically begin until June. |
| `draft_20260427_230744_138` | 2026-04-27 | fire | B | Mexico State is radiating 258 MW of energy. 95% satellite confidence. The region's dry season doesn't break until late May. It is only April 27. |

**Notable:** four of these (NSW, Navi Mumbai, Mali Western Sahel "is burning", Mali "HOT season") were A- grades — they would have shipped if posting weren't paused AND if they were still timely. The pause + the staleness combine to disqualify even the strong drafts.

### 2026-04-26 — Bulk-reject 4 D-range fire drafts (earlier same day)

**Why:** humor-lens evaluation flagged banned-formula openers, stranded misdirection, and Wodehouse-rule violations. Detail in `docs/DRAFT_CORPUS.md` Apr 27 humor-lens section. Drafts:
- `draft_20260427_193501_136` — D- — "A wildfire burning in Mexico State is radiating 281 MW... pointed at the sky."
- `draft_20260427_193333_135` — D — "A wildfire in Mexico state is radiating 382 MW... commercial nuclear reactor outputs around 3,000 MW. This fire is running at roughly one-eighth of that — from a forest."
- `draft_20260427_120948_133` — D — "A single fire in central India is radiating 274 MW..."
- `draft_20260426_110808_128` — D — "A single wildfire in central India is pushing 297 MW of radiative power..."

### 2026-04-24 — Bulk-reject all 35 from Apr 24 corpus

**Why:** End of Apr 24 session, after the corpus grading exercise that established the eval baseline. All 35 drafts in queue were rejected to start fresh under voice engine v2 (which shipped same day). Texts preserved in `docs/DRAFT_CORPUS.md` Apr 24 section.

## How this file is used

- **Update after every grading cycle** — append a row to the A-rate table with that cycle's date, grade distribution, and notes.
- **Update after every bulk-reject event** — log the count, reason, and IDs (or a corpus reference) under the rejection events section.
- **Read before any posting decision** — has the trend cleared 50% sustained? If yes, resume. If no, the voice work continues.
- **Scheduled grader output** — the autonomous grading agent (next fires 2026-04-27 06:00 UTC) should append its own row to this table when it grades a fresh corpus cycle.
