# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

> **Jun 30: 10 pending, 9 graded, 22% A-rate (bar cleared Jun 29 still stands).** 1 stale excl.: Mediterranean regional_sst_anomaly (~59h, "today" baked). 2 A-: GMST marine_heatwave A- (floor/ceiling inversion "already the floor of a new streak"); Prudhoe Bay all_time_high A- (score 92, 101°F at 70°N, latitude peer-comparison). 5 B: France reganom B+, Astana B+, Antwerpen B+, Amsterdam B, Colorado B-. 2 C+: Phalodi + Taiz dust_event (P_dust 5th+6th cycle, zero named mechanics, no WHO anchor). P9 9th cycle: 3/3 fresh precip drafts (Astana/Antwerpen/Colorado) show opener template + restate-math. P5: dust_event continues to deploy zero named mechanics (2nd cycle confirming gap category). regional_anomaly corpus debut: France reganom B+ (score 88, 6-city +8.4°C avg, 2.8σ — first reganom in corpus post-#349). P_compound: Prudhoe Bay shows archive+margin double-qualifier (3rd cycle). 22% A-rate reflects different signal mix vs. Jun 29 — fewer A-grade-prone signal types in queue. GMST marine_heatwave approaching 48h staleness (~45.7h at grading) — publish promptly. 32nd consecutive staleness skip.
>
> **Jun 29: 5 fresh drafts (80% A-rate — BAR CLEARED).** 1 Jun-28 carry-over (Mediterranean B+, grade stands). [2] marine_heatwave A- (floor/ceiling inversion; "already the floor of a new streak"; P_close positive). [3] France reganom B+ (pre-#349; "Across 6 sampled cities" buries lede; "hour by hour" Wodehouse mild; P_close failing). [4] Congo fire A- (first A-grade fire in two-bot corpus; ecosystem incongruity "something has broken the convective lid"; P_close positive). [5] Prudhoe Bay all_time_high A- (latitude peer-comparison 91°F at 70°N vs. northern Siberia rarely 80°F; P_compound 2nd cycle — archive+margin double-qualifier). [6] Amsterdam precipitation_extreme A- (declarative close "there is nowhere for the water to go"; P_close positive; P9 8th cycle; P_precip_floor 2nd cycle — 4.7% margin wet-climate). P_close 11th cycle: 3 positives, 1 failing, 1 n/a. New signal type in corpus: marine_heatwave. No Wodehouse violations (8th consecutive clean). `gh` CLI absent (31st consecutive skip).
>
> **Jun 28: 5 fresh drafts (0% A-rate).** 2 Jun-27 carry-overs not re-graded ([1] fire B+, [2] Amsterdam C+). [3] Taiz dust_event C+ (P_dust 4th cycle, no WHO anchor; P_close mechanism-only fail). [4] Mediterranean SST B+ (P_close borderline positive "nowhere fast to go"). [5] Astana precip B+ (51.1/3.9 mm implicit 13×, steppe closer; P9 7th cycle). [6] Beaver Dams all_time_high B+ (P_compound new — archive+margin double-qualifier; P_close implied fail). [7] Casper monthly_low B (P_compound 2nd obs; P_close implied fail). P_close 10th cycle; 3 failing, 1 borderline positive, 1 n/a. New proposal P_compound. `gh` CLI absent (30th consecutive skip).
>
> **Jun 26: 3 fresh drafts (0% A-rate).** All precipitation_extreme. Anchorage B (183.8 mm/3d,
> 22.5% margin, orographic stall mechanism, P_close mechanism-only failing). Amsterdam C+ (157.1
> mm, 4.73% margin, canal-capacity incongruity, P_close implied-consequence failing). Aktobe C+
> (150.8 mm, 0.53% margin, steppe-aridity + half-year ratio, P_close borderline). **Infrastructure
> alert:** all 3 cite "previous 3-day record of 150.0 mm" — detection threshold used as prior
> record (`previous_record_year: null`); operator must verify authentic station records before
> publishing as "record-breaking." P9 6th cycle: all 3 use opener template + restate-math. P_close
> 9th cycle: 2 failing + 1 borderline. `gh` CLI absent (29th consecutive skip).
>
> **Jun 25: 5 fresh drafts (0% A-rate).** P_close 8th cycle: 3 failing (Taiz dust_event ×2 + Michigan monthly_low), 2 positive (Siberia fire "burns deep" + Barrow "nearly twice that total"). P_dust 3rd cycle: both Taiz dust_event drafts lack WHO anchor; all 4 dust_event corpus drafts template-converged. P9 5th precipitation_extreme (Barrow, same opener template + restate-math). First companion-fire peer comparison in fire corpus. "Roughly"/"nearly" hedges cost Barrow A-; date-baking ("today"/"same day") costs Siberia A-. `gh` CLI absent (28th consecutive skip).
>
> **Jun 24: 2 fresh drafts (0% A-rate).** Randolph UT monthly_high (B+): ecosystem specificity "normally blunts" = P_close 7th cycle failing (implied-consequence form). Al Aḥmadī Kuwait air_quality_hazard (B): 10.1× WHO ratio stated (P_dust POSITIVE), closes on system resolution "by evening" = P_close 7th cycle failing (resolution-close subtype). First air_quality_hazard in corpus. Draft [2] "June 24" date-baked — stale by Jun 26T14:50. Mediterranean SST `draft_20260622_171200_17` crosses 48h at ~Jun 24T17:12 UTC — operator must post/reject within ~2h of this run. `gh` CLI absent (27th consecutive skip).
>
> **Jun 23: 3 fresh drafts (33% A-rate).** Cope Rch TX all_time_high (A-): "push extremes fast" = declarative-consequence, P_close positive evidence. Columbus GA all_time_high (B): 1°F margin, dual-mechanism. Mediterranean SST regional_sst_anomaly (B): comparative-implied close + unexplained NOAA 2.5°C threshold (A3 filed). P_close 6th cycle: Columbus + Mediterranean = failing; Cope Rch = positive. `gh` CLI absent (26th consecutive staleness skip). Mediterranean SST "today" anchor → staleness at Jun 24T17:12Z.
>
> **Jun 22: 0 pending; 1 retroactive grade.** Barrow 7-day precip (draft_20260618_154318_15, created Jun 18T15:43Z, flagged ungraded in Jun 19/21) graded A-. "Has nowhere to go" = first precipitation_extreme declarative-consequence close — P_close positive evidence (validates the fix, not a failing observation). Restate-math confirmed: P9 now 3 cycles (all 3 precipitation_extreme corpus drafts). Queue empty 4th consecutive day. `gh` CLI absent (25th consecutive staleness skip).
>
> **Jun 21: 0 fresh drafts; queue empty.** No new drafts since Jun 18T15:43Z (~2.5d gap). P_new archived (2nd time): 3 consecutive fresh-draft cycles without cold-record (Jun 15/17/18) meets the 3+ runbook threshold. No new evidence for P_close/P9/P_dust/P5. `gh` CLI absent (24th consecutive staleness skip).
>
> **Jun 19: 0 fresh drafts; queue empty.** All 3 Jun 18 precipitation_extreme drafts operator-rejected (Barrow daily B+, Amsterdam B, Barrow 7-day [ungraded, created Jun 18T15:43Z]). First operator rejection of a B+ graded draft. No proposal evidence updates this cycle.
>
> **Jun 18: 2 fresh drafts (both precipitation_extreme, both B-range).** P_close 5th cycle confirmed (Barrow "any of it" + Amsterdam "stack up faster than they drain" both implied-consequence closes). New proposal P9 added (precipitation_extreme opener template convergence + restate-math). No dust/coral/cold-record drafts this cycle. The *source-health* sentinel (0.9.12.0+, every 4h) is a separate system.

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
| Bot commit | `0.9.67.0` (R-02 NOAA HMS independent fire witness for firms; main HEAD 2026-06-13. 30-item audit backlog complete [S-01..S-35, PRs #222–#265, self-merged]; source-redundancy lane R-00..R-09 executing [PRs #222–#271]; 0.9.22.0–0.9.47.0 infra/source/dashboard sprint Jun 9–12: record-store caps, slow-mover cache, publish-ledger idempotency, sqlite backend, dashboard project state — all non-voice; bot active since 2026-06-01) |
| Voice engine version | **two-bot + Attenborough/Economist voice + all-sources triage + evidence contract + diversity gate + automation dashboard** (Sonnet 4.6 writer prompt-cached + Gemini 2.5 Flash fact-checker [skips unknown kinds] + Gemini 2.5 Pro critic [assesses relative to available data]; all 23 sources on triage path via PR #150; evidence contract gates writer via 0.9.0.0; pending-type cap default 3 + per-type TTL sweep [fast 7d, coral/DHW 21d] via 0.9.6.0/0.9.16.0; `THEHEAT_TRIAGE_ENABLED=1` in CI; **`THEHEAT_WRITER_SAMPLES=2` + `THEHEAT_CRITIC_REVISE_ENABLED=1` live 2026-06-13** — best-of-2 drafts + one critic rewrite per cycle; routine beacon writes the `ROUTINE_BEACON` repo variable via `gh variable set` each cycle) |
| Last cycle A-rate | **22% (2/9 non-stale, Jun 30)** — GMST marine_heatwave A- (floor/ceiling inversion); Prudhoe Bay A- (latitude peer-comparison, score 92). France reganom B+, Astana B+, Antwerpen B+, Amsterdam B, Colorado B-. Phalodi + Taiz dust_event C+ (P_dust). 1 stale excl. (Mediterranean regional_sst_anomaly ~59h). Prior: 80% Jun 29 [BAR CLEARED]. |
| Resumption bar | majority A (>50%) sustained — **cleared Jun 29 (80%, n=5); Jun 30 returned 22% on different signal mix** |
| Gap | **28 pp below bar** (50% − 22%, Jun 30); Jun 29 was +30 pp above bar — signal-mix variation, not regression in writer quality. Dust_event and monthly_low categories structurally underperform; A-grade rate is signal-type dependent. |
| Posting | paused; operator decision pending — Jun 29 cleared bar (80%), Jun 30 below (22%) on dust+precip-heavy queue; Mediterranean stale (operator reject); marine_heatwave approaching 48h — publish promptly |
| Coverage | **638 cities × 180 countries** (was 613 × 179; +25 via PR #81) |
| Queue status | **10 pending as of Jun 30 grading** (1 stale: Mediterranean regional_sst_anomaly; 9 graded: marine_heatwave A- [publish promptly ~48h], France reganom B+, Astana B+, Antwerpen B+, Amsterdam B, Colorado B-, Prudhoe Bay A-, Phalodi C+, Taiz C+). Bot at 0.9.81.0; reganom enabled post-PR #347; `THEHEAT_WRITER_SAMPLES=2` + `THEHEAT_CRITIC_REVISE_ENABLED=1` live. |

## Active proposals

Ordered by leverage. Priority as of Jun 30: **P_close** (11+ cycles) > **P9** (9 cycles, Jun 30) > **P_dust** (6 cycles, Jun 30 ×2) > **P5** (dust_event gap confirmed Jun 30) > **P_compound** (3 cycles, Jun 30) > **P_precip_floor** (2 cycles). Each entry tracks: observation count (cycles where the failure mode appeared), last seen, proposed fix, expected impact, status.

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

### P_close — Mechanism close defaults to implied consequence rather than declarative statement

**Observed:** 2026-06-07 — Barrow, Alaska precipitation_extreme, B+: "sheets across the
surface instead" — consequence implied by contrast ("instead"), not named. 2026-06-10 —
Chesnee, South Carolina monthly_low, B+ (status=approved): "threaten gardens well into
early summer" — frost implied, not stated. 2026-06-13 — Red Dog Mine, Alaska monthly_low,
C+: "tundra terrain offers no shelter from cold air pooling on clear nights" — mechanism
explanation only; no consequence named or implied (the coldest version: stops at mechanism
before reaching even the implied-consequence stage). Three consecutive fresh-draft cycles
from different signal categories (precipitation_extreme, monthly_low ×2), same gap to A-.

All three had correct mechanism identification (ecosystem specificity operating). The gap
is in the LANDING: the writer arrives at the physical mechanism but stops before naming
what the mechanism does. The corpus A-grade closers state the consequence flatly:
"persistence is what kills" (Madagascar), "nowhere to drain" (Costa Rica), "It is April"
(Mali). None defer to implication; none stop at mechanism.

**Cycles observed:** 11 active (Jun 7 pending; Jun 10 approved voice observation; Jun 13 Red Dog Mine;
Jun 15 retroactive; Jun 18 Barrow + Amsterdam; Jun 23 Columbus GA + Mediterranean SST failing,
Cope Rch TX positive; Jun 24 Randolph UT + Al Aḥmadī Kuwait both failing; Jun 25 Taiz ×2 +
Michigan monthly_low failing, Siberia fire + Barrow precip positive; Jun 26 Amsterdam
implied-consequence failing + Anchorage mechanism-only failing + Aktobe half-year ratio
borderline; Jun 28 — Taiz [3] mechanism-only failing, Mediterranean [4] "nowhere fast to go"
borderline positive, Beaver Dams [6] "blunt the afternoon peak" implied-consequence failing,
Casper [7] "what June air masses would otherwise deliver" implied-consequence failing;
Astana [5] steppe-closer = ecosystem-incongruity punchline, not traditional P_close;
Jun 29 — marine_heatwave [2] "floor of a new streak" positive, France reganom [3] "hour by hour" failing,
Congo fire [4] "convective lid" positive, Prudhoe Bay [5] latitude-peer n/a, Amsterdam [6] "nowhere for the water to go" positive).
Jun 15 retroactive: 5 A- drafts (Loxahatchee NWR, Beaver Dams, Kapingamarangi, Gilbert Islands,
Chesnee SC) each reached A- not A — consistent with P_close pattern (implied consequence or
mechanism-only close). Loxahatchee: "water levels are still dropping" implies drought, doesn't
name it. Beaver Dams: "stranding paddlers well into spring" implies low water, names the human
consequence (strong A- form, closest to A). Kapingamarangi/Gilbert Islands/Chesnee: similar
implied-consequence structure. Nauru (A): "no adjacent reef system to reseed it" — declarative
structural consequence, no hedge. Validates P_close gap: Nauru's direct form earns A; the A-
drafts stop one step short.
Jun 24: Randolph UT monthly_high B+ ("normally blunts the heat" = implied-consequence form; new
signal type confirms cross-category scope). Al Aḥmadī Kuwait air_quality_hazard B ("before sea
breezes suppress them by evening" = resolution-close subtype — close actively defuses the
violation by naming the system's natural recovery, not just implying consequence). P_close now
confirmed across 7 signal types: precipitation_extreme, monthly_low, coral, fire, all_time_high,
monthly_high, air_quality_hazard.
Jun 25: Siberia fire B+ ("burns deep" = declarative-consequence, peatland-carbon close, P_close
POSITIVE). Barrow AK B+ ("delivered nearly twice that total" = declarative annual-ratio, P_close
POSITIVE). Michigan monthly_low B ("cold air finds less land friction to slow it down" = mechanism-
only, failing). Taiz Jun 24 C+ ("pushing it into the terrain" = weakest mechanism close in corpus,
failing). Taiz Jun 25 B- ("push it upslope into the city basin" = transport mechanism, failing).
P_close now confirmed across 8 signal types (adding dust_event to the prior 7).
Jun 26: Amsterdam C+ ("not to absorb a month's rain in 72 hours" = implied-consequence, failing).
Anchorage B ("wring out moisture in compressed bursts" = mechanism-only, failing — weakest form).
Aktobe C+ ("three days here matched half a year's average" = declarative ratio, borderline — correct
form, setup too thin at 0.53% margin + "just edging" hedge). P_close now confirmed across 9 signal
types via Jun 26 (precipitation_extreme ×3 same cycle).
Jun 28: Mediterranean SST [4] B+ ("heat absorbed at the surface has nowhere fast to go" —
borderline positive; "fast" hedges slightly, compare Costa Rica A- "nowhere to drain"). Taiz
dust_event [3] C+ (mechanism-only, failing). Beaver Dams all_time_high [6] B+ ("little moisture
overhead to blunt the afternoon peak" = negation-of-blunter = implied, failing). Casper monthly_low
[7] B ("pushing lows well below what June air masses would otherwise deliver" = implied-consequence
framed as comparative, failing). Astana [5] steppe-incongruity close is not P_close territory.
P_close now confirmed across 10 signal types (adding regional_sst_anomaly via Mediterranean [4]).
Jun 29: marine_heatwave [2] A- ("a record set two years ago is already the floor of a new streak" =
declarative floor/ceiling reframe, POSITIVE). France reganom [3] B+ ("the heat debt compounds hour
by hour" = implied-consequence metaphor, failing). Congo fire [4] A- ("something has broken the
convective lid" = declarative physical consequence, POSITIVE). Prudhoe Bay [5] A- (latitude
peer-comparison close — not P_close territory; n/a). Amsterdam [6] A- ("there is nowhere for the
water to go" = declarative consequence, POSITIVE). P_close now confirmed across 11 signal types
(adding marine_heatwave [2] and regional_anomaly/reganom [3] via Jun 29).
**Last seen:** Jun 29 (3 positives, 1 failing, 1 n/a).

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
in the system-clause / second-sentence guidance section (near the "delete the system clause"
test already present from PR #85):

> When the second sentence closes on a mechanism, name the consequence directly — don't
> imply it, and don't stop at the mechanism. "Drain heat fast enough to frost gardens in
> June" beats "threaten gardens well into early summer." "Rain sheets across the surface"
> beats "sheets across the surface instead." "Cold pools here on clear nights, breaking
> June records" beats "tundra terrain offers no shelter from cold air pooling." The
> consequence lands in ≤5 words. Test: can you state it as a verb phrase (frost / flood /
> strand / kill / pool / fail)? If yes, do it. Mechanism without consequence is the C form;
> implied consequence is the B+ form; declarative consequence is the A form.

**Expected impact:** B+ → A- lift for ecosystem-specificity drafts where the mechanism is
correct but the close is soft. Jun 15 retroactive confirms: the gap is consistent across 5 A-
drafts from 4 signal types (precipitation_extreme, monthly_low, coral, fire-suppression).
The one A in the batch (Nauru) uses the declarative form directly.

**Status:** Drafted. Awaiting human implementation. Highest-leverage active proposal:
4 cycles of evidence (Jun 7/10/13/15), 5+ drafts, same gap to A across signal types.

### P_dust — Dust_event drafts lack calibrating comparison anchor

**Observed:** 2026-06-13 — Riyadh, Saudi Arabia dust_event (2,083 μg/m³, score 75)
reached pending with no comparison anchor. 2,083 μg/m³ is ≈ 139× the WHO PM2.5 daily
guideline (15 μg/m³) and ≈ 46× the WHO PM10 guideline (45 μg/m³) — an extraordinary
number that lands flat because the reference is unstated. Draft also includes aerosol
optical depth (0.61) the reader cannot calibrate. Second sentence ends on dispersal
("before heat-driven turbulence disperses it") — resolution of the mechanism, not
consequence. "Model-estimated" qualifier correctly flags source uncertainty; the WHO
multiple is always available as world knowledge regardless.

**Cycles observed:** Jun 13, Jun 17, Jun 25, Jun 28 (4 cycles; Jun 13 = Riyadh 2,083 μg/m³; Jun 17 =
Urumqi 2,260 μg/m³; Jun 25 = Taiz Jun 24 2,271 μg/m³ C+ + Taiz Jun 25 2,135 μg/m³ B- — all 4
corpus drafts through Jun 25 lack WHO calibration anchor; Jun 28 = Taiz [3] 728 μg/m³ C+ — 5th
dust_event corpus draft, no WHO anchor stated [728 ≈ 16× WHO PM10 limit, unstated], mechanism-only
P_close fail, 5th consecutive dust_event with identical opener structure). Jun 15 retroactive confirmed
the reference-frame gap is binding; WHO multiple transforms the grade from B/B- to A-.
**Template convergence confirmed:** all 5 dust_event corpus drafts share identical opener
structure ("[City]: model-estimated dust daily maximum of X µg/m³ on [date] — aerosol optical
depth at Y.") and AOD-only metric. Jun 24's Al Aḥmadī Kuwait (air_quality_hazard) stated the
WHO multiple (10.1×) — confirming the gap is specific to the dust_event signal type, not the
PM signal path generally.
**Last seen:** Jun 28. Taiz [3] C+ ("model-estimated dust daily maximum of 728 μg/m³ on June 27 —
aerosol optical depth at 0.77. Taiz sits at the southwest corner of the Arabian Peninsula where the
summer monsoon low pulls Red Sea and Arabian dust inland through the Tihama coastal plain" —
mechanism-only close, no WHO anchor, 728 ≈ 16× WHO PM10 limit unstated). Urumqi "traps it"
close remains the best dust_event close form; ceiling B- only because the WHO anchor is absent.

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
dust_event / air_quality framing section:

> For `dust_event` or `air_quality` signals, the WHO PM2.5 daily guideline (15 μg/m³) is
> always available as world knowledge — it requires no archive data. State the multiple.
> "Riyadh: 2,083 μg/m³ on June 13 — 139× the WHO daily limit" is the natural form. Do NOT
> include aerosol optical depth as a standalone metric unless you state what it means to a
> lay reader (>0.4 = hazy-to-hazardous; >1.0 = extreme). The second sentence should land
> a consequence, not describe dispersal — describing how dust clears is anti-climactic.
> Note: if the signal is model-estimated and no historical comparison is available, the WHO
> multiple IS the comparison. Use it.

**Expected impact:** Transforms dust_event drafts from opaque-number reports into
calibrated-violation framing. The WHO multiple is derivable from any bundle value — no
archive needed. One paragraph addition; no architectural change. Also applies to air_quality
(PM2.5/dust) signal type from the @extremetemps coverage lane. Verify whether
`writer_prompt.py` already has an air_quality framing section before adding a new paragraph.

Jun 30: Phalodi, India dust_event C+ + Taiz, Yemen dust_event C+ — both lack WHO anchor; both use identical opener structure. 6th and 7th consecutive dust_event corpus drafts without the calibrating comparison. No named humor mechanics deployed in either draft (P5 gap confirmed). Template convergence: all 7 dust_event corpus drafts share the opener structure. Phalodi: model-estimated PM2.5, aerosol optical depth stated without calibration. Taiz: same pattern, 3rd Taiz draft in corpus.
**Last seen:** Jun 30 (6 cycles: Jun 13/17/25/28/30 ×2; template convergence 7 of 7).

**Status:** Drafted. **6 cycles confirmed** (Jun 13/17/25/28/30 ×2); template convergence 7 of 7. Awaiting human implementation.

### P9 — precipitation_extreme opener template convergence + restate-math

**Observed:** 2026-06-18 — 2 of 2 fresh precipitation_extreme drafts share the same sentence-1
structure: "[City] received/recorded X mm in [timeframe] — [comparison]." Amsterdam draft
compounds with restate-math ("14.4 mm above a previous record of 300.0 mm"; margin is derivable
arithmetic). Jun 7 Barrow had the same restate-math ("63.8 mm above the previous 3-day record of
150.0 mm"). Three precipitation_extreme corpus drafts across 2 cycles — all 3 share the opener
template; 2 of 3 have restate-math. Same failure mode as P6 (fire) and P7 (coral, resolved),
appearing after just 3 drafts.

**Cycles observed:** Jun 7 (1 draft, restate-math; template baseline); Jun 18 (2 drafts, template
+ restate-math in Amsterdam); Jun 22 retroactive (Barrow 7-day: "127.5 mm above the previous 7-day
record of 300.0 mm" — P9 restate-math; template convergence confirmed: all 3 prior
precipitation_extreme corpus drafts share the "[City] received/recorded X mm in [timeframe] —
[comparison]" structure); Jun 25 (Barrow AK 213.8 mm/3-day B+: "beating the previous 3-day record
by 63.8 mm" = restate-math; opener "Barrow, Alaska accumulated 213.8 mm of rain in 3 days" —
same structure, verb varies "accumulated" vs. prior "received/recorded"); Jun 28 (Astana [5]);
Jun 26 (Amsterdam "received 157.1 mm in 3 days" + Aktobe "logged 150.8 mm over 3 days" +
Anchorage "received 183.8 mm in 3 days" — all 3 use template; verb varies "received"/"logged";
all 3 have restate-math: Amsterdam "7.1 mm above the previous 3-day record of 150.0 mm," Aktobe
"just edging the previous 3-day record of 150.0 mm," Anchorage "33.8 mm above the previous 3-day
record of 150.0 mm." Threshold artifact: all 3 cite 150.0 mm as the prior record — the detection
threshold. First 3-draft P9 batch in a single cycle.)
Jun 28: Astana [5] B+ ("Astana, Kazakhstan recorded 51.1 mm of rain on June 26 — against a
previous daily record of 3.9 mm, set earlier this same year." Opener template confirmed (9th
precipitation_extreme corpus draft using "[City] recorded/received X mm — [comparison]" structure).
No restate-math this time — "3.9 mm" is not a derivable margin but the prior record value stated
directly for contrast. Second sentence: "Aktobe and Almaty logged 50.2 mm and 43.2 mm the same day.
Astana sits in the driest interior of the Eurasian steppe." = steppe ecosystem-incongruity punchline.
51.1/3.9 mm = implicit 13× ratio, not named — ratio-as-punchline opportunity missed.)
Jun 29: Amsterdam [6] A- ("Amsterdam recorded 314.1 mm of rain in seven days through June 27 —
14.1 mm above the previous seven-day record of 300.0 mm." 10th precipitation_extreme corpus draft
using the template. Restate-math present: 14.1 = 314.1 − 300.0. P_precip_floor 2nd cycle: 4.7%
margin in wet-climate city. Despite shallow margin, declarative close "there is nowhere for the
water to go" carries A-.)
**Last seen:** Jun 29. 10 of 10 precipitation_extreme corpus drafts share the opener template;
8 of 10 have restate-math (Barrow Jun 18 daily — no restate-math; Astana Jun 28 — no restate-math;
all others have it).

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
precipitation_extreme framing section (or general record guidance): burn the default opener. Name
3 alternative sentence-1 forms:
1. **Period-and-restate:** "Amsterdam received 314.4 mm in 7 days. The previous record was 300.0 mm."
   (No margin arithmetic — let the two values speak.)
2. **Lead with mechanism or context first:** "The Rhine-Meuse delta has nowhere to put 314.4 mm in
   7 days. That is 14 mm past Amsterdam's previous record." (Context before number.)
3. **Preserve punchline placement when the comparator IS the joke:** "Barrow, Alaska recorded 71.2 mm
   of rain in a single day on June 16 — the previous daily record was 0.0 mm." (When the prior
   record is extraordinary, keep sentence 1 tight and make sentence 2 one declarative consequence.)

Also add explicit ban on restate-math form: "Do NOT state the derivable margin when both values are
present: '14.4 mm above a previous record of 300.0 mm' is three numbers where two suffice. Use
ratio form ('4.8% above the prior record') or period-and-restate."

**Expected impact:** Breaks the default opener for precipitation_extreme after just 3 drafts —
earlier intervention than P6 (fire, 3+ cycles before fix) and P7 (coral, resolved). Restate-math
ban reduces a recurring violation across signal types.

Jun 30: 3/3 fresh precipitation_extreme drafts (Astana B+, Antwerpen B+, Colorado B-) use the opener template and show restate-math. Astana: "Astana, Kazakhstan recorded 51.1 mm of rain on June 26 — against a previous daily record of 3.9 mm" (template confirmed; Astana previously appeared in Jun 28 without restate-math; Jun 30 Astana draft used margin arithmetic). Antwerpen: opener template + restate-math. Colorado: same pattern. 13 of 13 precipitation_extreme corpus drafts now on opener template; 10–11 of 13 have restate-math.
**Last seen:** Jun 30. 13 of 13 precipitation_extreme corpus drafts share the opener template.

**Status:** Drafted. First observation 2026-06-18. **Cycles observed: 9** (Jun 7, Jun 18, Jun 22 retroactive, Jun 25, Jun 26 ×3, Jun 28, Jun 29, Jun 30). Awaiting human implementation.

~~### P_new — Cold-record quality floor~~ → **[Archived 2026-06-21 — see Resolved section]**

### P5 — Name humor moves as available tools in writer_prompt.py

**Observed:** Apr 25-27 corpus — SYSTEM_PROMPT named only a subset of available moves;
Gemini converged on the most-explicit ones (era anchors). Unnamed mechanics (idiom-flip,
accelerating-warming, ecosystem specificity) appeared inconsistently. In the two-bot
context, the Sonnet writer also defaults to the most-stated patterns unless the full
palette is named.

**Cycles observed:** Apr 25, Apr 27, May 13, May 19 (4 cycles; era anchor over-deployment
+ mechanic convergence in v2 era; no named mechanics in fire drafts in two-bot era).
**Last seen:** Jun 28 (weak: steppe ecosystem-incongruity in Astana [5] deployed organically —
third-sentence "Astana sits in the driest interior of the Eurasian steppe" is a named
ecosystem-specificity move used without explicit prompting. Taiz dust_event [3] and Casper [7]
showed no named humor moves beyond mechanism. Same pattern as Jun 25/26/27: geographic categories
self-select their mechanics naturally; dust_event and monthly_low do not.
Prior Jun 26 note: Anchorage B chose orographic-stall mechanism as system clause organically;
Aktobe C+ deployed half-year aridity ratio as close naturally. All 3 precipitation_extreme;
all 3 used system-clause specificity without prompting. No named humor move beyond mechanism/ratio.
Prior Jun 25 note: Siberia fire B+ deployed peatland carbon + companion-fire peer comparison;
Barrow B+ used annual-precipitation ratio. Michigan monthly_low B and Taiz dust_event ×2 showed
no named humor moves. Same pattern across cycles: fire/precip categories self-select mechanics;
dust_event/monthly_low categories do not.
Jun 29: Full mechanic variety across 5 fresh drafts — floor/ceiling inversion (marine_heatwave),
ecosystem incongruity (Congo fire), latitude peer-comparison (Prudhoe Bay), declarative ecosystem
specificity (Amsterdam). Not one draft needed explicit P5 prompting; mechanics deployed organically.
3rd consecutive graded cycle where all deployed mechanics appeared without explicit naming.
Jun 30: 2 dust_event drafts (Phalodi + Taiz) graded C+ — both deploy zero named humor mechanics. Mechanism-only second sentences, no period-and-restate, no idiom-flip, no comic triple. 2nd consecutive dust_event cycle without a named mechanic across all corpus drafts in this category. Precipitation drafts (Astana/Antwerpen/Colorado) also show no named moves beyond mechanism-as-system-clause. Pattern confirmed: dust_event is the current gap category for P5; precipitation_extreme continues self-selecting mechanism without named humor moves.
Negative evidence accumulating: 5 consecutive fresh-draft cycles (Jun 7 / Jun 25-26 / Jun 27 / Jun 29 / Jun 30) show precipitation/fire named mechanics deploying naturally. P5 urgency split: fire/precip/record — organically deploying, low urgency; dust_event/monthly_low — confirmed gap, higher urgency.
**Last seen:** Jun 30 (dust_event confirming gap; precipitation + record categories deploying organically).)
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
`src/two_bot/prompts/writer_prompt.py`. Awaiting human implementation. Jun 15 retroactive
extends evidence to fire/hot10/dust categories; coral/record categories may not need it.

~~### P7 — Coral opener formula convergence~~ → **[Resolved 2026-06-15 — see Resolved section]**

~~### P8 — Snow/extreme record: ratio-as-punchline unused~~ → **[Resolved 2026-06-17 — see Resolved section]**

### P_compound — Compound-qualifier first sentence: choose archive OR margin, not both

**Observed:** 2026-06-28 — two record-type drafts in the same cycle open with both archive-depth
qualifier AND margin qualifier in one sentence. Beaver Dams UT all_time_high [6]: "Beaver Dams,
Utah hit 104°F (39.9°C) on June 25 — hottest daily maximum in 23 years of records, 15°F above
the 2020 mark." Casper WY monthly_low [7]: "Casper, Wyoming hit 27°F (-2.8°C) on June 25 —
coldest June low in 26 years of records, 3°F below the 2018 mark." Double-qualification dilutes
both data points: neither archive depth ("23 years of records") nor margin ("15°F above the 2020
mark") lands with full force when immediately followed by the other. The punchline is split, and
neither half is the punchline. Compare: Jun 15 retroactive Cope Rch TX A- ("hottest daily
maximum ever recorded, 1.5°F above the 2018 mark") — same structure, but "ever recorded" is a
stronger qualifier than "in 23 years" and 1.5°F margin is implicit-tight rather than stated-loose.

**Cycles observed:** Jun 28 (1 cycle; 2 of 5 fresh drafts in the same cycle — confirms the
pattern is structural, not coincidence in a single draft); Jun 29 (Prudhoe Bay [5] A-:
"hottest daily maximum in 24 years of records, 2°F above the 2024 mark" — same archive+margin
double-qualifier structure. Smaller margin (2°F) makes double-qualification less visible but
the structural pattern recurs in record-type openers. 2nd consecutive cycle with P_compound.);
Jun 30 (Prudhoe Bay all_time_high carry-over — same double-qualifier structure observed again
in the 3rd grading cycle where this draft appears. Pattern holds across grading cycles:
archive+margin double-qualifier is the default form for record-type openers.)
**Last seen:** Jun 30 (3 cycles; 3rd consecutive cycle where P_compound observed in record-type drafts).

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
record-type framing section:

> When stating a record: choose ONE qualifier per sentence — either the archive span ("23 years of
> records") OR the margin above the prior mark ("15°F above the 2020 mark"). Not both. Preferred
> form: "Beaver Dams, Utah hit 104°F on June 25 — 15°F above the previous record, set in 2020."
> Let the archive depth be implicit (the reader infers that a record being set means the archive
> was searched) or move it to sentence 2 as contrast. Stacking both in the same clause produces
> two half-punchlines; either one alone produces a full punchline.

**Expected impact:** Tighter record-type openers; B+ → A- path for drafts where mechanism is
already solid. Immediate two-observation confirmation within a single cycle suggests the
double-qualifier is a prompt-level default, not a one-off. Affects all_time_high, monthly_low,
monthly_high, country_record signal types where both archive depth and margin are available.

**Status:** Drafted. Awaiting human implementation. 2 cycles (Jun 28, Jun 29).

### P_precip_floor — Precipitation quality floor: writer over-passes shallow-margin signals

**Observed:** 2026-06-27 — Amsterdam precipitation_extreme (score 74, 157.1 mm / 3-day
record, 7.1 mm / 4.7% above prior record of 150.0 mm) reached pending with competent
ecosystem specificity (peat drainage, canal/pump infrastructure) but weak underlying
signal. The margin is editorially thin: a 4.7% improvement on a 3-day precipitation record
in a maritime European city (~820 mm annual rainfall) is not extraordinary by the bar
Andrew established for cold records (Mankato reject, May 2026: "weak signal, defensive
closer"). The writer and critic both passed this draft; voice execution quality did not
compensate for signal weakness. Same failure class as P_new: writer lacks a self-kill gate
for the marginally-above-threshold precipitation record in a wet-climate location.

Corpus comparison: Barrow, Alaska (Jun 7, 42.5% above record, Arctic permafrost drainage,
score 81) = B+; Amsterdam (Jun 27, 4.7% above record, maritime Europe, score 74) = C+.
The margin gap accounts for the grade gap, not voice execution.

**Cycles observed:** 2 (Jun 27; Jun 29 — Amsterdam [6] A-: 314.1 mm / 7d, 4.7% margin, sea-level
wet-climate city. Same percentage margin as Jun 27 Amsterdam C+ (157.1 mm / 3d, different
record window). Jun 29 Amsterdam earned A- via strong declarative close despite shallow margin —
confirms that voice execution can offset weak signal, but structural vulnerability persists.
Signal is thin relative to other precipitation_extreme A-grades: Barrow Jun 7 / Jun 22 both
had 42.5% margin. The 4.7% / wet-climate pattern has now recurred on a second Amsterdam draft.)
**Last seen:** 2026-06-29.

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
precipitation framing section:

> For `precipitation_extreme` signals: self-kill when ALL of the following are true:
> (a) margin above prior record is less than 10% (ratio < 1.10), (b) location is in a
> wet climate (>800 mm annual rainfall, maritime, or tropical). A 4.7% improvement on a
> 3-day precipitation record in Amsterdam — maritime Europe, ~820 mm/year, prior record
> 150.0 mm — is not extraordinary; archive depth is shallow relative to the signal's
> marginal nature. Use kill_reason: "shallow-margin precipitation record: insufficient
> editorial weight (< 10% improvement, wet-climate location)." Example that clears the
> bar: Barrow, Alaska (42.5% above record, Arctic permafrost drainage, score 81). Example
> that fails: Amsterdam (4.7% above record, maritime Europe, score 74).

**Expected impact:** Prevents the class of precipitation_extreme drafts that pass the
score gate but fail the human editorial bar. Mirrors P_new's cold-record quality floor.
Scoped to wet-climate locations only — does not affect arid or semi-arid stations where
any precipitation record may carry higher editorial weight.

**Status:** Drafted. 2-cycle evidence. Pattern recurred on a second Amsterdam draft. Jun 29
demonstrates voice can carry a shallow-margin draft to A-; the question is whether the
gate should block weak-signal precipitation records regardless of voice quality. Awaiting
human implementation. Signal types most at risk: European maritime cities, tropical coastal
cities, Pacific Northwest.

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

### A3 — Mediterranean SST threshold calibration gap (P_dust analog)

**Observed:** 2026-06-23 — Mediterranean SST regional_sst_anomaly draft (`draft_20260622_171200_17`) states "exceeds the 2.5°C tier threshold in NOAA CRW's basin-wide anomaly index" with no explanation of what the tier means. Analogous to P_dust's WHO PM2.5 calibration gap: extraordinary number (2.5°C tier) stated without telling the reader its significance. The NOAA CRW tier nomenclature (1.0°C / 2.0°C / 2.5°C / 3.0°C tiers correspond to successively rare basin-wide anomaly events) is not self-evident. Single observation — too thin for active proposal; filing for tracking.

**Cycles observed:** Jun 23 (1 cycle, 1 draft, 1 signal type).
**Last seen:** Jun 23.

**Watch for:** Future regional_sst_anomaly or ocean_sst drafts that state NOAA CRW tier thresholds without explaining the tier nomenclature. If 2+ cycles observed, promote to active proposal with P_dust-style fix: add NOAA CRW tier calibration as world-knowledge anchor ("2.5°C basin-wide anomaly = among the 5% rarest monthly deviations on record").

## Resolved (archive)

History of fixes that landed or became obsolete — added when a failure mode either held
for 3+ cycles without appearing, or when the target code was retired.

### [Archived 2026-06-17] P8 — Snow/extreme record: ratio-as-punchline unused

Last observed May 19 (1 cycle; 2/2 snow_extreme drafts). 4 fresh-draft grading cycles
without snow_extreme in the queue (Jun 7, Jun 13, Jun 15, Jun 17) — exceeds 3-cycle
threshold. No new snow_extreme drafts have appeared in the post-0.9.6.0 triage era;
the absence may be seasonal or score-gate. Reopen if snow_extreme drafts with ≥2×
ratio appear and still don't land the ratio as punchline.

### [Archived 2026-06-15] P7 — Coral opener formula convergence

Last observed: May 19 (8 of 9 coral drafts used accumulation formula). Jun 15 retroactive
batch: 2 coral drafts (Gilbert Islands, Nauru) both used alternative opener forms — colon-lead
and possession form respectively. Neither used the banned accumulation sentence. 3+ graded
cycles (Jun 7 n/a, Jun 13 n/a, Jun 15 counter-evidence) without observation; resolved. If the
formula reappears in future coral batches, re-open with the original fix spec (3 alternative
sentence-1 forms + DHW persistence exemplar from the May 19 corpus).

### [Archived 2026-06-21, 2nd archiving] P_new — Cold-record quality floor

Re-activated Jun 13 (Red Dog Mine, Alaska: 17yr archive, 1°F margin, above Arctic Circle —
all three kill criteria met; operator rejected). 3 consecutive fresh-draft cycles since then
without cold-record drafts (Jun 15 retroactive: no cold-record; Jun 17: dust_event only;
Jun 18: precipitation_extreme only) — meets the 3+ runbook threshold for archiving.
Reopen if `monthly_low` or `country_low` drafts with (a) < 20yr archive, (b) < 2°F margin,
(c) cold-climate location reappear in pending. The fix (self-kill gate in writer_prompt.py)
remains unimplemented; the absence is seasonal/triage-upstream, not a resolved failure mode.
Chesnee SC (35yr, 7°F, SE US) remains the counter-example: writer correctly passes strong signals.

### [Archived 2026-06-09, Re-activated 2026-06-13] P_new — Cold-record quality floor

Archived Jun 9 after 6 consecutive fresh-draft cycles without recurrence (May 15–19, Jun 7).
Re-activated Jun 13: Red Dog Mine, Alaska monthly_low (19°F, score 80, 17yr archive, 1°F
margin, above Arctic Circle) hit pending — all three kill criteria met. Archive note
condition ("Reopen if cold-record drafts with shallow archive + trivial margin reappear")
was satisfied. Full proposal text now in Active proposals section above. Chesnee SC
monthly_low (Jun 10, 35yr archive, 7°F margin, SE US) remains the clear counter-example
that the proposal correctly does NOT kill.

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
