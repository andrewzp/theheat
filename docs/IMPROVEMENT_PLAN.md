# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

## Current state

| | |
|---|---|
| Bot commit | `f321be8` (origin/main) — **NOTE:** Gist run history + draft patterns indicate a two-bot architecture (Claude Sonnet 4.6 writer, Gemini Flash claim-extract/fact-check) has been live since ~May 4 in a later commit; voice generator (`src/voice/generator.py`) may be retired from live path. See A3. |
| Voice engine version | v2.5 per main; Gist evidence suggests two-bot pipeline active since ~May 4 (all alert cycles show drafted=0 despite signals detected) |
| Last cycle A-rate | 0% (Apr 29, 0/3) |
| Resumption bar | majority A (>50%) sustained |
| Gap | 50 percentage points (as of last graded cycle Apr 29) |
| Posting | paused until bar cleared; additionally paused by generation gap |

## Active proposals

Ordered by leverage = (cycles observed) × (recency). Each entry tracks: observation count, last seen, proposed fix, expected impact, status.

**Architectural note (May 6):** Gist run history indicates the two-bot pipeline (Sonnet 4.6 writer) may be live in a later commit. If so, P1 and P4–P6 target `SYSTEM_PROMPT` / `_CATEGORY_PROMPTS` in `src/voice/generator.py` which may be retired from the live path; P2 and P3 target `_STOCK_FORMULA_PATTERNS` (same file). Human operator should confirm which code is active before implementing any proposal. The principles in each proposal remain valid for any AI writer — only the target location changes.

### P4 — Add Wodehouse rule top-of-SYSTEM_PROMPT

**Observed:** Wodehouse-rule violations are the single most predictive failure mode across all graded cycles. Drafts that try too hard ("pointed at the sky" / "nearly 3 degrees" approximation / explicit gap math / restate-padding) graded D-/C+/B regardless of mechanics. Drafts that don't try graded B+/A- regardless. Confirmed across four consecutive cycles:
- Apr 24: poetry-attempt closers ("It is burning") and restate patterns
- Apr 25: "nearly 3 degrees" approximation when exact was available (Manchester)
- Apr 27: [10] Petaling Jaya "That gap is 4.4 degrees" (same explicit-gap pattern)
- Apr 29: [2] Mexico City "That gap is 4.5 degrees" — same pattern, second consecutive repeat

**Cycles observed:** Apr 24, Apr 25, Apr 27, Apr 29 (all four graded cycles).
**Last seen:** Apr 29.
**Proposed fix:** add as rule #0 (above the existing "WHAT MAKES A TWEET VIRAL" section) in `src/voice/generator.py::SYSTEM_PROMPT`:

> 0. **DON'T SOUND LIKE YOU'RE TRYING.** The data is already extraordinary; the voice is its straight man. The Wodehouse rule: trying too hard breaks the spell. Approximation when exact is available ("nearly 3 degrees" when it's 2.7F), restate-padding ("The new high: 94.5F. The old one: 93.7F." after the data was given), explicit gap math ("That gap is 4.5 degrees" — the reader can do this), poetry-attempt closers ("pointed at the sky") — all show effort, all kill the joke before it lands.

If the two-bot architecture is live, the analogous location is the Sonnet writer's system prompt (wherever the writer instructions live in the new pipeline).

**Expected impact:** highest-leverage prompt change in the stack. Wodehouse violations cluster in every graded cycle; eliminating them moves several B drafts to B+/A- without changing structure.

**Status:** drafted. Awaiting human implementation. Target code location to confirm if two-bot is live.

### P1 — Reframe era anchors as one specificity vehicle — ESCALATE TO STRUCTURAL GATE

**Observed:** Era-anchor over-deployment has persisted across every graded record cycle.
- Apr 25: 3/3 records used era anchors
- Apr 27: 5/5 records used era anchors
- Apr 29: 3/3 records used era anchors — third consecutive cycle at 100%

Prompt-only reframing (as currently drafted) has not broken the pattern after two cycles of evidence. Three consecutive cycles at 100% indicates the LLM defaults to era anchors regardless of prompt framing when they're available in the addendum context.

**Cycles observed:** Apr 25, Apr 27, Apr 29 (3 cycles, 100% deployment each).
**Last seen:** Apr 29.

**Proposed fix — escalated from prompt reframe to structural gate:**

Prompt reframe alone (listing vehicles equally) is insufficient evidence suggests. The fix needs a deterministic layer:

Option A (code gate): add a `_era_anchor_should_fire(rate=0.10)` gate seeded by city+date. 90% of calls return a steer-away message that explicitly names the 5 alternative vehicles. 10% of calls return the era anchor content framed as "your 1-in-10 turn." This ensures the distribution in the LLM's context reflects intent, not prompt-text alone.

Option B (addendum rewrite only): rewrite all record-type addenda to list the 6 specificity vehicles equally, and add to `_era_anchor_hint`: *"Era anchors used on every record tweet become the formula they were meant to escape. Pick a different vehicle unless the era anchor is genuinely the most striking move for this data."*

Option A is the structural fix. Option B is lower-risk but lower-impact given 3 cycles of evidence it's insufficient.

**Expected impact (A):** deterministic gate breaks the pattern structurally. Expected era-anchor rate drops to ~10% empirically within 2-3 cycles.

**Status:** escalate to Option A. Awaiting human implementation. If two-bot is live, the gate location shifts to wherever the Sonnet writer receives era-anchor content.

### P6 — Name humor moves as available tools (not requirements)

**Observed:** SYSTEM_PROMPT names some moves ("HISTORICAL WEIGHT" in #1, "VARY YOUR STRUCTURE" in voice section) but doesn't enumerate the full mechanic palette. Gemini reaches for whichever moves are explicitly named; unnamed mechanics get used inconsistently. Era anchors over-deployed because they're the most-explicit move in the prompt.

**Cycles observed:** Apr 25, Apr 27 (2 cycles).
**Last seen:** Apr 27.
**Proposed fix:** add a "Voice moves available" section after the hard rules. List: comic triple (period-stop), idiom-flip (Steven Wright), understatement closer (British dry), period-and-restate (Anchorage move), deadpan delivery, accelerating-warming, era anchor, ecosystem-specific specificity. Conclude: *"None of these are mandatory. When the number alone is striking, deliver the data plainly. Forced humor breaks the spell."*

**Expected impact:** richer move palette → more variety across drafts → less convergence on the easy moves (era anchors, throat-clearing).

**Status:** drafted. Awaiting human implementation. Target code location to confirm if two-bot is live.

### P2 — Widen plant-comparison regex adjective allowlist

**Observed:** Apr 27 draft [4] (re-graded D) used *"a commercial nuclear reactor outputs around 3,000 MW"* — the existing regex misses this because "commercial" isn't in the adjective allowlist (`typical|standard|average|large|small|usual`).

**Cycles observed:** Apr 27 (1 draft).
**Last seen:** Apr 27.
**Proposed fix:** add `commercial|industrial|mid-sized|high-capacity` to the adjective allowlist in `src/voice/generator.py::_STOCK_FORMULA_PATTERNS`. OR drop the adjective slot entirely (regex matches plant comparison regardless of adjective).

**Expected impact:** kills variant plant-comparison openers at parse time. Pure tactical; corpus-grounded. Note: per-user direction (Apr 27), evaluator-rewrite path bypass is intentional, so this regex catches Gemini-side only.

**Status:** ready to implement. Awaiting human greenlight.

### P3 — Widen opener-formula verb list (or rewrite as shape match)

**Observed:** Apr 27 draft [11] (D) used *"A single wildfire in central India is **pushing** 297 MW"* — `pushing` isn't in the regex's verb allowlist (`radiating | releasing | generating | putting out | emitting | producing`).

**Cycles observed:** Apr 27 (1 draft, but the pattern "Gemini finds new verbs once known ones are blocked" is structural).
**Last seen:** Apr 27.
**Proposed fix:** two options — (a) add common synonyms (`pushing | spewing | pumping out | throwing off | sending up`) — incremental, ongoing maintenance. (b) rewrite the regex to match shape rather than verb (`is\s+\w+(?:ing|s)\s+\d`) — bigger blast radius, risk of false positives.

**Expected impact (a):** blocks the named variants. May surface new ones next cycle.
**Expected impact (b):** structural fix; needs false-positive analysis before shipping.

**Status:** decision point — pick (a) tactical or (b) structural. Awaiting human direction.

### P5 — Add stranded-mechanic warning to fire prompt addendum

**Observed:** Apr 27 drafts [3] (*"pointed at the sky"*), [4] (*"from a forest"*), and [12] (*"That was 6 months ago"*) all contain real humor moves stranded inside throat-clearing prose or over-explanation. The mechanics work; the surrounding text kills them.

**Cycles observed:** Apr 27 (3 drafts).
**Last seen:** Apr 27.
**Proposed fix:** add to `_CATEGORY_PROMPTS["fire"]`:

> If you write a punchline, leave it alone. Don't pre-explain it ("for reference, a power plant runs at..."), don't post-explain it ("that's roughly one-eighth of that"), don't restate the data ("The new high: X. The old one: Y."). The data is the setup. The closer is the punchline. No math out loud.

**Expected impact:** specifically targets the failure pattern that drove the Apr 27 fire regression. Should reduce stranded-mechanic D drafts.

**Status:** drafted. Awaiting human implementation. Target code location to confirm if two-bot is live.

## Awaiting evidence

These need more cycles before promotion to active proposals or retirement.

### A1 — Era_anchors prune impact (Apr 26)

43 politically-charged / US-centric / mass-tragedy entries removed from `data/era_anchors.json` on 2026-04-26. The Apr 27 cycle had ONE draft that used a politically-charged anchor (Jacobabad / Elon Musk) — that anchor is no longer in the file. The Apr 29 cycle's three era-anchor drafts (Cuenca/2011, Mexico City/2017, Jacksonville/2002) used non-political cultural anchors. No political-anchor regression observed in Apr 29.

**Status:** positive signal — prune appears to have worked for political anchors. The problem that remains is not political content but volume (100% deployment, not 100% inappropriate anchors).

**Watch for:** any politically-charged or divisive anchor appearing in future cycles. If none appear in next 3 cycles, A1 can be resolved/archived.

### A2 — Voice engine v2.5 sample-size fragility

Apr 25 corpus = 7 drafts (43% A-rate). Apr 27 corpus = 11 drafts (9% A-rate). Apr 29 corpus = 3 drafts (0% A-rate). All small. The generation gap (May 4 onward) means this question is now moot for the Gemini-based pipeline — the two-bot architecture has superseded v2.5.

**Status:** superseded by A3. If the two-bot pipeline stabilizes and resumes generation, A-rate stability analysis restarts from the new baseline.

### A3 — Two-bot architecture transition and output quality baseline (May 2026)

Gist run history shows all alert cycles from ~May 4 onward have `drafted_count=0` despite signals being detected and promoted above threshold. This indicates a pipeline break or major change at the generation step following a code update. BRIEFING.md in a later commit confirms a two-bot architecture (Sonnet 4.6 writer + Gemini Flash fact-check) was ported as PR #25. The voice generator is no longer in the live signal path per that commit.

**Block on:** human operator must investigate and resolve the generation gap before any quality data can flow.

**Watch for — once generation resumes:**
- **Era-anchor rate**: P1 gate (if shipped) in generator.py may not apply to Sonnet writer. What does Sonnet produce naturally on records?
- **Wodehouse violations (P4)**: do explicit-gap-math and restate-padding appear in Sonnet output?
- **Formula openers (P2/P3)**: the regex is in generator.py. If Sonnet writer generates "A wildfire burning in X is radiating..." shapes, there's no regex gate unless it was ported or the new pipeline adds equivalent filtering.
- **Stranded mechanics (P5)**: whether or not the fire prompt addendum was ported, does Sonnet strand punchlines in throat-clearing?
- **New failure modes**: Sonnet may have entirely different voice failure modes. First graded cycle under the new system is the baseline.

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
