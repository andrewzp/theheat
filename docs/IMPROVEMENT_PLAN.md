# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

## Current state

| | |
|---|---|
| Bot commit | `d9c84ff` (two-bot pipeline live — #47 Codex high-severity batch) |
| Voice engine version | v3 (era anchors PARKED at 1-in-10 + addendum-mismatch fix + SYSTEM_PROMPT vehicle-agnostic + new bad-examples). **NOTE: `src/voice/generator.py` is DEAD since 2026-05-04** — no live call sites. The active writer is `src/two_bot/prompts/writer_prompt.py`. All proposal code pointers below that reference `generator.py` target dead code and must be redirected to `writer_prompt.py` before implementation. |
| Last cycle A-rate | 0% (May 9, 0 of 3) |
| Resumption bar | majority A (>50%) sustained |
| Gap | 50 percentage points |
| Posting | paused until bar cleared |

## Active proposals

Ordered by leverage. Each entry tracks: observation count (cycles where the failure mode appeared), last seen, proposed fix, expected impact, status.

### ~~P1~~ — Era anchors parked at 1-in-10 — **SHIPPED 2026-04-29 (awaiting empirical confirmation)**

**Observed (cumulative):** 3 of 3 records used era anchors on Apr 25, 5 of 5 on Apr 27, 3 of 3 on Apr 29 — three consecutive cycles at 100%. User direction same day: park era anchors at no more than 1-in-10 tweets. Prose-only de-emphasis was insufficient; structural gate was required.

**Cycles observed:** Apr 25, Apr 27, Apr 29 (3 cycles, 100% deployment each).
**Last seen:** Apr 29.

**Implemented in same-day commit (voice engine v3):**

1. `_era_anchor_should_fire(seed_key, rate=0.1)` — deterministic 1-in-10 gate, seeded by city+year+date. Same draft cycle reproducible; across many seeds fires at ~10%.
2. `_era_anchor_hint` rewritten: 90% of calls return explicit "parked, not your turn" steer-away message naming the 5 alternative specificity vehicles. 10% of calls return curated content framed as "your 1-in-10 turn."
3. **Addendum-mismatch bug fixed.** `generate_all_time_record_tweet` was using `category="all_time_record"` but addenda were keyed `all_time_high`/`all_time_low` — addenda had been dormant. Fixed to `category=f"all_time_{kind}"`. Same fix for monthly. Added missing `monthly_low`, `country_low`, `record_low` addenda.
4. **5 record-type per-category addenda rewritten** to use a shared 6-vehicle specificity menu (`_RECORD_SPECIFICITY_VEHICLES` constant). Era anchor is option 6, explicitly marked PARKED.
5. **SYSTEM_PROMPT #1 ("HISTORICAL WEIGHT") rewritten** to be vehicle-agnostic. Was era-anchor-evangelizing ("anchor the year to something human"); now lists all 6 specificity vehicles equally and notes era anchors are parked.
6. **3 new bad-examples added:** explicit-gap math ("That gap is 4.5 degrees"), restate-padding ("The new high: X. The old one: Y."), era-anchor-then-restate template.

**Tests:** 23 era_anchor tests pass (up from 18 — added 5 gate tests). Full suite 566 passing.

**Status:** SHIPPED. Awaiting 3 cycles of empirical confirmation. **May 9 update:** 0/3 drafts used era anchors (first cycle of post-gate data — no record-type drafts in this batch, so strict comparison is difficult, but the absence of era anchors in a mixed batch is consistent with the gate). 1 of 3 confirmation cycles complete. 2 more cycles needed before promoting to Resolved.

### P4 — Add Wodehouse rule top-of-SYSTEM_PROMPT

**Observed:** Wodehouse-rule violations are the single most predictive failure mode
across every corpus cycle. Drafts that try too hard (restate-padding, explicit-gap
math, poetry-attempt closers, authority-gloss after punchline) grade D–C regardless
of mechanics. Drafts that don't try grade B+/A- regardless of structure. May 9 [2]
Phoenix EHW: "NWS rates the risk as Major." appended after "May, not July." — same
topology as restate-padding ([5] Bukit Rahman Putra) and gap-math ([2] Mexico City,
[10] Petaling Jaya). Bot adds an extra beat after the punchline because it doesn't
trust the punchline alone.

**Cycles observed:** Apr 24, Apr 25, Apr 27, Apr 29, May 9 (5 of 5 corpus cycles —
every single batch has had a Wodehouse violation).
**Last seen:** May 9.
**Proposed fix:** add as rule #0 (above the existing top section) in
`src/two_bot/prompts/writer_prompt.py` (**NOT** `generator.py` — dead since
2026-05-04):

> 0. **DON'T SOUND LIKE YOU'RE TRYING.** The data is already extraordinary; the
> voice is its straight man. The Wodehouse rule: trying too hard breaks the spell.
> Specific violations to avoid: approximation when exact is available ("nearly 3
> degrees" when it's 2.7F), restate-padding ("The new high: 94.5F. The old one:
> 93.7F." after the data was given), poetry-attempt closers ("pointed at the sky"),
> authority-gloss after a punchline ("NWS rates the risk as Major." after "May, not
> July." — this tells the reader how to feel instead of letting the data show it).
> All show effort; all kill the joke before it lands.

**Expected impact:** highest-leverage prompt change in the active stack. Five cycles
of evidence, zero false negatives — every batch has had at least one violation.
Eliminating this pattern moves several C+/B- drafts to B without any other change.

**Status:** drafted. Awaiting human implementation. Implement in `writer_prompt.py`.

### P5 — Add stranded-mechanic warning to prompt

**Observed:** Apr 27 drafts [3] (*"pointed at the sky"*), [4] (*"from a forest"*),
[12] (*"That was 6 months ago"*) — real humor moves stranded inside throat-clearing.
May 9 [2] — "May, not July." is a genuine idiom-flip closer, then overridden by
"NWS rates the risk as Major." The mechanic lands; the surrounding text buries it.
May 9 [3] — "May 9th." deployed as a closer by shape-matching the "It is April 26."
pattern without the incongruity that makes the move land (date-as-punchline only
works when the date names the mismatch; here it names nothing).

**Cycles observed:** Apr 27, May 9 (2 cycles).
**Last seen:** May 9.
**Proposed fix:** add to the general prompt section in
`src/two_bot/prompts/writer_prompt.py` (**NOT** `_CATEGORY_PROMPTS["fire"]` in
`generator.py` — dead since 2026-05-04):

> If you write a punchline, leave it alone. Don't pre-explain it, don't
> post-explain it, don't append an authority rating after it. The data is the setup.
> The closer is the punchline. No math out loud. And only use a date-as-closer when
> the date names a violation — "It is April." works for a Mali fire because April
> is the wrong season; "May 9th." doesn't work as a Phoenix heat closer because May
> in Phoenix is expected to be hot.

**Expected impact:** targets the two distinct failure patterns in this batch — the
override-after-punchline failure ([2]) and the shape-match-without-logic failure ([3]).

**Status:** drafted. Awaiting human implementation.

### P6 — Name humor moves as available tools (not requirements)

**Observed:** SYSTEM_PROMPT names some moves but doesn't enumerate the full mechanic
palette. Writer reaches for whichever moves are explicitly named; unnamed mechanics
get used inconsistently.

**Cycles observed:** Apr 25, Apr 27 (era anchors over-deployed because they were the
most-explicit move in the prompt).
**Last seen:** Apr 27.
**Proposed fix:** add a "Voice moves available" section in
`src/two_bot/prompts/writer_prompt.py`. List: comic triple (period-stop), idiom-flip
(Steven Wright), understatement closer (British dry), period-and-restate (Anchorage
move), deadpan delivery, accelerating-warming, era anchor, ecosystem-specific
specificity. Conclude: *"None of these are mandatory. When the number alone is
striking, deliver the data plainly. Forced humor breaks the spell."*

**Expected impact:** richer move palette → more variety across drafts → less
convergence on easy moves (era anchors, authority-gloss).

**Status:** drafted. Awaiting human implementation. Note: P4 should ship first —
naming more moves is less useful if the Wodehouse rule violation pattern persists.

### P2 — Widen plant-comparison regex adjective allowlist

**Observed:** Apr 27 draft [4] (re-graded D) used *"a commercial nuclear reactor
outputs around 3,000 MW"* — the existing regex misses this because "commercial" isn't
in the adjective allowlist (`typical|standard|average|large|small|usual`).

**Cycles observed:** Apr 27 (1 draft).
**Last seen:** Apr 27.
**Note:** 2 cycles without re-observation (Apr 29, May 9). One more cycle without
evidence → retires to archive.
**Proposed fix:** add `commercial|industrial|mid-sized|high-capacity` to the adjective
allowlist in `src/two_bot/` safety layer (**NOT** `generator.py::_STOCK_FORMULA_PATTERNS`
— dead since 2026-05-04; trace the live regex path before implementing).

**Expected impact:** kills variant plant-comparison openers. Per-user direction (Apr
27): evaluator-rewrite bypass is intentional; this regex catches writer-side only.

**Status:** ready to implement. Awaiting human greenlight. Low priority until
re-observed.

### P3 — Widen opener-formula verb list (or rewrite as shape match)

**Observed:** Apr 27 draft [11] (D) used *"A single wildfire in central India is
**pushing** 297 MW"* — `pushing` isn't in the regex's verb allowlist.

**Cycles observed:** Apr 27 (1 draft).
**Last seen:** Apr 27.
**Note:** 2 cycles without re-observation (Apr 29, May 9). One more cycle without
evidence → retires to archive. (No fire drafts in May 9 batch, so absence is
inconclusive for this fire-specific pattern.)
**Proposed fix:** two options — (a) add common synonyms (`pushing | spewing | pumping
out | throwing off | sending up`) — incremental. (b) rewrite the regex to match shape
rather than verb (`is\s+\w+(?:ing|s)\s+\d`) — structural; needs false-positive
analysis. Implement in the live safety layer, **not** `generator.py`.

**Status:** decision point — (a) tactical or (b) structural. Awaiting human direction.
Low priority until re-observed.

## Awaiting evidence

These need more cycles before promotion to active proposals or retirement.

### A1 — Era_anchors prune impact (Apr 26)

43 politically-charged / US-centric / mass-tragedy entries removed from `data/era_anchors.json` on 2026-04-26. The Apr 27 cycle had ONE draft that used a politically-charged anchor (Jacobabad / Elon Musk) — that anchor is no longer in the file. Whether the prune actually eliminates political/US-centric leakage from records needs the next cycle to confirm.

**Watch for:** record drafts that use era anchors. Note which year + which anchor. Compare against current `era_anchors.json`. If any anchor used isn't in the current file, that's a curation regression — different fix needed.

### A2 — Voice engine v2.5 sample-size fragility

Apr 25 corpus = 7 drafts (43% A-rate). Apr 27 corpus = 11 drafts (9% A-rate). Both small. The Apr 27 regression may be small-sample noise OR a real pattern. Need 3-4 more cycles at >15 drafts each to know.

**Watch for:** A-rate stability across larger corpora. If A-rate stays in 30-50% range over 3+ cycles, voice engine v2.5 is the new baseline. If it stays at 9-15%, v2.5 didn't generalize.

## Resolved (archive)

History of fixes that landed and held — added to this section by the daily agent when a previously-active failure mode no longer appears in a corpus for 3+ consecutive cycles. **Empty for now.**

## Daily agent runbook

The recurring grading agent fires every day at 15:00 UTC (8 AM Pacific PDT). Its job is to refine THIS plan, not implement. Per-run protocol:

1. Read these docs (the framework):
   - `docs/IMPROVEMENT_PLAN.md` (this doc — the active state)
   - `docs/DRAFT_CORPUS.md` (longitudinal grading archive)
   - `docs/QUALITY_TREND.md` (A-rate-by-cycle metric)
   - `brand/HUMOR_RESEARCH.md` (humor theory + voice mechanics)
   - `brand/VOICE.md` (voice spec)
   - `BRIEFING.md` (project state)

2. Pull pending drafts from Gist `06c02c97ffc0d11458687f1ed998d9e5`.
3. Grade each draft on the A-F rubric matching the corpus methodology.
4. Apply the humor-research lens (named mechanic operating, Wodehouse rule, stranded mechanics, Sonnet-rewrite-bypass NOTE: intentional per user).
5. Append a new dated section to `docs/DRAFT_CORPUS.md` (top of file, just below the header).
6. Append a new row to `docs/QUALITY_TREND.md` A-rate table.
7. **Refine THIS plan** (`docs/IMPROVEMENT_PLAN.md`):
   - For each active proposal, if a new failure was observed → increment "Cycles observed" count, update "Last seen" date.
   - If a new failure mode emerged that doesn't fit existing proposals → add new proposal with full template (Observed / Cycles / Last seen / Proposed fix / Expected impact / Status).
   - If an active proposal hasn't been observed for 3+ cycles → move it to "Resolved (archive)" with a one-line note.
   - Re-order active proposals by current leverage (observation count × recency).
8. Bulk-reject any pending drafts older than 48 hours that contain real-time-baked content (per the 2026-04-26 staleness policy).
9. Commit to a feature branch `daily-plan-YYYY-MM-DD`, push, open a PR titled "Daily plan refinement YYYY-MM-DD".
10. Print to stdout: A-rate, gap from bar, top 3 active proposals (numbered).

**Hard constraints:**
- DO NOT push to main. Branch + PR only.
- DO NOT modify code (`src/**`, `tests/**`).
- DO NOT modify spec docs (`brand/VOICE.md`, `brand/MESSAGING_ARCHITECTURE.md`, `brand/HUMOR_RESEARCH.md`, `brand/EXEMPLARS.md`, `brand/VIRALITY_RESEARCH.md`).
- DO NOT modify `data/era_anchors.json` content — only the `audit_history` field in `_meta` if logging.
- DO NOT modify regex (`_STOCK_FORMULA_PATTERNS`) or any prompt strings.
- DO NOT propose architectural changes (new modules, tool swaps, new data sources).
- DO NOT propose Sonnet-evaluator-rewrite bypass — user has confirmed (2026-04-27) it's intentional design.
- DO NOT skip a run because the queue is empty — append a "no fresh drafts" entry to the corpus instead, with a note on why this might have happened (cycles haven't fired, all auto-published, etc.).

**Allowed file edits:**
- `docs/DRAFT_CORPUS.md` (append new sections)
- `docs/QUALITY_TREND.md` (append rows)
- `docs/IMPROVEMENT_PLAN.md` (refine in place)
- Gist state (mark stale drafts as rejected)

## How the human operator uses this plan

- **Read on a schedule** (when a daily PR lands): scan the active-proposals top 3, pick what to implement.
- **Implement together with Claude in a session.** Reference this plan; the proposal entry has the full fix outlined. Move the entry to "Resolved" once the fix ships and the next 3 cycles confirm the failure mode is gone.
- **Override the plan when you have better information.** The daily agent works on what the corpus shows. If you see something the corpus hasn't surfaced yet, add it as a proposal directly (or override priorities).
- **Don't merge daily PRs blindly.** They're docs only, but bad observations can poison future runs. Skim before merging.
