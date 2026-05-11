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

## 2026-05-11 — Daily corpus grading (8 drafts)

**Context:** First grading cycle on two-bot pipeline output post-May 4 port. Signal mix: three cold-record monthly_lows (Hill City SD, Mankato MN, Baudette MN), three severe heat warnings (Phoenix Metro ×2, Imperial County CA), one storm surge (Cook Inlet AK), one blizzard warning (Point Lay AK). First appearance of monthly_low cold-record signal type in this corpus. No fire or heat record drafts. `evaluator_pass: None` on all 8 drafts — same pattern as Apr 29; Sonnet evaluator either disabled or not logging verdict. Three drafts stale (>48h with dated/forecast references): [1], [2], [3].

**Grade distribution:** 1 A-, 3 B+, 2 B, 2 B-. **A-rate: 12.5% (1/8).**
Gap from resumption bar: 37.5 percentage points.

### A range (1)

#### [8] Point Lay, Alaska — blizzard warning — score 63 — **A-**

> Blizzard Warning for Point Lay, Alaska — an Inupiat village on the Chukchi Sea — on May 11th. No falling snow needed: 40 mph winds are picking up what's already on the ground and cutting visibility to a quarter mile. The calendar says spring.

Three moves stacked, none trying:

1. **Place-identity specificity.** "An Inupiat village on the Chukchi Sea" gives the place its character without sentimentalizing it. Reader's model of the location sharpens immediately.
2. **Mechanism explanation as voice move.** "No falling snow needed" is misdirection — you expect a blizzard to require precipitation. The explanation of the ground-blizzard mechanism is genuinely informative AND is itself the violation (existing snowpack dense enough to white-out in May). This is a move not catalogued in prior corpus entries: explaining HOW the violation works, not just asserting THAT it does. Stronger than any of the timing-closers-only drafts in this batch.
3. **Timing closer.** "The calendar says spring." — clean descendant of "It's April." with one ironic degree added ("says" implies the calendar is being contradicted). Tighter than "May, not July." in [2] because it doesn't explain the irony; the reader supplies it.

Wodehouse: perfect. No visible effort. Each sentence earns its place.

### B+ range (3)

#### [7] Baudette, Minnesota — monthly_low — score 82 — **B+**

> Baudette, Minnesota hit 18°F (-7.8°C) overnight on May 7th — coldest May low in 31 years of records, breaking the 21°F mark set in 2002 by 3°F.

Pure data delivery. 31 years is near-full-archive depth. 18°F in May + 3°F margin = three substantive data points that carry without needing a voice mechanic. No Wodehouse violations. "2002" is in `era_anchors.json` but the gate correctly didn't fire (1-in-10). Would benefit from a closer but lacks nothing that isn't absence of upside.

#### [1] Hill City, South Dakota — monthly_low — score 80 — **B+**

> Hill City, South Dakota hit 13°F (-10.6°C) overnight on May 6th — coldest May night in 59 years of records, breaking the 14°F mark set in 2002.

59 years is the strongest record depth in this batch. Pure data delivery, clean execution. "2002" again — same anchor year as [7], same gate-correct non-deployment. No Wodehouse violations. Lacks a voice move that could elevate to A. **Stale: created 2026-05-09T06:18Z (>48h), contains "May 6th" dated reference. Bulk-reject.**

#### [6] Mankato, Minnesota — monthly_low — score 79 — **B+**

> Mankato, Minnesota hit 30°F (-1.1°C) overnight on May 6th — coldest May low in 16 years of records there, edging out the 30°F mark set in 2020 by a tenth of a degree Celsius. A record is a record.

"A record is a record." is a genuine voice moment — dry tautology that acknowledges the marginal nature of the signal without apologizing. The detail that both temperatures round identically in Fahrenheit (30°F) but differ by a tenth Celsius is specific and earns the closer's wry shrug. 16 years is the weakest record depth in the batch, so the voice work carries more load here than in [1] or [7].

### B range (2)

#### [5] Anchorage Cook Inlet — storm_surge — score 63 — **B**

> Anchorage's Cook Inlet recorded a storm surge 0.587 m above predicted tide on May 10th — water levels hitting 5.228 m against a forecast of 4.641 m. Cook Inlet's tidal range is already among the largest in North America. Extra water on top of that gets noticed.

"Extra water on top of that gets noticed." is an understatement closer — genuine Wodehouse compliance ("gets noticed" = it's serious but said quietly). Ecosystem context (Cook Inlet's tidal range) is apt and correctly frames the signal. Dense numerical setup is the structural weakness: two pairs of precise figures before the interesting part, reader does calculation. Signal strength (0.587m on a multi-meter tidal range) is modest; the framing rescues it better than the raw number would.

#### [3] Phoenix Metro — severe_weather — score 60 — **B**

> 105–109°F (41–43°C) forecast across Phoenix Metro Sunday into Monday. Nine zones from Buckeye to Queen Creek under Extreme Heat Warning. May 9th.

Lead-with-the-number opener (correct). "Nine zones from Buckeye to Queen Creek" is specific geography. "May 9th." is a clean timing closer — same family as "It's April." — and it IS the closer; nothing follows to undercut it. No Wodehouse violations. **Stale: created 2026-05-09T09:23Z (>48h), "Sunday into Monday" is past. Bulk-reject.**

### B- range (2)

#### [2] Phoenix Metro — severe_weather — score 60 — **B-**

> Phoenix Metro under Extreme Heat Warning Sunday through Monday: 104–110°F (40–43°C) across nine zones from Buckeye to Queen Creek. May, not July. NWS rates the risk as Major.

"May, not July." is the real voice moment — understatement contrast, same family as "It's April." but more explicit. **Stranded-mechanic violation (P3 evidence):** the voice beat lands in the middle; "NWS rates the risk as Major" follows it and defuses the closer. "NWS rates the risk as Major" is also borderline label:value territory. Compare with [3]: same event, tighter execution, "May 9th." as actual closer. [3] outperforms [2] precisely because [2]'s punchline is stranded. **Stale: created 2026-05-09T06:19Z (>48h). Bulk-reject.**

#### [4] Imperial County, California — severe_weather — score 60 — **B-**

> Imperial County, California — the Salton Sea corridor — bracing for 101–112°F (38–44°C) Sunday through Monday evening. The Sonoran Desert floor at its most unforgiving, weeks before summer solstice.

"The Salton Sea corridor" is strong ecosystem specificity. "weeks before summer solstice" is the timing closer and earns its place. **Wodehouse violation (P1 evidence):** "The Sonoran Desert floor at its most unforgiving" tells the reader the data is serious — the numbers already do that. Editorial descriptor where none is needed; slight effort shows. Not quite 48h old (created 2026-05-09T16:59Z, ~46h elapsed at grading time) but forecast window ("Sunday through Monday evening") is functionally past.

### Patterns named in this batch

1. **Timing-closer family dominant.** Four of eight drafts use timing-as-punchline closers ("May 9th.", "The calendar says spring.", "May, not July.", "weeks before summer solstice"). The family is well-established and working. [8]'s "The calendar says spring." is the best execution because it adds ironic ambiguity ("says" implies the calendar is wrong) without over-explaining.
2. **Wodehouse violations persist in severe-weather drafts.** [4]'s "at its most unforgiving" is the clearest instance — editorial heat the data doesn't need. Pattern is no longer fire/record-specific; it's prompt-wide. P1 evidence: fifth cycle. Highest-leverage unimplemented proposal.
3. **Stranded-mechanic pattern extends to severe weather.** [2]'s "May, not July." is a real voice move killed by the following NWS line. Same shape as Apr 27 fire drafts [3], [4], [12]. P3 evidence: second cycle.
4. **Mechanism explanation as new voice move.** [8]'s "No falling snow needed" is a move not in the current prompt tool palette — explaining HOW the violation works. More engaging than stating THAT it does. Candidate for P2 enrichment (name humor moves as tools).
5. **First cold-record signal type in corpus.** Monthly_low drafts grade consistently B+ on pure data delivery. No specific failure mode emerged; the signal type handles cleanly with the existing voice approach.
6. **Era-anchor gate working correctly.** [1] and [7] both reference 2002 records; neither deployed an era anchor. Gate at 1-in-10 doing its job.

### Followups

1. **Bulk-reject stale drafts [1], [2], [3]** (>48h, dated/forecast references) — attempt via `gh api -X PATCH`. Log result in `docs/QUALITY_TREND.md`.
2. **P1 (Wodehouse rule) is the highest-leverage unimplemented proposal** — 5 cycles, present across fire/record/severe-weather signal types. Implement as rule #0 in `src/two_bot/prompts/writer_prompt.py`.
3. **P3 (stranded mechanics)** — drafted addendum originally targeted fire prompt; May 11 evidence shows same pattern in severe-weather drafts. Extend to both addenda.
4. **P2 (name humor moves)** — add "mechanism explanation" (explain HOW the violation works) to the tool palette, with [8] "No falling snow needed" as the corpus exemplar.

### Numbers

- Pending drafts: 8
- A-rate: 12.5% (1/8)
- Gap from bar: 37.5 points
- Stale (>48h): [1] [2] [3] — bulk-reject attempted
- Era-anchor deployment: 0% (no record drafts in batch; gate not triggered)
- Evaluator_pass: None on all 8 (second consecutive batch — investigate separately, out of scope for voice work)

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
