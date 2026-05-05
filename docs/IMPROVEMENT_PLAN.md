# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

## Current state

| | |
|---|---|
| Bot commit | `00f621a9` (two-bot port: Sonnet 4.6 prose writer, PR #25) |
| Voice engine version | two-bot: Sonnet 4.6 (intern→writer→claim-extractor→fact-check→memory) + Gemini Flash (structured JSON only). `generator.py` retired from live path. |
| Last cycle A-rate | N/A (May 5, 0 drafts — empty queue, first day post two-bot port) |
| Last graded A-rate | 0% (Apr 29, 0 of 3) |
| Resumption bar | majority A (>50%) sustained |
| Gap | 50 points (last real data Apr 29; two-bot baseline not yet established) |
| Posting | paused until bar cleared |
| Proposal status | ALL active proposals (P1–P6) target `generator.py`, now dead code. P7 is the blocking dependency. |

## Active proposals

Ordered by leverage. Each entry tracks: observation count (cycles where the failure mode appeared), last seen, proposed fix, expected impact, status.

**NOTE (2026-05-05):** All proposals P1–P6 were written against `src/voice/generator.py`. That file is now dead code — the two-bot port (PR #25, `00f621a9`, 2026-05-04) means every draft is written by Claude Sonnet 4.6 instead of Gemini Flash, and `generator.py` is no longer on the live signal path. P7 (below) is the blocking dependency before any P1–P6 fix can be implemented. Ordering below reflects inherent voice leverage, not current implementability.

---

### P7 — Retarget all voice proposals to two-bot Sonnet prompts — **BLOCKING**

**Observed:** 2026-05-05 grading run confirmed `generator.py` is retired from live path (BRIEFING.md, commit `00f621a9` PR #25). All proposals P1–P6 specify fix targets in `generator.py::SYSTEM_PROMPT`, `_CATEGORY_PROMPTS`, `_STOCK_FORMULA_PATTERNS`, or `_era_anchor_should_fire` — none of which are called on any live draft.

**Cycles observed:** 1 (May 5 — structural discovery, not a voice failure mode per se).
**Last seen:** May 5.

**Proposed fix:** Before implementing any P1–P6 fix, the human operator needs to:
1. Identify the Sonnet two-bot equivalent of each target: the intern prompt, writer prompt, or any per-signal-type prompt addenda in the new pipeline that correspond to `SYSTEM_PROMPT` / `_CATEGORY_PROMPTS`.
2. Confirm whether the era-anchor gate (`_era_anchor_should_fire` in `generator.py`) is replicated in the new pipeline or was silently dropped. If dropped, era-anchor over-deployment may resume under Sonnet.
3. Confirm whether `_STOCK_FORMULA_PATTERNS` (the banned-opener regex) is applied to Sonnet output — if not, the banned opener and plant-comparison failures could resurface under the new writer.
4. Once the new prompt files are identified, retarget P2–P6 fixes to the correct files and update proposal fix descriptions accordingly.

**Expected impact:** Unblocks the entire active proposal stack. Without this, no proposal can be implemented even if evidence is clear.

**Status:** CRITICAL — blocking. Assign to human operator for next implementation session.

---

### ~~P1~~ — Era anchors parked at 1-in-10 — **SHIPPED 2026-04-29 — NEEDS TWO-BOT VERIFICATION**

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

**Status:** SHIPPED into `generator.py` (Apr 29). However: `generator.py` is now dead code per the May 4 two-bot port. The era-anchor gate (`_era_anchor_should_fire`), the `_era_anchor_hint` rewrite, and the vehicle-agnostic SYSTEM_PROMPT all live in `generator.py` and are NOT active on the live draft path. **The gate may not be protecting the two-bot pipeline from era-anchor over-deployment.** Per P7: verify whether the two-bot Sonnet prompts include equivalent era-anchor steering before marking P1 resolved. Cannot advance to "Resolved" until confirmed.

### P2 — Widen plant-comparison regex adjective allowlist

**Observed:** Apr 27 draft [4] (re-graded D) used *"a commercial nuclear reactor outputs around 3,000 MW"* — the existing regex misses this because "commercial" isn't in the adjective allowlist (`typical|standard|average|large|small|usual`).

**Cycles observed:** Apr 27 (1 draft).
**Last seen:** Apr 27.
**Proposed fix:** add `commercial|industrial|mid-sized|high-capacity` to the adjective allowlist in `src/voice/generator.py::_STOCK_FORMULA_PATTERNS`. OR drop the adjective slot entirely (regex matches plant comparison regardless of adjective).

**Expected impact:** kills variant plant-comparison openers at parse time. Pure tactical; corpus-grounded. Note: per-user direction (Apr 27), evaluator-rewrite path bypass is intentional, so this regex catches Gemini-side only. **With two-bot port, Gemini no longer generates prose — the regex fix would need to be retargeted to wherever banned-opener detection runs in the new pipeline (likely `safety.py` or a Sonnet prompt constraint).**

**Status:** BLOCKED pending P7 retargeting. Was: "ready to implement, awaiting human greenlight." Now: identify new target first.

### P3 — Widen opener-formula verb list (or rewrite as shape match)

**Observed:** Apr 27 draft [11] (D) used *"A single wildfire in central India is **pushing** 297 MW"* — `pushing` isn't in the regex's verb allowlist (`radiating | releasing | generating | putting out | emitting | producing`).

**Cycles observed:** Apr 27 (1 draft, but the pattern "Gemini finds new verbs once known ones are blocked" is structural).
**Last seen:** Apr 27.
**Proposed fix:** two options — (a) add common synonyms (`pushing | spewing | pumping out | throwing off | sending up`) — incremental, ongoing maintenance. (b) rewrite the regex to match shape rather than verb (`is\s+\w+(?:ing|s)\s+\d`) — bigger blast radius, risk of false positives.

**Expected impact (a):** blocks the named variants. May surface new ones next cycle.
**Expected impact (b):** structural fix; needs false-positive analysis before shipping.

**Status:** BLOCKED pending P7 retargeting. Was: "decision point — pick (a) tactical or (b) structural." Now: both options target `generator.py::_STOCK_FORMULA_PATTERNS`, which is dead code. Retarget to the correct file in the two-bot pipeline first.

### P4 — Add Wodehouse rule top-of-SYSTEM_PROMPT

**Observed:** humor-lens evaluation (Apr 27 corpus) found Wodehouse-rule violations are the single most predictive failure mode. Drafts that try too hard ("pointed at the sky" / "nearly 3 degrees" approximation / restate-padding) graded D-/C+/B regardless of mechanics. Drafts that don't try graded B+/A- regardless. Apr 29 [2] Mexico City repeated the explicit-gap-math violation ("That gap is 4.5 degrees" — same pattern as Apr 27 [10] Petaling Jaya). Two consecutive cycles with the same violation.

**Cycles observed:** Apr 24, Apr 25, Apr 27, Apr 29 (consistent across all corpus cycles).
**Last seen:** Apr 29.
**Proposed fix:** add as rule #0 (above the existing "WHAT MAKES A TWEET VIRAL" section) in `src/voice/generator.py::SYSTEM_PROMPT`:

> 0. **DON'T SOUND LIKE YOU'RE TRYING.** The data is already extraordinary; the voice is its straight man. The Wodehouse rule: trying too hard breaks the spell. Approximation when exact is available ("nearly 3 degrees" when it's 2.7F), restate-padding ("The new high: 94.5F. The old one: 93.7F." after the data was given), poetry-attempt closers ("pointed at the sky") — all show effort, all kill the joke before it lands.

**Expected impact:** highest-leverage prompt change in the proposal stack. Wodehouse violations cluster across grades; eliminating them moves several B drafts to B+/A- without changing anything else.

**Status:** BLOCKED pending P7 retargeting. Was: "drafted, awaiting human implementation." Proposed fix targets `src/voice/generator.py::SYSTEM_PROMPT`, dead code. The Wodehouse rule text itself remains valid — it just needs to go into the Sonnet writer prompt in the two-bot pipeline instead.

### P5 — Add stranded-mechanic warning to fire prompt addendum

**Observed:** Apr 27 drafts [3] (*"pointed at the sky"*), [4] (*"from a forest"*), and [12] (*"That was 6 months ago"*) all contain real humor moves stranded inside throat-clearing prose or over-explanation. The mechanics work; the surrounding text kills them.

**Cycles observed:** Apr 27 (3 drafts).
**Last seen:** Apr 27.
**Proposed fix:** add to `_CATEGORY_PROMPTS["fire"]`:

> If you write a punchline, leave it alone. Don't pre-explain it ("for reference, a power plant runs at..."), don't post-explain it ("that's roughly one-eighth of that"), don't restate the data ("The new high: X. The old one: Y."). The data is the setup. The closer is the punchline. No math out loud.

**Expected impact:** specifically targets the failure pattern that drove the Apr 27 fire regression. Should reduce stranded-mechanic D drafts.

**Status:** BLOCKED pending P7 retargeting. Was: "drafted, awaiting human implementation." Proposed fix targets `_CATEGORY_PROMPTS["fire"]` in `generator.py`, dead code. The no-math-out-loud, leave-the-punchline-alone principle is still valid and should transfer verbatim into the Sonnet fire-signal writer prompt.

### P6 — Name humor moves as available tools (not requirements)

**Observed:** SYSTEM_PROMPT names some moves ("HISTORICAL WEIGHT" in #1, "VARY YOUR STRUCTURE" in voice section) but doesn't enumerate the full mechanic palette. Gemini reaches for whichever moves are explicitly named; unnamed mechanics get used inconsistently.

**Cycles observed:** Apr 25, Apr 27 (era anchors over-deployed because they're the most-explicit move in the prompt).
**Last seen:** Apr 27.
**Proposed fix:** add a "Voice moves available" section after the hard rules. List: comic triple (period-stop), idiom-flip (Steven Wright), understatement closer (British dry), period-and-restate (Anchorage move), deadpan delivery, accelerating-warming, era anchor, ecosystem-specific specificity. Conclude: *"None of these are mandatory. When the number alone is striking, deliver the data plainly. Forced humor breaks the spell."*

**Expected impact:** richer move palette → more variety across drafts → less convergence on the easy moves (era anchors, throat-clearing).

**Status:** BLOCKED pending P7 retargeting. Was: "drafted, awaiting human implementation." Proposed fix targets `src/voice/generator.py::SYSTEM_PROMPT`, dead code. The humor-moves-as-palette concept transfers directly to Sonnet writer prompt — the content is valid, the target is wrong.

## Awaiting evidence

These need more cycles before promotion to active proposals or retirement.

### A1 — Era_anchors prune impact (Apr 26) — STATUS UNCLEAR post two-bot port

43 politically-charged / US-centric / mass-tragedy entries removed from `data/era_anchors.json` on 2026-04-26. The Apr 27 cycle had ONE draft that used a politically-charged anchor (Jacobabad / Elon Musk) — that anchor is no longer in the file. Whether the prune actually eliminates political/US-centric leakage from records needs the next cycle to confirm.

**2026-05-05 update:** With the two-bot port, `era_anchors.json` may no longer be used by the live pipeline at all — the old code path that loaded and injected era anchor content was in `generator.py`. Confirm whether the two-bot Sonnet writer has access to `era_anchors.json` or equivalent. If era anchor data isn't injected into Sonnet's context, A1 is moot (and the era-anchor failure mode is automatically resolved by the architecture change).

**Watch for:** whether any Sonnet-drafted record tweets use era anchors at all. If yes, trace whether `era_anchors.json` is being read and injected — and check that the pruned file is the one being used. If no era anchors appear in any Sonnet record drafts, era-anchor failure mode is resolved by architecture.

### A2 — Voice engine sample-size fragility (updated: Sonnet baseline not yet established)

Apr 25 corpus = 7 drafts (43% A-rate). Apr 27 corpus = 11 drafts (9% A-rate). Apr 29 corpus = 3 drafts (0% A-rate). All small. The Apr 27/29 regression had named causes (era-anchor convergence, banned-formula variants). The v2.5 baseline was never clearly established.

**2026-05-05 update:** The sample-size fragility question now applies to the two-bot Sonnet pipeline, not v2.5. The first Sonnet corpus cycle (coming days) is the new baseline. Expect Sonnet output to differ substantially from Gemini's patterns — both the failure modes and the strengths may shift. The Wodehouse-rule and stranded-mechanic failures (P4, P5) may or may not persist under Sonnet; the opener-formula and plant-comparison failures (P2, P3) may not appear at all if Sonnet generates cleaner structure by default.

**Watch for:** A-rate on first 2-3 Sonnet corpus cycles. If A-rate is ≥50% immediately, the two-bot port cleared the bar and posting can resume. If A-rate is in the 9-43% Gemini range, the voice failure modes have survived the architecture change and the proposals need retargeting (P7).

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
