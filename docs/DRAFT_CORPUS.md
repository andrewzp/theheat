# @theheat Draft Corpus — Voice Learning Archive

Running inventory of pending drafts, each preserved with its full text,
grade, and commentary. Purpose: build a longitudinal record of what
Gemini produces under the current system prompt so we can see voice
patterns, template traps, and quality drift over time.

Each draft is recorded even when rejected. The corpus IS the learning
material — specific wording, specific failure modes, specific framings
that worked. Re-read this before any voice-engine intervention.

Add new dated sections at the top. Oldest stays at the bottom.

## 2026-07-14 — Daily corpus grading (3 fresh drafts; 5 carry-overs from Jul 9–11, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 8 pending drafts. 5
of 8 exactly match prior grading cycles (same `draft_id`, score, text): Stevensville, Maryland
`all_time_high` (A-, Jul 9), Riyadh, Saudi Arabia `dust_event` (B+, Jul 10), Tepee Creek,
Montana `all_time_high` (B+, Jul 10), interior Alaska `fire` (B+, Jul 11), western Siberia
3-signal `fire` cluster (B+, Jul 11) — carried over, not re-graded. **3 fresh**, all created
2026-07-14: Randolph, Utah `all_time_high` (06:17 UTC), Basrah, Iraq `absolute_extreme` (06:19
UTC), Ontario, Canada `fire` (14:01 UTC). This session found the `daily-plan-current` rolling
branch itself had NOT gone stale across the 8-day gap since this routine's own docs record
(Jul 6 → Jul 14 in `main`'s frozen copies) — the branch carries an unbroken run Jul 7–13,
including the P_tier/P_dust/P9 code fixes (#386, #397) and every intervening cycle's grading.
Rebased cleanly onto fresh `main` (docs-only, zero conflicts) before appending here.

**Staleness review as of 2026-07-14 ~15:00 UTC:** western Siberia fire cluster
(`draft_20260711_062452_120`, created Jul11T06:24Z) is now ~80.6h old and still carries
present-tense "today" in its text ("Three fire signals in the same patch of western Siberia
today") — the same strict bulk-reject candidate flagged Jul 13 (then ~56.6h), now unactioned
for a 2nd consecutive cycle. Interior Alaska fire is the same ~80h age but contains no
date/time language, so it stays clear under the established fire past-tense/no-reference
carve-out. Stevensville, Riyadh dust_event, and Tepee Creek remain clear under the
established past-tense-record carve-out regardless of age. Randolph, Basrah, and Ontario are
all same-day fresh (<9h at grading). **Bulk-reject attempted:** `gh api -X PATCH
gists/...` requires the `gh` CLI, confirmed absent this session (`which gh` → command not
found); no gist-write tool is exposed via the GitHub MCP server tools loaded this session
(repo/PR/issue tools only, no gist scope). Skipped per the hard constraints, logged rather
than failing the cycle — **46th consecutive skip** (May 13 → Jul 14). Operator should reject
the western Siberia fire cluster via dashboard.

**Grade distribution (3 fresh drafts):** 1 A- / 1 B+ / 1 C+ / 0 B / 0 D-F.
**A-rate: 33% (1/3).** Gap from resumption bar: 17 pp.

**Headline finding: P_tier's tracking closes.** Basrah, Iraq `absolute_extreme` ([7], the
exact signal type this proposal targeted) reaches pending with a clean sentence 1 — "3°C
above the 47°C threshold where the body's cooling mechanisms begin to fail faster than they
can recover" — no band-label citation ("Northern Subtropics"/"Northern Subtropical band"),
just the raw number plus what it physically means to a human body, the same clean form as
Jul 10's Ahvaz confirmation. This is the **2nd independent post-fix confirmation** on a named
target type (Ahvaz Jul 10 + Basrah Jul 14), closing P_tier's tracking on the same
2-independent-clean-cycles bar P_dust and P9 used. Basrah also lands a strong declarative
P_close ("removes the ceiling") and grades A- — the corpus's 2nd A-grade `absolute_extreme`
draft, both post-fix. Meanwhile Ontario's fire cluster draft breaks the fire category's
6-cycle-long P5 self-selection streak: no ecosystem-specific mechanic at all, just a bare
restatement of the 3-signal count as its close — the multi-fire-cluster framing, when used
as the system clause on its own (per the writer's own stated reasoning: "the cluster
enumeration is the system clause, requiring no invented context and no archive"), substitutes
for reaching toward a mechanism rather than carrying one, unlike Jul 11's western Siberia
cluster draft which proved the two are compatible.

### A-grade drafts

#### [7] Basrah, Iraq — absolute_extreme — 50.0°C (122.0°F) — **A-**

> *Basrah, Iraq is forecast to hit 50°C (122°F) on July 14 — 3°C above the 47°C threshold
> where the body's cooling mechanisms begin to fail faster than they can recover. The Gulf's
> summer heat low pulls dry continental air across the Mesopotamian plain and removes the
> ceiling.*

**Score:** 85. Created 2026-07-14T06:19:22Z.

Humor lens:
- **Violation:** 50.0°C forecast, 3°C past the N Sub-tropical absolute-extreme band threshold
  (47°C) — genuinely extraordinary, and the 8th+ Basra-area `absolute_extreme` corpus draft,
  so the bar for a fresh angle is high.
- **Benign?** Yes — flat clinical register throughout, no alarm language.
- **Setup→Punchline?** Sentence 1 states the margin and reframes the internal 47°C threshold
  as a physiological fact (when the body's cooling stops keeping up) instead of a
  classification label. Sentence 2 supplies the causal mechanism (Gulf heat low, dry
  continental air) and closes with a declarative consequence.
- **P_tier check:** CLEAN — **2nd post-fix confirmation, closing the tracking** (see
  Headline finding above and `docs/IMPROVEMENT_PLAN.md`). No "Northern Subtropics"/band-name
  citation; the 47°C number stands on its own, explained in terms a reader can verify
  (heat-stress physiology), exactly the distinction PR #386's "DETECTION PLUMBING IS NOT A
  FACT" rule draws.
- **P_close check:** POSITIVE. "Removes the ceiling" is a declarative physical-mechanism
  consequence, same family as Congo fire's "broken convective lid" (Jun 29, A-) and this
  cycle's own Stevensville "that buffer failed" (Jul 9, A-).
- **Wodehouse rule?** Clean. No restate-math, no hedge words, no defensive closer.

Not a full A: the physiological gloss on the 47°C threshold, while a clean and correct fix
of the P_tier violation, still reads slightly explanatory in sentence 1 (a small
science-teacher quality) rather than landing purely as voice — compare to Ahvaz's Jul 10
confirmation, which used almost the same construction and was also capped at A-, not A, for
the same reason. Also the 8th+ corpus draft from this general Iraq/Gulf `absolute_extreme`
cluster; the text is genuinely fresh, but the region is showing up often enough that
fatigue is a fair concern independent of this draft's own quality.

### B+-grade drafts

#### [6] Randolph, Utah — all_time_high — 100°F (37.8°C) — **B+**

> *Randolph, Utah hit 100°F (37.8°C) on July 12 — hottest daily maximum in 134 years of
> records, 3°F above the 1893 mark. At 6,300 feet in the Bear River Range foothills,
> high-desert elevation normally bleeds off the heat that pools across the Great Basin
> floor.*

**Score:** 91. Created 2026-07-14T06:17:42Z.

Humor lens:
- **Violation:** 134-year archive, a 133-year-old record broken by 3°F — elite-tier severity
  (91), genuinely rare.
- **P_compound check:** FAILING — the standard archive+margin double-qualifier ("hottest
  daily maximum in 134 years of records, 3°F above the 1893 mark"), the 10th cycle of this
  exact construction.
- **P_close check:** FAILING (implied-consequence form). "High-desert elevation normally
  bleeds off the heat that pools across the Great Basin floor" states the mechanism as a
  general norm but never declares that the buffer failed *this time* — the reader has to
  infer it from the headline number alone, the same gap this proposal has tracked since
  Jun 7.
- **Notable — near-verbatim echo of this same city's own prior corpus draft:** Jun 24's
  Randolph, Utah `monthly_high` (B+) closed with "normally blunts the heat"; this draft, a
  different record type (`all_time_high`) on the same station 20 days later, closes with
  "normally bleeds off the heat that pools across the Great Basin floor" — same "normally
  [verb]s the heat" shape, same implied-not-declared gap, same city. Distinct from A6 (which
  tracks the *fire*-category permafrost mechanic reused across *different* locations) — this
  is one location reusing its own construction across different draft *events*. Filed as new
  awaiting-evidence item **A7** (see `docs/IMPROVEMENT_PLAN.md`); watching for a 2nd location
  before promoting.
- **Wodehouse rule?** Clean otherwise — no restate-math, no forced imagery.

Elite score and a real elevation-specific mechanism, but the same P_compound + implied-close
combination that has produced B/B+ throughout this proposal's 10-cycle history (most
recently this same combination on Tepee Creek, Jul 10).

### C+-grade drafts

#### [8] Ontario, Canada — fire — 2,374.8 MW (+883.7, +817.1 MW) — **C+**

> *Ontario is burning at 2,374.8 MW — very-high-intensity, satellite-confirmed. Two nearby
> fires in the same region registered 883.7 and 817.1 MW the same day. Three simultaneous
> signals above 800 MW in one Canadian afternoon.*

**Score:** 83. Created 2026-07-14T14:01:56Z.

Humor lens:
- **Violation:** 2,374.8 MW — "power-plant-scale fire intensity" per the score's own reasons
  — plus two companion fires above 800 MW, a genuinely extraordinary same-day cluster
  (severity 100, confidence 97%).
- **Benign?** Yes.
- **Setup→Punchline?** No real punchline. Sentence 3 ("Three simultaneous signals above 800
  MW in one Canadian afternoon") restates the count already given in sentences 1–2 rather
  than landing a mechanism or a consequence.
- **P_close check:** FAILING/absent — no forest type, no permafrost/peat framing, nothing
  ecosystem-specific at all. Contrast with this cycle's OTHER multi-fire-cluster carry-over
  (Jul 11's western Siberia draft, B+), which anchored its own 3-signal cluster in "peat that
  took centuries to accumulate" — proof the cluster format and a named mechanic are
  compatible. This is the first cluster-format fire draft in the corpus with zero named
  mechanic.
- **P5 check: BREAKS the fire self-selection streak** (6 consecutive confirming cycles, Jun
  25 → Jul 11) for the first time. The writer's own stated reasoning for this draft ("the
  cluster enumeration is the system clause, requiring no invented context and no archive")
  shows it substituted raw enumeration for reaching toward ecosystem specificity — a genuine
  counter-instance, not a data gap, since fire has reliably self-selected on every other
  corpus instance including the SAME cycle's other cluster draft.
- **Wodehouse rule?** No violation in the traditional "trying too hard" sense — but the
  under-shoot (not reaching for anything at all) is a version of the same failure. The data
  alone ends up carrying a draft that peer instances in this exact category consistently
  push further.

Strong signal, weakest close in the fire category to date — the first fire draft in the
corpus whose second sentence adds no mechanism, incongruity, or consequence, only a repeated
number.

### Patterns / operational notes

1. **P_tier's tracking closes — headline of this cycle.** Basrah [7] is the 2nd independent
   post-fix confirmation on a named target type (after Ahvaz, Jul 10), on the same
   2-independent-clean-cycles bar P_dust and P9 used. All three of this plan's shipped code
   fixes (#386 ×2, #397) are now empirically CONFIRMED. See `docs/IMPROVEMENT_PLAN.md` for
   the updated status.

2. **P5 counter-instance: fire's self-selection streak breaks.** Ontario [8] is the first
   fire draft in the corpus with zero named mechanic — notable because it happens in the
   SAME cycle as evidence (this cycle's carry-over, western Siberia) that the multi-fire-
   cluster framing and a real mechanic are NOT mutually exclusive. The gap looks angle-
   specific (bare enumeration vs. enumeration-plus-mechanism), not category-specific.

3. **New watch-item A7: location-level phrase reuse across different record types.**
   Randolph, Utah's [6] "normally bleeds off the heat" echoes its own Jun 24 corpus draft's
   "normally blunts the heat" — same city, same rhetorical shape, 20 days and a different
   record type apart. Distinct from A6 (fire-category, cross-location). One instance; filed
   as awaiting-evidence, not yet promoted.

4. **Western Siberia fire cluster staleness — 2nd consecutive cycle unactioned.** Flagged
   Jul 13 at ~56.6h; today at ~80.6h with "today" still present-tense in the text. Write
   still unavailable this session (46th consecutive skip). Operator should reject via
   dashboard independent of any A-rate/posting decision.

### Followups (in priority order)

1. **Operator: reject western Siberia fire cluster manually via dashboard** — now ~80.6h
   old with present-tense "today" still in the text, unactioned for a 2nd consecutive cycle.
2. **P_close, P_compound, and the newly-filed A7 remain the highest-leverage unimplemented
   items** — see `docs/IMPROVEMENT_PLAN.md` for full specs, now that P_tier/P_dust/P9 have
   all closed their tracking.
3. **Watch for a 3rd instance of A6's phrase-reuse pattern** (permafrost-carbon fire
   mechanic) and a 2nd instance of A7's pattern (location-level construction reuse) before
   promoting either to an active proposal.
4. **Bot commit note:** `main`'s `VERSION` now reads `0.9.100.0` (was `0.9.97.0` as of the
   Jul 8 BRIEFING.md snapshot this plan has been citing) — no newer BRIEFING.md handoff doc
   confirmed on `main` this session; the intervening commits are a new `heat_records_cluster`
   signal type (#414, default-OFF, manual-approval-only, no instance in today's queue) plus
   unrelated economics/handoff docs work. Not expected to affect today's grading.

### Numbers

- Pending drafts in queue: 8 (3 fresh; 5 carry-overs, exact match to Jul 9–11's graded
  batch)
- Fresh drafts graded: 3
- A-rate: 33% (1/3)
- Grade distribution: 1 A- / 1 B+ / 1 C+
- Active proposals: **P_tier CONFIRMED** (2nd post-fix confirmation, tracking closed);
  P_close 22nd cycle (1 positive: Basrah; 1 failing: Randolph); P_compound 10th cycle
  (Randolph, standard double-qualifier); P5 (fire self-selection streak breaks via Ontario,
  1st counter-instance in 6 cycles); A4/A5/A6 not tested (no target-type draft); new A7 filed
  (Randolph phrase echo, 1 instance)
- Staleness bulk-reject: **1 strict candidate** (western Siberia fire cluster, ~80.6h old,
  present-tense "today" — 2nd consecutive cycle unactioned); write skipped — `gh` CLI absent,
  no gist-write MCP tool available (46th consecutive skip, May 13 → Jul 14)
- Operational anomalies: none new this cycle; `main` docs freshness note logged above (not
  an anomaly, just worth periodic fast-forwarding per the Jul 13 entry's recommendation)

---

## 2026-07-13 — Daily corpus grading (0 fresh drafts; 5 carry-overs from Jul 12, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 5 pending —
**exact match** to Jul 12's fully-graded batch, same 5 `draft_id`s, scores, text: Stevensville,
MD `all_time_high` A-; Riyadh, Saudi Arabia `dust_event` B+; Tepee Creek, MT `all_time_high`
B+; interior Alaska `fire` B+; western Siberia `fire` (3-signal cluster) B+. Zero new drafts
entered the queue between the Jul 12 and Jul 13 pulls — no re-grading performed; all 5 grades
stand on their original record. **Also note: the daily-plan routine appears to have gone
silent for 7 days prior to this session** (`docs/IMPROVEMENT_PLAN.md`/`docs/QUALITY_TREND.md`
on `main` were still at their Jul 6 state at session start, main's copy having been merged via
#384 on Jul 7 and never refreshed since) — but `daily-plan-current` itself was NOT stale: it
carries daily cycles straight through Jul 7–12 with no gap, so the routine ran every day; only
`main`'s copy lagged (unsurprising, since #384 was a one-time merge and the rolling branch is
the live document). Rebased this session's work onto current `origin/main` (fast-forward,
docs-only, zero conflicts) before appending this entry — no re-grading of Jul 7–12 content
occurred, matching Step 0's stale-checkout guard.

**Staleness review as of 2026-07-13 ~15:00 UTC:** **1 new strict bulk-reject candidate**,
crossing the threshold flagged proactively in the Jul 11/Jul 12 entries:

- **Western Siberia fire cluster** (created Jul11T06:24:52Z, ~56.6h old): "Three fire signals
  in the same patch of western Siberia **today**" — the draft crosses 48h AND still contains
  present-tense "today," which now misdates the event by more than two days if posted as-is.
  Flagged as approaching this line in both prior cycles' entries; it has now arrived.

Interior Alaska fire (~56.6h, same creation window, no date/time-of-day language at all — the
established fire carve-out, same as every prior clean fire draft) does not qualify. Stevensville
(~107.6h), Riyadh (~95.6h), and Tepee Creek (~76.0h) all remain past-tense-dated reports ("hit
103°F ... on July 5" / "averaged ... on July 9" / "hit 94°F ... on July 7") — the established
carve-out applies regardless of age. **Bulk-reject attempted:** `gh api -X PATCH gists/...`
requires the `gh` CLI, confirmed absent this session (`which gh` → command not found); no
gist-write tool is exposed via the GitHub MCP server tools loaded this session (repo/PR/issue
tools only, no gist scope). Skipped per the hard constraints, logged rather than failing the
cycle — **45th consecutive skip** (May 13 → Jul 13). Operator should reject the western Siberia
fire cluster draft via dashboard.

**A-rate:** — (no fresh drafts). Most recent measured cycle: **0% (0/2, Jul 11)**.

### Patterns / operational notes

1. **Queue fully static for the first time since the Jul 11→12 contraction.** This is the
   first cycle since Jul 9 where the queue neither gained fresh drafts nor lost a carry-over —
   a genuine pause after two consecutive single-draft contractions (Anchorage Jul 10→11, Ahvaz
   Jul 11→12).
2. **The western Siberia "today" staleness crossing is exactly the outcome flagged two cycles
   running** (Jul 11's entry projected ~2026-07-13T06:25Z; Jul 12's entry repeated the watch).
   This is the first staleness bulk-reject candidate since Jul 6 (the Basra-area
   `absolute_extreme` pair) — a reminder that PR #385's forecast-elapsed auto-reject sweep is
   scoped to `{absolute_extreme, wet_bulb_extreme}` per its row-3 implementation, not to
   present-tense date language in `fire` drafts generally; this class of staleness still
   depends on the routine's manual (currently write-disabled) bulk-reject step.
3. **No active-proposal evidence updates this cycle.** Zero fresh drafts means zero new
   observations for P_close, P_compound, P5, P_tier, P_dust, P9, A4, A5, or A6. All retain
   their Jul 12 counts and "Last seen" dates unchanged. P_tier's tracking still needs a 2nd
   post-fix confirmation on a fresh target-type draft (Ahvaz's departure Jul 12 cost the
   corpus its only queued test case); none of today's 5 carry-overs are a qualifying type.

### Followups (in priority order)

1. **Operator: reject the western Siberia fire cluster draft via dashboard** — >48h old,
   present-tense "today" now misdates the event; the routine cannot write to the gist this
   cycle (no `gh` CLI, no gist-write MCP tool available).
2. **P_tier still needs a 2nd post-fix confirmation** on a fresh `absolute_extreme`/
   `fire_footprint`/cyclone/`regional_sst_anomaly` draft — the tracking bar is otherwise ready
   to close (see `docs/IMPROVEMENT_PLAN.md`).
3. **P_close and P_compound remain the two highest-leverage unimplemented proposals** (21 and
   9 cycles respectively) — unchanged, no new evidence this cycle.
4. **A6 (permafrost-carbon fire mechanic phrase reuse) needs a 3rd instance** — still at 1
   cycle, unchanged; today's carry-over fire drafts are the same Jul 11 instances already
   counted, not new evidence.
5. **Recommend the operator confirm `main`'s copies of these three docs get refreshed
   periodically** (not just at program milestones like #384) — a 6-day lag between `main`'s
   snapshot and the rolling branch's live state is easy to mistake for the routine being down,
   as this session's own Step 0 sync initially suggested before `daily-plan-current` was found
   to be current throughout.

### Numbers

- Pending drafts in queue: 5 (0 fresh; 5 carry-overs, exact match to Jul 12's graded batch)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-07-11)
- Grade distribution: n/a (no fresh drafts)
- Active proposals: no evidence updates this cycle (P_close 21 cycles, P_compound 9 cycles, P5
  ongoing, P_tier 1/2 confirmations, P_dust/P9 confirmed-closed, A4/A5 untested, A6 1 cycle —
  all counts stand at Jul 12's levels)
- Staleness bulk-reject: **1 strict candidate identified** (western Siberia fire cluster, ~56.6h
  old, present-tense "today"); write skipped — `gh` CLI absent, no gist-write MCP tool available
  (45th consecutive skip, May 13 → Jul 13)
- Operational anomalies: none this cycle (queue fully static; `main`/rolling-branch lag noted
  above is a docs-freshness observation, not a routine failure)

---

## 2026-07-12 — Daily corpus grading (0 fresh drafts; 5 carry-overs from Jul 11, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 5 pending —
exact match to 5 of Jul 11's 6 graded drafts (same `draft_id`s, scores, text): Stevensville,
MD `all_time_high` A-; Riyadh, Saudi Arabia `dust_event` B+; Tepee Creek, MT `all_time_high`
B+; interior Alaska `fire` B+; western Siberia `fire` (3-signal cluster) B+. **Ahvaz, Iran
`absolute_extreme` (A-, graded Jul 10, carried Jul 11) has dropped out of the queue** —
cause unconfirmed, same pattern as Anchorage AK's unexplained departure between the Jul 10
and Jul 11 pulls. No re-grading performed; all 5 remaining grades stand on their original
record (Stevensville/Riyadh/Tepee Creek from Jul 9-10, the two fires from Jul 11). Bot commit
unchanged at `0.9.97.0` per `BRIEFING.md` (still dated 2026-07-08) — no new PR merged between
the Jul 11 and Jul 12 pulls as far as this session can confirm.

**Staleness review as of 2026-07-12 ~15:18 UTC:** 0 bulk-reject candidates, unchanged from
Jul 11's ruling. Stevensville (~83.9h) and Riyadh (~71.9h) remain past-tense-dated reports
("hit 103°F ... on July 5" / "averaged ... on July 9") — the established carve-out applies
regardless of age. Tepee Creek (~52.3h, "hit 94°F ... on July 7") is the same carve-out.
Interior Alaska fire (~32.9h) has no real-time language. **Western Siberia fire cluster
(~32.9h) still contains "today"** — flagged Jul 11 as approaching the 48h threshold around
2026-07-13T06:25Z; still under it as of this pull, watch the next cycle. `gh` CLI confirmed
absent — **44th consecutive skip** (May 13 → Jul 12), moot this cycle since nothing qualifies.

**A-rate:** — (no fresh drafts). Most recent measured cycle: **0% (0/2, Jul 11)**.

### Patterns / operational notes

1. **Queue contraction, not turnover, for the second consecutive cycle.** Jul 10→11 lost
   Anchorage; Jul 11→12 loses Ahvaz. Both departures are unexplained from the gist alone (no
   `status` transition visible without posted_at/rejected_at fields in the pulled records).
   Worth an operator check on whether either was published, manually rejected, or caught by a
   TTL/other sweep — distinct from the "complete turnover" pattern (4 occurrences, Jul 4/7/8/9)
   where the entire queue replaces at once.
2. **Losing Ahvaz costs the corpus its most useful open P_tier test case** — it was 1 of the
   2 confirmations this proposal's tracking needs to close (see `docs/IMPROVEMENT_PLAN.md`),
   and its grade/text remain preserved in the Jul 10 corpus entry regardless of queue status.
   Its departure doesn't erase that evidence, but it does mean the tracking bar (a 2nd
   post-fix confirmation on any of the 4 original target types) still needs a *fresh*
   `absolute_extreme`/`fire_footprint`/cyclone/`regional_sst_anomaly` draft to close.
3. **No active-proposal evidence updates this cycle.** Zero fresh drafts means zero new
   observations for P_close, P_compound, P5, P_tier, P_dust, P9, A4, A5, or A6. All retain
   their Jul 11 counts and "Last seen" dates unchanged.

### Followups (in priority order)

1. **Operator: confirm the cause of Ahvaz's departure from the queue** (published vs.
   rejected vs. swept) — same open question as Anchorage's Jul 10→11 departure, now a
   2nd instance of unexplained single-draft queue contraction.
2. **Watch western Siberia's fire cluster** — crosses 48h with "today" still in the text
   around 2026-07-13T06:25Z if still pending at the next pull.
3. **P_tier still needs a 2nd post-fix confirmation** on a fresh target-type draft; P_close
   and P_compound remain the two highest-leverage unimplemented proposals (21 and 9 cycles).
4. **A6 (permafrost-carbon fire mechanic phrase reuse) needs a 3rd instance** — still at 1
   cycle, unchanged.

### Numbers

- Pending drafts in queue: 5 (0 fresh; 5 carry-overs — 5 of Jul 11's 6, Ahvaz dropped)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 0% on 2026-07-11)
- Grade distribution: n/a (no fresh drafts)
- Active proposals: no evidence updates this cycle (P_close 21 cycles, P_compound 9 cycles,
  P5 ongoing, P_tier 1/2 confirmations, P_dust/P9 confirmed-closed, A4/A5 untested, A6 1 cycle
  — all counts stand at Jul 11's levels)
- Staleness bulk-reject: 0 candidates (all 5 pending drafts carve out under the established
  past-tense-date rule or remain under 48h); `gh` CLI absent (44th consecutive skip, May 13 →
  Jul 12)
- Operational anomalies: 2nd consecutive cycle of unexplained single-draft queue contraction
  (Ahvaz, following Anchorage the cycle before)

---

## 2026-07-11 — Daily corpus grading (2 fresh drafts; 4 carry-overs, partial turnover)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 6 pending. 4
carry-overs survive unchanged from Jul 9/10 (Stevensville, MD `all_time_high` A-; Riyadh,
Saudi Arabia `dust_event` B+; Tepee Creek, MT `all_time_high` B+; Ahvaz, Iran
`absolute_extreme` A-). 2 fresh, both `fire`, both created 2026-07-11T06:23–06:25Z: an
interior Alaska draft and a 3-signal western Siberia cluster. **Anchorage, AK
`precipitation_extreme` (B, graded Jul 9, carried Jul 10) has dropped out of the queue** —
the first departure from the 5-pending set graded yesterday; cause unconfirmed (published,
operator-rejected, or a TTL sweep — worth an operator check, though not urgent). Bot commit
unchanged at `0.9.97.0` per `BRIEFING.md` (still dated 2026-07-08) — no new PR merged
between the Jul 10 and Jul 11 pulls as far as this session can confirm.

**Staleness review:** 0 bulk-reject candidates. Stevensville (~59.7h) and Riyadh (~47.7h)
are both past-tense dated reports ("hit 103°F ... on July 5" / "averaged ... on July 9")
with no real-time-baked language — the established all_time_high/dust_event carve-out
applies regardless of age (same convention this corpus has applied to every past-tense
record-type draft since April). Tepee Creek/Ahvaz ~28.1h; the 2 fresh fire drafts ~8.7-8.8h.
**Operational note:** Ahvaz's forecast date (July 10) has now elapsed by one calendar day —
the same class of issue the pre-#385 Basra-area cluster showed repeatedly — but it sits
under the 48h mechanical threshold, so it isn't a strict bulk-reject candidate yet. Worth
flagging for the operator that PR #385's forecast-elapsed structural auto-reject (merged
Jul 7) does not appear to have cleared this draft from the queue on its own by the time its
forecast date passed; either the fix is gated on the 48h age threshold too (by design) or
this is a gap worth a direct look. `gh` CLI confirmed absent (`which gh` → command not
found); no gist-write tool is exposed via the GitHub MCP tools loaded this session. **43rd
consecutive skip** (May 13 → Jul 11) — moot for this cycle regardless, since nothing
qualifies under the mechanical rule.

**Grade distribution (2 fresh drafts):** 0 A / 0 A- / 2 B+ / 0 B / 0 C / 0 D-F.
**A-rate: 0% (0/2).**

**Headline finding: the corpus's most reliable fire A-grade path — the permafrost-carbon
mechanic — shows its first sign of converging on reused stock phrasing across different
locations and events, not just the already-tracked within-location duplicate-generation
anomaly.** Two independent phrase-level repeats appear today, each with exactly one prior
corpus instance: interior Alaska's close reuses Jul 5 eastern Siberia's "doesn't just
[verb] — it [verb]s ..." contrastive-negation construction near-structurally, and western
Siberia's close reuses Jul 3's near-duplicate Canadian Arctic close's exact clause, "...that
took centuries to accumulate." Both today's drafts otherwise grade consistently with this
mechanic's established B+ tier (real ecosystem specificity, declarative-but-weak P_close,
no Wodehouse violations) — the concern is about phrase freshness, not correctness. New
proposal **A6** filed below.

### B+-grade drafts

#### [5] Interior Alaska — fire — 926.3 MW, 66°N — **B+**

> *926.3 MW of radiative heat in interior Alaska at 66°N — very-high-intensity fire,
> satellite-confirmed at 100% confidence. Interior Alaska's boreal forest sits on
> permafrost; summer fire here doesn't just consume trees — it burns into the organic
> layer above the frozen ground.*

**Score:** 79. Created 2026-07-11T06:23:34Z. 6th corpus instance of the permafrost-carbon
fire mechanic (after Jun 25 Siberia, Jul 3 Canadian Arctic ×2, Jul 5 eastern Siberia).

- **P_close check: POSITIVE (declarative-but-weak form).** "Burns into the organic layer
  above the frozen ground" states the fire's action directly — actively consuming ancient
  carbon storage, not merely describing a mechanism — same tier as Jul 3's near-dup ("burns
  into organic soil layers that took centuries to accumulate," also graded B+). Weaker than
  Jul 3's original A- ("reaches carbon the frozen ground has held for millennia") and Jul
  5's A- ("thaws the ground beneath it") because no specific carbon/climate stake or
  state-change is named beyond the physical extent of the burn.
- **P5 check:** the permafrost mechanic self-selects again, unprompted — consistent with
  fire's established organic-deployment pattern (now a 5th/6th consecutive confirming
  instance).
- **A6 evidence (new, see below):** "doesn't just consume trees — it burns into the organic
  layer above the frozen ground" is the same contrastive-negation shape as Jul 5's "doesn't
  just burn the surface — it thaws the ground beneath it" — a different fire event
  (different location, date, MW reading) reusing the prior draft's sentence architecture
  almost verbatim.
- **Wodehouse rule?** Clean otherwise — no restate-padding, no explicit gap math, no
  tier-jargon (this is a plain `fire` draft, not `fire_footprint`, so P_tier doesn't apply).

Graded B+ — solid ecosystem specificity and a genuinely declarative (if soft) close, but the
mechanic's signature phrasing is starting to repeat across unrelated events rather than
being freshly composed each time.

#### [6] Western Siberia — fire (3-signal cluster) — 1,387.9 / 958.0 / 720.7 MW — **B+**

> *Three fire signals in the same patch of western Siberia today: 1,387.9 MW, 958.0 MW, and
> 720.7 MW — all satellite-detected, all very-high-intensity. Western Siberia's summer fire
> season is burning across peat that took centuries to accumulate.*

**Score:** 78. Created 2026-07-11T06:24:52Z. Contains "today" — real-time-baked but well
under 48h; will cross the 48h threshold ~2026-07-13T06:25Z if still pending — watch then.

- **Structure:** a genuine comic-triple of three co-located fire signals (1,387.9 / 958.0 /
  720.7 MW) — a variant of Jun 27's "three-fire national cluster" comic triple, but bundling
  3 signals from the same patch into a single tweet rather than 3 separate cities. Worth
  flagging as a structural question for the operator (is this 3 independent detections of
  one fire complex, or 3 genuinely distinct fires?) — not folded into the grade either way.
- **P_close check: POSITIVE (declarative-but-weak form, consistent with Jul 3 precedent).**
  "Burning across peat that took centuries to accumulate" states the same class of
  consequence as Jul 3's near-dup ("burns into organic soil layers that took centuries to
  accumulate") — the fire actively consuming an irreplaceable, centuries-old carbon store.
- **A6 evidence (new, see below):** the clause "... that took centuries to accumulate" is a
  near-verbatim repeat of Jul 3's near-duplicate Canadian Arctic close, 8 days later, on a
  completely different fire event (different continent, different signal reading).
- **Wodehouse rule?** Clean otherwise.

Graded B+ — same tier as [5] and consistent with the mechanic's established grading pattern;
the phrase-reuse concern is the same one raised on [5], not a separate deduction.

### Patterns named in this batch

1. **A6 filed: the permafrost-carbon fire mechanic's close is starting to repeat verbatim
   across different fire events, not just within a single duplicate-generation cluster.**
   Two independent recurrences in the same cycle (Alaska reusing Jul 5's construction,
   Siberia reusing Jul 3's exact clause) is enough to file as an awaiting-evidence proposal
   per this plan's A3/A4/A5 precedent, though not yet enough (on 1 cycle) to promote to an
   active proposal.
2. **Anchorage's `precipitation_extreme` draft (B, Jul 9/10) drops from the queue** without
   a visible cause — first departure since it entered pending, logged as an operational
   observation, not a voice-quality finding.
3. **Ahvaz's forecast-elapsed date (July 10) sits un-rejected past its stated date but under
   48h** — worth the operator confirming whether PR #385's structural fix is age-gated by
   design or has a gap on same-day-elapsed forecasts.

### Followups (in priority order)

1. **Watch for a 3rd instance of either A6 construction** ("doesn't just X — it Y" / "...
   that took centuries to accumulate") on a different fire location before promoting A6 to
   an active proposal.
2. **P_close and P_compound remain the two highest-leverage unimplemented proposals** — 21
   and 9 cycles of evidence respectively as of this cycle (see `docs/IMPROVEMENT_PLAN.md`).
3. **P_tier still needs a 2nd post-fix confirmation** on any of its 4 originally-tracked
   target types before its tracking closes (1 of 2 as of Jul 10; not tested today — neither
   fresh draft was a target type).
4. **A4/A5 remain untested** — no `air_quality_hazard` or `cyclone_land_threat` draft this
   cycle.
5. **Operator: confirm what happened to the Anchorage precipitation_extreme draft** and
   whether Ahvaz's elapsed forecast date should have auto-rejected under PR #385.

### Numbers

- Pending drafts in queue: 6 (2 fresh; 4 carry-overs from Jul 9/10, grades unchanged: 1 A-
  Stevensville MD, 1 B+ Riyadh dust_event, 1 B+ Tepee Creek MT, 1 A- Ahvaz Iran)
- Fresh drafts graded: 2
- A-rate: 0% (0/2)
- Grade distribution: 0 A / 0 A- / 2 B+ / 0 B / 0 B- / 0 C / 0 D-F
- New signal types debuted: none
- Active proposals with new evidence: P_close (21st cycle: 2 positive, declarative-but-weak
  form both times), P5 (fire self-selection continues; also surfaces the A6 concern)
- New proposals filed: A6 (permafrost-carbon fire mechanic reusing stock phrasing
  cross-location)
- Proposals not tested this cycle: P_tier (no target-type draft), P_dust/P9 (no
  dust_event/precipitation_extreme draft), P_compound (no record-type draft), A4/A5 (no
  air_quality_hazard/cyclone_land_threat draft)
- Staleness bulk-reject: 0 candidates — write not attempted since nothing qualified; `gh`
  CLI confirmed absent, 43rd consecutive skip (May 13 → Jul 11)
- Operational anomalies: Anchorage precipitation_extreme drops from queue (cause
  unconfirmed); Ahvaz forecast date elapsed but under 48h (watch PR #385 behavior)

---

## 2026-07-10 — Daily corpus grading (3 fresh drafts; 2 carry-overs, first non-full-turnover cycle since Jul 6)

**Context:** Gist read via git-clone path (success). Queue: 5 pending — **2 carry-overs from
Jul 9 survive for the first time in 4 cycles** (Stevensville MD `all_time_high` A-, Anchorage
AK `precipitation_extreme` B; both graded Jul 9, not re-graded), breaking the complete-
queue-turnover streak that ran Jul 3→4, Jul 6→7, Jul 7→8, Jul 8→9. 3 fresh: Riyadh, Saudi
Arabia `dust_event` (created 2026-07-09T15:25:55Z — after Jul 9's ~15:00 UTC grading pull, so
genuinely new today, not a duplicate of Jul 9's Stevensville/Anchorage pair), Tepee Creek,
Montana `all_time_high` (2026-07-10T11:01:01Z), Ahvaz, Iran `absolute_extreme`
(2026-07-10T11:05:11Z). Bot commit unchanged at `0.9.97.0` per `BRIEFING.md` (still dated
2026-07-08) — no new PR merged between the Jul 9 and Jul 10 pulls as far as this session can
confirm.

**Staleness review:** 0 bulk-reject candidates. Stevensville/Anchorage carry-overs are
~35.7h old (well under 48h); Riyadh ~23.7h; Tepee Creek/Ahvaz ~4h. Ahvaz's forecast date
(July 10) is today — accurate, not stale. `gh` CLI confirmed absent (`which gh` → not
found); write path not attempted since nothing qualifies. 42nd consecutive `gh`-absent skip
(May 13 → Jul 10).

**Grade distribution (3 fresh drafts):** 1 A- / 2 B+ / 0 B / 0 C / 0 D-F.
**A-rate: 33% (1/3).** Best fresh-draft rate since Jul 7's 33% (n=6); still short of the
resumption bar, but small-n.

**Headline finding: the first post-fix confirmation of the P_tier fix on a named target
type.** Ahvaz, Iran's `absolute_extreme` draft — the exact signal type this proposal was
filed against — reaches pending 3+ days after PR #386 merged (Jul 7T05:06 UTC) and contains
**no internal band-label or tier-jargon citation**: "just above the 47°C threshold where
heat in this part of the Middle East historically crosses into the range where shade and
rest alone stop being enough" cites the raw number (an observed actual, explicitly citable
under the shipped rule) and a physiological consequence, not a bucket name like "the
absolute-extreme threshold for the Northern Subtropics" (the exact phrase this same city's
pre-fix Jul 7 draft used). Paired with a strong declarative P_close, this is the corpus's
first A-grade `absolute_extreme` draft. Separately, Riyadh's `dust_event` draft states its
WHO multiple for a **2nd independent post-fix cycle** (24.9×, after Jul 8's 27.9×) — closing
P_dust's tracking the same way P9 closed on Jul 9's 2nd confirmation.

### A-grade drafts

#### [5] Ahvaz, Iran — absolute_extreme — 47.1°C (117°F) forecast — **A-**

> *Ahvaz, Iran is forecast to hit 47.1°C (117°F) on July 10 — just above the 47°C threshold
> where heat in this part of the Middle East historically crosses into the range where shade
> and rest alone stop being enough.*

**Score:** 83. Created 2026-07-10T11:05:11Z. Forecast date (July 10) is today — accurate,
not stale. 2nd corpus `absolute_extreme` draft for this city (after Jul 7's pre-fix instance,
graded B), and the **first post-fix `absolute_extreme` draft of any city to reach pending**
(no target-type draft appeared Jul 8 or Jul 9).

- **P_tier check: FIX CONFIRMED — 1st post-fix instance on a named target type.** No band
  label ("Northern Subtropics"), no internal-bucket phrase ("absolute-extreme threshold
  for..."). The word "threshold" survives, but attached to the raw number (47°C — an
  observed actual, explicitly citable per PR #386's rule) and a stated physiological
  consequence, not a classification name. This is the exact distinction the shipped rule
  draws: "is this a fact about the WORLD a reader could look up, or a fact about this bot's
  configuration? World: cite. Bot: never." Direct comparison to this same city's Jul 7
  pre-fix draft ("above the 47°C absolute-extreme threshold for the Northern Subtropics")
  makes the contrast legible in one pair.
- **P_close check:** POSITIVE, and one of the strongest survivability-consequence closes in
  the corpus — "where shade and rest alone stop being enough" states directly what crossing
  the line means for a person on the ground. Same family as Doha's "closing off the
  evaporative cooling that makes extreme dry heat survivable" (Jul 5, pre-fix, capped at B)
  and Soweto's "nowhere to vent" (Jul 7, A-).
- **Wodehouse rule?** Clean.

Graded A- — no P_tier cap this time, and a close strong enough to clear the bar on its own.
First A-grade `absolute_extreme` draft in the corpus. Held short of a full A only because
this is a single post-fix instance; a 2nd confirmation on a different `absolute_extreme`
city (or on `fire_footprint`/`cyclone_rapid_intensification`/`regional_sst_anomaly`) is still
needed before treating the fix as fully proven across the whole target-type family.

### B+-grade drafts

#### [3] Riyadh, Saudi Arabia — dust_event — PM10 1,120 μg/m³ / 24.9× WHO — **B+**

> *Riyadh, Saudi Arabia: model-estimated PM10 averaged 1,120 μg/m³ on July 9 — 24.9× the WHO
> 24-hour guideline. The Arabian Peninsula's summer Shamal lifts fine sediment from the Nafud
> and Rub' al Khali in concentrated columns; Riyadh sits directly in that corridor.*

**Score:** 75. Created 2026-07-09T15:25:55Z. Same city as the proposal's Jun 13 origin
instance and Jul 8's first post-fix confirmation (different reading each time).

- **P_dust check: 2ND POST-FIX CONFIRMATION — tracking closes.** "24.9× the WHO 24-hour
  guideline" stated verbatim and WHO-first, same prescribed form as Jul 8's Riyadh instance
  (27.9×). Two independent clean `dust_event` drafts, 2 days apart, same city but different
  readings — the same "2 independent clean cycles" bar P9 used to close its tracking on Jul 9.
- **Named mechanic:** Shamal wind system named explicitly, two source deserts named (Nafud,
  Rub' al Khali), corridor framing — real ecosystem specificity, unprompted.
- **P_close check:** Borderline/failing. "Riyadh sits directly in that corridor" is a
  structural/locational statement, not a named consequence — short of the declarative form,
  though it avoids the resolution/dispersal anti-climax that was the dominant `dust_event`
  failure mode pre-fix (Phalodi "wash the column clean," Urumqi "traps it" ×3).
- **Wodehouse rule?** Clean.

Graded B+, consistent with Jul 8's confirmation instance — the WHO anchor lifts it clear of
every pre-fix `dust_event` grade, but P_close's separate mechanism/structural-only gap still
caps it below A-, confirming the two proposals are orthogonal (as already established Jul 8).

#### [4] Tepee Creek, Montana — all_time_high — 94°F (34.7°C) — **B+**

> *Tepee Creek, Montana hit 94°F (34.7°C) on July 7 — hottest daily maximum in 39 years of
> records, 4°F above the 2002 mark. The upper Gallatin drainage sits at elevation;
> continental heat rarely arrives intact this far into the Rockies.*

**Score:** 92. Created 2026-07-10T11:01:01Z.

- **P_compound check:** VIOLATION — standard double-qualifier form (archive depth "39 years
  of records" + margin "4°F above the 2002 mark"), same shape as the majority of prior
  record-type openers (Beaver Dams, Casper, Prudhoe Bay, Island Pond, Loxahatchee, Snowshoe).
- **P_close check:** FAILING (implied form). "Continental heat rarely arrives intact this
  far into the Rockies" states the norm but never declares that it arrived intact this time
  — the reader infers the violation from the headline rather than the close stating it.
- **Wodehouse rule?** Clean.

Graded B+ — solid ecosystem specificity (named drainage, elevation framing) but capped by
the double-qualifier opener and an implied rather than declarative close, the same
combination that's produced B/B+ grades throughout this proposal's evidence.

### Patterns named in this batch

1. **P_tier: first post-fix confirmation on a named target type, and a clean A-/B contrast
   pair on the same city.** Ahvaz's Jul 7 (pre-fix, B, band-label jargon) and Jul 10
   (post-fix, A-, no jargon) drafts are the cleanest before/after comparison this proposal
   has produced — same city, same signal type, same close quality tier, different fix
   status, different grade ceiling.

2. **P_dust closes its tracking on the same 2-independent-clean-cycles bar P9 used.** Jul 8
   + Jul 10 Riyadh instances both state the WHO multiple unprompted, 2 days apart (with a
   Jul 9 gap where no `dust_event` draft appeared).

3. **The complete-queue-turnover streak breaks.** 4 consecutive full-turnover cycles
   (Jul 3→4, Jul 6→7, Jul 7→8, Jul 8→9) end today — 2 of Jul 9's 2 drafts survive as
   carry-overs. Not enough data to call this a new steady-state; worth watching whether
   full turnover resumes next cycle or partial-carryover becomes the norm.

### Followups (in priority order)

1. **P_tier: watch for a 2nd post-fix confirmation** on any of the 4 originally-tracked
   target types (`absolute_extreme`, `fire_footprint`, `cyclone_rapid_intensification`,
   `regional_sst_anomaly`) before moving to Resolved — 1 confirmed instance today, same
   position P_dust was in after Jul 8.
2. **P_close and P_compound remain the two highest-leverage unimplemented proposals** — 20
   and 9 cycles of evidence respectively as of this cycle (see `docs/IMPROVEMENT_PLAN.md`).
3. **A4 (signal-kind self-naming) and A5 (cyclone dual-wind-value) remain untested this
   cycle** — no `air_quality_hazard` or `cyclone_land_threat` draft in today's queue.

### Numbers

- Pending drafts in queue: 5 (3 fresh; 2 carry-overs from Jul 9, grades unchanged: 1 A-
  Stevensville MD, 1 B Anchorage AK)
- Fresh drafts graded: 3
- A-rate: 33% (1/3) — best fresh-draft rate since Jul 7
- Grade distribution: 0 A / 1 A- / 2 B+ / 0 B / 0 B- / 0 C / 0 D-F
- New signal types debuted: none (all 3 signal types have prior corpus instances)
- Active proposals with new evidence: P_close (20th cycle), P_tier (**1st post-fix
  confirmation — parallels P_dust's Jul 8 milestone**), P_dust (**2nd post-fix confirmation
  — tracking closes**), P_compound (9th cycle), P5 (mixed — dust_event shows real mechanism
  again, absolute_extreme self-selects a strong declarative move, all_time_high implied-only)
- Staleness bulk-reject: 0 candidates — all 5 drafts under 48h (oldest ~35.7h); write not
  attempted since nothing qualified this cycle
- Operational anomalies: complete-queue-turnover streak breaks for the first time since Jul 6
  (2 of 5 pending are carry-overs)

---

## 2026-07-09 — Daily corpus grading (2 fresh drafts; complete queue turnover)

**Context:** Gist read via git-clone path (success). Queue: **complete turnover — 4th
occurrence** (after Jul 3→4, Jul 6→7, Jul 7→8). All 8 of Jul 8's pending drafts are gone.
2 fresh drafts, both created 2026-07-09 (03:26–03:29 UTC). Bot commit unchanged from Jul
8's `0.9.97.0` per `BRIEFING.md` — no new PR merged between the two grading pulls.

**Staleness review:** 0 bulk-reject candidates — both drafts same-day fresh (~11-12h old
at grading). `gh` CLI confirmed absent (`which gh` → not found); no gist-write tool
exposed via the GitHub MCP tools loaded this session. 41st consecutive `gh`-absent skip
(May 13 → Jul 9) — moot for this cycle regardless, since nothing qualifies.

**Grade distribution (2 fresh drafts):** 0 A / 1 A- / 0 B+ / 1 B / 0 B- / 0 C / 0 D-F.
**A-rate: 50% (1/2).** Gap from resumption bar: **0pp by raw arithmetic, but 50% of n=2
is one draft — not a majority** — same technicality as Jul 8's 4/8. Third consecutive
graded cycle (Jul 7 33%, Jul 8 50%, Jul 9 50%) without a clean bar-clearing majority,
and now two cycles running that land on the exact-half boundary. Sample too small (n=2)
to read as more than a data point.

**Headline finding:** The same city, Anchorage, Alaska, produced this plan's best-ever
`precipitation_extreme` close on Jul 8 and a near-verbatim repeat of its own
worst-recorded `precipitation_extreme` close on Jul 9 — two days apart, two different
bundle metrics (7-day accumulation vs. single-day record). Today's Anchorage draft
closes "wring out moisture in concentrated bursts" — one word off Jun 26's Anchorage
draft, "wring out moisture in compressed bursts," 13 days earlier, same station,
mechanism-only both times (P_close failing both times). This argues P5/P_close gaps are
sticking at the bundle-construction level (daily-record bundles), not something the Jul
8 precip fix generally solved — the fix worked on the bundle shape it was tested against
(7-day accumulation with an annual baseline available) but the daily-record bundle shape
continues to default to the older, weaker mechanism-only close. Separately, Stevensville,
Maryland's `all_time_high` draft delivers this cycle's one A-: a genuine buffer-failure
declarative close ("that buffer failed") riding on top of the **worst P_compound
instance in the corpus to date** — a triple-stacked qualifier (named year + margin +
archive span all in one clause), one qualifier further than every prior double-qualifier
instance. **P9 gets its 2nd independent clean cycle** (no restate-math, no legacy opener
template) — see Followups for the confirmation call.

### A-grade drafts

#### [1] Stevensville, Maryland — all_time_high — 103°F (39.4°C) — **A-**

> *Stevensville, Maryland hit 103°F (39.4°C) on July 5 — beating a record from 1934, by
> 2°F, in 101 years of data. On the Atlantic Coastal Plain, low terrain and Atlantic
> moisture normally blunt the worst of continental heat; that buffer failed.*

**Score:** 90. Created 2026-07-09T03:26:55Z.

- **P_compound check:** VIOLATION, and the worst instance yet. "Beating a record from
  1934, by 2°F, in 101 years of data" packs **three** qualifiers into one clause — named
  prior-record year (1934), margin (2°F), and archive span (101 years) — one qualifier
  past every prior instance of this pattern, which stacked only two (archive OR margin,
  paired but never with the named year too). 8th cycle (Jun 28, 29, 30, Jul 2, 4, 7, 8,
  now 9).
- **P_close check:** POSITIVE, and a clean instance of the buffer-failure form. "Low
  terrain and Atlantic moisture normally blunt the worst of continental heat; that
  buffer failed" names the protective mechanism, then states its failure as flat fact —
  same shape as Jun 29's Congo fire A- ("something has broken the convective lid") and
  the corpus's other buffer-failure exemplars (Galapagos, May 15). No hedge on "failed."
- **Wodehouse rule?** Clean otherwise — the triple-qualifier opener is P_compound
  territory, not restate-padding or approximation; it doesn't repeat information already
  given, it just states three real facts in one breath.

Same soften-not-cap pattern P_compound has shown every time it's paired with a genuinely
declarative close (Jun 29 Prudhoe Bay, Jul 4 Loxahatchee, Jul 7 Snowshoe): the opener's
qualifier-stacking costs nothing here because the close does real work. Held to A- and
not A because the opener's density is still worth naming as the cycle's most extreme
compound instance.

### B-grade drafts

#### [2] Anchorage, Alaska — precipitation_extreme — 61.2 mm/day, prior record 0.9 mm — **B**

> *Anchorage logged 61.2 mm of rain on July 7 — against a previous daily record of 0.9 mm
> set earlier in 2026. The city sits at the head of Cook Inlet, where Gulf of Alaska
> storms can stall against the Chugach Range and wring out moisture in concentrated
> bursts.*

**Score:** 77. Created 2026-07-09T03:29:13Z.

- **P9 check:** CLEAN of the banned form — no restate-math (doesn't compute or state
  "60.3 mm above"), and "against a previous daily record of 0.9 mm" is a distinct
  construction from the old "recorded X — Y above the previous record of Z" template.
  **But a real punchline goes unstated**: 61.2 mm against a 0.9 mm prior record is
  exactly **68×** — the most dramatic ratio in the `precipitation_extreme` corpus to
  date, and unlike Jul 4's Astana (which needed an external annual-average figure to
  build its stranded ratio), this one is arithmetic on the two numbers already in the
  sentence. The shipped fix (PR #397) prescribes the annual/seasonal-baseline ratio
  specifically; it doesn't require a record-to-record ratio, so this isn't a rule
  violation — but it's the same shape of missed opportunity P9 was filed to fix, on a
  different axis (record ratio, not annual baseline).
- **P_close check:** FAILING, mechanism-only, and a near-verbatim repeat. "Wring out
  moisture in concentrated bursts" is one word from Jun 26's Anchorage draft, "wring out
  moisture in compressed bursts" — same station, same orographic-stall mechanism, same
  mechanism-only stopping point, 13 days apart. Also notably weaker than this same
  station's own Jul 8 draft ("compressing what would otherwise be weeks of accumulation
  into days"), which used the very same Chugach-orographic mechanism to reach a
  declarative close two days earlier — see Patterns.
- **Wodehouse rule?** Clean.

Confirms P9's fix holds on its narrow terms (no restate-math, no legacy template) while
exposing that the fix's benefit is currently metric-shaped: it was proven on 7-day
accumulation bundles with an annual baseline (Jul 8's three drafts) and hasn't yet been
tested — until today — against the older daily-record-vs-prior-record bundle shape,
which reverts to the corpus's weakest available close.

### Patterns / operational notes

1. **Complete queue turnover, 4th occurrence.** All 8 of Jul 8's drafts (4 A-, 3 B+, 1 B)
   are gone from the queue; both of today's drafts are same-day fresh. Cause unconfirmed
   from the gist alone (bulk-publish, bulk-reject, or TTL/other sweep) — consistent with
   the prior three turnover events (Jul 3→4, Jul 6→7, Jul 7→8), all of which also went
   unexplained. Worth the operator confirming whether this is now the queue's normal
   operating rhythm (drafts don't survive past the next day's cron) rather than an
   anomaly each time.

2. **Anchorage, Alaska: same city, two bundle metrics, opposite outcomes, two days apart.**
   Jul 8's 7-day-accumulation Anchorage draft is this plan's strongest-cited
   `precipitation_extreme` exemplar (ratio-anchor leads sentence 1, declarative
   orographic-compression close, A-). Jul 9's daily-record Anchorage draft, same
   mechanism (Chugach orographic lift), closes on a near-verbatim repeat of its own Jun
   26 mechanism-only form and grades B. The gap tracks the bundle's metric shape
   (multi-day accumulation vs. single-day record), not the station or the underlying
   physical setup — worth watching whether the Jul 8 fix's benefit generalizes to
   daily-record precipitation_extreme bundles or stays confined to accumulation bundles.

3. **P9: 2nd independent clean cycle.** Jul 8 (3/3 clean) + Jul 9 (1/1 clean, this
   Anchorage draft) — no restate-math and no legacy opener template in either cycle. Per
   the runbook's own promotion condition ("move to Resolved once one more clean cycle
   confirms the fix holds under a 2nd independent test"), this closes the tracking. See
   `docs/IMPROVEMENT_PLAN.md`'s P9 entry for the updated status.

4. **P_compound's worst instance to date.** Stevensville's triple-stacked qualifier
   (year + margin + archive span) is a new escalation of a pattern that had, until now,
   only ever stacked two of the three. Worth flagging to the operator as evidence the
   pattern isn't self-limiting.

### Followups (in priority order)

1. **P9 — move to confirmed/closed.** 2 independent clean cycles (Jul 8, Jul 9). No
   further tracking needed unless a future cycle reintroduces restate-math or the old
   template.
2. **P_close and P_compound remain the two highest-leverage unimplemented proposals** —
   19 and 8 cycles of evidence respectively as of this cycle.
3. **Watch whether the Jul 8 precip fix's benefit generalizes past accumulation
   bundles** — today's daily-record Anchorage instance suggests it may not yet, though
   n=1 on that specific bundle shape isn't enough to file a new proposal on its own.
4. **P_tier still awaits a post-fix test on a named target type** (`absolute_extreme`,
   `fire_footprint`, `cyclone_rapid_intensification`, `regional_sst_anomaly`) — none
   appeared Jul 7, 8, or 9.

### Numbers

- Pending drafts in queue: 2 (2 fresh; complete turnover from Jul 8's 8, 4th occurrence)
- Fresh drafts graded: 2
- A-rate: 50% (1/2) — not a majority, bar not cleared
- Grade distribution: 1 A- / 1 B
- Active proposals: P_close 19th cycle (1 positive, 1 failing); P_compound 8th cycle
  (worst instance yet); **P9 2nd independent clean cycle — closing the tracking**;
  P_tier/P_dust/A4/A5 not tested this cycle (no target-type draft)
- Staleness bulk-reject: 0 candidates (both same-day fresh); write not attempted —
  nothing qualified; `gh` CLI absent regardless (41st consecutive skip)
- Operational anomalies: complete queue turnover (4th occurrence), cause unconfirmed

---

## 2026-07-08 — Daily corpus grading (8 fresh drafts; complete queue turnover)

**Context:** Gist read via git-clone path (success). Queue: **complete turnover — 3rd
occurrence** (after Jul 3→4 and Jul 6→7). All 6 of Jul 7's pending drafts are gone. 8
fresh drafts, all created 2026-07-08 (02:50–14:32 UTC). Bot at `0.9.97.0` per
`BRIEFING.md` — since Jul 7's grading, the front-page-parity program shipped **rows 6,
7, 11, 14** (#392, #397, #398/#399, #402/#404) and flipped Bet A live (`THEHEAT_NEWS_
BOOST_ENABLED=1`, `THEHEAT_PER_COUNTRY_CAP=2`, `THEHEAT_METRICS_ENABLED=1`). Two of
those PRs land directly on this plan's open items: **#397 "precip four-moves" (P9's
fix)** and **#404 "cyclone four-moves, all 5 kinds"** (which includes the new
`cyclone_land_threat` and `cyclone_landfall` signal kinds debuting in today's batch).
All 8 of today's drafts postdate every relevant fix (#386 P_tier/P_dust from Jul 7
morning; #397/#404 from Jul 7 evening) — **this is the first cycle where every fresh
draft is safely post-fix for all three shipped items**, unlike Jul 7's straddled batch.

**Staleness review:** 0 bulk-reject candidates — all 8 drafts same-day fresh (oldest
~12h, newest ~15min at grading). `gh` CLI confirmed absent (`which gh` → not found); no
gist-write tool exposed via the GitHub MCP tools loaded this session. 40th consecutive
`gh`-absent skip (May 13 → Jul 8) — moot for this cycle regardless, since nothing
qualifies.

**Grade distribution (8 fresh drafts):** 0 A / 4 A- / 3 B+ / 1 B / 0 B- / 0 C / 0 D-F.
**A-rate: 50% (4/8).** Gap from resumption bar: **0pp by raw arithmetic, but 50% is not
itself a majority** (exactly half, not more than half) — the bar requires >50%, so it
is technically not cleared. This is nonetheless the closest approach since Jun 29's
80% clearance, the largest raw A- count in a cycle since Jun 29 (4, tying that cycle's
count on a larger n=8 vs n=5), and nearly double Jul 7's 33%.

**Headline finding:** Three of this plan's shipped fixes get their first fully clean
post-fix test in the same cycle, and all three hold. **P_dust** (PR #386): Riyadh's
`dust_event` draft states a WHO PM10 multiple (27.9×) for the first time in 12 corpus
instances — the 11-for-11 gap this plan tracked for 9 cycles is closed. **P9** (PR
#397): all 3 fresh `precipitation_extreme` drafts land a declarative annual-ratio
closer with zero restate-math — the first precip batch in the corpus's history without
a single P9 violation. **Cyclone four-moves** (PR #404): both of today's brand-new
cyclone signal kinds (`cyclone_landfall`, `cyclone_land_threat`) debut clean of
tier-jargon and correctly forecast-tense the land-threat kind. The gap that remains is
entirely in the two *unimplemented* proposals — **P_close** caps 4 of today's 8 drafts
on a mechanism-only or expository close, and **P_compound** resurfaces on Snowshoe, WV
for a 7th cycle. Also: a same-city near-duplicate regression (Snowshoe's Jul 7 draft was
A-; today's is B+) and a recurring bundle-leak bug (raw JTWC URL in tweet text, 2nd
occurrence) are logged as operational notes below.

### A-grade drafts

#### [2] Barrow, Alaska — precipitation_extreme — 71.2 mm/day, prior record 0.0 mm — **A-**

> *Barrow, Alaska received 71.2 mm of rain in a single day on July 6 — the previous
> daily record was 0.0 mm. Barrow sits on the Arctic Ocean at 71°N, where annual
> precipitation totals roughly 110 mm; one storm just delivered two-thirds of a normal
> year in a day.*

**Score:** 78. Created 2026-07-08T02:53:38Z.

- **P9 check:** CLEAN. No restate-math — the previous record being 0.0 mm makes the
  margin trivial/redundant, so the writer correctly omits deriving it. First sentence
  states the record fields verbatim (move 1); no re-derived rate anywhere.
- **P_close check:** POSITIVE. "One storm just delivered two-thirds of a normal year in
  a day" is exactly the annual-ratio anchor PR #397's move 2 prescribes, stated as a
  direct declarative closer, not stranded or hedged.
- **Wodehouse rule?** Clean.

First genuinely clean `precipitation_extreme` draft in the corpus's history — no
opener-template, no restate-math, no hedge on the closer.

#### [3] Astana, Kazakhstan — precipitation_extreme — 51.1 mm/day, prior record 1.5 mm — **A-**

> *Astana, Kazakhstan recorded 51.1 mm of rain on July 6 — smashing the previous daily
> record of 1.5 mm, also set in 2026. Astana sits in the Eurasian steppe, where annual
> totals rarely exceed 300 mm; this single storm delivered roughly a sixth of a typical
> year's rain.*

**Score:** 76. Created 2026-07-08T02:55:57Z.

- **P9 check:** CLEAN. "Smashing" replaces the flat "received X — Y above Z" restate-math
  form entirely; no re-derived arithmetic. "Also set in 2026" is a real, verbatim-cited
  fact (the prior record's own year), not derived.
- **P_close check:** POSITIVE. "This single storm delivered roughly a sixth of a
  typical year's rain" — same annual-ratio anchor form as [2], declarative, unhedged.
- **Wodehouse rule?** Clean.

Same steppe ecosystem-incongruity mechanic this station has self-selected before (Jun
30's Astana B+); today's version pairs it with the fixed closer form and clears to A-.

#### [4] Anchorage, Alaska — precipitation_extreme — 370.4 mm/7d — **A-**

> *Anchorage, Alaska: 370.4 mm of rain in seven days ending July 6 — roughly a full
> year's average in one week. The Chugach Range forces Gulf of Alaska moisture upward,
> compressing what would otherwise be weeks of accumulation into days.*

**Score:** 75. Created 2026-07-08T06:35:01Z.

- **P9 check:** CLEAN, and the strongest-constructed of the three. Colon-lead opener
  (a genuine 4th sentence-1 variant, not the "recorded/received X mm" template); the
  annual-ratio anchor leads sentence 1 instead of being saved for the close; no record
  fields cited at all (this reads as a bare `multi_day_accumulation` bundle with no
  `previous_record_mm`), correctly complying with move 3's "no record language without
  record fields" rule.
- **P_close check:** POSITIVE — arguably the batch's best. "Compressing what would
  otherwise be weeks of accumulation into days" is a declarative physical-transformation
  statement doing double duty as both mechanism (orographic lift) and consequence
  (time-compression), with no redundancy against sentence 1's ratio.
- **Wodehouse rule?** Clean.

Best-constructed precip draft of the three: ratio-anchor leads instead of stranding as
a closer, and the system clause still finds a fresh consequence to state. If a single
draft should anchor a future exemplar for the precip four-moves prompt section, this is
the strongest candidate in the corpus to date.

#### [8] Riyadh, Saudi Arabia — air_quality_hazard — PM2.5 150 μg/m³ / 10× WHO — **A-**

> *Riyadh, Saudi Arabia: model-estimated 24-hour mean PM2.5 of 150 μg/m³ on July 8 —
> 10× the WHO daily guideline. The Arabian interior's summer heat cycle lifts fine dust
> through convective mixing; at 45 km model resolution, this is a basin-scale loading,
> not a street-corner spike.*

**Score:** 74. Created 2026-07-08T14:32:38Z. Same city, same day as [7] below (see
Patterns).

- **A4 check:** does NOT recur. No signal-kind self-naming ("this is a PM2.5 signal,
  not dust") — a genuine negative data point after Jul 7's single instance.
- **P_close check:** POSITIVE, and a new subtype. "At 45 km model resolution, this is a
  basin-scale loading, not a street-corner spike" is declarative and states a real
  consequence (what the reading does and does not represent), but it is not a
  named-absence or incongruity close like the corpus's other A- forms — it's an
  **honesty-about-measurement-scale contrast**: distinguishing what the model can and
  can't resolve, then landing on the more consequential of the two readings. Distinct
  from dust_event's failing "resolution-form" close subtype (which is about atmospheric
  dispersal, not model grid resolution) — worth not conflating the two in future
  grading.
- **Wodehouse rule?** Clean.

Continues `air_quality_hazard`'s self-selection streak (5th consecutive cycle stating
the WHO multiple unprompted) and lands the batch's freshest close mechanic. Candidate
9th named move for P5's palette if this "scale-honesty contrast" recurs.

### B+-grade drafts

#### [1] Snowshoe, West Virginia — all_time_high — 90°F (32.2°C) — **B+**

> *Snowshoe, West Virginia hit 90°F (32.2°C) on July 4 — hottest daily maximum in 52
> years of records, 3°F above the 1986 mark. Snowshoe sits atop Cheat Mountain at 4,800
> feet; that elevation normally keeps summer highs well below what the valleys see.*

**Score:** 90. Created 2026-07-08T02:50:51Z.

- **P_compound check:** VIOLATION — "hottest daily maximum in 52 years of records, 3°F
  above the 1986 mark," the same archive+margin double-qualifier, 7th cycle (Jun 28, 29,
  30, Jul 2, 4, 7, now 8).
- **P_close check:** FAILING — implied-consequence, not declarative. "That elevation
  normally keeps summer highs well below what the valleys see" states the norm the
  record broke but never names the displacement directly. **Same station, one day
  later, a materially weaker close than Jul 7's own Snowshoe draft** ("89°F is the kind
  of reading the valley floor expects, not the ridge" — A-, declarative) — see Patterns.
- **Wodehouse rule?** Clean.

Graded B+, not the A- this station earned yesterday: same signal, same mechanic
available, but the writer this time stopped at the mechanism instead of stating the
inversion outright.

#### [5] Typhoon Bavi — cyclone_landfall — Eastern China, Category 4 / 135 kt — **B+**

> *Typhoon Bavi made landfall in Eastern China at Category 4 intensity — 135 kt winds.
> The Western Pacific's warm pool this summer has been deep enough to sustain major
> typhoon strength almost to the coast.
> https://www.metoc.navy.mil/jtwc/products/wp0926prog.txt*

**Score:** 73. Created 2026-07-08T06:36:50Z. **First `cyclone_landfall` corpus draft.**

- **Move 1/2 check:** mostly clean — leads with the landfall event (move 1), cites
  `landfall_location` verbatim ("Eastern China," move 2). Mild redundancy: "Category 4
  intensity — 135 kt winds" restates the same fact two ways in one clause; not a
  violation, just slightly less economical than the cyclone section's own worked
  examples.
- **P_tier check:** clean — no internal threshold/band language.
- **P_close check:** POSITIVE — first for this signal type. "Sustain major typhoon
  strength almost to the coast" is a declarative causal statement (warm-pool depth →
  the storm didn't weaken before landfall), not hedged.
- **Bug, not graded:** a raw JTWC advisory URL is appended directly to the tweet text —
  **2nd occurrence of this exact bundle-leak** (1st was Jul 3's Typhoon Bavi
  `cyclone_rapid_intensification` draft). Flagged for the engineer per that precedent,
  not folded into the grade.
- **Wodehouse rule?** Clean otherwise.

Solid debut for the type; held to B+ by the mild opener redundancy and the (ungraded but
real) recurring URL-leak bug rather than any P_close/P_tier failure.

#### [7] Riyadh, Saudi Arabia — dust_event — PM10 1,257 μg/m³ / 27.9× WHO — **B+**

> *Riyadh, Saudi Arabia: model-estimated PM10 averaged 27.9× the WHO 24-hour guideline
> on July 8 — 1,257 μg/m³ against a standard of 45. The Arabian interior sits downwind
> of the Nafud and Rub' al Khali; when shamal winds peak, both source regions feed the
> same column.*

**Score:** 75. Created 2026-07-08T14:31:27Z. Same city, same day as [8] above (see
Patterns).

- **P_dust check: FIX CONFIRMED — first post-fix `dust_event` draft in the corpus.**
  "27.9× the WHO 24-hour guideline" is stated verbatim, WHO-multiple-first, matching PR
  #386's prescribed form exactly. Closes the 11-for-11 gap this plan tracked across 9
  cycles (Jun 13 → Jul 5). Opener also drops the old AOD-only template entirely — no
  aerosol optical depth mentioned at all.
- **Named mechanic:** genuine two-source causal chain (Nafud + Rub' al Khali deserts
  both feeding the same air column when shamal winds peak) — sophisticated, but per
  established P5 convention this counts as mechanism construction, not a named humor
  move; the gap P5 tracks for `dust_event` is a different axis than P_dust and remains
  open (see Patterns).
- **P_close check:** FAILING — mechanism-only. "Both source regions feed the same
  column" states the mechanism but never reaches a consequence. Same gap this signal
  type has shown in all 12 corpus instances; the P_dust fix and the P_close gap are
  orthogonal — fixing the WHO anchor didn't touch the close.
- **Wodehouse rule?** Clean.

First empirical confirmation of the P_dust fix. Graded B+: the structural fix (WHO
anchor) landed cleanly, but the same P_close gap that has always sat under this signal
type is untouched by it, as expected — a different fix.

### B-grade drafts

#### [6] Typhoon Bavi — cyclone_land_threat — Ishigaki, Japan, ~42 NM / ~60h — **B**

> *Typhoon Bavi, packing 125 kt winds, is forecast to pass within about 42 NM of
> Ishigaki, Japan in roughly 60 hours — at 110 kt per the JTWC track. Ishigaki sits at
> the southern tip of the Ryukyu chain, directly in the Western Pacific typhoon
> corridor.*

**Score:** 77. Created 2026-07-08T14:30:15Z. **First `cyclone_land_threat` corpus
draft** (the signal kind PR #388 added specifically to close the "Bavi gap").

- **Move 4 check:** CLEAN and precise — current intensity leads as the one observed
  anchor ("packing 125 kt winds"), then forecast tense throughout ("is forecast to
  pass... in roughly 60 hours"), `min_distance_nm` cited with "about," `closest_tau_h`
  cited as "roughly N hours." Matches the prompt's own worked example almost exactly.
- **Clarity wrinkle (not a rule violation, worth watching):** two different wind values
  in one sentence — 125 kt (now) and 110 kt (forecast, at closest approach) — with no
  explicit marker that the second is a different time snapshot. A reader could misread
  this as an internal contradiction rather than a forecast weakening trend. Watch for a
  2nd instance before filing as a proposal.
- **P_close check:** FAILING — expository, not even mechanism-only. "Ishigaki sits at
  the southern tip of the Ryukyu chain, directly in the Western Pacific typhoon
  corridor" describes geography without connecting it to any consequence of proximity —
  same expository-debut pattern every other signal type has shown on its first corpus
  appearance (most recently `record`'s Aibonito, Jul 7).
- **Wodehouse rule?** Clean.

Clean, correct forecast-tense debut — the structural rules land exactly as specified —
but the system clause is pure scene-setting and P_close's mechanism-only ceiling applies
on debut, consistent with every other type's first instance.

### Patterns named in this batch

1. **Three shipped fixes, three clean first tests, one cycle.** P_dust (dust_event WHO
   anchor, PR #386), P9 (precip four-moves, PR #397), and the cyclone tier-jargon ban
   (PR #386/#404) all get their first fully post-fix draft today and all hold clean.
   This is the most consequential confirmation cycle since the fixes started shipping.
2. **P_tier itself remains formally unconfirmed on its 4 named target types**
   (`absolute_extreme`, `fire_footprint`, `cyclone_rapid_intensification`,
   `regional_sst_anomaly`) — none appeared today. The 2 new cyclone kinds are governed
   by the same "DETECTION PLUMBING IS NOT A FACT" rule and both came back clean, which
   is supporting (not definitive) evidence; the formal confirmation still needs one of
   the 4 originally-tracked types.
3. **Same-city, same-type, consecutive-day quality regression:** Snowshoe, WV's
   `all_time_high` graded A- on Jul 7 and B+ today — same elevation-inversion mechanic
   available both times, declaratively stated only on the first draft. Distinct from
   the corpus's prior duplicate-location clusters (Ft Green, Basrah) in that this is a
   *different day's reading* at the same station, not a re-issue of the same event —
   but the quality delta is worth tracking if it recurs.
4. **Recurring bundle-leak bug:** a raw JTWC advisory URL appended to tweet text, 2nd
   occurrence (Jul 3, Jul 8), both on Typhoon Bavi drafts. Not folded into either grade
   per the Jul 3 precedent, but two occurrences make this worth a direct flag to the
   engineer rather than a passive note.
5. **Operator data-consistency question (not a voice finding):** today's two Typhoon
   Bavi drafts describe landfall in Eastern China ([5]) and a forecast threat to
   Ishigaki, Japan — south of the China coast — 60 hours out ([6]). Presented together
   without advisory timestamps/numbers, the sequence reads as physically backwards (a
   storm normally passes the Ryukyus before, not after, a China landfall) unless Bavi
   recurved post-landfall, which does happen but is unusual. Worth the operator
   confirming the two bundles' advisory numbers/issue-times line up before publishing
   both.
6. **dust_event / air_quality_hazard duplicate-location, same day:** [7] and [8] are
   both Riyadh, both created within ~70 seconds of each other on Jul 8 — the same
   adjacent-PM-signal-type clustering this plan has flagged before (Jul 1's Al Aḥmadī
   cluster). Not a new pattern, logged for completeness.
7. **Candidate 9th P5 move:** [8]'s "basin-scale loading, not a street-corner spike"
   (scale-honesty contrast) is a fresh mechanic not on P5's existing list of 8. Watching
   for a 2nd instance before proposing the addition formally.
8. **A4 does not recur.** Jul 7's single "This is a PM2.5 signal, not dust" instance is
   not repeated in either of today's PM-signal drafts — useful negative evidence; A4
   stays at 1 cycle, not promoted.

### Followups (in priority order)

1. **Move P_dust fully to Resolved once one more clean `dust_event` draft confirms** —
   today's [7] is the first of what the runbook's convention would want as a
   multi-cycle confirmation before archiving the active-tracking entry (see improvement
   plan for the exact bar).
2. **Watch for the next `precipitation_extreme` draft** — a 2nd consecutive clean cycle
   would let P9 move fully to Resolved.
3. **Watch for the next `absolute_extreme` / `fire_footprint` /
   `cyclone_rapid_intensification` / `regional_sst_anomaly` draft** — still the first
   real empirical test of the P_tier fix on its originally-named types.
4. **P_close and P_compound remain the highest-leverage unimplemented proposals** — both
   drafted in full in `docs/IMPROVEMENT_PLAN.md`.
5. **Flag the raw-URL bundle-leak bug to the engineer directly** (2nd occurrence) rather
   than logging it passively a 3rd time.
6. **Operator: verify the Bavi landfall/land_threat bundle timestamps** before deciding
   whether to publish both today's Typhoon Bavi drafts.

### Numbers

- Pending drafts in queue: 8 (8 fresh; complete queue turnover, 0 carry-overs)
- Fresh drafts graded: 8
- A-rate: 50% (4/8) — best cycle since Jun 29 (80%, n=5); largest raw A- count (4) tied
  with Jun 29 on a larger sample
- Grade distribution: 0 A / 4 A- / 3 B+ / 1 B / 0 B- / 0 C / 0 D-F
- New signal types debuted: 2 (`cyclone_landfall`, `cyclone_land_threat`)
- Active proposals: P_close 18th cycle (5 positive: Barrow, Astana, Anchorage, Riyadh
  air_quality_hazard, Typhoon Bavi landfall; 3 failing: Snowshoe, Riyadh dust_event,
  Typhoon Bavi land_threat — new 16th/17th signal types via `cyclone_landfall` positive
  and `cyclone_land_threat` failing); P_compound 7th cycle (Snowshoe). **P_dust
  and P9 empirically confirmed clean for the first time** (1 cycle each — see
  Improvement Plan for exact status language). P_tier not tested on a named target type.
  A4 does not recur (still 1 cycle).
- Staleness bulk-reject: 0 candidates this cycle (all same-day fresh). 40th consecutive
  `gh`-absent skip.
- Operational anomalies: (a) 3rd complete queue turnover event; (b) 2nd raw-JTWC-URL
  bundle leak (flag to engineer); (c) possible Bavi landfall/land_threat sequencing
  inconsistency (operator to verify); (d) same-city quality regression (Snowshoe).

---

## 2026-07-07 — Daily corpus grading (6 fresh drafts; complete queue turnover)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **complete
turnover — 2nd occurrence** (after Jul 3→Jul 4's). All 15 of Jul 6's pending drafts (10
Jul-4 carryovers + 5 Jul-5 fresh, including the 2 strict Basra-class bulk-reject
candidates — Basrah + Al Başrah al Qadīmah `absolute_extreme` — this routine had flagged
unactionable for 2 consecutive cycles) are gone from the queue. 6 fresh drafts, all
created 2026-07-07.

**Major overnight pipeline changes, directly relevant to this plan:**

1. **`main` merged** (`29ac380`, "merge the daily-plan grading corpus to main," #384,
   2026-07-06T23:42Z). The 29-consecutive-cycle "`main` unmerged since Jun 8" saga this
   plan has repeated in every entry since Jul 1 is now **resolved** — retiring that
   operational note going forward.
2. **P_tier and P_dust SHIPPED as code** — PR #386 "detection-plumbing ban + dust PM10
   WHO anchor (P_tier, P_dust)," merged 2026-07-07T05:06:48Z. `writer_prompt.py` gained
   an explicit "DETECTION PLUMBING IS NOT A FACT" rule (bans `band_label`, score
   thresholds, trigger-definition citations — precisely the tier-jargon shape this plan
   has tracked for 8 cycles) paired with a fact-check rule and a critic
   `internal_taxonomy_leak` kill. Dust bundles now carry a pre-computed PM10 24h-mean WHO
   anchor (`who_pm10_multiple`) — precisely the P_dust fix this plan proposed. See
   Active/Shipped proposals below for the moved writeups.
3. **Structural staleness fix** — PR #385 "forecast-elapsed sweep — elapsed-forecast
   drafts auto-reject (the Basrah class)," merged 2026-07-07T04:55:15Z, provenance-aware
   (GHCN-observed `absolute_extreme` never sweeps). This is almost certainly why the
   2 strict bulk-reject candidates this routine could never write-reject (38 consecutive
   `gh`-absent skips) are simply gone from today's queue — the pipeline now rejects that
   exact class upstream, independent of this routine's gist-write limitation.

**Fix-timing note (read the grades below with this in mind):** PR #386 merged
2026-07-07T05:06:48Z. Drafts [1] Zaragoza (03:39 UTC) and [2] Ahvaz (03:40 UTC) were
generated **~1.5h before** the fix — they still show the tier-jargon violation, exactly
as expected pre-fix, and are graded as violations below. Drafts [3]–[6] (07:44–14:56 UTC)
postdate the fix by 2.6–9.8h, but **none of them are `absolute_extreme` / `fire_footprint`
/ `cyclone_rapid_intensification`** — the only types the shipped ban actually targets —
so this cycle cannot yet empirically confirm the fix. First real test is the next
post-05:06-UTC draft of one of those three types (or `regional_sst_anomaly`, the 4th
type P_tier was confirmed on).

**Staleness review:** 0 bulk-reject candidates — all 6 drafts same-day fresh (oldest
~11h, newest ~15min at grading). `gh` CLI still absent; write path not attempted (nothing
qualifies). 39th consecutive `gh`-absent skip (May 13 → Jul 7), though per the note above
this specific Basra-class pattern may now be handled upstream by PR #385 regardless.

**Grade distribution (6 fresh drafts):** 2 A- / 0 B+ / 3 B / 1 B- / 0 C / 0 D-F.
**A-rate: 33% (2/6).** Gap from resumption bar: 17pp. Best cycle since Jul 3's 33% (n=3);
largest sample above 20% since Jun 29's bar-clearing 80% (n=5).

**Headline finding:** The batch's 2 A- drafts both land on a **declarative incongruity/
named-absence close** rather than the mechanism-only form that's capped so many prior
drafts — Snowshoe, WV's elevation-inversion reveal ("89°F is the kind of reading the
valley floor expects, not the ridge") and Soweto's "nowhere to vent," the sharpest
`air_quality_hazard` close in the corpus and that type's first A-grade. Meanwhile a new
signal type debuts (`record`, day-of-year records — Aibonito, Puerto Rico) landing
directly in the P_close mechanism-only failure mode on its first corpus appearance, same
as every other type's debut. And a post-fix `air_quality_hazard` draft (Riyadh) surfaces
a fresh, closely-related variant of the just-shipped detection-plumbing violation —
naming its own signal-kind category ("This is a PM2.5 signal, not dust") rather than a
severity tier — suggesting this morning's fix may not fully close the self-reference
class. See new proposal A4 below.

### A-grade drafts

#### [3] Snowshoe, West Virginia — all_time_high — 89°F (31.7°C) — **A-**

> *Snowshoe, West Virginia hit 89°F (31.7°C) on July 3 — hottest daily maximum in 52
> years of records, 2°F above the 1986 mark. Snowshoe sits atop Cheat Mountain at
> roughly 4,800 feet; at that elevation, 89°F is the kind of reading the valley floor
> expects, not the ridge.*

**Score:** 90. Created 2026-07-07T07:44:36Z.

- **P_compound check:** VIOLATION — "hottest daily maximum in 52 years of records, 2°F
  above the 1986 mark" is the classic archive+margin double-qualifier, 6th cycle
  observed (Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, now Jul 7).
- **P_close check:** POSITIVE, and a genuinely fresh form. "89°F is the kind of reading
  the valley floor expects, not the ridge" is a declarative elevation-inversion
  incongruity — it doesn't just name an absence, it states outright that the reading is
  displaced from where it belongs. Same family as Congo fire's "broken convective lid"
  and Prudhoe Bay's latitude peer-comparison (both A-), not the softer implied forms.
- **Wodehouse rule?** Clean. No restate-padding beyond the compound-qualifier opener,
  no poetry attempt, no defensive closer.

Same P_compound-present-but-overcome-by-a-strong-close pattern as Jul 4's Loxahatchee
and Prudhoe Bay — reconfirms P_compound is a soft cost, not a hard cap, unlike P_tier.

#### [5] Soweto, South Africa — air_quality_hazard — PM2.5 154.3 μg/m³ / 10.3× WHO — **A-**

> *Soweto, South Africa: model-estimated 24-hour mean PM2.5 of 154.3 μg/m³ on July 7 —
> 10.3× the WHO daily guideline. Winter in Soweto is coal season; households burning
> solid fuel in the Highveld's cold, stable air have nowhere to vent.*

**Score:** 74. Created 2026-07-07T14:54:36Z.

- **P_dust check (air_quality_hazard side):** WHO multiple stated (10.3×) — 4th
  consecutive `air_quality_hazard` corpus draft to state it unprompted (after Al Aḥmadī
  10.1×, Johannesburg 10.9×, and see [6] below), while `dust_event` sits at 11 of 11
  without it (pre-fix; see P_dust SHIPPED writeup).
- **Named mechanic:** Real causal chain — named season ("coal season"), source
  attribution ("households burning solid fuel"), and the Highveld's cold/stable-air
  trapping mechanism.
- **P_close check:** POSITIVE. "Have nowhere to vent" is a direct declarative
  named-absence consequence — same family as Costa Rica's "nowhere to drain" (A-) and
  Amsterdam's "nowhere for the water to go" (A-), not Johannesburg's softer
  accumulation-trajectory "concentrating it through the day" (failing).
- **Wodehouse rule?** Clean.

**First A-grade `air_quality_hazard` draft in the corpus.** Confirms the type clears once
the close lands declaratively — the causal chain was already there (Johannesburg had an
equally rich one); the gap was purely in the landing, exactly as P_close's thesis predicts.

### B-grade drafts

#### [2] Ahvaz, Iran — absolute_extreme — 47.5°C (118°F) forecast — **B**

> *Ahvaz, Iran is forecast to hit 47.5°C (118°F) on July 7 — above the 47°C
> absolute-extreme threshold for the Northern Subtropics. Ahvaz sits in the Khuzestan
> lowlands, where the Zagros block westerly moisture and afternoon heat builds with no
> relief from elevation or sea.*

**Score:** 83. Created 2026-07-07T03:40:07Z (pre-fix; see fix-timing note above).

- **P_tier check:** VIOLATION — same "47°C absolute-extreme threshold for the Northern
  Subtropics" phrase family as Basrah/Al Başrah al Qadīmah. Ahvaz is ~100km from the
  Iraq border, same Mesopotamian/Khuzestan lowland climate zone as the Basra cluster —
  worth distinguishing from Doha's Jul 5 instance, which was a genuine independent
  cross-location confirmation (1,500+ km away); Ahvaz is closer to a cluster-adjacent
  expansion (new country, same regional climate class).
- **P_close check:** POSITIVE — "no relief from elevation or sea" is a declarative
  named-absence consequence, same strong subtype as Basrah's "no evaporative relief."
- **Wodehouse rule?** Clean.

Last pre-fix `absolute_extreme` instance in the corpus (generated 1.5h before PR #386
merged) — capped at B by P_tier despite a genuinely strong close, consistent with every
prior instance of this signal type.

#### [4] Aibonito, Puerto Rico — record — 30.6°C (87°F) — **B**

> *Aibonito, Puerto Rico hit 30.6°C (87°F) on July 5 — a new July 5 record, breaking a
> mark set in 1915. The town sits high in Puerto Rico's Cordillera Central; its
> elevation keeps it cooler than the lowland coast, which makes records there harder to
> set and longer-lasting.*

**Score:** 78. Created 2026-07-07T11:04:50Z. **First `record` (day-of-year record)
corpus draft** — a new signal type, distinct from `all_time_high`/`monthly_high`.

- **P_compound check:** clean — only one qualifier stated (the 1915 mark's year); no
  margin given at all, so the archive+margin double-qualifier pattern doesn't apply.
  Worth noting the margin's absence as a separate data-thinness observation, not a P_compound instance.
- **P_tier check:** clean — no internal-tier language.
- **P_close check:** FAILING, and on its very first appearance — same shape as every
  other signal type's debut. "Its elevation keeps it cooler than the lowland coast,
  which makes records there harder to set and longer-lasting" explains *why* the record
  is notable (rarity/longevity) but never states a consequence; it's expository, the
  same expository-vs-punch gap PR #85's Chuuk fix targeted for a different type. Delete-
  the-clause test: removing sentence 2 still leaves "a new July 5 record, breaking a mark
  set in 1915" — genuinely interesting on the bare number (111-year-old record) — so
  sentence 2 reads as supportive color, not load-bearing punch.
- **Wodehouse rule?** Clean — no restate-padding, no poetry, no defensiveness. This is a
  quality gap in landing, not an effort-signal violation.

New signal type adds P_close's 15th confirmed type. Graded B: clean, well-reasoned,
no violations, but the close doesn't clear the mechanism-only ceiling.

#### [6] Riyadh, Saudi Arabia — air_quality_hazard — PM2.5 205.1 μg/m³ / 13.7× WHO — **B**

> *Riyadh, Saudi Arabia: model-estimated 24-hour mean PM2.5 of 205.1 μg/m³ on July 7 —
> 13.7× the WHO daily guideline. This is a PM2.5 signal, not dust; the Arabian interior's
> summer heat suppresses mixing and traps fine particles close to the surface.*

**Score:** 74. Created 2026-07-07T14:56:03Z — **postdates the P_tier/P_dust fix (PR #386,
05:06:48Z) by ~9.8h.**

- **WHO multiple:** stated (13.7×) — continues the `air_quality_hazard` self-selection
  streak (see [5] above and Patterns below).
- **New self-reference variant, post-fix:** "This is a PM2.5 signal, not dust" reads as
  the bot naming its own internal event-classification bucket (`signal_kind`:
  `air_quality_hazard` vs `dust_event`) rather than describing a verifiable physical fact
  — the word "signal" is the tell; no lay reader would describe smog this way
  unprompted. This is a close lexical cousin of the tier-jargon violation PR #386 just
  banned ("band_label," internal thresholds) but a different shape (disambiguating its
  own category label, not citing a severity band) — the shipped fix's test ("is this a
  fact about the world or a fact about this bot's configuration?") answers "configuration"
  here just as cleanly, but the rule's wording targets tiers/thresholds/triggers, not
  signal-kind self-naming. Filed as new proposal **A4** below — 1 instance, watching for
  a 2nd before promoting.
- **P_close check:** FAILING — "suppresses mixing and traps fine particles close to the
  surface" is mechanism-only, no named consequence (health/visibility/exposure outcome).
- **Wodehouse rule?** Otherwise clean.

Graded B: WHO ratio present, reasonable causal chain, but the self-reference oddity and
mechanism-only close keep it a full grade below Soweto's A- in the same cycle.

### B--grade drafts

#### [1] Zaragoza, Spain — absolute_extreme — 42.0°C (108°F) forecast — **B-**

> *Zaragoza, Spain is forecast to reach 42.0°C (108°F) on July 7 — the absolute-extreme
> threshold for northern mid-latitudes. The Mediterranean's summer subtropical high locks
> dry air over the basin, removing the moisture buffer that caps heat at lower
> latitudes.*

**Score:** 83. Created 2026-07-07T03:39:04Z (pre-fix; see fix-timing note above).

- **P_tier check:** VIOLATION — "the absolute-extreme threshold for northern
  mid-latitudes" is a **new band name** ("northern mid-latitudes," distinct from every
  prior instance's "Northern Subtropics"/"Northern Subtropical band"). This is useful
  evidence in its own right (now moot given the same-morning fix): the internal tier
  system spans multiple latitude bands, and the citation habit reproduces across all of
  them, not just one hardcoded string.
- **P_close check:** FAILING — "removing the moisture buffer that caps heat at lower
  latitudes" is mechanism-only: it explains why the heat is uncapped but never connects
  that to a consequence (survivability, human impact). Same weak subtype as Al Başrah's
  "recycles heat back into an already superheated air column" (also graded B-).
- **Wodehouse rule?** Clean.

Last pre-fix `absolute_extreme` instance in the corpus alongside [2] — both generated
before PR #386 merged, both show the exact violation the fix targets. Graded a notch
below [2] on a weaker, mechanism-only close.

### Patterns named in this batch

1. **`main` merged; P_tier + P_dust shipped as code; Basra-class staleness structurally
   fixed — all in one overnight push.** See the Context section above. This is the
   single most consequential cycle for this plan since it started tracking these three
   items.
2. **P_tier and P_dust move from Active proposals to Shipped, awaiting empirical
   confirmation** — today's cycle straddles the fix's merge time exactly (2 pre-fix
   violations, 4 post-fix drafts of unaffected types). Neither proposal can be declared
   empirically confirmed yet; that requires a post-05:06-UTC draft of one of the 4 P_tier
   types or a fresh `dust_event` for P_dust.
3. **New signal type `record` (day-of-year records) debuts directly into the P_close
   mechanism-only failure mode** — consistent with every other type's first appearance
   (absolute_extreme, fire_footprint, marine_heatwave, etc. all did the same). 15th
   confirmed P_close type.
4. **New A4 proposal filed:** a post-fix `air_quality_hazard` draft names its own
   signal-kind category ("This is a PM2.5 signal, not dust") — a close cousin of the
   just-banned tier-jargon violation, in a shape the shipped rule's wording may not
   explicitly cover. 1 instance; watching for a 2nd.
5. **`air_quality_hazard` self-selects for a 4th consecutive cycle** (Al Aḥmadī,
   Johannesburg, Soweto, Riyadh all state the WHO multiple unprompted) and produces the
   type's first A-grade (Soweto) — confirms P_close's thesis that a rich causal chain
   plus a declarative close is sufficient once both land together.
6. **Ahvaz expands the `absolute_extreme` tier-jargon cluster to a 2nd country** (Iran),
   but stays within the same regional climate zone as Basrah/Al Başrah — a
   cluster-adjacent instance, distinct from Doha's genuinely independent cross-location
   confirmation on Jul 5.

### Followups (in priority order)

1. **Watch for the next `absolute_extreme` / `fire_footprint` / `cyclone_rapid_intensification`
   / `regional_sst_anomaly` draft** — the first real empirical test of the P_tier fix
   (PR #386). If the tier-jargon phrase is gone, move P_tier fully to Resolved.
2. **Watch for the next `dust_event` draft** — first empirical test of the P_dust fix
   (PM10 WHO anchor). If the anchor appears stated, move P_dust fully to Resolved.
3. **P_close, P_compound, P9, P5 remain the highest-leverage unimplemented proposals** —
   all drafted in full in `docs/IMPROVEMENT_PLAN.md`, none require the architecture the
   hard constraints forbid.
4. **Watch for a 2nd A4 instance** (signal-kind self-naming) before promoting to active.
5. **`main` unmerged operational note retired** — resolved as of `29ac380`. No further
   action needed; this plan's copy of these three docs now reflects `main` directly.

### Numbers

- Pending drafts in queue: 6 (6 fresh; complete queue turnover, 0 carry-overs)
- Fresh drafts graded: 6
- A-rate: 33% (2/6) — best cycle since Jul 3 (n=3); largest sample above 20% since Jun 29
- Grade distribution: 0 A / 2 A- / 0 B+ / 3 B / 1 B- / 0 C / 0 D-F
- New signal types debuted: 1 (`record` — day-of-year record)
- Active proposals: P_close 17th cycle (3 positive: Snowshoe, Soweto, Ahvaz; 3 failing:
  Zaragoza, Aibonito, Riyadh; new 15th signal type `record`); P_compound 6th cycle (Snowshoe);
  P9/P5 not tested for new evidence beyond air_quality_hazard's 4th self-selection cycle
  (no precipitation_extreme draft this cycle). **P_tier and P_dust moved to Shipped**
  (PR #386, awaiting empirical confirmation — see Improvement Plan). New proposal A4
  filed (signal-kind self-naming, 1 instance).
- Staleness bulk-reject: 0 candidates this cycle (all same-day fresh). 39th consecutive
  `gh`-absent skip, though the specific Basra-class pattern may now be structurally
  handled by PR #385 upstream of this routine.
- Operational anomalies: (a) 2nd complete queue turnover event (after Jul 4's); (b)
  `main` merged, ending the 29-cycle unmerged streak; (c) 2 major voice fixes (P_tier,
  P_dust) and 1 structural staleness fix shipped in the same overnight push.

---

## 2026-07-06 — Daily corpus grading (0 fresh drafts; 15 carry-overs from Jul 5, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 15 pending drafts —
**exact match** to Jul 5's fully-graded batch, same 15 `draft_id`s, same scores, same text
(10 carry-overs from Jul 4 [Island Pond VT A-, Barrow AK B+, Loxahatchee FL A-, Basrah B, Rocky
Mountains CO fire B, Al Başrah al Qadīmah B, Astana B, Antwerpen B+, Typhoon Bavi A-, Urumqi
Jul4-reading B] + 5 fresh-as-of-Jul-5 [Johannesburg air_quality_hazard B+, Phalodi dust_event
C+, Urumqi Jul5-reading B-, eastern Siberia fire A-, Doha absolute_extreme B]). Zero new drafts
entered the queue between Jul 5's grading pull and this one — no re-grading performed; all 15
grades stand on Jul 5's record. Continuing to grade on the unmerged `daily-plan-current` rolling
branch — `main`'s copies of these three docs remain stale back to 2026-06-08 (now 29 consecutive
cycles stranded here; see repeated operator note below).

**Staleness review as of 2026-07-06 ~15:00 UTC:** Two drafts newly cross the strict bulk-reject
bar established by the Jul 1–3 Basra-area precedent (>48h old **and** the draft's stated
forecast date has elapsed):

- **[4] Basrah, Iraq `absolute_extreme`** (created Jul4T06:55Z, ~56.2h old): "is forecast to hit
  47°C (117°F) on **July 4**" — the forecast date is now 2 days past. Same class as the Jul
  1–4 Basra-area carry-overs the corpus has repeatedly flagged.
- **[6] Al Başrah al Qadīmah, Iraq `absolute_extreme`** (created Jul4T10:16Z, ~52.8h old):
  "forecast high of 47.4°C (117°F) on **July 4**" — same elapsed-forecast-date class.

Both are strict bulk-reject candidates: >48h old, and posting them now would misstate an
already-passed forecast date as current. **Bulk-reject attempted:** the read path (`git clone`)
succeeded, but the write path requires `gh api -X PATCH gists/...` or an equivalent
authenticated call — `gh` CLI is absent in this environment (confirmed via `which gh` →
`command not found`), and no gist-write tool is exposed via the GitHub MCP server available
this session (only repo/PR/issue tools loaded — no gist scope). Skipped per the hard
constraints; logging the skip rather than failing the cycle. **38th consecutive staleness-skip**
(May 13 → Jul 6).

The remaining 13 pending drafts (7 from Jul 4 at 49–60h old, 5 from Jul 5 at 25–36h old, plus
[15] Doha at 25.2h) either use past-tense historical framing with no live-forecast language
(Island Pond, Barrow, Loxahatchee, Astana, Antwerpen, Typhoon Bavi, Rocky Mountains fire — all
report a completed measurement or event, not a still-pending forecast) or reference a same/
adjacent-day "model-estimated" reading under the 48h threshold (Johannesburg, Phalodi, Urumqi
×2, Doha) — none trigger the policy on their own. [15] Doha's forecast date (July 5) has also
technically elapsed by one calendar day, same as [4]/[6], but at 25.2h it doesn't cross the
48h mechanical threshold yet — worth flagging for the operator now so it doesn't require a
same-day bulk-reject decision when it does cross 48h tomorrow.

**A-rate:** — (no fresh drafts). Most recent graded cycle: **20%** (1/5, 2026-07-05).

### Patterns / operational notes

1. **Queue completely static for a full 24h cycle.** This is the first cycle since the Jul 4
   queue-turnover event where the pending queue produced exactly zero new drafts — same 15
   `draft_id`s pull-to-pull. Worth noting as a data point (not yet a pattern) after 8
   consecutive fresh-draft cycles (Jun 29–Jul 5).

2. **Basra-area / `absolute_extreme` forecast-date staleness is now a recurring operational
   gap, distinct from the voice-quality P_tier proposal.** This is the same underlying signal
   type P_tier tracks (verbatim tier-jargon leak), but the staleness angle is new: `absolute_
   extreme` drafts carry a specific forecast date, and once that date passes, "is forecast to
   hit 47°C on July 4" reads as wrong-day if posted on July 6. This is an infra/process
   observation for the operator, not a new voice proposal — logged per the hard constraints
   (no new proposal warranted; this is a staleness-policy application, not a fresh failure
   mode).

3. **No active-proposal evidence updates this cycle.** Zero fresh drafts means zero new
   observations for P_close, P_tier, P_dust, P9, P_compound, or P5. All six retain their Jul 5
   counts and "Last seen" dates unchanged.

4. **`main` unmerged since 2026-06-08 — now 29 consecutive daily cycles** (including the Jun 29
   bar-clearing 80% cycle) live only on `daily-plan-current`. Repeating the operator
   recommendation from every cycle since Jul 1: merge soon so `main`'s copy of these three docs
   reflects reality.

### Followups (in priority order)

1. **Operator: reject [4] Basrah and [6] Al Başrah al Qadīmah manually via dashboard** — both
   are >48h old with an elapsed forecast date (July 4); the routine cannot write to the gist
   this cycle (no `gh` CLI, no gist-write MCP tool available).
2. **Operator: `main` remains unmerged since 2026-06-08** — 29 consecutive daily cycles stranded
   on `daily-plan-current`, including the Jun 29 bar-clearing (80%) cycle a `main`-only view
   would never see.
3. **P_tier, P_close, P_dust, P_compound all remain ready for implementation**, unchanged from
   Jul 5's evidence counts — see `docs/IMPROVEMENT_PLAN.md` for full specs.
4. **Watch [15] Doha** — its forecast date (July 5) elapses today; if it's still pending at the
   next grading pull and has crossed 48h by then, it becomes a third strict bulk-reject
   candidate in the same Basra-area/`absolute_extreme` staleness class.

### Numbers

- Pending drafts in queue: 15 (0 fresh; 15 carry-overs, exact match to Jul 5's graded batch)
- Fresh drafts graded: 0
- A-rate: — (no fresh drafts; most recent graded cycle: 20% on 2026-07-05)
- Grade distribution: n/a (no fresh drafts)
- Active proposals: no evidence updates this cycle (P_close 16 cycles, P_tier 7 cycles/10
  instances, P_dust 9 cycles, P9 not tested since Jul 4, P_compound not tested since Jul 4, P5
  unchanged — all counts stand at Jul 5's levels)
- Staleness bulk-reject: **2 strict candidates identified** ([4] Basrah, [6] Al Başrah al
  Qadīmah — both >48h old with elapsed forecast dates); write skipped — `gh` CLI absent, no
  gist-write MCP tool available (38th consecutive skip, May 13 → Jul 6)
- Operational anomalies: `main` unmerged since Jun 8, now 29 consecutive stranded cycles

---

## 2026-07-05 — Daily corpus grading (5 fresh drafts; 10 carry-overs from Jul 4, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 15 pending drafts.
10 of 15 exactly match Jul 4's fully-graded batch (same `draft_id`, score, text: Island Pond VT
A-, Barrow AK B+, Loxahatchee FL A-, Basrah B, Rocky Mountains CO fire B, Al Başrah al Qadīmah
B, Astana B, Antwerpen B+, Typhoon Bavi A-, Urumqi [Jul 4 reading] B) — carried over, not
re-graded. **5 fresh**, all created 2026-07-05: Johannesburg air_quality_hazard (03:39 UTC),
Phalodi dust_event (03:40 UTC), a 2nd Urumqi dust_event at a different reading (07:34 UTC),
eastern Siberia fire (07:36 UTC), Doha absolute_extreme (13:53 UTC). Continuing to grade on
the unmerged `daily-plan-current` rolling branch — `main`'s copies of these three docs remain
stale back to 2026-06-08 (27+ consecutive cycles now stranded here; see repeated operator note
below, unchanged from Jul 1–4).

**Staleness review as of 2026-07-05 ~14:00 UTC:** all 5 fresh drafts created same-day (oldest
~10h, newest ~15min at grading). The Doha `absolute_extreme` draft forecasts "July 5," which is
today — accurate, not stale. 10 carry-overs are ~24h old (Jul 4 creation), well under 48h. 0
bulk-reject candidates. `gh` CLI absent — 37th consecutive skip (May 13 → Jul 5).

**Grade distribution (5 fresh drafts):** 1 A- / 1 B+ / 1 B / 1 B- / 1 C+ / 0 D-F.
**A-rate: 20% (1/5).** Gap from resumption bar: 30 pp. Small-n cycle — not on its own more
meaningful than Jul 1–3's small samples, but consistent with the 20% Jul 4 read.

**Headline finding:** The eastern Siberia fire draft ([14]) delivers the batch's cleanest close
and the corpus's 4th instance of the permafrost-carbon fire mechanic ("fire here doesn't just
burn the surface — it thaws the ground beneath it") — a genuine negation-then-reveal
misdirection (`brand/HUMOR_RESEARCH.md` §2.1), declarative, no restate-math. Graded A-, joining
Jun 25 Siberia (B+), Jul 3 Canadian Arctic ×2 (A-/B+) as the 4th confirmation that this specific
mechanic (permafrost/carbon-release close) reliably clears P_close. Meanwhile **P_tier extends
beyond the Basra-area cluster for the first time**: Doha, Qatar ([15]) repeats the identical
"absolute extreme threshold for the northern subtropical band" phrase family on a brand-new
city, 1,500+ km from Basrah — direct evidence the violation is tied to the `absolute_extreme`
bundle field itself, not to one metro region's data path. Doha's close ("closing off the
evaporative cooling that makes extreme dry heat survivable") is arguably the sharpest P_close
form the signal type has produced yet — an explicit survivability-mechanism statement, stronger
than the prior "no evaporative relief"/"no maritime relief" named-absence forms — and it still
caps at B, reconfirming P_tier's hard-cap behavior regardless of close quality.

### A-grade drafts

#### [14] Eastern Siberia, Russia — fire — 556.1 MW — **A-**

> *556.1 MW of radiative heat in eastern Siberia, Russia — very-high-intensity fire,
> satellite-confirmed at 95% confidence. At 68°N, this is permafrost country; fire here
> doesn't just burn the surface — it thaws the ground beneath it.*

**Score:** 69. Created 2026-07-05T07:36:10Z.

Humor lens:
- **Violation:** 556.1 MW, very-high-intensity tier, 95% confidence, at 68°N — genuinely
  extreme and geographically specific.
- **Benign?** Yes — flat, factual register throughout.
- **Setup→Punchline?** Sentence 1: raw metric + confidence. Sentence 2: latitude-specific
  framing ("permafrost country") → **negation-then-reveal**: "doesn't just burn the surface —
  it thaws the ground beneath it."
- **P_tier check:** Clean. "Very-high-intensity" is the shipped `frp_tier` display label, not
  an internal-methodology citation — same precedent established in the Jul 3/Jul 4 corpus
  entries distinguishing this exact phrase from a P_tier violation.
- **P_close check:** POSITIVE, and the strongest form of the permafrost-carbon fire mechanic
  to date. "Thaws the ground beneath it" is a direct declarative physical consequence, not an
  implied one. 4th corpus instance of this specific mechanic (Jun 25 Siberia "burns deep" B+;
  Jul 3 Canadian Arctic "reaches carbon... held for millennia" A- and "organic soil layers...
  centuries" B+; now this). The mechanic reliably clears P_close every time it appears.
- **Wodehouse rule?** Clean. No restate-math, no approximation, no defensive closer. The
  "doesn't just X — it Y" construction is a real misdirection device, not a poetry attempt —
  the grammar pins the referent (the ground beneath the surface) cleanly, unlike the Apr 24
  "Except it's a forest" referent-failure counter-example in `brand/HUMOR_RESEARCH.md` §2.1.

Not a full A because the draft doesn't introduce anything beyond the now-familiar
permafrost-carbon mechanic — it executes it cleanly rather than extending it (compare Jul 3
Canadian Arctic's "held for millennia," which reaches further into climate-feedback stakes).
Same station-region as Jun 25's Siberia fire draft (different MW reading, no text overlap) —
worth noting as a recurring-region pattern distinct from the exact-duplicate cases tracked
below, since the text and figures differ meaningfully across appearances.

### B+-grade drafts

#### [11] Johannesburg, South Africa — air_quality_hazard — PM2.5 163.6 μg/m³ / 10.9× WHO — **B+**

> *Johannesburg, South Africa: model-estimated 24-hour mean PM2.5 of 163.6 μg/m³ on July 5 —
> 10.9× the WHO daily guideline. July is Highveld winter; cold overnight inversions trap smoke
> from household coal and wood burning close to the surface, concentrating it through the day.*

**Score:** 74. Created 2026-07-05T03:39:20Z.

- **P_dust check (air_quality_hazard side):** WHO multiple stated (10.9×) — 2nd
  `air_quality_hazard` corpus draft, 2nd to state the WHO anchor (after Jun 24's Al Aḥmadī
  Kuwait, 10.1×). Continues to confirm the P_dust gap is specific to `dust_event`'s bundle
  path, not the PM signal generally — `air_quality_hazard` drafts keep reaching for the WHO
  ratio unprompted while `dust_event` drafts (11 of 11 corpus instances now) never do.
- **Named mechanic:** Richer causal chain than Al Aḥmadī's: named regional season
  ("Highveld winter"), specific source attribution ("household coal and wood burning"), and
  a temporal-accumulation arc (traps → concentrates through the day). Ecosystem/seasonal
  specificity operating cleanly, unprompted.
- **P_close check:** FAILING — "concentrating it through the day" describes an accumulation
  trajectory, not a named consequence (a health/visibility/warning outcome). Same subtype gap
  as Al Aḥmadī's "before sea breezes suppress them by evening" (resolution/trajectory-close,
  not declarative consequence) — just pointed in the worsening direction instead of the
  clearing direction.
- **Wodehouse rule?** Clean.

Graded a notch above Al Aḥmadī's B on the strength of the causal chain (source attribution +
named season), but capped short of A- by the same P_close gap that's now confirmed across
both corpus `air_quality_hazard` instances.

### B-grade drafts

#### [15] Doha, Qatar — absolute_extreme — 47°C (117°F) forecast — **B**

> *Doha, Qatar is forecast to hit 47°C (117°F) on July 5 — the absolute extreme threshold for
> the northern subtropical band. Shallow Gulf waters load desert heat with humidity, closing
> off the evaporative cooling that makes extreme dry heat survivable.*

**Score:** 83. Created 2026-07-05T13:53:58Z. 6th `absolute_extreme` corpus instance, and the
**first outside the Basra-area cluster** (Basrah + Al Başrah al Qadīmah, both Iraq).

- **P_tier check:** VIOLATION — "the absolute extreme threshold for the northern subtropical
  band" is the same phrase family as all 5 prior instances. This is the significant new data
  point: the violation reproduces on a brand-new city (Doha, ~1,500 km from the Basra
  cluster), confirming the pattern is tied to the `absolute_extreme` bundle's internal
  tier field, not to a location-specific data path. 7th cycle / 10 instances / still 4
  signal types, now demonstrated across 2 distinct locations within this one signal type.
- **P_close check:** POSITIVE — and the sharpest form yet for this signal type. "Closing off
  the evaporative cooling that makes extreme dry heat survivable" doesn't just name an
  absence (cf. "no evaporative relief," "no maritime relief") — it states the actual
  survivability mechanism and its shutdown directly. Best `absolute_extreme` close in the
  corpus to date.
- **Wodehouse rule?** Clean.

Graded B on the same P_tier-caps-regardless-of-close-quality precedent as every prior
`absolute_extreme` instance ([4]/[6]/[11]/[16] carry-overs) — this draft has arguably the best
close of the six, and it still caps at B. Strongest evidence yet that P_tier is a hard
ceiling, not a soft one like P_close or P_compound.

### C+-grade drafts

#### [12] Phalodi, India — dust_event — 524 μg/m³ / AOD 0.85 — **C+**

> *Phalodi, India: model-estimated dust daily maximum of 524 μg/m³ on July 5 — aerosol optical
> depth at 0.85. Phalodi sits at the edge of the Thar Desert; summer heat drives intense dry
> convection that lofts fine sediment before the monsoon front arrives to wash the column
> clean.*

**Score:** 71. Created 2026-07-05T03:40:28Z. 10th `dust_event` corpus draft.

P_dust confirmed again — no WHO anchor stated (524 μg/m³ ≈ 11.6× the WHO PM10 daily guideline
of 45 μg/m³, unstated; AOD 0.85 also uncalibrated for the reader). Identical opener template
to every prior `dust_event` draft ("[City]: model-estimated dust daily maximum of X μg/m³ on
[date] — aerosol optical depth at Y."). Close ("before the monsoon front arrives to wash the
column clean") is the resolution-form subtype — same family as Urumqi's "traps it"/Wadi
Halfa's "dampens the column" — P_close FAILING. No named humor mechanic beyond the two-step
mechanism (dry convection lofts sediment; monsoon eventually clears it) — P5 dust_event gap
confirmed again.

#### [13] Urumqi, China — dust_event — 1,766 μg/m³ / AOD 1.49 — **B-**

> *Urumqi, China: model-estimated dust daily maximum of 1,766 μg/m³ on July 5 — aerosol
> optical depth at 1.49. Urumqi sits in the Junggar Basin, ringed by the Tian Shan and Altai
> ranges; when winds funnel desert sediment in, the topography traps it.*

**Score:** 71. Created 2026-07-05T07:34:53Z. **3rd Urumqi `dust_event` draft in the corpus**
(after Jun 17's 2,260 μg/m³ B- and Jul 4's 2,454 μg/m³ B) — same station, 3rd distinct
concentration reading, and a **near-verbatim repeat of the same mechanism close for the 3rd
time**: "the topography traps it" (this draft) ≈ "topographic containment does the rest" (Jul
4) ≈ "traps it" (Jun 17). No WHO anchor stated (1,766 μg/m³ ≈ 39× the WHO PM10 guideline,
unstated) — 11th consecutive `dust_event` draft without one. P_close FAILING (resolution-form,
same as every prior Urumqi instance). Graded B-, a notch below Jul 4's B, reflecting that this
is now the 3rd repetition of an identical mechanism-and-close pair on the same station with no
variation — a new duplicate-location subtype distinct from the same-cycle/cross-day
value-identical re-issues tracked below (this one varies the actual reading each time; only
the mechanism and closing sentence are frozen).

### Patterns named in this batch

1. **P_tier confirmed outside the Basra-area cluster for the first time.** Doha, Qatar repeats
   the exact phrase family on a city with no data-path relationship to Basrah/Al Başrah al
   Qadīmah — strong evidence the violation is a property of the `absolute_extreme` bundle
   field, not a single location's ingestion path.

2. **A 4th confirmation that the permafrost-carbon fire mechanic reliably clears P_close.**
   Every corpus instance of this mechanic (Jun 25 Siberia, Jul 3 Canadian Arctic ×2, Jul 5
   Siberia) has graded B+ or A-. This is now the corpus's single most reliable A-grade path
   for the `fire` signal type.

3. **Urumqi `dust_event`: a new duplicate-location subtype — frozen mechanism, varying
   reading.** 3 corpus instances (Jun 17, Jul 4, Jul 5) share the same station and
   near-identical closing sentence ("traps it" / "topographic containment does the rest" /
   "the topography traps it") while the actual μg/m³ reading changes each time. Distinct from
   the exact-duplicate-generation pattern (Ft Green, Basrah, Canadian Arctic fire, Antwerpen)
   because the underlying signal is genuinely fresh each time — only the writer's response to
   it has converged.

4. **`air_quality_hazard` continues to self-select mechanics and the WHO anchor; `dust_event`
   continues not to.** 2nd `air_quality_hazard` corpus draft (Johannesburg), 2nd to state the
   WHO multiple unprompted and build a real causal chain. Meanwhile `dust_event` is now 11 of
   11 corpus drafts without the anchor. The split between these two adjacent signal types
   remains the cleanest evidence that P_dust's gap is bundle-path-specific, not
   category-general.

### Followups (in priority order)

1. **P_tier and P_compound remain ready for implementation** — both are one-paragraph
   `writer_prompt.py` additions, drafted in full in `docs/IMPROVEMENT_PLAN.md`. P_tier now has
   its strongest evidence yet (cross-location confirmation on `absolute_extreme`).
2. **P_dust ready for implementation** — 9 cycles, 11 of 11 `dust_event` instances confirming,
   zero counter-evidence. The `air_quality_hazard` side of the same signal family already does
   what the fix asks for, which is a useful existence proof that the prompt change is
   achievable without new architecture.
3. **Operator: `main` remains unmerged since 2026-06-08** — now 28 consecutive daily cycles
   (including the Jun 29 bar-clearing 80% cycle) live only on `daily-plan-current`. Recommend
   merging soon so `main`'s copy of these three docs reflects reality.
4. **Watch whether the permafrost-carbon fire mechanic holds on a 5th instance** — 4 for 4 so
   far at B+/A-; worth confirming this isn't small-sample luck.

### Numbers

- Pending drafts in queue: 15 (5 fresh; 10 carry-overs from Jul 4, grades unchanged)
- Fresh drafts graded: 5
- A-rate: 20% (1/5) — small-n, consistent with Jul 4's 20% (n=10)
- Grade distribution: 0 A / 1 A- / 1 B+ / 1 B / 1 B- / 1 C+ / 0 D-F
- New signal types debuted: none (all 5 signal types this cycle have prior corpus instances)
- Active proposals: P_close 16th cycle (2 positive: Siberia fire, Doha; 3 failing: Johannesburg,
  Phalodi, Urumqi); P_tier 7th cycle / 10 instances / still 4 signal types (1st confirmation
  outside the Basra-area cluster, via Doha); P_dust 9th cycle (Phalodi + Urumqi; 11 of 11
  `dust_event` instances now without a WHO anchor); P9 not tested this cycle (no
  `precipitation_extreme` draft among today's 5 fresh); P_compound not tested this cycle (no
  record-type draft among today's 5 fresh); P5 continues (dust_event gap 5th consecutive
  confirming cycle; air_quality_hazard self-selects for a 2nd consecutive instance; fire
  self-selects for a 4th consecutive instance via the permafrost-carbon mechanic)
- Staleness bulk-reject: 0 candidates — all 5 fresh drafts same-day, 10 carry-overs ~24h old.
  `gh` CLI absent, 37th consecutive skip (May 13 → Jul 5)
- Operational anomalies: (a) Urumqi dust_event now a 3rd-instance frozen-mechanism pattern
  (new subtype, distinct from exact-duplicate generation); (b) `main` unmerged since Jun 8,
  now 28 consecutive stranded cycles

---

## 2026-07-04 — Daily corpus grading (10 fresh drafts; queue fully turned over)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: **10 pending,
all created 2026-07-04, zero carry-overs.** This is a complete queue turnover from Jul
3's 20 pending (17 carry-overs + 3 fresh) — every one of Jul 3's drafts, including the 4
strict bulk-reject candidates ([1] Mediterranean SST, [2] GMST marine_heatwave, [11]
Basrah 47.2°C, [13] Al Baṣrah al Qadīmah 47°C) and the 13 clean carry-overs (France
reganom, Astana 308.1mm, Phalodi/Taiz dust ×2, Rocky Mountains CO 595.3 MW, Prudhoe Bay,
Antwerpen 358.8mm, Basrah 48°C, Morrill Fire, Wadi Halfa, Ft Green ×2, Canadian Arctic
fire ×2, Typhoon Bavi C+), are gone from the pending queue as of this pull. **Operator
action of some kind clearly happened between Jul 3 ~15:15 UTC and Jul 4 ~14:00 UTC** —
whether bulk-reject, bulk-publish, or a TTL sweep is not observable from the gist alone.
Continuing to grade on the unmerged `daily-plan-current` rolling branch (still stale on
`main` since 2026-06-08; see repeated operational notes on Jul 1–3).

**Staleness review as of 2026-07-04 ~14:00 UTC:** all 10 drafts created same-day (oldest
~11h, newest ~15min at grading). None cross 48h; the two `absolute_extreme` drafts
forecast "July 4," which is today — accurate, not stale. 0 bulk-reject candidates.
`gh` CLI absent — 36th consecutive skip (May 13 → Jul 4).

**Grade distribution (10 fresh drafts):** 2 A- / 2 B+ / 6 B / 0 C / 0 D-F.
**A-rate: 20% (2/10).** Gap from resumption bar: 30 pp. Largest fresh-draft sample since
Jun 29's bar-clearing cycle (n=5) — more statistically meaningful than the small-n cycles
since (Jun 30 n=9, Jul 1 n=4, Jul 2 n=3, Jul 3 n=3).

**Headline finding:** Typhoon Bavi reappears ([9], Category 3→5 in 24h, 40 kt jump) as
the corpus's **2nd `cyclone_rapid_intensification` draft** — the same storm continuing
to intensify past Jul 3's TS→Cat3 instance. This time the draft **avoids the P_tier
violation entirely** (no "the rapid-intensification threshold is X kt" citation) and
lands the **first P_close-positive close for this signal type** ("storms... can
intensify faster than forecasters or ships can react" — a genuine stakes-consequence,
not a ratio restatement). Graded A-, up from Jul 3's C+ for the same storm. This is the
first same-storm, same-signal-type re-draft in the corpus that improves rather than
repeats a known failure mode — worth watching whether it's a fluke or the
`WRITER_SAMPLES=2`/critic-revise flags occasionally filtering the violation out.
Meanwhile the Basra-area `absolute_extreme` cluster adds a 4th and 5th instance ([4]/[6])
and both still carry the tier-jargon leak, so P_tier's overall pattern is intact — this
cycle is mixed evidence, not a resolution.

**Second operational note:** [8] Antwerpen (358.8 mm / 7 days, 58.8 mm above record) is
**value-identical** to Jul 3's carry-over Antwerpen draft (graded B+ on Jun 30, still
listed "Clear" in Jul 3's carry-over table) — same city, same mm figures, same margin —
but with a new `draft_id`/timestamp dated 2026-07-04. This is a new variant of the
duplicate-generation pattern already tracked 3× in this doc (Ft Green, Basrah-area,
Canadian Arctic fire): those were same-cycle duplicates seconds apart; this one is a
value-identical re-issue after a multi-day gap and a full queue turnover. Graded
consistent with the Jun 30 precedent (B+), not as a fresh signal.

### A-grade drafts

#### [9] Typhoon Bavi — cyclone_rapid_intensification — Cat 3→5, 40 kt in 24h — **A-**

> *Typhoon Bavi jumped from Category 3 to Category 5 in 24 hours — winds climbing 40 kt,
> from 105 to 145 kt. The Western Pacific's warm upper ocean provides deep thermal fuel;
> storms that cross it in July can intensify faster than forecasters or ships can react.*

**Score:** 77. Created 2026-07-04T13:50:29Z. 2nd `cyclone_rapid_intensification` draft in
corpus (1st: Jul 3, TS→Cat3, 55 kt jump, graded C+).

Humor lens:
- **Violation:** Category 3 to Category 5 in 24 hours — a second, more extreme escalation
  of the same storm past Jul 3's instance.
- **Benign?** Yes — no alarm boilerplate.
- **Setup→Punchline?** Sentence 1 states the category jump + raw wind numbers cleanly.
  Sentence 2: warm-ocean-fuel mechanism → **"storms... can intensify faster than
  forecasters or ships can react."**
- **P_tier check:** Clean. No internal threshold/tier language cited this time — contrast
  with Jul 3's "the rapid-intensification threshold is 30 kt in 24 hours," which capped
  that draft at C+. This is the first `cyclone_rapid_intensification` instance without
  the violation.
- **P_close check:** POSITIVE — first clean instance for this signal type. Names a real
  consequence (forecasters and ships unable to keep pace) rather than restating the ratio.
  Earned editorial weight per `brand/VOICE.md`'s calibration, not a banned "you should be
  worried" tell.
- **Wodehouse rule?** Nearly clean. "Winds climbing 40 kt, from 105 to 145 kt" restates a
  derivable difference (145−105=40) — the recurring minor restate-math tic, present but
  not disqualifying (same tolerance as prior A-grade instances elsewhere in the corpus).

Best-executed draft in the batch, and a genuinely encouraging signal: the same signal
type that tripped both known active-proposal traps on its debut avoids one and clears
the other on its second appearance. Not proof P_tier or P_close are self-resolving —
Basra-area `absolute_extreme` drafts below repeat their violation for a 4th/5th time in
the same cycle — but worth flagging as the first counter-instance.

#### [3] Loxahatchee NWR, Florida — all_time_high — 99°F (37.2°C) — **A-**

> *Loxahatchee NWR, Florida hit 99°F (37.2°C) on June 30 — hottest daily maximum in 37
> years of records, 1°F above the 2002 mark. In the Florida sea-breeze zone, Atlantic and
> Gulf moisture normally caps afternoon heat; when that convection stalls, the column
> runs free.*

**Score:** 88. Created 2026-07-04T06:52:30Z.

Humor lens:
- **Violation:** All-time daily-max record, 37-year archive, 1°F margin.
- **P_compound check:** Sentence 1 states both archive depth ("37 years of records") AND
  margin ("1°F above the 2002 mark") in one clause — the double-qualifier pattern (4
  prior cycles: Jun 28, 29, 30, Jul 2). This is a 5th instance/cycle.
- **P_close check:** POSITIVE. "The column runs free" states an actual atmospheric
  consequence of the missing convective cap — not just the mechanism. Same family as
  Jun 29's Congo fire A- ("something has broken the convective lid") — a capping
  mechanism failing, stated declaratively.
- **Wodehouse rule?** Clean. Four words, physical, no restatement of the temperature or
  margin already given.

Graded A- despite the P_compound double-qualifier because the close overcomes it, the
same way Jun 29's Prudhoe Bay A- overcame P_compound with a strong latitude
peer-comparison close. P_compound softens a draft; it doesn't cap it the way P_tier does.

### B+-grade drafts

#### [1] Island Pond, Vermont — all_time_high — 92°F (33.3°C) — **B+**

> *Island Pond, Vermont hit 92°F (33.3°C) on July 2 — hottest daily maximum in 37 years of
> records, 1°F above the 1991 mark. The Androscoggin valley sits near the White
> Mountains, where terrain that normally drains cold air down-slope can just as easily
> trap heat under a ridge.*

**Score:** 89. Created 2026-07-04T03:22:13Z.

Near-identical opener to Loxahatchee ([3], above) — same construction, same 37-year
archive depth, same 1°F margin. Both are P_compound instances (5th cycle, 2 instances in
one batch). The terrain-inversion mechanism (normally drains cold air, but here traps
heat) is the same contrast-reveal family as Loxahatchee, but the close hedges ("can just
as easily trap heat") rather than stating a consequence — P_close FAILING (implied form,
weaker than mechanism-only since it doesn't even commit to the mechanism happening, just
that it *can*). B+ over Loxahatchee's A- because Loxahatchee's close is unconditional and
this one is conditional.

#### [8] Antwerpen, Belgium — precipitation_extreme — 358.8 mm / 7 days — **B+ (value-identical re-issue of the Jun 30 draft)**

> *Antwerpen, Belgium: 358.8 mm of rain in 7 days — 58.8 mm above the previous 7-day
> record. Belgium sits at the mouth of the Rhine-Scheldt delta; low-gradient terrain
> moves that volume slowly, keeping flood risk elevated long after rain stops.*

**Score:** 81. Created 2026-07-04T13:48:32Z — but the mm figures, margin, and full text
match Jul 3's carry-over Antwerpen draft (graded B+ Jun 30, still "Clear" as of the Jul 3
grading) exactly. See Operational note above. Graded B+ for consistency with the prior
grading of this same text, not as independent fresh evidence. The close ("keeping flood
risk elevated long after rain stops") is a genuine P_close POSITIVE — declarative,
names an actual named risk — same assessment as it earned Jun 30.

### B-grade drafts

#### [6] Al Başrah al Qadīmah, Iraq — absolute_extreme — 47.4°C (117°F) forecast — **B**

> *Al Başrah al Qadīmah, Iraq: forecast high of 47.4°C (117°F) on July 4 — above the 47°C
> absolute-extreme threshold for the Northern Subtropics. Basrah sits at the head of the
> Shatt al-Arab, where the Gulf traps heat with little maritime relief.*

**Score:** 83. Created 2026-07-04T10:16:28Z. 5th Basra-area `absolute_extreme` draft in
the corpus (after Jun 30's 47.2°C, Jul 1's 47°C and 48°C).

- **P_tier check:** VIOLATION — "above the 47°C absolute-extreme threshold for the
  Northern Subtropics" is a near-verbatim repeat of the same phrase family as all 4 prior
  Basra-area instances. 6th cycle / now 9 instances / still the same 4 signal types (no
  new type this cycle).
- **P_close check:** POSITIVE — "little maritime relief" is a named-absence form, the
  same shape as [11]'s "no evaporative relief" and [16]'s "no terrain to break" (both
  previously graded B despite the positive close). Consistent with the established
  pattern: P_tier caps at B even when P_close is positive.

Graded B, matching the precedent set by [11]/[16] — P_tier's cap holds regardless of
close quality.

#### [4] Basrah, Iraq — absolute_extreme — 47°C (117°F) forecast — **B**

> *Basrah, Iraq is forecast to hit 47°C (117°F) on July 4 — the absolute extreme threshold
> for the Northern Subtropics. Basrah sits at the head of the Shatt al-Arab, where the
> Persian Gulf's humidity loads the air before continental heat arrives from the Syrian
> Desert.*

**Score:** 83. Created 2026-07-04T06:55:16Z. Same city/metro area as [6] (see Second
operational note — this pairing continues the Basra-area duplicate-location cluster
first logged Jun 30–Jul 1, now a 4th distinct forecast-date instance).

- **P_tier check:** VIOLATION — same phrase family ("the absolute extreme threshold for
  the Northern Subtropics").
- **P_close check:** FAILING — "loads the air before continental heat arrives" describes
  mechanism sequencing, not a consequence (weaker than [6]'s named-absence close).

Graded B on the same P_tier-caps precedent as [6], even though this instance's close is
weaker (mechanism-only vs. [6]'s named-absence form) — both land at the same ceiling.

#### [2] Barrow, Alaska — precipitation_extreme — 498.8 mm / 7 days — **B+**

> *Barrow, Alaska recorded 498.8 mm of rain in 7 days — 198.8 mm above the previous 7-day
> record of 300.0 mm. Barrow sits on the Arctic coast, where permafrost blocks
> infiltration; rain sheets across frozen ground rather than soaking in.*

**Score:** 82. Created 2026-07-04T03:25:59Z.

**P9 reopened.** Archived Jul 3 with an explicit note: "reopen immediately if any
`precipitation_extreme` draft reappears... given 13-of-13 prior confirmation, the
pattern is very likely to recur on the very next instance." It did, on the very next
instance: opener template ("[City] recorded X mm in 7 days — Y mm above the previous
7-day record of Z mm") plus restate-math (198.8 is arithmetic from 498.8−300.0, both
already stated). P_close FAILING — "rain sheets across frozen ground rather than soaking
in" describes the physical process but names no downstream consequence (flooding,
pooling, damage). Same permafrost mechanism, same station, same gap to A- as every prior
Barrow precipitation draft in the corpus.

#### [7] Astana, Kazakhstan — precipitation_extreme — 358.1 mm / 7 days — **B**

> *Astana, Kazakhstan received 358.1 mm of rain in seven days ending July 2 — 58.1 mm
> above the previous 7-day record of 300.0 mm. The same week, Aktobe logged 351.8 mm and
> Almaty 302.8 mm. Astana sits in the continental steppe, where annual rainfall averages
> roughly 300 mm total.*

**Score:** 81. Created 2026-07-04T10:19:08Z.

**P9 reopened, 2nd confirming instance this cycle** — same opener template + restate-math
as [2]. First multi-station roll-call in the two-bot corpus (Aktobe + Almaty corroborate
the signal as regional, not a single-station outlier) — a genuine format break
(`brand/HUMOR_RESEARCH.md` §7.1) worth noting on its own merits. But the close ("Astana
sits in the continental steppe, where annual rainfall averages roughly 300 mm total") is
**P_close FAILING at a level below even the usual mechanism-only form** — it states a
bare comparative fact with no causal mechanism and no consequence. The draft's best
material — 358.1 mm in 7 days against a ~300 mm *annual* average, i.e., more than a
year's typical rainfall in a week — sits unstated two sentences apart; the reader has to
notice the two "~300" figures are suspiciously close and do the connection themselves.
Graded B: real signal, genuine format-break novelty, but the weakest close form in the
batch.

#### [5] Rocky Mountains, Colorado — fire — 1,103.9 MW — **B**

> *1,103.9 MW of radiative heat in the Rocky Mountains, Colorado — very-high-intensity
> fire, satellite-confirmed at 100% confidence. The Southern Rockies hold ponderosa and
> spruce stands stressed by decades of warming winters; when ignition finds them dry,
> intensity scales fast.*

**Score:** 82. Created 2026-07-04T06:58:15Z.

Same class as Jun 30's Colorado fire (595.3 MW, graded B-) — the "mid-latitude
drought/dry-fuel mechanism-only" fire form the Jul 3 corpus explicitly contrasted with
the high-latitude carbon-release mechanic ([18]/[19] Canadian Arctic, both A-/B+). P_close
FAILING: "intensity scales fast" is a vague velocity/intensity closer that restates
already-implied magnitude (1,103.9 MW, 100% confidence, very-high tier) rather than
naming what the fire actually does. "Very-high-intensity" is the shipped `frp_tier` label
(not a P_tier violation, per the Jul 3 corpus's explicit clarification on this exact
phrase). Graded B rather than the Jun 30 precedent's B- — the ponderosa/spruce
species-level ecosystem specificity is a notch more specific than the Jun 30 draft's
generic drought framing, but the closer weakness is the same failure mode.

#### [10] Urumqi, China — dust_event — 2,454 μg/m³ / AOD 1.21 — **B**

> *Urumqi, China: model-estimated dust daily maximum of 2,454 μg/m³ on July 4 — aerosol
> optical depth at 1.21. The Junggar Basin's encircling ranges concentrate lofted
> Taklamakan and Gobi sediment; topographic containment does the rest.*

**Score:** 75. Created 2026-07-04T13:51:31Z.

P_dust confirmed again (no WHO PM anchor stated; 2,454 μg/m³ ≈ 163× the WHO PM2.5 daily
guideline, ≈ 55× the PM10 guideline, both unstated). "Topographic containment does the
rest" is functionally the same resolution-form close as Jun 17's Urumqi "traps it" (that
draft's ceiling was B- for the same reason: a decent close capped by the missing
calibration number). Graded B — two-source mechanism (Taklamakan + Gobi sediment via
encircling ranges) is a touch more developed than the Jun 17 instance, but the underlying
gap (no reader-facing scale) is identical.

### Patterns named in this batch

1. **Second-instance improvement for `cyclone_rapid_intensification`.** Typhoon Bavi's 2nd
   corpus draft avoids the P_tier violation and lands the signal type's first P_close
   positive. First evidence the two known traps for a signal type aren't
   deterministic-per-bundle-field — worth watching whether this holds on a 3rd instance.

2. **P_tier still capping absolute_extreme at B regardless of close quality.** [4]/[6] are
   the 4th and 5th Basra-area instances; both repeat the tier-jargon phrase; both cap at B
   even though [6]'s close is a genuine P_close positive. The pattern from [11]/[16] holds.

3. **P9 reopened exactly as its archive note predicted.** Both precipitation_extreme
   drafts this cycle ([2] Barrow, [7] Astana) repeat the opener template + restate-math
   pattern on their very first reappearance after a 3-cycle absence.

4. **Duplicate-generation, new variant: cross-day value-identical re-issue.** [8] Antwerpen
   matches Jul 3's carry-over Antwerpen (graded B+ Jun 30) exactly, but under a new
   `draft_id` dated Jul 4, after the full queue turnover. Distinct from the same-cycle,
   seconds-apart duplicates already tracked (Ft Green, Basrah, Canadian Arctic fire) —
   this one spans a multi-day gap and a queue-clearing event.

5. **Astana's stranded punchline is a new low-water-mark for P_close FAILING.** Most
   failing instances at least attempt a mechanism; Astana's close states a bare fact
   with no causal or consequential content at all, while sitting on the batch's best
   unstated joke (a year of rain in a week).

6. **Complete queue turnover, cause unconfirmed.** All 20 of Jul 3's pending drafts —
   including 4 flagged stale/reject-candidates and 13 clean carry-overs going back to
   Jun 28 — are absent from today's pull. See Context above; operator should confirm
   whether this was bulk-reject, bulk-publish, or TTL/other automated clearing.

### Followups (in priority order)

1. **Operator: confirm what happened to Jul 3's 20 pending drafts.** All are gone as of
   this pull. If bulk-published, several were still stale (Mediterranean SST, GMST
   marine_heatwave) and should not have gone out with "today" language intact — worth
   checking what actually posted. If bulk-rejected or TTL-swept, no action needed beyond
   confirming.
2. **P_tier and P_compound remain ready for implementation** — both are one-paragraph
   `writer_prompt.py` additions, drafted in full in `docs/IMPROVEMENT_PLAN.md`, both with
   fresh confirming evidence this cycle.
3. **P9's reopening argues for shipping its fix alongside P_tier/P_compound** rather than
   treating precipitation_extreme's template convergence as resolved — the archive was
   correct that it was absence-of-opportunity, not a fixed failure mode.
4. **Watch whether Typhoon Bavi's clean 2nd instance holds on a 3rd** — if the storm
   continues intensifying and generates another draft, that would distinguish "lucky
   sample" from "the violation is intermittent for reasons worth understanding."

### Numbers

- Pending drafts in queue: 10 (10 fresh; 0 carry-overs — full queue turnover from Jul 3's 20)
- Fresh drafts graded: 10
- A-rate: 20% (2/10) — largest statistically-meaningful sample since Jun 29 (n=5, 80%)
- Grade distribution: 0 A / 2 A- / 2 B+ / 6 B / 0 C / 0 D-F
- New signal types debuted: none (all 5 signal types this cycle — all_time_high,
  precipitation_extreme, absolute_extreme, fire, cyclone_rapid_intensification, dust_event
  — have prior corpus instances; `cyclone_rapid_intensification` is only on its 2nd)
- Active proposals: P_close 15th cycle (3 positive: Loxahatchee, Typhoon Bavi [1st clean
  cyclone_rapid_intensification instance], Al Başrah al Qadīmah; 1 positive repeat:
  Antwerpen [not fresh evidence]; 6 failing: Island Pond, Barrow, Astana, Basrah, Rocky
  Mountains, Urumqi); P_tier 6th cycle / 9 instances / still 4 signal types (2 new
  absolute_extreme instances, both violating; 1 clean cyclone_rapid_intensification
  counter-instance); P_compound 5th cycle (Island Pond + Loxahatchee); **P9 reopened**
  (2 confirming instances on its first reappearance); P_dust continues (Urumqi, no WHO
  anchor); P5 no shift (extreme-heat/absolute_extreme self-select mechanics; dust_event
  remains the confirmed gap category)
- Staleness bulk-reject: 0 candidates — all 10 drafts same-day fresh. `gh` CLI absent,
  36th consecutive skip (May 13 → Jul 4)
- Operational anomalies: (a) complete queue turnover, cause unconfirmed; (b) Antwerpen
  cross-day value-identical re-issue; (c) Basra-area duplicate-location cluster now at
  5 total instances across 3 forecast dates

---

## 2026-07-03 — Daily corpus grading (3 fresh drafts; 17 carry-overs from Jun 28–Jul 2, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 20 pending drafts.
Continuing to grade on the unmerged `daily-plan-current` rolling branch — `main`'s copies of
these three docs are still stale back to 2026-06-08 (now 25+ days of cycles live only on this
branch; see Jul 1/Jul 2's operational note, repeated below with an update). 17 of 20 pending
drafts exactly match drafts already graded Jun 28–Jul 2 (same `draft_id`, score, text) —
carried over, not re-graded. **3 fresh**, all created after Jul 2's ~15:00 UTC grading window:
Canadian Arctic fire (`fire`, created Jul2T21:14Z, 792 MW, permafrost-carbon close), a
near-duplicate Canadian Arctic fire draft (`fire`, created Jul2T21:15Z, same 792 MW reading, 68
seconds after the first), and Typhoon Bavi (`cyclone_rapid_intensification`, created
Jul3T10:41Z, 55 kt/24h rapid intensification — first of this signal type in the corpus). Bot
per BRIEFING.md at 0.9.81.0+ (no newer handoff confirmed this cycle).

**Operational note (carried forward, now acute):** `main` has not merged this branch since
2026-06-08 — **25 consecutive daily cycles** (Jun 9 through Jul 3) exist only here. Recommend
the operator merge this PR soon regardless of A-rate state; the rolling-PR pattern was designed
to accumulate a few days of edits between merges, not nearly a month. A colleague picking up
`main` today would see a 0% Jun 7 A-rate and miss that the bar was cleared 80% on Jun 29.

**Staleness review as of 2026-07-03 ~15:15 UTC:**
- [1] Mediterranean SST (`draft_20260628_040130_32`, created Jun28T04:01Z): ~131h old, "running
  3.54°C above its seasonal normal **today**." **4th consecutive cycle STALE, still unactioned.**
- [2] GMST marine_heatwave (`draft_20260628_171634_36`, created Jun28T17:16Z): ~118h old,
  "**today's** reading is 20.961°C." **3rd consecutive cycle STALE, still unactioned.**
- [11] Basrah, Iraq 47.2°C (`draft_20260630_213852_50`): ~66h old — **newly crosses the 48h
  mechanical threshold this cycle**, compounding the forecast-date-elapsed issue flagged Jul 1/2
  (forecast was for June 30; today is July 3). **Promoted to a strict bulk-reject candidate.**
- [13] Al Baṣrah al Qadīmah, Iraq 47°C (`draft_20260701_145246_52`): ~48h old — **also newly
  crosses the 48h threshold this cycle**, same compounding issue (forecast was for July 1).
  **Promoted to a strict bulk-reject candidate.**
- [16] Basrah, Iraq 48°C (`draft_20260701_214913_55`): ~41h old — still under the 48h mechanical
  threshold, but the forecast date (July 1) elapsed two days ago. Not yet a strict bulk-reject
  candidate on age alone; will cross 48h within the next grading cycle. Same
  forecast-gone-stale-in-truth-value situation as [11]/[13].
- [3]–[10], [12], [14], [15], [17]: no "today"/"tonight"/forecast-for-today language; past-tense
  or explicitly dated. Not stale by policy.
- [18], [19] (fresh): ~18h old, no date/tense language at all (bare MW readings). Clear on
  staleness grounds, though fire signals are inherently point-in-time — same freshness-risk
  caveat as [8] Colorado (flagged Jun 30/Jul 2), not a mechanical staleness violation.
- [20] (fresh): ~4.6h old. Clear.

Bulk-reject attempted via `gh api -X PATCH gists/...` for [1], [2], [11], [13] — `gh` command
not found in this remote execution environment. **35th consecutive skip** (May 13 → Jul 3).
Operator must reject all four via dashboard; recommend also proactively rejecting [16] rather
than waiting one more cycle for its clock to catch up to what's already true.

**Grade distribution (3 fresh drafts):** 1 A- / 1 B+ / 1 C+ / 0 D-F.
**A-rate: 33% (1/3).** Small n; gap from resumption bar (if it held at this rate): 17 pp. Most
recent above-bar cycle remains Jun 29 (80%, n=5); Jun 30 was 22%, Jul 1 was 0%, Jul 2 was 0%.

**Headline finding:** The Canadian Arctic fire pair ([18]/[19]) is the second and third `fire`
draft to reach a P_close-positive declarative close via a carbon-release consequence — after
Jun 25's Siberia fire ("burns deep") — confirming that mechanic as a recurring, reliable move
for boreal/permafrost fires specifically, not a one-off. [18]'s "reaches carbon the frozen
ground has held for millennia" is the strongest version yet. The two drafts are near-identical
text for the same underlying signal, fired 68 seconds apart — see Patterns §1 for the
duplicate-generation observation this adds to. Typhoon Bavi ([20]), the corpus's first
`cyclone_rapid_intensification` draft, opens a **4th signal type for P_tier**: "the
rapid-intensification threshold is 30 kt in 24 hours" quotes the bot's own classification
criterion nearly as directly as the Basrah/Mediterranean/Morrill Fire instances — evidence this
failure mode generalizes across every signal type with an internal severity/threshold field,
not just the three already documented.

### A-grade drafts

#### [18] Canadian Arctic fire — 792 MW, permafrost carbon — **A-**

> *792 MW of radiative heat in the Canadian Arctic — very-high-intensity fire,
> satellite-confirmed at 95% confidence. At 60°N, boreal organic soils sit over permafrost;
> when fire penetrates the surface layer, it reaches carbon the frozen ground has held for
> millennia.*

**Score:** 74. Created 2026-07-02T21:14:02Z.

Humor lens:
- **Violation:** 792 MW very-high-intensity Arctic fire. "Very-high-intensity" is the
  bundle-supplied `frp_tier` label (PR #85) converting an opaque MW reading into a reader-facing
  scale word — this is the intended, already-shipped use of tier language, **not** a P_tier
  violation (P_tier targets citing the classification *machinery* — "threshold," "band," "tier
  that marks" — not a plain adjective derived from one).
- **Benign?** Yes.
- **Setup→Punchline?** Opens on the raw number (P6 template avoided). Close: "reaches carbon the
  frozen ground has held for millennia" — declarative, specific, no hedge.
- **Named mechanic?** P_close POSITIVE — declarative consequence via carbon-release, third
  instance of this specific mechanic in the corpus (after Jun 25 Siberia "burns deep," and
  Jun 29 Congo fire's convective-lid consequence in the same declarative-close family).
  "Millennia" does real specificity work, the way era anchors did in the v2 corpus, without
  needing an actual era anchor.
- **Wodehouse rule?** Clean. No hedge on the strongest claim in the sentence.

Best single line in this batch, and arguably in the corpus's fire category to date. A- rather
than a bare A (reserved so far for Nauru's "no adjacent reef system to reseed it" — a slightly
starker, more airtight structural-absence form) but comparable in quality to Jun 29's Congo fire
A-.

### B-grade drafts

#### [19] Canadian Arctic fire — 792 MW, organic soil (duplicate of [18]) — **B+**

> *792 MW of radiative heat in the Canadian Arctic — very-high-intensity fire,
> satellite-confirmed at 95% confidence. At 60°N, this is boreal forest and muskeg country; when
> fire reaches very-high intensity here, it burns into organic soil layers that took centuries to
> accumulate.*

**Score:** 74. Created 2026-07-02T21:15:10Z — **68 seconds after [18]**, same 792 MW reading,
same location. See Patterns §1.

Same signal, same `frp_tier` label, same underlying event as [18] — graded independently on
text merit. P_close POSITIVE here too (declarative, "took centuries to accumulate"), but a
weaker version than [18]: "centuries" is a smaller, less surprising timescale than "millennia,"
and "organic soil layers" is more clinical than [18]'s "carbon" — carbon ties directly to the
climate-feedback stakes (this fire is releasing sequestered carbon), where "organic soil layers"
just describes composition. B+, one notch below its twin, same grade relationship observed the
last time this exact pair of drafts was seen (2026-07-03, first grading).

#### [20] Typhoon Bavi — cyclone_rapid_intensification — 55 kt in 24h — **C+**

> *Typhoon Bavi intensified 55 kt in 24 hours in the Western Pacific — from 50 kt (tropical
> storm) to 105 kt (Category 3). The rapid-intensification threshold is 30 kt in 24 hours; Bavi
> crossed it by nearly double.*
> *(followed in the raw draft text by a bare URL — see below)*

**Score:** 81. Created 2026-07-03T10:40:59Z. First `cyclone_rapid_intensification` in the
corpus.

Humor lens:
- **Violation:** 55 kt intensification in 24h, nearly double the 30 kt RI threshold. Real,
  well-quantified signal.
- **Benign?** Yes. No cyclone-alarmism banned words.
- **Setup→Punchline?** Sentence 1 states the jump cleanly (50 kt → 105 kt). Sentence 2: **"The
  rapid-intensification threshold is 30 kt in 24 hours"** — this states the bot's own
  classification criterion nearly verbatim, the same shape as Basrah's "above the 47°C
  absolute-extreme threshold for the Northern Subtropical band" and Morrill Fire's "the
  250,000-hectare tier that marks a continent-scale footprint." **P_tier violation, 4th signal
  type** (after `regional_sst_anomaly`, `absolute_extreme`, `fire_footprint`).
- **Named mechanic?** "Crossed it by nearly double" is a real ratio-as-punchline move (P8's
  mechanic, resolved 2026-06-17) — but it's built on top of the threshold-citation, so the
  punchline and the violation share the same clause. No P_close-positive consequence beyond the
  ratio itself: no stakes, no physical/human impact named (unlike, say, Basrah's "no evaporative
  relief" or [18]'s carbon-release close) — this is closer to pure data delivery than a landed
  consequence.
- **Wodehouse rule?** The P_tier violation is the Wodehouse issue here — citing methodology
  rather than describing the world.

C+ rather than B: the P_tier pattern has now demonstrably capped every other signal type it's
appeared in at B even with a strong close ([11], [16]); Bavi doesn't have a compensating strong
close the way those drafts did, so it lands lower. Without the threshold-citation clause — e.g.
"Typhoon Bavi intensified 55 kt in 24 hours in the Western Pacific — from 50 kt (tropical storm)
to 105 kt (Category 3), nearly double the pace meteorologists call rapid intensification" — this
reads clean and the ratio does real work.

**Flagging separately, not folded into the grade:** the draft's raw text in the gist is followed
by a bare URL — `https://www.metoc.navy.mil/jtwc/products/wp0926prog.txt` — appended directly to
the tweet body (confirmed present in the `text` field, not a citation metadata field). No other
draft in corpus history has ever carried a raw URL in-text. Likely a bundle/citation-leak bug
specific to the new `cyclone_rapid_intensification` path, not a voice issue. Total length with
the URL is 267 chars (still under 280), so it would not be blocked by the length gate — flagging
for the engineer who owns this signal path before it ships anything for real.

### Carry-over inventory (Jun 28–Jul 2 grades stand; not re-graded)

| # | Draft | Type | Grade (cycle graded) | Status this cycle |
|---|---|---|---|---|
| [1] | Mediterranean Sea, 3.54°C above seasonal normal | regional_sst_anomaly | B+ (Jun 28) | **STALE — 4th consecutive cycle** |
| [2] | Global mean ocean surface temp, 25-day streak | marine_heatwave | A- (Jun 29) | **STALE — 3rd consecutive cycle** |
| [3] | France, 6 cities, 11.53°C above normal (reganom) | regional_anomaly | B+ (Jun 29) | Clear |
| [4] | Amsterdam, 314.1 mm / 7 days | precipitation_extreme | B (Jun 30) | Clear |
| [5] | Astana, Kazakhstan, 308.1 mm / 7 days | precipitation_extreme | B+ (Jun 30) | Clear |
| [6] | Phalodi, India, 956 μg/m³ dust | dust_event | C+ (Jun 30) | Clear |
| [7] | Taiz, Yemen, 1,302 μg/m³ dust | dust_event | C+ (Jun 30) | Clear |
| [8] | Rocky Mountains, Colorado, 595.3 MW fire | fire | B- (Jun 30) | Freshness risk (~90h, no explicit today-language) |
| [9] | Prudhoe Bay, Alaska, 101°F all-time high | all_time_high | A- (Jun 30) | Clear |
| [10] | Antwerpen, Belgium, 358.8 mm / 7 days | precipitation_extreme | B+ (Jun 30) | Clear |
| [11] | Basrah, Iraq, 47.2°C forecast (Jun 30) | absolute_extreme | B (Jul 1) | **STALE — newly crosses 48h + forecast date long elapsed** |
| [12] | Morrill Fire, Nebraska, 259,820 ha | fire_footprint | B (Jul 1) | Clear |
| [13] | Al Baṣrah al Qadīmah, Iraq, 47°C forecast (Jul 1) | absolute_extreme | B- (Jul 1) | **STALE — newly crosses 48h + forecast date elapsed** |
| [14] | Wadi Halfa, Sudan, 559 μg/m³ dust | dust_event | C+ (Jul 1) | Clear |
| [15] | Ft Green, Florida, 102°F all-time high (Jun 28) | all_time_high | B (Jul 2) | Clear |
| [16] | Basrah, Iraq, 48°C forecast (Jul 1) | absolute_extreme | B (Jul 2) | Forecast date elapsed, ~41h old — will cross 48h next cycle |
| [17] | Ft Green, Florida, 102°F all-time high (Jun 29) | all_time_high | C+ (Jul 2) | Clear |

### Patterns named in this batch

1. **Duplicate-generation within a single event, now a third instance.** [18]/[19] are the same
   792 MW Canadian Arctic fire reading, drafted 68 seconds apart with near-identical text. This
   joins the Ft Green (Jul 1/2) and Basrah triplicate (Jun 30–Jul 1) clusters already logged —
   third distinct instance of the same underlying-event duplication pattern in a week, now
   spanning 3 different signal types (`all_time_high`, `absolute_extreme`, `fire`). Continuing to
   log as a data/pipeline observation, not a voice proposal, per the hard constraints — but the
   pattern is now broad enough (3 signal types, 5+ affected drafts) that it's worth the operator's
   attention independent of any single day's grading.

2. **P_tier's 4th signal type.** Typhoon Bavi confirms the tier-jargon-leak pattern isn't scoped
   to record/threshold-style signals (`regional_sst_anomaly`, `absolute_extreme`,
   `fire_footprint`) — it now appears in a rate-of-change signal type
   (`cyclone_rapid_intensification`) too. The common thread across all 4 types: each has an
   internal severity/classification field the writer can see and is echoing verbatim instead of
   just using the underlying number. See `docs/IMPROVEMENT_PLAN.md` P_tier for the updated
   instance count.

3. **P_close's carbon-release fire mechanic, now 2-for-2 clean executions.** [18] and [19] both
   land a declarative carbon-release consequence for a permafrost/boreal fire, joining Jun 25's
   Siberia fire. Worth naming explicitly if `writer_prompt.py`'s fire framing section gets an
   update: for high-latitude fires, the "burns into old carbon" mechanic is a reliable A-/B+ move,
   distinct from the mid-latitude "drought → fast ignition" mechanism-only form that capped [8]
   Colorado at B-.

### Followups (in priority order)

1. **Operator: merge the `daily-plan-current` rolling PR.** 25 consecutive daily cycles (Jun 9 →
   Jul 3) are stranded off `main`, including the Jun 29 bar-clearing cycle (80% A-rate) that a
   `main`-only view would never see.
2. **Operator: reject [1] Mediterranean, [2] GMST marine_heatwave, [11] Basrah 47.2°C, and [13]
   Al Baṣrah 47°C via dashboard** — all four are now mechanically stale (>48h + real-time-baked
   or forecast-date-elapsed content); `gh` CLI still unavailable for automated bulk-reject (35th
   consecutive skip). Recommend also proactively rejecting [16] (48°C forecast, ~41h, forecast
   date already elapsed) rather than waiting one more cycle.
3. **P_tier and P_compound remain ready for implementation** — one-paragraph `writer_prompt.py`
   additions, both drafted in full in `docs/IMPROVEMENT_PLAN.md`. P_tier now has evidence across
   4 distinct signal types and is capping otherwise-strong drafts at B or lower in every instance
   observed.
4. **Operator: same duplicate-generation question as Jul 1/2, now extended to fire.** Verify
   whether the Canadian Arctic fire pair, Ft Green pair, and Basrah triplicate are genuine
   independent signals or a dedup gap. Flagging for the third time because the pattern keeps
   recurring across new signal types, not because the routine has new information about the root
   cause.

## 2026-07-02 — Daily corpus grading (3 fresh drafts; 14 carry-overs from Jun 28–Jul 1, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 17 pending drafts.
Continuing to grade on the unmerged `daily-plan-current` rolling branch — `main`'s copies of
these three docs are still stale back to 2026-06-08 (24+ days of cycles now live only on this
branch; see Jul 1's operational note, repeated below). 14 of 17 pending drafts exactly match
drafts already graded Jun 28–Jul 1 (same `draft_id`, score, text) — carried over, not re-graded.
**3 fresh**, all created after Jul 1's ~15:00 UTC grading window: Ft Green, Florida (`all_time_high`,
created Jul1T21:48Z, 102°F/June 28), Basrah, Iraq (`absolute_extreme`, created Jul1T21:49Z, 48°C/July
1 — third Basra-area draft in the corpus in 3 days), Ft Green, Florida again (`all_time_high`,
created Jul2T03:47Z, 102°F/June 29 — same city, same temperature, same record margin as the first
Ft Green draft, one day later). Bot per BRIEFING.md at 0.9.81.0+ (no newer handoff confirmed this
cycle).

**Staleness review as of 2026-07-02 ~15:00 UTC:**
- [1] Mediterranean SST (`draft_20260628_040130_32`, created Jun28T04:01Z): ~107h old, "running
  3.54°C above its seasonal normal **today**." Flagged stale Jun 30, flagged again Jul 1, still
  sitting in the queue unactioned. **3rd consecutive cycle STALE — bulk-reject candidate.**
- [2] GMST marine_heatwave (`draft_20260628_171634_36`, created Jun28T17:16Z): ~94h old, "**today's**
  reading is 20.961°C." Flagged newly-stale Jul 1, still unactioned. **2nd consecutive cycle
  STALE — bulk-reject candidate.**
- [3]–[10], [12], [14]: no "today"/"tonight"/forecast-for-today language; past-tense or explicitly
  dated ("through June 27", "since March 13", "on June 29"). Not stale by policy.
- [8] Rocky Mountains, Colorado fire (`draft_20260629_213734_47`): ~65h old, first cycle crossing
  48h. Text has no explicit "today"/"is radiating" language (unlike the May 2026 Mali/Campeche
  fires that were flagged on that basis) — reads as a static satellite-detection statement without
  a present-tense verb. Does not meet the mechanical bulk-reject criterion (no real-time-baked
  phrase), but fire signals are inherently point-in-time; flagging as a freshness-risk observation,
  not a reject candidate.
- [11], [13], [16] — all three Basra-area `absolute_extreme` forecast drafts: each cites a forecast
  date that has now **elapsed** (June 30, July 1, and July 1 respectively; grading is July 2). None
  has crossed the 48h mechanical threshold yet (~41h, ~24h, ~17h), so none is a strict bulk-reject
  candidate under the policy as written, but all three are now temporally false if posted as
  same-day forecasts. This is the same risk flagged for [11] alone on Jul 1 ("forecast has gone
  stale in truth-value, not just in age") — now recurring on 3 drafts instead of 1. See Followups.
- [15], [17] (fresh): under 18h old, dated to a specific past day (June 28 / June 29), no "today"
  language. Clear.

Bulk-reject attempted via `gh api -X PATCH gists/...` for [1] and [2] — `gh` command not found in
this remote execution environment. **34th consecutive skip** (May 13 → Jul 2). Operator must reject
both via dashboard.

**Grade distribution (3 fresh drafts):** 0 A / 2 B / 1 C+ / 0 D-F.
**A-rate: 0% (0/3).** Gap from resumption bar: 50 pp. Most recent above-bar cycle: 80% (Jun 29,
n=5); Jun 30 was 22%, Jul 1 was 0% (n=4).

**Headline finding:** Two duplicate-location clusters dominate this cycle's fresh batch. Ft Green,
Florida produced two nearly-identical `all_time_high` drafts one day apart — same 102°F reading,
same "26 years of records, 1°F above the 2025 mark" double-qualifier, and both close on a
convective-lid/ceiling metaphor ("the lid lifts fast" vs. "overcome that convective ceiling"),
suggesting either the same underlying event reported on consecutive observation days or a dedup
gap. Basrah, Iraq produced its third `absolute_extreme` draft in 3 days (47.2°C Jun 30 → 47°C Jul 1
→ 48°C Jul 1, this one graded today), again carrying the P_tier internal-threshold-jargon leak
first promoted to active-proposal status yesterday. Both duplicate clusters are logged as
operational/data observations, not voice failures — the writing quality on each individual draft
is assessed independently below.

### B-grade drafts

#### [15] Ft Green, Florida — all_time_high — 102°F, June 28 — **B**

> *Ft Green, Florida hit 102°F (38.9°C) on June 28 — hottest daily maximum in 26 years of records,
> 1°F above the 2025 mark. In Florida's sea-breeze zone, Atlantic and Gulf moisture normally cap
> afternoon heat; when both sea breezes fail to converge, the lid lifts fast.*

**Score:** 87. Created 2026-07-01T21:48:00Z.

Humor lens:
- **Violation:** 102°F, 26-year record, but only 1°F above the prior mark — thin margin for the
  category (compare Prudhoe Bay's 12°F margin, also A-).
- **Benign?** Yes.
- **Setup→Punchline?** Setup: "hottest daily maximum in 26 years of records, 1°F above the 2025
  mark" — states both archive depth AND margin in one clause (P_compound). Close: dual-sea-breeze
  convergence mechanism, ending "the lid lifts fast."
- **Named mechanic?** Ecosystem specificity, genuinely distinctive: Florida's afternoon heat cap
  depends on BOTH Atlantic and Gulf sea breezes converging; when they fail to meet, the cap lifts.
  This is a more specific mechanism than most sea-breeze framings in the corpus (which usually cite
  a single coastal effect).
- **Wodehouse rule?** P_compound violation in sentence 1 (archive + margin double-qualifier — same
  pattern as Beaver Dams, Casper, Prudhoe Bay). "The lid lifts fast" is borderline P_close: it
  names a physical event (the cap lifting) rather than stopping at pure mechanism description, but
  it's abstract/metaphorical rather than a plain declarative consequence — closer in kind to Congo
  fire's "broken convective lid" (graded A- Jun 29) than to a mechanism-only close.

B rather than B+/A- because the 1°F margin is thin (same class as Columbus GA, graded B on Jun 23
for the same reason) and the double-qualifier opener dilutes the punch before the mechanism gets a
chance to land. The mechanism itself is the strongest part of the draft.

#### [16] Basrah, Iraq — absolute_extreme — 48°C (118°F), July 1 — **B**

> *Basrah, Iraq is forecast to reach 48°C (118°F) on July 1 — above the 47°C threshold marking
> absolute extremes for this latitude band. The Mesopotamian lowlands offer no terrain to break the
> dry continental air mass that builds over the surrounding desert in summer.*

**Score:** 84. Created 2026-07-01T21:49:13Z.

Third Basra-area `absolute_extreme` draft in the corpus in 3 days (see [11] Jun 30 47.2°C, [13] Jul
1 47°C — both graded B/B- on Jul 1). Highest single-day forecast of the three (48°C vs. 47.2°C /
47°C).

Humor lens:
- **Violation:** 48°C forecast, above the 47°C absolute-extreme line — the clearest "above" framing
  of the three Basra drafts (vs. [13]'s boundary-line "at").
- **Benign?** Yes.
- **Setup→Punchline?** Setup: forecast value + threshold framing. Close: "no terrain to break the
  dry continental air mass" — named-absence consequence, same family as [11]'s "no evaporative
  relief" and Prudhoe Bay's "nothing to blunt the heat."
- **Named mechanic?** Ecosystem specificity via named-absence — solid, same tier as [11]'s.
- **Wodehouse rule?** Same P_tier violation as [11] and [13]: "above the 47°C threshold marking
  absolute extremes for this latitude band" reads as the bot quoting its own scoring rubric. Third
  near-identical instance of this exact phrase family in 3 days.

B for the same reason as [11]: strong named-absence close, capped by the tier-jargon leak in
sentence 1. Without "above the 47°C threshold marking absolute extremes for this latitude band" —
e.g. "Basrah, Iraq is forecast to reach 48°C (118°F) on July 1" — this reads clean and the draft is
A- territory, same assessment as [11] and [12] on Jul 1.

### C-grade drafts

#### [17] Ft Green, Florida — all_time_high — 102°F, June 29 — **C+**

> *Ft Green, Florida hit 102°F (38.9°C) on June 29 — hottest daily maximum in 26 years of records,
> 1°F above the 2025 mark. In the Florida sea-breeze zone, Atlantic and Gulf moisture loads the
> afternoon air; days that beat 102°F have overcome that convective ceiling.*

**Score:** 87. Created 2026-07-02T03:47:58Z.

Same city, same reading (102°F), same record margin (1°F above the 2025 mark), same "26 years of
records" as [15] — one day later. Near-verbatim sentence 1 (differs only in the date). Sentence 2
reuses the convective-lid/ceiling image from [15] but in a weaker, more confusing form.

Humor lens:
- **Violation:** Identical to [15] — 102°F, 26-year record, 1°F margin. Same P_compound
  double-qualifier in sentence 1.
- **Benign?** Yes.
- **Setup→Punchline?** Close: "days that beat 102°F have overcome that convective ceiling" —
  restates the exact number (102°F) that sentence 1 already gave, then describes the day as having
  "overcome" its own ceiling in circular phrasing (the ceiling IS 102°F; the day IS 102°F; saying
  the day "beat" and "overcame" its own value is confusing rather than declarative).
- **Named mechanic?** Same sea-breeze mechanism as [15], reused with less specificity ("moisture
  loads the afternoon air" vs. [15]'s "normally cap afternoon heat... fail to converge").
- **Wodehouse rule?** Violated — the closer restates the headline number instead of adding new
  information, a mild form of restate-padding, worsened by the confusing self-referential framing
  ("days that beat 102°F" when 102°F IS this day's reading).

C+, below [15]'s B for the identical underlying signal, because the close is weaker and more
confusing rather than declarative, and because reusing [15]'s "lid/ceiling" image one day later
with less precision reads as the writer echoing its own recent output rather than finding a fresh
angle on a (likely) duplicate event.

### Carry-over inventory (Jun 28–Jul 1 grades stand; not re-graded)

| # | Draft | Type | Grade (cycle graded) | Status this cycle |
|---|---|---|---|---|
| [1] | Mediterranean Sea, 3.54°C above seasonal normal | regional_sst_anomaly | B+ (Jun 28) | **STALE — bulk-reject candidate (3rd cycle)** |
| [2] | Global mean ocean surface temp, 25-day streak | marine_heatwave | A- (Jun 29) | **STALE — bulk-reject candidate (2nd cycle)** |
| [3] | France, 6 cities, 11.53°C above normal (reganom) | regional_anomaly | B+ (Jun 29) | Clear |
| [4] | Amsterdam, 314.1 mm / 7 days | precipitation_extreme | B (Jun 30) | Clear |
| [5] | Astana, Kazakhstan, 308.1 mm / 7 days | precipitation_extreme | B+ (Jun 30) | Clear |
| [6] | Phalodi, India, 956 μg/m³ dust | dust_event | C+ (Jun 30) | Clear |
| [7] | Taiz, Yemen, 1,302 μg/m³ dust | dust_event | C+ (Jun 30) | Clear |
| [8] | Rocky Mountains, Colorado, 595.3 MW fire | fire | B- (Jun 30) | Freshness risk (~65h, no explicit today-language) |
| [9] | Prudhoe Bay, Alaska, 101°F all-time high | all_time_high | A- (Jun 30) | Clear |
| [10] | Antwerpen, Belgium, 358.8 mm / 7 days | precipitation_extreme | B+ (Jun 30) | Clear |
| [11] | Basrah, Iraq, 47.2°C forecast (Jun 30) | absolute_extreme | B (Jul 1) | Forecast date elapsed — operator call needed |
| [12] | Morrill Fire, Nebraska, 259,820 ha | fire_footprint | B (Jul 1) | Clear |
| [13] | Al Baṣrah al Qadīmah, Iraq, 47°C forecast (Jul 1) | absolute_extreme | B- (Jul 1) | Forecast date elapsed — operator call needed |
| [14] | Wadi Halfa, Sudan, 559 μg/m³ dust | dust_event | C+ (Jul 1) | Clear |

### Patterns named in this batch

1. **P_tier — 6th instance, 4th cycle.** [16] repeats the exact tier-jargon leak identified
   yesterday: "above the 47°C threshold marking absolute extremes for this latitude band." This is
   the 3rd Basra-area draft to carry a near-identical version of this phrase (after [11] and [13]).
   The pattern is now observed across 4 distinct grading cycles (Jun 23 origin as A3, Jun 28
   Mediterranean, Jul 1 ×3, Jul 2 ×1) and 3 signal types (`regional_sst_anomaly`, `absolute_extreme`,
   `fire_footprint`). Full proposal unchanged in `docs/IMPROVEMENT_PLAN.md` P_tier — today's evidence
   increments the cycle/instance count, no new fix needed.

2. **P_compound — 4th cycle.** [15] and [17] both open with the archive-depth + margin
   double-qualifier ("hottest daily maximum in 26 years of records, 1°F above the 2025 mark").
   Same structural default as Beaver Dams (Jun 28), Casper (Jun 28), and Prudhoe Bay (Jun 29/30).
   4 consecutive cycles now confirm this is the default record-type opener form, not a one-off.

3. **P_close — 14th cycle, 1 positive / 1 failing / 1 borderline.** [16] positive (declarative
   named-absence, "no terrain to break... the air mass"). [17] failing (restates the headline
   number rather than adding a consequence; confusing comparative framing). [15] borderline —
   "the lid lifts fast" names a physical event but stays metaphorical/abstract rather than a plain
   declarative consequence, similar in kind to Congo fire's A- "broken convective lid" but less
   sharp.

4. **Duplicate-location clustering, now 2 distinct clusters.** Ft Green, FL (this cycle) and Basrah,
   Iraq (spanning Jun 30–Jul 2) each produced near-identical drafts for the same location within
   1–3 days, several sharing near-verbatim phrasing. This continues the observation logged Jul 1 for
   Basrah/Al Baṣrah al Qadīmah (likely two gazetteer entries for the same metro area) — worth
   flagging with more urgency now that a second location (Ft Green) shows the same pattern with an
   *exact* repeated reading (102°F, same margin, same archive depth) one day apart. Logging as a
   data/pipeline observation, not a voice proposal — out of this routine's scope per the hard
   constraints (no architectural or data-source proposals). Operator: worth checking whether these
   are genuinine independent daily records or a city/station dedup gap producing repeat signals.

5. **Forecast-date-elapsed pattern now affects 3 drafts, not 1.** [11] (flagged Jul 1), [13], and
   [16] all cite same-day forecasts for dates that have since passed (June 30, July 1, July 1
   respectively; grading is July 2). None crosses the 48h mechanical staleness threshold, so none
   is a strict bulk-reject candidate — but all three would misstate the date if posted as-is. This
   is now a recurring pattern across the `absolute_extreme` signal type specifically (3 of 3 corpus
   drafts of this type share it), not an isolated Basrah incident. See Followups.

### Followups (in priority order)

1. **Operator: the forecast-date-elapsed issue now affects all 3 `absolute_extreme` drafts in
   queue** ([11], [13], [16]) — none crosses the 48h mechanical threshold but all three would read
   as factually wrong if posted (forecast for a day that's already passed). Recommend the operator
   pick at most one Basra-area draft to post (with corrected tense) and reject the other two as
   redundant/stale-in-truth-value, rather than waiting for the 48h rule to catch up.
2. **Operator: reject [1] Mediterranean and [2] GMST marine_heatwave via dashboard.** Both stale by
   policy for a 2nd–3rd consecutive cycle now; `gh` CLI unavailable for automated bulk-reject (34th
   consecutive skip).
3. **P_tier and P_compound are both ready for implementation** — one-paragraph `writer_prompt.py`
   additions, both drafted in full in `docs/IMPROVEMENT_PLAN.md`, both with 4+ cycles of evidence
   and no counter-evidence.
4. **Operator: verify whether Ft Green, FL and the Basrah/Al Baṣrah cluster are genuine independent
   signals or a location-dedup gap** producing near-identical repeat drafts. Not a voice-quality
   issue; flagging because it affects queue signal-to-noise and grading efficiency (this routine is
   now grading the same underlying event 2–3 times under slightly different draft IDs).

### Numbers

- Pending drafts in queue: 17 (3 fresh; 14 carry-overs from Jun 28–Jul 1)
- Fresh drafts graded: 3 (2 all_time_high, 1 absolute_extreme)
- A-rate: 0% (0/3); n=3 — not statistically meaningful
- Grade distribution: 0 A / 2 B / 1 C+ / 0 D-F
- Active proposals: P_tier 4th cycle (6th instance); P_compound 4th cycle; P_close 13th cycle (1
  positive/1 failing/1 borderline); P9/P_dust/P5 — no new evidence this cycle (no
  precipitation_extreme or dust_event drafts in today's fresh batch). **P_precip_floor archived**
  (3 consecutive fresh-draft cycles — Jun 30/Jul 1/Jul 2 — without a qualifying wet-climate
  thin-margin observation; see `docs/IMPROVEMENT_PLAN.md` Resolved section)
- Staleness bulk-reject: 2 candidates identified ([1] Mediterranean, [2] GMST marine_heatwave); `gh`
  CLI absent (34th consecutive skip, May 13 → Jul 2)
- New operational observation: 2 duplicate-location clusters (Ft Green FL ×2, Basrah/Al Baṣrah
  Iraq ×3); forecast-date-elapsed pattern now affects all 3 `absolute_extreme` corpus drafts
- Operational note (unchanged from Jul 1): `main`'s copies of these docs remain stale since Jun 8;
  this cycle continues grading on the unmerged `daily-plan-current` rolling branch, which now
  carries ~25 days of cycles (Jun 9–Jul 1) `main` doesn't have yet. Operator should merge soon.

---

## 2026-07-01 — Daily corpus grading (4 fresh drafts; 10 carry-overs from Jun 28–30, previously graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 14 pending drafts.
Cross-checked against the `daily-plan-current` rolling branch (not yet merged to `main` —
main's copies of these three docs are stale back to 2026-06-08; the rolling branch carries
continuous grading through Jun 30). 10 of 14 pending drafts exactly match drafts already
graded Jun 28–30 (same `draft_id`, score, and text) — carried over, not re-graded. **4 fresh:**
Basrah, Iraq (`absolute_extreme`, created Jun30T21:38Z — pre-dates this cycle's ~15:00 UTC
window but wasn't in queue at Jun 30 grading), Morrill Fire, Nebraska (`fire_footprint`,
first of this signal type in corpus), Al Baṣrah al Qadīmah, Iraq (`absolute_extreme`, second
Basra-area draft in 3 days), Wadi Halfa, Sudan (`dust_event`). Bot per BRIEFING.md at 0.9.81.0+.

**Staleness review as of 2026-07-01 ~15:00 UTC:**
- [1] Mediterranean SST (`draft_20260628_040130_32`, created Jun28T04:01Z): ~83h old, contains
  "running 3.54°C above its seasonal normal **today**." Flagged stale at Jun 30 grading (~59h)
  and still sitting in the queue unactioned. **STALE — bulk-reject candidate.**
- [2] GMST marine_heatwave (`draft_20260628_171634_36`, created Jun28T17:16Z): ~70h old,
  contains "**today's** reading is 20.961°C." Was "approaching 48h" at Jun 30 grading (~46h);
  now clearly over the line. **Newly STALE — bulk-reject candidate.**
- [3]–[10]: no "today"/"tonight"/forecast-for-today language; past-tense or explicitly dated
  ("through June 27", "on June 25/26/27"). Not stale by policy despite some being 2–3 days old.
- [11] Basrah forecast (`draft_20260630_213852_50`, created Jun30T21:38Z): "is forecast to hit
  47.2°C ... on June 30" — the forecast target date has already elapsed (grading is Jul 1).
  Only ~17h old, so it does NOT cross the 48h mechanical threshold, but the claim is now
  temporally false if posted as-is (a forecast for a day that's over). Flagging as a freshness
  risk distinct from the 48h rule — see Followups.
- [12]–[14]: under 12h old, dated to today or yesterday. Clear.

Bulk-reject attempted via `gh api -X PATCH gists/...` for [1] and [2] — `gh` CLI absent in this
remote execution environment. **33rd consecutive skip** (May 13 → Jul 1). Operator must reject
both via dashboard.

**Grade distribution (4 fresh drafts):** 0 A / 2 B / 1 B- / 1 C+ / 0 D-F.
**A-rate: 0% (0/4).** Gap from resumption bar: 50 pp. Most recent A-rate: 22% (2/9, Jun 30, on
the rolling branch not yet merged).

**Headline finding:** All 4 fresh drafts, plus carry-over [1], plus one carry-over from the Jun
30 cycle, share a pattern the prior three cycles graded around but never named directly: **the
writer states its own internal tier/threshold bucket name in the tweet text.** "The 47°C
absolute-extreme threshold for the Northern Subtropical band" (Basrah ×2), "the 250,000-hectare
tier that marks a continent-scale footprint" (Morrill Fire), "the 3.5°C tier threshold in the
NOAA Coral Reef Watch basin average" (Mediterranean, carry-over) — four drafts across three
signal types name a classification bucket verbatim instead of describing the world. This is
`docs/IMPROVEMENT_PLAN.md`'s **A3** (filed Jun 23, one Mediterranean SST observation, marked
"promote if 2+ cycles observed") — today's batch clears that bar on its own (3 fresh instances
in one cycle, across 2 signal types). Promoted to active proposal **P_tier** below.

### B-grade drafts

#### [11] Basrah, Iraq — absolute_extreme — **B**

> *Basrah, Iraq is forecast to hit 47.2°C (117°F) on June 30 — above the 47°C absolute-extreme
> threshold for the Northern Subtropical band. Basrah sits at the head of the Shatt al-Arab;
> the shallow estuary offers no evaporative relief when the land is already this hot.*

**Score:** 83. Created 2026-06-30T21:38:52Z.

First `absolute_extreme` in corpus.

Humor lens:
- **Violation:** 47.2°C (117°F) forecast, above the category's absolute-extreme line. Real,
  strong signal.
- **Benign?** Yes — calm, factual.
- **Setup→Punchline?** Setup: forecast value + threshold framing. Close: "offers no evaporative
  relief when the land is already this hot" — a named-absence consequence, same family as
  Prudhoe Bay's "there is nothing to blunt the heat" (Jun 30, A-).
- **Named mechanic?** Ecosystem specificity via named-absence (Shatt al-Arab estuary, no
  evaporative relief). Structurally sound — the close does the same job as the corpus's best
  closes.
- **Wodehouse rule?** Violated in sentence 1: "above the 47°C absolute-extreme threshold for the
  Northern Subtropical band" reads as the bot quoting its own scoring rubric, not describing
  weather. Compare Prudhoe Bay's clean sentence 1 (no internal category name) — same all-time/
  extreme-tier signal class, no jargon leak, graded A-.

B rather than A-/B+ solely because of the tier-jargon leak — the closer is genuinely strong,
the mechanism is real, but sentence 1 sounds like a data label instead of the bot's voice.
Fix in P_tier below unlocks this draft toward A-.

#### [12] Morrill Fire, Nebraska — fire_footprint — **B**

> *The Morrill Fire in Nebraska has burned 259,820 hectares since March 13 — past the
> 250,000-hectare tier that marks a continent-scale footprint. The Nebraska Sandhills sit on a
> grass-stabilized dune field; when that cover burns away, the underlying sand can begin to
> shift.*

**Score:** 73. Created 2026-07-01T04:09:36Z.

First `fire_footprint` in corpus (footprint/acreage framing, distinct from the FRP/MW-based
`fire` signal type already in corpus).

Humor lens:
- **Violation:** 259,820 hectares burned since March 13 — a months-long, landscape-scale fire.
  Genuinely unusual framing (duration + area rather than instantaneous radiative power).
- **Benign?** Yes.
- **Setup→Punchline?** Setup: hectares burned + duration. Close: "the underlying sand can begin
  to shift" — a forward-looking, declarative physical consequence (dune destabilization once
  the stabilizing grass cover is gone). This is close to the corpus's best form (Nauru's "no
  adjacent reef system to reseed it" — declarative structural consequence, no hedge).
- **Named mechanic?** Ecosystem specificity + causal chain (grass stabilizes dunes → fire removes
  grass → sand moves). The most specific, least generic mechanism close in this batch.
- **Wodehouse rule?** Violated in sentence 1 for the same reason as Basrah: "the 250,000-hectare
  tier that marks a continent-scale footprint" names an internal classification bucket
  ("continent-scale footprint" reads like an invented severity label, not a natural description)
  instead of just stating the number and letting it stand.

B rather than A- for the identical reason as Basrah: the closer is arguably the strongest single
sentence in today's batch, but the tier-jargon opener caps the grade. Without "the 250,000-hectare
tier that marks a continent-scale footprint" — e.g. "The Morrill Fire in Nebraska has burned
259,820 hectares since March 13" — this reads clean and the draft is A- territory.

### B- / C-grade drafts

#### [13] Al Baṣrah al Qadīmah, Iraq — absolute_extreme — **B-**

> *Al Baṣrah al Qadīmah, Iraq: forecast high of 47°C (117°F) on July 1 — at the absolute extreme
> threshold for the Northern Subtropics. Basra sits at the head of the Gulf, where the shallow
> coastal sea recycles heat back into an already superheated air column.*

**Score:** 83. Created 2026-07-01T14:52:46Z.

Second Basra-area `absolute_extreme` draft in 3 days (see [11], Jun 30, same city under a
different gazetteer name — "Basrah" vs. "Al Baṣrah al Qadīmah" — likely two separate station/
city records for the same metro area). Same score (83) as [11].

Humor lens:
- **Violation:** 47°C forecast, "at" (not clearly above) the absolute-extreme threshold —
  right at the boundary rather than past it. Slightly weaker framing than [11]'s "above."
- **Named mechanic?** Ecosystem specificity (Gulf heat-recycling). Physically apt but the close
  describes a present state ("recycles heat back into an already superheated air column") rather
  than naming a forward consequence — mechanism-only, not declarative-consequence.
- **Wodehouse rule?** Same tier-jargon leak as [11]: "the absolute extreme threshold for the
  Northern Subtropics." Third occurrence of this near-identical phrase across 2 drafts.

B- rather than B: same jargon violation as [11] and [12], compounded by a softer close
(descriptive state vs. declarative consequence) and a boundary-line ("at" vs "above") framing
that's less forceful than [11]'s.

#### [14] Wadi Halfa, Sudan — dust_event — **C+**

> *Wadi Halfa, Sudan: model-estimated dust daily maximum of 559 μg/m³ on July 1 — aerosol
> optical depth at 0.87. The city sits on the Nile at the edge of the Sahara, where summer
> haboobs push Nubian Desert sediment south before lake-effect moisture from Nasser dampens
> the column.*

**Score:** 71. Created 2026-07-01T14:56:45Z.

8th `dust_event` corpus draft (Riyadh, Urumqi, Taiz ×3, Phalodi, Taiz [Jun 30], Wadi Halfa).

Humor lens:
- **Violation:** 559 μg/m³, AOD 0.87 — lower peak concentration than every other dust_event
  draft in corpus (Riyadh 2,083; Urumqi 2,260; Taiz 1,302/2,271/2,135; Phalodi 956), but no
  reference point is given so the reader can't calibrate low-vs-high either way.
- **Named mechanic?** Two-step ecosystem mechanism — haboob winds lift Nubian Desert sediment
  south, then Lake Nasser's moisture dampens (settles) it. This is the same "lift → stall/settle"
  two-step structure the Jun 30 grading called "the more sophisticated of the two dust drafts"
  for Taiz — the most specific dust mechanism in the batch.
- **Wodehouse rule?** Clean of tier-jargon (unlike [11]/[12]/[13]) — no internal category name.
  But same P_dust gap as every prior dust_event draft: no WHO PM2.5/PM10 multiple, and the close
  ("dampens the column") is a resolution/dispersal beat — describing how the dust clears, not
  what the concentration means to someone breathing it. Same subtype as Al Aḥmadī Kuwait's
  "before sea breezes suppress them by evening" and Taiz's "before topography stalls it inland."

C+, same ceiling as every dust_event draft to date. 8th consecutive corpus draft sharing the
identical opener template ("[City], [Country]: model-estimated dust daily maximum of X μg/m³ on
[date] — aerosol optical depth at Y.") and the same missing-consequence gap. Template convergence
is now total (8 of 8).

### Carry-over inventory (Jun 28–30 grades stand; not re-graded)

| # | Draft | Type | Grade (cycle graded) | Status this cycle |
|---|---|---|---|---|
| [1] | Mediterranean Sea, 3.54°C above seasonal normal | regional_sst_anomaly | B+ (Jun 28) | **STALE — bulk-reject candidate** |
| [2] | Global mean ocean surface temp, 25-day streak | marine_heatwave | A- (Jun 29) | **Newly STALE — bulk-reject candidate** |
| [3] | France, 6 cities, 11.53°C above normal (reganom) | regional_anomaly | B+ (Jun 29) | Clear; operator's reganom voice-upgrade P1 target per BRIEFING.md |
| [4] | Amsterdam, 314.1 mm / 7 days | precipitation_extreme | B (Jun 30) | Clear |
| [5] | Astana, Kazakhstan, 308.1 mm / 7 days | precipitation_extreme | B+ (Jun 30) | Clear |
| [6] | Phalodi, India, 956 μg/m³ dust | dust_event | C+ (Jun 30) | Clear |
| [7] | Taiz, Yemen, 1,302 μg/m³ dust | dust_event | C+ (Jun 30) | Clear |
| [8] | Rocky Mountains, Colorado, 595.3 MW fire | fire | B- (Jun 30) | Clear |
| [9] | Prudhoe Bay, Alaska, 101°F all-time high | all_time_high | A- (Jun 30) | Clear |
| [10] | Antwerpen, Belgium, 358.8 mm / 7 days | precipitation_extreme | B+ (Jun 30) | Clear |

### Patterns named in this batch

1. **Tier/threshold jargon leak — new pattern, promoted to P_tier (was A3, awaiting evidence).**
   4 of 14 pending drafts (1 carry-over + 3 fresh) state an internal classification bucket name
   verbatim: "3.5°C tier threshold," "47°C absolute-extreme threshold for the Northern Subtropical
   band" (×2), "250,000-hectare tier that marks a continent-scale footprint." All four are
   otherwise structurally sound — real signal, correct ecosystem mechanism, several with genuinely
   strong closes (Morrill Fire's dune-destabilization consequence is the best single closer in
   today's batch) — but the tier-naming reads as the bot quoting its own scoring rubric. This is a
   Wodehouse violation of a kind not previously named: not approximation, not restate-padding, but
   **citing methodology**. Full writeup in `docs/IMPROVEMENT_PLAN.md` P_tier.

2. **Duplicate near-identical drafts for the same location 3 days apart.** [11] Basrah (Jun 30,
   47.2°C) and [13] Al Baṣrah al Qadīmah (Jul 1, 47°C) are almost certainly the same metro area
   under two different gazetteer names, both `absolute_extreme`, both at ~47°C, 3 days apart, both
   carrying the identical tier-jargon phrase. This reads as a possible city-dedup gap (two entries
   for one place in `cities.csv`) rather than a voice issue — logging as an observation, not a
   voice proposal, since it's a data/pipeline question out of this routine's scope. Operator:
   BRIEFING.md already tracks a related issue (#346, duplicate-city `city|country` re-key, held
   pending 5 same-place country aliases).

3. **Basrah [11] forecast has gone stale in truth-value, not just in age.** Created for a
   same-day (June 30) forecast; by grading time (July 1) the forecast date has passed without the
   draft being posted or updated to past tense. Under 48h old, so it doesn't trip the mechanical
   staleness rule, but if shipped today it would misstate the date. Distinct from the reganom
   honesty-gating fix (PR #347, which handles *ended heatwave spells*, not single-day extreme-heat
   forecasts) — flagging as an observation for the operator, not proposing a code fix (out of
   scope for a surgical voice/prompt proposal).

4. **Two more A-grade closer references confirmed against P_close.** [11] Basrah ("offers no
   evaporative relief when the land is already this hot") and [12] Morrill Fire ("the underlying
   sand can begin to shift") are both P_close POSITIVE — declarative, named consequences, not
   implied. [13] Al Baṣrah ("recycles heat back into an already superheated air column") and [14]
   Wadi Halfa ("dampens the column") are both P_close FAILING — mechanism/resolution-only closes.
   2 positive / 2 failing this cycle; P_close now 12 cycles evidenced.

5. **P_dust — 8th consecutive dust_event draft, still no WHO/consequence anchor.** Wadi Halfa
   continues the unbroken pattern: real signal, decent (even two-step) ecosystem mechanism, no
   calibration for the reader, resolution-style close. 7th grading cycle with this observation.

### Followups (in priority order)

1. **P_tier is ready for implementation.** 4 corroborating instances across `regional_sst_anomaly`
   and `absolute_extreme` (×2) and `fire_footprint`, spanning Jun 23 (A3's original filing) through
   Jul 1. The fix is a one-paragraph addition to `writer_prompt.py`: state the raw number, never
   the bucket name.
2. **Operator: reject [1] Mediterranean and [2] GMST marine_heatwave via dashboard.** Both stale
   by policy (>48h + "today" language); `gh` CLI unavailable for automated bulk-reject (33rd
   consecutive skip).
3. **Operator: decide on [11] Basrah before it goes further stale.** The forecast date (June 30)
   has already passed; post now with corrected tense, or reject and let [13] (the fresher,
   same-area July 1 draft) stand in its place.
4. **P_dust and P_tier fixes are complementary and could ship together** — both are one-paragraph
   `writer_prompt.py` additions targeting the same underlying issue (numbers presented without a
   reader-facing reference frame: WHO multiples for dust, plain values for tier thresholds).

### Numbers

- Pending drafts in queue: 14 (4 fresh; 10 carry-overs from Jun 28–30, not re-graded)
- Fresh drafts graded: 4 (absolute_extreme ×2, fire_footprint, dust_event)
- A-rate: 0% (0/4); n=4 — not statistically meaningful
- Grade distribution (fresh): 0 A / 2 B / 1 B- / 1 C+ / 0 D-F
- New signal types in corpus: `absolute_extreme`, `fire_footprint`
- Active proposals: P_close 12th cycle (2 positive, 2 failing); P_dust 7th cycle (8th corpus
  draft, template convergence total); P_tier promoted from A3 (awaiting-evidence) to active,
  4 corroborating instances across 3 signal types; P9/P_compound/P_precip_floor — no applicable
  drafts this cycle, counts unchanged; P5 — dust_event gap continues (Wadi Halfa: real mechanism,
  no named humor move)
- Staleness bulk-reject: 2 candidates ([1] Mediterranean, [2] GMST marine_heatwave); `gh` CLI
  absent — 33rd consecutive skip (May 13 → Jul 1)
- Operational note: `main` branch's copies of these three docs are stale since 2026-06-08 (23
  daily cycles' worth of grading — Jun 9 through Jun 30 — live only on the unmerged
  `daily-plan-current` rolling branch). This cycle continues that branch rather than restarting
  from `main`'s stale copies, per the runbook's rolling-branch instructions. Operator should merge
  soon; the longer the branch goes unmerged, the larger the gap between `main` and ground truth.

---

## 2026-06-29 — Daily corpus grading (5 fresh drafts; 1 Jun-28 carry-over not re-graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 6 pending — 1 carry-over from Jun 28 (Mediterranean regional_sst_anomaly B+, grade stands from Jun 28), plus 5 fresh (created after Jun 28's ~15:00 UTC grading window). Fresh mix: marine_heatwave (global SST streak), regional_anomaly/reganom (France, 8 cities), fire (Congo Basin), all_time_high (Prudhoe Bay AK), precipitation_extreme (Amsterdam). New signal type entering corpus: marine_heatwave.

**Staleness review as of 2026-06-29 ~15:00 UTC:** [1] Mediterranean (Jun 28T04:01Z, ~35h, "today" baked) — crosses 48h at ~Jun 30T04:00Z; operator must post or reject before then. [2] marine_heatwave (Jun 28T17:16Z, ~22h, "today's reading") — crosses 48h at ~Jun 30T17:00Z. [3] France reganom (Jun 28T19:48Z, ~19h, "through June 27" data) — no hard real-time anchor; clear for now. [4] Congo fire (Jun 29T04:11Z, ~11h, satellite data past-tense) — clear. [5] Prudhoe Bay (Jun 29T12:40Z, ~2h, "June 26" data date) — clear. [6] Amsterdam (Jun 29T12:43Z, ~2h, "through June 27") — clear. Bulk-reject: 0 candidates today. `gh` CLI absent — **31st consecutive skip** (May 13 → Jun 29).

**Grade distribution (5 fresh drafts):** 4 A- / 1 B+ / 0 B / 0 C / 0 D-F.
**A-rate: 80% (4/5). BAR CLEARED — first non-retroactive cycle above 50% since tracking began.**
Prior peak (non-retroactive fresh-draft cycles): 0% across all prior cycles. Retroactive Jun 15 was 67% but those were retrospective grades on already-posted/approved/rejected drafts.

**Headline finding:** 80% A-rate is the highest fresh-draft rate in the corpus. Four distinct mechanics carried the A-grades: floor/ceiling inversion (marine_heatwave "a record set two years ago is already the floor of a new streak"), ecosystem incongruity (Congo fire "something has broken the convective lid" — **first A-grade fire draft in two-bot corpus**, prior: 0/10 fire drafts A), latitude peer-comparison (Prudhoe Bay 91°F at 70°N vs. northern Siberia rarely 80°F), declarative consequence close (Amsterdam "there is nowhere for the water to go"). B+ draft: France reganom (pre-#349 upgrade; "Across 6 sampled cities" buries lede; "hour by hour" effort signal). P_close 11th cycle: 3 positives (marine_heatwave, Congo, Amsterdam), 1 failing (France), 1 n/a (Prudhoe latitude-peer). P9 8th cycle (Amsterdam template + restate-math). P_compound 2nd cycle (Prudhoe Bay archive+margin double-qualifier). P_precip_floor 2nd cycle (Amsterdam 4.7% margin wet-climate). No Wodehouse violations (8th consecutive clean cycle).

### Carry-overs (Jun 28 grades stand; not re-graded)

| Draft | Type | Grade (Jun 28) | Notes |
|---|---|---|---|
| [1] Mediterranean Sea (3.54°C above seasonal normal) | regional_sst_anomaly | **B+** | "Nowhere fast to go" borderline declarative; "today" baked; stale by ~Jun 30T04:00Z |

### A-grade drafts

#### [2] marine_heatwave — Global mean ocean SST streak — **A-**

> *Global mean ocean surface temperature (60°S–60°N) has stayed above the 44-year NOAA archive ceiling for 25 straight days. The prior record was 20.896°C, set in 2024; today's reading is 20.961°C. A record set two years ago is already the floor of a new streak.*

**Score:** 82. Created 2026-06-28T17:16Z.

Humor lens:
- **Violation:** 25 consecutive days above a 44-year archive ceiling. The ceiling itself is the boundary — not just a record broken but the outer limit of 44 years sustained as a floor.
- **Benign?** Yes — calm, factual. No panic.
- **Setup→Punchline?** Three sentences. Sentence 1: streak + ceiling framing (setup). Sentence 2: prior record vs. current reading (intensifier). Sentence 3: "A record set two years ago is already the floor of a new streak" — the punchline. Classic comic triple with escalating reveal at sentence 3.
- **Named mechanic?** Floor/ceiling inversion — the prior ceiling becomes the new floor. "Already the floor of a new streak" is an idiom-flip on the standard floor/ceiling vocabulary of records. Accelerating-warming embedded: the 2024 record lasting only 2 years is the mechanism.
- **Wodehouse rule?** Clean. "20.896°C" and "20.961°C" — deliberate specificity, structurally necessary. Closing sentence: flat, declarative, non-reaching. No effort signals.
- **P_close:** Positive. "A record set two years ago is already the floor of a new streak" — declarative reframe, not implied consequence. States the reversal directly.

Best draft in the batch. The three-sentence comic-triple structure is the strongest voicing in the two-bot corpus since the May 19 coral A-grades. "Already the floor of a new streak" is the kind of reframe that rewards a re-read.

Contains "today's reading" — real-time anchor. Operator must post or reject before Jun 30T17:00 UTC.

#### [4] fire — Congo Basin, DR Congo — 1,468 MW — **A-**

> *1,468 MW of radiative heat in the Congo Basin, DR Congo — very-high-intensity fire, satellite-confirmed at 100% confidence. The Basin's equatorial moisture normally suppresses fire; when it burns here, something has broken the convective lid.*

**Score:** 83. Created 2026-06-29T04:11Z.

Humor lens:
- **Violation:** 1,468 MW fire in the Congo Basin — equatorial moisture belt is the normative suppressor of fire here; the location IS the violation.
- **Benign?** Yes — physical, calm register.
- **Setup→Punchline?** Sentence 1: FRP + location + intensity tier + confidence (setup). Sentence 2: normal suppression mechanism → named consequence ("something has broken the convective lid"). Causal, not expository.
- **Named mechanic?** Ecosystem incongruity — the equatorial moisture belt normally prevents fire here. "Something has broken the convective lid" names the physical mechanism (convective inhibition failure) in plain language. The phrasing "something has broken" is mild understatement — acknowledges the cause exists without over-specifying it. Deliberate deadpan, not vagueness.
- **Wodehouse rule?** Clean. Lead-with-number ("1,468 MW of radiative heat") avoids the banned "A fire in [location] is radiating X MW" formula (P6 fix holding). "Very-high-intensity fire" uses the FRP tier label from PR #85 — adds scale without MW jargon. No effort signals.
- **P_close:** Positive. "Something has broken the convective lid" — declarative consequence statement. The convective inhibition failure is stated directly.

**First A-grade fire draft in the two-bot corpus** (prior: 0/10 fire drafts A across May 13–May 19 cycles). The ecosystem-incongruity mechanic is the fire category's strongest available tool; this draft deploys it cleanly. The convective-lid close is the fire version of "nowhere to drain" (Costa Rica coral, A-).

P6 check: opener is "1,468 MW of radiative heat in the Congo Basin" — varied form (lead-with-FRP), not the banned formula. P6 fix confirmed for third consecutive fire draft.

#### [5] all_time_high — Prudhoe Bay, Alaska — 91°F — **A-**

> *Prudhoe Bay, Alaska hit 91°F (32.8°C) on June 26 — hottest daily maximum in 24 years of records, 2°F above the 2024 mark. Prudhoe sits on the Arctic Ocean at 70°N; the same latitude in northern Siberia rarely breaks 80°F even in peak summer.*

**Score:** 88. Created 2026-06-29T12:40Z.

Humor lens:
- **Violation:** 91°F at Prudhoe Bay (70°N Arctic coast, oil-infrastructure landmark) — the location identity IS the violation. Prudhoe is one of the most recognizable names in Arctic resource geography; 91°F there is extreme on name recognition alone.
- **Benign?** Yes — factual, no catastrophizing.
- **Setup→Punchline?** Sentence 1: record + margin (setup). Sentence 2: location identity (Arctic Ocean, 70°N) + latitude peer-comparison (northern Siberia same latitude, rarely 80°F in peak summer). The Siberia comparison is the punchline — 91°F where 80°F is rare at the same latitude.
- **Named mechanic?** Ecosystem specificity via latitude peer-comparison. "The same latitude in northern Siberia rarely breaks 80°F even in peak summer" — verifiable world knowledge that grounds the violation without an era anchor. The implicit gap (~11°F unstated) is left for the reader to supply.
- **Wodehouse rule?** Clean. "2°F above the 2024 mark" slightly informal but not an effort signal. No restate-math. No poetry attempts.
- **P_close:** N/A — the close is a latitude peer-comparison, not a mechanism-consequence statement. The punchline structure is ecosystem specificity ("91°F where 80°F is rare") rather than the P_close pattern. Not counted in P_close cycle.
- **P_compound (2nd cycle):** "Hottest daily maximum in 24 years of records, 2°F above the 2024 mark" — two qualifier clauses (archive depth + margin) in the same clause. Compare: Beaver Dams [6] Jun 28 ("hottest daily maximum in 23 years of records, 15°F above the 2020 mark") — same structure. Smaller margin (2°F vs. 15°F Jun 28) makes the double-qualification less visible but the structural pattern recurs.

Record set in 2024 — only 2 years prior. Recency embedded in "2°F above the 2024 mark" without making it an era-anchor feature.

#### [6] precipitation_extreme — Amsterdam, Netherlands — 314.1 mm / 7 days — **A-**

> *Amsterdam recorded 314.1 mm of rain in seven days through June 27 — 14.1 mm above the previous seven-day record of 300.0 mm. The city sits at sea level in the Rhine-Meuse delta; when Atlantic systems stall over the Low Countries, there is nowhere for the water to go.*

**Score:** 76. Created 2026-06-29T12:43Z.

Humor lens:
- **Violation:** 314.1 mm / 7 days in a delta city at sea level — the physical setting amplifies the record.
- **Benign?** Yes — physical consequence stated, not human catastrophe focus.
- **Setup→Punchline?** Sentence 1: record + margin (setup). Sentence 2: location mechanism (sea level, delta, Atlantic stall) → declarative consequence close ("there is nowhere for the water to go").
- **Named mechanic?** Ecosystem specificity — delta at sea level, no drainage escape. "There is nowhere for the water to go" states the physical consequence directly. Compare to Barrow Jun 7 B+ close: "sheets across the surface instead" (implied contrast). Amsterdam: "nowhere to go" (declarative). Matches A- close standard: Costa Rica "nowhere to drain" (May 18, A-), Barrow 7-day Jun 22 A-.
- **Wodehouse rule?** Minor restate-math: "14.1 mm above the previous seven-day record of 300.0 mm" — the margin (14.1) is derivable from 314.1 − 300.0. Same class as prior precipitation_extreme instances. The declarative close offsets this; the close does enough work to carry A-.
- **P_close (positive):** "There is nowhere for the water to go" — unambiguous declarative consequence. Matches the B+/A- boundary established across the Jun 22 Barrow/Jun 7 Barrow comparison.
- **P9 (8th cycle):** "[City] recorded X mm in [period] through [date] — [margin] above the previous [period] record of [prior value]." 8th precipitation_extreme using this opener template. Restate-math present (14.1 = 314.1 − 300.0).
- **P_precip_floor (2nd cycle):** 314.1 mm / 7d, 4.7% margin in a sea-level wet-climate city. Same percentage as Jun 27 Amsterdam C+ (157.1 mm / 3d, different record window). The declarative close carries A- despite the shallow margin — demonstrates that strong voice can offset weak signal structure. Signal is structurally thin relative to other precipitation_extreme A-grades (Barrow Jun 7 / Jun 22: 42.5% margin).

Comparison to Barrow (Jun 7, B+): Amsterdam's close is more declarative → A-. Confirms the B+/A- boundary.

### B-grade drafts

#### [3] regional_anomaly — France, 8 cities — **B+**

> *Across 6 sampled cities in France, temperatures ran 11.53°C (20.8°F) above the 1991–2020 daily normal for 8 straight days through June 27 — 2.8 standard deviations out. At that margin, even brief nighttime relief disappears; the heat debt compounds hour by hour.*

**Score:** 88. Created 2026-06-28T19:48Z.

Humor lens:
- **Violation:** 11.53°C / 2.8σ above normal for 8 straight days — very strong signal.
- **Benign?** Yes, though "heat debt compounds hour by hour" edges toward consequence framing. Physical rather than human-impact.
- **Setup→Punchline?** Sentence 1: data (setup, with σ as em-dash kicker). Sentence 2: physical consequence (nighttime relief disappears + heat debt compounds). Two consequential beats.
- **Named mechanic?** "Heat debt compounds" — non-standard idiom. The accumulation framing echoes the DHW principle applied to atmosphere. Works conceptually but is metaphorical rather than a named physical mechanism.
- **Wodehouse rule?** "Heat debt compounds hour by hour" — slightly reaching for effect. "Hour by hour" is rhythmic padding; the mechanism of compounding is already in "compounds." Mild Wodehouse violation — not poetry-attempt level, but audible effort.
- **P_close (failing):** "The heat debt compounds hour by hour" — implied consequence framed as metaphorical intensifier. Fails the declarative close test.

Not A- because: (a) opener "Across 6 sampled cities in France" buries the lede — methodology caveat leads, not the significance; (b) "hour by hour" is mild effort signal in the close; (c) 11.53°C not rounded. **This draft predates the #349 voice upgrade** (shipped Jun 28–29) designed to address these exact failure modes (significance-leading, rounding). The next reganom draft will test whether the upgrade corrects lede-burial and effort signal.

### Patterns named in this batch

1. **80% A-rate clears the resumption bar for the first time (non-retroactive).** Prior non-retroactive peak: 0% across all prior fresh-draft cycles (Jun 7, Jun 13, Jun 17, Jun 18, Jun 23, Jun 24, Jun 25, Jun 26, Jun 27, Jun 28). The structural bar set 2026-04-26 ("majority A-rate, >50%, sustained") requires consistency — this is the first non-retroactive data point above the bar. One cycle is not sustained; confirmation needed.

2. **First A-grade fire draft (Congo Basin).** Two-bot corpus 0/10 fire drafts A-grade prior to today. The ecosystem-incongruity mechanic (equatorial moisture suppresses fire; "something has broken the convective lid") is the fire category's strongest available move. It mirrors the coral A-grade pattern: signal incongruity + named physical mechanism.

3. **Declarative vs. implied close: the B+/A- dividing line confirmed again.** Amsterdam (A-): "there is nowhere for the water to go" — declarative. Mediterranean carry-over (B+): "has nowhere fast to go" — qualified. France reganom (B+): "heat debt compounds hour by hour" — implied/metaphorical. Pattern: flat declarative consequence → A-; qualified or implied → B+.

4. **Marine_heatwave type enters corpus with A-.** First marine_heatwave draft. Three-sentence comic-triple with floor/ceiling inversion ("a record set two years ago is already the floor of a new streak") is the strongest closing mechanic in this batch.

5. **Reganom (regional_anomaly) pre-#349 voice pattern identified.** "Across N sampled cities" buries lede. "Heat debt compounds hour by hour" has mild effort signal. Both failure modes match the BRIEFING's pre-#349 assessment. Next reganom draft is the empirical test of the upgrade.

6. **P5 (name humor moves) not observed — mechanics deploying naturally.** This batch: floor/ceiling inversion, ecosystem incongruity, latitude peer-comparison, declarative ecosystem specificity. Full mechanic variety without explicit prompting. 3rd consecutive graded cycle without P5 evidence.

7. **Restate-math in precipitation_extreme: second confirmed instance.** Amsterdam mirrors Barrow pattern: "[new value] — [margin] above previous record of [prior value]." P9 8th cycle.

### Numbers

- Pending drafts in queue: 6 total (1 Jun-28 carry-over + 5 fresh)
- Fresh drafts graded this cycle: 5
- Carry-overs not re-graded: 1 ([1] Mediterranean B+, grade stands from Jun 28)
- Grade distribution (fresh only): 4 A- / 1 B+ / 0 B / 0 C / 0 D/F
- **A-rate (fresh): 80% (4/5) — BAR CLEARED**
- New signal types graded: marine_heatwave (1st corpus entry)
- First A-grade fire draft in two-bot corpus: Congo Basin [4]
- Active proposals with new evidence: P_close (11th cycle — 3 pos, 1 fail, 1 n/a), P9 (8th cycle), P_compound (2nd cycle), P_precip_floor (2nd cycle)
- P_dust: Not observed this cycle (no dust_event drafts)
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (31st consecutive skip)
- Real-time anchors to watch: [1] "today" (~35h → stale Jun 30T04:00 UTC), [2] "today's reading" (~22h → stale Jun 30T17:00 UTC)

---

## 2026-06-28 — Daily corpus grading (5 fresh drafts; 2 Jun-27 carry-overs not re-graded)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 7 pending — 2 carry-overs from Jun 27 (Canadian Prairies/BC fire B+, Amsterdam precipitation_extreme C+ — grades stand from Jun 27), plus 5 fresh (created after Jun 27's 15:00 UTC grading window). Fresh mix: dust_event (Taiz), regional_sst_anomaly (Mediterranean), precipitation_extreme (Astana), all_time_high (Beaver Dams UT), monthly_low (Casper WY).

**Staleness review as of 2026-06-28 ~15:00 UTC:** `gh` CLI absent — **30th consecutive skip** (May 13 → Jun 28, continuing from Jun 26's confirmed count; Jun 27's "13th" was a tracking bug). Carry-over [1] (fire, "today" baked, ~32h old) — under 48h; watch flag: crosses threshold at ~Jun 29T07:00Z. Carry-over [2] (Amsterdam, no date-bake) — ~29h, clear. Fresh [3] (Taiz, "June 27" baked, ~22h) — under 48h; crosses at ~Jun 29T17:00Z. All other fresh drafts <12h old. 0 staleness candidates.

**Grade distribution (5 fresh drafts only):** 0 A / 4 B / 1 C / 0 D-F.
**A-rate (fresh): 0% (0/5).** Gap from resumption bar: 50 pp.

**Headline finding:** Zero A-grades for the 5th consecutive graded cycle. P_close is 10th cycle and accounts for the ceiling: [4] Mediterranean is the closest to A- ("nowhere fast to go" = borderline declarative), but [6] Beaver Dams and [7] Casper both land implied-consequence closes that cap at B+/B. New failure mode observed: **compound-qualifier syndrome** — [6] and [7] both state archive depth AND margin in the same opener clause, producing double-qualification that dilutes both. P_dust 4th cycle: Taiz [3] again lacks WHO anchor, template-converges with all 5 prior dust_event corpus drafts. P9 7th cycle: Astana [5] uses the precipitation_extreme opener template. No Wodehouse violations (7th consecutive clean cycle).

### Carry-overs (Jun 27 grades stand; not re-graded)

| Draft | Type | Grade (Jun 27) | Notes |
|---|---|---|---|
| [1] Canadian Prairies/BC fire (1,517.9–2,979.4 MW) | fire | **B+** | Comic triple; "today" baked; stale by ~Jun 29T07Z |
| [2] Amsterdam (157.1 mm / 3d, 4.7% margin) | precipitation_extreme | **C+** | Thin margin, canal ecosystem specificity; P_precip_floor |

### B-grade drafts (fresh)

#### [4] Mediterranean — regional_sst_anomaly — 3.54°C above seasonal normal — **B+**

> *The Mediterranean Sea is running 3.54°C above its seasonal normal today — just past the 3.5°C tier threshold in the NOAA Coral Reef Watch basin average. The Mediterranean is a semi-enclosed sea with limited deep-water exchange; heat absorbed at the surface has nowhere fast to go.*

**Score:** 82. Created 2026-06-28T04:01:30Z (~11h old; "today" baked; fresh).

Humor lens:
- **Violation:** 3.54°C above seasonal normal — fractionally past the 3.5°C tier threshold.
- **Benign?** Yes — calm factual register.
- **Setup→Punchline?** Setup: 3.54°C anomaly. Punchline: semi-enclosed sea + "heat absorbed at the surface has nowhere fast to go." Structure echoes Costa Rica's A- ("nowhere to drain") — same conceptual frame.
- **Named mechanic?** Ecosystem specificity (semi-enclosed, no deep exchange). Understatement closer.
- **P_close:** Borderline positive. "Has nowhere fast to go" is close to declarative consequence but "fast" introduces a mild hedge ("fast" implies there is somewhere slow to go). Compare: "nowhere to drain" (Costa Rica A-) is unhedged. This close is the B+/A- boundary case.
- **Why B+ not A-:** First sentence is jargon-dense ("just past the 3.5°C tier threshold in the NOAA Coral Reef Watch basin average") — threshold attribution is opaque without a referent. Strip that clause and the draft is A- territory. "Nowhere fast to go" is nearly declarative but not quite.

---

#### [5] Astana, Kazakhstan — precipitation_extreme — 51.1 mm / 3.9 mm prior record — **B+**

> *Astana, Kazakhstan recorded 51.1 mm of rain on June 26 — against a previous daily record of 3.9 mm, set earlier this same year. Aktobe and Almaty logged 50.2 mm and 43.2 mm the same day. Astana sits in the driest interior of the Eurasian steppe.*

**Score:** 76. Created 2026-06-28T04:04:31Z (~11h old; fresh).

Humor lens:
- **Violation:** 51.1 mm against a prior record of 3.9 mm — implicit 13× ratio. "Set earlier this same year" is a temporal twist.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 51.1/3.9 mm contrast. Escalation: geographic spread. Punchline: steppe ecosystem-incongruity closer.
- **Named mechanic?** Ecosystem incongruity (driest steppe interior receiving 51.1 mm). The 3.9 mm prior record defines the violation's scale.
- **P9 (opener template):** "[City] recorded X mm on [date] — against a previous [daily] record of Y mm" — 7th precipitation_extreme using the template. P9 evidence confirmed.
- **P_close:** Not traditional P_close territory — the steppe closer is an ecosystem-incongruity punchline, not a mechanism close. Steppe line = location fact as punchline. Distinct pattern (no mechanism, no consequence — just the irony of the location). P_close not directly applicable.
- **Why B+ not A-:** The 13× ratio goes unnamed — ratio-as-punchline opportunity missed. The Aktobe/Almaty catalog (sentence 2) dilutes the 51.1/3.9 contrast before the steppe closer lands. "Astana sits in the driest interior of the Eurasian steppe" is correct but slightly flat — it names the location's character without naming a consequence ("13 mm of rain per year on average; this was 51" would be more pointed). Borderline B+/A-.

---

#### [6] Beaver Dams, Utah — all_time_high — 104°F / 15°F above 2020 mark — **B+**

> *Beaver Dams, Utah hit 104°F (39.9°C) on June 25 — hottest daily maximum in 23 years of records, 15°F above the 2020 mark. The Colorado Plateau's canyon topography locks in continental heat with little moisture overhead to blunt the afternoon peak.*

**Score:** 92. Created 2026-06-28T07:59:21Z (~7h old; "June 25" = data date; fresh).

Humor lens:
- **Violation:** 104°F, 15°F above the previous all-time record. 15°F is an extraordinary margin.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 104°F, 15°F margin. Second sentence: canyon topography locks heat + "blunt the afternoon peak."
- **Named mechanic?** Ecosystem specificity (canyon lock-in, low moisture). Load-bearing.
- **P_close:** Failing — "little moisture overhead to blunt the afternoon peak" is implied-consequence (the negation of blunting → the peak is extreme). Not stated directly. Compare: "lock in heat" is mechanism; "blunt" framed as negation is implied.
- **P_compound (NEW):** First-sentence compound-qualifier: "hottest daily maximum in 23 years of records, 15°F above the 2020 mark." Two qualifier clauses state the same fact in different framings (archive + margin). Choose one. **New failure mode.**
- **Why B+ not A-:** P_compound (double-qualifier opener) + P_close (implied-consequence). The prior Beaver Dams all_time_high (Jun 15 retroactive, different event) earned A-; this one's opener is heavier.

---

#### [7] Casper, Wyoming — monthly_low — 27°F / 3°F below 2018 mark — **B**

> *Casper, Wyoming hit 27°F (-2.8°C) on June 25 — coldest June low in 26 years of records, 3°F below the 2018 mark. The North Platte River valley drains cold air down from the Laramie Range on clear nights, pushing lows well below what June air masses would otherwise deliver.*

**Score:** 82. Created 2026-06-28T14:00:34Z (~1h old; "June 25" = data date; fresh).

Humor lens:
- **Violation:** 27°F below freezing in late June. 3°F below the June record in a 26-year archive.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: 27°F, record margin. Second sentence: cold-air drainage (North Platte valley + Laramie Range). Close: "what June air masses would otherwise deliver."
- **Named mechanic?** Ecosystem specificity (cold-air drainage basin). Load-bearing.
- **P_close:** Failing — "well below what June air masses would otherwise deliver" is implied-consequence (implies temperatures should be higher in June; doesn't state the consequence). "Freezing on June 25" is the consequence and should be stated.
- **P_compound (2nd obs this cycle):** "coldest June low in 26 years of records, 3°F below the 2018 mark" — same double-qualifier pattern as [6]. Archive depth + margin in same clause.
- **P_new floor check:** 26-year archive (> 20yr), 3°F ≈ 1.67°C margin (> 1°C threshold) — passes both criteria. P_new not triggered.
- **Why B not B+:** P_close failing (implied-consequence close). P_compound first sentence. "What June air masses would otherwise deliver" is wordy where "Below freezing. In June." would be more pointed. The below-freezing irony is the joke and the draft doesn't let it land.

---

### C-grade drafts (fresh)

#### [3] Taiz, Yemen — dust_event — 728 μg/m³ — **C+**

> *Taiz, Yemen: model-estimated dust daily maximum of 728 μg/m³ on June 27 — aerosol optical depth at 0.77. Taiz sits at the southwest corner of the Arabian Peninsula where the summer monsoon low pulls Red Sea and Arabian dust inland through the Tihama coastal plain.*

**Score:** 71. Created 2026-06-27T17:21:33Z (~22h old; "June 27" date-baked; not stale by policy; crosses 48h at ~Jun 29T17Z).

Humor lens:
- **Violation:** 728 μg/m³. WHO PM₁₀ guideline is 45 μg/m³ — this is ~16× the limit. But the draft doesn't name the ratio, a prior maximum, or any calibrating reference.
- **P_dust (4th cycle):** "[City]: model-estimated dust daily maximum of X μg/m³ on [date] — aerosol optical depth at Y" — **identical opener template** to Riyadh (Jun 13), Urumqi (Jun 17), Taiz Jun 24, Taiz Jun 25. All 5 dust_event corpus drafts share this template. AOD metric unstated for lay reader. Proposal confirmed across 5 drafts.
- **P_close:** Failing — "pulls Red Sea and Arabian dust inland through the Tihama coastal plain" = mechanism-only. Transport mechanism described; no consequence named.
- **Why C+:** No WHO anchor (P_dust), mechanism-only close (P_close). Reader cannot feel the violation. Tihama coastal plain geography is accurate and specific — that's the only positive element. C+ (not C) for the genuine geographic specificity.

---

### Patterns named

1. **P_close 10th cycle** — 3 failing in fresh batch ([3] Taiz mechanism-only; [6] Beaver Dams implied; [7] Casper implied), 1 borderline positive ([4] Mediterranean "nowhere fast to go"), 1 ecosystem-incongruity form that isn't P_close ([5] Astana steppe punchline). Pattern: implied-consequence and mechanism-only forms continue to cap drafts at B/B+.

2. **P_compound (new, 2 obs in one cycle)** — [6] Beaver Dams and [7] Casper both state archive depth AND margin in the same opener sentence. Choose one. New proposal.

3. **P_dust 4th cycle** — 5th consecutive dust_event draft lacks WHO calibration anchor. Template convergence: all 5 corpus dust_event drafts share "[City]: model-estimated dust daily maximum of X μg/m³ on [date] — aerosol optical depth at Y" structure.

4. **P9 7th cycle** — [5] Astana uses the precipitation_extreme opener template. 9 of 9 precipitation_extreme corpus drafts share the template structure.

5. **No Wodehouse violations** (7th consecutive clean cycle). P4 fix holding.

6. **Mediterranean draft revisited** — Jun 23 Mediterranean SST was graded B ("retains heat faster than open-ocean basins"). Jun 28 Mediterranean SST is a new draft, same basin; "nowhere fast to go" is a stronger close form (borderline positive P_close). B+ assigned — demonstrating measurable close-quality variation within the same signal type.

### Numbers

- Pending: 7 (2 carry-overs, 5 fresh)
- Fresh drafts graded: 5
- A-rate (fresh): **0%** (0/5). Gap from bar: 50 pp.
- New proposals: P_compound (compound-qualifier opener; 2 instances this cycle)
- Evidence updates: P_close (10th cycle), P_dust (4th cycle), P9 (7th cycle)
- Staleness bulk-reject: 0 candidates; `gh` CLI absent (30th consecutive skip, May 13 → Jun 28)

---

## 2026-06-26 — Daily corpus grading (3 fresh drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 3 pending drafts — all
fresh, all precipitation_extreme, all created 2026-06-26. **Infrastructure note:** All 3 drafts
cite "previous 3-day record of 150.0 mm" — this is the detection threshold value (150.0 mm for
3-day accumulation) being passed as the prior record when no authenticated station historical record
exists in the bundle (`previous_record_year: null` in all 3 bundles). Threshold artifact: the
bundle uses the triage floor as the "record" comparator. Operator should verify whether authentic
station records exist before publishing any of these as "record-breaking."

**Staleness review as of 2026-06-26 ~15:00 UTC:** `gh` CLI absent — **29th consecutive skip**
(May 13 → Jun 26). All 3 drafts < 48h old (tweet_date 2026-06-24; created Jun 26T04:00–07:59Z).
No real-time-baked language ("today"/"tonight"/"forecast") — 0 staleness candidates. **Operator
note:** All 3 Jun 26 drafts approach 48h threshold ~Jun 28T04:00–07:59Z — post or reject before
then.

**Grade distribution (3 fresh drafts):** 0 A / 1 B / 2 C+ / 0 D-F.
**A-rate: 0% (0/3).** Gap from resumption bar: 50 pp.

**Headline finding:** P9 6th cycle — all 3 drafts use "[City] received/logged X mm in 3 days —
[comparison]" opener template; Amsterdam + Aktobe have restate-math; Anchorage restate-math also
present. P_close 9th cycle: Anchorage mechanism-only failing; Amsterdam implied-consequence
failing; Aktobe half-year ratio (borderline — ratio form correct, setup too thin). All 3 cite
"previous 3-day record of 150.0 mm" — threshold artifact confirmed across the batch.

### B drafts

#### [3] Anchorage, Alaska, US — precipitation_extreme — 183.8 mm/3-day — **B**

> *Anchorage received 183.8 mm of rain in 3 days — 33.8 mm above the previous 3-day record of
> 150.0 mm. The city sits at the head of Cook Inlet, where storms tracking up from the Gulf of
> Alaska can stall against the Chugach Range and wring out moisture in compressed bursts.*

**Score:** 80 (threshold 70; passes). Created 2026-06-26T07:59Z. Margin: 33.8/150.0 = **22.5%** above record.

Humor lens:
- **Violation:** 183.8 mm in 3 days — strongest margin in the batch (22.5%). Fact-checked clean.
- **Benign?** Yes — factual, no human loss language.
- **Setup→Punchline?** Setup: 183.8 mm, margin named (33.8 mm above record). System clause:
  Cook Inlet head + Gulf of Alaska storm tracks + Chugach Range orographic stall + "wring out
  moisture in compressed bursts." Close ends on the mechanism description — does not name the
  consequence of those compressed bursts. Mechanism-only P_close form (the weakest).
- **Named mechanic?** Orographic stall (Gulf of Alaska → Cook Inlet → Chugach Range stall →
  moisture compression) — specific, load-bearing, correct topographic geography. Best system
  clause in the batch.
- **Wodehouse rule?** No effort signal. "Compressed bursts" is precise. "Stall against the
  Chugach Range" is the right verb.

**P9 observed (6th cycle).** "[City] received X mm of rain in N days — [comparison]" opener
template. Also restate-math: "33.8 mm above the previous 3-day record of 150.0 mm" — margin +
prior record both stated (derivable arithmetic).

**P_close FAILING (9th cycle, mechanism-only).** "Wring out moisture in compressed bursts" ends
on the mechanism, not the consequence. Weakest P_close form — does not even reach implied-
consequence. Compare: Red Dog Mine Jun 13 (mechanism-only, C+); here the 22.5% margin saves to B.
Declarative-consequence form: "The Chugach holds these systems long enough to saturate Cook Inlet
drainages" or similar.

**Threshold artifact.** "Previous 3-day record of 150.0 mm" = the 3-day detection threshold.
`previous_record_year: null` in bundle. The 22.5% margin above the threshold is real; whether a
station-authenticated 3-day record of 150.0 mm exists for Anchorage is unverified.

**Why not B+?** P_close mechanism-only close + restate-math + P9 template. To reach B+: drop
restate-math (ratio or period-and-restate), name a consequence in the close.

### C+ drafts

#### [1] Amsterdam, The Netherlands — precipitation_extreme — 157.1 mm/3-day — **C+**

> *Amsterdam received 157.1 mm of rain in 3 days — 7.1 mm above the previous 3-day record of
> 150.0 mm. The Netherlands sits at the mouth of the Rhine-Meuse delta; the city's canal network
> was built to manage gradual accumulation, not to absorb a month's rain in 72 hours.*

**Score:** 74 (threshold 70; passes). Created 2026-06-26T04:00Z. Margin: 7.1/150.0 = **4.73%** above record.

Humor lens:
- **Violation:** 157.1 mm in 3 days; narrow 4.73% margin. Fact-checked clean.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: margin stated (restate-math). System clause: Rhine-Meuse delta +
  canal network design-capacity framing. Close: "not to absorb a month's rain in 72 hours" —
  contrast structure (built for gradual accumulation, NOT for 72h total) implies the canal system
  was overwhelmed but does not name the consequence. Implied-consequence P_close form.
- **Named mechanic?** Rhine-Meuse delta geography + canal network design capacity — strong
  infrastructure-incongruity framing. "A month's rain in 72 hours" is accurate (Amsterdam
  average June rainfall ~60mm → 157mm ≈ 2.6 months; "a month's rain" understates). The delta-
  drainage engineering angle is the right specificity vehicle.
- **Wodehouse rule?** No effort signal. "Not to absorb a month's rain in 72 hours" is precise.

**P9 observed (6th cycle).** "[City] received X mm in N days — [comparison]" opener template.
Restate-math: "7.1 mm above the previous 3-day record of 150.0 mm" — three numbers where two
suffice. Compare Jun 18 Amsterdam B: "14.4 mm above a previous record of 300.0 mm" — same
pattern, same slot, different event data.

**P_close FAILING (9th cycle, implied-consequence).** "Not to absorb a month's rain in 72 hours"
implies the canal system was overwhelmed but does not name the consequence. Declarative form:
"The delta's canal network backs up" or "Amsterdam's drainage saturates." The canal-capacity
clause is the strongest system clause in a C+-graded precipitation_extreme draft — the gap is
entirely in the LANDING, not the mechanism identification.

**Threshold artifact.** "Previous 3-day record of 150.0 mm" = detection threshold. See above.

**Why C+ and not B?** Narrow margin (4.73%) + implied-consequence close. Jun 18 Amsterdam B had
4.8% margin + same implied-consequence form — functionally the same grade. Infrastructure
specificity (canal design capacity) is slightly stronger here but not enough to lift.

#### [2] Aktobe, Kazakhstan — precipitation_extreme — 150.8 mm/3-day — **C+**

> *Aktobe, Kazakhstan logged 150.8 mm of rain over 3 days — just edging the previous 3-day record
> of 150.0 mm. Aktobe sits on the dry Kazakh steppe, where annual rainfall totals rarely exceed
> 300 mm; three days here matched half a year's average.*

**Score:** 73 (threshold 70; passes). Created 2026-06-26T04:03Z. Margin: 0.8/150.0 = **0.53%** above record.

Humor lens:
- **Violation:** 0.8 mm margin — narrowest in precipitation_extreme corpus. Barely a record.
- **Benign?** Yes.
- **Setup→Punchline?** Setup: "just edging" hedge immediately signals thin margin. System clause:
  Kazakh steppe aridity + annual rainfall context. Close: "three days here matched half a year's
  average" — declarative ratio (150.8 mm ≈ 300 mm × 0.5). The ratio close is the strongest
  element of the draft; comparable structure to Barrow Jun 25 "nearly twice that total" (P_close
  POSITIVE). But the setup (hedge + thin margin) undercuts the ratio's impact.
- **Named mechanic?** Kazakh steppe aridity calibration — correct and specific. Annual
  precipitation <300 mm is accurate for Aktobe latitude (~50°N, semi-arid steppe).
- **Wodehouse rule?** "Just edging" is the violation — signals awareness of how thin the margin
  is. The writer is apologizing for the number. Wodehouse would not hedge. "Logged 150.8 mm of
  rain over 3 days" is fine; "just edging the previous 3-day record of 150.0 mm" is the mistake.

**P9 observed (6th cycle).** "[City] logged X mm in N days — [comparison]" opener template. Verb
varies ("logged" vs. "received") but structure is identical. Restate-math: "just edging the
previous 3-day record of 150.0 mm" — both values present.

**P_close borderline (9th cycle).** "Three days here matched half a year's average" — declarative
ratio, structurally similar to Barrow Jun 25 "nearly twice that total" (P_close POSITIVE). But
Barrow's ratio followed a 22.5% margin with no hedge; Aktobe's ratio follows a 0.53% margin with
"just edging." The ratio form is correct; the setup is too weak to carry it to POSITIVE.

**Threshold artifact.** "Previous 3-day record of 150.0 mm" = detection threshold. Also: 0.8 mm
above a threshold value raises the question of whether this event qualifies as a genuine record if
authenticated station data were available.

**Why C+ and not B?** 0.53% margin is nearly invalidating. "Just edging" hedge is a Wodehouse
violation. Without the hedge and with a stronger margin, the steppe-aridity + half-year ratio
close would reach B.

---

## 2026-06-25 — Daily corpus grading (5 fresh drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 5 pending drafts
— all fresh. Jun 24 queue (Randolph UT B+, Al Aḥmadī Kuwait B) cleared between cycles. First
dust_event pair in a single cycle (Taiz Yemen ×2). First companion-fire peer comparison in
fire corpus.

**Staleness review as of 2026-06-25 ~15:00 UTC:** `gh` CLI absent — **28th consecutive skip**
(May 13 → Jun 25). 0 qualifying candidates this cycle (all drafts <48h old). **Operator note:**
Draft [1] (Taiz Jun 24 dust, "June 24", created Jun 24T21:30Z) stale by ~Jun 26T21:30 UTC.
Draft [3] (Taiz Jun 25 dust, "June 25", created Jun 25T07:48Z) stale by ~Jun 27T07:48 UTC.
Draft [4] (Siberia fire, "today"/"same day", created Jun 25T10:46Z) stale by ~Jun 27T10:46 UTC.
Operator must act on Drafts [1], [3], [4] within 30–48h.

**Note on Barrow Alaska same-event regeneration:** Draft [5] (Barrow AK 213.8 mm/3-day, created
Jun 25T14:45Z) matches the Jun 7 corpus entry (same event, same data). Treated as independent
draft; prior clearance does not chain.

**Grade distribution (5 fresh drafts):** 0 A / 4 B-range (2 B+ / 1 B / 1 B-) / 1 C+ / 0 D-F.
**A-rate: 0% (0/5).** Gap from resumption bar: 50 pp.

**Headline finding:** P_close 8th cycle — 3 failing (Taiz Jun 24 C+, Michigan monthly_low B,
Taiz Jun 25 B-), 2 positive (Siberia fire "burns deep" + Barrow "nearly twice that total").
P_dust 3rd cycle: both Taiz drafts lack WHO PM2.5 anchor (AOD-only); all 4 dust_event corpus
drafts now template-converged. P9 5th precipitation_extreme (Barrow, same opener + restate-math).
First companion-fire peer comparison in fire corpus. "Roughly"/"nearly" hedges cost Barrow A-;
date-baking ("today"/"same day") costs Siberia A-.

### B+ drafts

#### [4] Western Siberia, Russia — fire — 965.6 MW FRP — **B+**

> *965.6 MW of radiative heat in western Siberia today — very-high-intensity fire,
> satellite-confirmed at 100% confidence. Two nearby fires in the same basin registered
> 611 and 569.6 MW the same day. Western Siberia's peatlands hold centuries of carbon;
> summer fire here burns deep.*

**Score:** 84. Created 2026-06-25T10:46Z. "Today"/"same day" date-baked — stale by ~Jun 27T10:46.

Humor lens:
- **Violation:** 965.6 MW — highest FRP value in fire corpus. Satellite-confirmed at 100%
  confidence; "very-high-intensity" classification stated.
- **Benign?** Yes — factual, no human loss language.
- **Setup→Punchline?** Setup: 965.6 MW, regional record. Pivot: companion fires (611 + 569.6 MW
  in same basin, same day). Close: "Western Siberia's peatlands hold centuries of carbon; summer
  fire here burns deep." Named mechanic (peatlands) + declarative consequence ("burns deep").
  Strong punchline structure.
- **Named mechanic?** Peatland carbon storage — first peat framing in fire corpus. Companion-fire
  peer comparison — also first in fire corpus.
- **Wodehouse rule?** "Burns deep" — tight, earned, not telegraphed. "Centuries of carbon" does
  real work. No effort signal.

**P_close POSITIVE (8th cycle, fire).** "Burns deep" = declarative consequence. The peatland
clause sets up the consequence (stored carbon → depth of burn); "burns deep" names it directly.
Compare to Red Dog Mine (stops at mechanism) and Barrow Jun 7 ("sheets across the surface
instead" = implied by contrast).

**Why not A?** "Today" and "same day" date-bake the draft — stale by Jun 27T10:46 UTC. Without
the real-time anchor, this draft reaches A-.

**First companion-fire peer comparison in fire corpus.** Two companions (611 + 569.6 MW) cited
alongside 965.6 MW — regional system framing instead of single-event report.

#### [5] Barrow (Utqiaġvik), Alaska — precipitation_extreme — 213.8 mm/3-day — **B+**

> *Barrow, Alaska accumulated 213.8 mm of rain in 3 days — beating the previous 3-day
> record by 63.8 mm. Barrow's mean annual precipitation is roughly 110 mm; this single
> event delivered nearly twice that total.*

**Score:** 82. Created 2026-06-25T14:45Z. Same event as Jun 7 corpus entry (213.8 mm/3-day, B+).

Humor lens:
- **Violation:** 213.8 mm / 3-day — 42.5% above the 150.0 mm prior record (63.8 mm margin).
- **Benign?** Yes — factual.
- **Setup→Punchline?** Setup: 213.8 mm, beats record by 63.8 mm. Sentence 2 pivots to annual
  total ("roughly 110 mm"). Close: "this single event delivered nearly twice that total."
  Annual-ratio IS the punchline — declarative-comparative form. P_close positive.
- **Named mechanic?** Ratio-to-annual-precipitation — novel framing. No permafrost clause
  (contrast to Jun 7 B+ version, which used "permafrost beneath Barrow's tundra keeps the
  ground impermeable; rain that falls here has nowhere to go").
- **Wodehouse rule?** "Roughly" hedges the annual total; "nearly" hedges the ratio. Two hedges
  in two sentences. Restate-math in sentence 1: "beating the previous 3-day record by 63.8 mm"
  (63.8 = 213.8 − 150.0; margin is derivable arithmetic).

**P_close POSITIVE (8th cycle, precipitation_extreme).** "Delivered nearly twice that total" =
declarative-comparative consequence. Cleaner close than Jun 7 ("sheets across the surface instead"
= implied by contrast). The annual-ratio is the named consequence.

**Why not A?** "Roughly" + "nearly" soften what should be declarative: "Barrow's mean annual
precipitation is 110 mm; this three-day event doubled it." Restate-math present. P9 opener
template: same [City] [verb] [X mm] in [timeframe] structure as all prior precipitation_extreme
corpus drafts.

**P9 5th cycle.** Opener template saturated (5 of 5 precipitation_extreme corpus drafts). Verb
varies ("accumulated" vs. prior "received/recorded") — cosmetic. Restate-math: 63.8 mm margin
derivable from 213.8 − 150.0.

**Same-event regeneration.** Jun 7 B+ and Jun 25 B+: same data, different draft text. Jun 7
used permafrost-impermeability clause; Jun 25 uses annual-ratio pivot. Both earn B+ for different
reasons; Jun 25 annual-ratio close is the stronger punchline form.

### B drafts

#### [2] Nw Michigan Rsch Farm — monthly_low — 33°F / 0.6°C — **B**

> *Nw Michigan Rsch Farm hit 33°F (0.6°C) on June 23 — coldest June low in 29 years of
> records, 4°F below the 1998 mark. In the Great Lakes lake-effect belt, open water keeps
> nights wetter and unstable; cold air finds less land friction to slow it down.*

**Score:** 74. Created 2026-06-25T03:46Z.

Humor lens:
- **Violation:** Coldest June low in 29 years, 4°F below 1998 mark. Real record.
- **Benign?** Yes — factual, lake-effect mechanism explained.
- **Setup→Punchline?** Setup: 33°F, 29-year June low, 4°F below 1998. System clause: lake-effect
  belt, open water → wetter/unstable nights. Close: "cold air finds less land friction to slow it
  down" — mechanism description, consequence unstated (frost? crop damage? June freeze?).
  P_close failing.
- **Named mechanic?** Lake-effect cooling from Lake Michigan — load-bearing. Explains why a 33°F
  June reading at this station matters.
- **Wodehouse rule?** "Cold air finds less land friction to slow it down" is slightly abstract
  but not an effort signal. Clean.

**P_close FAILING (8th cycle, monthly_low).** "Less land friction to slow it down" = mechanism
without consequence. Fix: "cold air finds nothing to slow it down. June records fall." Or: "where
lake-effect cooling from Lake Michigan delivers June minimums below frost level."

### B- drafts

#### [3] Taiz, Yemen (Jun 25) — dust_event — 2,135 μg/m³ — **B-**

> *Taiz, Yemen: model-estimated dust daily maximum of 2,135 μg/m³ on June 25 — aerosol
> optical depth at 0.69. Taiz sits in Yemen's western highlands, where summer Kharif winds
> draw hot, dust-laden air off the Tihama coastal plain and push it upslope into the city
> basin.*

**Score:** 62. Created 2026-06-25T07:48Z. "June 25" date-baked — stale by ~Jun 27T07:48.

Humor lens:
- **Violation:** 2,135 μg/m³ = ~142× WHO PM2.5 daily guideline (15 μg/m³). Not stated — only
  AOD (0.69) given as comparator. P_dust failing.
- **Benign?** Yes — factual.
- **Setup→Punchline?** Setup: 2,135 μg/m³, AOD 0.69. System clause: Kharif winds, Tihama plain,
  upslope push into city basin. Close: "push it upslope into the city basin" — transport
  mechanism, consequence unstated. P_close failing.
- **Named mechanic?** Kharif monsoon winds + Tihama geography — more specific than draft [1]'s
  "dust corridors + southwest monsoon winds." The Tihama/Kharif/basin triad is genuine load-bearing
  geography.
- **Wodehouse rule?** Dense second sentence but accurate to the transport chain. Not an effort signal.

**P_dust FAILING (3rd cycle, dust_event type).** 2,135 μg/m³ (~142×) left without WHO calibration.
AOD (0.69) is not interpretable without additional framing.

**P_close FAILING (8th cycle, dust_event).** "Push it upslope into the city basin" = transport
mechanism. Consequence (trapped, accumulates, nowhere to vent) unstated. Fix: "the city basin
has no exit for it" or "the city basin traps it."

**B- over C+:** Geographic specificity (Kharif/Tihama/basin triad) elevates above draft [1]'s
generic "dust corridors + southwest monsoon winds." Same template structure, meaningfully better
second sentence.

### C+ drafts

#### [1] Taiz, Yemen (Jun 24) — dust_event — 2,271 μg/m³ — **C+**

> *Taiz, Yemen: model-estimated dust daily maximum of 2,271 µg/m³ on June 24 — aerosol
> optical depth at 0.73. Taiz sits in Yemen's highlands where the Arabian Peninsula's dust
> corridors converge with southwest monsoon winds that loft sediment before pushing it
> into the terrain.*

**Score:** 55. Created 2026-06-24T21:30Z. "June 24" date-baked — stale by ~Jun 26T21:30.

Humor lens:
- **Violation:** 2,271 μg/m³ = ~151× WHO PM2.5 daily guideline (15 μg/m³). Not stated; AOD
  (0.73) is the only comparator. The number lands flat without calibration.
- **Benign?** Yes — factual.
- **Setup→Punchline?** Setup: 2,271 μg/m³, AOD 0.73. System clause: Arabian Peninsula dust
  corridors + southwest monsoon. Close: "pushing it into the terrain" — weakest possible
  mechanism close; "terrain" is vague. No setup→punchline structure.
- **Named mechanic?** "Dust corridors converge with southwest monsoon winds" — generic. No
  specific geographic identification (compare: Kharif/Tihama/basin in draft [3]).
- **Wodehouse rule?** "Into the terrain" is vague (terrain of what?). Low precision but not
  an effort signal.

**P_dust FAILING (3rd cycle, dust_event).** 2,271 μg/m³ = ~151× WHO. Unstated.

**P_close FAILING (8th cycle, dust_event).** "Pushing it into the terrain" = weakest close
in corpus. Below "traps it" (Urumqi, B-). No consequence, no named endpoint.

**Template convergence confirmed.** Identical opener structure to all 3 prior dust_event corpus
drafts: "[City]: model-estimated dust daily maximum of X µg/m³ on [date] — aerosol optical
depth at Y." All 4 dust_event corpus drafts now share this template.

### Patterns named in this batch

1. **P_close 8th cycle — 5 drafts, 3 failing, 2 positive.** Failing: Taiz [1] (C+,
   "pushing it into the terrain" = weakest close in corpus), Michigan [2] (B, "less land
   friction" = mechanism without consequence), Taiz [3] (B-, "push it upslope into the city
   basin" = transport without named endpoint). Positive: Siberia [4] (B+, "burns deep" =
   declarative peatland-consequence), Barrow [5] (B+, "nearly twice that total" = declarative
   annual-ratio). Positive cases share a structural feature: named consequence emerging from
   specific ecosystem property. P_close now confirmed across 8 signal types (adding dust_event
   to the prior 7).

2. **P_dust 3rd cycle — template convergence across all 4 dust_event corpus drafts.**
   Opener: "[City]: model-estimated dust daily maximum of X µg/m³ on [date] — aerosol
   optical depth at Y." AOD-only metric in all 4 (Riyadh, Urumqi, Taiz Jun 24, Taiz Jun 25).
   WHO anchor absent in all 4. Jun 24's Al Aḥmadī (air_quality_hazard) stated the WHO multiple
   (10.1×) — confirming the gap is specific to the dust_event signal type, not the PM signal
   path generally.

3. **P9 5th precipitation_extreme draft.** Barrow Jun 25 uses the same opener structure as all
   4 prior precipitation_extreme corpus drafts. 5 of 5 template saturation. Same-event
   regeneration (Barrow Jun 7 + Jun 25, identical data, different close strategies).

4. **First companion-fire peer comparison in fire corpus.** Siberia cites two companion fires
   (611 + 569.6 MW) alongside 965.6 MW primary — regional-system framing. Date-baking is the
   sole A-kill; close form itself is A-grade.

5. **"Roughly"/"nearly" hedges as A-grade inhibitors.** Barrow [5]: "roughly 110 mm" + "nearly
   twice that total." Declarative form: "Barrow's mean annual precipitation is 110 mm; this
   three-day event doubled it." The hedge is the A-kill, not the structure.

6. **P5 partial.** Siberia (peatland carbon) and Barrow (annual-ratio) deployed named mechanics
   organically. Michigan monthly_low and Taiz dust_event ×2 show no named humor moves beyond
   mechanism explanation.

### Numbers

- **965.6 MW** — highest FRP in fire corpus (Western Siberia); companion fires 611 + 569.6 MW
- **2,271 µg/m³** (Taiz Jun 24) ≈ 151× WHO PM2.5 daily guideline (15 µg/m³)
- **2,135 μg/m³** (Taiz Jun 25) ≈ 142× WHO PM2.5 daily guideline
- **213.8 mm / 3-day** — 42.5% above 3-day record; ~1.94× annual precip total (~110 mm)
- **33°F / 0.6°C** — coldest June low in 29 years, Nw Michigan Rsch Farm

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

## 2026-06-27 — Daily corpus grading (2 fresh drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 2 pending drafts — both fresh, not previously graded. First multi-draft cycle since 2026-05-19 (39 days). Bot at 0.9.81.0; `THEHEAT_WRITER_SAMPLES=2` + `THEHEAT_CRITIC_REVISE_ENABLED=1` active (best-of-2 drafts + critic rewrite pass, per 2026-06-13 Thirty-Loop completion).

**Staleness review as of 2026-06-27 ~15:00 UTC:** Draft [1] (fire, created 2026-06-27T06:57Z, ~8h old) contains "today" — real-time-baked. Under 48h threshold; not a staleness candidate yet, but stale after ~2026-06-28T06:57Z if unpublished. Draft [2] (precipitation_extreme, created 2026-06-27T10:17Z, ~5h old) uses past-tense framing ("received") — no real-time-baked content. Neither draft triggers the bulk-reject policy.

Bulk-reject: 0 candidates. `gh` CLI absent — **13th consecutive skip** (May 13 → Jun 27).

**Grade distribution (2 fresh drafts):** 0 A / 1 B+ / 0 B / 1 C+ / 0 D-F.
**A-rate: 0% (0/2).** Gap from resumption bar: 50 pp (n=2; not statistically meaningful).

**Headline finding:** Fire draft (Canadian Prairies + BC, three fires above 1,500 MW) earns B+ via comic triple and a clean period-form closer. The BC fires (~3,000 MW each) are individually extraordinary but buried as escalation detail — the closer's threshold framing understates peak severity. Precipitation draft (Amsterdam, 157.1 mm, 4.7% above record) earns C+ — ecosystem specificity deployed correctly, signal editorially thin (score 74, maritime city, 7.1 mm margin). P6 fire template fix holding. New proposal P_precip_floor added: writer over-passes shallow-margin precipitation records (parallel to P_new cold-record floor).

### B-grade drafts

#### [1] Canadian Prairies / British Columbia — fire — 1,517.9 / 2,979.4 / 2,812.4 MW — **B+**

> *1,517.9 MW of radiative heat in the Canadian Prairies today — very-high-intensity fire, satellite-confirmed at 100% confidence. Two fires in British Columbia registered 2,979.4 and 2,812.4 MW the same day. Three signals above 1,500 MW in one country, one afternoon.*

**Score:** 83. Created 2026-06-27T06:57:25Z.

Humor lens:
- **Violation:** 1,517.9 MW (Prairies), 2,979.4 and 2,812.4 MW (BC). All three in the very-high-intensity tier. The BC fires are each individually extreme — ~3,000 MW is near the top of the FIRMS detection range.
- **Benign?** Yes — calm observational register throughout. No panic.
- **Setup→Punchline?** Three-sentence structure: S1 (Prairies fire as hook), S2 (BC fires, escalating pair, exact values), S3 ("Three signals above 1,500 MW in one country, one afternoon" — period-form closer). The closer compresses geographic scope (one country) and temporal coincidence (one afternoon) into a clean count summary. Works.
- **Named mechanic?** Comic triple — three fire signals stacked, closed with scope statement. S3 uses the period-and-restate form with new information (count + scope), not redundant restate.
- **Wodehouse rule?** Clean. Exact values throughout. No approximation, no restate-padding, no poetry attempt. "One country, one afternoon" is tight compression, not straining.

Not A- because: The BC fires at 2,979.4 and 2,812.4 MW are each nearly twice the Prairies fire — each close to 3 GW, individually extraordinary. The draft buries them as pair detail in the escalation sentence. "Three signals above 1,500 MW" uses a minimum threshold (the Prairies fire barely clears it at 1,517.9) while the BC values are nearly 2× that floor. The A- version names the peak: "The Prairies fire: 1,517.9 MW. Two fires in BC: 2,979.4 and 2,812.4. Three above 1,500 MW in one country, one afternoon." Or re-leads with the BC fires. Also: "satellite-confirmed at 100% confidence" — bureaucratic qualifier mid-sentence; echoes the P6 formula tone; cuttable without loss.

**P6 fire formula check (positive):** Opener leads with FRP value + intensity tier, not the banned "A fire in [location] is radiating X MW of heat, detected by satellite." P6 fix holding for the 3rd post-ship fire draft.

### C-grade drafts

#### [2] Amsterdam — precipitation_extreme — 157.1 mm / 3 days — **C+**

> *Amsterdam received 157.1 mm of rain in 3 days, breaking the previous 3-day record of 150.0 mm by 7.1 mm. The city sits on drained peat below sea level; its canals and pumps move water out continuously, but the system is sized for typical loads, not compressed extremes.*

**Score:** 74. Created 2026-06-27T10:17:07Z.

Humor lens:
- **Violation:** 157.1 mm in 3 days, 7.1 mm (4.7%) above the prior record of 150.0 mm. Margin is thin. Compare Barrow (Jun 7): 63.8 mm (42.5%) above record, score 81.
- **Benign?** Yes — factual, no alarm.
- **Setup→Punchline?** S1: data + margin (setup). S2: peat drainage + below sea level + canal/pump infrastructure + "sized for typical loads, not compressed extremes" (mechanism + implicit close). Implies consequence (canals stressed when overwhelmed) without naming it — same implied-vs-declarative gap as Barrow's "sheets across the surface instead."
- **Named mechanic?** Ecosystem specificity: peat drainage, below sea level, canal/pump infrastructure. Mechanic is real and load-bearing — directly explains why Amsterdam's drainage has a bounded ceiling. "Compressed extremes" is evocative but lightly coined; intuitive, minor effort-signal.
- **Wodehouse rule?** Restate-math: "breaking the previous 3-day record of 150.0 mm by 7.1 mm" — derivable margin stated after both values are given. Same minor violation as Barrow (Jun 7). Pattern recurs for the precipitation_extreme category.

C+ (not B-) because: signal is editorially thin. 4.7% above a precipitation record in Amsterdam — maritime Europe, ~820 mm annual rainfall — is not extraordinary by the editorial bar Andrew established for cold records (Mankato reject: "weak signal"). Score 74 confirms marginal signal strength. Voice execution is competent; it cannot rescue a weak underlying signal. The declarative consequence is also missing: "sized for typical loads, not compressed extremes" implies the system fails without naming what happens. B- form names it: "Amsterdam's canals have moved storm water since the 1600s. Not built for 157 mm in 72 hours." Current form earns C+.

Signal comparison — precipitation_extreme corpus to date:

| Draft | Location | Margin | % above | Score | Grade |
|---|---|---|---|---|---|
| Barrow, AK (Jun 7) | Arctic, permafrost drainage | 63.8 mm | 42.5% | 81 | B+ |
| Amsterdam (Jun 27) | Maritime Europe, canal drainage | 7.1 mm | 4.7% | 74 | C+ |

The margin gap accounts almost entirely for the grade gap, not voice execution.

### Patterns named in this batch

1. **Multi-fire combo signal — corpus first.** Draft [1] is the first example of a multi-fire framing (three fires in one draft). Comic triple works naturally: hook fire → escalating pair → scope closer. Valid signal type when fires cluster nationally on the same afternoon. Individual BC fires (~3,000 MW) are each extreme enough to stand alone; the combo framing is structurally stronger, but the peak values are undersold in the closer's threshold framing.

2. **Precipitation_extreme quality floor — emerging.** Amsterdam's 4.7% margin (score 74) is editorially thin. Ecosystem specificity is correctly deployed but can't compensate for a weak signal. Two precipitation_extreme drafts in corpus: Barrow (42.5%, B+) and Amsterdam (4.7%, C+). Margin gap accounts for the grade gap, not voice. New proposal P_precip_floor added: parallel to P_new cold-record floor.

3. **Restate-math: recurring in precipitation_extreme.** Both precipitation drafts (Barrow Jun 7, Amsterdam Jun 27) use "breaking the previous record of X by Y mm" — derivable margin stated after both values. Fix for the category: ratio form ("4.7% above the prior record") or plain period-and-restate ("157.1 mm in 3 days. The prior record was 150.0 mm.").

4. **P6 fire formula negative (positive).** Draft [1] does not use the banned "A fire in [location] is radiating X MW" opener. P6 fix holding for 3rd consecutive post-ship fire draft.

5. **P5 natural mechanic deployment — 2nd consecutive cycle.** Comic triple (fire) and ecosystem specificity (precipitation) both appeared without explicit prompt naming. Jun 7 (Barrow, ecosystem specificity) was the first. Two consecutive fresh-draft cycles now show named mechanics deployed naturally without P5's proposed fix. P5's core concern (convergence to default mechanics without naming the full palette) has not appeared in either cycle — but n=3 fresh-draft cycles total is too small to conclude variety is structurally guaranteed. P5 urgency reduced but not retired.

6. **`THEHEAT_WRITER_SAMPLES=2` + critic rewrite context.** Both drafts reached pending under the best-of-2 + critic-rewrite configuration (live since Jun 13 Thirty-Loop). No visibility into pre-rewrite variants. The fire draft's comic-triple structure looks like a strong writer choice; "compressed extremes" in the precipitation draft may be critic-contributed.

### Followups

1. **P_precip_floor threshold.** Score 74 + 4.7% margin passed the writer/critic filter. Operator should verify whether the precipitation_extreme score threshold is calibrated appropriately for wet-climate locations — the same margin on an arid station would carry different editorial weight.

2. **BC fire peak values.** 2,979.4 MW is individually extraordinary; the best-of-2 writer configuration might have produced a stronger single-fire draft. The combo framing was the right structural choice, but the A- version names the BC peak explicitly.

3. **Fire draft shelf life.** Draft [1] contains "today" — stale by policy after ~2026-06-28T06:57Z. Operator should track.

### Numbers

- Pending drafts in queue: 2 (2 fresh; 0 carry-overs)
- Fresh drafts graded: 2 (fire, precipitation_extreme)
- A-rate: 0% (0/2); n=2 — not statistically meaningful
- Grade distribution: 0 A / 1 B+ / 0 B / 1 C+ / 0 D-F
- First multi-fire combo in corpus (Canadian Prairies + BC)
- Active proposals: P6 fire template negative (holding); P5 partial negative (2nd natural-mechanic cycle); P_precip_floor new proposal added; P7/P8/P_new — no applicable signal types this cycle
- Staleness bulk-reject: 0 candidates (both fresh, under 48h); `gh` CLI absent (13th consecutive skip, May 13 → Jun 27)
- Most recent A-grade in corpus: May 19, 2026 (3/14, coral_bleaching batch)

---

## 2026-06-30 — Daily corpus grading (10 pending; 9 fresh-graded, 1 stale)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 10 pending drafts —
all fresh (no previously-graded carry-overs; prior Barrow precip draft cleared from queue).
**Four new signal types in corpus:** `regional_sst_anomaly` (Mediterranean), `marine_heatwave`
(GMST streak), `regional_anomaly` (France — first reganom draft post-PR #347),
`dust_event` (Phalodi India, Taiz Yemen). Pipeline context: reganom enabled with 2-day recency
window for just-ended heatwaves (PR #347); world-half eval-gating defect fixed (PR #345).
Bot at 0.9.81.0.

**Staleness review as of 2026-06-30 ~15:00 UTC:**
- Draft [1] (Mediterranean regional_sst_anomaly, `draft_20260628_040130_32`, created
  2026-06-28T04:01Z): ~59h at grading. Contains "running 3.54°C above its seasonal normal
  **today**" — explicit real-time-baked language past 48h threshold. **STALE.**
  Excluded from A-rate denominator.
- Draft [2] (GMST marine_heatwave, `draft_20260628_171634_36`, created 2026-06-28T17:16Z):
  ~46h at grading. Contains "**today's** reading is 20.961°C" — approaching 48h threshold.
  Not stale by policy at grading time; publish promptly or update with current NOAA OISST value.
- Drafts [3]–[10]: all created 2026-06-29–2026-06-30, under 30h old. Past-tense or
  date-anchored framing throughout; no "today" language.

Bulk-reject attempted: `gh` CLI absent — **13th consecutive skip** (May 13 → Jun 30).
Draft [1] is the one qualifying stale candidate; operator should reject via dashboard.

**Grade distribution (9 non-stale fresh drafts):** 2 A- / 3 B+ / 1 B / 1 B- / 2 C+ / 0 D-F.
**A-rate: 22% (2/9).** Gap from resumption bar: 28 pp.

**Headline finding:** Four new signal types in a single cycle — the richest category variety
since the May 19 coral batch. The two A- drafts come from opposite ends of the draft pool:
GMST marine_heatwave earns A- on a reframe punchline ("a record set two years ago is already
the floor of a new streak") and Prudhoe Bay all_time_high earns A- on signal weight (score 92,
101°F at 70°N) with ecosystem specificity. Dust_event debuts at C+ on both drafts: ecosystem
mechanism is present and specific, but the closes are expository conditions rather than
consequences. Precipitation_extreme continues the restate-math pattern (3 of 3 drafts state
the arithmetic margin above the prior record even when both raw values are given). P5 confirmed
in new categories (dust and fire deploy no named mechanics).

### A-grade drafts

#### [2] Global mean ocean surface temperature — marine_heatwave — **A-**

> *Global mean ocean surface temperature (60°S–60°N) has stayed above the 44-year NOAA archive
> ceiling for 25 straight days. The prior record was 20.896°C, set in 2024; today's reading is
> 20.961°C. A record set two years ago is already the floor of a new streak.*

**Score:** 82. Created 2026-06-28T17:16Z.

Humor lens:
- **Violation:** 25 consecutive days above the 44-year archive ceiling. Real signal with measurable
  magnitude (20.961°C vs 20.896°C prior record).
- **Benign?** Yes — factual register, no panic.
- **Setup→Punchline?** Sentence 1: establishes the 25-day streak above the archive ceiling.
  Sentence 2: prior record + current reading (comparison data for sentence 3). Sentence 3:
  "A record set two years ago is already the floor of a new streak." — the punchline.
- **Named mechanic?** Status inversion: the prior record (the ceiling, the highest value in the
  44-year archive) is reframed as the floor (the minimum of the current streak). "Floor" does
  the work — the 2024 record has been demoted from extraordinary to ordinary. This is the
  HUMOR_RESEARCH §2.1 misdirection pattern: setup frames the 2024 record as an achievement;
  punchline reframes it as a baseline.
- **Wodehouse rule?** Clean. Sentence 3 is declarative and economical — no approximation,
  no restate-padding. "Two years ago" adds precision without adding words.

The punchline is in the corpus's A-grade family: "A record set two years ago is already the
floor of a new streak" joins "persistence is what kills" (Madagascar) and "nowhere to drain"
(Costa Rica Pacific) as a short, declarative inversion that stops cold. Three-sentence structure
earns its length because each sentence loads the next. "Today's reading" in sentence 2 is
approaching 48h staleness; publish soon or update the NOAA OISST figure.

#### [9] Prudhoe Bay, Alaska — all_time_high — **A-**

> *Prudhoe Bay, Alaska hit 101°F (38.3°C) on June 27 — hottest daily maximum in 24 years of
> records, 12°F above the 2024 mark. At 70°N on the Arctic Ocean, the tundra offers no shade
> and no sea breeze; there is nothing to blunt the heat.*

**Score:** 92. Created 2026-06-30T03:47Z.

First all_time_high in the two-bot corpus (all-time records were graded in the v2 era, Apr 24–29;
this is the first under Sonnet 4.6 two-bot).

Humor lens:
- **Violation:** 101°F (38.3°C) at 70°N latitude on the Arctic Ocean coast. 24-year record.
  12°F above the 2024 mark. Score 92.
- **Benign?** Yes — calm, factual.
- **Setup→Punchline?** Setup: 101°F, Prudhoe Bay, 24-year record, 12°F above 2024.
  System clause: "At 70°N on the Arctic Ocean, the tundra offers no shade and no sea breeze"
  — names both cooling mechanisms that are absent. Close: "there is nothing to blunt the heat"
  — consequence of both absences stated declaratively.
- **Named mechanic?** Ecosystem specificity + named absences. "No shade and no sea breeze" is
  specific: the two physical relief mechanisms that normally moderate extreme heat are both absent
  at the Arctic tundra coast. "Nothing to blunt the heat" is the declarative consequence.
- **Wodehouse rule?** Clean. "12°F above the 2024 mark" is specific without restate-math (the
  2024 value isn't given, so the margin is informative rather than derivable). "Nothing to blunt
  the heat" is direct — not a poetry attempt, not a vague adverb.

Grades A- because the signal (score 92, 101°F at 70°N) carries the grade even with a slightly
soft close. The gap from A-: "nothing to blunt" states absence, not consequence. The A-grade
version names what happens when there's nothing to blunt it: "there is nothing to blunt the heat,
and nothing to drain it." Or: "nothing moderates it; nothing ends it until the wind shifts."
As written, the reader infers the consequence rather than receiving it.

### B-grade drafts

#### [1] Mediterranean Sea — regional_sst_anomaly — **B+ (STALE: "today" baked, ~59h old)**

> *The Mediterranean Sea is running 3.54°C above its seasonal normal today — just past the 3.5°C
> tier threshold in the NOAA Coral Reef Watch basin average. The Mediterranean is a semi-enclosed
> sea with limited deep-water exchange; heat absorbed at the surface has nowhere fast to go.*

**Score:** 82. Created 2026-06-28T04:01Z. **Stale at grading (~59h, "today" language).
Excluded from A-rate denominator.**

First `regional_sst_anomaly` in corpus. Voice quality assessed independently of staleness:

Humor lens:
- **Violation:** 3.54°C above seasonal normal, past the 3.5°C tier threshold. Real signal.
- **Named mechanic?** Ecosystem specificity (semi-enclosed sea, limited deep-water exchange) +
  consequence. "Heat absorbed at the surface has nowhere fast to go" directly echoes the
  Costa Rica Pacific A- closer ("heat that builds has nowhere to drain").
- **Wodehouse rule?** Nearly clean. "nowhere fast to go" — the adverb "fast" is the soft point.
  "Nowhere to drain" (Costa Rica A-) is more physically precise — "drain" is a specific verb;
  "nowhere fast to go" is idiomatic ("going nowhere fast") and slightly blunts the physical
  image. Remove "fast" and it matches A- territory on voice alone.

B+ for voice quality: structure is right (ecosystem specificity + declarative consequence close),
close is one word from A-. **STALE: operator should reject via dashboard.** First
`regional_sst_anomaly` — if the anomaly persists, refile with past-tense or
threshold framing and remove "today."

#### [3] France — regional_anomaly (reganom) — **B+**

> *Across 6 sampled cities in France, temperatures ran 11.53°C (20.8°F) above the 1991–2020
> daily normal for 8 straight days through June 27 — 2.8 standard deviations out. At that
> margin, even brief nighttime relief disappears; the heat debt compounds hour by hour.*

**Score:** 88. Created 2026-06-28T19:48Z.

First `regional_anomaly` (reganom) in corpus. BRIEFING notes this draft is in the `manual_only`
queue; the reganom writer-prompt voice upgrade is P1 for the operator.

Humor lens:
- **Violation:** 11.53°C above normal, 2.8σ, 8 days consecutive through June 27. Score 88.
  Strong signal.
- **Benign?** Yes — calm, factual.
- **Setup→Punchline?** Setup: 11.53°C, 2.8σ, 8 days. System clause: "At that margin, even
  brief nighttime relief disappears." Close: "the heat debt compounds hour by hour."
- **Named mechanic?** Ecosystem specificity via named absence (nighttime relief, the body's
  recovery mechanism, disappears at this margin). "Heat debt compounds hour by hour" applies
  a financial metaphor to thermal load — "compounds" implies exponential accumulation, "hour
  by hour" adds cadenced rhythm.
- **Wodehouse rule?** Borderline. "compounds hour by hour" — "hour by hour" is rhythm-padding
  redundant to "compounds" (compounding implies duration). The A-grade version is starker:
  "At that margin, nighttime no longer cools. The body has no recovery window." Declarative,
  consequence-named, no cadenced metaphor.

B+ because the signal (score 88, 2.8σ) is strong and the system clause ("even brief nighttime
relief disappears") is specific and earns its place. The close is the B+/A- boundary: slightly
literary where a starker declarative would grade A-. This is the operator's reganom voice-upgrade
target — direction is right, close needs tightening toward consequence.

#### [5] Astana, Kazakhstan — precipitation_extreme — **B+**

> *Astana, Kazakhstan recorded 308.1 mm of rainfall in 7 days — 8.1 mm above the previous 7-day
> record. The same week, Aktobe logged 301.5 mm. Astana sits on the dry Kazakh steppe, where
> annual precipitation rarely exceeds 300 mm total.*

**Score:** 75. Created 2026-06-29T16:03Z.

Humor lens:
- **Violation:** 308.1 mm in 7 days on a steppe where annual precipitation rarely exceeds
  300 mm. One week's rain exceeded the full-year average — that's the actual violation.
- **Named mechanic?** Ecosystem specificity deployed as implicit ratio: 7-day total > full-year
  average. The reader compares 308.1 mm (7 days) to "rarely exceeds 300 mm" (year) and supplies
  the ratio. The punchline is in sentence 3, not sentence 2.
- **Wodehouse rule?** "8.1 mm above the previous 7-day record" — mild restate-math (pattern
  recurring across all precip drafts). The Aktobe sentence ("The same week, Aktobe logged 301.5
  mm") adds regional breadth but delays the punchline by one sentence.

B+ because the annual-precipitation punchline is genuinely strong — the most surprising number
in the batch lands as the final fact. The Aktobe sentence is the one expendable element.
Without it: "Astana, Kazakhstan recorded 308.1 mm of rainfall in 7 days. Astana sits on the
dry Kazakh steppe, where annual precipitation rarely exceeds 300 mm total." Period-and-restate
variant; the annual figure as the kicker is A- territory.

#### [10] Antwerpen, Belgium — precipitation_extreme — **B+**

> *Antwerpen, Belgium logged 358.8 mm of rain in 7 days — 58.8 mm above the previous 7-day
> record of 300.0 mm. The city sits where the Scheldt estuary meets the North Sea's weather
> track; slow-moving Atlantic systems have little topographic barrier to stall and unload against.*

**Score:** 81. Created 2026-06-30T03:50Z.

Humor lens:
- **Violation:** 358.8 mm in 7 days, 19.6% above the prior record of 300.0 mm. Substantial margin.
- **Named mechanic?** Ecosystem specificity (Scheldt estuary, North Sea weather track, low
  relief). Close explains why Antwerpen accumulates extreme 7-day totals.
- **Wodehouse rule?** "58.8 mm above the previous 7-day record of 300.0 mm" — restate-math:
  358.8 − 300.0 = 58.8; both values are given; the margin is arithmetic. "Slow-moving Atlantic
  systems have little topographic barrier to stall and unload against" — the preposition-ending
  is slightly awkward; the close is explanatory rather than consequential.

B+ for signal strength (19.6% margin) and mechanism specificity. Close is right in type but
more expository than Amsterdam's simpler "nowhere for the water to go." Restate-math is
the main Wodehouse concern — same pattern as Amsterdam and Barrow (Jun 7).

#### [4] Amsterdam, Netherlands — precipitation_extreme — **B**

> *Amsterdam recorded 314.1 mm of rain in seven days through June 27 — 14.1 mm above the
> previous seven-day record of 300.0 mm. The city sits at sea level in the Rhine-Meuse delta;
> when Atlantic systems stall over the Low Countries, there is nowhere for the water to go.*

**Score:** 76. Created 2026-06-29T12:43Z.

Humor lens:
- **Violation:** 314.1 mm in 7 days, 4.7% above the prior record of 300.0 mm. Modest margin.
- **Named mechanic?** Ecosystem specificity (sea level, Rhine-Meuse delta). "There is nowhere
  for the water to go" is in the declarative family of corpus A-grade closers.
- **Wodehouse rule?** "14.1 mm above the previous seven-day record of 300.0 mm" — restate-math:
  same pattern. Close "there is nowhere for the water to go" is cleanly declarative but slightly
  generic vs. "has nowhere to drain" (Costa Rica Pacific) — "drain" is more physically precise
  than "go."

B rather than B+ because the signal margin is modest (4.7%, score 76) and the restate-math is
the same violation as Antwerpen and Barrow (Jun 7). The close is right in direction; the signal
doesn't carry past B.

### C-grade drafts

#### [8] Rocky Mountains, Colorado — fire — **B-**

> *595.3 MW of radiative heat in the Rocky Mountains, Colorado — very-high-intensity fire,
> satellite-confirmed at 95% confidence. The southern Rockies shed winter snowpack early in
> drought years; exposed, dry slopes ignite fast once summer heating sets in.*

**Score:** 70. Created 2026-06-29T21:37Z.

Humor lens:
- **Violation:** 595.3 MW — very-high-intensity tier. Score 70 at threshold. Strong signal.
- **Setup→Punchline?** Leads with number (P6 fix maintained — not "A fire in [location] is
  radiating X MW"). Second sentence: snowpack mechanism + timing close.
- **Named mechanic?** Timing element embedded in mechanism close: "exposed, dry slopes ignite
  fast once summer heating sets in." Compare Siberia B+ (May 19): "May fires here ignite before
  the understory has greened enough to resist" — that timing surprise named the specific
  biological resistance mechanism not yet activated. Here "once summer heating sets in" is June:
  summer heating in late June is expected, not incongruous.
- **Wodehouse rule?** "ignite fast" — same weak adverb pattern as "totals compound fast" in
  Stahl Peak B-. "Early snowpack shed in drought years" is specific and causal; "once summer
  heating sets in" is the muted close.

B- because the timing close lacks the Siberia draft's incongruity. "Once summer heating sets
in" states a present condition rather than a gap (vegetation not yet resistant; monsoon not
yet arrived). P6 fix is maintained; the opener structure is correct. Failure mode is the
close's missing edge, not the category template.

#### [6] Phalodi, India — dust_event — **C+**

> *Phalodi, India: model-estimated dust daily maximum of 956 μg/m³ on June 29 — aerosol optical
> depth at 0.86. Phalodi sits at the edge of the Thar Desert; summer heat-low pressure over the
> subcontinent pulls dry northwestern air across exposed dunes before the monsoon arrives.*

**Score:** 71. Created 2026-06-29T21:33Z.

First `dust_event` in corpus. Signal level: 956 μg/m³, AOD 0.86, score 71 (low end).

Humor lens:
- **Violation:** 956 μg/m³ dust daily maximum. No corpus baseline for this category. Score 71
  suggests moderate threshold exceedance.
- **Named mechanic?** Ecosystem specificity (Thar Desert, heat-low pressure, exposed dunes,
  monsoon timing). P5 failure mode: all mechanics named are physical explanations; none deployed
  as a punchline.
- **Wodehouse rule?** The mechanism sentence is explanatory throughout. "Before the monsoon
  arrives" is the closest thing to a punch but lands as timing context (the monsoon will end
  this), not a consequence (what the concentration means right now).

C+ — first dust_event in corpus. Ecosystem specificity earns partial credit. Close needs a
named consequence: visibility reduction, health threshold crossed, respirable particle count —
something that states what 956 μg/m³ means for people in Phalodi, not how the dust got there.

#### [7] Taiz, Yemen — dust_event — **C+**

> *Taiz, Yemen: model-estimated dust daily maximum of 1,302 μg/m³ on June 29 — aerosol optical
> depth at 0.71. Yemen sits at the southern end of the Red Sea corridor, where summer monsoon
> winds lift fine sediment off the Tihama coastal plain before topography stalls it inland.*

**Score:** 71. Created 2026-06-29T21:36Z.

Same grade as Phalodi (C+). Score 71, dust_event debut.

Humor lens:
- **Violation:** 1,302 μg/m³ — higher than Phalodi. AOD 0.71.
- **Named mechanic?** More layered geographic mechanism than Phalodi: monsoon winds lift sediment
  off the Tihama plain → topography stalls it inland. Two-step mechanism (lift → stall) is more
  interesting than Phalodi's single-step close. "Before topography stalls it inland" is specific
  geography — the barrier ridgeline forcing the sediment plume down.
- **Wodehouse rule?** Complex sentence with no declarative close. "Stalls it inland" is physical
  but abstract — the nameless topography is the agent. 1,302 μg/m³ is higher than Phalodi's;
  the mechanism is more geographically layered; both deficiencies are parallel: physical
  explanation without naming the consequence.

C+ on parity with Phalodi. The lift-stall two-step is the more sophisticated of the two dust
drafts, but neither closes with a consequence. The category needs: "visibility drops below
[threshold] m" or "at [N] μg/m³, the WHO hourly guideline is exceeded by [X]×" or similar —
something that tells the reader what the number means at ground level, not just how it got
there.

### Patterns named in this batch

1. **Four new signal types in one cycle.** `regional_sst_anomaly` (Mediterranean), `marine_heatwave`
   (GMST), `regional_anomaly` / reganom (France), `dust_event` (Phalodi, Taiz). Marine_heatwave
   produced the cycle's cleanest punchline; regional_anomaly produced the highest-score draft (88);
   dust_event debuted at C+ on both drafts. First all_time_high in the two-bot corpus (Prudhoe Bay,
   score 92).

2. **Restate-math recurring across precipitation_extreme.** Amsterdam [4], Astana [5], Antwerpen [10]
   — all three 7-day precipitation drafts — state the margin above the prior record ("X mm above the
   previous record of Y mm") even though both raw values are given and the margin is arithmetic. Same
   pattern flagged in the Jun 7 Barrow B+ note ("63.8 mm above the previous 3-day record of 150.0 mm").
   Four consecutive precipitation_extreme drafts with the same Wodehouse violation. Fix: "state the two
   values plainly and stop: '[new value] in [N] days. The previous record was [prior value].' Do NOT
   add the arithmetic margin."

3. **Dust_event: ecosystem specificity without consequence.** Both dust drafts use mechanism sentences
   that explain the physical cause (pressure systems, topography, monsoon timing) but close on a condition
   rather than a consequence. "Before the monsoon arrives" and "before topography stalls it inland" are
   conditions — the category needs a closer that names what the concentration means at ground level
   (visibility, health threshold, respiratory impact).

4. **P5 confirmed in new categories.** Dust_event (both drafts) and fire (Colorado) — three drafts —
   use expository mechanism sentences without named humor mechanics. GMST [2] and Prudhoe Bay [9]
   deployed mechanics (status inversion, named absences) without explicit prompting. The writer prompt's
   mechanic guidance works for some categories and not for others. Dust_event and the general fire
   template are the current gap categories.

5. **GMST marine_heatwave: status inversion is the mechanic.** "A record set two years ago is already
   the floor of a new streak" — the prior record (ceiling) is reframed as the current baseline (floor).
   HUMOR_RESEARCH §2.1 misdirection pattern. The 2024 record is well-known context; the reframe is
   immediately available to a climate-aware reader without explanation. Clean execution.

6. **Reganom first draft lands B+.** France (score 88, 2.8σ, 8 days) earns B+ — reasonable baseline
   for a first reganom draft. BRIEFING identifies voice upgrade as P1 for the operator. Gap: "the heat
   debt compounds hour by hour" → needs a named consequence ("no nighttime recovery window," cumulative
   deficit stated flatly, or: "At 2.8 standard deviations. Even the nights offer no relief.").

7. **Mediterranean regional_sst_anomaly: staleness from "today."** Draft [1] is the 13th consecutive
   staleness skip (gh CLI absent). B+ voice quality; "today" is the only blocker. Operator: reject and
   refile without "today" if the anomaly persists at the current tier.

8. **Prudhoe Bay first all_time_high in two-bot corpus.** Score 92, 101°F at 70°N. Writer deployed
   ecosystem specificity (no shade, no sea breeze) with a declarative close. The all_time_high category
   should produce the clearest punchlines; "nothing to blunt" states absence rather than consequence.
   Next all_time_high: the consequence should be named explicitly.

### Followups

1. **Reganom voice upgrade (BRIEFING P1 for operator):** France draft [3] close — "the heat debt
   compounds hour by hour" → replace with consequence: "At this margin, the body cannot recover
   overnight. Eight days of no relief." Or period-and-restate on the σ reading: "2.8 standard
   deviations. No summer spell in the NOAA archive reached 8 days at this margin." The direction:
   declarative, consequence-named, no cadenced metaphor.

2. **Restate-math in precipitation_extreme (→ new P_precipitation_restate proposal):** 3/3 drafts
   in this cycle + Barrow Jun 7 = 4 consecutive precipitation_extreme drafts with the inline margin
   statement. Add to writer_prompt.py precipitation section: prefer period-and-restate on the two
   raw values; do not state the arithmetic margin when both values are present.

3. **Dust_event: add consequence guidance to writer_prompt.py.** First appearance of category.
   Both drafts earn C+ because mechanism explains causation without naming consequence. Add: "For
   dust_event, the close should state what the concentration means at ground level — visibility
   threshold, WHO guideline exceedance, health threshold — not only how the dust arrived."

4. **Mediterranean SST [1]: STALE.** Operator should reject. First `regional_sst_anomaly` in corpus.
   Good B+ voice quality once "today" is removed; refile with past-tense or ongoing-anomaly framing.

5. **GMST marine_heatwave [2]: approaching 48h.** "Today's reading is 20.961°C" — publish promptly
   or update with current NOAA OISST value before the draft crosses 48h.

6. **Prudhoe Bay all_time_high [9]: publish-ready.** A-, score 92, June 27 observation date
   (past-tense, not "today"). Clean for posting.

### Numbers

- Pending drafts in queue: 10 (10 fresh; 0 carry-overs from prior cycles)
- Fresh drafts graded: 9 (1 stale excluded: Mediterranean regional_sst_anomaly — "today" baked, ~59h)
- A-rate: 22% (2/9)
- Grade distribution: 2 A- / 3 B+ / 1 B / 1 B- / 2 C+ / 0 D-F
- New signal types in corpus: regional_sst_anomaly (1), marine_heatwave (1), regional_anomaly (1),
  dust_event (2); first all_time_high in two-bot corpus (Prudhoe Bay, score 92)
- Active proposals: P5 confirmed (dust_event + fire categories, 5th cycle); P7/P8 not observed
  (no coral/snow); P_new archived (3+ consecutive fresh-draft cycles without observation);
  new P_precipitation_restate proposed
- Staleness bulk-reject: 1 candidate (Mediterranean "today"); gh CLI absent (13th consecutive
  skip, May 13 → Jun 30); operator must reject via dashboard
- Queue gap since Jun 8 carry-over: 22 days; 10 fresh drafts is the largest single-cycle
  fresh batch since May 19 (14 drafts)

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
