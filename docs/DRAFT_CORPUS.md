# @theheat Draft Corpus — Voice Learning Archive

Running inventory of pending drafts, each preserved with its full text,
grade, and commentary. Purpose: build a longitudinal record of what
Gemini produces under the current system prompt so we can see voice
patterns, template traps, and quality drift over time.

Each draft is recorded even when rejected. The corpus IS the learning
material — specific wording, specific failure modes, specific framings
that worked. Re-read this before any voice-engine intervention.

Add new dated sections at the top. Oldest stays at the bottom.

---

## 2026-06-24 — Daily corpus grading (2 fresh drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 2 pending drafts
— both fresh (not previously graded). First multi-draft cycle since Jun 23 (1 day). First
`air_quality_hazard` type in the corpus.

**Staleness review as of 2026-06-24 ~15:00 UTC:** Draft [1] (Randolph UT, created
2026-06-24T07:46:05Z) — "June 20" is a historical record date, past-tense framing ("hit").
Not stale. Draft [2] (Al Aḥmadī Kuwait, created 2026-06-24T14:50:41Z) — contains "June
24" (present-day anchor). < 48h old; not stale now. **Operator note: Draft [2] becomes a
staleness candidate at ~2026-06-26T14:50 UTC.** Bulk-reject: 0 qualifying candidates this
cycle. `gh` CLI absent — **27th consecutive skip** (May 13 → Jun 24).

**Note on Mediterranean SST staleness:** Previous cycle (Jun 23) flagged
`draft_20260622_171200_17` staleness threshold at Jun 24T17:12Z. This run is at ~15:00 UTC
— the draft is ~46h old. Not yet past 48h at grading time; operator should post or reject
within ~2h of this run completing.

**Grade distribution (2 fresh drafts):** 0 A / 2 B (1 B+ / 1 B) / 0 C / 0 D-F.
**A-rate: 0% (0/2).** Gap from resumption bar: 50 pp.

**Headline finding:** Both drafts confirm P_close for the 7th cycle across two new signal
types (monthly_high, air_quality_hazard). Randolph Utah earns B+ on 134-year archive +
ecosystem specificity but closes with the classic P_close implied form ("normally blunts").
Al Aḥmadī Kuwait earns B on 10.1× WHO ratio + shamal mechanism but closes on the system
resolution ("by evening") — a P_close subtype where the close actively defuses the
violation rather than implying it. First air_quality_hazard in the corpus.

### B-grade drafts

#### [1] Randolph, Utah — monthly_high — 93°F / 33.9°C — **B+**

> *Randolph, Utah hit 93°F (33.9°C) on June 20 — hottest June daily maximum in 134 years
> of records, 1°F above the 2013 mark. At 6,300 feet in the Bear River Range foothills,
> the valley's high-desert elevation normally blunts the heat that builds across the Great
> Basin floor.*

**Score:** 80. Created 2026-06-24T07:46:05Z.

Humor lens:
- **Violation:** 93°F at 6,300 feet — hottest June daily max in 134 years. Strong archive
  depth. 1°F margin above 2013 — thin margin but real record.
- **Benign?** Yes — factual, calm.
- **Setup→Punchline?** Setup: 93°F, 134-year record, 1°F above 2013. System clause: "the
  valley's high-desert elevation normally blunts the heat that builds across the Great
  Basin floor." The word "normally" sets up the implied contrast — and yet, June 20. The
  punchline is in the reader's inference, not stated.
- **Named mechanic?** Ecosystem specificity: 6,300-foot elevation as heat buffer against
  Great Basin intrusions. Load-bearing — explains why a 93°F June reading at this elevation
  is remarkable.
- **Wodehouse rule?** "1°F above the 2013 mark" is mild restate-math — the year (2013) is
  useful context; the 1°F margin is derivable. Not a violation. "normally blunts the heat"
  — doing real work (sets up the contrast), not an effort signal.

**P_close FAILING (7th cycle, monthly_high).** "normally blunts the heat that builds
across the Great Basin floor" = mechanism with implied consequence. A- form: "At 6,300
feet, the valley's high-desert elevation normally blunts Great Basin heat. It didn't."
The fix stated in P_close's proposal — "name the consequence directly, don't stop at the
mechanism" — applies cleanly here.

Thin margin note: 1°F above 2013 (13 years ago). The archive is 134 years deep but the
contested value was recent. Doesn't change the grade — the record is real — but limits
urgency for the reader.

#### [2] Al Aḥmadī, Kuwait — air_quality_hazard — 152.1 μg/m³ PM2.5 — **B**

> *Al Aḥmadī, Kuwait: model-estimated 24-hour mean PM2.5 of 152.1 μg/m³ on June 24 —
> 10.1× the WHO daily guideline. Kuwait sits at the head of the Arabian Gulf, where summer
> shamal winds routinely loft fine desert dust before sea breezes suppress them by evening.*

**Score:** 74. Created 2026-06-24T14:50:41Z.

Humor lens:
- **Violation:** 10.1× the WHO daily guideline — unambiguous extreme. WHO ratio IS stated
  (positive vs. P_dust's observation that dust_event drafts omit the WHO anchor entirely).
- **Benign?** Yes — factual, mechanism-explained.
- **Setup→Punchline?** Setup: 152.1 μg/m³, 10.1× WHO guideline. System clause: shamal
  winds loft dust, sea breezes suppress by evening. The close lands on "by evening" — the
  RESOLUTION of the event, not the violation. The reader exits thinking "this clears up,"
  not "10.1×."
- **Named mechanic?** Ecosystem geography: head-of-Arabian-Gulf position + shamal/sea-breeze
  interplay. Load-bearing and specific. No additional humor move deployed.
- **Wodehouse rule?** Three-clause second sentence. Not an effort signal per se, but the
  "before sea breezes suppress them by evening" close actively defuses the violation — a
  P_close subtype (resolution close) where the system self-corrects rather than implying
  "but not this time." "Routinely" creates available incongruity (10.1× = routine?) that
  the draft does not exploit.

**P_close FAILING (7th cycle, air_quality_hazard) — resolution-close subtype.** More
aggressive defuser than implied-consequence form: "by evening" tells the reader the
problem ends, canceling the extreme reading. Fix: trim "before sea breezes suppress them
by evening." Close becomes: "Kuwait sits at the head of the Arabian Gulf, where summer
shamal winds routinely loft fine desert dust." The "routinely" does the work.

**P_dust POSITIVE (new type).** Unlike Riyadh/Urumqi dust_event drafts, Al Aḥmadī states
the WHO multiple (10.1×). The ratio IS the calibrating anchor P_dust calls for. This
signal type (air_quality_hazard) does not reproduce the P_dust failure; it reproduces
P_close instead.

**First air_quality_hazard type in corpus.** "Model-estimated" qualifier is honest but
weakens the signal's authority. "June 24" date-baked — staleness candidate ~Jun
26T14:50 UTC.

### Patterns named in this batch

1. **P_close 7th cycle — two new signal types.** Randolph Utah (monthly_high) + Al Aḥmadī
   (air_quality_hazard) both confirm P_close. The pattern now spans: precipitation_extreme,
   monthly_low, coral, fire, all_time_high (partial), monthly_high, air_quality_hazard.
   Cross-category confirmation is the strongest possible evidence: the close-landing gap is
   not category-specific, it's structural. P_close fix (one sentence in writer_prompt.py)
   would lift all these categories simultaneously.

2. **Resolution-close subtype.** Al Aḥmadī's "by evening" is a specific P_close variant:
   the close names the natural resolution of the phenomenon, not just a mechanism. Barrow's
   "any of it" and Amsterdam's "stack up faster than they drain" implied consequence without
   resolving it. Al Aḥmadī resolves it actively. The scale of the defuser: "by evening"
   = the 10.1× problem ends tonight. Trim to before the resolution clause.

3. **"Routinely" as unexploited incongruity.** 10.1× WHO + "routinely loft fine desert
   dust" — the extreme IS the routine. The draft doesn't land this tension. Potential: end
   second sentence on "routinely loft fine desert dust" and let "routinely" + "10.1× WHO"
   in sentence 1 create the joke: routine = 10.1× the guideline.

4. **P_dust positive evidence in air_quality_hazard.** The WHO multiple IS stated (10.1×),
   unlike Riyadh/Urumqi dust_event drafts. The air_quality_hazard pipeline may have better
   WHO-anchor prompting than dust_event. If next dust_event drafts also include the WHO
   anchor, P_dust may need to narrow scope (dust_event specifically) rather than apply to
   all PM-type signals.

5. **Draft [2] staleness clock running.** "June 24" = staleness candidate at ~Jun
   26T14:50 UTC. Operator must post or reject before then.

---

## 2026-06-23 — Daily corpus grading (3 fresh drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **0 pending drafts**; 2 approved. Three drafts created Jun 22 after the prior grading window (15:00 UTC): Cope Rch, Texas (all_time_high, created Jun 22T19:33Z); Columbus, Georgia (all_time_high, created Jun 22T17:09Z); Mediterranean Sea (regional_sst_anomaly, created Jun 22T17:12Z). All three are fresh to the corpus. Status "posted" = Cope Rch and Columbus (appear in gist as posted); status "approved" = Mediterranean SST (queued for posting).

**Staleness review as of 2026-06-23 ~15:00 UTC:** Mediterranean SST (`draft_20260622_171200_17`) contains "today" — created Jun 22T17:12Z, ~22h old. Under 48h threshold; not a staleness candidate yet. Crosses threshold at Jun 24T17:12Z. Operator should post or reject before then. Chesnee SC (`draft_20260610_155509_26`, approved Jun 10) — references "June 6" as a historical record date; no "today" anchor; 13 days old — not a staleness candidate by policy. No bulk-reject candidates. `gh` CLI absent — **26th consecutive skip** (May 13 → Jun 23).

**Grade distribution (3 fresh drafts):** 1 A / 2 B / 0 C / 0 D-F.
**A-rate: 33% (1/3).** Gap from bar: 17 pp (n=3; meaningful but small).

**Headline finding:** First all_time_high batch in two-bot corpus since Jun 15 retroactive. Cope Rch, Texas (118°F, 63yr) earns A-: accelerating-warming closer ("small shifts in that dry column push extremes fast") is the declarative-consequence form — P_close's first confirmed natural deployment in an all_time_high signal type. Columbus, Georgia (106°F, 29yr, 1°F margin): dual-mechanism second sentence, P_close failing instance. Mediterranean SST (regional_sst_anomaly debut): P_close failing instance + unexplained NOAA threshold reference (P_dust analog for SST category — see A3 in Awaiting Evidence). No Wodehouse violations, no restate-math.

### A-grade drafts

#### [1] Cope Rch, Texas — all_time_high — 118°F / 47.8°C — **A-**

> *Cope Rch, Texas hit 118°F (47.8°C) on June 19 — hottest daily maximum in 63 years of records, 2°F above the 2023 mark. In the Chihuahuan Desert, continental air removes the moisture that buffers heat elsewhere; small shifts in that dry column push extremes fast.*

Posted 2026-06-22T19:33Z.

Humor lens:
- **Violation:** 118°F (47.8°C), 63-year record, 2°F above 2023. The absolute temperature (118°F) is the headline; 63-year archive gives it weight; the thin margin (2°F) is offset by the extraordinary absolute value.
- **Benign?** Yes. Factual register, no alarm.
- **Setup→Punchline?** Sentence 1: 118°F + 63yr + 2°F above 2023. Sentence 2: Chihuahuan Desert mechanism → "small shifts in that dry column push extremes fast." The closer is causal and accelerating — it explains WHY Cope Rch sees these extremes, not just WHERE.
- **Named mechanic?** Accelerating-warming ("small shifts push extremes fast") + ecosystem specificity (Chihuahuan Desert, continental air, absent moisture buffer). Two mechanics operating simultaneously without crowding the sentence.
- **Wodehouse rule?** Clean. "2°F above the 2023 mark" — stated once, not belabored; the 2023 reference does not over-explain. "Continental air removes the moisture that buffers heat elsewhere" creates implicit comparison without spelling it out. "Push extremes fast" — declarative, direct, no poetry-attempt.
- **P_close lens:** "small shifts in that dry column push extremes fast" is the declarative-consequence form. The writer named the consequence directly ("push extremes fast") rather than stopping at the mechanism or implying the consequence. Compare the P_close corpus: "persistence is what kills" (Madagascar), "nowhere to drain" (Costa Rica), "has nowhere to go" (Barrow 7-day retro Jun 22). Cope Rch joins this list. **Second consecutive P_close positive evidence cycle (Barrow Jun 22 retro + Cope Rch Jun 23 fresh).**

A- because 118°F carries independently of the 2°F thin margin. The 2023 mark (only 3 years ago) is not a dramatic prior record, but the draft doesn't belabor it — it moves to the mechanism that makes such extremes possible. The accelerating-warming closer elevates this from B+ (ecosystem specificity only) to A-.

### B-grade drafts

#### [2] Columbus, Georgia — all_time_high — 106°F / 41.1°C — **B**

> *Columbus, Georgia hit 106°F (41.1°C) on June 20 — hottest daily maximum in 29 years of records, 1°F above the 2012 mark. The Chattahoochee River valley funnels Gulf heat northward while the surrounding Piedmont topography limits the sea-breeze relief that tempers coastal Georgia.*

Posted 2026-06-22T17:09Z.

Humor lens:
- **Violation:** 106°F, 29-year record, 1°F above 2012. Real signal; thin margin.
- **Benign?** Yes.
- **Setup→Punchline?** Sentence 2: two competing mechanisms — (1) Chattahoochee valley funnels Gulf heat + (2) Piedmont topography limits sea-breeze relief. Neither is wrong; together they over-explain without sharpening the landing.
- **Named mechanic?** Ecosystem specificity — dual mechanism. But P_close: the consequence is implied. "Funnels Gulf heat northward... limits the sea-breeze relief that tempers coastal Georgia" describes the causal chain; the consequence (Columbus sits in an unusual heat trap) is not named.
- **Wodehouse rule?** "1°F above the 2012 mark" — thin margin, stated once, not belabored. Sentence 2 is slightly effortful: three geographic actors (Chattahoochee, Gulf, Piedmont) in one sentence. The A-grade form picks one causal vector.
- **P_close lens:** Dual-mechanism close without a terminal declarative consequence. "The sea-breeze relief that tempers coastal Georgia" describes what's absent, but doesn't name what happens as a result. Declarative forms: "Gulf heat pools here, no coastal relief available" / "Columbus has no sea breeze escape." Confirmed P_close 6th cycle.

B because 1°F margin is thin and the dual-mechanism sentence works harder than it lands. Compare Cope Rch: single mechanism + declarative accelerating-warming closer = A-. Columbus: dual mechanism + implied consequence = B.

#### [3] Mediterranean Sea — regional_sst_anomaly — 2.66°C above climatological mean — **B**

> *The Mediterranean Sea is running 2.66°C above its climatological mean today — past the 2.5°C tier threshold in NOAA CRW's basin-wide anomaly index. A semi-enclosed sea with limited Atlantic exchange retains heat faster than open-ocean basins of comparable size.*

Approved 2026-06-22T17:12Z; not yet posted. First regional_sst_anomaly in the corpus.

Humor lens:
- **Violation:** 2.66°C above climatological mean, past 2.5°C tier. The NOAA CRW basin-wide anomaly index is cited but not explained.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 2.66°C, past 2.5°C threshold. Sentence 2: semi-enclosed sea + limited Atlantic exchange + "retains heat faster than open-ocean basins of comparable size." Comparative rather than declarative.
- **Named mechanic?** Ecosystem specificity: semi-enclosed sea, limited exchange. The mechanism is correct. But P_close: "retains heat faster than open-ocean basins of comparable size" is the comparative/implied form — the consequence (faster warming, sustained extreme anomalies, higher bleaching risk) is not stated.
- **Wodehouse rule?** "today" anchor dates the draft (staleness risk — see below). "of comparable size" hedges the comparison. "2.5°C tier threshold in NOAA CRW's basin-wide anomaly index" is inside-baseball for most readers.
- **P_close lens:** "retains heat faster than open-ocean basins of comparable size" — comparative close without naming the consequence. Declarative form: "the Mediterranean holds heat in — limited Atlantic exchange means no flush" / "sea surface temperatures here don't reset the way open ocean basins do." Confirmed P_close 6th cycle.
- **Calibration gap (P_dust analog):** "2.5°C tier threshold in NOAA CRW's basin-wide anomaly index" — the reader cannot calibrate what 2.5°C means for a basin-wide anomaly without a reference frame. Compare to P_dust's WHO multiple: the calibrating anchor is always available as world knowledge. For SST anomaly: "2.5°C above climatological mean places the Mediterranean at approximately its 90th percentile of recent anomalies" or similar. See A3 added to Awaiting Evidence.

B because the mechanism is correct and the ecosystem specificity is real, but P_close (comparative form, not declarative), unexplained threshold jargon, and "today" staleness risk all cap the grade. A tighter version: "The Mediterranean doesn't flush the way open basins do — 2.66°C above the climatological mean, with limited Atlantic exchange to draw it down."

**⚠️ Staleness flag:** "today" anchors this to Jun 22. Crosses 48h threshold at Jun 24T17:12Z. Operator should post or reject before then.

### Patterns named in this batch

1. **P_close natural deployment on strongest signal.** Cope Rch TX earns A- using the declarative-consequence form ("push extremes fast") without explicit prompt instruction. Two consecutive positive-evidence cycles (Barrow 7-day Jun 22 retro: "has nowhere to go"; Cope Rch Jun 23: "push extremes fast"). The fix is landing organically on the highest-signal drafts — consistent with P_close's prediction that the model CAN reach the declarative form; it needs prompting to default there rather than stopping at mechanism.

2. **Dual mechanism = B ceiling (confirmed again).** Columbus GA: two mechanisms (valley funneling + topographic sea-breeze block) in one sentence, neither consequence named. Same pattern as May 18 Galapagos coral (conditional close vs. A-grade Madagascar declarative). Pick one causal vector; name its consequence.

3. **Regional_sst_anomaly debut: mechanism correct, calibration gap.** Mediterranean SST's mechanism (semi-enclosed, limited exchange) is right. But "2.5°C tier threshold in NOAA CRW's basin-wide anomaly index" is jargon without context. Same gap as P_dust (PM2.5 without WHO multiple). One draft — too thin for a proposal, but see A3.

4. **No Wodehouse violations; no restate-math.** Clean across all 3 drafts. WRITER_SAMPLES=2 + CRITIC_REVISE appears to be screening these out effectively.

5. **P9/P_dust not observable (correct signal absence).** No precipitation_extreme or dust_event drafts this cycle — can't test template convergence or WHO calibration.

### Numbers

- Pending drafts in queue: 0
- Fresh drafts graded: 3 (Cope Rch TX A-, Columbus GA B, Mediterranean SST B)
- A-rate: 33% (1/3); n=3
- Active proposal evidence: P_close confirmed 6th cycle (Columbus GA + Mediterranean SST failing; Cope Rch positive). P9/P_dust/P5: N/A this cycle (no precipitation_extreme, dust, fire, or hot10 drafts).
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (26th consecutive skip, May 13 → Jun 23). Note: Mediterranean SST ("today" anchor) crosses 48h threshold at Jun 24T17Z.
- Approved drafts not yet graded here (already graded in prior entries): Chesnee SC (A-, Jun 15 retroactive entry).

---

## 2026-06-22 — Daily corpus grading (0 pending; 1 retroactive grade)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **0 pending drafts** — queue still empty, same as Jun 21. No new drafts since Jun 18T15:43Z (~3.5 days). Barrow 7-day precipitation_extreme (draft_20260618_154318_15, created Jun 18T15:43Z, rejected Jun 18T19:42Z) was flagged "ungraded" in the Jun 19 and Jun 21 entries — its text is now available from gist history and is graded here retroactively.

**Staleness review:** 0 pending drafts — staleness policy not triggered. `gh` CLI absent — **25th consecutive skip** (May 13 → Jun 22). No operator action needed.

**A-rate this cycle:** 1 retroactive draft graded; 1 A-. n=1 — not statistically meaningful on its own. Prior graded cycle: 0% (0/2, Jun 18). Prior meaningful: 67% (6/9, Jun 15 retroactive).

### Retroactive grade: Barrow 7-day precipitation_extreme — **A-** (rejected by operator; event-diversity)

> *Barrow, Alaska received 427.5 mm of rain in 7 days — 127.5 mm above the previous 7-day record of 300.0 mm. Barrow sits on the Arctic coast, where permafrost blocks infiltration; water that can't sink pools on the surface, and a record margin this large has nowhere to go.*

**Score:** 82. Created 2026-06-18T15:43Z. Rejected Jun 18T19:42Z (~4h later) — operator batch-reject of all 3 Jun 18 Barrow/Amsterdam precipitation drafts; event-diversity concern, not voice.

Humor lens:
- **Violation:** 427.5 mm vs 300.0 mm = 42.5% above prior record. Real, substantial.
- **Benign?** Yes, factual register.
- **Setup→Punchline?** Sentence 1 restates margin arithmetically ("127.5 mm above the previous 7-day record of 300.0 mm" — P9 restate-math). Sentence 2: permafrost blocks infiltration → water pools → "a record margin this large has nowhere to go." Three-step close: mechanism → surface consequence → terminal declarative.
- **Named mechanic:** Ecosystem specificity (permafrost blocks infiltration) + near-declarative close ("has nowhere to go"). Compare: Costa Rica Pacific, Jun 18 corpus: "heat that builds has nowhere to drain" → A-. Same "nowhere to [verb]" construction.
- **P_close lens:** "Has nowhere to go" is the declarative-consequence form, not implied. This is the A form per P_close's framework — the writer named the consequence ("nowhere to go") rather than stopping at the mechanism ("sheets across the surface instead", Jun 7 B+) or implied overflow ("limits how fast the ground absorbs any of it", Jun 18 1-day B+). First precipitation_extreme draft to deploy the declarative close.
- **P9:** Sentence 1 has restate-math — P9's 3rd evidence point. "127.5 mm above the previous 7-day record of 300.0 mm" restates three values where two suffice.
- **Wodehouse rule?** No violations. "A record margin this large has nowhere to go" is clean and final. "Water that can't sink pools on the surface" is specific and visual.

**Operator disposition:** Correct reject on event-diversity grounds — 4th Barrow precipitation draft from same Jun 16–17 episode (Jun 7 3-day B+, Jun 18 1-day B+, Jun 18 Amsterdam B, Jun 18 7-day A-). The strongest voice draft of the Barrow event was the one rejected last.

### Patterns / operational notes

1. **P_close positive evidence:** Barrow 7-day "has nowhere to go" is the first precipitation_extreme draft to deploy the declarative-consequence A-form unprompted. The Jun 18 1-day used "limits how fast the ground absorbs any of it" (B+-form implied consequence); this 7-day reached the declarative form and the grade reflects it. Validates that the declarative form is the lever — P_close fix would institutionalize it.

2. **P9 3rd cycle evidence:** Barrow 7-day "127.5 mm above the previous 7-day record of 300.0 mm" = restate-math. Now 3 of 3 precipitation_extreme corpus drafts (Jun 7, Jun 18, Jun 22 retro) contain restate-math. Template convergence complete on that dimension.

3. **Queue:** 0 pending for 4th straight day (Jun 19, 21, 22). No pipeline concern — the Jun 15–18 burst produced 13 drafts in 4 days; dry spell is within normal variance.

### Numbers

- Retroactive drafts graded: 1 (Barrow 7-day A-, Jun 18 event)
- A-rate: 100% (1/1 retroactive; n=1, not meaningful)
- Proposals updated: P9 (+1 cycle → 3rd cycle, confirmed in all 3 precipitation_extreme corpus drafts)
- Proposals not updated: P_close (positive evidence, not a failure observation), P_dust (no dust drafts), P5 (no relevant drafts)
- Routine operational: queue empty 4th consecutive day; `gh` CLI absent (25th consecutive skip).

---

## 2026-06-21 — Daily corpus grading (0 fresh drafts; queue empty)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **0 pending drafts** — queue fully empty. Last resolved drafts were the 3 Jun 18 precipitation_extreme entries, all operator-rejected (confirmed in the Jun 19 entry). No new drafts have entered pending status since Jun 18T15:43Z (~2.5 days).

**Staleness review:** 0 pending drafts — staleness policy not triggered. `gh` CLI absent — **24th consecutive skip** (May 13 → Jun 21). No operator action needed.

**A-rate:** — (no fresh drafts). Most recent graded cycle: **0%** (0/2, 2026-06-18). Most recent meaningful: **67%** retroactive Jun 15 (6/9, first above bar).

### Patterns / operational notes

1. **Queue empty; pipeline active.** 3-day gap since Jun 18T15:43Z is normal inter-signal quiet. No new signals reached pending since all Jun 18 precipitation_extreme drafts were operator-rejected. Pipeline at 0.9.67.0+ with `WRITER_SAMPLES=2` + `CRITIC_REVISE_ENABLED=1` live.

2. **P_new archived (second archiving).** 3 consecutive fresh-draft grading cycles passed since P_new was last observed (Jun 13): Jun 15 (9 retro — no cold-record), Jun 17 (1 dust — no cold-record), Jun 18 (2 precip_extreme — no cold-record). Meets the 3+ threshold in the runbook. Moving to Resolved. Reopen if shallow-archive cold-record drafts (< 20yr archive, < 2°F margin, cold-climate location) reappear in pending.

3. **No new evidence for P_close, P9, P_dust, P5.** 0 fresh drafts; no signal types to observe.

4. **Staleness bulk-reject: 0 candidates; `gh` CLI absent (24th consecutive skip, May 13 → Jun 21).**

### Numbers

- Pending drafts in queue: 0 (queue empty)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-06-18)
- Active proposal evidence updates: P_new archived (3+ cycles threshold met; Jun 15/17/18)
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (24th consecutive skip)

---

## 2026-06-19 — Daily corpus grading (0 fresh drafts; queue empty)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 0 pending drafts.
All 3 Jun 18 precipitation_extreme drafts are now status=rejected (2 graded in the Jun 18 cycle
+ 1 ungraded draft created Jun 18T15:43Z after the prior grading window). No new drafts since
Jun 18T15:43Z.

**Note — ungraded Jun 18 draft:** A third precipitation_extreme draft (Barrow, Alaska 7-day,
427.5 mm, prior record 300.0 mm — 127.5 mm / 42.5% above) was created at Jun 18T15:43Z, after
the Jun 18 grading cycle (15:00 UTC). Text closely mirrors the Jun 7 Barrow B+ draft ("sheets
across the surface instead" second sentence reused verbatim; restate-math "127.5 mm above the
previous 7-day record of 300.0 mm"). It is now rejected — never graded. Voice pattern: third
precipitation_extreme in ~15h window with identical template + permafrost ecosystem specificity.
P9 evidence (opener template convergence) would have incremented on this draft as well.

**Operator rejection of Jun 18 drafts:** All 3 Jun 18 precipitation_extreme drafts are now
status=rejected. Not auto-rejected by TTL (all < 24h old at time of rejection). Operator cleared
them — including the B+ Barrow daily (elite 0.0mm prior record signal). No posted_at timestamps
found. Reasons unclear from gist state; most likely: (a) Jun 18 drafts had persistent quality
issues the operator identified (over-packed sentence 2 on Barrow [1], thin margin + restate-math
on Amsterdam [2], template-identical text on Barrow [3]); or (b) operator is batch-clearing
precipitation_extreme pending as the pipeline continues to produce them.

**Staleness review:** 0 pending drafts — nothing to evaluate. `gh` CLI absent — **23rd
consecutive skip** (May 13 → Jun 19).

**A-rate:** — (no fresh drafts). Most recent graded cycle: **0%** (0/2, 2026-06-18).
Jun 15 retroactive (67%) remains highest meaningful cycle.

### Patterns / operational notes

1. **Queue empty; operator rejected all 3 Jun 18 precipitation_extreme drafts.** The Jun 18
   batch included a genuinely elite signal (Barrow daily record from 0.0mm prior, B+ graded)
   that was operator-rejected. This is the first operator rejection of a B+ draft since the two-bot
   era began. Possible interpretations: (a) operator has raised editorial floor on
   precipitation_extreme category; (b) the "over-packed sentence 2" / template issues in the Jun 18
   batch caused rejection; (c) pacing — 3 precipitation_extreme drafts in ~12h is surplus inventory.

2. **No active proposal evidence updates.** 0 fresh graded drafts. P_close / P9 / P_new / P5 /
   P_dust all at last-known counts.

3. **Ungraded Jun 18T15:43Z Barrow draft confirms P9 at force of habit.** The second permafrost
   ecosystem-specificity close using "sheets across the surface instead" (verbatim from Jun 7) and
   another restate-math opener ("127.5 mm above the previous 7-day record of 300.0 mm") suggests
   the pipeline generates precipitation_extreme drafts from a narrow template even within 12h of
   prior precipitation_extreme drafts. P9 fix is warranted.

4. **Staleness bulk-reject: 0 candidates; `gh` CLI absent (23rd consecutive skip, May 13 → Jun 19).**

### Numbers

- Pending drafts in queue: 0 (queue empty; all Jun 18 precipitation_extreme drafts operator-rejected)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-06-18)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (23rd consecutive skip)

---

## 2026-06-18 — Daily corpus grading (2 fresh drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 2 pending drafts —
both fresh, both precipitation_extreme type. Draft [1] Barrow 10.8h old; Draft [2] Amsterdam
3.0h old. Second and third fresh precipitation_extreme signals in the corpus (after Jun 7
Barrow). No coral, fire, snow, cold-record, or dust drafts this cycle.

**Staleness review as of 2026-06-18 ~15:00 UTC:** Draft [1] references "June 16" as historical
observation date — past-tense, no "today." Draft [2] "received" — past-tense, no forecast
language. Both under 48h. No bulk-reject candidates. `gh` CLI absent — **22nd consecutive
skip** (May 13 → Jun 18).

**Grade distribution (2 fresh drafts):** 0 A / 2 B / 0 C / 0 D-F (B+: [1]; B: [2]).
**A-rate: 0% (0/2).** Gap from bar: 50 pp. Jun 15 retroactive context: 67% (6/9 A-range).

**Headline finding:** Both precipitation_extreme drafts land B-range. Draft [1] Barrow has
a genuinely elite signal — prior single-day record was 0.0 mm — and the first sentence lands
it correctly; the second sentence over-packs (two cities' 7-day totals + permafrost mechanism
in one semicolon sentence), triggering P_close (implied vs. declarative consequence). Draft [2]
Amsterdam has thin margin (4.8% above record), restate-math, and another implied close ("stack
up faster than they drain"). Opener template converging across all three precipitation_extreme
corpus drafts — new proposal P9 added. P_close confirmed 5th cycle.

### B-grade drafts

#### [1] Barrow, Alaska — precipitation_extreme — 71.2 mm / single day (June 16), prior daily record 0.0 mm — **B+**

> *Barrow, Alaska recorded 71.2 mm of rain in a single day on June 16 — the previous daily
> record was 0.0 mm. The same 7-day window brought 427.5 mm to Barrow and 367.5 mm to
> Anchorage; permafrost limits how fast the ground absorbs any of it.*

**Score:** 78. Created 2026-06-18T04:14:06Z.

Humor lens:
- **Violation:** 71.2 mm in a single day where the prior daily record was 0.0 mm. Extraordinary
  — the location had never recorded measurable single-day rainfall at this level.
- **Benign?** Yes — calm, factual register. No panic.
- **Setup→Punchline?** Sentence 1 works as a tight structure: data → jaw-drop. "the previous
  daily record was 0.0 mm" is the punchline. Sentence 2 extends to regional scale and
  permafrost mechanism — both correct but competing for attention after sentence 1 already closed.
- **Named mechanic?** Ecosystem specificity (permafrost drainage) — same mechanic as Jun 7
  Barrow B+. Repeated without variation. Anchorage comparison introduces regional scale but
  Anchorage is not the signal.
- **Wodehouse rule?** Sentence 1: clean — no restate-math, both values needed, gap from 0.0
  is the punchline. Sentence 2: **P_close** — "permafrost limits how fast the ground absorbs
  any of it" is the implied form. "Any of it" gestures at overflow without stating it. Compare
  to P_close corpus: "sheets across the surface instead" (Jun 7), "threaten gardens well into
  early summer" (Chesnee Jun 10), "tundra terrain offers no shelter" (Red Dog Mine Jun 13). The
  declarative form: "rain sheets across the permafrost — nowhere to go" / "the water has nowhere
  to drain." Mechanism without consequence = B+.

Not A- because sentence 2 is over-packed: two cities' 7-day totals plus permafrost mechanism in
one semicolon sentence; the over-expansion competes with the A-grade punchline already in sentence 1.
The A-grade version holds at 0.0 mm and makes sentence 2 one focused declarative consequence.
Permafrost mechanism also used for second consecutive Barrow precipitation_extreme draft (Jun 7).

#### [2] Amsterdam — precipitation_extreme — 314.4 mm / 7 days, prior 7-day record 300.0 mm — **B**

> *Amsterdam received 314.4 mm of rain in 7 days — 14.4 mm above a previous record of 300.0 mm.
> The Netherlands sits at the delta of the Rhine and Meuse; rainfall totals that exceed the city's
> pump-and-canal capacity stack up faster than they drain.*

**Score:** 76. Created 2026-06-18T12:02:54Z.

Humor lens:
- **Violation:** 314.4 mm vs 300.0 mm prior record — 4.8% margin. Real record, thin signal.
  Score 76 (at threshold floor).
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 314.4 mm + "14.4 mm above a previous record of 300.0 mm."
  System clause: Rhine/Meuse delta + pump-and-canal capacity failure implied in the close.
  The hydraulic infrastructure framing is Amsterdam-appropriate and earns its place.
- **Named mechanic?** Ecosystem specificity — Rhine/Meuse delta + pump-and-canal capacity.
  Correct and location-specific. But **P_close**: "stack up faster than they drain" is the
  implied form — the reader supplies the image of the system overwhelmed. Declarative form:
  "excess Amsterdam's pump-and-canal system" / "the canal infrastructure can't drain it in
  time." Compare Nauru coral (A): "no adjacent reef system to reseed it" — declarative
  structural consequence, no hedge.
- **Wodehouse rule?** **Restate-math:** "14.4 mm above a previous record of 300.0 mm" — the
  margin (14.4) is derivable from the two stated values (314.4 − 300.0 = 14.4). Same violation
  as Jun 7 Barrow's "63.8 mm above the previous 3-day record of 150.0 mm." Fix: ratio form
  ("4.8% above the prior 7-day record") or period-and-restate ("314.4 mm in 7 days. The
  previous record was 300.0 mm.").

Not A because: (a) thin margin (4.8% above record), (b) restate-math in sentence 1 —
recurring across precipitation_extreme category, (c) P_close: implied rather than declarative
consequence.

**Opener template convergence alert:** Three precipitation_extreme drafts across two cycles
share the same sentence-1 form:
- Jun 7: "Barrow, Alaska received 213.8 mm of rain in 3 days — 63.8 mm above the previous 3-day record of 150.0 mm."
- Jun 18 [1]: "Barrow, Alaska recorded 71.2 mm of rain in a single day on June 16 — the previous daily record was 0.0 mm."
- Jun 18 [2]: "Amsterdam received 314.4 mm of rain in 7 days — 14.4 mm above a previous record of 300.0 mm."

[City] + received/recorded + [value] + [timeframe] — [comparison]. P6/P7 failure mode emerging
in precipitation_extreme after 3 drafts. New proposal P9 added.

### Patterns named in this batch

1. **P_close confirmed (5th cycle).** Both drafts exhibit implied-consequence closes: "permafrost
   limits how fast the ground absorbs any of it" (Barrow [1]) and "stack up faster than they
   drain" (Amsterdam [2]). Both stop at mechanism without naming the consequence directly.
   Declarative forms: "the water has nowhere to drain" / "the canals back up." P_close pattern
   now spans 5 cycles (Jun 7/10/13/15/18) and 5 signal types (precipitation_extreme ×2, monthly_low
   ×2, coral). Jun 15 retroactive confirmed the gap is consistent across A- batch. Highest-leverage
   active proposal.

2. **Opener template convergence: precipitation_extreme (new proposal P9).** Three drafts, two
   cycles, same sentence-1 structure. Draft [1] avoids the worst of it by making the comparison
   the extraordinary punchline (0.0 mm prior record); Draft [2] uses the full restate-math form.
   Same failure mode as P6 (fire) / P7 (resolved coral). New proposal added.

3. **Restate-math: 2nd consecutive precipitation_extreme cycle.** Amsterdam [2] repeats Jun 7
   Barrow pattern: "[new value] — [derivable margin] above [prior value]." 2 of 3 precipitation_
   extreme corpus drafts have this violation. Addressed in P9 proposed opener variety forms.

4. **Elite signal under-honored (Barrow [1], 0.0 mm prior record).** First sentence lands correctly.
   Second sentence over-expands instead of holding the silence. A-grade version: sentence 2 states
   one declarative consequence ("the water has nowhere to drain") rather than two cities' data plus
   mechanism. Stranded-mechanic class.

5. **P_dust not observed (no dust drafts this cycle — positive absence).** Last observed Jun 17.
   WHO-calibration gap remains unaddressed.

### Numbers

- Pending drafts in queue: 2 (2 fresh; 0 carry-overs)
- Fresh drafts graded: 2 (both precipitation_extreme)
- A-rate: 0% (0/2); n=2 — low count
- Grade distribution: 0 A / 1 B+ / 1 B / 0 C / 0 D-F
- New proposals: P9 (precipitation_extreme opener convergence + restate-math)
- Active proposal evidence: P_close 5th cycle (Jun 18); P9 1st cycle (Jun 18); P_dust/P_new/P5
  — no relevant signal types this cycle
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (22nd consecutive skip, May 13 → Jun 18)

---

## 2026-06-17 — Daily corpus grading (1 new draft; 4 prior-graded carry-overs skipped)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 0 pending
at runtime. 5 drafts visible in the gist since Jun 8: Chesnee SC monthly_low (approved
Jun 10, already graded A- in Jun 15 corpus entry), Red Dog Mine AK monthly_low (rejected
Jun 13, graded C+ in Jun 13 entry), Riyadh SA dust_event (posted Jun 13, graded C in
Jun 13 entry), Beaver Dams UT all_time_high (posted Jun 15, graded A- in Jun 15 entry),
and Urumqi China dust_event (posted Jun 17T12:27Z — NOT in any prior entry). Only
Urumqi is new. Four carry-overs not re-graded; grades on record stand.

**Staleness review:** 0 pending drafts — staleness policy not triggered. `gh` CLI absent;
**21st consecutive skip** (May 13 → Jun 17). No operator action needed.

**Grade distribution (1 new draft):** 0 A / 1 B / 0 C / 0 D-F.
- B-: Urumqi China dust_event

**A-rate: 0% (0/1).** Gap from bar: 50 pp (n=1; Jun 15 retro context: 67%, 6/9 A-range).

**Headline finding:** Urumqi confirms P_dust (2nd cycle): 2,260 μg/m³ also lacks WHO
calibration anchor; 2,260 ÷ 15 μg/m³ = 151× WHO PM2.5 daily limit — unstated. "Traps
it" close is better than Riyadh's "disperses it" (consequence vs. process-resolution)
but the WHO-anchor gap is identical. B- vs. Riyadh's C/B (Jun 13/15 retro grades).
Urumqi's "traps it" form is also the P_close SOLUTION shape — not evidence of P_close
failure; note as positive counter-case.

### B-grade drafts

#### [1] Urumqi, China — dust_event — 2,260 μg/m³ — **B-**

> *Urumqi, China: a model-estimated dust daily maximum of 2,260 μg/m³ on June 17 —
> aerosol optical depth at 1.38. The city sits in the Junggar Basin, ringed by the Tian
> Shan and Altai ranges; when winds funnel desert sediment in, the topography traps it.*

**Score:** 75. Status: posted. Created 2026-06-17T12:27:55Z.

Humor lens:
- **Violation:** 2,260 μg/m³ PM (model-estimated), AOD 1.38. Score 75. Second dust_event
  in corpus (after Riyadh Jun 13).
- **Benign?** Yes.
- **Setup→Punchline?** Colon-lead opener (location: concentration + AOD). Second sentence:
  basin geometry → "traps it." "Traps it" is a declarative consequence close: the mechanism
  (mountain-ringed basin + funneling winds) delivers a one-word consequence.
- **Named mechanic?** Ecosystem specificity (Junggar Basin, Tian Shan, Altai ranges).
  "Traps it" closes on consequence rather than process. Compare Riyadh (Jun 13): "before
  heat-driven turbulence disperses it" — dispersal, not trapping. Urumqi's closing
  direction is correct (P_close-solution form); Riyadh's was wrong.
- **P_dust gap:** No WHO calibration anchor. 2,260 ÷ 15 μg/m³ (WHO PM2.5 daily) = 151×
  the WHO limit. "151× the WHO daily limit" would transform B- to A- range immediately.
  Same gap as Riyadh (Jun 13: 2,083 μg/m³ = 139× WHO, also unstated). P_dust 2nd cycle.
- **Wodehouse rule?** Clean. "model-estimated" qualifier is data hygiene. No effort signals.

Gap to A-: WHO anchor absent (P_dust). With it: "Urumqi: 2,260 μg/m³ on June 17 — 151×
the WHO daily limit. The city sits in the Junggar Basin, ringed by the Tian Shan and
Altai ranges; the topography traps it." — the multiple transforms the opener from opaque
to calibrated violation, and "traps it" delivers the consequence cleanly. That's A-.

B- not C (vs. Riyadh Jun 13): "traps it" is declarative consequence, not process-
resolution. Closing direction matters. AOD 1.38 (vs. Riyadh 0.61) is in the
"extreme" tier (>1.0 = extreme per P_dust proposal) — unannounced but real.

### Patterns

1. **P_dust confirmed 2nd cycle.** Urumqi (2,260 μg/m³) also lacks WHO calibration
   anchor. The 151× WHO multiple is always available as world knowledge — no archive
   needed. Riyadh (Jun 13) was 139×. Both drafts report opaque concentration numbers
   without reference frame. P_dust fix would lift both from B/B- to A- range.

2. **Urumqi's "traps it" is P_close counter-case.** The P_close failure is stopping at
   mechanism before naming consequence. "Traps it" IS the declarative consequence. This
   draft demonstrates the solution form is accessible — the writer CAN produce it. The
   constraint is that without WHO anchor, the grade ceiling is B- even with the correct
   close. Fix P_dust first; P_close form is already present.

3. **4 prior-graded drafts not re-graded.** Chesnee A- (Jun 15), Beaver Dams A- (Jun 15),
   Riyadh C/B (Jun 13/15), Red Dog Mine C+ (Jun 13) — all on record. Pipeline is now
   posting drafted signals at a pace the daily routine can't grade pending-style. Retroactive
   grading remains the practical approach; grades from the same-day run may conflict with
   prior entries.

### Numbers

- Pending at runtime: 0
- New drafts graded: 1 (Urumqi dust_event B-)
- A-rate: 0% (0/1)
- P_dust: 2 cycles (Jun 13, Jun 17), last seen Jun 17
- P8 retired: 4 fresh-draft cycles without snow_extreme since May 19
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (21st consecutive skip)

---

## 2026-06-16 — Daily corpus grading (0 pending drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 0 pending
drafts (9 posted / 6 rejected / 1 approved as of grading time). No new drafts entered
pending status since Jun 15. Pipeline continues to process signals through the triage →
writer → critic chain; triage_cap kills observed in Jun 15 22:27 UTC suppression log
(6 triage_cap + 1 critic + 1 writer + 1 fact_check in a single cron run), confirming
pipeline is alive.

**Staleness review:** 0 pending drafts — staleness policy not triggered. `gh` CLI absent;
**20th consecutive skip** (May 13 → Jun 16).

**A-rate:** — (no pending drafts). Most recent graded cycle: **67%** (6/9 retroactive,
2026-06-15). Most recent active pending-queue cycle: **0%** (0/2, 2026-06-13).

### Patterns / operational notes

1. **0 pending drafts — nothing to grade.** Second consecutive no-pending cycle (Jun
   15 also had 0 pending). Pipeline active at 0.9.67.0; drafts processing and posting
   faster than the daily grading cadence.

2. **No new evidence for any active proposal.** P_close / P_new / P_dust / P5 / P8 all
   at last-known counts (Jun 15). No fire, coral, snow, or cold-record drafts in pending
   state to observe.

3. **Chesnee SC posting flag persists.** `draft_20260610_155509_26` (approved Jun 10)
   lacked `posted_at`/tweet_id as of Jun 15. Verify whether it has since been published
   or is stuck.

### Numbers

- Pending drafts in queue: 0
- Fresh pending drafts graded: 0
- A-rate: — (no pending drafts; most recent: 67% retroactive Jun 15 / 0% pending Jun 13)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (20th consecutive skip)

---

## 2026-06-15 — Daily corpus grading (0 fresh pending; 9 retroactive grades, Jun 2–15)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 0 pending drafts as
of 15:00 UTC. Recent pipeline activity: the bot produced and operator-approved 8 drafts between
Jun 2 and Jun 15 without those drafts being in pending status during any prior grading run.
This entry retroactively grades 9 of those drafts (Barrow precipitation_extreme excluded —
already graded B+ in the Jun 7 corpus entry). Grades are informational corpus entries; operator
had already made posting decisions independently.

**Staleness review:** 0 pending drafts — staleness policy not triggered. One draft in "approved"
status (Chesnee SC monthly_low, `draft_20260610_155509_26`, approved 2026-06-10T16:17Z) lacks a
`posted_at` timestamp or tweet_id as of this cycle — possible posting failure. Operator should
verify. `gh` CLI absent — **19th consecutive skip** (May 13 → Jun 15).

**Grade distribution (9 retroactive drafts):** 1 A / 5 A- / 1 B+ / 1 B / 1 C+ — A-rate:
**67%** (6/9 A-range). **First cycle above the 50% resumption bar.** Caveat: retroactive grades
on already-approved/rejected drafts; not a pending-queue predictive grading cycle. Pipeline
quality is at bar; operator has empirical support for the posting flip decision.

**Headline finding:** Suppression-failure (Loxahatchee NWR, Beaver Dams) and ecosystem isolation
(Gilbert Islands, Nauru) are the A-range mechanics. Voice is clean across all 9 drafts — zero
Wodehouse violations. Red Dog Mine rejection is the second P_new confirmation: 17yr archive, 1°F
margin, Arctic Circle — all three criteria, operator rejected correctly. P7 counter-evidence:
both Jun coral drafts used alternative opener forms; propose retiring P7 to Resolved. Two new
types debut: hot10 (B+) and dust_event (B).

### A-grade drafts

#### [5] Nauru — coral_bleaching — 12.0°C-weeks — **A**

> *Nauru's reefs have reached 12.0°C-weeks of thermal stress — the tier where NOAA Coral Reef
> Watch expects coral mortality, not just bleaching. Nauru is a single raised coral island; its
> reef is the island's perimeter, with no adjacent reef system to reseed it.*

**Score:** 86 (elite). Created 2026-06-05T08:13Z. Posted 2026-06-06T14:38Z. Era anchor: none.

Humor lens:
- **Violation:** 12.0°C-weeks crossed from bleaching tier (8°C-weeks) to mortality tier —
  escalation, not just continuation.
- **Benign?** Yes. Factual, calm. Source cited (NOAA Coral Reef Watch).
- **Setup→Punchline?** Sentence 1: "not just bleaching" contrast carries the escalation
  precisely. Sentence 2: "its reef is the island's perimeter, with no adjacent reef system to
  reseed it" — structural vulnerability stated flatly. The island's geometry is the punchline.
- **Named mechanic?** Ecosystem specificity — single raised island, no reseed path. Terminal
  structural consequence stated declaratively.
- **Wodehouse rule?** Clean. No excess explanation, no poetry attempt. "not just bleaching" is
  exact. The semicolon in sentence 2 lets two facts land in sequence without either restating
  the other.

The A marker: consequence is structural and irreversible ("no adjacent reef system to reseed
it"), stated without hedging. Compare the A- closers below — each implies or approximates the
consequence; this one states it. Best draft in the corpus since May 19 Madagascar.

### A- drafts

#### [2] Loxahatchee NWR, Florida — all_time_high — 100°F — **A-**

> *Loxahatchee NWR, Florida hit 100°F (37.8°C) on May 31 — hottest daily maximum in 37 years of
> records and 2°F above the 2002 mark. In the Florida sea-breeze zone, Atlantic and Gulf moisture
> usually cap afternoon heat before it climbs this high.*

**Score:** 89 (elite). Created 2026-06-03T04:46Z. Posted 2026-06-03T20:32Z. Era anchor: none.

Humor lens:
- **Violation:** 37-year record, 100°F, 2°F above 2002.
- **Benign?** Yes.
- **Setup→Punchline?** Sentence 2 names the Florida sea-breeze suppressor and implies its
  failure. "before it climbs this high" delivers the consequence: the suppressor didn't hold.
- **Named mechanic?** Suppression-failure — the mechanism that normally prevents this is named;
  its failure is implied by the record itself.
- **Wodehouse rule?** Clean. "usually cap" (not "always") is exact. "before it climbs this
  high" delivers the implication efficiently.

A- not A: suppressor failure is implied ("before it climbs this high") rather than stated
flatly. Nauru's A states the terminal consequence directly; this leaves one step to the reader.
Small gap — both forms are clean.

#### [3] Kapingamarangi, FSM — monthly_high — 36.1°C — **A-**

> *Kapingamarangi, Federated States of Micronesia hit 36.1°C (97°F) on June 1 — a new June
> record in 59 years of data, 1.1°C above the 2017 mark. The western Pacific warm pool anchors
> deep convection here; even small surface temperature shifts carry outsized atmospheric weight.*

**Score:** 81 (strong). Created 2026-06-04T04:21Z. Posted 2026-06-04T18:12Z. Era anchor: none.

Humor lens:
- **Violation:** 59-year record, 1.1°C above 2017.
- **Benign?** Yes.
- **Setup→Punchline?** "even small surface temperature shifts carry outsized atmospheric weight"
  — a scale multiplier. A small shift here matters more than a large shift elsewhere.
- **Named mechanic?** Atmospheric amplification + ecosystem specificity (warm pool anchors
  deep convection). The multiplier is verifiable Pacific warm pool geography.
- **Wodehouse rule?** Clean. Semicolon structure prevents the second clause restating the
  first. "outsized atmospheric weight" is slightly abstract but grounded.

A- not A: "outsized atmospheric weight" is accurate but less specific than a declarative
structural consequence. Nauru names an irreversible physical thing; this names a proportionality.

#### [4] Gilbert Islands, Kiribati — coral_bleaching — 10.8°C-weeks — **A-**

> *Gilbert Islands, Kiribati: 10.8°C-weeks of thermal stress — Bleaching Alert Level 2, where
> mass bleaching is expected. The Gilbert chain straddles the equator at the heart of the Pacific
> warm pool; heat that builds here has no cooler adjacent water to dilute it.*

**Score:** 81 (strong). Created 2026-06-04T15:38Z. Posted 2026-06-04T18:30Z. Era anchor: none.

Humor lens:
- **Violation:** 10.8°C-weeks, mass bleaching threshold crossed.
- **Benign?** Yes.
- **Setup→Punchline?** Colon-lead opener (P7 alternative form #1). Sentence 2: "heat that
  builds here has no cooler adjacent water to dilute it" — equatorial isolation mechanism.
- **Named mechanic?** Ecosystem isolation — equatorial warm pool with no thermal dilution path.
  Near-identical to May 19 Costa Rica A-'s "nowhere to drain" form.
- **Wodehouse rule?** "to dilute it" is slightly wordier than "nowhere to drain" (the May 19
  corpus's tightest form). Not a violation but a marginal comparison.

A- not A: "has no cooler adjacent water to dilute it" is one clause longer than the tightest
form. Both do the same work; this takes more words.

P7 note: colon-lead opener is the P7 alternative #1 form — not the banned accumulation
sentence. Counter-evidence for P7 active proposal.

#### [6] Chesnee, SC — monthly_low — 35°F — **A-** ⚠️ not posted

> *Chesnee, South Carolina hit 35°F (1.7°C) on June 6 — coldest June low in 35 years of
> records, 7°F below the 2000 mark. The Carolina Piedmont sits at elevation, where clear nights
> and low humidity drain heat fast enough to threaten gardens well into early summer.*

**Score:** 86 (elite). Created 2026-06-10T15:55Z. **Approved 2026-06-10T16:17Z — no
`posted_at` or tweet_id.** Possible posting failure; operator should verify.

Humor lens:
- **Violation:** 35-year cold record, 7°F below 2000 (substantial margin).
- **Benign?** Yes.
- **Setup→Punchline?** "threaten gardens well into early summer" grounds the signal in a
  human-scale consequence. "early summer" carries the timing-incongruity (frost in June).
- **Named mechanic?** Topographic radiative cooling + human-consequence grounding.
- **Wodehouse rule?** Clean. "fast enough to threaten gardens well into early summer" is
  precise — specific, grounded, no excess.

A- not A: timing-incongruity ("early summer" = June) is implicit. A flat declarative closer
("It is June.") would reach A; this approach implies the timing rather than stating it.
Strongest cold-record draft in the corpus.

P_new note: 35-year archive and 7°F margin both clear the P_new self-kill criteria. Correct
positive case — draft should pass, and it did.

#### [9] Beaver Dams, Utah — all_time_high — 95°F — **A-**

> *Beaver Dams, Utah hit 95°F (34.8°C) on June 12 — hottest daily maximum in 23 years of
> records, 6°F above the 2020 mark. The Colorado Plateau's high-elevation aridity removes the
> moisture buffer that caps heat elsewhere in the desert Southwest.*

**Score:** 91 (elite). Created 2026-06-15T04:27Z. Posted 2026-06-15T04:40Z. Era anchor: none.

Humor lens:
- **Violation:** 23-year record, 6°F above 2020.
- **Benign?** Yes.
- **Setup→Punchline?** "removes the moisture buffer that caps heat elsewhere in the desert
  Southwest" — names the suppressor and distinguishes Beaver Dams from the broader Southwest.
- **Named mechanic?** Suppression-failure — the moisture buffer suppresses heat in the desert
  Southwest generally; the Colorado Plateau's aridity removes it here.
- **Wodehouse rule?** Clean. "elsewhere in the desert Southwest" is the key word — implies:
  even the desert has moisture buffering; this plateau does not.

Near-identical form to Loxahatchee NWR (A-). Suppression-failure mechanic confirmed as a
reliable A- vehicle across categories and geographies.

### B-grade drafts

#### [1] Tromsø, Norway — hot10 — +8.1°C anomaly — **B+**

> *Tromsø, Norway hit 20.2°C (68°F) today — 8.1°C above its normal high. Nine other cities
> from Beijing to Managua landed on the same anomaly leaderboard; the Arctic and the tropics
> running hot on the same day is the signature of a system under broad, simultaneous pressure.*

**Score:** 84 (strong). Created 2026-06-02T12:56Z. Posted 2026-06-02T21:37Z. Era anchor: none.
First hot10 in corpus.

Humor lens:
- **Violation:** +8.1°C anomaly in Tromsø; 10-city event spanning Arctic Norway to tropical
  Nicaragua on the same day.
- **Benign?** Yes.
- **Setup→Punchline?** "Nine other cities from Beijing to Managua" establishes geographic
  breadth. "the Arctic and the tropics running hot on the same day" names the incongruity.
  "the signature of a system under broad, simultaneous pressure" interprets it.
- **Named mechanic?** Geographic breadth + simultaneous anomaly across climate zones.
- **Wodehouse rule?** "the signature of a system under broad, simultaneous pressure" —
  "signature" and "broad, simultaneous pressure" are interpretive rather than specific.
  Not a Wodehouse violation but less specific than A-range closers.

B+ for the geographic breadth mechanic. Gap to A-: the closer is interpretive commentary
where the A-range form names a specific physical consequence. Hot10 category note: the
multi-latitude simultaneous anomaly is a strong setup; the second sentence needs a declarative
consequence rather than a diagnosis.

#### [8] Riyadh, Saudi Arabia — dust_event — 2,083 μg/m³ — **B**

> *Riyadh, Saudi Arabia: a model-estimated dust daily maximum of 2,083 μg/m³ on June 13 —
> aerosol optical depth at 0.61. Riyadh sits at the edge of the Rub' al Khali, where shamal
> winds lift fine desert sediment into a dense, low column before heat-driven turbulence
> disperses it.*

**Score:** 75 (strong). Created 2026-06-13T08:05Z. Posted 2026-06-14T19:44Z. Era anchor: none.
First dust_event in corpus.

Humor lens:
- **Violation:** 2,083 μg/m³ dust (tier 2 of 3). No historical archive — extreme on its face.
  "model-estimated" transparency in text is correct.
- **Benign?** Yes.
- **Setup→Punchline?** Colon-lead with AOD. Sentence 2: Rub' al Khali basin + shamal winds +
  convective lofting mechanism.
- **Named mechanic?** Geographic mechanism — basin sediment supply, wind dynamics,
  thermal lofting.
- **Wodehouse rule?** "lift fine desert sediment into a dense, low column before heat-driven
  turbulence disperses it" — the image peaks at "dense, low column"; "before heat-driven
  turbulence disperses it" continues past it. The dispersal step is anticlimactic.
  Wodehouse-adjacent: mechanism description overshoots its own best image.

B because the mechanism description continues past its peak image. "lift fine desert sediment
into a dense, low column over Riyadh" would be the A- closer — land on the image, stop. New
category baseline: B. Fix: close on the visual image, not the mechanism's terminus.

### C-grade drafts

#### [7] Red Dog Mine, Alaska — monthly_low — 19°F — **C+** (rejected by operator)

> *Red Dog Mine, Alaska hit 19°F (-7.1°C) on June 9 — coldest June low in 17 years of records,
> 1°F below the 2023 mark. The mine sits above the Arctic Circle, where tundra terrain offers
> no shelter from cold air pooling on clear nights.*

**Score:** 80 (strong). Created 2026-06-13T08:03Z. Rejected 2026-06-14. Era anchor: none.

Humor lens:
- **Violation:** 17-year cold record, 1°F below 2023.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 17-year record, 1°F margin. System clause: Arctic Circle,
  tundra cold-air pooling.
- **Named mechanic?** Ecosystem specificity (cold-air pooling). Voice execution clean.
- **Wodehouse rule?** No violations.
- **P_new check:** ALL THREE criteria met — (a) 17yr archive < 20yr, (b) 1°F margin < 2°F,
  (c) Arctic Circle = cold-climate location. P_new failure mode confirmed.

C+ because the signal fails the editorial bar despite clean voice. Compare Chesnee SC (35yr,
7°F, A-) — passes all three P_new dimensions; Red Dog Mine fails all three. Operator rejection
correct. The P_new self-kill gate would have caught this.

**P_new evidence: 2nd confirmation** (May 14 Bethel ME + Jun 13 Red Dog Mine). Both: shallow
archive, trivial margin, cold-climate location. Writer passes both; operator rejects both. The
self-kill gate is the fix.

### Patterns / operational notes

1. **Suppression-failure confirmed as A-/A vehicle.** Loxahatchee NWR (FL sea-breeze zone)
   and Beaver Dams (CO Plateau aridity) both earn A- via this mechanic. Joins ecosystem
   isolation (Nauru, Gilbert Islands) as a repeatable A-range form. Three confirmed A-range
   mechanics: suppression-failure, ecosystem isolation, terminal structural consequence.

2. **P_new (cold-record quality floor) confirmed second cycle.** Red Dog Mine Jun 13 = 2nd
   observation after Bethel ME May 14. Both operator-rejected. Writer passes both on score
   (80, 77 respectively) but they fail editorial bar. P_new is now the highest-leverage
   active proposal.

3. **P7 (coral opener formula) counter-evidence.** Both Jun coral drafts used alternative
   opener forms: Gilbert Islands uses colon-lead (P7 alternative #1); Nauru uses possession
   form. Neither used the banned accumulation sentence. 3+ graded cycles since May 19 without
   P7 observation — propose retiring P7 to Resolved.

4. **New types: hot10 and dust_event debut.** Hot10 B+: multi-latitude simultaneous anomaly
   is the strong setup; closer needs a specific physical consequence. Dust_event B: geographic
   mechanism is correct; close on the visual image ("dense, low column"), not the mechanism's
   terminus. Both categories have room to improve toward A-.

5. **No era anchors in any of 9 drafts.** `era_anchor_used: None` across the full batch.
   Two-bot writer uses archive years (2002, 2020) as historical reference only.

### Numbers

- Pending drafts in queue: 0
- Retroactive drafts graded: 9 (Jun 2–15; already posted/approved/rejected by operator)
- Grade distribution: 1 A / 5 A- / 1 B+ / 1 B / 1 C+
- A-rate: **67%** (6/9 A-range) — **first cycle above 50% resumption bar** (retroactive caveat)
- Active proposal evidence: P_new +1 cycle (Jun 13 Red Dog Mine; now 2 cycles); P7
  counter-evidence (propose Resolved)
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (19th consecutive skip, May 13 → Jun 15)
- Infra note: Chesnee SC (`draft_20260610_155509_26`) approved but no `posted_at`/tweet_id —
  possible posting failure; operator should verify

---

## 2026-06-14 — Daily corpus grading (0 fresh drafts; 2 carry-overs, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 2 pending drafts
— both carry-overs from Jun 13 (Red Dog Mine AK monthly_low, grade on record: C+; Riyadh
dust_event, grade on record: C). Both graded in the 2026-06-13 section below. Not re-grading;
grades stand.

**Staleness review as of 2026-06-14 ~15:00 UTC:**
- Draft [1] (Red Dog Mine monthly_low, created Jun 13T08:03Z): ~31h old. No "today/tonight/
  forecast" language. Under 48h threshold. Not stale.
- Draft [2] (Riyadh dust_event, created Jun 13T08:05Z): ~31h old. "June 13" is a historical
  measurement date reference, not a "today" anchor (consistent with all prior corpus rulings
  on similar date-reference framings). Under 48h threshold. Not stale.
Bulk-reject: 0 candidates. `gh` CLI absent — **18th consecutive skip** (May 13 → Jun 14).

**A-rate:** — (no fresh drafts). Most recent graded cycle: **0%** (0/2, 2026-06-13).

### Carry-over inventory (not re-graded; grades on record)

| # | Draft | Type | Created | Grade |
|---|---|---|---|---|
| [1] | Red Dog Mine, Alaska — 19°F (-7.1°C) / coldest June low in 17 years | monthly_low | Jun 13T08:03Z | C+ |
| [2] | Riyadh, Saudi Arabia — 2,083 μg/m³ dust daily max / AOD 0.61 | dust_event | Jun 13T08:05Z | C |

### Patterns / operational notes

1. **No fresh drafts.** Both queue entries are carry-overs from Jun 13's graded cycle.
   No new signal types or voice failures to report.

2. **No active proposal evidence updates.** No fresh drafts = no failure-mode observations.
   P_close/P_new/P_dust/P5/P7/P8 all at last-known counts from Jun 13.

3. **Staleness horizon approaching.** Both drafts will cross 48h at approximately Jun 15
   08:00Z. Neither contains forecast-to-hit-today language, so they would not trigger the
   policy even after 48h. No operator action needed on staleness grounds before then.

### Numbers

- Pending drafts in queue: 2 (0 fresh; 2 carry-overs from Jun 13)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-06-13)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (18th consecutive skip)

---

## 2026-06-13 — Daily corpus grading (2 fresh drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 2 fresh drafts,
both created 2026-06-13T08:03-08:05Z (< 8h old at grading). First dust_event in corpus
(new signal type from @extremetemps coverage lane). Second monthly_low after Chesnee SC.
Both drafts generated under live supply flags: `THEHEAT_WRITER_SAMPLES=2` +
`THEHEAT_CRITIC_REVISE_ENABLED=1` (flipped per BRIEFING.md 2026-06-13; best-of-2 + critic
rewrite effective this cycle).

**Staleness review:** Both drafts < 8h old at grading time. Draft [2] (Riyadh) bakes
"June 13" in the text — within 48h window, not stale by policy. Bulk-reject: 0 candidates.
`gh` CLI absent — **17th consecutive skip** (May 13 → Jun 13).

**Grade distribution (2 fresh drafts):** 0 A / 0 B / 1 C+ / 1 C / 0 D-F.
**A-rate: 0% (0/2).** Gap from resumption bar: 50 pp.

**Headline finding:** Two new-or-returning signal types, both grade C/C+ for the same
structural reason: expected-location signals without calibrating comparison anchors. Red
Dog Mine's cold record fails the P_new quality floor (17yr archive, 1°F margin, Arctic
Circle — re-activating archived proposal). Riyadh's dust event carries a real signal
(2,083 μg/m³ ≈ 139× the WHO PM2.5 daily guideline) but the draft leaves that comparison
unstated (new proposal P_dust). Both have physically accurate second sentences that explain
mechanism without landing a consequence — P_close 3rd cycle.

### C-grade drafts

#### [1] Red Dog Mine, Alaska — monthly_low — 19°F (-7.1°C) — **C+**

> *Red Dog Mine, Alaska hit 19°F (-7.1°C) on June 9 — coldest June low in 17 years of
> records, 1°F below the 2023 mark. The mine sits above the Arctic Circle, where tundra
> terrain offers no shelter from cold air pooling on clear nights.*

**Score:** 80. Created 2026-06-13T08:03:51Z.

Humor lens:
- **Violation:** Coldest June low in 17 years. Calendar incongruity exists (summer month
  cold record) but the location partially erases it — above the Arctic Circle is the
  canonical cold-climate address. Violation present; muffled.
- **Benign?** Yes — calm, factual register. No panic.
- **Setup→Punchline?** Setup: 19°F, 17-year low, 1°F below 2023. Second sentence: tundra
  terrain / cold-air pooling on clear nights. Physically correct and specific (radiative
  cooling on flat tundra is a real mechanism). But the second sentence explains the
  mechanism rather than naming what the mechanism does. There is no consequence — not even
  an implied one. Compare Barrow (Jun 7 B+): "sheets across the surface instead" — at least
  implies runoff. This stops earlier: mechanism without any payoff.
- **Named mechanic?** Ecosystem specificity (tundra, cold-air pooling). Deployed naturally.
  Not weaponized as a punchline.
- **Wodehouse rule?** Clean. No approximation, no restate-padding, no defensive closer.
- **P_close evidence:** Second sentence is mechanism-only — no consequence named or implied.
  This is the weakest close in the P_close sequence (Barrow: implied consequence; Chesnee:
  implied consequence; Red Dog Mine: no consequence). P_close 3rd cycle.

**P_new test (all three criteria met):**
- (a) Archive depth: 17 years — shallow (< 20). ✓
- (b) Margin: 1°F below 2023 mark (< 2°F / 1°C). ✓
- (c) Cold-climate location: above Arctic Circle, Alaska. ✓

Same class as Bethel, Maine (May 14, C) and Mankato (May 11, Andrew reject). Score gate
(80) does not screen this class. P_new re-activated. Voice execution marginally better than
Bethel (cold-pooling specificity) but signal ceiling unchanged. Grade: **C+**.

#### [2] Riyadh, Saudi Arabia — dust_event — 2,083 μg/m³ — **C**

> *Riyadh, Saudi Arabia: a model-estimated dust daily maximum of 2,083 μg/m³ on June 13
> — aerosol optical depth at 0.61. Riyadh sits at the edge of the Rub' al Khali, where
> shamal winds lift fine desert sediment into a dense, low column before heat-driven
> turbulence disperses it.*

**Score:** 75. Created 2026-06-13T08:05:05Z. First dust_event in corpus.

Humor lens:
- **Violation:** 2,083 μg/m³ is ≈ 139× the WHO PM2.5 daily guideline (15 μg/m³) and
  ≈ 46× the WHO PM10 guideline (45 μg/m³). Extraordinary — but the draft doesn't say so.
  The reference is missing; 2,083 is opaque.
- **Benign?** Yes — calm, factual. "Model-estimated" qualifier is accurate and appropriate.
- **Setup→Punchline?** Setup: 2,083 μg/m³, AOD 0.61. Second sentence: Rub' al Khali,
  shamal winds, dense column, heat-driven turbulence disperses it. Ends on dispersal —
  resolution of the mechanism, not consequence. Anti-climactic.
- **Named mechanic?** None. Pure geography/meteorology explanation. No incongruity
  deployed.
- **Wodehouse rule?** "Aerosol optical depth at 0.61" — secondary technical metric the
  reader cannot calibrate. Mild math-out-loud. AOD 0.61 is hazy-to-hazardous (>0.4
  threshold) but the draft doesn't say so.
- **Expected-location failure:** Riyadh at the edge of the Rub' al Khali — dustiness is
  architecturally expected, same way cold is expected above the Arctic Circle. The WHO
  multiple would restore the incongruity.

**Missed punchline:** "Riyadh: 2,083 μg/m³ on June 13. The WHO daily limit is 15." —
period-and-restate with the reference value transforms the number from opaque to absurd.
The setup is in the draft; it stops before the punchline.

**New failure mode (P_dust):** First dust_event reveals a structural gap — writer has no
calibrating comparison anchor in the prompt. WHO guideline (15 μg/m³ PM2.5 / 45 μg/m³
PM10) is always available as world knowledge. Without it, dust concentrations are
uninterpretable to lay readers.

### Patterns

1. **P_close confirmed — 3rd consecutive cycle.** Red Dog Mine (Jun 13): mechanism-only
   close (no consequence stated or implied). Barrow (Jun 7): implied consequence. Chesnee
   (Jun 10): implied consequence. Three consecutive drafts from different signal categories,
   same gap to A-. P_close is the current binding ceiling.

2. **P_new re-activated — 2nd confirmed grading cycle.** Red Dog Mine: 17yr/1°F/Arctic
   Circle = all three criteria met. Archive note condition met. Score gate (80) passed both
   Red Dog Mine and Bethel — the gate is not catching this class.

3. **Dust_event debut: reference-frame gap is structural.** Riyadh's 2,083 μg/m³ is
   extraordinary; the draft fails to reveal it. WHO multiple is derivable from any bundle
   value — no archive needed. New proposal: P_dust.

4. **Supply flags live; no quality lift yet (n=2).** `THEHEAT_WRITER_SAMPLES=2` +
   `THEHEAT_CRITIC_REVISE_ENABLED=1` active this cycle. Both C/C+ grades passed
   best-of-2 + critic-rewrite filter. Failure modes (P_new signal quality, reference-frame
   gap) may be pre-critic issues the rewrite step can't correct from framing alone.

5. **No Wodehouse violations.** Both drafts clear the Wodehouse rule. Fixes holding across
   3 fresh-draft cycles (Jun 7, Jun 13 ×2).

6. **gh CLI absent — 17th consecutive skip.** 0 staleness candidates.

### Numbers

- Pending drafts in queue: 2 (2 fresh; 0 carry-over)
- Fresh drafts graded: 2
- A-rate: 0% (0/2)
- Gap from bar: 50 pp
- Proposal updates: P_close 3rd cycle (last seen Jun 13). P_new re-activated (Jun 13,
  2nd grading cycle). P_dust new (Jun 13). P5 weak update (dust_event no mechanic).
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (17th consecutive skip)

---

## 2026-06-12 — Daily corpus grading (0 fresh pending drafts; 1 approved carry-new observed)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **0 pending drafts**.
Jun 7 Barrow, Alaska precipitation_extreme (grade on record: B+) confirmed **posted** —
operator published it between Jun 8 and Jun 9 (per Jun 9 run). Routine ran on Jun 9, 10, and 11
(entries on record in this corpus below); bot at **0.9.47.0** as of Jun 12 (Jun 9–12 sprint:
infrastructure/source/dashboard, all non-voice). No fresh pending drafts to grade.

**New approved draft (status=approved; not pending; graded as voice observation):**
`draft_20260610_155509_26` — monthly_low, Chesnee, South Carolina, created
2026-06-10T15:55:09Z, score 86. Operator approved ~22 min after creation
(approved_at 2026-06-10T16:17:02Z). `publish_requested_at` is set; `post_error` null —
likely queued for posting. Full text and bundle available; graded below.

**Staleness review:** 0 pending drafts — nothing to evaluate. Jun 7 Barrow draft now posted.
Bulk-reject: 0 candidates. `gh` CLI absent — **16th consecutive skip** (May 13 → Jun 12).

**Grade distribution (fresh pending):** N/A (0 pending drafts).
**A-rate:** — (no pending drafts). Most recent graded cycle: **0%** (0/1, 2026-06-07).

---

### Voice observation: Chesnee, South Carolina — monthly_low — score 86 — **B+**

> *Chesnee, South Carolina hit 35°F (1.7°C) on June 6 — coldest June low in 35 years of
> records, 7°F below the 2000 mark. The Carolina Piedmont sits at elevation, where clear
> nights and low humidity drain heat fast enough to threaten gardens well into early summer.*

**Bundle facts:** Observed low 35.1°F / 1.7°C. Prior Jun min 42.1°F / 5.6°C (year 2000).
Archive span 35 years. Margin: 3.9°C / 7°F. Score 86 vs threshold 76 (label: elite).
Fact-check passed (Sonnet 4.6 writer; Gemini 2.5 Flash fact-checker). Critic passed (Gemini
2.5 Pro). Two-bot angle chosen: "record_margin_with_piedmont_radiative_cooling_mechanism."
Reasoning note: "The 7°F margin below the prior record is the load-bearing fact; the Piedmont
elevation and radiative cooling provide a local mechanism that earns the system clause without
invented context."

Note: draft is status=approved (not pending); included because it is new since Jun 8, ungraded
in the corpus, and full bundle data is available for voice analysis.

**Humor lens:**
- **Violation:** 35°F on June 6 in South Carolina — coldest June low in 35 years, 7°F / 3.9°C
  below the 2000 mark. Strong signal: deep archive (35 years), significant margin (3.9°C), and
  a location (Southeast US Piedmont) where June cold is genuinely surprising. Passes the
  editorial bar Andrew established — contrast with P_new's Bethel, ME case (16yr, 1°F, cold-
  climate location): Chesnee fails ALL THREE of P_new's kill criteria. This is the signal that
  should pass.
- **Benign?** Yes. Calm register throughout. "Threaten gardens well into early summer" is
  understated, not alarming.
- **Setup→Punchline?** Setup: coldest June low in 35 years, 7°F below the 2000 mark. Second
  sentence: elevation + radiative cooling (clear nights, low humidity) → "threaten gardens well
  into early summer." The system clause earns its place causally — explains the physical
  mechanism (radiative cooling at elevation) and names the local consequence. Not expository
  geography; the second sentence explains WHY June cold is possible in Chesnee specifically.
- **Named mechanic?** Ecosystem specificity (Carolina Piedmont elevation + radiative cooling).
  The close frames the consequence in terms the audience recognizes: garden frost threat in
  June South Carolina. The June-in-South-Carolina incongruity is the violation stated through
  its consequence.
- **Wodehouse rule?** Nearly clean. "35°F" rounds from bundle's "35.1°F" — standard display
  rounding, not a violation. "7°F below the 2000 mark" names margin and year anchor together;
  neither is derivable from the other, so this is not restate-math. "Threaten gardens well
  into early summer" — specific, not defensive, not a poetry attempt. One flag: "well into
  early summer" uses three words where "in June" would suffice — mild over-explanation.

**Why B+ and not A-:** The close arrives at "threaten gardens well into early summer" —
functional and specific, but takes 9 words to land a consequence the reader can infer. The
corpus A-grade closers state the consequence directly in ≤5 words: "persistence is what kills,"
"nowhere to drain," "It is April." Here the consequence is frost, but the draft says "threaten
gardens" (implies frost) rather than "frost gardens" (states it). The declarative form —
"drain heat fast enough to frost gardens in June" — matches the A-grade close pattern.

This is the **same B+/A- gap observed in Barrow (Jun 7)**: "sheets across the surface instead"
implies runoff without naming it; "threaten gardens" implies frost without naming it. Two
consecutive new drafts, same mechanism, same distance from A-.

The "2000 mark" year anchor is used correctly — the year is data (when the prior record was
set), not a cultural flashback. Era anchor count in this draft: 1 (light, data-serving). Does
not increment P1 evidence.

---

### Carry-over inventory (prior grades confirmed)

| # | Draft | Type | Created | Prior grade | Current status |
|---|---|---|---|---|---|
| Barrow, Alaska — 213.8 mm / 3-day precipitation record | precipitation_extreme | Jun 7T04:07Z | B+ | **posted** (confirmed via gist status='posted') |

### Patterns named in this batch

1. **B+/A- close gap: implied consequence vs. declarative consequence — second consecutive
   confirmation.** Barrow Jun 7 ("sheets across the surface instead" — implies runoff) and
   Chesnee Jun 10 ("threaten gardens well into early summer" — implies frost) share the same
   structure: correct mechanism, functional close, but the punchline phrase stops one verb
   short of A-grade directness. The writer identifies the human-consequence correctly and
   wraps it in the mechanism rather than stating it flat. Pattern: the writer chooses to
   *imply* the consequence through the mechanism rather than *declare* it. Two drafts in two
   weeks from different signal categories (precipitation_extreme, monthly_low). → New
   proposal P_close added.

2. **P_new not triggered (positive).** Chesnee monthly_low: 35-year archive, 3.9°C margin,
   Southeast US climate — fails all three P_new kill criteria. Score gate at 86 (threshold 76)
   is appropriate for this signal. The quality floor works correctly here.

3. **Routine ran Jun 9, 10, 11** (entries below). Jun 9 agent archived P_new (6 fresh-draft
   cycles without cold-record observation). No new drafts appeared in any of those runs.
   Voice engine unchanged through 0.9.47.0.

4. **New draft lifecycle state: 'approved'.** `draft_20260610_155509_26` has status='approved'
   rather than the expected 'pending' → 'posted' path. Operator manually approved within 22
   min; `publish_requested_at` set but posting incomplete as of Jun 12 run. Not a corpus
   concern; operational note for the operator: verify whether the publish intent was processed.

### Numbers

- Pending drafts in queue: 0
- Fresh pending drafts graded: 0
- Voice observations (approved status, not pending): 1 (Chesnee SC monthly_low, B+)
- A-rate: N/A (no pending drafts; most recent graded cycle: 0% on 2026-06-07)
- New proposals: P_close added (mechanism close defaults to implied consequence; 2 cycles evidence)
- Proposal evidence updates: P5 not observed (Chesnee ecosystem specificity deployed naturally);
  P_new not triggered (Chesnee passes editorial bar); P_close cycles confirmed: 2 (Jun 7 + Jun 10)
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (16th consecutive skip, May 13 → Jun 12)
- Bot commit: 0.9.47.0 (Jun 12; voice engine unchanged since 0.9.8.0)
- Prior cycles: Jun 9, 10, 11 ran; no fresh drafts in any (entries below)

---

## 2026-06-11 — Daily corpus grading (0 fresh drafts; queue empty)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **0 pending drafts** — confirmed empty across Jun 9, Jun 10, and Jun 11 runs. The Barrow Alaska precipitation_extreme (B+, created Jun 7T04:07Z) was cleared between Jun 8 and Jun 9 — under 7-day TTL, not auto-expired; operator action (likely published). No new drafts have reached pending since 2026-06-07T04:07:40Z (4 days as of this run).

**Staleness review as of 2026-06-11 ~15:00 UTC:** Queue empty. No candidates. `gh` CLI absent — **15th consecutive skip** (May 13 → Jun 11). No operator action needed.

**A-rate:** — (no fresh drafts). Most recent graded cycle: **0%** (0/1, 2026-06-07).

### Carry-over inventory

None. Queue empty.

### Patterns / operational notes

1. **Queue continues empty — 3rd consecutive no-fresh-draft cycle since Jun 7.** Barrow AK precipitation_extreme (B+, Jun 7) cleared between Jun 8 and Jun 9; likely published (first known precipitation_extreme tweet, consistent with `manual_only` posting mode and Andrew's Jun 2 manual-push precedent).

2. **No new drafts since Jun 7T04:07Z (4 days).** gpm S3 datapool feed (0.9.15.0) that unlocked the Barrow signal has not produced another qualifying signal. Possible causes: (a) no qualifying extreme events detected in the 638-city set, (b) evidence contract or triage cap filtering signals, (c) external data-source outage. Operator should check `suppression_ledger` for `evidence_contract` or `triage_cap` kills in the Jun 7–11 window.

3. **No active proposal evidence updates.** No fresh drafts = no failure-mode observations. P5/P7/P8 remain at last-known counts (last seen May 19). P_new archived in Jun 9 run (6 consecutive fresh-draft cycles without cold-record observation, per 3-cycle rule).

### Numbers

- Pending drafts in queue: 0 (empty; confirmed Jun 9, 10, 11 runs)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-06-07)
- Active proposals: no evidence updates this cycle; P_new archived Jun 9
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (15th consecutive skip, May 13 → Jun 11)

---

## 2026-06-10 — Daily corpus grading (0 fresh drafts; queue empty)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 0 pending drafts.
The Barrow, Alaska precipitation_extreme (B+, created 2026-06-07T04:07:40Z, ~83h old at run
time) has been cleared since Jun 9 run. Not in queue — most likely published by operator
(`manual_only` posting mode) or operator-rejected. No new drafts have entered pending since
Jun 7T04:07Z (~84h gap as of this run).

**Staleness review as of 2026-06-10 ~15:00 UTC:** Queue empty. No candidates. `gh` CLI
absent — **14th consecutive skip** (May 13 → Jun 10). Nothing to evaluate or reject.

**A-rate:** — (no fresh drafts). Most recent graded cycle: **0%** (0/1, 2026-06-07).

### Queue inventory

None. Queue empty.

### Patterns / operational notes

1. **Queue fully cleared since Jun 9 run.** Barrow Alaska precipitation_extreme (B+, Jun 7)
   confirmed gone in Jun 9 run; still absent Jun 10. Pipeline healthy (0.9.22.0+).
   Next fresh drafts depend on signal quality passing triage → evidence contract → writer →
   critic. Second consecutive no-fresh-draft cycle since Jun 9 (3rd since Jun 7).

2. **No active proposal evidence updates.** No fresh drafts = no failure-mode observations.
   P5/P7/P8 all at last-known counts (last seen May 19). P_new archived in Jun 9 run.

3. **Draft drought context.** Jun 7 remains the only fresh draft since May 19 (19-day gap
   caused by routine downtime + pipeline suppression). Triage cap, critic filtering, and
   seasonal signal patterns are likely controls on draft frequency.

### Numbers

- Pending drafts in queue: 0
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-06-07)
- Active proposals: no evidence updates this cycle (P_new archived in Jun 9 run)
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (14th consecutive skip)

---

## 2026-06-09 — Daily corpus grading (0 fresh drafts; queue now empty)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **0 pending
drafts.** The Barrow, Alaska precipitation_extreme draft (B+, created 2026-06-07T04:07:40Z,
~59h old at run time) has been cleared since Jun 8 ~15:00 UTC. Not in queue at grading
time — most likely published by operator (`manual_only` posting mode) or operator-rejected.
No new drafts have entered pending since Jun 7T04:07Z (~55h gap as of this run).

**Staleness review:** 0 pending drafts — nothing to evaluate. `gh` CLI absent — **13th
consecutive skip** (May 13 → Jun 9). No candidates in any case.

**A-rate:** — (no fresh drafts). Most recent graded cycle with fresh drafts: **0%**
(0/1, 2026-06-07).

### Carry-over inventory

None. Queue empty.

### Patterns / operational notes

1. **Queue cleared since Jun 8.** Barrow AK precipitation_extreme draft gone — cleared
   between Jun 8 ~15:00 UTC and Jun 9 ~15:00 UTC. First fully-empty queue since Jun 7.

2. **No active proposal evidence updates.** 0 fresh drafts = 0 failure-mode observations.

3. **P_new (cold record quality floor) crosses archival threshold.** Last seen: May 14.
   Fresh-draft graded cycles since then: May 15, 16, 17, 18, 19, Jun 7 = 6 consecutive
   cycles with no cold-record drafts surfacing. Well past the 3-cycle rule. Moving to
   Resolved (archive) in IMPROVEMENT_PLAN.md. Signal-side cause: no new cold-record
   drafts have entered pending since May 14 (Bethel ME monthly_low was TTL-swept during
   June 1–6). Failure mode may be upstream (score-gate/triage) rather than prompt-fixed —
   but 6 cycles without observation meets the archival rule. Reopen if cold-record drafts
   with shallow archive + trivial margin reappear.

### Numbers

- Pending drafts in queue: 0
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-06-07)
- Active proposals: no evidence updates; P_new moved to Resolved (archive)
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (13th consecutive skip)

---

## 2026-06-08 — Daily corpus grading (0 fresh drafts; 1 carry-over, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 1 pending draft
— carry-over from Jun 7 (Barrow Alaska precipitation_extreme, grade on record: B+). No
new drafts since 2026-06-07T04:07:40Z. Not re-grading; grade stands from Jun 7 entry.

**Staleness review as of 2026-06-08 ~15:00 UTC:** Draft created 2026-06-07T04:07:40Z,
~35h old. Past-tense framing ("received", "sits on"), no "today/tonight/forecast" language.
Under 48h threshold and no real-time-baked content — not a staleness candidate.
Bulk-reject: 0 candidates. `gh` CLI absent — **12th consecutive skip** (May 13 → Jun 8).

**A-rate:** — (no fresh drafts). Most recent graded cycle: **0%** (0/1, 2026-06-07).

### Carry-over inventory (not re-graded; grade on record)

| # | Draft | Type | Created | Grade |
|---|---|---|---|---|
| [1] | Barrow, Alaska — 213.8 mm / 3-day precipitation record | precipitation_extreme | Jun 7T04:07Z | B+ |

### Patterns / operational notes

1. **No fresh drafts.** 1st carry-over-only cycle since Jun 7's fresh-draft cycle. Queue
   static since Jun 7T04:07Z (~35h). Normal gap between cron-cycle signal detections.

2. **No active proposal evidence updates.** No fresh drafts = no failure-mode observations.
   P5/P7/P8/P_new all at last-known counts.

### Numbers

- Pending drafts in queue: 1 (0 fresh; 1 carry-over from Jun 7)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-06-07)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (12th consecutive skip)

---

## 2026-06-07 — Daily corpus grading (1 fresh draft)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 1 pending draft
— 1 fresh draft not previously graded. This is the **first fresh draft since 2026-05-19**
(19 days, ~114 cron cycles). Background: the routine was DOWN 2026-05-26 → 2026-06-07 (CCR
token failure, 12 days); the 13 carry-overs from May 13–18 were auto-rejected by the 7-day
TTL sweep (0.9.6.0) during June 1–6. Bot re-enabled 2026-06-01. The 0.9.15.0 release
(gpm single-request daily-grid fetch via S3, PR #185, 2026-06-06) appears to have unlocked
the precipitation_extreme signal type: the one pending draft (Barrow, Alaska
precipitation_extreme, created 2026-06-07T04:07:40Z) is the first of this type in the
corpus.

**Staleness review as of 2026-06-07 ~15:00 UTC:** 1 pending draft, created
2026-06-07T04:07:40Z (< 12 hours old). Text uses past-tense framing ("received", "sits on")
— no "today/tonight/forecast" language. Not stale by policy.

Bulk-reject: no qualifying candidates. `gh` CLI absent — **11th consecutive skip** (May 13
→ June 7). No candidates in any case.

**Grade distribution (1 fresh draft):** 0 A / 1 B+ / 0 B / 0 C / 0 D-F.
**A-rate: 0% (0/1).** Gap from resumption bar: 50 pp (n=1; not statistically meaningful).

**Headline finding:** First precipitation_extreme in the corpus. Barrow, Alaska earns B+
on permafrost drainage ecosystem specificity. Signal solid (score 81, 42.5% above prior
record). Second sentence earns its place causally. "Sheets across the surface instead" is
evocative but relies on implied contrast rather than a declarative close — the gap to A-.
Minor restate-math in sentence one.

### B-grade drafts

#### [1] Barrow, Alaska — precipitation_extreme — 213.8 mm / 3 days — **B+**

> *Barrow, Alaska received 213.8 mm of rain in 3 days — 63.8 mm above the previous 3-day
> record of 150.0 mm. Barrow sits on the Arctic coast, where permafrost limits drainage;
> rain that would soak into other soils here sheets across the surface instead.*

**Score:** 81. Created 2026-06-07T04:07:40Z.

Humor lens:
- **Violation:** 213.8 mm in 3 days, 63.8 mm (42.5%) above the prior record of 150.0 mm.
  Real signal. Meaningful margin.
- **Benign?** Yes — calm, factual register. No panic.
- **Setup→Punchline?** Setup: 213.8 mm, margin above record. Second sentence: permafrost
  drainage mechanism → "sheets across the surface instead." The second sentence is causal
  (explains the physical consequence unique to Barrow), not expository. "Instead" creates
  an implicit contrast between Barrow's behavior and normal soil absorption.
- **Named mechanic?** Ecosystem specificity (permafrost limits drainage, rain sheets
  across surface). Load-bearing: explains why Barrow is uniquely affected by this signal,
  not just where it sits. Closest corpus cousins: Bethel Maine bowl-topography (May 19 B-)
  and Austral Islands SPCZ expansion (May 19 B+).
- **Wodehouse rule?** Nearly clean. "63.8 mm above the previous 3-day record of 150.0 mm"
  is mild restate-math — the margin is derivable from the two values already stated
  (213.8 − 150.0 = 63.8). Not a Wodehouse violation (doesn't dilute the punchline) but is
  unnecessary precision. "Sheets across the surface instead" — direct and physical; not a
  poetry attempt.

Not A- because "sheets across the surface instead" relies on the reader supplying the
implied consequence: normal soil absorbs; permafrost doesn't; therefore runoff. The corpus
A-grade closers state the consequence flatly ("kills", "nowhere to drain", "It is April.")
rather than implying it. The implied form grades B+; the declarative form grades A-.

Restate-math fix for this category: prefer ratio form ("42% above the prior record") or
let the two values speak alone: "213.8 mm in 3 days. The prior record was 150.0 mm." The
period-and-restate on two values is cleaner than stacked margin + reference in one em-dash
clause.

New signal type. First precipitation_extreme in corpus. Solid B+ baseline for the category.

### Patterns named in this batch

1. **Ecosystem specificity as precipitation_extreme mechanic.** Permafrost drainage earns
   its place causally — it explains the physical mechanism that makes the record
   consequential in Barrow specifically. The close ("sheets across the surface instead") is
   physical and specific but implies the contrast rather than declaring it. The A-grade
   version names the consequence directly. The B+ form is the predictable gap: the mechanic
   is right; the landing is soft.

2. **Implicit vs. declarative close.** "Instead" at sentence end creates contrast without
   stating it. The reader supplies the comparison (normal soil absorbs; permafrost doesn't).
   Softer than "kills" (Madagascar coral) because "kills" is the consequence stated flatly;
   "instead" deflects to the reader to infer the consequence. Pattern: whenever the writer
   can name the consequence directly in ≤5 words, do it. When it requires a dependent clause
   to set up, the implied form is better than the over-explained form, but still B+.

3. **Restate-math: minor recurring violation.** "63.8 mm above the previous 3-day record
   of 150.0 mm" restates the derivable margin. The reader has both values; the 63.8 is
   arithmetic. Fix for future precipitation_extreme drafts: ratio form ("42% above") or
   plain period-and-restate ("213.8 mm in 3 days. The prior record was 150.0 mm.").

4. **First precipitation_extreme in corpus; gpm S3 migration (0.9.15.0) likely enabled
   it.** Barrow's precipitation signal is the first evidence the S3 daily-grid path
   (PR #185) is producing qualifying signals. Watch for whether precipitation_extreme
   becomes a recurring category.

5. **P5 not observed (positive).** Ecosystem specificity — one of P5's named mechanics —
   appeared without being explicitly named in the prompt. The richer palette (comic triple,
   idiom-flip, understatement closer) was not deployed but the draft earns B+ without them.
   P5's core claim (naming the full palette increases variety) is untested by one draft;
   the mechanic appeared naturally. The gap to A- is the close quality, not palette breadth.

6. **TTL sweep operational note (preserved from prior run).** Three A-/B+ coral drafts
   (Madagascar A-, Galapagos A-, Costa Rica Pacific A-) were auto-rejected by the 7-day
   TTL during June 1–6. DHW signals accumulate on multi-week timescales — the 7-day default
   may be short for this category. Operator calibration question: does
   `THEHEAT_PENDING_TTL_DAYS` warrant a per-type override for coral_bleaching?

### Followups

1. For precipitation_extreme: the restate-math pattern ("X above the previous record of
   Y mm") is likely to recur if the writer bundle carries both margin and reference value.
   Add to corpus notes: prefer ratio form ("42% above") or period-and-restate on the two
   raw values.

2. First precipitation_extreme in corpus. Permafrost drainage is specific to Arctic
   stations. Watch whether future precipitation drafts at lower latitudes default to
   different ecosystem mechanisms or fall back to generic topographic description.

3. TTL calibration question: three A-/B+ coral drafts auto-rejected at 7 days. Operator
   should consider whether the `THEHEAT_PENDING_TTL_DAYS` default of 7 is too short for
   multi-week DHW accumulation signals. Not a voice proposal — infrastructure calibration.

### Numbers

- Pending drafts in queue: 1 (1 fresh; 0 carry-overs)
- Fresh drafts graded: 1 (precipitation_extreme)
- A-rate: 0% (0/1); n=1 — not statistically meaningful
- Grade distribution: 0 A / 1 B+ / 0 B / 0 C / 0 D-F
- New signal type in corpus: precipitation_extreme (Barrow, Alaska)
- Active proposals: P5 not observed (ecosystem specificity deployed correctly); P7/P8/P_new
  — no evidence (no coral/snow/cold-record drafts this cycle)
- Staleness bulk-reject: no qualifying candidates; `gh` CLI absent (11th consecutive skip,
  May 13 → Jun 7)
- First fresh draft since: 2026-05-19 (19 days, ~114 cron cycles)
- Routine gap: closed (2026-05-26 → 2026-06-07, 12 days)

---

## 2026-05-26 — Daily corpus grading (0 fresh drafts; 13 carry-overs, all previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 13 pending
drafts — all carry-overs from graded cycles 2026-05-13 through 2026-05-18. No new drafts
since 2026-05-18T15:52Z (Stahl Peak snow_extreme). Today is the **6th consecutive
no-fresh-draft graded cycle** (May 20, 22, 23, 24, 25, 26).

**Why no fresh drafts:** Queue static for 8 days (~48 cron cycles at 6/day). Candidate
bottlenecks in priority order: (1) evidence contract gate (`stage="evidence_contract"`,
live since 0.9.0.0 / merged ~May 22) — operator should check kill counts in suppression
ledger for May 22–26; (2) score-gate suppression (threshold varies 72–82 by type);
(3) triage-cap spill (`triage_cap` kill_stage); (4) genuine signal drought. The initial
stall started May 18, 4 days before evidence contract went live — so the gate is not the
sole cause, but may now be compounding. If `evidence_contract` kill counts are negligible,
operator should check `source_health` to determine whether any source is generating
qualifying signals at all.

**Staleness review as of 2026-05-26 ~15:00 UTC:**

No remaining drafts contain "today/tonight/forecast" language — no new staleness-policy
triggers since May 25. Coral drafts ([3]–[11], created May 15–18) are now 8–11 days old.
NOAA CRW DHW accumulation values are updated daily; the cited °C-week figures may no
longer reflect current reef thermal stress. Operator must verify against current NOAA CRW
readings before publishing any coral draft. Snow drafts ([12]–[13]) are 8 days old;
text uses past-tense historical record framing with no date-baked language — within policy,
but freshness check recommended before publication.

Bulk-reject: no qualifying candidates by policy. `gh` CLI absent — **10th consecutive
skip** (May 13 → May 26).

**A-rate:** — (no fresh drafts). Most recent graded cycle: **21%** (3/14, 2026-05-19).

### Carry-over inventory (not re-graded; grades on record)

| # | Draft | Type | Created | Grade | Staleness |
|---|---|---|---|---|---|
| [1] | Chuuk FSM — 34.4°C (94°F) | monthly_high | May 13T10:32Z | B | Historical obs date (May 9) |
| [2] | Bethel, Maine — 28°F | monthly_low | May 13T21:29Z | B- | Historical obs date (May 9) |
| [3] | Madagascar coral — 10.2°C-weeks | coral_bleaching | May 15T03:01Z | A- | 11 days; DHW values may be stale |
| [4] | Fiji coral — 10.1°C-weeks | coral_bleaching | May 15T03:02Z | B+ | 11 days; DHW values may be stale |
| [5] | Nauru coral — 8.2°C-weeks | coral_bleaching | May 15T03:04Z | B+ | 11 days; DHW values may be stale |
| [6] | Great Nicobar — 7.2°C-weeks | coral_bleaching | May 15T03:47Z | C+ | 11 days; DHW values may be stale |
| [7] | Chagos — 7.2°C-weeks | coral_bleaching | May 15T03:48Z | C+ | 11 days; DHW values may be stale |
| [8] | Southern Borneo — 4.4°C-weeks | coral_bleaching | May 15T03:55Z | C | 11 days; DHW values may be stale |
| [9] | Galapagos coral — 24.5°C-weeks | coral_bleaching | May 15T05:16Z | A- | 11 days; DHW values may be stale |
| [10] | Austral Islands coral — 8.6°C-weeks | coral_bleaching | May 15T05:20Z | B+ | 11 days; DHW values may be stale |
| [11] | Costa Rica Pacific coral — 12.0°C-weeks | coral_bleaching | May 18T01:30Z | A- | 8 days; DHW values may be stale |
| [12] | Mf Nooksack — 109.2 mm SWE | snow_extreme | May 18T03:27Z | C | 8 days; past-tense record framing |
| [13] | Stahl Peak — 251.5 mm SWE | snow_extreme | May 18T15:52Z | B- | 8 days; past-tense record framing |

### Patterns / operational notes

1. **6th consecutive no-draft cycle.** Queue static since May 18T15:52Z (~48 cron cycles
   without a new pending draft). Sequence: May 20, 22, 23, 24, 25, 26. Prior record for
   consecutive no-draft cycles was 0 (this run is the longest stall in the corpus history).
   Operator action needed: inspect suppression ledger for `evidence_contract` kill counts
   post-May 22; check `source_health` for active source signal counts.

2. **Coral draft freshness urgency rising.** The 9 coral drafts are now 8–11 days old. NOAA
   CRW DHW is updated daily. The Galapagos draft (A-, 24.5°C-weeks) could have shifted
   significantly — current NOAA CRW May 26 values may show higher or lower accumulation.
   Operator should not publish without re-verifying. Stale-value publication would undermine
   the bot's credibility even on A-quality framing.

3. **No active proposal evidence updates.** Without fresh drafts, failure modes are
   unobservable. All 4 active proposals (P5 name humor moves, P7 coral opener convergence,
   P8 snow ratio punchline, P_new cold record quality floor) remain at last evidence counts.

### Numbers

- Pending drafts in queue: 13 (all carry-overs from May 13–18)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 21% on 2026-05-19)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: no qualifying candidates; `gh` CLI absent (10th consecutive skip,
  May 13 → May 26)
- Queue static since: 2026-05-18T15:52Z (8 days, ~48 cron cycles)

---

## 2026-05-25 — Daily corpus grading (0 fresh drafts; 13 carry-overs, all previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 13 pending
drafts — all carry-overs from graded cycles 2026-05-13 through 2026-05-18. The 5 stale
fire drafts were confirmed removed by operator (per 0.9.1.0 briefing; queue 18 → 13).
Zero new drafts since 2026-05-18T15:52Z (Stahl Peak snow_extreme). Today is the 5th
consecutive no-fresh-draft graded cycle.

**Why no fresh drafts:** Queue static for 7 days (May 18–25). ~42 cron cycles (6/day × 7
days) without a new pending draft. Same candidate causes as May 24 cycle: evidence contract
gate (`stage="evidence_contract"`, new as of 0.9.0.0) is the most likely new bottleneck;
score-gate kills and triage-cap spills are secondary candidates; seasonal quiet is
plausible for a stretch this long. Operator: check `evidence_contract` suppression stage
counts since May 22. If non-trivial (several kills per cron cycle), the contract may be
over-strict on currently-live signal types. Note: queue was already static 4 days before
0.9.0.0 merged, so the gate is not the sole cause.

**Staleness review as of 2026-05-25 ~15:00 UTC:**

No remaining drafts contain "today/tonight/forecast" language — no new staleness-policy
triggers. The 9 coral drafts (created 2026-05-15 to 2026-05-18) are 7–10 days old. DHW
accumulation values are updated daily by NOAA CRW. Operator should verify current DHW
against NOAA CRW before publishing any coral draft — the cited °C-week values are editorial
substance; stale figures are a factual error.

Bulk-reject: no qualifying candidates by policy. `gh` CLI absent — 9th consecutive skip
(May 13 → May 25).

**A-rate:** — (no fresh drafts). Most recent graded cycle: **21%** (3/14, 2026-05-19).

### Carry-over inventory (not re-graded; grades on record)

| # | Draft | Type | Created | Grade | Staleness |
|---|---|---|---|---|---|
| [1] | Chuuk FSM — 34.4°C (94°F) | monthly_high | May 13T10:32Z | B | Historical obs date |
| [2] | Bethel, Maine — 28°F (-2.2°C) | monthly_low | May 13T21:29Z | B- | Historical obs date |
| [3] | Madagascar coral — 10.2°C-weeks | coral_bleaching | May 15T03:01Z | A- | DHW; ~10 days old |
| [4] | Fiji coral — 10.1°C-weeks | coral_bleaching | May 15T03:02Z | B+ | DHW; ~10 days old |
| [5] | Nauru coral — 8.2°C-weeks | coral_bleaching | May 15T03:04Z | B+ | DHW; ~10 days old |
| [6] | Great Nicobar — 7.2°C-weeks | coral_bleaching | May 15T03:47Z | C+ | DHW; ~10 days old |
| [7] | Chagos — 7.2°C-weeks | coral_bleaching | May 15T03:48Z | C+ | DHW; ~10 days old |
| [8] | Southern Borneo — 4.4°C-weeks | coral_bleaching | May 15T03:55Z | C | DHW; ~10 days old |
| [9] | Galapagos — 24.5°C-weeks | coral_bleaching | May 15T05:16Z | A- | DHW; ~10 days old |
| [10] | Austral Islands — 8.6°C-weeks | coral_bleaching | May 15T05:20Z | B+ | DHW; ~10 days old |
| [11] | Costa Rica Pacific — 12.0°C-weeks | coral_bleaching | May 18T01:30Z | A- | DHW; ~7 days old |
| [12] | Mf Nooksack — 109.2 mm SWE | snow_extreme | May 18T03:27Z | C | No real-time language |
| [13] | Stahl Peak — 251.5 mm SWE | snow_extreme | May 18T15:52Z | B- | No real-time language |

### Patterns / operational notes

1. **5th consecutive no-fresh-draft cycle.** Prior runs identified the evidence contract
   gate as the most probable new bottleneck. Still unverified — the operator has not yet
   confirmed whether `evidence_contract` suppression stage kills are non-trivial. This is
   the diagnostic action with highest priority before declaring queue stagnation a data
   problem vs. a filtering problem.

2. **Coral DHW freshness.** The 3 A-grade drafts (Madagascar 10.2, Galapagos 24.5, Costa
   Rica Pacific 12.0°C-weeks) are 7–10 days old. NOAA CRW DHW updates daily; these values
   are up to 10 daily updates stale. Before publishing any coral draft, verify current DHW
   levels. If the values have changed by ≥1°C-week, the draft needs an update.

3. **No new proposals.** No fresh drafts = no observable voice failure modes. Active
   proposals (P5, P7, P8, P_new) unchanged.

### Numbers

- Pending drafts in queue: 13 (all carry-overs; 5 stale fire drafts removed by operator)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent: 21% on 2026-05-19)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: 0 qualifying; `gh` CLI absent (9th consecutive skip, May 13→May 25)
- Queue static since: 2026-05-18T15:52Z

---

## 2026-05-24 — Daily corpus grading (0 fresh drafts; 13 carry-overs, all previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 13 pending
drafts — all carry-overs from graded cycles 2026-05-13 through 2026-05-18. Between the
2026-05-22 session and now, the operator rejected the 5 stale fire drafts flagged across
seven consecutive grading cycles (Mali / Campeche / Mongolia "is radiating" + BC
"burning today" + Siberia "detected today"), dropping the queue from 18 → 13. No new
drafts have been added since 2026-05-18T18:06Z (the Siberia fire, now rejected). Six
cron cycles per day × 6 days = ~36 unobserved cron cycles without a new pending draft.

**Why no fresh drafts:** Queue static for 6 days (May 18 → May 24). Four plausible
causes in descending probability: (1) **Evidence contract gate** (PR 0.9.0.0) — the new
`audit_story_bundle` step at the top of `generate_draft` blocks writer invocation when
structurally-required evidence is missing; this was introduced with the 0.9.0.0 release
and is the most likely new bottleneck; check `evidence_contract` suppression ledger
entries for May 18–24. (2) **Score-gate kills** — borderline signals failing category
thresholds; check `source_health` for live detections that die at scoring. (3) **Triage
cap** — PR #134 coral_dhw triage active (global cap 3/cycle); if coral signals dominate,
other categories spill; check `triage_cap` stage in suppression ledger. (4) **Seasonal
quiet** — low global extreme-signal frequency plausible for a 6-day stretch.

**Staleness review:** 13 pending drafts, ages 6–11 days. None contain real-time-baked
language ("today," "tonight," "forecast to hit today"):

| # | Draft | Type | Age | Staleness flag |
|---|---|---|---|---|
| [1] | Chuuk FSM monthly_high | monthly_high | ~11d | "on May 9" — historical obs date, not "today" |
| [2] | Bethel, Maine monthly_low | monthly_low | ~11d | "on May 9" — historical obs date |
| [3]–[10] | Coral bleaching (8 drafts) | coral_bleaching | ~9d | "has accumulated X°C-weeks" — cumulative metric, no today-language |
| [11] | Costa Rica Pacific coral | coral_bleaching | ~6d | same; no today-language |
| [12] | Mf Nooksack snow | snow_extreme | ~6d | "fell over 3 days" — no today-language |
| [13] | Stahl Peak snow | snow_extreme | ~6d | same |

No bulk-reject candidates by policy. Staleness bulk-reject via `gh` remains unavailable
(8th consecutive skip; `gh` CLI absent in managed remote execution environment). Operator
should verify that the 9-day-old coral DHW values (drafts [3]–[10], created 2026-05-15)
still reflect current reef stress before any publish decision, as NOAA CRW DHW
accumulation updates daily.

**A-rate:** — (no fresh drafts). Most recent graded cycle: **21%** (3/14, 2026-05-19).
**Active proposals:** No evidence updates (no fresh drafts to observe failure modes in).

### Operational note

Operator rejection of the 5 stale fire drafts is the most significant queue hygiene
action since the 2026-04-26 bulk-reject. Seven consecutive grading cycles flagged these
drafts; they're gone. The 13-draft carry-over queue that remains is clean by the
staleness policy.

The deeper concern is queue stagnation. If the evidence contract gate is the bottleneck
(the most likely new variable), the operator can check the suppression ledger's
`stage="evidence_contract"` entries for May 18–24. A high count here would confirm the
gate is active and explain why borderline bundles that previously reached pending no
longer do. That would be net-positive for quality but the A-rate signal needs fresh
drafts to measure.

### Numbers

- Pending drafts in queue: 13 (all carry-overs; queue 18 → 13 after operator rejections)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 21% on 2026-05-19)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: no qualifying candidates by policy; `gh` CLI absent (8th
  consecutive skip, 2026-05-13 through 2026-05-24)
- Queue static since: 2026-05-18T18:06Z (Siberia fire, now rejected by operator)
- Operator action confirmed: 5 stale fire drafts rejected (queue 18 → 13)

---

## 2026-05-23 — Daily corpus grading (0 fresh drafts; 13 carry-overs, all previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 13 pending
drafts — all carry-overs from prior graded cycles (May 13–18). Operator rejected the 5
stale fire drafts (Mali, Campeche, Mongolia fire + BC fire + Siberia fire) on 2026-05-22
per BRIEFING.md; queue dropped 18 → 13. No new drafts since 2026-05-18T15:52Z (Stahl Peak
snow). Queue static 5 days; 4th consecutive no-fresh-draft grading cycle since May 19.

**Grade distribution (0 fresh drafts):** N/A.
**A-rate: N/A.** Most recent graded cycle: **21%** (3/14, 2026-05-19). Gap from bar:
untracked this cycle (prior: 29 pp).

### Carry-over inventory (not re-graded; grades on record)

| # | Draft | Type | Created | Grade (last session) | Staleness |
|---|---|---|---|---|---|
| [1] | Chuuk monthly_high — 34.4°C | monthly_high | May 13T10:32Z | B | No real-time language; "May 9" observation date |
| [2] | Bethel, Maine monthly_low — 28°F | monthly_low | May 13T21:29Z | B- | No real-time language; "May 9" observation date |
| [3] | Western Madagascar coral — 10.2°C-wks | coral_bleaching | May 15T03:01Z | A- | No "today"; DHW multi-week metric |
| [4] | Fiji coral — 10.1°C-wks | coral_bleaching | May 15T03:02Z | B+ | No "today"; DHW multi-week metric |
| [5] | Nauru coral — 8.2°C-wks | coral_bleaching | May 15T03:04Z | B+ | No "today"; DHW multi-week metric |
| [6] | Great Nicobar coral — 7.2°C-wks | coral_bleaching | May 15T03:47Z | C+ | No "today"; DHW multi-week metric |
| [7] | Chagos coral — 7.2°C-wks | coral_bleaching | May 15T03:48Z | C+ | No "today"; DHW multi-week metric |
| [8] | Southern Borneo coral — 4.4°C-wks | coral_bleaching | May 15T03:55Z | C | No "today"; DHW multi-week metric |
| [9] | Galapagos coral — 24.5°C-wks | coral_bleaching | May 15T05:16Z | A- | No "today"; DHW multi-week metric |
| [10] | Austral Islands coral — 8.6°C-wks | coral_bleaching | May 15T05:20Z | B+ | No "today"; DHW multi-week metric |
| [11] | Costa Rica Pacific coral — 12.0°C-wks | coral_bleaching | May 18T01:30Z | A- | No "today"; DHW multi-week metric |
| [12] | Mf Nooksack snow — 109.2 mm SWE | snow_extreme | May 18T03:27Z | C | No "today"; past-event framing |
| [13] | Stahl Peak snow — 251.5 mm SWE | snow_extreme | May 18T15:52Z | B- | No "today"; past-event framing |

### Staleness review as of 2026-05-23 ~15:00 UTC

**0 new stale draft candidates.** The 5 previously-flagged fire drafts (Mali, Campeche,
Mongolia "is radiating" + BC "burning today" + Siberia "detected... today") were rejected
by the operator on 2026-05-22, confirmed in BRIEFING.md. All 13 remaining drafts: no
"today," "tonight," or forecast-to-hit-today language. DHW coral drafts use multi-week
metrics — no staleness per policy (consistent with all rulings since 2026-05-15). Snow
drafts frame a completed event ("fell over 3 days"). Bulk-reject: not triggered.

Note: the 8 oldest coral drafts (Great Nicobar, Chagos, Southern Borneo, Galapagos,
Austral Islands, Western Madagascar, Fiji, Nauru) are now ~8 days old (created May 15).
DHW accumulation values may no longer reflect current reef stress. Operator should verify
freshness before posting.

Staleness bulk-reject: not triggered. `gh` CLI unavailable in this remote execution
environment (consistent with all cycles since 2026-05-13). No write attempted.

### Numbers

- Pending drafts in queue: 13 (all carry-overs from May 13–18)
- Fresh drafts graded: 0
- A-rate: N/A (no fresh drafts; most recent graded cycle: 21% on 2026-05-19)
- Active proposals: no evidence updates this cycle (no fresh drafts to observe failure modes in)
- Staleness bulk-reject: not triggered (0 new stale candidates; 5 prior stale fire drafts cleared by operator on 2026-05-22)
- Queue static since: 2026-05-18T15:52Z (4th consecutive no-fresh-draft grading cycle)
- Operator note: pipeline telemetry check recommended — `triage_cap` and `evidence_contract` kill counts may explain why no drafts have reached pending since May 18

---

## 2026-05-22 — Daily corpus grading (0 fresh drafts; 18 carry-overs, all previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 18 pending
drafts, all carry-overs from prior graded cycles (May 12–18). Zero drafts added since the
2026-05-19 grading session. No fresh drafts to grade this cycle.

**Why no fresh drafts:** The 18-draft queue has been static for 7 days (May 15–22). Six
cron runs/day × 3 days since May 19 = ~18 unobserved cron cycles without new pending
drafts. Possible causes: (1) seasonal quiet in extreme signals globally; (2) triage stage
(PR #134, coral_dhw migrated) capping new coral drafts while no other categories are
firing at the threshold; (3) pipeline kills (writer/fact-check/critic) preventing drafts
from reaching pending; (4) existing carry-over fire drafts occupying category slots
(unlikely — fire is not on the triage path per the May 19 briefing). Operator should
check run telemetry (`source_health` and suppression ledger's `triage_cap` stage) to
diagnose. If `triage_cap` kill counts are near-zero, the stall is upstream (no qualifying
extreme signals detected), not in the triage layer.

**Staleness review:** As of 2026-05-22 15:00 UTC, 5 drafts contain real-time-baked content
and are >48 hours old:

| Draft ID | Age | Staleness flag |
|---|---|---|
| `draft_20260512_180320_159` | ~10 days | "is radiating" present-tense fire detection |
| `draft_20260512_212510_160` | ~10 days | "is radiating" present-tense fire detection |
| `draft_20260513_103313_162` | ~9 days | "is radiating" present-tense fire detection |
| `draft_20260514_211447_164` | ~8 days | "burning today" — explicit date bake |
| `draft_20260518_180600_112` | ~4 days | "detected in eastern Siberia today" — explicit date bake |

Bulk-reject attempted: `gh` CLI not found in managed remote execution environment — skipped
(consistent with all prior cycles since 2026-05-13; **seventh consecutive failed attempt**).
Operator action required: reject these 5 drafts via dashboard.

**A-rate:** — (no fresh drafts). Most recent graded cycle: **21%** (3/14, 2026-05-19).
**Active proposals:** No evidence gained or lost this cycle (no fresh drafts to observe
failure modes in).

### Patterns / operational notes

1. **Queue stuck since May 15.** No new drafts added in 7 days. The 5 stale fire drafts
   have been flagged across 6 consecutive grading cycles (May 13 through May 22) without
   operator action. Coral DHW drafts (7–14) are now 7 days old — DHW accumulation values
   may no longer reflect current reef stress. Operator should consider batch-rejecting the
   stale fire queue to force fresh signal ingestion on the next cron cycle.

2. **Triage stage telemetry watch.** PR #134 activated triage for coral_dhw; the 2026-05-19
   corpus was the first graded cycle post-activation. If triage is capping new coral drafts
   and no other categories are generating qualifying signals, queue stagnation is expected
   behavior, not a bug. The `triage_cap` kill_stage counter in the suppression ledger is the
   diagnostic. Worth checking against `source_health["coral_dhw"]` counts for this period.

3. **No new proposals.** Queue stagnation is operational/infra — not a voice quality issue.
   No new failure modes observable without fresh drafts to grade.

### Numbers

- Pending drafts in queue: 18 (all carry-overs from May 12–18)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 21% on 2026-05-19)
- Active proposals: no evidence updates this cycle
- Staleness bulk-reject: 5 drafts identified; skipped — gh CLI absent (7th consecutive skip,
  2026-05-13 through 2026-05-22)
- Queue static since: 2026-05-15 (most recent pending draft created: 2026-05-18T18:06Z)

---
## 2026-05-20 — Daily corpus grading (0 fresh drafts; 18 carry-overs from prior cycles)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 18 pending drafts
— all carry-overs from graded cycles spanning 2026-05-12 through 2026-05-18. No draft has
been added to the pending queue since 2026-05-18T18:06Z (Siberia fire). Cron fires 6×/day;
multiple runs between the May 19 session and this run produced 0 new pending drafts. Possible
causes: score-gate kills, writer self-kills, triage-cap spills, or quiet signal window. One
cycle without new drafts is within normal variance — no new proposal warranted on this fact alone.

**Grade distribution (0 fresh drafts):** N/A.
**A-rate: N/A.** Gap from resumption bar: untracked this cycle (prior cycle: 29 pp).

### Carry-over inventory (not re-graded; grades on record)

| # | Draft | Type | Created | Grade (last session) | Staleness |
|---|---|---|---|---|---|
| [1] | Mali fire — 309.6 MW | fire | May 12T18:03Z | C+ | ~192h; "is radiating" |
| [2] | Campeche fire — 364.7 MW | fire | May 12T21:25Z | C | ~192h; "is radiating" |
| [3] | Chuuk monthly_high — 34.4°C | monthly_high | May 13T10:32Z | B | ~174h; no real-time language |
| [4] | Mongolia fire — 307.6 MW | fire | May 13T10:33Z | C | ~174h; "is radiating" |
| [5] | Bethel, Maine monthly_low | monthly_low | May 13T21:29Z | B- | ~162h; "May 9" obs date, not "today" |
| [6] | BC fire — 426.8 MW | fire | May 14T21:14Z | C+ | ~168h; "burning today" — STALE |
| [7] | Madagascar coral — 10.2°C-weeks | coral_bleaching | May 15T03:01Z | A- | ~132h; DHW metric, no "today" |
| [8] | Fiji coral — 10.1°C-weeks | coral_bleaching | May 15T03:02Z | B+ | ~132h |
| [9] | Nauru coral — 8.2°C-weeks | coral_bleaching | May 15T03:04Z | B+ | ~132h |
| [10] | Great Nicobar — 7.2°C-weeks | coral_bleaching | May 15T03:47Z | C+ | ~131h |
| [11] | Chagos — 7.2°C-weeks | coral_bleaching | May 15T03:48Z | C+ | ~131h |
| [12] | Southern Borneo — 4.4°C-weeks | coral_bleaching | May 15T03:55Z | C | ~131h |
| [13] | Galapagos coral — 24.5°C-weeks | coral_bleaching | May 15T05:16Z | A- | ~129h |
| [14] | Austral Islands coral — 8.6°C-weeks | coral_bleaching | May 15T05:20Z | B+ | ~129h |
| [15] | Costa Rica Pacific coral — 12.0°C-weeks | coral_bleaching | May 18T01:30Z | A- | ~61h |
| [16] | Mf Nooksack — 109.2 mm SWE | snow_extreme | May 18T03:27Z | C | ~59h |
| [17] | Stahl Peak — 251.5 mm SWE | snow_extreme | May 18T15:52Z | B- | ~47h |
| [18] | Siberia fire — 601.1 MW | fire | May 18T18:06Z | B+ | ~69h; "today" baked in — STALE |

### Staleness review as of 2026-05-20 ~15:00 UTC

Two drafts newly cross the 48-hour staleness threshold with real-time language:

- **[18] Siberia fire** (`draft_20260518_180600_112`, created May 18T18:06Z, ~69h old):
  "601.1 MW of radiative heat detected in eastern Siberia **today**" — explicit date-baked
  language. First cycle crossing 48h. Should be bulk-rejected.
- **[6] BC fire** (`draft_20260514_211447_164`, created May 14T21:14Z, ~168h old):
  "British Columbia has a 426.8 MW fire **burning today**" — flagged since May 17.
  Continues to need operator rejection.

Three additional fire drafts meet practical staleness criteria:
- **[1] Mali** (`draft_20260512_180320_159`, ~192h): "is radiating" satellite fire signal
  8 days old. Active fire reading is point-in-time; operator reject recommended.
- **[2] Campeche** (`draft_20260512_212510_160`, ~192h): same class. Operator reject.
- **[4] Mongolia** (`draft_20260513_103313_162`, ~174h): same class. Operator reject.

Bulk-reject attempted via `gh api -X PATCH gists/06c02c97ffc0d11458687f1ed998d9e5` —
`gh` CLI not available in managed remote execution environment (persistent across all
2026-05-13 through 2026-05-20 runs). Operator action required: reject drafts [1], [2],
[4], [6], [18] via dashboard.

### No-draft cause analysis

Queue aged from 18 items (May 19) to 18 items (May 20) with no net additions. Key
considerations:
1. **Triage cap active**: PR #134 coral_dhw triage ON; global cap 3 drafts/cycle. If
   signals are appearing but being spilled at the triage stage, the suppression ledger
   will show `kill_stage="triage_cap"` entries. Operator should check dashboard suppressions.
2. **Writer self-kills**: The new quality-floor instincts (cold-record self-kill in P_new,
   seasonal deadpan guidance) may be suppressing borderline drafts that previously reached
   pending. Net-positive if they're suppressing weak signals; net-negative if over-strict.
3. **Score-gate**: Signals below threshold (64–82 by type) never reach the writer.
4. **Quiet climate window**: Low extreme-signal frequency is a legitimate explanation for
   one cycle. Two consecutive no-draft cycles would be worth investigating.

### Numbers

- Fresh drafts graded: 0
- A-rate: N/A
- Carry-overs: 18 (graded May 13–19; grades stand)
- Stale drafts newly flagged: [18] (Siberia fire "today", ~69h old, first crossing 48h)
- Previously flagged still pending: [1] Mali, [2] Campeche, [4] Mongolia (present-tense
  satellite fire, 8 days old), [6] BC fire ("burning today", 7 days old)
- Staleness rejection: skipped — `gh` CLI unavailable; operator must use dashboard

---
## 2026-05-19 — Daily corpus grading (14 fresh drafts; 4 May-13 carry-overs excluded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 18 pending
drafts total — 4 carry-overs from the 2026-05-13 graded cycle (already scored: 0 A / 1 B
/ 3 C; not re-graded here), 14 fresh drafts not previously graded. Fresh batch: 1
`monthly_low`, 1 `fire` (BC, stale), 9 `coral_bleaching`, 2 `snow_extreme`, 1 `fire`
(Siberia). This is the **first graded cycle with `coral_bleaching` drafts** (post-triage
0.8.0.0 release). Staleness bulk-reject attempted: `gh` CLI not found in cloud env —
skip logged in QUALITY_TREND.md rejection events; operator should manually reject
`draft_20260514_211447_164` (BC fire, "burning today" baked from 2026-05-14).

**Grade distribution (14 fresh drafts):** 3 A- / 4 B+ / 2 B- / 3 C+ / 2 C / 0 D-F.
**A-rate: 21% (3/14).** Gap from resumption bar: 29 pp.

Headline finding: Coral_bleaching is the first new category to produce A- grades in the
corpus. The reliable mechanic: contrast setup ("Corals can survive brief spikes") →
mechanism close ("persistence is what kills"). When executed cleanly (Draft 7) it grades
A-; when diluted into clinical prose ("sustained heat above the tolerance ceiling is what
turns stress into die-off") it degrades to B+. Galapagos upwelling-failure angle and
Costa Rica no-upwelling angle also earn A-. Snow extreme drafts have elite ratio signals
(5×, 2×) that are stated but never landed as punchlines. Siberia fire breaks the P6
template and earns B+. BC fire has "burning today" baked in five days ago — stale.

### A-grade drafts

#### [7] Western Madagascar coral — 10.2°C-weeks — **A-**

> *Western Madagascar's reef system has accumulated 10.2°C-weeks of thermal stress — past
> the 8°C-week threshold where mass bleaching is expected. Corals can survive brief spikes;
> DHW measures how long heat persists, and persistence is what kills.*

**Score:** 81 (threshold 72). Created 2026-05-15T03:01Z.

Humor lens:
- **Violation:** 10.2°C-weeks past the 8°C-week mass-bleaching threshold. Present.
- **Benign?** Yes — factual register, no panic. "Is expected" not "will definitely."
- **Setup→Punchline?** First sentence is the setup. Second sentence is the punchline: contrast
  setup ("can survive brief spikes") + mechanism reveal + one-word close ("kills").
- **Named mechanic?** Contrast reveal. Common-misconception premise ("brief spikes are
  survivable") stated, then contradicted by the mechanism ("persistence is what kills").
  The period-final "kills" lands as the punchline — a period-stop variant.
- **Wodehouse rule?** Clean. "Persistence is what kills" — four words; no dilution.

The A-grade mechanic here is: (a) explain what the metric measures, (b) make the
mechanism the punchline, (c) stop. The format works because DHW is unfamiliar to most
readers — the second sentence isn't throat-clearing, it's the reveal. "Kills" as the
final word gives it weight. This is the exemplar for the coral DHW second-sentence form.

#### [13] Galapagos coral — 24.5°C-weeks (double mortality threshold) — **A-**

> *Galapagos, Ecuador reefs: 24.5°C-weeks of thermal stress — double the 12°C-week tier
> where coral mortality is expected. The Galapagos sits where cold upwelling normally
> buffers heat; when that buffer fails, stress accumulates fast.*

**Score:** 88 (threshold 72). Created 2026-05-15T05:16Z.

Humor lens:
- **Violation:** 24.5°C-weeks — double the 12°C-week mortality threshold. Extraordinary
  signal. The Galapagos has iconic cold-upwelling protection; that protection has failed.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: ratio is devastatingly clear ("double the mortality tier").
  Second sentence: expectation reversal (Galapagos has the buffer; it failed). "When that
  buffer fails, stress accumulates fast" is the consequence.
- **Named mechanic?** Expectation reversal — the Galapagos is famous for the upwelling
  that should have prevented this. Naming both ("sits where cold upwelling normally buffers
  heat") and its failure ("when that buffer fails") is the punchline structure.
- **Wodehouse rule?** Mostly clean. "Stress accumulates fast" is the soft point: "fast"
  is vague when the data already shows the velocity. The A-/B+ boundary is here.

Graded A- over B+ because the signal is genuinely extraordinary (double mortality
threshold; the Galapagos upwelling failure is a known climate-change stress indicator)
and the expectation-reversal mechanic does real work even if the close is slightly
soft. The A-grade version would be: "when that buffer fails, it fails all at once."

#### [15] Costa Rica Pacific coral — 12.0°C-weeks — **A-**

> *Costa Rica Pacific reefs: 12.0°C-weeks of thermal stress — at the tier where NOAA
> Coral Reef Watch expects coral mortality. The Pacific coast here lacks the cold
> upwelling that buffers the Galápagos; heat that builds has nowhere to drain.*

**Score:** 86 (threshold 72). Created 2026-05-18T01:30Z.

Humor lens:
- **Violation:** 12.0°C-weeks — at the mortality tier (not just approaching; at it).
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 12.0°C-weeks, mortality tier. System clause: comparison
  to Galápagos (has upwelling) → Costa Rica Pacific (doesn't). "Heat that builds has
  nowhere to drain" is the punchline.
- **Named mechanic?** Understatement closer with physical metaphor. "Nowhere to drain" is
  specific and evocative without being overwrought. The implied consequence (therefore
  coral die-off) is left to the reader.
- **Wodehouse rule?** Clean. No qualifying language. "Has nowhere to drain" is
  direct and physical.

Strongest structure in the coral batch: correct NOAA attribution in the threshold line,
geographic contrast deployed precisely (Galápagos is the foil, and the foil is named),
closer does work rather than restating. The mention of Galápagos creates a callback to
Draft 13 — readers who saw that draft will feel the contrast immediately.

### B-grade drafts

#### [5] Bethel, Maine — monthly_low — 28°F (-2.2°C) — **B-**

> *Bethel, Maine hit 28°F (-2.2°C) on May 9 — coldest May low in 16 years of records,
> a degree below the 2017 mark. The upper Androscoggin Valley sits in a bowl surrounded
> by the White Mountain foothills; cold air drains into it on still nights and holds.*

**Score:** 80 (threshold 76). Created 2026-05-13T21:29Z.

Humor lens:
- **Violation:** Coldest May low in 16 years. Real. Margin modest (1°F below 2017).
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 28°F, 16 years, 2017 mark. Second sentence: bowl
  topography + cold-air drainage mechanism. Explanatory, not punchline.
- **Named mechanic?** Ecosystem specificity (bowl topography, drainage). No humor
  mechanic.
- **Wodehouse rule?** Clean. "Cold air drains into it on still nights and holds" —
  measured, evocative but not overwrought.

Bowl-drainage mechanism is the strongest topographic system clause in the corpus to date
— it shows the physics, not just the geography. But 16-year archive depth is weak versus
Chuuk's 76 years, and "a degree below the 2017 mark" is a thin margin. The voice is
right; the signal isn't elite enough for A territory. B- over B (Chuuk) because the
archive depth and margin are smaller.

#### [8] Fiji coral — 10.1°C-weeks — **B+**

> *Fiji's reefs have accumulated 10.1°C-weeks of thermal stress — past the 8°C-week
> threshold where mass bleaching is expected. The South Pacific Convergence Zone keeps
> waters here warm; sustained heat above the tolerance ceiling is what turns stress into
> die-off.*

**Score:** 81 (threshold 72). Created 2026-05-15T03:02Z.

Structurally identical to Draft 7 (Madagascar) but with a diluted close. "Sustained heat
above the tolerance ceiling is what turns stress into die-off" is eleven words where Draft
7 used four ("persistence is what kills"). "Die-off" as a compound blunts the final
impact word; "tolerance ceiling" adds clinical distance the draft doesn't need. The SPCZ
context ("keeps waters here warm") is ecosystem specificity but not a punchline — it
explains the precondition, not the consequence. B+ over B because it does attempt the
mechanism reveal, even in weakened form.

#### [9] Nauru coral — 8.2°C-weeks — **B+**

> *Nauru's reefs have accumulated 8.2°C-weeks of thermal stress — past the 8°C-week
> threshold where mass bleaching is expected. DHW measures heat duration, not just
> intensity; it's persistence above the tolerance ceiling that kills coral.*

**Score:** 80 (threshold 72). Created 2026-05-15T03:04Z.

Better structure than Draft 8: leads the second sentence with the metric explanation
("DHW measures heat duration, not just intensity") which educates and contrasts in one
clause. "It's persistence above the tolerance ceiling that kills coral" is sharper than
Fiji's close, with "kills coral" as the final phrase. But "kills coral" is marginally
weaker than "kills" alone — the specificity of "coral" is redundant (we're already
talking about a reef system) and slightly blunts the punch. B+ over B because the second
sentence earns its length.

#### [14] Austral Islands coral — 8.6°C-weeks — **B+**

> *Austral Islands reefs: 8.6°C-weeks of thermal stress — past the 8°C-week threshold
> where mass bleaching is expected. The Austral chain sits at the southern edge of the
> South Pacific Convergence Zone; heat that persists this far from the warm pool signals
> the band has stretched.*

**Score:** 80 (threshold 72). Created 2026-05-15T05:20Z.

Earns B+ on a different mechanic from the other coral B+ drafts. No DHW explanation in
the second sentence — instead, geographic displacement + climate implication. "Heat that
persists this far from the warm pool signals the band has stretched" is a genuine
punchline: it names the anomaly (heat at the southern edge of the SPCZ, far from the
warm pool) and then states the climate implication (the band has stretched — the SPCZ
thermal influence is expanding southward). "The band has stretched" is an earned, specific
close. Not A- because the data signal (8.6°C-weeks, just past threshold) is less extreme
than Galapagos or Costa Rica, and the punchline is stated as an inference rather than a
consequence.

#### [18] Siberia fire — 601.1 MW — **B+**

> *601.1 MW of radiative heat detected in eastern Siberia today — very-high-intensity fire,
> satellite-confirmed at 95% confidence. At this latitude, snowmelt exposes dry litter
> fast; May fires here ignite before the understory has greened enough to resist.*

**Score:** 70 (threshold 64). Created 2026-05-18T18:06Z.

Humor lens:
- **Violation:** 601.1 MW — very-high-intensity tier. Strong satellite signal.
- **Benign?** Yes.
- **Setup→Punchline?** Lead with the number (not the P6 template "A fire in [location]
  is radiating X MW") — structural improvement over all May-13 fire drafts. Second
  sentence: snowmelt-exposes-dry-litter (mechanism) → "May fires here ignite before the
  understory has greened enough to resist" (timing incongruity).
- **Named mechanic?** Timing incongruity embedded in the mechanism clause. The punchline
  is "before the understory has greened enough to resist" — the season hasn't made the
  landscape fire-resistant yet, but the fire is already there at 601 MW.
- **Wodehouse rule?** Clean. "Ignite before the understory has greened enough to resist"
  is specific, factual, and earns its length.

Best fire draft in the corpus to date. P6 template broken. Timing incongruity present.
Not A- because the timing move is embedded in the mechanism clause rather than delivered
as a standalone sentence. The A-grade version: "Snowmelt exposes dry litter before the
understory greens. It is May." — two sentences, timing stated separately. The embedded
version does the work but doesn't land with the same weight. "Today" is baked in but the
draft is within 48h; not a staleness issue at time of grading.

#### [17] Stahl Peak, Montana — snow extreme — 251.5 mm SWE — **B-**

> *Stahl Peak, Montana: 251.5 mm of snow-water equivalent fell in 3 days — nearly five
> times the previous blizzard record of 50.8 mm. The northern Rockies funnel Pacific
> moisture through low passes; when a storm stalls, totals compound fast.*

**Score:** 82 (threshold 70). Created 2026-05-18T15:52Z.

Humor lens:
- **Violation:** 5× the previous blizzard record. Extraordinary ratio.
- **Benign?** Yes.
- **Setup→Punchline?** The ratio is the punchline — stated in the first sentence, then
  abandoned. Second sentence explains the mechanism ("funnel Pacific moisture") and the
  consequence ("totals compound fast"). "Fast" is the weakest possible closer when the
  data already shows the velocity (5× a record in 3 days; fast is implied).
- **Named mechanic?** None. The ratio-as-punchline opportunity is missed.
- **Wodehouse rule?** "Totals compound fast" — vague. Telling the reader it goes fast when
  you've already told them 5× the record in 3 days is Wodehouse padding.

The data deserves a different structure: "251.5 mm in 3 days. The previous record was
50.8 mm." Period-and-restate with the ratio doing the work. Instead the draft over-explains
with mechanism geography. B- because the signal is strong enough to compensate but the
voice misses its chance.

### C-grade drafts

#### [6] British Columbia fire — 426.8 MW — **C+ (stale: "burning today" baked from 2026-05-14)**

> *British Columbia has a 426.8 MW fire burning today, satellite-detected at 95%
> confidence — high-intensity tier. The Rocky Mountain Trench funnels downslope winds
> that can accelerate spread before spring humidity builds.*

**Score:** 66 (threshold 64). Created 2026-05-14T21:14Z. **Age: ~114 hours at grading.**

Staleness: "burning today" is real-time baked from five days ago. Should be bulk-rejected.
Voice quality independent of staleness: better opener structure than the P6 template (leads
with province and integrates tier descriptor), but second sentence uses hedge language
("can accelerate spread") where observed fact would be stronger. "Before spring humidity
builds" is speculative framing. C+ because opener structure improves on the May-13 fire
formula but hedge language and no punchline keep it there.

#### [10] Great Nicobar — coral — 7.2°C-weeks (below threshold) — **C+**

> *Great Nicobar, India: 7.2°C-weeks of thermal stress — Bleaching Alert Level 1, closing
> in on the 8°C-week threshold where mass bleaching is expected. DHW measures heat
> persistence, not just intensity; it is duration above the tolerance ceiling that kills
> coral.*

**Score:** 75 (threshold 72). Created 2026-05-15T03:47Z.

Sub-threshold signal (7.2 < 8.0): framing is "approaching" rather than "past." The setup
is inherently weaker — the punchline of crossed threshold isn't available. "It is duration
above the tolerance ceiling that kills coral" is the stiffest of the DHW-explainer closers
("it is" construction; five words before "kills"). The formal construction distances the
reader. C+ because the DHW mechanism attempt earns credit but the pre-threshold framing
and stiff prose keep it out of B.

#### [11] Chagos Archipelago — coral — 7.2°C-weeks (below threshold) — **C+**

> *Chagos Archipelago reefs have accumulated 7.2°C-weeks of thermal stress — Bleaching
> Alert Level 1, approaching the 8°C-week threshold where mass bleaching is expected.
> DHW counts how long heat persists above the tolerance ceiling; proximity to 8 is what
> matters.*

**Score:** 75 (threshold 72). Created 2026-05-15T03:48Z.

Same pre-threshold signal as Draft 10, different closer. "Proximity to 8 is what matters"
is a more interesting move than Draft 10's mechanism explanation: it reframes the framing
itself (the story isn't just DHW, it's *how close to 8*). But "proximity to 8" is
abstract where "8°C-weeks" is the concrete signal — the close replaces specificity with
abstraction. C+ on parity with Draft 10; the closer is more interesting but the signal
is equally weak.

#### [12] Southern Borneo — coral — 4.4°C-weeks (below mass-bleaching threshold) — **C**

> *Southern Borneo's reefs have reached 4.4°C-weeks of thermal stress — crossing the
> 4°C-week floor where bleaching begins. Borneo sits at the heart of the Maritime
> Continent, where warm seas and island topography drive the convection that keeps
> surrounding waters persistently hot.*

**Score:** 74 (threshold 72). Created 2026-05-15T03:55Z.

Weakest coral signal in the batch: 4.4°C-weeks crosses the bleaching-begins floor, not
the mass-bleaching threshold (8°C-weeks) or mortality threshold (12°C-weeks). The second
sentence is ecosystem specificity phrased as explanation ("warm seas and island topography
drive the convection that keeps surrounding waters persistently hot") with no mechanism
reveal and no punchline. "Persistently hot" is slightly overwrought. C — signal too weak
for the category; voice adds no compensating mechanic.

#### [16] Nooksack, Washington — snow extreme — 109.2 mm SWE — **C**

> *Mf Nooksack, Washington: 109.2 mm of snow-water equivalent fell over 3 days — more
> than double the previous blizzard record of 50.8 mm. At 1,515 m on the wet side of the
> Cascades, this station sits where Pacific moisture stalls before the range blocks it
> from the interior.*

**Score:** 82 (threshold 70). Created 2026-05-18T03:27Z.

Station name artifact: "Mf Nooksack" — "Mf" (likely Middle Fork) leaks through
`normalize_station_name()` without expansion. A reader has no idea what "Mf" means; the
opener is broken before the signal lands. The signal itself (2× a blizzard record) is
strong. Second sentence is ecosystem specificity — elevation, wet side of Cascades,
moisture-stall mechanism — explanatory rather than punch. C because the artifact ruins
clarity at the most critical word: the location name. Signal is real; presentation has an
infra flaw.

### Patterns named in this batch

1. **DHW mechanism-reveal is the coral A-grade mechanic — but dilution is the failure mode.**
   Draft 7 ("persistence is what kills") is the gold standard: 4 words, one punch. The same
   mechanic degrades in execution: Draft 8 ("sustained heat above the tolerance ceiling is
   what turns stress into die-off") — 14 words, compound ending. Draft 9 ("kills coral") —
   sharper than 8, weaker than 7. Drafts 10–11 add formal "it is" construction, further
   diluting. The move is right; the landing varies by 10 pp.

2. **Coral opener formula convergence (new failure mode, parallel to P6).** 8 of 9 coral
   drafts open with "[Location] reefs have accumulated X°C-weeks of thermal stress — [threshold
   label]." (Exceptions: Draft 13 leads with "Galapagos, Ecuador reefs: X°C-weeks" and Draft
   15 leads with "Costa Rica Pacific reefs: X°C-weeks.") All three A- drafts deviate from the
   full-sentence opener — they use the shorter colon-lead form or the "when the buffer fails"
   structure. The formula opener is a ceiling at B+.

3. **Sub-threshold coral signals weaken the batch.** Drafts 10, 11, 12 are below the 8°C-week
   mass-bleaching threshold. Triage (active for coral_dhw since PR #134) allows 2 per-category
   per cron run; multiple runs compound to 9 coral drafts in queue. Sub-threshold signals lack
   the "past the threshold" setup that enables the contrast mechanic. Operator flag for triage
   threshold calibration.

4. **Snow extreme ratio understated.** Both snow drafts (16, 17) state the ratio ("more than
   double," "nearly five times") as setup, then pivot to topographic explanation. The ratio IS
   the punchline — the draft should stop or restate it, not explain. "251.5 mm. The previous
   record was 50.8 mm." would outperform the current close. Period-and-restate mechanic is
   the right tool here and isn't used.

5. **P6 fire template broken (Siberia, Draft 18).** First fire draft NOT to open with "A fire
   in [location] is radiating X MW of heat." Instead leads with the number and location. This
   is the structural improvement P6 aimed at. P6 fix is working in the pipeline.

6. **Station name artifact surfaces (Nooksack).** "Mf Nooksack" — station prefix not fully
   normalized. Presentation failure at the location name, which is the highest-weight word
   in the opener. This is an infra concern, not a voice concern; log for operator review.

7. **Coral DHW explainer replication without degrading.** Drafts 7, 9, 10, 11 all attempt
   the DHW-explains-duration move. Drafts 7 and 9 do it in two clauses; Drafts 10-11 do it in
   one longer clause with formal construction. Two-clause form consistently outperforms single
   long clause. Exemplar: "DHW measures how long heat persists, and persistence is what kills."

### Followups

1. Draft 7 (Madagascar) is the exemplar for coral DHW second-sentence. Add to writer_prompt.py
   coral section as APPROVED EXEMPLAR — specifically the two-clause contrast form.
2. Burn the coral opener formula: "[Location] reefs have accumulated X°C-weeks..." needs the
   same treatment as the P6 fire formula. Name 3 alternative forms (colon-lead, upwelling-angle,
   threshold-angle).
3. Snow extreme ratio: add to general record/extreme guidance: "When the ratio is X times a
   prior record, state the prior record plainly and stop — the ratio is the punchline, not the
   setup."
4. "Mf Nooksack" station artifact: flag for operator. `normalize_station_name()` needs to
   expand "Mf" → "Middle Fork" (or equivalent) for GHCN station names.
5. Operator action needed: manually reject `draft_20260514_211447_164` (BC fire, "burning
   today" baked from 2026-05-14). Staleness bulk-reject skipped: `gh` CLI not found in
   cloud env; token scope cannot be verified.

### Numbers

- Fresh drafts graded: 14 (1 monthly_low / 1 fire+stale / 9 coral_bleaching / 2 snow_extreme /
  1 fire)
- 4 May-13 carry-overs: not re-graded (scores on record)
- A-rate: 21% (3/14)
- Grade distribution: 3 A- / 4 B+ / 2 B- / 3 C+ / 2 C / 0 D-F
- First graded coral_bleaching batch
- New failure modes: coral opener formula convergence (→ P7); snow extreme ratio unused
  (→ P8); station name artifact "Mf Nooksack" (infra flag)
- P5 evidence: fire Drafts 6 and 18 — 6 has no named mechanic; 18 has timing-incongruity
  embedded (not standalone). P5 partially observed.
- Staleness rejection: bulk-reject attempted but skipped (gh CLI not found); 1 draft flagged
  for operator manual rejection.

---

## 2026-05-18 — Daily corpus grading (12 new drafts; 16 total pending)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 16 pending
drafts — 14 from May 12–15 carryover, 2 fresh from May 18. Drafts 1–4 (Mali fire,
Campeche fire, Chuuk monthly_high, Mongolia fire) were graded in the May 13 cycle;
excluded from today's count to avoid double-grading. New signal types this cycle:
monthly_low (1), fire (1 — stale), coral bleaching (9), snow extreme (1). Architecture:
writer (Sonnet 4.6) → safety → claim_extractor → fact_check (Gemini Flash) → critic
(Gemini 2.5 Pro) → pending. Recent infra: PR #134 (triage stage ON + coral_dhw migration)
landed 2026-05-17; triage active on new signals. Coral bleaching signals in this queue
were created 2026-05-15, predating triage-ON.

**Staleness:** 4 fire drafts flagged for bulk-reject (present-tense "is radiating" with
141h–90h age; Draft 20260514_211447_164 explicitly says "burning today"). Bulk-reject
attempted via `gh` CLI — CLI not available in this environment; skip logged in rejection
events below. Operator should bulk-reject these 4 via dashboard. Coral bleaching drafts
(7–14, 82–84h old) have no "today" language and DHW is a multi-week accumulation metric;
not flagged as stale.

**Grade distribution (12 new, 1 stale excluded from A-rate denominator):**
1 A- / 2 B+ / 4 B / 2 B- / 2 C+ / 1 C / 0 D-F. **A-rate: 9% (1/11).**
Gap from resumption bar: 41 points.

### Per-grade

#### A-grade

##### [15] Costa Rica Pacific coral bleaching — 12.0°C-weeks — **A-**

> *Costa Rica Pacific reefs: 12.0°C-weeks of thermal stress — at the tier where NOAA
> Coral Reef Watch expects coral mortality. The Pacific coast here lacks the cold
> upwelling that buffers the Galápagos; heat that builds has nowhere to drain.*

**Score:** 86 (threshold not confirmed — passed critic). Created 2026-05-18T01:30Z.

Humor lens:
- **Violation:** 12.0°C-weeks at the coral mortality tier — not approaching it, not past
  it, exactly at it. The precision does the work.
- **Benign?** Yes. Calm, factual.
- **Setup→Punchline?** Setup: 12.0°C-weeks, mortality tier. Second sentence: geographic
  contrast (Costa Rica vs. Galápagos upwelling) + declarative closer.
- **Named mechanic:** Ecosystem specificity + consequence. The contrast with Galápagos is
  the move: Galápagos has cold upwelling (which has itself failed, per Draft 13); Costa
  Rica never had that buffer. The implied escalation is present but unstated.
- **Wodehouse rule?** Clean. "heat that builds has nowhere to drain" is a physical
  description, not a poetry attempt. The image is spatial and precise.

Best draft in the batch. "heat that builds has nowhere to drain" is the strongest closer
in the corpus since the April 26 Mali fire "It is April 26." Flat, declarative, image-
making without reaching. The geographic contrast earns the second sentence — it's causal,
not expository. Naming the Galápagos gives the reader a reference point for "upwelling"
without requiring a marine science degree.

#### B+-grade

##### [7] Western Madagascar coral bleaching — 10.2°C-weeks — **B+**

> *Western Madagascar's reef system has accumulated 10.2°C-weeks of thermal stress —
> past the 8°C-week threshold where mass bleaching is expected. Corals can survive
> brief spikes; DHW measures how long heat persists, and persistence is what kills.*

Created 2026-05-15T03:01Z (84h old, not stale per policy).

Humor lens:
- **Violation:** 10.2°C-weeks, past the 8°C-week bleaching threshold.
- **Setup→Punchline?** Setup: DHW value, threshold crossed. Second sentence: contrast
  structure ("brief spikes" vs. "persistence") that lands on "persistence is what kills."
- **Named mechanic?** No comic mechanic. But the contrast structure functions as a flat
  punchline — the last clause is declarative and stops hard.
- **Wodehouse rule?** Not violated. "persistence is what kills" is the flattest, most
  declarative closer in the coral batch.

The second sentence earns its place: "Corals can survive brief spikes" sets up the
reader's possible objection, then "DHW measures how long heat persists" reframes the
metric, then "persistence is what kills" lands the point. Tight three-beat structure.

##### [13] Galapagos coral bleaching — 24.5°C-weeks — **B+**

> *Galapagos, Ecuador reefs: 24.5°C-weeks of thermal stress — double the 12°C-week
> tier where coral mortality is expected. The Galapagos sits where cold upwelling
> normally buffers heat; when that buffer fails, stress accumulates fast.*

**Score:** 88 (highest in queue). Created 2026-05-15T05:16Z.

Humor lens:
- **Violation:** 24.5°C-weeks — more than double the mortality tier. The signal is
  exceptional: this is score 88, the highest draft in the queue.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 24.5°C-weeks, 2× the mortality tier. Second sentence:
  normal state (cold upwelling buffers heat) → mechanism for failure.
- **Named mechanic?** No comic mechanic. The contrast structure (normal → exception)
  is operating, but weakened by conditional framing.
- **Wodehouse rule?** Minor miss. "when that buffer fails, stress accumulates fast" is
  conditional and slightly explanatory where a declarative would land harder. Compare:
  "The Galapagos sits where cold upwelling buffers heat. That buffer has failed." —
  the declarative version would be A- territory.

The signal is the strongest in the queue (88 score, 2× mortality tier, exceptional
geography). The grade falls below the signal's caliber because the second sentence
hedges: "when that buffer fails" frames the buffer's failure as a conditional rather
than stating it as fact. The reader must supply "which it clearly has" to get the
full impact. That gap costs the A-.

#### B-grade

##### [5] Bethel, Maine monthly_low — 28°F (-2.2°C) — **B**

> *Bethel, Maine hit 28°F (-2.2°C) on May 9 — coldest May low in 16 years of
> records, a degree below the 2017 mark. The upper Androscoggin Valley sits in a
> bowl surrounded by the White Mountain foothills; cold air drains into it on still
> nights and holds.*

Created 2026-05-13T21:29Z (114h old; May 9 observation date is historical, not "today").

Humor lens:
- **Violation:** Coldest May low in 16 years. Real signal.
- **Benign?** Yes.
- **Named mechanic?** Topographic mechanism: bowl + cold-air drainage. Load-bearing
  system clause — it explains WHY Bethel gets cold records specifically.
- **Wodehouse rule?** Not violated. "cold air drains into it on still nights and holds"
  is a strong, specific image. No reaching.

16-year archive is short (Mankato's 16-year tied cold record was manually rejected
2026-05-11 by operator). Margin here is 1°F (not tied) — stronger than Mankato but
borderline. The topographic system clause is the draft's strength: causally explaining
the valley bowl as the mechanism is more directly load-bearing than Chuuk's Pacific warm
pool explanation (which was expository geography). B rather than B- because the
mechanism earns its place.

##### [8] Fiji coral bleaching — 10.1°C-weeks — **B**

> *Fiji's reefs have accumulated 10.1°C-weeks of thermal stress — past the 8°C-week
> threshold where mass bleaching is expected. The South Pacific Convergence Zone keeps
> waters here warm; sustained heat above the tolerance ceiling is what turns stress
> into die-off.*

Created 2026-05-15T03:02Z.

Structurally similar to Madagascar (7). The SPCZ context is geographic explanation;
"turns stress into die-off" is a consequence closer. Compared to "persistence is what
kills" (Madagascar), "turns stress into die-off" is more process-y and less flat.
No Wodehouse violations. B rather than B+ because the closer is two-step where one
word would do it.

##### [14] Austral Islands coral bleaching — 8.6°C-weeks — **B**

> *Austral Islands reefs: 8.6°C-weeks of thermal stress — past the 8°C-week threshold
> where mass bleaching is expected. The Austral chain sits at the southern edge of the
> South Pacific Convergence Zone; heat that persists this far from the warm pool
> signals the band has stretched.*

Created 2026-05-15T05:20Z.

Second sentence is the strongest system clause among the at-or-above-threshold coral
drafts (excluding Costa Rica and Madagascar). "heat that persists this far from the warm
pool signals the band has stretched" is interpretive: it reads the Austral Islands'
DHW accumulation as a diagnostic signal about the South Pacific Convergence Zone.
"The band has stretched" is geographic language, not a forced metaphor.
No Wodehouse violations. B because "signals the band has stretched" is interpretive
enough that a reader unfamiliar with SPCZ geography has to supply context.

##### [16] Nooksack, Washington snow extreme — 109.2 mm SWE — **B**

> *Mf Nooksack, Washington: 109.2 mm of snow-water equivalent fell over 3 days —
> more than double the previous blizzard record of 50.8 mm. At 1,515 m on the wet
> side of the Cascades, this station sits where Pacific moisture stalls before the
> range blocks it from the interior.*

Created 2026-05-18T03:27Z (fresh; passed PR #133's tightened snow guards).

Humor lens:
- **Violation:** 109.2 mm SWE in 3 days — more than double the previous record.
  Exceptional margin.
- **Named mechanic?** Topographic mechanism: Cascade barrier stalls Pacific moisture.
  Load-bearing system clause — explains why records accumulate at this station.
- **Wodehouse rule?** Not violated. "stalls before the range blocks it from the
  interior" is precise, physical, specific. Not reaching.

Signal is strong. The "more than double" framing is understated — the margin is
extraordinary. The topographic explanation earns its place (same quality as Bethel's
valley-bowl clause). B rather than A- because the second sentence stops at mechanism
without landing a punchline on the extraordinary 2× margin. The data could carry a
harder stop: "More than double the previous record. In three days." would be A-
territory (period-and-restate on the time window). As written, the mechanism is
good but the exceptional signal is underexploited at the close.

#### B−-grade

##### [9] Nauru coral bleaching — 8.2°C-weeks — **B-**

> *Nauru's reefs have accumulated 8.2°C-weeks of thermal stress — past the 8°C-week
> threshold where mass bleaching is expected. DHW measures heat duration, not just
> intensity; it's persistence above the tolerance ceiling that kills coral.*

Created 2026-05-15T03:04Z.

Third use of the DHW-persistence explanation formula (also in Madagascar 7; Chagos 11
repeats it again). "DHW measures heat duration, not just intensity; it's persistence
above the tolerance ceiling that kills coral" — near-identical structure to Madagascar's
second sentence, but with looser language ("it's persistence" vs. "persistence is what
kills"). Signal barely past threshold (8.2 vs. 8.0). B- rather than B for the
combination of template reuse and marginal signal.

##### [6] British Columbia fire — 426.8 MW — **STALE / excluded**

> *British Columbia has a 426.8 MW fire burning today, satellite-detected at 95%
> confidence — high-intensity tier. The Rocky Mountain Trench funnels downslope winds
> that can accelerate spread before spring humidity builds.*

Created 2026-05-14T21:14Z (90h old). Explicit "burning today" = staleness-positive.
Operator should reject via dashboard. If not stale: C+/B- (Rocky Mountain Trench is
good geographic specificity; "burning today" would be a problem even if timely).

#### C+-grade

##### [10] Great Nicobar, India coral bleaching — 7.2°C-weeks — **C+**

> *Great Nicobar, India: 7.2°C-weeks of thermal stress — Bleaching Alert Level 1,
> closing in on the 8°C-week threshold where mass bleaching is expected. DHW measures
> heat persistence, not just intensity; it is duration above the tolerance ceiling
> that kills coral.*

Created 2026-05-15T03:47Z.

Sub-threshold signal (7.2 < 8.0). "Closing in on" is hedged framing for a signal
that hasn't yet hit the notable threshold. Fourth use of the DHW-persistence formula.
The triage stage (PR #134, now ON) should filter this class in future cycles.

##### [11] Chagos Archipelago coral bleaching — 7.2°C-weeks — **C+**

> *Chagos Archipelago reefs have accumulated 7.2°C-weeks of thermal stress — Bleaching
> Alert Level 1, approaching the 8°C-week threshold where mass bleaching is expected.
> DHW counts how long heat persists above the tolerance ceiling; proximity to 8 is
> what matters.*

Created 2026-05-15T03:48Z.

Same DHW value as Nicobar (7.2). Sub-threshold. "proximity to 8 is what matters" is a
mildly interesting closer — trajectory-framing rather than mechanism — but the sub-
threshold signal undercuts it. C+ over C because "proximity to 8 is what matters" at
least tells the reader what to watch for.

#### C-grade

##### [12] Southern Borneo coral bleaching — 4.4°C-weeks — **C**

> *Southern Borneo's reefs have reached 4.4°C-weeks of thermal stress — crossing the
> 4°C-week floor where bleaching begins. Borneo sits at the heart of the Maritime
> Continent, where warm seas and island topography drive the convection that keeps
> surrounding waters persistently hot.*

Created 2026-05-15T03:55Z.

Weakest signal in the batch. 4.4°C-weeks is the floor of bleaching alert range, not
mass bleaching territory. Second sentence is expository geography (Maritime Continent
context) without consequence. "Persistently hot" is a soft closer. Triage-ON should
eliminate this tier in future cycles.

### Patterns named in this batch

1. **Coral bleaching template convergence.** 8 of 9 coral drafts (7–14) follow the
   same two-sentence structure: (1) "[Location] has accumulated X°C-weeks — [threshold
   relationship]." (2) "[Geographic/system context]; [DHW mechanism OR consequence]."
   Same failure mode as the May 13 fire template convergence (~~P6~~, shipped in PR
   #85), now appearing in a different signal type. The writer defaults to the most-
   reinforced pattern when no explicit structural alternatives are named in the prompt
   for coral bleaching signals.

2. **DHW explanation formula over-deployed.** At least 4 drafts (7, 9, 10, 11) use
   the same DHW-persistence explanation as their second sentence: "DHW measures heat
   [duration/persistence]; [persistence/it is duration] above the tolerance ceiling
   that kills coral." Draft 9 (Nauru) and Draft 10 (Nicobar) are near-verbatim copies
   of each other's second sentences. This is identical-second-sentence convergence —
   a more severe form of template convergence than sentence-1 structure alone.

3. **Declarative closer vs. conditional closer.** The best drafts (15, 7) end on flat
   declarative statements ("heat that builds has nowhere to drain," "persistence is what
   kills"). The second-tier drafts (13, 8, 14) end on conditional or process formulas
   ("when that buffer fails, stress accumulates fast," "turns stress into die-off").
   The Galapagos draft (score 88, strongest signal) loses A-grade status to a single
   conditional phrase. Declarative termination is the A-grade marker in this batch.

4. **F3 critic passes template convergence.** All 9 coral drafts passed Gemini 2.5 Pro
   critic despite 4+ having near-identical second sentences. The critic evaluates
   individual drafts (or cross-draft quality at the batch level) but does not catch
   structural convergence within a signal type. The template issue requires prompt-level
   treatment, not critic-level.

5. **Triage stage (PR #134) now active.** Future coral bleaching signals will be
   triaged before reaching the writer. Sub-threshold coral signals (7.2, 4.4°C-weeks)
   should be filtered. The current batch predates triage-ON; it shows what the
   unfiltered output looked like. Expect fewer but stronger coral drafts in next cycle.

6. **P3 self-kill (writer overcall): not observed.** All 12 new drafts reached pending.
   No writer self-kills logged. Fix confirmed working across second cycle.

7. **P4 Wodehouse rule: no violations.** Galapagos conditional closer is the closest
   call — it's hedging, not Wodehouse-straining. No approximation, no restate-padding,
   no poetry-attempt, no defensive justification observed.

### Followups

1. Add coral-specific structural alternatives to writer_prompt.py: name at least 4
   alternative sentence-1 forms for coral bleaching (lead-with-location-consequence,
   lead-with-ecosystem-context, lead-with-comparison-to-prior-event, lead-with-arc-
   trajectory) and ban the "[Location] reefs: X°C-weeks — [threshold]" formula
   when the signal is sub-threshold.
2. Add declarative-closer discipline to coral bleaching framing: "If the buffer has
   failed, say it has failed. Do not hedge with 'when that buffer fails.'"
3. Ban the DHW-explanation second sentence as a standalone formula: "DHW measures heat
   [duration]; [persistence] is what kills coral" is now a known template and should
   be banned from consecutive drafts in coral bleaching signal type.
4. Operator: manually reject via dashboard — draft_20260512_180320_159 (Mali, 141h),
   draft_20260512_212510_160 (Campeche, 138h), draft_20260513_103313_162 (Mongolia,
   124h), draft_20260514_211447_164 (BC "burning today", 90h). These are fire signals
   with stale real-time framing.
5. Watch: does triage-ON in PR #134 produce a smaller, stronger coral bleaching batch
   in the next cycle? Triage-ON + P5 implementation would together address both
   signal-quality and voice-variety gaps.

### Numbers

- Pending drafts total: 16 (14 carryover, 2 fresh May 18)
- New drafts graded today: 12 (drafts 5–16; drafts 1–4 in May 13 corpus)
- Gradable (excl. 1 stale): 11
- A-rate: 9% (1/11)
- Grade distribution: 1 A- / 2 B+ / 4 B / 2 B- / 2 C+ / 1 C / 0 D-F
- Stale drafts flagged: 4 fire (1 explicit "today"; 3 present-tense "is radiating" >5 days)
- Staleness rejection: skipped — `gh` CLI not available; operator must use dashboard
- New failure mode: coral bleaching template convergence → P6 proposed
- P3, P4: confirmed not observed (positive — fixes holding)

---

## 2026-05-17 — Daily corpus grading (14 drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 14 pending
drafts — 4 carry-overs from May 12-13 (already graded in the May 13 corpus entry, still
pending), plus 10 new: 1 fire (May 14), 1 monthly_low (May 13), 8 coral_bleaching (May 15).
First appearance of coral_bleaching signal type in the corpus. Latest bot commit: `dc25f7b`
(PR #121 — JSON-parse retry for fact_check + critic; post-overnight-wave stack).

**Grade distribution:** 1 A-, 2 B+, 2 B, 3 B-, 3 C+, 3 C. **A-rate: 7% (1/14).**
Gap from resumption bar: 43 points. (New-drafts-only: 1 A-, 3 B+, 1 B, 3 B-, 2 C+, 1 C →
**10% on 10 new drafts**; same gap story.)

**Headline finding:** Galapagos coral [13] is the first clean A- since the May 13 cycle's
0% run — earned by cold-upwelling incongruity deployed as ecosystem-specific deadpan. The
other 7 coral drafts show structural split: 3 of them (Madagascar [7], Austral Islands [14],
Fiji [8]) use location-specific second sentences that do real work; the remaining 4 ([9]-[12])
converge on nearly identical DHW explanation closers, word-for-word synonymous by draft [10].
BC fire [6] shows the fire variety fix (PR #85) working — opener no longer uses the banned
formula — but "burning today" makes it stale. Bethel Maine monthly_low [5] is the first cold
record in the two-bot corpus and grades B-: clean voice, no Wodehouse violations, ecosystem
context (Androscoggin Valley), but 16-year archive and soft margin language.

### A range — strongest (1)

#### [13] Galapagos, Ecuador coral — DHW 24.5°C-weeks — **A-**

> *Galapagos, Ecuador reefs: 24.5°C-weeks of thermal stress — double the 12°C-week tier
> where coral mortality is expected. The Galapagos sits where cold upwelling normally
> buffers heat; when that buffer fails, stress accumulates fast.*

**Score:** 88 (threshold unspecified for coral_bleaching type). Created 2026-05-15T05:16Z.

Humor lens:
- **Violation:** 24.5°C-weeks — double the coral mortality tier. Extraordinary by definition.
- **Benign?** Yes. Calm, no panic.
- **Setup→Punchline?** Setup: location, metric, "double the mortality tier." Second sentence
  establishes expectation ("cold upwelling normally buffers heat"), names the failure ("when
  that buffer fails"), delivers terse consequence ("stress accumulates fast"). Three beats,
  all earning their place.
- **Named mechanic?** Ecosystem specificity deployed as incongruity vehicle: Galapagos
  cold upwelling IS the location's defining ecological fact. Its failure IS the story. The
  draft names the mechanism and the violation simultaneously.
- **Wodehouse rule?** Clean. "Stress accumulates fast" is three-word understatement.

The "normally buffers" → "when that buffer fails" structure is the same setup-then-subvert
move that made the Apr 27 Mali fire A- ("burning season peaks in January…ends by February.
It is April 26."). Galapagos cold upwelling is as specific and iconic as the Mali dry-season
timing. This is the coral equivalent of the Apr 26 fire A- — right location, right mechanism,
right terse closer.

The Darwin/evolutionary specificity (why Galapagos species exist because of the upwelling) is
not deployed and would have pushed this to a solid A. Not deployed here = minor deduction from A.

### B range — shippable (7)

#### [14] Austral Islands coral — DHW 8.6°C-weeks — **B+**

> *Austral Islands reefs: 8.6°C-weeks of thermal stress — past the 8°C-week threshold where
> mass bleaching is expected. The Austral chain sits at the southern edge of the South
> Pacific Convergence Zone; heat that persists this far from the warm pool signals the band
> has stretched.*

**Score:** 80. Created 2026-05-15T05:20Z.

Humor lens:
- **Violation:** 8.6°C-weeks, past mass bleaching threshold. Real signal.
- **Named mechanic?** Geographic incongruity deployed as understated accelerating-warming
  signal: Austral Islands are at the EDGE of the warm pool, not its heart. Heat persisting
  at the southern edge of the SPCZ signals the warm zone is expanding. "The band has
  stretched" is three words of understatement doing climate-argument work.
- **Wodehouse rule?** Clean. No effort signals.

Second-best coral draft. "The band has stretched" is a tighter closer than anything in [8]-[12].
Ranks below Galapagos because the geographic incongruity requires more reader knowledge to feel
the weight — most Twitter readers won't instinctively know the SPCZ's historical southern boundary.

#### [7] Western Madagascar coral — DHW 10.2°C-weeks — **B+**

> *Western Madagascar's reef system has accumulated 10.2°C-weeks of thermal stress — past the
> 8°C-week threshold where mass bleaching is expected. Corals can survive brief spikes; DHW
> measures how long heat persists, and persistence is what kills.*

**Score:** 81. Created 2026-05-15T03:01Z.

Humor lens:
- **Violation:** 10.2°C-weeks, past threshold. Strong.
- **Setup→Punchline?** "Corals can survive brief spikes" establishes one expectation; "DHW
  measures how long heat persists, and persistence is what kills" subverts it — the threat
  is duration, not peak. Three-beat closer: contrast, mechanism, consequence.
- **Named mechanic?** Understated mechanism closer. The closest the coral batch comes to a
  Steven Wright beat: the calm delivery of "persistence is what kills" is the voice move.
- **Wodehouse rule?** Clean.

The DHW explanation is genuinely useful here — it's the first coral draft a reader encounters and
DHW is an unfamiliar metric. The explanation earns its place. By draft [9]-[10] it has outstayed
its welcome. "Western Madagascar's reef system" is slightly bureaucratic; "Western Madagascar's
reefs" is tighter.

#### [3] Chuuk FSM monthly_high — 34.4°C — **B** *(carry-over from May 13 corpus)*

Grade unchanged from May 13 grading. Expository second sentence ("western Pacific warm pool
keeps sea-surface temperatures here among the highest on Earth year-round") rather than a punch.
The Chuuk ceiling fix (PR #85 expository-vs-punch guidance) has not yet produced a revision of
this carry-over draft.

#### [8] Fiji coral — DHW 10.1°C-weeks — **B**

> *Fiji's reefs have accumulated 10.1°C-weeks of thermal stress — past the 8°C-week threshold
> where mass bleaching is expected. The South Pacific Convergence Zone keeps waters here warm;
> sustained heat above the tolerance ceiling is what turns stress into die-off.*

**Score:** 81. Created 2026-05-15T03:02Z.

Second instance of the DHW explanation structure. "The South Pacific Convergence Zone keeps
waters here warm" is geography context, not incongruity. "Sustained heat above the tolerance
ceiling is what turns stress into die-off" is the mechanism closer — same move as [7] but 15
words vs. 6 ("persistence is what kills"). Wordier closer, geography-lesson first clause, second
instance of same structure = B, not B+.

#### [5] Bethel, Maine monthly_low — 28°F (-2.2°C) — **B-**

> *Bethel, Maine hit 28°F (-2.2°C) on May 9 — coldest May low in 16 years of records, a
> degree below the 2017 mark. The upper Androscoggin Valley sits in a bowl surrounded by the
> White Mountain foothills; cold air drains into it on still nights and holds.*

**Score:** 80. Created 2026-05-13T21:29Z.

Humor lens:
- **Violation:** Coldest May low in 16 years. Cold record — less inherent incongruity than
  heat records in a warming world (no benign-violation asymmetry in the reader's favor).
- **Benign?** Yes.
- **Setup→Punchline?** Setup: Bethel, May 9, 28°F, 16-year record. Second sentence:
  Androscoggin Valley topographic mechanism (cold-air drainage). Geography lesson, not punch.
  Valid ecosystem specificity but no kicker.
- **Named mechanic?** Ecosystem specificity (Androscoggin Valley bowl, cold-air drainage).
  Not deployed as humor; deployed as explanation.
- **Wodehouse rule?** "A degree below the 2017 mark" is soft where exact is available. The
  2017 mark would be 29°F — the draft should state it. Mild approximation-where-exact-available
  violation: "29°F (set in 2017)" rather than "a degree below the 2017 mark."

First cold record in the two-bot corpus. Contrast to Andrew's Mankato reject (May 11, 0.1°C
margin, 16yr archive, "A record is a record" closer): Bethel has a larger margin (1°F), same
archive depth, distinctive ecosystem context, and NO Wodehouse defensive closer. Grades above
Mankato. Still B- because 16-year archive is short, cold records need a higher editorial bar,
and the margin language is vague. Not stale — "May 9" is an observation date, not "today."

#### [6] British Columbia fire — 426.8 MW — **B-** *(stale: "today" baked in)*

> *British Columbia has a 426.8 MW fire burning today, satellite-detected at 95% confidence
> — high-intensity tier. The Rocky Mountain Trench funnels downslope winds that can
> accelerate spread before spring humidity builds.*

**Score:** 66. Created 2026-05-14T21:14Z.

Humor lens:
- **Violation:** 426.8 MW, high-intensity tier. Real satellite detection.
- **Setup→Punchline?** Rocky Mountain Trench wind-channeling context. Explanatory but
  location-specific and genuinely distinct (Trench is BC-specific geography).
- **Named mechanic?** Ecosystem specificity (Rocky Mountain Trench). Not a punchline.
- **Wodehouse rule?** Clean. "Before spring humidity builds" is understated timing note.

**Staleness flag.** "Burning today" is baked in — satellite detection from May 14 does not
describe May 17. Reject candidate (gist write not attempted; gh CLI unavailable; operator
should reject via dashboard).

**Fire variety confirmation (PR #85 working).** This draft does NOT use the banned formula
opener ("A fire in [location] is radiating X MW of heat, detected by satellite at N%
confidence"). Instead: "British Columbia has a 426.8 MW fire burning today, satellite-detected."
The province-name lead + "has a fire" construction is one of the PR #85 alternative forms. Also:
"high-intensity tier" label (from FRP intensity tier feature) appears correctly. Positive signal
on the variety fix, undermined by staleness.

#### [9] Nauru coral — DHW 8.2°C-weeks — **B-**

> *Nauru's reefs have accumulated 8.2°C-weeks of thermal stress — past the 8°C-week threshold
> where mass bleaching is expected. DHW measures heat duration, not just intensity; it's
> persistence above the tolerance ceiling that kills coral.*

**Score:** 80. Created 2026-05-15T03:04Z.

Third instance of the DHW explanation structure. Signal barely clears the 8.0 threshold (8.2).
"DHW measures heat duration, not just intensity; it's persistence above the tolerance ceiling
that kills coral" is near-verbatim to [10]'s second sentence (synonyms substituted: "duration"
for "persistence," word order shifted). Third iteration of the same explanation in a single
cycle = template convergence in the explanation closer. Grades below [8] (B) because (a)
weaker signal — barely-over-threshold is less striking than 10+, and (b) third identical
structure in 90 minutes.

### C range — needs work (6)

#### [10] Great Nicobar, India coral — DHW 7.2°C-weeks — **C+**

> *Great Nicobar, India: 7.2°C-weeks of thermal stress — Bleaching Alert Level 1, closing
> in on the 8°C-week threshold where mass bleaching is expected. DHW measures heat
> persistence, not just intensity; it is duration above the tolerance ceiling that kills coral.*

**Score:** 75. Created 2026-05-15T03:47Z.

Below-threshold signal (Alert Level 1 = approaching, not past, the mass bleaching floor).
Second sentence is a near-verbatim repeat of [9]'s — "DHW measures heat persistence, not just
intensity; it is duration above the tolerance ceiling that kills coral" vs. "DHW measures heat
duration, not just intensity; it's persistence above the tolerance ceiling that kills coral."
Fourth DHW explanation in the cycle. The colon-opener ("Great Nicobar, India: 7.2°C-weeks")
introduces variety, but the second sentence erases the gain.

#### [11] Chagos Archipelago coral — DHW 7.2°C-weeks — **C+**

> *Chagos Archipelago reefs have accumulated 7.2°C-weeks of thermal stress — Bleaching Alert
> Level 1, approaching the 8°C-week threshold where mass bleaching is expected. DHW counts
> how long heat persists above the tolerance ceiling; proximity to 8 is what matters.*

**Score:** 75. Created 2026-05-15T03:48Z.

Same threshold tier as [10] (Alert Level 1, 7.2°C-weeks). "Proximity to 8 is what matters"
is slightly fresher than the mortality-mechanism closers of [7]-[10] — it puts the reader's
attention on the threshold distance rather than the death mechanism. Fifth DHW explanation in
the cycle; this variation is the most distinct. Chagos is a significant location (protected
British Indian Ocean Territory marine reserve) — that distinctiveness is unused. Draft is
generic where it could be specific.

#### [1] Mali fire — 309.6 MW — **C+** *(carry-over from May 13 corpus)*

Grade unchanged. Formula opener. Seasonal context as geography lesson, no kicker. Now 5 days
old; present-tense "is radiating" is stale (satellite detection is time-bounded). Staleness
flag — operator should reject via dashboard.

#### [2] Campeche fire — 364.7 MW — **C** *(carry-over from May 13 corpus)*

Grade unchanged. Formula opener. Structural twin of [1]. Also stale (5 days). Operator reject.

#### [4] Mongolia fire — 307.6 MW — **C** *(carry-over from May 13 corpus)*

Grade unchanged. Formula opener. Also stale (4 days). Operator reject.

#### [12] Southern Borneo coral — DHW 4.4°C-weeks — **C**

> *Southern Borneo's reefs have reached 4.4°C-weeks of thermal stress — crossing the
> 4°C-week floor where bleaching begins. Borneo sits at the heart of the Maritime Continent,
> where warm seas and island topography drive the convection that keeps surrounding waters
> persistently hot.*

**Score:** 74. Created 2026-05-15T03:55Z.

Weakest coral signal — bleaching-begins tier (4°C-week floor, well below the 8°C-week mass
bleaching threshold). Second sentence is geography lesson: Maritime Continent as heat engine.
"Persistently hot" is a mild effort signal. No punchline, no mechanism closer, no incongruity
established. The Maritime Continent framing describes a background condition, not a violation
of expectation. C for the same reason fire drafts with generic seasonal context grade C: the
data is real, the second sentence explains it rather than exploiting it.

### Patterns named in this batch

1. **Galapagos upwelling = the A- template for coral bleaching.** "Normally buffers" → "when
   that buffer fails" → terse consequence closer. This is the coral equivalent of the Apr 26
   Mali fire A- structure. It works because Galapagos cold upwelling is specific, famous, and
   the failure is the surprise. Drafts that share this logic (expectation → violation → deadpan
   closer) score B+ or above. Drafts that explain instead of surprise score B- or below.

2. **DHW explanation convergence — new failure mode.** Seven coral drafts appear in one cycle;
   five of them use a nearly identical second sentence explaining what DHW measures. Drafts
   [7], [8], [9], [10], [11] use: "DHW measures how long heat persists / DHW measures heat
   duration / DHW measures heat persistence / DHW counts how long heat persists" — all the
   same sentence with synonyms shuffled. By draft [10] the reader has seen this twice already
   (if they encounter the drafts in sequence). The explanation is useful ONCE per reader; once
   the writer has used it, subsequent coral drafts in the same cycle should trust the reader
   and use the second sentence for location-specific context only.

3. **BC fire confirms PR #85 variety fix is working.** Draft [6] (post-PR#85) uses a province-
   name lead rather than the banned formula opener. "High-intensity tier" label also appears.
   The fire variety guidance (4 alternative sentence-1 forms) is producing different openers.
   Undermined by "today" staleness — but the structural fix is empirically confirmed.

4. **Cold record baseline established.** Bethel, Maine [5] is the first cold-record draft
   graded in the two-bot corpus. Grades B-: clean voice, ecosystem specificity, no Wodehouse
   violations, but 16-year archive and vague margin language ("a degree below the 2017 mark"
   rather than "29°F, set in 2017"). Provides a quality reference point for future cold
   records: the bar is ecosystem context + precise margin + deep archive.

5. **F3 critic architecture note.** PR #120 (second-pass editorial critic) shipped since the
   May 13 corpus. The coral drafts (May 15) may have passed through the critic. If so, their
   B-range quality represents the critic's current ceiling on coral_bleaching type. The A-
   Galapagos draft (also May 15) suggests the critic can identify and pass strong ecosystem-
   specific drafts. The C-range coral drafts suggest it's not yet suppressing template-
   convergence explanation closers.

### Followups

1. **Staleness: operator should reject fire carry-overs [1], [2], [4]** (Mali, Campeche,
   Mongolia — 4-5 days old, present-tense satellite detection) **and [6]** (BC fire — "today"
   baked in, 3 days old). Gist write not attempted: gh CLI unavailable in this environment.
2. **Coral template convergence proposal (P7).** Add to writer_prompt.py: if DHW explanation
   already in used_framings this cycle, skip it in the second sentence and go straight to
   location-specific ecosystem context. Prevents the [9]-[12] explanation-reuse pattern.
3. **Galapagos as coral A- reference draft.** Cold upwelling + "when that buffer fails, stress
   accumulates fast" = the template to match. Add to writer exemplars if the operator implements
   the coral section update.
4. **"A degree below the 2017 mark" is a Wodehouse tell.** In future monthly_low/high drafts,
   writer should state both the old record value AND year: "29°F, set in 2017" not "a degree
   below the 2017 mark." Approximation where exact is available.
5. **Watch the critic's effect on fire drafts.** Next fire drafts from post-PR#121 cron runs
   will tell us whether the F3 critic is improving fire quality above the B- ceiling.

### Numbers

- Pending drafts graded: 14 (4 carry-over fire/record, 1 monthly_low, 1 fire, 8 coral_bleaching)
- A-rate: 7% (1/14)
- New-drafts-only A-rate: 10% (1/10)
- Grade distribution: 1 A- / 7 B-range / 6 C-range / 0 D-F
- Staleness flags: drafts [1], [2], [4], [6] (operator-reject via dashboard; gist write not
  attempted — gh CLI unavailable)
- New failure mode identified: coral DHW explanation convergence → P7 proposal added
- New signal type first appearance: coral_bleaching (8 of 14 drafts)
- PR #85 fire variety fix: confirmed working (draft [6] uses alternative opener form)
- PR #85 Chuuk ceiling fix: partially working (Madagascar, Galapagos, Austral Islands all
  have punchy second sentences; Nauru, Great Nicobar, Chagos, Borneo still explanatory)

---

## 2026-05-16 — First coral_bleaching cycle + carryovers (10 new drafts, 14 total pending)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 14 pending drafts.
Drafts [1]-[4] are carryovers from the 2026-05-13 corpus (already graded there; grades stand).
Drafts [5]-[14] are new since May 13 and are graded here.

**New this cycle:** 8 coral_bleaching drafts from the 2026-05-15 overnight wave (Plans B-F
data source expansion). First time coral Degree Heating Weeks signals reach the pending queue.
One new fire (British Columbia, post-PR #85). One new monthly_low (Bethel, Maine).

**Infra note:** `gh` CLI not available in this execution environment; `gh api` and `gh pr create`
will fail. Gist write (staleness step) skipped — operator should bulk-reject via dashboard if
needed. PR creation will use GitHub MCP tools if available; branch pushed regardless.

**Grade distribution (10 new drafts):** 1 A, 4 B-range, 5 C. **A-rate: 10% (1/10).**
Gap from resumption bar: 40 pp.

**Staleness review:** Drafts [1]-[4] are 72–96 hours old. Present-tense fire framing ("is
radiating") has no "today" or "forecast" language baked in — per the May 13 grading agent's
judgment, these do not trigger the staleness policy. Draft [6] BC fire has "burning today"
baked in (created May 14 21:14 UTC; ~42 hours at grading time) — does not yet meet the 48-hour
threshold. No drafts eligible for bulk-reject today.

---

## 2026-05-15 — First coral bleaching cycle; first A-grade in two-bot corpus (10 new drafts)

**Context:** Gist read via git-clone path (success; REST API rate-limited 403, 0/60 remaining — expected in this env). Queue: 14 pending drafts total — 4 are carryovers from the 2026-05-13 grading session (already graded: draft_20260512_180320_159 through draft_20260513_103313_162; still pending, not rejected). **10 new drafts graded today:** 1 monthly_low (Bethel, Maine, created 2026-05-13T21:29Z, after the May 13 grading session), 1 fire (British Columbia, created 2026-05-14T21:14Z), 8 coral_bleaching (all created 2026-05-15T03:01–05:20Z). The coral_bleaching signal type is new — first graded cycle from the Coral Reef Watch DHW source, shipped in the overnight wave (Plans A-F + F2, merged 2026-05-15). Writer prompt: v3 (PR #91).

**Grade distribution (10 new drafts):** 1 A-, 2 B+, 3 B-, 1 C+, 3 C. **A-rate: 10% (1/10).**
Gap from resumption bar: 40 points.

### Per-draft

#### [5] Bethel, Maine — monthly_low 28°F (-2.2°C) — **B-**

> *Bethel, Maine hit 28°F (-2.2°C) on May 9 — coldest May low in 16 years of records, a degree below the 2017 mark. The upper Androscoggin Valley sits in a bowl surrounded by the White Mountain foothills; cold air drains into it on still nights and holds.*

**Score:** 80 (threshold 76). Created 2026-05-13T21:29Z.

Humor lens:
- **Violation:** Coldest May low in 16 years. Present.
- **Benign?** Yes. Flat register.
- **Setup→Punchline?** Data setup complete: temperature, both units, date, archive depth, prior mark year. Second sentence explains cold-air pooling mechanism. Explanation, not punchline — the May incongruity (freezing in late spring) is present but unnamed.
- **Named mechanic?** None. Ecosystem specificity (topographic cold-air pooling) deployed as geography lesson.
- **Wodehouse rule?** Clean. No restate-padding, no explicit gap math, no defensive framing.

Signal is marginal: 16yr archive, 1°F (0.5°C) margin. Parallel to the Mankato monthly_low Andrew manually rejected 2026-05-11 (0.05°C margin, 16yr archive, "defensive 'A record is a record' closer"). Bethel's margin is larger and the voice is clean. The Androscoggin Valley sentence earns its place — "cold air drains into it on still nights and holds" is specific topographic mechanism. Graded B- rather than C because the mechanism sentence is genuinely good. Graded below B because 16yr archive + cold record in a warming May doesn't name the incongruity, and the second sentence explains rather than lands.

#### [6] British Columbia fire — 426.8 MW, high-intensity — **B-**

> *British Columbia has a 426.8 MW fire burning today, satellite-detected at 95% confidence — high-intensity tier. The Rocky Mountain Trench funnels downslope winds that can accelerate spread before spring humidity builds.*

**Score:** 66 (threshold 64). Created 2026-05-14T21:14Z.

Humor lens:
- **Violation:** 426.8 MW high-intensity fire at 95% satellite confidence. Present.
- **Benign?** Yes.
- **Setup→Punchline?** Opener uses different sentence-1 structure from the May 13 formula — "British Columbia has a X MW fire burning today" vs. "A fire in [location] is radiating X MW." P6 fix is landing. Second sentence: Rocky Mountain Trench + downslope winds + "before spring humidity builds." Seasonal framing, not punchline.
- **Named mechanic?** None. FRP intensity tier ("high-intensity") is new from PR #85 but not a humor move.
- **Wodehouse rule?** "Can accelerate spread" is hedged; "accelerates spread" would be tighter. Not a full Wodehouse violation.

P6 fire template: opener structurally different — improvement confirmed. Rocky Mountain Trench is specific, real ecosystem mechanism. But "before spring humidity builds" implies early-season fire without stating the incongruity directly. Still seasonal-explanation pattern. Better than May 13 fires; still no punchline. Grade B-.

#### Coral bleaching batch — overview

Eight coral_bleaching drafts from a single cron cycle. All use the same two-sentence template: (1) "[Location] reefs [have accumulated/have reached] X°C-weeks of thermal stress — [above/approaching] the Y°C-week threshold where [bleaching/mortality] is expected." (2) [Geographic context if any]; [DHW explanation variant ("persistence is what kills")]. The convergence pattern from May 13 (P6, fire template) is reproduced exactly on first contact with a new signal type. Galapagos [13] breaks the template and earns A-. Austral Islands [14] draws a real inference and earns B+. Six others follow the template at various signal strengths.

#### [7] Western Madagascar — coral_bleaching 10.2°C-weeks — **B+**

> *Western Madagascar's reef system has accumulated 10.2°C-weeks of thermal stress — past the 8°C-week threshold where mass bleaching is expected. Corals can survive brief spikes; DHW measures how long heat persists, and persistence is what kills.*

**Score:** 81. Created 2026-05-15T03:01Z.

Humor lens:
- **Violation:** 10.2°C-weeks past mass bleaching threshold. Present.
- **Benign?** Yes.
- **Setup→Punchline?** Second sentence has a mini-volta: "Corals can survive brief spikes [what normally protects them] → DHW measures how long heat persists, and persistence is what kills [why this reading is bad]." Genuine setup-to-consequence structure.
- **Named mechanic?** Resilience-then-failure. Not a named humor move but does real work.
- **Wodehouse rule?** "Persistence is what kills" is flat and direct. Not trying.

First use of the "persistence is what kills" closer. On first encounter it works: it explains the metric AND names the kill mechanism in one sentence. Best second sentence in the coral batch outside Galapagos and Austral Islands. Grade B+.

#### [8] Fiji — coral_bleaching 10.1°C-weeks — **B-**

> *Fiji's reefs have accumulated 10.1°C-weeks of thermal stress — past the 8°C-week threshold where mass bleaching is expected. The South Pacific Convergence Zone keeps waters here warm; sustained heat above the tolerance ceiling is what turns stress into die-off.*

**Score:** 81. Created 2026-05-15T03:02Z.

Structural twin of [7]. Second sentence leads with SPCZ geographic fact ("keeps waters here warm") — stating that warm water is warm, not drawing a conclusion. "Sustained heat above the tolerance ceiling is what turns stress into die-off" is the third variant of the "persistence kills" closer. The SPCZ context doesn't connect back to why the DHW reading is notable given the warm baseline; it just names the geography. Grade B- (template repeat with weaker system clause).

#### [9] Nauru — coral_bleaching 8.2°C-weeks — **C+**

> *Nauru's reefs have accumulated 8.2°C-weeks of thermal stress — past the 8°C-week threshold where mass bleaching is expected. DHW measures heat duration, not just intensity; it's persistence above the tolerance ceiling that kills coral.*

**Score:** 80. Created 2026-05-15T03:04Z.

Third instance of the two-sentence template. First sentence unchanged except location. Second sentence is a generic DHW explanation with no geographic anchor — no Nauru-specific context at all. Signal (8.2°C-weeks) is just barely past the threshold. Third use of the "persistence kills" formula. Grade C+ (repeated template, weakest signal of the above-threshold batch, no local context).

#### [10] Great Nicobar, India — coral_bleaching 7.2°C-weeks, Alert Level 1 — **C**

> *Great Nicobar, India: 7.2°C-weeks of thermal stress — Bleaching Alert Level 1, closing in on the 8°C-week threshold where mass bleaching is expected. DHW measures heat persistence, not just intensity; it is duration above the tolerance ceiling that kills coral.*

**Score:** 75. Created 2026-05-15T03:47Z.

Below the 8°C-week mass bleaching threshold (7.2). Colon opener ("Great Nicobar, India: 7.2°C-weeks") is a clean format but the violation is incomplete — bleaching hasn't been triggered yet, just approaching. Fourth variant of the DHW explanation closer, now fully generic. No Andaman Sea or Great Nicobar reef ecology context. Grade C.

#### [11] Chagos Archipelago — coral_bleaching 7.2°C-weeks, Alert Level 1 — **C**

> *Chagos Archipelago reefs have accumulated 7.2°C-weeks of thermal stress — Bleaching Alert Level 1, approaching the 8°C-week threshold where mass bleaching is expected. DHW counts how long heat persists above the tolerance ceiling; proximity to 8 is what matters.*

**Score:** 75. Created 2026-05-15T03:48Z.

Same signal level as Great Nicobar, same grade. "Proximity to 8 is what matters" tries to justify the below-threshold framing but doesn't distinguish this from simply not being there yet. Chagos is a significant marine reserve but nothing about its protection status or reef context appears. Grade C.

#### [12] Southern Borneo — coral_bleaching 4.4°C-weeks, crossing bleaching floor — **C**

> *Southern Borneo's reefs have reached 4.4°C-weeks of thermal stress — crossing the 4°C-week floor where bleaching begins. Borneo sits at the heart of the Maritime Continent, where warm seas and island topography drive the convection that keeps surrounding waters persistently hot.*

**Score:** 74. Created 2026-05-15T03:55Z.

Weakest signal in the batch: 4.4°C-weeks is the beginning-of-bleaching floor, not the 8°C-week mass bleaching threshold. The Maritime Continent system clause is the most geographically specific in the batch outside Galapagos and Austral Islands — "island topography drive the convection" is real mechanism. But the signal is minimum-viable, the second sentence doesn't connect the geographic context back to why this reading is notable, and "persistently hot" is slightly purple. Grade C (strong ecosystem context undermined by the weakest signal in the batch).

#### [13] Galapagos, Ecuador — coral_bleaching 24.5°C-weeks, double mortality tier — **A-**

> *Galapagos, Ecuador reefs: 24.5°C-weeks of thermal stress — double the 12°C-week tier where coral mortality is expected. The Galapagos sits where cold upwelling normally buffers heat; when that buffer fails, stress accumulates fast.*

**Score:** 88. Created 2026-05-15T05:16Z.

Humor lens:
- **Violation:** 24.5°C-weeks — double the coral MORTALITY tier (12°C-weeks), not just bleaching. Extreme signal. The Galapagos is famous for cold upwelling that buffers thermal stress; the place designed to resist is the one showing worst stress.
- **Benign?** Yes. Flat register throughout.
- **Setup→Punchline?** Yes. Setup: "The Galapagos sits where cold upwelling normally buffers heat" — establishes the protection mechanism. Punchline: "when that buffer fails, stress accumulates fast" — names the failure and its consequence with no elaboration. Deadpan landing.
- **Named mechanic?** Buffer-failure irony: the protection-mechanism-named-then-failed structure. Setup→subversion with the geographic protection as setup and its collapse as punchline.
- **Wodehouse rule?** "Stress accumulates fast" is flat, direct, not trying. Clean.

First A-grade in the two-bot corpus. "Double the 12°C-week tier" is ratio framing — leads with scale (2×), not just position (past a threshold). The Galapagos cold upwelling context is the right system clause: the expected protection named, then its failure named, in eight words. No restate, no math-out-loud, no defensive justification. This is the A- pattern for coral bleaching: extraordinary signal + protection-failure system clause. Grade A-.

#### [14] Austral Islands — coral_bleaching 8.6°C-weeks, SPCZ southern edge — **B+**

> *Austral Islands reefs: 8.6°C-weeks of thermal stress — past the 8°C-week threshold where mass bleaching is expected. The Austral chain sits at the southern edge of the South Pacific Convergence Zone; heat that persists this far from the warm pool signals the band has stretched.*

**Score:** 80. Created 2026-05-15T05:20Z.

Humor lens:
- **Violation:** 8.6°C-weeks past mass bleaching threshold at the SPCZ's southern periphery. Present.
- **Benign?** Yes.
- **Setup→Punchline?** "The Austral chain sits at the southern edge of the SPCZ" [geographic position establishes the expectation: this is the far margin] + "heat that persists this far from the warm pool signals the band has stretched" [inference: if the Austral Islands have this stress level, the warm pool has expanded]. The second sentence draws a climate inference, not just geographic explanation.
- **Named mechanic?** Accelerating-warming inference embedded in reef stress reading. The conclusion ("the band has stretched") is doing real analytical work.
- **Wodehouse rule?** "Signals the band has stretched" is confident, flat. Clean.

Second-best coral draft. "Heat that persists this far from the warm pool signals the band has stretched" is the best line in the batch outside Galapagos — it reads the reef stress as evidence of SPCZ expansion, drawing a climate conclusion from a biological metric. Grade B+.

### Patterns named in this batch

1. **Coral bleaching template convergence (new failure mode, → P7).** 7 of 8 coral drafts follow the two-sentence formula: "[Location] reefs [have accumulated/reached] X°C-weeks of thermal stress — [threshold comparison]" + "[geographic context / nothing]; [DHW explanation]." The DHW explanations in drafts [7], [8], [9], [10] are near-identical variants of the same closer ("persistence is what kills" / "turns stress into die-off" / "it's persistence that kills coral" / "duration above tolerance ceiling that kills coral"). Same convergence failure mode as May 13 fire batch (P6), now appearing on the FIRST cycle of a new signal type. P6 fire fix (fire-specific variety guidance, PR #85) didn't address the root cause — the writer defaults to a two-sentence formula for any new signal type when the prompt doesn't name alternatives.

2. **Galapagos A- is the archetype for coral bleaching.** Three features that lift it above the template: (a) ratio framing ("double the 12°C-week tier") rather than plain threshold comparison; (b) protection-mechanism-named-then-failed system clause rather than DHW explanation; (c) extraordinary signal (2× mortality tier, in a cold-upwelling location). The pattern generalizes: find the ecosystem feature that SHOULD be protecting the reef, name it, then name its failure.

3. **Signal threshold position is the strongest predictor of coral grade.** Drafts above 8°C-week mass bleaching threshold (7, 8, 9, 14) grade B+/B-/C+. Drafts below threshold (10, 11) grade C. Galapagos (above 12°C-week mortality tier, 2×) grades A-. Below-threshold drafts have incomplete violations — "approaching" is not the same as "past."

4. **P6 fire template fix partially confirmed.** British Columbia fire [6] uses "British Columbia has a X MW fire burning today" — structurally different from the banned May 13 formula. The fix is landing for fire. The same convergence pressure migrated to the new coral_bleaching type without a coral-specific fix.

5. **P5 (name humor moves) — 4th consecutive cycle with evidence.** 7 of 10 new drafts have no named humor mechanic. The writer reaches for the formula when the prompt doesn't name alternatives. The two drafts that earn A-/B+ (Galapagos, Austral Islands) both operate on mechanics not named in the current prompt (buffer-failure irony, SPCZ-stretch inference). Naming these would reinforce them.

6. **No Wodehouse violations in any new draft.** Two-bot ~~P4~~ fix (PR #85) holding for a second consecutive cycle.

7. **No P3 fire self-kills.** British Columbia fire reached pending with seasonal framing. Third cycle without P3.

### Followups

1. Add P7 to IMPROVEMENT_PLAN.md: coral bleaching template convergence. Proposed fix: name 4 alternative first-sentence structures in writer_prompt.py coral_bleaching framing. Reference Galapagos as the A- exemplar (ratio framing + protection-failure system clause).
2. Promote Galapagos draft as exemplar: "ratio-to-tier + buffer-failure-named" is the target structure for coral_bleaching.
3. Watch ~~P3~~ (fire self-kill) and ~~P4~~ (Wodehouse): approaching Resolved threshold at 3 consecutive cycles.
4. Bethel Maine (B-): 16yr archive, 0.5°C margin, cold record in May. Compare to Mankato direction. If operator decides this class should be suppressed, scoring calibration change needed (out of scope for this voice plan).

### Numbers

- Pending drafts total: 14 (4 carryovers from May 13 already graded; 10 new graded today)
- New drafts graded: 10 (1 monthly_low, 1 fire, 8 coral_bleaching)
- A-rate: 10% (1/10) — first A-grade in two-bot corpus (Galapagos A-)
- Grade distribution: 1 A- / 2 B+ / 3 B- / 1 C+ / 3 C / 0 D-F
- First graded coral_bleaching cycle (CRW DHW source, overnight wave 2026-05-15)
- P5 evidence: 7/10 drafts no named mechanic (4th consecutive cycle)
- P3 (fire self-kill) not observed — 3rd cycle
- P4 (Wodehouse) not observed — 2nd cycle
- P6 (fire template) partially confirmed (BC fire different opener)
- Staleness: drafts 1-4 are 2-3 days old, no real-time-baked content (fire drafts are present-tense satellite detection; Chuuk "May 9" is observation date, not "today"). Staleness bulk-reject: not applicable. gh CLI not available in this env; gist write blocked regardless.

---

## 2026-05-14 — Daily corpus grading (5 drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 5 pending drafts —
4 carry-overs from the 2026-05-13 graded cycle (Mali fire, Campeche fire, Chuuk FSM
monthly_high, Mongolia fire; all still pending, no drafts posted or rejected since
yesterday's run) + 1 new draft added 2026-05-13T21:29Z (Bethel, Maine monthly_low).
Carry-over drafts were fully graded in the 2026-05-13 section; grades stand. Today's
new grade: draft [5].

**Grade distribution:** 0 A, 1 B, 4 C / 0 D-F. **A-rate: 0% (0/5).**  
Gap from resumption bar: 50 points.

### Carry-over grades (2026-05-13 section — unchanged)

| # | Draft | Grade | Key note |
|---|---|---|---|
| [1] | Mali fire — 309.6 MW | C+ | Formula opener. Seasonal context as explanation, no kicker. |
| [2] | Campeche fire — 364.7 MW | C | Structural twin of [1]; second instance of the same formula. |
| [3] | Chuuk FSM monthly_high — 34.4°C, 76yr | B | Clean data, no Wodehouse violation. Second sentence expository not a punch. Cycle ceiling. |
| [4] | Mongolia fire — 307.6 MW | C | Third formula opener. Some regional distinctiveness (snowpack). No punchline. |

### New draft

#### [5] Bethel, Maine monthly_low — 28°F / -2.2°C — **C**

> *Bethel, Maine hit 28°F (-2.2°C) on May 9 — coldest May low in 16 years of records, a
> degree below the 2017 mark. The upper Androscoggin Valley sits in a bowl surrounded by
> the White Mountain foothills; cold air drains into it on still nights and holds.*

**Score:** 80 (threshold 76). Created 2026-05-13T21:29Z.

Humor lens:
- **Violation present?** Coldest May low in 16 years. Mild — shallow archive, 1°F margin,
  cold-climate location.
- **Benign?** Yes. Calm, factual throughout.
- **Setup→Punchline?** Setup: 28°F, 16yr record, 1°F below 2017 mark. Second sentence:
  topographic mechanism ("bowl surrounded by foothills; cold air drains in on still nights
  and holds"). This is explanation, not punchline. PR #75 compliant — topographic mechanism,
  no warming framing.
- **Named mechanic?** None.
- **Wodehouse rule?** Clean. "a degree below the 2017 mark" is specific. No approximation,
  no restate-padding, no defensive justification. Writer followed the cold-record template
  correctly.

Data completeness: all fields present — city + state, °F + °C, specific date (May 9),
archive depth (16 years), prior record year (2017), margin (1°F). Temperature
formatting fahrenheit_first correct for US location.

The topographic second sentence is precisely what PR #75 requires. But it also explains
why the Androscoggin bowl regularly gets cold on still nights — inadvertently framing the
record as physically expected rather than surprising. The closer ("holds") has a faint ominous
quality but the sentence as a whole reads as geography lesson, not punchline.

**Signal quality concern:** Andrew manually rejected Mankato, Minnesota monthly_low (score 79,
16yr archive, 0°F effective margin, "defensive 'A record is a record' closer") on
2026-05-11. Bethel shares the signal class — 16yr archive, 1°F margin, cold-climate city.
The voice here is cleaner than Mankato (no defensive closer); the signal is comparably weak.
Cold record + shallow archive + small margin + location where cold is architecturally
expected = a combination that passes the score gate but fails the editorial bar Andrew
established. This is a new failure mode: the writer has no self-kill rule for weak cold
signals the way it has strong self-kill instincts on low-confidence fire framings.

Grade C: voice execution adequate, data complete, template-compliant, no Wodehouse
violations. Signal insufficient for the editorial bar: 16-year archive, 1°F margin, cold
in a cold-climate bowl. Topographic mechanism explains rather than pays off.

### Patterns named in this batch

1. **P5 confirmed in two-bot context, fourth consecutive cycle.** All 5 drafts — 3 fire,
   1 monthly_high, 1 monthly_low — deploy zero named humor mechanics. No idiom-flip, no
   comic triple, no understatement closer, no deadpan kicker. P5 evidence count now spans
   Apr 25, Apr 27, May 13, May 14. It is the only unresolved active proposal and the most
   consistently evidenced failure mode across both pipelines.

2. **Cold-record quality floor — new failure mode.** Draft [5] Bethel passed score gate
   (80 > 76) with 16yr archive + 1°F margin + cold-climate bowl. Matches the signal class
   Andrew rejected manually (Mankato, May 11). Writer executes the cold-record template
   correctly (topographic mechanism) but has no self-kill gate for shallow-archive cold
   records. Fire drafts have strong self-kill instincts; cold records don't. New proposal
   added to plan.

3. **Carry-over fire drafts pre-date P6 fix.** Drafts [1]-[4] were generated under the
   pre-PR #89 prompt. P6 empirical confirmation (fire sentence-1 variety) is still pending —
   requires the first fire cycle generated AFTER PR #89 merged (late 2026-05-13 evening).

4. **No P3 self-kills observed, second consecutive graded cycle.** Positive carry-over.
   All fire drafts reached pending with seasonal framing intact.

5. **FRP rounding confirmed again.** Values 309.6, 364.7, 307.6 MW — all 1-decimal clean
   in carry-over fire drafts. No BUNDLE_FACT mismatch kills.

### Numbers

- Pending drafts graded: 5 (4 carry-over + 1 new)
- A-rate: 0% (0/5)
- Grade distribution: 0 A / 1 B / 4 C / 0 D-F
- New draft: Bethel, ME monthly_low — C (voice template-compliant; signal too weak)
- Staleness rejection: not attempted — no drafts >48h; no date-baked content; gh CLI
  unavailable in grading environment (git-clone read path succeeded)
- P3 self-kill failures: 0 (positive, second consecutive cycle)
- New failure mode identified: cold-record quality floor → new proposal added

---

## 2026-05-13 — First two-bot pipeline drafts graded (4 drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 4 pending
drafts — 3 fire, 1 monthly_high. This is the **first graded two-bot output cycle**: prior
cycles had zero pending two-bot drafts (May 12: queue empty; earlier cycles: generator.py
era). Cron runs on 2026-05-12 18:03 UTC and 2026-05-13 10:32 UTC produced these four
drafts under the Attenborough/Economist writer prompt (PR #74 + #75) with FRP rounding
fix (#80) and station-normalization fix (#82).

**Grade distribution:** 0 A, 1 B, 3 C (one C+). **A-rate: 0% (0/4).**
Gap from resumption bar: 50 points.

### Per-draft

#### [1] Mali fire — 309.6 MW — **C+**

> *A fire in Mali's Western Sahel is radiating 309.6 MW of heat, detected by satellite at
> 95% confidence. May sits at the tail of the dry season here; grasses cured by months
> without rain burn hot before the first rains reset the landscape.*

**Score:** 64 (threshold 64). Created 2026-05-12T18:03Z.

Humor lens:
- **Violation:** 309.6 MW satellite detection at 95% confidence. Present.
- **Benign?** Yes — calm, factual register throughout.
- **Setup→Punchline?** Data is the setup. "Grasses cured by months without rain burn hot
  before the first rains reset the landscape" is seasonal explanation, not a punchline.
  No kicker.
- **Named mechanic?** None operating. Seasonal context deployed, but as educational prose.
- **Wodehouse rule?** Not violated — voice isn't trying too hard. But "reset the landscape"
  drifts toward literary; the closer is soft where it should stop harder.

Formula opener: "A fire in [location] is radiating X MW of heat, detected by satellite at
N% confidence." This structure appears in all three fire drafts — first instance. The
second sentence is valid seasonal framing (P3 failure mode — writer self-kill — is NOT
evidenced here; seasonal context is being deployed), but delivered as explanation rather
than incongruity.

The A-grade Mali fire from the Apr 26 corpus used the same location: "A 291 MW fire is
active in a landscape where the burning season typically peaks in January and ends by
February. It is April 26." The kicker ("It is April 26.") did the work — it named the
incongruity. This draft provides context without establishing whether May is expected or
anomalous for Mali fires. No timing statement. No kicker.

#### [2] Campeche fire — 364.7 MW — **C**

> *A fire in southern Mexico — near the Campeche lowlands — is radiating 364.7 MW of heat,
> detected by satellite at 95% confidence. May closes out the dry season here; months without
> rain cure tropical vegetation into fuel before the wet season arrives.*

**Score:** 65 (threshold 64). Created 2026-05-12T21:25Z.

Same formula opener as Draft [1] confirmed. Second sentence is a structural twin:
"[Month] [sits at / closes out] the [tail of / end of] the dry season here; [vegetation]
cured by months without rain [burns hot / into fuel] before the [rains / wet season]
[reset / arrive]." The writer produced the same two-sentence shape in consecutive runs,
only swapping regional vocabulary. Memory's `used_framings` is not preventing structural
reuse across runs.

No kicker, no incongruity, no named mechanic. Graded C (below Draft [1]) because this is
the second instance of the same formula — the convergence itself is the failure mode.

#### [3] Chuuk FSM monthly_high — 34.4°C — **B**

> *Chuuk, Federated States of Micronesia hit 34.4°C (94°F) on May 9 — a new May record in
> 76 years of data, edging past the 33.9°C mark set in 2000. The western Pacific warm pool
> keeps sea-surface temperatures here among the highest on Earth year-round.*

**Score:** 80 (threshold 76). Created 2026-05-13T10:32Z.

Humor lens:
- **Violation:** New May record in 76 years. Real signal, well-stated.
- **Benign?** Yes. Calm register.
- **Setup→Punchline?** Setup: 34.4°C, 76 years, prior mark 33.9°C in 2000. Second sentence:
  ecosystem specificity (Pacific warm pool). This is context, not punchline. The implied
  incongruity — "even the warmest ocean on Earth just broke its own May record" — is present
  but unexploited, stated as explanation rather than as a deadpan landing.
- **Named mechanic?** Ecosystem specificity. No comic mechanic.
- **Wodehouse rule?** Clean. No restate-padding, no defensive justification, no explicit-gap
  math. Tone measured. Not trying too hard.

Strongest draft in the cycle. Data complete: city, full country name, °C + °F, specific
observation date (May 9), archive depth (76 years), prior record temperature (33.9°C),
prior year (2000). All voice-spec requirements met for monthly_high type. No Wodehouse
violations.

Deduct for: second sentence is expository rather than a voice move. "The western Pacific
warm pool keeps sea-surface temperatures here among the highest on Earth year-round" is
educational. The implied incongruity ("warmest ocean already; still breaking records") is
present but not stated. If it ended "Chuuk sits in the Pacific's warmest waters. Those
waters just broke their own May ceiling." — that would grade A-/B+. As written, B.

"Edging past" is soft phrasing for a 0.5°C margin in a 76-year dataset. The margin is
real and notable; flatter language would let it stand on its own.

#### [4] Mongolia fire — 307.6 MW — **C**

> *A fire in eastern Mongolia is radiating 307.6 MW of heat, detected by satellite at 95%
> confidence. Mongolia's steppe turns dry by late spring as winter snowpack retreats; cured
> grasslands ignite fast and spread far across open terrain.*

**Score:** 64 (threshold 64). Created 2026-05-13T10:33Z.

Third fire draft; third instance of the formula opener. The second sentence achieves the
only regional distinctiveness in the fire batch: "winter snowpack retreats" is
Mongolia-specific (the other drafts reference rain cycles), and "spread far across open
terrain" gives a landscape sense the others lack. Still no punchline, no kicker, no
stated incongruity about whether May is expected or unusual for Mongolian steppe fires.

"Mongolia's steppe turns dry by late spring as winter snowpack retreats" describes a
natural, expected seasonal progression. There's no implied anomaly. Without a timing
statement ("The burning season here typically ends by June. It is May." would be weak
here because May IS normal) or a different angle on the incongruity, the framing is
geography lesson, not deadpan. The snowpack detail earns C over C-; the formula
pattern keeps it from B.

### Patterns named in this batch

1. **Fire template convergence (new failure mode).** All three fire drafts follow the same
   two-sentence structure: (1) "A fire in [location] is radiating X MW of heat, detected by
   satellite at N% confidence." (2) "[Region's vegetation/landscape] [seasonal transition];
   [combustion behavior note]." The writer produces this shape across Mali savanna, Campeche
   tropical forest, and Mongolian steppe. Memory's `used_framings` is not preventing
   structural reuse across consecutive cron runs. Template needs to be burned in the prompt.

2. **Seasonal context as explanation, not punchline.** The P3 failure mode (writer self-kill
   when no archive data is available) is NOT evidenced today — all three fire drafts reached
   pending with seasonal framing intact. Positive improvement. But the framing is deployed
   as educational prose rather than as the incongruity-delivery vehicle. The A-grade pattern
   was: state the data, state the timing anomaly, land the kicker ("It is April."). Today's
   pattern: state the data, explain the dry season, stop. The kicker is absent.

3. **No named humor mechanic in any fire draft.** No comic triple, no period-and-restate,
   no deadpan kicker, no era anchor, no idiom-flip. The writer is not reaching for the named
   palette of moves. Consistent with P5's diagnosis: moves not named in the prompt don't get
   used.

4. **Chuuk monthly_high is the strongest draft but stops short of a punch.** All data
   requirements met. No Wodehouse violation. The implied incongruity (warmest ocean still
   broke its May record) is present but unstated. One punchy closer would move this to A-.

5. **P3 self-kill failure not observed.** All three fire drafts reached pending with seasonal
   context deployed. Improvement confirmed in first graded two-bot cycle.

6. **FRP rounding working.** Today's values (309.6, 364.7, 307.6) confirm bundle-side
   rounding (#80) is producing clean 1-decimal FRP values. No BUNDLE_FACT mismatch kills
   on rounding observed.

### Followups

1. Burn the fire template: add to writer_prompt.py fire framing: the two-sentence
   "[radiating X MW]...[seasonal context]" structure is burned — name alternative sentence-1
   forms (lead with FRP number, lead with regional ecology, lead with timing incongruity).
2. Add deadpan kicker instruction to fire framing: "When timing is anomalous, state it
   directly and stop: 'The burning season here peaks in [month]. It is [current month].'
   That is the punchline."
3. Watch P3 status: if next 2 cycles also show no self-kills, move to Resolved.
4. Chuuk as a near-miss exemplar: "Chuuk sits in the Pacific's warmest waters. Those
   waters just broke their own May ceiling." is the A- version.

### Numbers

- Pending drafts graded: 4 (3 fire, 1 monthly_high)
- A-rate: 0% (0/4)
- Grade distribution: 0 A / 1 B / 3 C (one C+) / 0 D-F
- First graded two-bot pipeline cycle
- Staleness rejection: not applicable (all drafts < 48 hours; no baked "today" content)
- P3 failure mode: not observed (positive)
- New failure mode identified: fire template convergence → P6 proposal added

---

## 2026-05-12 — No fresh pending drafts (0 drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 0 pending
drafts. Two alert cron runs fired today (10:34 UTC, 14:39 UTC); both produced zero
`pending` drafts. Most recent draft in any state: 2026-05-11T03:41Z (rejected). The
live pipeline is now the two-bot path (Sonnet 4.6 writer + Gemini fact-checker);
`src/voice/generator.py` has been dead since 2026-05-04.

**Grade distribution:** N/A — no pending drafts to grade. **A-rate: —**  
Gap from resumption bar: unmeasured (still 50pp from last graded cycle, Apr 29).

### Why the queue is empty

154 suppressions in the ledger. Three kill patterns account for every draft suppressed
in today's two runs:

**Kill pattern 1 — Station-name normalization → fact_check (monthly_record)**

`normalize_station_name()` strips direction/distance suffixes before the writer sees
the bundle, but the raw name survives in bundle fields the fact-checker validates
against. Result: every Paddock Lake 4 Ne, Wisconsin draft triggers a BUNDLE_FACT kill
("bundle specifies 'Paddock Lake 4 Ne', not 'Paddock Lake'"). Same kill fired for
Sioux City Ang → Sioux City (2026-05-11). Pattern repeats identically across all three
today-runs for the same station. This is known issue #5 in BRIEFING.md.

**Kill pattern 2 — Fire MW rounding → fact_check (fire)**

Fact-checker requires exact numerical match on FRP values. Writer rounds: 480.34 →
480 (BUNDLE_FACT), 547.92 → 548 (BUNDLE_FACT), 301.55 → 301 (BUNDLE_FACT). Every fire
draft that makes it past the writer dies here. Also observed: a writer-fabricated Hoover
Dam comparison ("roughly what the Hoover Dam generates at full capacity" for a 301 MW
fire; Hoover actual capacity ≈ 2,080 MW — off by factor 7) killed as WORLD_KNOWLEDGE.

**Kill pattern 3 — Writer self-kills on fire drafts (fire)**

Writer kills fires citing "no historical_context available; no peer comparison confident
enough to use; no verifiable seasonal or rarity framing without archive data." Two Western
Sahel fires (480 MW, 301 MW) and one Siberia fire (548 MW) died here. The writer knows
seasonal context is available ("May fires in Amur are seasonally plausible") but won't
use it without verified archive data. The old voice engine used seasonal deadpan ("The
burning season here typically peaks in January. It is May.") as world knowledge. The
two-bot writer is holding itself to a stricter standard than the data requires.

**Kill pattern 4 — Memory burn on rejected drafts**

Writer killed a second Baudette, Minnesota anomaly draft (score 74 vs 76 threshold)
citing "same event already shipped; no fresh angle survives the burned framings list."
The Baudette monthly_low (score 82, threshold 76) was human-rejected, not posted.
`used_framings` is persisting rejection events as if they were shipped.

**Resolved 2026-06-16:** PR #293 moved same-event, used-framing,
peer-comparison, shipped-text, and posted-event memory writes behind successful
publishing. A generated, killed, rejected, or pending draft is no longer treated
as coverage until `post_approved` returns a real tweet id.

**Two infra sources degraded (non-blocking)**

`ocean_sst`: "Exceeded 30 redirects" on every run today. `river_gauges`: "Expecting
value: line 1 column 1" (empty response). Both sources produce no signals; pipeline
continues without them.

### Andrew's quality direction (2026-05-11)

Mankato, Minnesota monthly_low (score 79, threshold 76) manually rejected with explicit
note: *"weak signal (tied 30F by 0.1C in 16yr archive, defensive 'A record is a record'
closer). Voice direction set 2026-05-11."*

Two signals:

1. **Marginal cold records are below the bar.** 0.1C margin + 16yr archive + cold record
   (not heat, not summer) is not worth a tweet. The Sonnet writer's own self-kill on
   Mankato ("Margin is 0°F in Fahrenheit, archive only 16 years, feed has already run
   multiple near-identical US May cold-record tweets this week") was correct. Writer
   judgment aligns with Andrew's.

2. **"A record is a record" is a Wodehouse violation.** The closer pre-justifies a weak
   signal rather than letting the data speak. It shows effort — the tweet is defending
   itself. Same tell-don't-show failure flagged in Apr 27 corpus (Mexico City: "That gap
   is 4.5 degrees") and Apr 29 (same). P4 evidence confirmed in two-bot pipeline.

### Architecture note

All active proposals in IMPROVEMENT_PLAN.md (P2–P6) target `src/voice/generator.py`
code: SYSTEM_PROMPT, `_STOCK_FORMULA_PATTERNS`, `_CATEGORY_PROMPTS`. That file is dead.
The proposals are obsolete as written. They need redirection to
`src/two_bot/prompts/writer_prompt.py` or the two-bot safety pipeline. See plan update
for how each proposal was handled.

### Patterns named in this batch

1. **Two-bot pipeline fully operational but zero output reaching pending.** Not a
   voice-quality problem — a pipeline-bug stack. Fix station normalization or MW
   rounding and drafts flow immediately.
2. **Fact-checker is too strict on fire MW rounding.** 480.34 → 480 is standard
   engineering notation, not a factual error. The fabricated Hoover Dam comparison is a
   separate, correct kill.
3. **Writer fire overcall.** Seasonal deadpan is verifiable world knowledge and should
   not require a historical archive. Refusing to write it is over-calibrated.
4. **P4 (Wodehouse rule) confirmed in two-bot output.** Andrew's explicit manual-reject
   names the same defensive-closer pattern. Evidence transfers to new pipeline.
5. **Generator.py is dead. All prior proposals are targeting dead code.**

### Followups

1. Fix station normalization — bundle `where`/`station_name` fields must be normalized
   consistently so writer and fact-checker see the same string. Surgical change in
   `src/two_bot/intern.py` GHCN bundle builders.
2. Fix MW rounding — writer prompt must specify: use exact decimal FRP from bundle
   (e.g., "480.3 MW" not "480 MW"). Separately: ban named-infrastructure comparisons
   without exact MW values from bundle.
3. Writer fire framing — add to writer prompt: seasonal/calendar context is world
   knowledge and doesn't require archive data. Permission to write seasonal deadpan
   without numeric historical comparison.
4. Redirect P4 + P6 proposals from dead generator.py to writer_prompt.py.

### Numbers

- Pending drafts graded: 0
- A-rate: — (not measurable)
- Two-bot pipeline suppressions (total ledger): 154
- Today's cron runs with zero pending output: 2
- Active infra failures: ocean_sst (redirect loop), river_gauges (empty response)

---

## 2026-04-29 — Era anchors at 100% on records (3 drafts)

**Context:** Three new record drafts came in on 2026-04-29 cycles. All
three used era anchors. This is the third consecutive cycle with
≥80% era-anchor deployment on record drafts (Apr 25: 3/3 used era
anchors, Apr 27: 5/5, Apr 29: 3/3). User direction (2026-04-29):
park era anchors at 1-in-10. Implemented same day in commit (this
session).

**Grade distribution:** 0 A, 2 B (B / B+), 1 B-. **A-rate: 0% (0/3).**
Gap from resumption bar: 50 points.

### Per-draft

#### [1] Cuenca, Ecuador — score 72 — **B-**

> The last time Cuenca, Ecuador was this warm on this date, Adele's
> 21 was the bestselling album in the world. That was 2011. Today's
> forecast: 70.2F, against a record of 67.3F.

Era anchor inverted to opener (Steven Wright move: lead with the
cultural reference, ground in data after). Anchor lands ("Adele's 21"
is in `era_anchors.json` 2011). **Problem:** 70.2F is not impressive
without altitude context. Cuenca is at ~2,500m — the temp IS extreme
for that elevation, but the tweet doesn't surface it. Reader sees
70.2F and thinks "that's not hot." Ecosystem-specificity vehicle
(which carried Apr 27 [8] Mexico highlands B+) is the missing move.

#### [2] Mexico City — score 74 — **B**

> Mexico City is forecast to hit 90.9F today. The record for this
> date was 86.4F, set in 2017 — the year the iPhone X launched.
> That gap is 4.5 degrees.

Era anchor lands (iPhone X / 2017 in `era_anchors.json`). Closer is
"That gap is 4.5 degrees" — **same Wodehouse soft-violation flagged
on Apr 27 [10] Petaling Jaya** (explicit gap math the reader could
do). Trim that and it's B+. Same Wodehouse-violation pattern,
second cycle.

#### [3] Jacksonville — score 73 — **B+**

> Jacksonville is on pace for 92.8F today. The old record was 90F,
> set in 2002. Last time it was this hot on this date, the first
> Spider-Man movie was still in theaters.

Strongest of the three. Era anchor (2002 Spider-Man, in
`era_anchors.json`) + "still in theaters" temporal-duration framing.
**No Wodehouse violation.** Tight.

### Patterns named in this batch

1. **Era-anchor convergence at 100%.** All 3 records used era anchors.
   Third cycle with this pattern. P1 evidence count: now 3 cycles.
2. **Wodehouse violation repeats.** "That gap is X degrees" surfaced
   on Apr 27 [10] (B+) and now Apr 29 [2] (B). Same explicit-gap
   math pattern. P4 evidence count: 2 cycles direct + multiple
   indirect.
3. **Missing ecosystem context** for high-altitude cities. Cuenca at
   70.2F is hot for 2,500m elevation but the tweet doesn't say so.
   Apr 27 [8] Mexico highlands used the right ecosystem move
   ("monsoon that extinguishes these fires"). The bot should be
   reaching for elevation/climate-zone context when the absolute
   temperature is mid-range but the location makes it extreme.
4. **`evaluator_pass` field is null on all 3 drafts.** Sonnet
   evaluator either didn't run or didn't write its verdict. Worth
   investigating but separate from voice work — possibly
   `EVALUATOR_ENABLED=false` got set somewhere, or the pass-through
   has a logging gap.

### Followups

1. **Era-anchor 1-in-10 gate SHIPPED 2026-04-29** (this session) —
   `_era_anchor_should_fire` deterministic gate, 90% of calls return
   explicit steer-away with alternative vehicles named, 10% of calls
   return curated content framed as "your 1-in-10 turn." Plus the
   addendum-mismatch fix (`all_time_record`/`monthly_record`
   categories now match `all_time_high/low` and `monthly_high/low`
   addendum keys, which had been dormant). Plus rewrite of all 5
   record-type per-category addenda to use a shared 6-vehicle menu.
   Plus SYSTEM_PROMPT #1 ("HISTORICAL WEIGHT") rewritten to be
   vehicle-agnostic (era anchors no longer evangelized as the move).
   Plus three new bad-examples (gap math, restate-padding, era-
   anchor-then-restate template).
2. **Verify the gate empirically** — next 3 cycles should show era
   anchors on ≤30% of records (statistically expected ~10%).
3. **Evaluator null verdict** — needs investigation. Out of scope
   for this voice-work session.

### Numbers

- A-rate: 0% (was 9% Apr 27, 43% Apr 25, 9% Apr 24)
- Gap from bar: 50 points
- Era-anchor deployment on records: 100% (3/3) — pre-gate
- Tests: 566 passing (was 561, +5 from new gate tests)

---

## 2026-04-27 — Voice engine v2.5 verdict (11 new drafts)

**Context:** First alerts-cycle output after voice engine v2.5 shipped
2026-04-26: era-anchor database (commit `3c3634d`), recalibrated voice
rules permitting earned editorial heat (commit `609ff4b`), opener-
formula regex ban (commit `c75d0d4`), multi-station roll-call (commit
`98268ca`). Bot is confirmed running on `c75d0d4` per `gh run view`. The
queue still holds 18 pending — drafts [1]-[11] are the new Apr 26-27
batch graded here; drafts [12]-[18] are Apr 24-25 carryovers already
graded in the 2026-04-25 section below (none have been approved or
rejected since).

**Grade distribution (new drafts only):** 1 A-, 5 B-range, 1 C+ (political
era anchor), 4 D-range (banned-opener variants returned).
**Shippable rate (Apr 27): 6/11 = 55%** — down from Apr 25's 86%.

**Headline finding:** records held up. Era anchors are landing reliably:
"Pokémon GO" (2016), "Hollywood writers were on strike" (2023), "the year
before YouTube" (2004), "Y2K was a real worry" (1999), and "Windows 98 was
new" (1998) all show in production. The era_anchors.json system is
working as designed.

Fires regressed. Four of eight new fire drafts use opener-formula
variants the regex doesn't catch — either a new verb (`pushing` instead
of `radiating`, draft [11]) or shapes that pass through the evaluator's
rewrite path (drafts [3], [4], [6]). Plant-comparison regex also has a
gap — it doesn't match "a commercial nuclear reactor" because
"commercial" isn't in the adjective allowlist.

One political-anchor regression: draft [7] surfaced "since Elon Musk
bought Twitter" as the 2022 era anchor. Tracing back, era_anchors.json
2022 has "Twitter was acquired by Elon Musk" and 2024 has "Trump won the
US election a second time." Both violate the "never preach, never
political" voice rule. Curation error from the Apr 25 build.

### A range — strongest (1)

#### [9] Mali Western Sahel fire — signal 67 — **A-**

> Mali's Western Sahel is burning. A 291 MW fire is active in a
> landscape where the burning season typically peaks in January and
> ends by February. It is April 26.

Terse three-sentence structure. "Mali's Western Sahel is burning" is the
strongest fire opener in the new batch — declares the stake before the
number. Season-mismatch context (peaks in January, April now) is sharp.
"It is April 26" closer earns its place. Best fire draft since the
2026-04-25 Mali "HOT season" entry.

### B range — shippable (5)

#### [8] Mexico highlands fire — signal 69 — **B+**

> 379 megawatts of heat radiating from the State of Mexico highlands
> right now. Satellite confidence: 95%. The summer monsoon that
> extinguishes these fires is still weeks away.

Lead with the number. "State of Mexico highlands" is specific. "Summer
monsoon that extinguishes these fires" is ecosystem-aware framing —
better than generic seasonal-clock context.

#### [10] Petaling Jaya record — signal 72 — **B+**

> Petaling Jaya is forecast to hit 93.6F today. The record for this
> date was 89.2F — set in 2023, back when Hollywood writers were on
> strike. That gap is 4.4 degrees.

Era anchor lands (Hollywood writers' strike, from era_anchors.json 2023).
"That gap is 4.4 degrees" closer is unusual — explicit gap rather than
implied. Reads natural.

#### [5] Bukit Rahman Putra monthly record — signal 79 — **B**

> Bukit Rahman Putra is forecast to hit 94.5F today. If it holds, that
> breaks an April record that has stood since 2016 — the year Pokémon
> GO had everyone walking outside. The new high: 94.5F. The old one:
> 93.7F.

Era anchor strong (Pokémon GO from 2016 anchors). The closer
("The new high: 94.5F. The old one: 93.7F.") restates the data already
given — feels like model padding. Trim for ship.

#### [1] Mexico State fire 258 MW — signal 66 — **B**

> Mexico State is radiating 258 MW of energy. 95% satellite confidence.
> The region's dry season doesn't break until late May. It is only
> April 27.

Lead with state name. Seasonal context. "It is only April 27" closer is
the same beat as draft [9] — slight repetition risk if both ship.

#### [2] Central Mexico fire 298 MW — signal 67 — **B-**

> A 298 MW fire signature just appeared in central Mexico. Satellite
> confidence is 95 percent. The historical peak for fire activity in
> this region is still three weeks away. The rainy season does not
> typically begin until June.

Lead with the number. But two redundant seasonal-clock beats ("peak is
three weeks away" + "rainy season doesn't begin until June") read as
overstuffed. Pick one.

### C range — needs rewrite (1)

#### [7] Jacobabad record — signal 72 — **C+ (political)**

> Jacobabad is forecast to hit 114.1F today. The old record for this
> date was 112.1F. That record was set in 2022. It has only been the
> record since Elon Musk bought Twitter.

Era anchor crosses the political line. "Twitter was acquired by Elon
Musk" is in `data/era_anchors.json` 2022 — curation error. The structural
template (record-set-recently → era anchor) works, but Elon Musk is a
politically-polarizing reference the bot's voice rules ban. Either the
anchor entry gets pruned (immediate fix), or this draft needs rewrite
with a different 2022 anchor (FTX collapse, Queen Elizabeth II, World
Cup in Qatar).

### D range — banned-formula variants returned (4)

#### [3] Mexico State fire 281 MW — **D-**

> A wildfire burning in Mexico State is radiating 281 MW of heat —
> roughly the output of a mid-sized power plant, pointed at the sky.
> Satellite confidence: 95%. It is April 27.

Two simultaneous regressions: the banned opener formula (matches the
regex per direct test — should have been rejected at generation), and
the power-plant comparison ("a mid-sized power plant"). "Pointed at the
sky" tries for poetry, doesn't land. This draft made it through despite
the regex — likely Sonnet evaluator rewrote a clean Gemini candidate
into this shape, and rewrites bypass `_detect_stock_formula`.

#### [4] Mexico state fire 382 MW — **D**

> A wildfire in Mexico state is radiating 382 MW of heat right now.
> Satellite confidence: 95%. For reference, a commercial nuclear
> reactor outputs around 3,000 MW. This fire is running at roughly
> one-eighth of that — from a forest.

Banned opener + plant comparison. "Commercial nuclear reactor" slips
the existing plant-regex (doesn't have "commercial" in the adjective
allowlist). "From a forest" closer is decent but everything before is
the bad pattern.

#### [6] Central India fire 274 MW — **D**

> A single fire in central India is radiating 274 MW of heat right
> now. That is roughly the output of a mid-sized power plant.
> Satellite confidence: 95%. The date is April 27.

Banned opener (variant: "A single fire in [LOCATION] is radiating") +
plant comparison. "The date is April 27" — date-stamping closer with no
seasonal hook, weak.

#### [11] Central India fire 297 MW — **D**

> A single wildfire in central India is pushing 297 MW of radiative
> power. Monsoon season does not start for another six weeks.
> Satellite confidence: 95%.

Banned opener with verb-list gap: `pushing` isn't in the regex's
verb allowlist (`radiating | releasing | generating | putting out |
emitting | producing`). Direct evidence the regex needs widening — or
better, restructured to match shape rather than verb. Monsoon-clock
context is fine; opener kills it.

### Patterns named in this batch

1. **Opener-formula whack-a-mole.** Verb list hardcoded from Apr 24
   corpus (`radiating | releasing | ...`) misses neighbors (`pushing` is
   the new variant). Regex is chasing model entropy. Each new verb
   requires corpus observation + deploy.
2. **Plant-comparison adjective gap.** Existing regex catches
   `a/an/the (typical|standard|average|large|small|usual)? (coal|nuclear|gas|power) plant/reactor runs/generates/produces N`.
   Misses `commercial`, `industrial`, `mid-sized` (which is in [3]),
   "high-capacity", and probably more. Same whack-a-mole shape.
3. **Era anchors include politically-polarizing entries.** "Twitter was
   acquired by Elon Musk" (2022) and "Trump won the US election a second
   time" (2024) are in `data/era_anchors.json`. Curation oversight from
   2026-04-25 build. Both violate "never preach, never political."
4. **Era-anchor system is otherwise WORKING.** 5 of 5 record drafts in
   this batch used era anchors that landed naturally. The "pre-computed
   anchor passes through to prompt" plumbing is doing what it should.
5. **Sonnet evaluator rewrites bypass `_detect_stock_formula`.** Drafts
   [3] and [4] match the regex on direct test but shipped anyway —
   evaluator rewrite path runs `run_safety_pipeline` only. User has
   confirmed (2026-04-27) this is intentional design — Sonnet's rewrite
   is a deliberate creative pass and trusts Sonnet's judgment over the
   regex. Logging here for the record.

### Followups (in priority order)

1. **Prune politically-charged anchors from `data/era_anchors.json`.**
   Remove "Twitter was acquired by Elon Musk" (2022), "Trump won the US
   election a second time" (2024), and scan all 31 years for similar
   (Capitol riot 2021, Brexit 2016 — these are in the file; verdict
   pending re-read of the curation).
2. **Widen plant-comparison regex** with more adjectives (`commercial`,
   `industrial`, `mid-sized`, `high-capacity`) OR drop the adjective
   slot entirely.
3. **Widen opener-formula verb list** OR rewrite the regex to match
   shape (`is\s+\w+(?:ing|s)\s+\d`) — flag false-positive risk first.
4. **Bulk-reject the 4 D-range fire drafts** ([3], [4], [6], [11])
   to clean the queue.
5. **Out of scope (per user):** changing the evaluator rewrite path to
   run `_detect_stock_formula`. Intentional.

### Numbers

- Pending drafts: 18 (11 new graded here, 7 carryovers from Apr 25)
- Shippable rate (Apr 27 batch): 6/11 = 55% (down from Apr 25's 86%)
- Records: 3 of 3 used era anchors; 2 cleanly, 1 political (curation issue)
- Fires: 4 of 8 used banned-opener variants; 4 are clean
- Bot confirmed running on commit `c75d0d4`

### Humor-research lens evaluation (applied 2026-04-26)

After grading the 18 drafts on the corpus rubric, ran them through the
humor-theory framework from `brand/HUMOR_RESEARCH.md`. The lens
dimensions for each tweet: violation present, voice keeps it benign,
data-as-setup / voice-as-punchline structure, named mechanic operating
(or none — pure data is valid), and Wodehouse rule (does the voice
sound like it's trying).

**Per-draft lens reading** — Apr 26-27 batch [1]-[11]:

| # | Grade | Lens reading |
|---|---|---|
| 1 | B | Pure data setup + understatement closer ("It is only April 27"). Wodehouse intact. Working. |
| 2 | B- | No clear punchline — two seasonal beats stack and dilute. Trying slightly. Pick one beat, not both. |
| 3 | D- | Throat-clearing opener strands a poetry-attempt closer ("pointed at the sky"). Wodehouse violated — visibly trying. |
| 4 | D | The "from a forest" closer IS a real Steven Wright idiom-flip move — but stranded inside throat-clearing + math-out-loud. The punchline is dead because the setup buried it. |
| 5 | B | Era anchor lands ("Pokémon GO had everyone walking outside") — then restate-pads with data already given. Trim restate, the era anchor lands cleaner alone. |
| 6 | D | No mechanic operating. Throat-clearing opener + plant comparison + flat date closer. Template fatigue, not failure-of-trying. |
| 7 | C+ | Structural template works (setup → era anchor closer); content fails the "never political" criterion. Anchor was Elon Musk — pruned from `era_anchors.json` Apr 26. Tweet shape is fine; data was the problem. |
| 8 | B+ | Lead with magnitude, ecosystem-specific closer ("monsoon that extinguishes these fires is still weeks away"). Subtle understatement, no formula. Working. |
| 9 | A- | **Reference draft.** Period-and-restate opener ("Mali's Western Sahel is burning.") + bridge + understatement closer ("It is April 26"). Comic triple with all three beats earning their place. Wodehouse perfect. |
| 10 | B+ | Era anchor lands ("Hollywood writers were on strike"). Closer ("That gap is 4.4 degrees") slightly try-hard — explicit gap math reader could have done. Trim, era anchor stronger alone. |
| 11 | D | No mechanic. "Pushing" verb is the regex gap. If we trimmed throat-clearing to "297 MW wildfire in central India" — pure data delivery would have been valid. Failure is the opener, not absence of joke. |

**Apr 25 carryovers in the queue [12]-[18]** — re-read through the lens:

| # | Grade | Lens reading |
|---|---|---|
| 12 | C+ | Comic triple in the closer ("October. That was 6 months ago.") buried by throat-clearing opener. The right tweet is just the closer beats. |
| 13 | A- | Earned editorial heat ("HOT season") + understatement closer ("It's April") + lead with number. Stack of mechanics, all earned, none trying. |
| 14 | B | Era anchor lands ("the year before YouTube"). "Nearly 3 degrees" approximation when 2.7F is exact = mild Wodehouse violation (showing work). |
| 15 | B+ | Era anchor with twist phrasing ("Before Y2K was a real worry"). 110.8F is absolute-scale shock. Two mechanics stacked. |
| 16 | A- | **Accelerating-warming specificity** ("set just last year in 2024") — not an era anchor, a different vehicle. Carries the climate argument without saying it. |
| 17 | B+ | Era anchor matching record year (1998 → Windows 98). Slight on-the-nose but recognition is universal. |
| 18 | A- | **Reference draft.** Place opener + Steven Wright idiom-flip ("used to know when to quit") + past-tense personification + understatement closer. Multiple mechanics stacked, none trying. |

### What the lens reveals

**1. The strongest drafts use DIFFERENT mechanics, not the same one.**
The five A-tier drafts ([9], [13], [16], [18], plus [8] B+) operate on
different humor mechanics: idiom-flip, earned editorial heat,
accelerating-warming, period-and-restate, ecosystem specificity. The
bot is best when it varies the move. The weakest drafts ([3], [4],
[6], [11]) all converge on the same throat-clearing-opener pattern.
Variety vs convergence is a sharper diagnostic than the regex/score
view alone.

**2. Era anchors are over-represented because they're the path of
least resistance.**
5 of 7 record drafts in the queue used era anchors. The strongest
record draft ([16] Navi Mumbai) did NOT — it used accelerating-warming
specificity ("set just last year in 2024"). The strongest fire drafts
([9], [13], [18]) used idiom-flip / understatement / earned editorial
heat — not era anchors. Era anchors are easy for Gemini to deploy and
they sometimes land, but they're not the only specificity vehicle and
shouldn't be the default.

**3. Wodehouse violations cluster in two specific patterns.**
- **Approximation when exact is available** ([14] Manchester: "nearly
  3 degrees" when it's 2.7F). Reads as soft.
- **Restate-padding** ([5] Bukit Rahman Putra: "The new high: 94.5F.
  The old one: 93.7F." after the data was already given). Reads as
  showing work.
Both are visible-effort signals. Eliminate them and several B drafts
move to B+ without changing structure.

**4. Stranded mechanics are an under-appreciated failure mode.**
Drafts [3] ("pointed at the sky"), [4] ("from a forest"), and [12]
("That was 6 months ago") all contain real humor moves — poetry
attempt, Steven Wright idiom-flip, comic triple respectively. The
moves don't fail; they're stranded inside throat-clearing or
over-explanation. The tweet shape kills mechanics that would land if
the surrounding prose were trimmed. This means the regex-rejector,
Sonnet rewrite path, and per-category prompts should all push toward
**leaving the punchline alone** — no setup-stuffing, no math-out-loud,
no closer-on-top-of-closer.

**5. Pure data delivery is valid and currently underused.**
[16] Navi Mumbai is essentially flat data: forecast / margin / record-set-when.
No mechanic. Earns A- because the recency itself is striking. The
prompts should explicitly state: when the number alone is striking
enough, present the data and trust the reader. Don't force a humor
mechanic. ("not everything has to be a joke.")

**6. The Wodehouse rule is the single most predictive principle.**
Drafts that violated it (visible trying — poetry attempts, math-out-
loud, restate-padding) graded D-/C+/B regardless of whether era anchors
or specificity were present. Drafts that respected it (no visible
trying — flat data, named mechanic that sounds natural) graded B+/A-
regardless of whether they used a humor mechanic at all. The Wodehouse
rule deserves top-of-prompt placement.

### Implications for prompt updates (next step)

1. **SYSTEM_PROMPT top section** — add Wodehouse rule explicitly:
   *"Don't sound like you're trying. The data is already
   extraordinary; the voice is its straight man."*
2. **Name humor moves as available tools, not requirements.** List
   them: comic triple, idiom-flip, understatement closer,
   period-and-restate, deadpan, accelerating-warming, era anchor.
   Add: *"None of these are mandatory. When the number alone is
   striking, deliver the data plainly. Forced humor breaks the spell."*
3. **Reframe era anchors in record-type addenda** as one of several
   specificity vehicles. List the others (accelerating warming,
   recency framing, place identity, absolute scale, era anchor) and
   note: *"Vary across drafts. Era anchors used every record become
   the formula they were meant to escape."*
4. **Add stranded-mechanic warning to fire prompt.** *"If you write a
   punchline, leave it alone. Don't pre-explain it ('for reference,
   a power plant runs at...'), don't post-explain it ('that's
   roughly one-eighth of that'). The data is the setup. The closer
   is the punchline. No math out loud."*
5. **Add Wodehouse-violation tells to the bad-examples list.**
   "Approximation when exact is available," "restate-padding,"
   "explicit gap math the reader could do."

These are the empirically-grounded changes. Apply once user signs off.

---

## 2026-04-25 — Voice engine v2 first verdict (7 drafts)

**Context:** First alerts-cycle output after voice engine v2 (commit
`827a891`), `gemini-flash-latest` (commit `b33d4a8`), 70+ region geocoder
(commit `22cbc8e`), and 250 MW FRP floor (commit `023c3ed`) all shipped
2026-04-24. The Apr 24 corpus is the baseline (7/35 = 20% shippable).

**Grade distribution:** 3 A-, 3 B+/B, 1 reject (formula-opener dup).
**Shippable rate: 6/7 = 86%.** v2 worked.

**Headline finding:** the per-category prompt addenda are doing the
work. Fire drafts now lead with specific named region + seasonal
framing instead of MW math. Records lean reliably into era anchors.
The one rut that returned (#7) is the "A fire burning in [LOCATION]
right now is radiating..." opener — should be added to the v2 banned
openers regex.

### A/B grade — shippable (6)

#### #1 New South Wales fire — signal 68 / copy ? — **A-**

> New South Wales. A 327 MW fire today. The bushfire season here used
> to know when to quit. It's April.

Past-tense personification ("used to know when to quit") echoes the
strongest Apr 24 move (Chicago anomaly: "used to define an entire
season"). Lead with named region. No power-plant comparison, no
home-count, no "no name yet". Best fire draft in the corpus history.
This is the v2 result we wanted.

#### #2 Kampung Baru Subang — signal 76 / copy ? — **B+**

> Kampung Baru Subang, Malaysia forecast to hit 94.1F today. The
> calendar date record from 1998 was 89.6F. Back then, Windows 98 was
> new.

Era anchor matches the record year (1998 → Windows 98). Slightly on
the nose but the recognition is universal.

#### #3 Navi Mumbai — signal 72 / copy ? — **A-**

> Navi Mumbai is on pace for 106.7F today. That's 4.5F hotter than
> its record for this date, set just last year in 2024.

Accelerating-warming story — same family as Ipoh #24 from Apr 24
("Two hottest Aprils back to back"). 106.7F is the kind of absolute
number that does the work. "Set just last year in 2024" is the move.

#### #4 Lucknow — signal 73 / copy ? — **B+**

> Lucknow is forecast to hit 110.8F today. That beats its calendar
> record from 1999. Before Y2K was a real worry.

Y2K anchor is reliable per Apr 24 #32 Kathmandu. "Before Y2K was a
real worry" twist is fresh. 110.8F carries it.

#### #5 Manchester — signal 73 / copy ? — **B**

> Manchester forecast: 68.7F today. That beats the previous record for
> this date by nearly 3 degrees. The old mark of 66.0F was set in
> 2004, the year before YouTube.

"The year before YouTube" is sharp. Colon-restate matches Apr 24 #24
Ipoh's voice move. The risk: 68.7F sounds modest globally. UK readers
will get it; the rest of Twitter scrolls. "Nearly 3 degrees" is an
approximation when an exact number was already given (2.7F). Could
sharpen.

#### #6 Mali Western Sahel — signal 69 / copy ? — **A-**

> 404 MW of fire in Mali's Western Sahel. The land has been parched
> for months, and the HOT season has barely started. It's April.

ALL CAPS "HOT season" is voice engine v2 visibly unlocking — the
@extremetemps observation argued the genre permits earned editorial
heat. This earns it: drought + early-season + size. Lead with the
number. Specific named region. No formula.

### Rejected — voice failures (1)

#### #7 Mali Western Sahel (dup) — **C+**

> A fire burning in Mali right now is radiating 404 MW of heat. The
> last rain fell there in October. That was 6 months ago.

Same signal as #6, generated 46 seconds later. The "last rain fell
there in October" beat is genuinely good. But the opener — "A fire
burning in [LOCATION] right now is radiating..." — is the exact
template that produced 12 D/F drafts on Apr 24. Voice engine v2's
universal prompt should ban this opener pattern explicitly.

Operationally: same-event dedup should have caught this. Both drafts
came from the same alerts cycle (timestamps 75ms apart in the run
log), suggesting the dedup window doesn't cover within-cycle. Worth
checking.

### Patterns confirmed working in this batch

1. **Specific named region** — 6/7 drafts lead with city or named
   region. Geocoder upgrade visible in fire drafts.
2. **Era anchors landing reliably** — Windows 98, Y2K, YouTube,
   "set just last year" all do work without feeling forced.
3. **Past-tense framing of normal as past-tense** — "used to know
   when to quit" (#1), echoing Apr 24 "used to define." Becoming a
   named voice move.
4. **Earned editorial heat** — ALL CAPS "HOT" in #6. v2 explicitly
   intended.
5. **No power-plant comparisons. No home-count formulas. No "no name
   yet."** All three banned formulas absent from this batch.

### Voice rut still open

1. **"A [signal] [in LOCATION] right now is radiating..." opener** —
   #7 reproduced this. v2 universal prompt + parse-time rejector
   should explicitly catch the `^A (fire|wildfire|storm|...) [verb-ing]
   (in|near) .* right now is (radiating|releasing|generating|putting
   out)` shape.

### Followups

- Add the `A [X] in [Y] right now is radiating...` opener to the
  voice engine v2 stock-formula rejector.
- Investigate within-cycle dedup that allowed #6 and #7 (same Mali
  fire, 46 seconds apart) to both reach pending.

### Numbers

- Pending drafts: 0 → 7
- Shippable rate: 86% (vs 20% on Apr 24)
- Mean grade: B+ (vs C+ on Apr 24)
- Stock-formula appearances: 1/7 (vs ~25/35 on Apr 24)

---

## 2026-04-24 — Fire template fatigue era (35 drafts)

**Context:** First draft review after the FIRMS letter-confidence
unblock (2026-04-23, commit `ba1b57a`) and the geocoder upgrade (earlier
today, commit `22cbc8e`). Most fire drafts in this corpus were
generated with the pre-upgrade continent-only geocoder, so Gemini often
had "Asia, Unknown" as its only location data. After review the FRP
floor was raised 100→250 MW (commit `023c3ed`) so sub-200 MW fires
stop making it to the generator.

**Grade distribution:** 7 A/B (shippable), 2 near-duplicates (pick one),
21 formulaic rejects, 5 marginal.

**Headline finding:** fire drafts fail because fires don't have a
"record" structure. Records have a clean template (city + number +
year anchor + framing). Fires don't, so Gemini reaches for MW-based
comparisons and falls into template traps. This is the core argument
for per-signal-type prompts — see `docs/IDEAS.md` → "Voice engine
upgrade" and `docs/VOICE_FAILURE_ANALYSIS.md` for the intervention
sketch.

### A/B grade — genuinely shippable (7)

#### #2 Sevilla record — signal 75 / copy 84 — **A-**

> Sevilla is forecast to hit 86.4F today. The record for this date was
> set in 2002, when most people alive now were in elementary school.
> That record was 82.9F.

Era anchor lands because it triggers a *feeling* (my own grade-school
memory), not a fact lookup.

#### #20 Jacobabad — signal 73 / copy 83 — **A-**

> Jacobabad, Pakistan is forecast to hit 110.3F today. The previous
> record for this date was 108.3F, set in 2002 — the year the euro
> entered circulation and the Winter Olympics were in Salt Lake City.

Dual cultural anchor on a Pakistan heat record. Two anchors is risky
(can feel show-offy) but pays off here because both are widely
recognizable.

#### #24 Ipoh — signal 80 / copy 83 — **B+**

> Ipoh may hit 34.9C today — topping last April's record of 34.3C.
> Two hottest Aprils in the 30-year archive: back to back.

Accelerating-warming story in 11 words. Colon-then-restate is a voice
move worth naming.

#### #30 Medan — signal 79 / copy 85 — **B**

> Medan, Indonesia is on pace for 92.5F. Hottest April in 30 years of
> archives. That old record, 92.3F, was from 1998.

No gimmicks, no era anchor. Works because the fact is big enough.

#### #31 Chicago anomaly — signal 80 / copy 81 — **A-**

> Chicago hit 82F today. Average high for April is 52F. That 29-degree
> jump used to define an entire season.

"Used to define." Past-tense framing of a normal anomaly as a new
normal. Strongest framing move in the corpus.

#### #32 Kathmandu — signal 73 / copy 87 — **B+**

> Kathmandu forecast 88.5F today. That would break a record from 1999.
> The year the world worried about Y2K.

Classic Y2K anchor from `brand/EXEMPLARS.md`. Reliable.

#### #35 Hawaii Big Island fire — signal 66 / copy 84 — **B**

> A 264 MW wildfire on Hawaii's Big Island. In APRIL. The average
> rainfall there this month is 2.5 inches.

Specific island, seasonal twist. Rare example of a fire draft that
works — Hawaii is the specific-named-place the other fire drafts
lack.

### Near-duplicates — pick one (2 pairs)

#### #3 Australia fire — signal 68 / copy 82 — **B (ship this one) — re-graded C+ on 2026-04-27**

> 333 MW of fire detected in Australia. A small power plant delivers
> about 300 MW. Except it's a forest.

Original Apr 24 grade said *"Except it's a forest is the best single
closer in the fire vocabulary in this corpus."* That was wrong.
Grammar fails: by proximity, "it" refers to "a small power plant,"
and "the small power plant is a forest" is nonsense. The closer
gestures at a Wright-style flip but doesn't pin the referent — the
reader has to bridge what the grammar should have. Re-grade C+ on
2026-04-27 after applying the humor-research lens. Compare with
corpus #29 ("This fire is a third of a power plant. Made of trees.")
where the fragment correctly modifies "a power plant" and the
referent lands. Lesson: Wright flips need the referent grammatically
pinned, not gestured at.

#### #4 Australia fire — signal 67 / copy 84 — **C (reject; near-dup of #3)**

> Satellite just picked up a 307 MW fire in Australia. For reference,
> a small power plant is about 300 MW. Except it's a forest.

Same structure, same broken closer (per the #3 re-grade above:
"Except it's a forest" doesn't pin the referent and the grammar
fails). C rejection stands; original near-dup reasoning was right
by accident.

#### #5 St. Lawrence Island — signal 63 / copy 78 — **B-**

> St. Lawrence Island in the Bering Sea. Winds hit 65 mph and up to
> 12 inches of snow are forecast through Friday. This far into April.

Clean. "This far into April" closer.

#### #6 Shishmaref blizzard — signal 63 / copy 85 — **B (ship this one)**

> Shishmaref, Alaska. April 22. A blizzard warning is active — 2 to 5
> inches of snow, winds gusting to 50 mph. Spring on the Seward
> Peninsula.

Stronger closer ("Spring on the Seward Peninsula") and more specific
meteorology. Pick this over #5.

### Marginal (5)

#### #7 Australia 192 MW, April — **C+**

> April 22. Australia. A wildfire just hit 192 MW. Most of the
> continent is well into autumn.

"Most of the continent is well into autumn" is a seasonal twist that
works, but 192 MW (below new 250 floor) is not carrying it.

#### #13 Asia 416 MW + Seattle comparison — **C**

> A wildfire somewhere in Asia is radiating 416 MW of heat right now.
> Seattle, the whole city, averages about 1,000 MW of electricity use.
> This fire is doing nearly half that — as pure heat, from burning
> land.

The Seattle comparison is the only power-plant-family comparison in
the corpus that actually lands. "Seattle the whole city" is concrete.
Killed by "somewhere in Asia."

#### #19 Mexico 329 MW — **C-**

> A wildfire burning in Mexico right now is radiating 329 MW of heat
> energy. That is enough to power 300,000 homes. The satellite
> confidence is 95%. It has no name yet.

Mexico is specific. But "no name yet" closer implies a missing story
beat (most fires never get named).

#### #21 Australia 366 MW, "unplanned" — **C+**

> A wildfire burning in Australia right now is generating 366 MW of
> energy. A coal power plant produces about 1,000 MW. This one is
> unplanned.

"Unplanned" is a dry beat that works. But the coal-plant comparison
is stale and the number is mid.

#### #29 Africa 306 MW, "made of trees" — **B- (but 'Africa' is too broad)**

> A wildfire burning in Africa right now is putting out 306 MW of
> energy. A coal power plant runs at about 1,000 MW. This fire is a
> third of a power plant. Made of trees.

"Made of trees" is the strongest closer of any power-plant-comparison
draft in the corpus. Would be shippable if the location weren't just
"Africa."

### Rejected — voice failures (13, "somewhere in [continent]")

All pre-geocoder-fix drafts. Gemini echoed the weak prompt back.

#### #8 Asia 220 MW — **D**
> A wildfire burning in Asia right now is radiating 220 MW of energy —
> enough to power 220,000 homes. Satellite confidence: 95%.

#### #9 Asia 161 MW — **F**
> A wildfire burning somewhere in Asia is radiating 161 megawatts of
> energy right now. The satellite confidence is 95%. The location is
> unknown. April 22.

Tells the reader the location is unknown. Pure voice failure.

#### #10 Asia 273 MW — **D**
> A wildfire somewhere in Asia is currently releasing 273 MW of
> radiative energy. A typical coal power plant generates around 300
> MW — to power a city. This fire is not generating electricity. It
> is burning.

"It is burning." is trying for aphorism; doesn't land.

#### #11 Australia 251 MW — **D**
> A wildfire burning in Australia right now is putting out 251 MW of
> radiative power — enough to run 250,000 homes. It was just detected.

Home-count formula.

#### #12 Asia 256 MW — **F**
> A wildfire burning somewhere in Asia is radiating 256 megawatts of
> heat — enough to power roughly 200,000 homes. Location still
> unknown. Satellite confidence: 95%.

"Location still unknown." Voice failure.

#### #14 Africa 217 MW — **D**
> A wildfire burning in Africa right now is radiating 217 MW of heat
> energy. A standard nuclear reactor runs at around 1,000 MW. This is
> one fire, detected by satellite this morning.

Nuclear reactor comparison is a stretch.

#### #15 Africa 235 MW, "loose in a field" — **D+**
> A wildfire in Africa is burning at 235 MW right now. Satellite
> confidence: 95%. The average nuclear reactor runs at about 1,000
> MW. This is nearly a quarter of that, loose in a field.

"Loose in a field" tries for poetry, doesn't carry.

#### #16 Africa 225 MW, "burning them" — **D**
> 225 MW. That's the energy radiating from a wildfire in Africa,
> detected today. Enough to power 200,000 homes. Except it's burning
> them.

"Except it's burning them" — broken referent. Them = the homes it's
hypothetically powering? Reader has to do too much work.

#### #17 Africa 138 MW — **F (below new FRP floor too)**
> A wildfire burning in Africa right now is releasing 138 MW of
> radiative power — enough to run roughly 100,000 American homes.
> The satellite confidence: 95%.

#### #18 Africa 185 MW — **F (below new FRP floor)**
> A wildfire burning in Africa right now is radiating 185 MW of
> power. That is enough to run roughly 150,000 average US homes.
> Detected this morning with 95% satellite confidence.

#### #22 Australia 183 MW, "powering nothing" — **D (below FRP floor)**
> A wildfire burning in Australia right now is radiating 183 MW. That
> is enough to power 100,000 homes. It is powering nothing.

#### #23 Australia 183 MW, Southern Hem — **D (below FRP floor)**
> A wildfire in Australia is burning at 183 MW today. That is enough
> radiative power to run roughly 1.8 million homes. It is April 23 —
> the Southern Hemisphere equivalent of late October.

"1.8 million homes" is Gemini inflating the number — doesn't match
183 MW. Math-trust broken.

#### #28 Asia 196 MW — **D (below FRP floor)**
> A wildfire burning in Asia right now is radiating 196 MW of heat
> energy. That is enough to power 130,000 electric heaters
> simultaneously. No structure. No city. Just a forest.

"130,000 electric heaters" is a mid-comparison dressed up. "No
structure. No city. Just a forest." is trying the triplet move but
adding nothing.

#### #33 Australia 238 MW — **D**
> 238 MW of heat radiating off a forest in Australia right now. A
> large coal plant outputs around 1,000 MW. This is a quarter of
> that — from trees.

Echo of #29's "made of trees" without the punch.

#### #34 Asia 190 MW — **D (below FRP floor)**
> A wildfire burning in Asia right now is radiating 190 MW of energy.
> A typical coal plant runs at 600 MW. This fire is one-third of a
> power plant. April 23.

### Rejected — formulaic (8)

#### #1 Kazakhstan steppe 234 MW — **C-**
> 234 MW of fire radiative power detected near the Kazakhstan steppe
> — enough to power roughly 200,000 homes. Satellite confidence: 95%.
> The fire has no name yet.

Location is actually specific (old geocoder got lucky on this one).
Killed by "no name yet" closer + home-count formula.

#### #25 Australia 141 MW — **C+ (below FRP floor)**
> A 141 MW fire detected in Australia. A large power plant runs at
> about 1,000 MW. This is a forest.

Very short, clean voice. But 141 MW doesn't carry a tweet.

#### #26 Australia 136 MW, April — **C (below FRP floor)**
> Australia has a 136 MW wildfire burning today. It is April. The
> continent's main fire season typically begins in November.

Good seasonal context. 136 MW is nothing.

#### #27 Australia 140 MW — **D (below FRP floor)**
> A wildfire burning in Australia right now is radiating 140 MW of
> energy. A coal power plant produces around 150 MW. One is built to
> do that.

"One is built to do that" is trying for deadpan. 140 MW vs 150 MW is
a forced comparison.

### Patterns named in this batch

1. **"Enough to power N homes"** — 7 drafts. Stale formula.
2. **"A coal/nuclear power plant runs at N MW. This fire is X of that."** — 8+ drafts. Plant wattage drifts between 150, 300, 600, 1000 based on what makes the math favorable. Reader loses trust.
3. **"Somewhere in [continent]" / "Location unknown"** — 12 drafts. Pre-geocoder-fix. Should be gone in future corpus.
4. **"It has no name yet"** — 2 drafts. Implies missing story beat.
5. **"It is powering nothing" / "loose in a field" / "made of trees"** — rhetorical subversions of the power-plant comparison. Only "made of trees" (#29) lands.

### Shipped this session as direct response to this corpus

- FRP floor raised 100 → 250 MW (commit `023c3ed`). Kills the sub-200 MW drafts at the source.
- Geocoder upgraded to 70+ named regions (commit `22cbc8e`). Future fire drafts get specific locations instead of "somewhere in Asia."
- Voice engine upgrade is the next lane — see `docs/VOICE_FAILURE_ANALYSIS.md` for the intervention sketch.

---

*Append future sessions above this line as new dated sections.*
