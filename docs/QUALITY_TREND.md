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
| 2026-04-29 | 3 | 0 | 3 | 0 | 0 | **0%** | ✗ | Three records, all era-anchored — third consecutive cycle at 100%. A-rate 0% because no draft reached A-; best was B+ (Jacksonville). Explicit-gap-math Wodehouse violation repeated (Mexico City). |
| 2026-05-06 | 0 | — | — | — | — | **N/A** | N/A | Zero-denominator cycle. Queue empty: generation gap post-two-bot port (PR #25 per later commit), alert cycles show promoted>0 but drafted=0 since ~May 4. Seven ungraded May 1–3 drafts already rejected; preliminary A-rate if graded would be ~14% (1/7). |

**Trend interpretation:**
The Apr 25 jump to 43% was real but came from a small cohort (7 drafts) and didn't sustain. Apr 27 regressed (named causes: Sonnet rewrite path, verb-list gap, era-anchor over-deployment, political anchor curation error). Apr 29 continued at 0% A (all three records B-range, all era-anchored). May 6 is a zero-denominator cycle: a generation gap (drafted=0 across all May 4–5 alert runs) has halted new output, likely caused by a pipeline change (two-bot architecture port). Until the generation gap resolves, A-rate tracking is paused.

Pre-gap trend: 9%–43%–9%–0% across four cycles. Era-anchor over-deployment (P1 / P4 Wodehouse are the two highest-leverage open proposals) is the consistent failure driver. Need to clear 50% sustained once generation resumes.

## Rejection events

Drafts that got rejected, with dates. The texts and full grading commentary live in `docs/DRAFT_CORPUS.md`. This section logs the rejection EVENT (when, why, count) so the operational history is traceable.

### 2026-05-06 — No bulk-reject (queue already empty)

Zero pending drafts at grading time. The May 1–3 drafts (Blizzard AK, Conakry, Ho Chi Minh City, Riga, Prague, Seattle, Mali fire) were already rejected before this session ran; all contained real-time-baked language ("today," "forecast," "right now") and were >48h old at grading time. Apr 29 drafts (Cuenca, Mexico City, Jacksonville) similarly already rejected by session time.

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
