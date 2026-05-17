# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

## Current state

| | |
|---|---|
| Bot commit | `dc25f7b` (PR #121 — JSON-parse retry for fact_check + critic; post-overnight-wave stack including Plans A-F + F2 + F3 critic + threshold registry + monolith decomposition) |
| Voice engine version | **two-bot + Attenborough/Economist voice + F3 second-pass editorial critic + length+JSON retries** (Sonnet 4.6 writer → Gemini fact-checker → Sonnet F3 critic; `src/voice/generator.py` dead since 2026-05-04; WORLD_KNOWLEDGE widened in PR #119; critic added in PR #120) |
| Last cycle A-rate | **7%** (May 17, 14 drafts: 1 A-, 7 B-range, 6 C-range) |
| Resumption bar | majority A (>50%) sustained |
| Gap | **43 pp** (1/14 A-rate, May 17) |
| Posting | paused until bar cleared |
| Coverage | **638 cities × 180 countries + 23 live data sources** (Plans A-F wave merged 2026-05-15; 9 new sources including Coral Reef Watch DHW, NHC/JTWC cyclones, Copernicus EMS floods, GPM-IMERG precip, NSIDC snow, NAO/AO/PDO, Antarctic ozone) |

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

**Status:** SHIPPED to `generator.py` — but `generator.py` was retired 2026-05-04. The
1-in-10 deterministic gate no longer runs. The two-bot writer has `memory.used_era_anchors`
tracking but no equivalent hard gate. Empirical confirmation of the gate rate is no longer
possible on the current code path. Whether era anchors are over-deployed in two-bot output
cannot be assessed until record drafts reach the pending queue. Move to Resolved when
operator confirms era-anchor logic is either ported to writer_prompt.py or unnecessary.

### ~~P1~~ — Fix station-name normalization: fact_check kills on GHCN suffix labels — **SHIPPED 2026-05-12 (PR #82)**

**Observed:** 2026-05-12 — "Paddock Lake 4 Ne" (Wisconsin) and "Sioux City Ang" (Iowa)
both produce BUNDLE_FACT kills every run because `normalize_station_name()` strips the
direction/distance suffix before the writer sees the bundle, but the raw suffix survives
in bundle fields the fact-checker validates against. Pattern fires three times today on
the same station (once per alerts run). Also observed 2026-05-11 on Sioux City Ang.

**Cycles observed:** May 11, May 12 (2 grading cycles; 5+ individual fact-check kills).
**Last seen:** 2026-05-12.

**Resolution:** Root cause was inside `normalize_station_name` itself, not bundle-builder
plumbing. `_COOP_SUFFIX_RE` required adjacent digit+direction (`1SW`) and missed
space-separated (`4 NE`). Fixed with `\s*` between digit and direction. Plus new
`_MILITARY_SUFFIX_RE = r"\s+ANG$"` for the Air National Guard class (covers Sioux City
ANG). Two regression tests in `tests/test_ghcn.py` cover both failure modes.

**Status:** SHIPPED in PR #82 (`48ee110`). Awaiting empirical confirmation on the next
alerts run that BUNDLE_FACT kills on these stations stop firing.

### ~~P2~~ — Fix fire MW rounding: fact_check kills on decimal truncation — **SHIPPED 2026-05-12 (PR #80)**

**Observed:** 2026-05-11-12 — fact-checker kills fire drafts when writer rounds FRP
values: 480.34 → 480 (BUNDLE_FACT), 547.92 → 548 (BUNDLE_FACT), 301.55 → 301
(BUNDLE_FACT). The fact-checker requires exact numerical match. Also observed: a
fabricated Hoover Dam comparison killed as WORLD_KNOWLEDGE ("roughly what the Hoover Dam
generates" for a 301 MW fire; Hoover ≈ 2,080 MW — off by factor 7). Two separate issues.

**Cycles observed:** May 11, May 12 (2 cycles; multiple kills each).
**Last seen:** 2026-05-12.

**Correction (2026-05-12, post-Codex-review):** the prior version of this plan proposed
telling the writer to round FRP to one decimal and claimed "the fact-checker requires an
exact match within 0.5 MW." Codex's review caught the contradiction:
`src/two_bot/prompts/fact_check_prompt.py` line 9 says *"Verify exact match (number, unit,
date). Mismatches = failure."* — there is **no tolerance rule**. Telling the writer to
emit `480.3 MW` when the bundle carries `480.34` would still BUNDLE_FACT-kill. The fix
has to make the writer's number match the bundle's number exactly, or change the bundle,
or change the fact-checker. Pick one — don't paper over it with a tolerance claim that
the runtime doesn't honor.

**Proposed fix (a — rounding, REVISED):** Round at the **bundle builder**, not at the
writer. In `src/two_bot/intern.py:build_fire_bundle` (line 167), change
`"value": fire.frp` to `"value": round(fire.frp, 1)` (and the same in `raw_signal_dump`
at line 180). The bundle then carries `480.3` as the source of truth; the writer
naturally echoes `480.3 MW`; the fact-checker confirms exact match. No prompt rule
needed, no fact-checker mutation needed, no runtime tolerance bookkeeping. Add a
regression test in `tests/two_bot/test_intern.py` that asserts the FRP `value` field is
rounded to 1 decimal for representative inputs (480.34 → 480.3, 547.92 → 547.9,
301.55 → 301.5 or 301.6 per Python banker's rounding).

  **Why bundle-side rounding wins over the alternatives:**
  - **vs. writer-side rule:** Writer-side rules are fragile under model stochasticity
    (see #76's length-cap retry). The bundle is source-of-truth and never drifts.
  - **vs. fact-check tolerance:** Adding a `±0.5 MW` tolerance to the fact-check prompt
    would mutate runtime behavior, require new voice-regression validation, and
    introduce a soft-equality rule that downstream code may not honor identically. The
    bundle-side fix preserves the "exact match" doctrine cleanly.

**Proposed fix (b — fabrication, unchanged):** Add to the writer prompt's HARD RULES /
bad-examples list: "Do NOT compare fire FRP to a named power plant or dam unless the
comparison's exact MW is provided in the bundle. 'Roughly what [named plant] produces'
is hallucination territory. Observed failure modes: Hoover Dam at full capacity (~2,080
MW) applied to a 301 MW fire; Akosombo Dam at full capacity (~1,020 MW) applied to a
361 MW fire." (This is already partially landed in PR #74's "no self-supplied facility
MW" rule; verify the wording still covers FRP-specifically and tighten if it doesn't.)

**Expected impact:** Bundle-side rounding unlocks every fire draft that's currently
dying on float-precision mismatch. The fabrication rule (already largely in place via
#74) prevents the Hoover/Akosombo class entirely.

**Status:** SHIPPED in PR #80 (`4677869`). Bundle-side rounding in
`src/two_bot/intern.py:build_fire_bundle` — both `headline_metric.value` and
`raw_signal_dump.frp` use `round(fire.frp, 1)`. Five-case regression test in
`tests/two_bot/test_intern.py::test_build_fire_bundle_rounds_frp_to_one_decimal` covers
the three production failures (480.34, 547.92, 301.55) plus banker's-rounding edges.
The writer-prompt no-self-supplied-facility-MW rule landed in PR #74 and remains in
force. Awaiting empirical confirmation on the next fire-bundle alerts cycle.

### ~~P3~~ — Writer fire overcall: add seasonal/calendar context as a verifiable framing — **SHIPPED 2026-05-12 (PR #84)**

**Observed:** 2026-05-11-12 — writer kills fire drafts citing "no historical_context
available; no peer comparison confident enough to use; no verifiable seasonal or rarity
framing without archive data." Two Western Sahel fires (480 MW, 301 MW) and one Siberia
fire (548 MW) died on this basis. The writer knows seasonal context exists ("May fires
in Amur are seasonally plausible") but won't use it without verified archive data.
The old voice engine used seasonal deadpan as world knowledge without archive backing.

**Cycles observed:** May 11, May 12 (2 cycles; 3+ writer self-kills per cycle).
**Last seen:** 2026-05-12.
**Proposed fix:** Add to `src/two_bot/prompts/writer_prompt.py` fire framing section:
"Seasonal and calendar context is world knowledge — it does not require archive data.
'The burning season in [region] typically peaks in [month].' or 'Fire activity here
normally fades by [month]. It is [current month].' are always verifiable framings. Do
NOT self-kill a fire draft solely because no numeric historical comparison is available.
When the only context is seasonal, use it. That's enough."

**Expected impact:** Unlocks the class of fire drafts where seasonal deadpan is the
mechanic. Sahel and Siberia fires are consistently in this class. One paragraph addition;
no other changes needed.

**Resolution:** Two changes to `src/two_bot/prompts/writer_prompt.py`:
1. Removed the "[country]'s fire/storm/wet season peaks in [month]" bullet from the
   `historical_context=empty` "do NOT write" list. The HARD RULES `NO FABRICATED
   CONTEXT` rule (with its 95%+ confidence gate) still catches truly invented seasonal
   claims; the removed bullet over-banned well-established geography.
2. Added a "Seasonal context for fires is world knowledge" paragraph after the existing
   "Important: lack of historical_context does NOT automatically mean kill" guidance.
   Emphasizes integrating seasonal framing INSIDE the system clause (the wink-kicker
   rules still apply — no separate calendar-stamp closer).

The proposal's second example ("Fire activity here normally fades by [month]. It is
[current month].") was trimmed during implementation because the second sentence
matched the banned wink-kicker shape from line 80. Replaced with single-clause example
("the Sahel dry season runs December–March") and explicit guidance against the calendar
closer.

**Status:** SHIPPED in PR #84. Awaiting empirical confirmation on the next two-bot
alerts cycle that fire drafts in Sahel/Siberia (the consistent self-kill class) now
produce drafts rather than dying on "no verifiable seasonal framing."

### ~~P4~~ — Add Wodehouse rule to top of writer_prompt.py — **SHIPPED 2026-05-12 (PR #85)**

**Observed:** humor-lens evaluation (Apr 27 corpus) found Wodehouse-rule violations are
the single most predictive failure mode across all corpus cycles. Drafts that try too
hard graded D-/C+/B regardless of mechanics; drafts that don't try graded B+/A-
regardless. Apr 29 [2] Mexico City repeated the explicit-gap-math violation. Two
consecutive prior cycles with the same violation. **2026-05-12 update:** Andrew's
explicit voice direction on Mankato manual-editorial reject names the same pattern:
"defensive 'A record is a record' closer" — the two-bot Sonnet writer reproduces
Wodehouse violations. Evidence confirmed in new two-bot pipeline.

**Cycles observed:** Apr 24, Apr 25, Apr 27, Apr 29, May 12 (5 cycles; most consistent
failure mode in the corpus).
**Last seen:** 2026-05-12.
**Proposed fix (REDIRECTED to two-bot):** Add as rule #0 in
`src/two_bot/prompts/writer_prompt.py` before the structural rules:

> 0. **DON'T SOUND LIKE YOU'RE TRYING.** The data is already extraordinary; the voice
> is its straight man. The Wodehouse rule: trying too hard breaks the spell. Signals
> of effort: approximation when exact is available ("nearly 3 degrees" when it's 2.7F),
> restate-padding ("The new high: 94.5F. The old one: 93.7F." after the data was given),
> poetry-attempt closers ("pointed at the sky"), defensive justification ("a record is
> a record") — all show effort, all kill the tweet before it lands.

**Expected impact:** Highest-leverage prompt change in the proposal stack. Wodehouse
violations cluster across grades and pipelines. Eliminating them moves B drafts to
B+/A- without changing structure.

**Resolution:** New section `# THE WODEHOUSE RULE` added to
`src/two_bot/prompts/writer_prompt.py` directly before `# HARD RULES`. Names the
four effort-signal failure modes (approximation, restate-padding, poetry-attempt
closers, defensive justification) and ties them back to the Attenborough/Economist
voice anchor — "the data is already extraordinary; the voice is its straight man."
Bundled with two other quality moves in the same PR:
1. **FRP intensity tier** in `build_fire_bundle` (`frp_tier` + `frp_tier_floor_mw`
   in `current_facts`) so the writer can give readers a scale-word ("high-intensity"
   at 309 MW) instead of opaque raw megawatts.
2. **Category cooldown** via new `recent_categories` field on `MemorySlice`. 24h
   per-category dedup prevents the "two fires in a row" pacing failure Andrew
   flagged on 2026-05-12 when both pending drafts were Sahel-style fires.

**Status:** SHIPPED in PR #85. Awaiting empirical confirmation on the next two-bot
alerts cycle (Wodehouse impact on writer self-criticism + variety mix) and the
next daily grading agent run (A-rate lift target: >50% sustained).

### P5 — Name humor moves as available tools in writer_prompt.py

**Observed:** Apr 25-27 corpus — SYSTEM_PROMPT named only a subset of available moves;
Gemini converged on the most-explicit ones (era anchors). Unnamed mechanics (idiom-flip,
accelerating-warming, ecosystem specificity) appeared inconsistently. In the two-bot
context, the Sonnet writer also defaults to the most-stated patterns unless the full
palette is named.

**Cycles observed:** Apr 25, Apr 27, May 13, May 17 (4 cycles; era anchor over-deployment
+ mechanic convergence in old pipeline; no named mechanics in fire batch May 13; mostly no
named mechanics in coral batch May 17 — exception: Galapagos [13] used ecosystem specificity
as incongruity vehicle and graded A-, showing the writer CAN reach for the move when the
location is distinctive enough; the gap is for less-iconic locations where the move is
available but not obvious).
**Last seen:** May 17.
**Proposed fix (REDIRECTED to two-bot):** Add a "Voice moves available" section to
`src/two_bot/prompts/writer_prompt.py` after the hard rules. List: comic triple
(period-stop), idiom-flip (Steven Wright), understatement closer (British dry),
period-and-restate (Anchorage move), deadpan delivery, accelerating-warming, era anchor,
ecosystem-specific specificity. Conclude: *"None of these are mandatory. When the number
alone is striking, deliver the data plainly. Forced humor breaks the spell."*

**Expected impact:** Richer move palette → more variety across drafts → less convergence
on the easy default.

**Status:** Drafted. Target updated from dead generator.py SYSTEM_PROMPT to
`src/two_bot/prompts/writer_prompt.py`. Awaiting human implementation.

### ~~P6~~ — Fire template convergence — **SHIPPED 2026-05-12 (PR #85)**

**Observed:** 2026-05-13 first graded two-bot cycle — all 3 fire drafts (Mali,
Campeche, Mongolia) used the identical sentence-1 structure: *"A fire in
[location] is radiating X MW of heat, detected by satellite at N% confidence."*
The writer defaults to the most-stated form when the bundle is signal_kind=fire
without historical_context, and the prompt's existing fire exemplar (#4) further
reinforces the template. The 24h category cooldown shipped in PR #85 catches
this across cron runs but not within a single cycle.

**Cycles observed:** May 13 (1 cycle; 3 of 3 fire drafts identical sentence-1).
**Last seen:** 2026-05-13.

**Resolution:** New paragraph in `writer_prompt.py` IF-historical_context-IS-EMPTY
section directly after the FRP intensity tier paragraph. Names 4 alternative
sentence-1 forms (lead-with-location, lead-with-seasonal-frame, lead-with-tier-word,
lead-with-stakes-or-scale-anchor) with full example tweets for each. Closes by
banning the default opener when `recent_categories` already contains "fire" within
24h, and tells the writer to ask whether the bundle is actually extraordinary
enough to ship if no alternative form works.

**Status:** SHIPPED in PR #85 second commit. Empirical test: next cron run that
produces 2+ fire drafts in the same cycle — do they show structural variety?

### ~~Chuuk ceiling — "expository → punch"~~ — **SHIPPED 2026-05-12 (PR #85)**

**Observed:** 2026-05-13 grader noted that the Chuuk monthly_high draft was the
ceiling at B (not A-). Clean data, 76-year record, °C+°F, specific date — but
second sentence was "expository (Pacific warm pool context) rather than a
punch." The system clause described the geography without paying off the data.

**Cycles observed:** May 13 (1 cycle; identified as ceiling-class).
**Last seen:** 2026-05-13.

**Resolution:** Augmented THE SIGNATURE MOVE section's bullet-2 with the
expository-vs-punch distinction. Explicit B-vs-A example pair using the Chuuk
case ("Chuuk sits in the Pacific warm pool" → expository B; "Chuuk anchors the
Pacific warm pool — the engine of the global atmosphere; small May reading
shifts here propagate downstream" → punch A). New "delete the system clause"
test: if removing your second sentence leaves the reader thinking "so what?",
load-bearing. If it leaves them thinking "oh, fair enough", expository.

**Status:** SHIPPED in PR #85 second commit. Empirical test: next graded cycle —
do system clauses do work (consequence/contrast/causal/rate) rather than just
describing geography?

**May 17 update:** Partially working. Three of the 8 coral bleaching drafts (Galapagos,
Austral Islands, Madagascar) have second sentences that do real work — expectation/violation,
geographic incongruity, mechanism-then-consequence. Five coral drafts (Nauru, Great Nicobar,
Chagos, Fiji, Southern Borneo) still use explanatory geography-lesson second sentences. The
fix is landing on strong signals with distinctive ecosystem context; not yet landing on
weaker signals. P7 (below) targets the within-cycle convergence version of this failure.

### P7 — Coral DHW explanation convergence in second sentences

**Observed:** May 17 — 8 coral_bleaching drafts in one cycle; 5 of them use near-identical
second-sentence DHW explanations. The pattern:

- [7] Madagascar: "DHW measures how long heat persists, and persistence is what kills"
- [8] Fiji: "sustained heat above the tolerance ceiling is what turns stress into die-off"
- [9] Nauru: "DHW measures heat duration, not just intensity; it's persistence above the
  tolerance ceiling that kills coral"
- [10] Great Nicobar: "DHW measures heat persistence, not just intensity; it is duration
  above the tolerance ceiling that kills coral" (synonyms for [9])
- [11] Chagos: "DHW counts how long heat persists above the tolerance ceiling; proximity to
  8 is what matters"

By draft [10], the explanation is verbatim-with-synonyms. The metric explanation is useful
ONCE — DHW is unfamiliar to most readers. After that, subsequent coral drafts in the same
cycle should use the second sentence for location-specific ecosystem context only (trust the
reader to remember what DHW means from the earlier draft in their scroll).

**Cycles observed:** May 17 (1 cycle; 5 of 8 coral drafts converge on explanation closer).
**Last seen:** May 17.

**Proposed fix:** Add to `src/two_bot/prompts/writer_prompt.py` coral_bleaching section:
"If `used_framings` already contains a DHW explanation this cycle, skip the DHW definition
in the second sentence entirely. Go straight to the location-specific ecosystem context:
what makes THIS reef system distinctively vulnerable? (Cold upwelling failure, SPCZ band
expansion, atoll exposure, etc.) Trust the reader — the metric was explained in the earlier
draft. Repeating it with synonyms reads as template, not voice."

**Expected impact:** Eliminates the [9]-[11] explanation-convergence pattern. Forces the
writer to surface location-specific ecosystem vulnerability in the second sentence for every
coral draft past the first — which is where the A-grade coral moves actually live
(Galapagos, Austral Islands).

**Status:** Drafted. Awaiting human implementation in `writer_prompt.py`.

## Awaiting evidence

These need more cycles before promotion to active proposals or retirement.

### A1 — Era_anchors prune impact (Apr 26) — superseded by architecture change

43 politically-charged entries removed from `data/era_anchors.json` on 2026-04-26. The
Apr 27 cycle had one political-anchor draft (Jacobabad / Elon Musk). Whether the prune
eliminated leakage was the watch condition — but this is now moot because generator.py
(which used era_anchors.json) is dead since 2026-05-04. The two-bot writer has its own
`memory.used_era_anchors` tracking. Watch for: era anchor quality in two-bot record
drafts once they reach pending. If any politically-charged anchor appears, that's a
separate curation path to investigate in the two-bot writer.

### A2 — Two-bot writer sample-size baseline (replaces v2.5 sample-size question)

The voice engine history (v2: 43% A-rate on 7 drafts; v2.5: 9% on 11 drafts) is no
longer relevant — that pipeline is dead. The two-bot writer is the new baseline.

**Updated May 17:** Two graded cycles now on record. May 13: 0% A-rate (4 drafts — 3 fire, 1
monthly_high). May 17: 7% A-rate (14 drafts — 4 carry-over, 1 monthly_low, 1 fire, 8 coral).
Cumulative two-bot A-rate: **1/18 graded = 6%** (not counting carry-over double-count). First
A- is Galapagos coral (May 17) — ecosystem-specificity mechanic via cold-upwelling incongruity.
Confirmed failure modes in two-bot pipeline: fire template convergence (partially fixed by
PR #85), DHW explanation convergence in coral drafts (new — P7), margin-language vagueness in
cold records (Bethel "a degree below"). No era-anchor over-deployment observed (no record drafts
with era anchors in either graded cycle). No Wodehouse violations in either cycle (P4 fix holding).

**F3 critic context (PR #120, merged ~May 15-16):** Second-pass editorial critic now in
pipeline. It's unclear whether the May 15 coral drafts passed through the critic (timing is
ambiguous). If they did, the 7% A-rate with the critic active sets a new post-critic baseline.
If they didn't, the next cycle with fresh coral or record drafts will be the first critic-
inclusive graded cycle.

**Watch for:** (a) Record drafts (all_time_high, country_high, monthly_high) reaching pending
under two-bot pipeline — no era anchor test cases yet. (b) First critic-inclusive graded cycle
to see if the F3 pass is lifting B drafts to B+ or A-.

## Resolved (archive)

History of fixes that landed or became obsolete — added when a failure mode either held
for 3+ cycles without appearing, or when the target code was retired.

### [Archived 2026-05-12] P2 — Widen plant-comparison regex adjective allowlist

Last observed: Apr 27 (1 draft; "a commercial nuclear reactor"). Target code
`src/voice/generator.py::_STOCK_FORMULA_PATTERNS` is dead since 2026-05-04. Proposal
cannot fire in the live two-bot pipeline. If plant-comparison failures emerge in two-bot
output, open a new proposal targeting `src/two_bot/prompts/writer_prompt.py`.

### [Archived 2026-05-12] P3 — Widen opener-formula verb list

Last observed: Apr 27 (1 draft; "pushing" not in verb allowlist). Target code
`src/voice/generator.py::_STOCK_FORMULA_PATTERNS` is dead since 2026-05-04. Proposal
cannot fire in the live pipeline. If banned-opener variants emerge in two-bot fire drafts,
open a new proposal against `src/voice/safety.py` (the safety pipeline still runs) or
`src/two_bot/prompts/writer_prompt.py`.

### [Archived 2026-05-12] P5 — Add stranded-mechanic warning to fire prompt addendum

Last observed: Apr 27 (3 drafts; mechanics buried in throat-clearing). Target code
`src/voice/generator.py::_CATEGORY_PROMPTS["fire"]` is dead since 2026-05-04. The
underlying concern (don't bury the punchline in setup) is covered by P4's Wodehouse rule
in the updated writer_prompt.py proposal.

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
