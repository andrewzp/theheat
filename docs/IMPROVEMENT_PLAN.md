# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

> **Routine restored and grading.** First fresh draft in 19 days reached the queue 2026-06-07 (Barrow, Alaska precipitation_extreme — B+). Pipeline producing signals again post-0.9.15.0 gpm single-request grid migration. The *source-health* sentinel (0.9.12.0+, every 4h) is a separate system — it tracks data-fetch health, not voice quality.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

> **Structural update (2026-06-16 eng-review).** This doc tracks voice quality
> toward the `>50%`-A-rate resumption bar. The 2026-06-16 `/plan-eng-review` found
> that bar is *structurally* unreachable as wired: it is graded by the
> daily-plan routine (dead since 2026-05-26), posting is paused until it clears
> (peak ever 21%), and A-grade drafts go stale in the queue before they could lift
> it. The **Throughput Initiative** addresses the structural causes directly —
> **Phase B** decouples the ship gate (per-draft critic-PASS + freshness instead of
> the dead cycle-level grader) and **Phase A** adds the missing per-stage kill-rate
> / critic-pass-rate instrumentation so "is voice the bottleneck or is the
> architecture?" becomes measurable rather than assumed. See
> [/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-throughput-initiative-EXECUTION.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-throughput-initiative-EXECUTION.md).
> The voice proposals below remain valid; they raise the A-rate at the source.

## Current state

| | |
|---|---|
| Bot commit | `0.9.21.0` (voice engine unchanged since 0.9.8.0's fact-check claim-kind hardening; 0.9.9.0–0.9.21.0 work is source reliability + observability: gpm_imerg date walk-back/IPv4/fan-out-cap/walk-back-exhaustion, daily source-health sentinel [0.9.12–0.9.13; issue label/body sync tightened in 0.9.16.1], dashboard external/idle/recovery tiers [0.9.14.0/0.9.16.1], gpm single-request daily-grid fetch via datapool/s3 [0.9.15.0, PR #185, 2026-06-06], per-type pending TTL [0.9.16.0]; @extremetemps coverage lane complete [Wave 1 0.9.17.0, SST 0.9.18.0, Part B #203 0.9.19.0]; state-merge + gist-size + CI hardening + tech-stack review [0.9.20.0]; air_quality rate-limit recovery + sentinel degraded-handling [0.9.21.0]. all 23 sources on triage path + evidence contract live since 0.9.0.0; bot active since 2026-06-01) |
| Voice engine version | **two-bot + Attenborough/Economist voice + all-sources triage + evidence contract + diversity gate + automation dashboard** (Sonnet 4.6 writer prompt-cached + Gemini Flash fact-checker [skips unknown kinds] + Gemini 2.5 Pro critic [assesses relative to available data]; all 23 sources on triage path via PR #150; evidence contract gates writer via 0.9.0.0; pending-type cap default 3 + per-type TTL sweep [fast 7d, coral/DHW 21d] via 0.9.6.0/0.9.16.0; gpm_imerg 60s timeout + retry via 0.9.5.0; `THEHEAT_TRIAGE_ENABLED=1` in CI; routine beacon writes the `ROUTINE_BEACON` repo variable via `gh variable set` each cycle) |
| Last cycle A-rate | **0%** (0/1 fresh draft, 2026-06-07; n=1 — not statistically meaningful; prior: 21% on 2026-05-19 [3/14, first A-grades in two-bot era]) |
| Resumption bar | majority A (>50%) sustained |
| Gap | **50 pp** (50% − 0%, n=1); prior measure: 29 pp (50% − 21%, 2026-05-19) |
| Posting | paused until bar cleared |
| Coverage | **638 cities × 180 countries** (was 613 × 179; +25 via PR #81) |
| Queue status | **0 pending** (as of 2026-06-16). Pipeline active: 7 new drafts created Jun 4–15. Barrow Alaska posted. Chesnee SC monthly_low approved (35yr/7°F/temperate — strong signal). Red Dog Mine Alaska monthly_low rejected (17yr/1°F/arctic — P_new exemplar). Riyadh dust_event + Beaver Dams Utah all_time_high posted. New types now producing: dust_event, all_time_high. Coral consequence-closer pattern holding in posted drafts. |

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
force. **Empirically confirmed: 2 graded cycles (May 13, May 14) with 6 fire drafts
total, all producing clean 1-decimal FRP values (309.6, 364.7, 307.6 MW), zero
BUNDLE_FACT rounding kills observed.**

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

**Status:** SHIPPED in PR #84. **Empirically confirmed: 2 graded cycles (May 13, May 14)
with 6 fire drafts (Mali, Campeche, Mongolia x 2 cycles), all reaching pending with
seasonal framing deployed. Zero P3 self-kills observed across both cycles. Failure mode
closed in two-bot pipeline.**

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

**Status:** SHIPPED in PR #85 / PR #89. **Empirically confirmed (partially): 2 graded
cycles (May 13, May 14) with 9 two-bot drafts total — zero Wodehouse violations observed
in either cycle. Fire drafts arrive clean; no defensive closers, no explicit gap math,
no restate-padding. A-rate has not lifted yet; Wodehouse violations were not the current
bottleneck — named mechanics and category-specific convergence are.**

### P_new — Cold-record quality floor: writer over-passes shallow-archive cold signals

**Observed:** 2026-05-14 — Bethel, Maine monthly_low (28°F / -2.2°C, May 9, score 80,
threshold 76) reached pending with a 16-year archive and 1°F margin in a cold-climate
bowl location. Voice execution is clean (topographic mechanism per PR #75, no Wodehouse
violation). The signal fails the editorial bar Andrew established on 2026-05-11 when he
manually rejected Mankato, Minnesota monthly_low (score 79, 16yr archive, 0°F effective
margin, note: "weak signal, defensive closer"). Bethel matches the signal class — shallow
archive, trivial margin, location where cold is architecturally expected — but with
cleaner voice. The writer has no self-kill gate for weak cold records the way it now has
strong self-kill instincts for low-confidence fire framings.

**Cycles observed:** May 14, Jun 13 (2 cycles; + May 11 Andrew-reject precedent + Jun 13
operator rejection of Red Dog Mine, Alaska as independent confirmation).
**Last seen:** 2026-06-13. Red Dog Mine, Alaska: 19°F (-7.1°C), coldest June low in 17
years of records, 1°F margin — same failure class as Bethel and Mankato (shallow archive,
trivial margin, arctic/subarctic cold-climate). Operator correctly rejected. Writer still
producing this class. Editorial contrast: Chesnee SC (35yr archive, 7°F margin, temperate
warm climate) approved same cycle — operator correctly distinguishing signal strength.

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
cold-record framing section:

> For `monthly_low` or `country_low` signals: self-kill when ALL of the following are true:
> (a) archive depth < 20 years, (b) margin below prior record < 1°C / 2°F, (c) location
> has a cold climate (high-latitude, subarctic, alpine, or in a documented cold-air
> drainage bowl). A 16-year cold record in Maine with a 1°F margin in a frost-prone valley
> is not extraordinary — archive is shallow, margin is trivial, cold is expected here. Use
> kill_reason: "shallow archive cold record: insufficient editorial weight (< 20yr archive,
> < 1°C margin, cold-climate location)." The writer self-kill on Mankato (May 2026) was
> correct on the same grounds.

**Expected impact:** Prevents the class of cold-record drafts that pass the score gate
(threshold 76) but fail the human editorial bar Andrew established. Mirrors the fire
drafts' existing self-kill instincts on low-confidence framings. Scoped to cold records
only — does not affect monthly_high or other record types.

**Status:** Drafted. Awaiting human implementation. Bethel, Maine (the original exemplar)
is no longer in the queue — cleared by TTL sweep. Red Dog Mine, Alaska (Jun 13, rejected
by operator) is now the live exemplar. Writer still produces this class; operator is
currently catching it at review. P_new writer self-kill would automate the filter.

### P5 — Name humor moves as available tools in writer_prompt.py

**Observed:** Apr 25-27 corpus — SYSTEM_PROMPT named only a subset of available moves;
Gemini converged on the most-explicit ones (era anchors). Unnamed mechanics (idiom-flip,
accelerating-warming, ecosystem specificity) appeared inconsistently. In the two-bot
context, the Sonnet writer also defaults to the most-stated patterns unless the full
palette is named.

**Cycles observed:** Apr 25, Apr 27, May 13, May 19 (4 cycles; era anchor over-deployment
+ mechanic convergence in v2 era; no named mechanics in fire drafts in two-bot era).
**Last seen:** May 19 (partial: fire Draft 6 has no named mechanic; fire Draft 18 has
timing-incongruity embedded but not standalone. Coral drafts show moves without explicit
naming — mixed evidence for the proposal's core claim, but fire-specific convergence
holds.)
**Proposed fix (REDIRECTED to two-bot):** Add a "Voice moves available" section to
`src/two_bot/prompts/writer_prompt.py` after the hard rules. List: comic triple
(period-stop), idiom-flip (Steven Wright), understatement closer (British dry),
period-and-restate (Anchorage move), deadpan delivery, accelerating-warming, era anchor,
ecosystem-specific specificity. Conclude: *"None of these are mandatory. When the number
alone is striking, deliver the data plainly. Forced humor breaks the spell."*

**Expected impact:** Richer move palette → more variety across drafts → less convergence
on the easy default. Note: coral drafts in the May 19 cycle produced named-move variants
without explicit prompting (contrast-reveal, expectation-reversal, understatement closer)
— the coral writer prompt may already be doing the work. Verify whether `writer_prompt.py`
has a coral-specific named-moves section before implementing.

**Status:** Drafted. Target updated from dead generator.py SYSTEM_PROMPT to
`src/two_bot/prompts/writer_prompt.py`. Awaiting human implementation.

### P7 — Coral opener formula convergence

**Observed:** 2026-05-19 — 8 of 9 coral_bleaching drafts use the same opener: "[Location]
reefs have accumulated X°C-weeks of thermal stress — [threshold label]." Identical to the
P6 fire template failure but in the new coral_bleaching category. All three A- coral
drafts deviate from the formula: they use the shorter colon-lead form ("Galapagos, Ecuador
reefs: 24.5°C-weeks...") or a named upwelling-failure angle rather than the accumulation
sentence. The formula opener is a structural ceiling at B+.

**Cycles observed:** May 19 (1 cycle; 8 of 9 coral drafts formula-identical).
**Last seen:** May 19.
**Proposed fix:** Add to `src/two_bot/prompts/writer_prompt.py` coral/DHW framing section
(if it exists) or to the fire-variety-forms paragraph (same location as P6's fix in PR
#85): burn the formula opener for coral. Name 3 alternative sentence-1 forms:
(1) colon-lead with the ratio ("Galapagos reefs: 24.5°C-weeks — double the mortality tier.");
(2) upwelling/buffering angle first ("The cold upwelling that normally buffers the Galápagos
has failed; reefs there have accumulated 24.5°C-weeks of thermal stress.");
(3) location + mechanism first ("Where Pacific moisture stalls before the Cascades blocks
it, stress accumulates: 10.2°C-weeks in Western Madagascar."). Add Draft 7's second-sentence
form as APPROVED EXEMPLAR for the DHW mechanism close: "Corals can survive brief spikes;
DHW measures how long heat persists, and persistence is what kills."

**Expected impact:** Same as P6 — breaks the writer's convergence on the stated opener
form. Higher expected yield than P6 because the coral category is newer and the writer
has had fewer corrections on it.

**Status:** Drafted. Awaiting human implementation.

### P8 — Snow/extreme record: ratio-as-punchline unused

**Observed:** 2026-05-19 — both snow_extreme drafts (Nooksack 2×, Stahl Peak 5×) state
the ratio in the first sentence as setup context, then pivot to topographic explanation.
Neither lands the ratio as a punchline. Stahl Peak's "nearly five times the previous
blizzard record of 50.8 mm" is the most striking number in the queue; the draft continues
to explain "the northern Rockies funnel Pacific moisture through low passes; when a storm
stalls, totals compound fast." "Totals compound fast" restates what "five times the record"
already shows. The period-and-restate mechanic from the voice spec is the right tool —
"251.5 mm in 3 days. The previous record was 50.8 mm." — and is not used.

**Cycles observed:** May 19 (1 cycle; 2 of 2 snow_extreme drafts miss the ratio-punchline).
**Last seen:** May 19.
**Proposed fix:** Add to `src/two_bot/prompts/writer_prompt.py` general record/extreme
guidance (after the existing SIGNATURE MOVE section): "When a record is broken by a ratio
(2×, 5×, 10×), the prior record stated plainly IS the punchline — do not over-explain
with mechanism geography after stating it. The period-and-restate form: '[Current value].
The previous record was [prior value].' is available. Test: if the ratio is more
surprising than the mechanism, state the ratio last."

**Expected impact:** Unlocks the "ratio landing" move for snow, fire, and any category
where the new value is a multiple of the prior. Prevents the writer from diluting a
naturally strong signal with topographic explanation.

**Status:** Drafted. Awaiting human implementation.

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

**Updated 2026-05-19:** Two-bot baseline now measurable across two graded cycles (May 13:
0/4 = 0%; May 19: 3/14 = 21%). Cumulative: 3 A / 18 drafts = 17% A-rate on first two-bot
graded drafts. First A-grades are coral_bleaching (3 of 3 A-grades came from new category
on 2026-05-19). Fire and monthly_high categories have not yet produced an A-grade in the
two-bot era. Voice engine history (v2: 43%; v2.5: 9%) remains reference only — pipeline
dead.

**Updated 2026-05-25:** Five consecutive graded cycles (May 20, 22, 23, 24, 25) produced
0 fresh drafts. Queue static since 2026-05-18T15:52Z (~7 days). Two-bot A-rate baseline
unchanged: May 13 0/4 = 0%; May 19 3/14 = 21%; cumulative 3A / 18 = 17%. The 0.9.0.0
release (2026-05-22) wired all 23 sources through the evidence contract for the first time
— `stage="evidence_contract"` suppression kills are now possible on every signal type and
are unverified empirically. A non-trivial kill count here would explain queue stagnation
without invoking seasonal quiet. Next measurement when queue resumes.

**Watch for:** whether fire category closes the gap between the May-13 0% and the coral
batch's A-grade-producing range. Whether Wodehouse violations re-emerge as more categories
are added. Whether the new critic stage (Gemini 2.5 Pro, PR #120) is contributing to or
suppressing A-grade candidates before they reach pending.

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
