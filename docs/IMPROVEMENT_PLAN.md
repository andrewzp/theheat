# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

## Current state

| | |
|---|---|
| Bot commit | `b82b844` (two-bot port + docs sweep) |
| Architecture | **Two-bot LIVE** (PR #25, `00f621a`): every tweet written by Claude Sonnet 4.6 via intern → writer → claim-extractor → fact-check → memory. `voice/generator.py` bypassed. |
| Active writer prompt | `src/two_bot/prompts/writer_prompt.py::WRITER_SYSTEM_PROMPT` |
| Last cycle A-rate | 0% (Apr 29, 0 of 3) — no new data 2026-05-04 (Gist inaccessible) |
| Resumption bar | majority A (>50%) sustained |
| Gap | 50 percentage points (last measured) |
| Posting | paused until bar cleared |

## Active proposals

Ordered by leverage = (cycles observed) × (recency factor). Most-evidenced + most-recent
goes to P1. **As of 2026-05-04, all proposals target `src/two_bot/prompts/writer_prompt.py::
WRITER_SYSTEM_PROMPT` — the live writer in the new two-bot architecture. Old proposals
targeting `voice/generator.py` are resolved or archived below.**

### P1 — Era-anchor frequency ungated in new architecture (reverted by two-bot port)

**Observed:** 3 of 3 records used era anchors on Apr 25, 5 of 5 on Apr 27, 3 of 3 on
Apr 29 — three consecutive cycles at 100% deployment. The 1-in-10 gate shipped Apr 29
in `voice/generator.py` (`_era_anchor_should_fire`) is now bypassed by the two-bot port.
The new writer prompt tracks `used_era_anchors` in the memory slice (prevents reuse of
the *same* anchor) but imposes no frequency cap. Sonnet can use a fresh era anchor on
every record signal — 100% deployment returns, just with different anchors each time.

**Cycles observed:** Apr 25, Apr 27, Apr 29 (3 cycles, 100% deployment each in old system).
**Last seen:** Apr 29 (pattern in old system; new system untested but mechanism persists).

**Proposed fix:** add to `WRITER_SYSTEM_PROMPT` (in the angle-selection section, after the
three angle bullets):

> Era anchors are ONE specificity vehicle among several. Do not use one for every record
> signal — across the account's tweet history they become the formula they were meant to
> escape. Other vehicles equally valid: recency framing ("set just last year in 2024"),
> accelerating-warming ("hottest two Aprils in the archive: back to back"), place identity
> ("Anchorage"), absolute scale (the number alone when it's striking), ecosystem context
> ("the monsoon that extinguishes these fires is still weeks away"). Vary across signals.

**Expected impact:** same as original P1 — drives specificity variety, prevents era-anchor
convergence. Higher impact in new system because Sonnet's training skews toward cultural
references as an easy elaboration move.

**Status:** fix drafted. Target updated from `voice/generator.py` to `WRITER_SYSTEM_PROMPT`.
Awaiting human implementation.

### P2 — Named humor mechanics absent from writer prompt (formerly P6, reframed)

**Observed:** A-grade drafts across all corpus cycles operated on specific named mechanics:
comic triple (Apr 27 [9] Mali), idiom-flip (Apr 25 [1] NSW, "used to know when to quit"),
understatement closer ("It's April"), period-and-restate (Apr 24 [31] Chicago), accelerating-
warming (Apr 25 [3] Navi Mumbai). B-range drafts that varied mechanics outperformed those
that defaulted to a single move. The single strongest predictor of A-grade was mechanic
variety across a cycle.

**Cycles observed:** Apr 25, Apr 27 (era anchors over-deployed because they were the most-
explicit move in the old prompt; same dynamic applies to the new prompt's "rarity, scale,
context" list, which is data-centric but doesn't name humor mechanics).
**Last seen:** Apr 27 (old system; mechanism applies to new prompt architecture).

**Proposed fix:** add a "Voice moves" section to `WRITER_SYSTEM_PROMPT` (after the three
angle bullets, with era-anchor frequency guidance from P1):

> **Voice moves available (one of these, or none):** comic triple (plain sentences ending
> in a period-stop restatement: "It is May."), Steven Wright idiom-flip (take a familiar
> phrase and alter the ending: "the fire season used to know when to quit"), British
> understatement (flatten the language so the magnitude shows through: "a slightly busy
> day for the Sahel"), period-and-restate (name a place or number, then restate it alone:
> "Anchorage."), accelerating-warming (two consecutive records showing acceleration),
> ecosystem-specificity (the context that makes an otherwise mid number extreme: elevation,
> dry-season timing, monsoon calendar). None of these are mandatory. When the number alone
> is striking, present the data plainly. Forced humor breaks the spell.

**Expected impact:** Sonnet has named mechanics to reach for → more variety across drafts →
less convergence on one move (era anchors under old system; "rarity" framing under new one).

**Status:** drafted. Awaiting human implementation in `WRITER_SYSTEM_PROMPT`.

### P3 — Earned editorial heat not explicitly permitted in writer prompt (new)

**Observed:** `brand/VOICE.md` explicitly permits ALL-CAPS openers for elite signals
("ALL-CAPS openers are allowed when the data warrants the highest tier of the genre").
`voice/generator.py` SYSTEM_PROMPT #2 (now bypassed) enforced this. The new
`WRITER_SYSTEM_PROMPT` frames the voice as "Economist correspondent: plain-spoken
authority, wry without precious" — implying restraint. There is no explicit permission
for ALL-CAPS on all-time records, country-archive records, or anomalies ≥18°C. The
corpus's A-grade drafts used earned editorial heat sparingly but effectively (Apr 25 [6]
Mali "HOT season" — A-). Without the explicit permission, Sonnet may produce competent
but consistently flat copy on elite signals.

**Cycles observed:** 0 (preventive proposal; two-bot architecture is untested).
**Last seen:** N/A.

**Proposed fix:** add to `WRITER_SYSTEM_PROMPT` hard rules:

> CAPS for emphasis are allowed. ALL-CAPS openers are permitted — and recommended — for
> elite signals (all-time records in the archive, country-wide archive peaks, anomalies
> ≥18°C above normal) when the data backs the editorial weight. Reserve this for signals
> where the score or context confirms genuine extremity. If every tweet uses ALL-CAPS,
> none do.

**Expected impact:** unlocks the earned-heat move for the top 5-10% of signals where it
drives engagement, while keeping the explicit "reserve this" discipline that prevents
inflation.

**Status:** new proposal. Awaiting first empirical cycle on two-bot output; then human
implementation if the pattern (flat copy on elite signals) appears.

### P4 — Wodehouse partial gap: "approximation when exact is available" (formerly P4, scope narrowed)

**Observed:** The new `WRITER_SYSTEM_PROMPT` correctly bans restate-padding, poetry-attempt
closers, and pre/post-explain punchlines. Remaining gap: "approximation when exact is
available." Apr 27 [14] Manchester used "nearly 3 degrees" when the exact figure (2.7F)
was in the bundle. Apr 29 [2] Mexico City used "that gap is 4.5 degrees" — explicit-gap
math the reader could do. Both were flagged as Wodehouse violations in corpus review.
Neither violation is banned in the new writer prompt.

**Cycles observed:** Apr 24, Apr 25, Apr 27, Apr 29 for Wodehouse overall (consistent
across all corpus cycles). Approximation-specific: Apr 27 [14], Apr 29 [2].
**Last seen:** Apr 29.

**Proposed fix:** add to `WRITER_SYSTEM_PROMPT` hard rules:

> Use exact numbers when given. "Nearly 3 degrees" when the bundle has 2.7F is
> approximation-when-exact — a Wodehouse violation. "That gap is 4.5 degrees" after
> stating both temperatures is redundant math — the reader can subtract.

**Expected impact:** closes the one remaining Wodehouse gap not already addressed by the
new prompt. Moves several B drafts to B+/A- without structural changes.

**Status:** drafted. Awaiting human implementation in `WRITER_SYSTEM_PROMPT`.

## Awaiting evidence

These need more cycles before promotion to active proposals or retirement.

### A1 — Political-anchor leakage from Sonnet training (formerly "era_anchors prune impact")

43 politically-charged entries removed from `data/era_anchors.json` on 2026-04-26.
**Architecture update (2026-05-04):** `data/era_anchors.json` is no longer referenced in
the new pipeline. Sonnet picks era anchors from its training knowledge without consulting
the curated file. The Apr 26 prune has no effect on the new architecture. The underlying
risk — politically-charged era anchors surfacing in drafts — persists if Sonnet reaches
for entries like "Elon Musk bought Twitter" (2022), "Trump won the US election" (2024), or
"Capitol riot" (2021) from training.

**Watch for:** first batch of Sonnet-generated record drafts that use era anchors. Note
exact phrasing. If any era anchor references political events, divisive figures, or mass
tragedies → add an explicit political-anchor ban to `WRITER_SYSTEM_PROMPT`.

### A2 — Two-bot baseline (first empirical cycle)

No Sonnet-generated drafts have been graded yet. The first cycle of two-bot output is the
new baseline — the equivalent of the Apr 24 "fire template fatigue era" corpus. Cannot
predict whether Sonnet under `WRITER_SYSTEM_PROMPT` will hit 0%, 43%, or higher A-rate on
first pass. The prompt was written with corpus-informed bans; the gaps (P1–P4 above) are
the plausible failure modes.

**Watch for:** A-rate on first 10+ graded drafts. Grade distribution by signal type (are
fire drafts weaker than records, as in old system?). Mechanic variety (does Sonnet converge
on one move, or range across the palette?). Era-anchor deployment rate on records.

## Resolved (archive)

History of fixes that landed and held — or proposals resolved by architectural change.

### [ARCH-RESOLVED 2026-05-04] Old P2 — Plant-comparison regex adjective allowlist

`voice/generator.py::_STOCK_FORMULA_PATTERNS` was proposed for widening. The new
`WRITER_SYSTEM_PROMPT` explicitly bans plant comparisons with the full extended adjective
list: "never compare a fire's MW to a typical/standard/average/large/small/commercial/
industrial/mid-sized/high-capacity/usual nuclear/coal/gas/power plant/reactor." The
regex target is bypassed; the failure mode is addressed at the prompt level.

### [ARCH-RESOLVED 2026-05-04] Old P3 — Opener-formula verb list

`_STOCK_FORMULA_PATTERNS` verb allowlist proposed for widening. The new
`WRITER_SYSTEM_PROMPT` bans throat-clearing openers structurally: "No throat-clearing
openers. ('A wildfire in X is putting out N MW of radiative power.')" The shape is banned
regardless of verb. Regex target is bypassed.

### [ARCH-RESOLVED 2026-05-04] Old P5 — Stranded-mechanic warning to fire prompt addendum

`_CATEGORY_PROMPTS["fire"]` addendum proposed. The new `WRITER_SYSTEM_PROMPT` addresses
this at the top level: "Do not pre-explain or post-explain a punch line." + "No throat-
clearing openers." + "No poetry-attempt closers." The fire-specific addendum target is
bypassed; the structural constraint is now global.

### [ARCH-SUPERSEDED 2026-05-04] Old P1 — Era anchors parked at 1-in-10 (voice engine v3)

Shipped Apr 29 in `voice/generator.py` (`_era_anchor_should_fire`, deterministic 1-in-10
gate). Superseded by two-bot port: the gate module is on the bypassed path. The underlying
problem (era-anchor frequency convergence) is reactivated as new P1 targeting
`WRITER_SYSTEM_PROMPT`.

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
