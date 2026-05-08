# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

## Current state

| | |
|---|---|
| Bot commit | `d9c84ff` (#47 codex high-severity batch; latest after 10-PR debugging marathon 2026-05-08) |
| Voice engine version | **two-bot v1** — Sonnet 4.6 writer + Gemini Flash fact-checker. `src/voice/generator.py` RETIRED 2026-05-04, no call sites in main.py. All prompt proposals now target `src/two_bot/prompts/writer_prompt.py`. |
| Last cycle A-rate | 0% (Apr 29, 0 of 3) — zero grading cycles Apr 30 through May 7 (pipeline outage) |
| Resumption bar | majority A (>50%) sustained |
| Gap | 50 percentage points (from last graded cycle; first two-bot corpus pending) |
| Posting | paused until bar cleared |

**Architectural note (2026-05-08):** The voice→two-bot port (May 3–4) retired generator.py
and replaced it with a Sonnet 4.6 writer feeding Gemini Flash fact-checking. All active
proposals (P1–P6) previously referenced generator.py code. Implementation targets for P2–P6
have been updated to `src/two_bot/prompts/writer_prompt.py` below. P1's era-anchor gate was
in generator.py and its two-bot successor is unverified — flagged at P1.

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

**Status:** SHIPPED in generator.py (2026-04-29) — **but generator.py is now dead (retired 2026-05-04).** The `_era_anchor_should_fire` gate no longer executes. `src/two_bot/memory.py` is described as tracking "era anchors" and may be the successor mechanism, but rate-cap logic is unverified. First post-fix two-bot cycle is the diagnostic. If era anchors revert to 100% deployment, P1 is effectively un-shipped and the gate needs to be re-implemented in `src/two_bot/prompts/writer_prompt.py` or `memory.py`.

### P2 — Add Wodehouse rule top-of-prompt *(was P4; promoted: 4 cycles, highest leverage)*

**Observed:** humor-lens evaluation (Apr 27 corpus) found Wodehouse-rule violations are the
single most predictive failure mode. Drafts that try too hard ("pointed at the sky" / "nearly
3 degrees" approximation / restate-padding) graded D-/C+/B regardless of mechanics. Drafts
that don't try graded B+/A- regardless. Apr 29 [2] Mexico City repeated the explicit-gap-math
violation ("That gap is 4.5 degrees" — same pattern as Apr 27 [10] Petaling Jaya). Consistent
across every graded cycle.

**Cycles observed:** Apr 24, Apr 25, Apr 27, Apr 29 (4 cycles — every graded cycle in the corpus).
**Last seen:** Apr 29.
**Proposed fix:** add as rule #0 (above existing hard rules) in
`src/two_bot/prompts/writer_prompt.py` *(target updated from dead generator.py SYSTEM_PROMPT)*:

> 0. **DON'T SOUND LIKE YOU'RE TRYING.** The data is already extraordinary; the voice is
> its straight man. The Wodehouse rule: trying too hard breaks the spell. Approximation
> when exact is available ("nearly 3 degrees" when it's 2.7F), restate-padding ("The new
> high: 94.5F. The old one: 93.7F." after the data was given), poetry-attempt closers
> ("pointed at the sky") — all show effort, all kill the joke before it lands.

**Expected impact:** highest-leverage prompt change in the stack. Wodehouse violations cluster
across grades; eliminating them moves B drafts to B+/A- without changing structure.

**Status:** drafted. Target file updated to `src/two_bot/prompts/writer_prompt.py`. Awaiting
human verification that the new writer prompt doesn't already include this, then implementation.

### P3 — Name humor moves as available tools (not requirements) *(was P6; 2 cycles)*

**Observed:** The writer's system prompt names some moves but doesn't enumerate the full
mechanic palette. Named mechanics get deployed; unnamed ones appear inconsistently. In the
old pipeline, era anchors were over-deployed because they were the most-explicit move named.
The same convergence risk applies to the two-bot writer prompt.

**Cycles observed:** Apr 25, Apr 27 (era-anchor over-deployment as the proxy signal).
**Last seen:** Apr 27.
**Proposed fix:** add a "Voice moves available" section to `src/two_bot/prompts/writer_prompt.py`
*(target updated from dead generator.py SYSTEM_PROMPT)*. List: comic triple (period-stop),
idiom-flip (Steven Wright), understatement closer (British dry), period-and-restate (Anchorage
move), deadpan delivery, accelerating-warming, era anchor, ecosystem-specific specificity.
Conclude: *"None of these are mandatory. When the number alone is striking, deliver the data
plainly. Forced humor breaks the spell."*

**Expected impact:** richer move palette → more variety across drafts → less convergence on
easy moves.

**Status:** drafted. Target updated to `src/two_bot/prompts/writer_prompt.py`. Awaiting
human verification of current writer prompt content, then implementation.

### P4 — Widen plant-comparison check *(was P2; 1 cycle)*

**Observed:** Apr 27 draft [4] (D) used *"a commercial nuclear reactor outputs around 3,000
MW"* — the existing regex missed it because "commercial" wasn't in the adjective allowlist
(`typical|standard|average|large|small|usual`).

**Cycles observed:** Apr 27 (1 draft).
**Last seen:** Apr 27.
**Proposed fix:** Two-step now that generator.py is dead:
1. **Verify `src/voice/safety.py`** for a plant-comparison regex. If present, add
   `commercial|industrial|mid-sized|high-capacity` to its adjective allowlist (or drop
   the adjective slot entirely). If absent, the check is running nowhere and must be added
   to `safety.py`.
2. **Add as a negative example** in `src/two_bot/prompts/writer_prompt.py`: explicitly
   name "power-plant comparison" as a banned framing, with examples of variants.

*(Original target `src/voice/generator.py::_STOCK_FORMULA_PATTERNS` is dead. `safety.py`
is the correct fallback for parse-time rejection.)*

**Expected impact:** kills plant-comparison openers at the safety layer regardless of
writer choice of adjective.

**Status:** target file updated. Awaiting human verification of safety.py regex coverage,
then implementation.

### P5 — Widen opener-formula verb check *(was P3; 1 cycle)*

**Observed:** Apr 27 draft [11] (D) used *"A single wildfire in central India is **pushing**
297 MW"* — `pushing` wasn't in the verb allowlist (`radiating | releasing | generating |
putting out | emitting | producing`). The underlying pattern — writer finds new verbs once
known ones are blocked — is structural.

**Cycles observed:** Apr 27 (1 draft).
**Last seen:** Apr 27.
**Proposed fix:** Same two-step as P4:
1. **Verify `src/voice/safety.py`** for the opener-formula verb regex. If present, add
   common synonyms (`pushing | spewing | pumping out | throwing off | sending up`), or
   rewrite to match shape (`is\s+\w+(?:ing|s)\s+\d+\s+MW`) to be verb-agnostic.
2. **Add as a negative-example framing** in `src/two_bot/prompts/writer_prompt.py`.

*(Original target `src/voice/generator.py::_STOCK_FORMULA_PATTERNS` is dead.)*

**Expected impact (shape-match):** structural fix; catches new verbs without corpus
observation + deploy cycles. Needs false-positive check before shipping.

**Status:** target updated. Decision point: (a) verb-list extension (tactical) or (b) shape
match (structural). Awaiting human direction + safety.py verification.

### P6 — Add stranded-mechanic warning to fire prompt *(was P5; 1 cycle)*

**Observed:** Apr 27 drafts [3] (*"pointed at the sky"*), [4] (*"from a forest"*), and [12]
(*"That was 6 months ago"*) all contain real humor moves stranded inside throat-clearing or
over-explanation. The mechanics work; surrounding text kills them.

**Cycles observed:** Apr 27 (3 drafts).
**Last seen:** Apr 27.
**Proposed fix:** add to the fire-signal section of `src/two_bot/prompts/writer_prompt.py`
*(target updated from dead `_CATEGORY_PROMPTS["fire"]` in generator.py)*:

> If you write a punchline, leave it alone. Don't pre-explain it ("for reference, a power
> plant runs at..."), don't post-explain it ("that's roughly one-eighth of that"), don't
> restate the data ("The new high: X. The old one: Y."). The data is the setup. The closer
> is the punchline. No math out loud.

**Expected impact:** reduces stranded-mechanic D drafts in fire category.

**Status:** drafted. Target updated to `src/two_bot/prompts/writer_prompt.py`. Awaiting
human implementation.

## Awaiting evidence

These need more cycles before promotion to active proposals or retirement.

### A1 — Era_anchors prune impact (Apr 26)

43 politically-charged / US-centric / mass-tragedy entries removed from `data/era_anchors.json` on 2026-04-26. The Apr 27 cycle had ONE draft that used a politically-charged anchor (Jacobabad / Elon Musk) — that anchor is no longer in the file. Whether the prune actually eliminates political/US-centric leakage from records needs the next cycle to confirm.

**Watch for:** record drafts that use era anchors. Note which year + which anchor. Compare against current `era_anchors.json`. If any anchor used isn't in the current file, that's a curation regression — different fix needed. Also note: the two-bot pipeline writer_prompt.py's era-anchor guidance (if any) may independently surface political-era-anchor risks if the memory.py mechanism passes through `era_anchors.json` content.

### A2 — Voice engine sample-size fragility

Apr 25 corpus = 7 drafts (43% A-rate). Apr 27 = 11 drafts (9%). Apr 29 = 3 drafts (0%). All small. The trend is declining but sample sizes are too thin to distinguish noise from pattern.

**Watch for:** First two-bot cycle corpus at any size. The new writer (Sonnet 4.6) may exhibit different voice baseline than Gemini Flash. If A-rate on first two-bot corpus is ≥30%, treat as a potential reset and watch 3+ cycles. If it opens at <10% with the same failure modes, the failure modes are voice-spec problems, not generator-specific.

### A3 — Two-bot writer voice baseline (new, 2026-05-08)

The two-bot port replaced Gemini Flash (generator) + Sonnet (evaluator) with Sonnet 4.6
(writer) + Gemini Flash (fact-check). This is a qualitatively different model stack. The
Apr 24–29 failure taxonomy (opener formulas, era-anchor over-deployment, Wodehouse
violations) was derived entirely from Gemini-as-writer output. Sonnet may reproduce some
of these; it may exhibit entirely different convergence patterns.

**Watch for:** first two-bot cycle output on all signal types. Key questions — (1) does the
Sonnet writer reach for MW openers and plant comparisons the way Gemini did? (2) does it
over-deploy era anchors without the old gate? (3) does it exhibit Wodehouse violations (try-
hard approximation, restate-padding, math-out-loud) at the same rate? (4) are there NEW
failure modes that didn't appear in the Gemini corpus? First corpus entry is the diagnostic
— do not update proposals P2–P6 until at least one two-bot cycle is graded.

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
