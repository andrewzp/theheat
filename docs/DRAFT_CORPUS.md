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

## 2026-05-21 — First post-critic cycle, new signal types (14 new drafts)

**Context:** Gist read via git-clone path (success; no rate limit). Queue: 18 pending
drafts total — 4 are May 12–13 carryovers already graded in the 2026-05-13 corpus section
(Mali fire C+, Campeche fire C, Chuuk monthly_high B, Mongolia fire C; still pending, not
published or rejected). This entry grades the 14 new drafts (5–18) created since then.

**Pipeline state:** Two notable additions since the May 13 cycle: (1) **PR #119** widened
the WORLD_KNOWLEDGE fact-check gate so the writer's external knowledge (geographic
mechanisms, climate system descriptions) can ship without a data-bundle anchor.
(2) **PR #120** added the **F3 second-pass editorial critic** (Gemini 2.5 Pro, PASS/KILL
only, no rewrite) as the final gate before the human-approval queue. The F3 critic went
live ~2026-05-15T05:11Z. The May 15 coral batch (drafts 7–14) was created 03:01–05:20Z
on the same day — mostly in the same cron cycle that preceded deployment — and reached
pending **without critic review**. The May 18 batch (drafts 15–18) was created three days
later and passed the critic. **PR #121** added JSON-parse retry for fact_check and critic.

**Grade distribution (14 new drafts):** 1 A, 8 B-range, 5 C-range, 0 D/F.
**A-rate: 7% (1/14).** Gap from resumption bar: 43 points.

### Per-draft

#### [5] Bethel, Maine monthly_low — 28°F / -2.2°C — **B-**

> *Bethel, Maine hit 28°F (-2.2°C) on May 9 — coldest May low in 16 years of records, a
> degree below the 2017 mark. The upper Androscoggin Valley sits in a bowl surrounded by
> the White Mountain foothills; cold air drains into it on still nights and holds.*

**Score:** 80 (threshold 76). Created 2026-05-13T21:29Z.

Humor lens:
- **Violation:** Coldest May low in 16 years. Present.
- **Benign?** Yes — factual, calm.
- **Setup→Punchline?** Data is setup. Second sentence is geographic mechanism: why the
  valley records cold extremes. No punchline.
- **Named mechanic?** None. Ecosystem specificity (bowl topography, cold air drainage).
- **Wodehouse rule?** Clean. No restate-padding, no defensive justification, no
  approximation-when-exact-available.

Voice spec met: specific location, both scales (°F/°C), observation date (May 9),
archive depth (16 years), prior record year (2017), margin (1 degree). The geographic
second sentence is competent — "cold air drains into it on still nights and holds" is a
mechanism, not just a description. But 16-year archive is shallow, the 1°F margin is
small, and cold records in May carry less editorial weight than heat records. No named
mechanic operating. B- for meeting the spec without landing a punch.

#### [6] British Columbia fire — 426.8 MW — **C+**

> *British Columbia has a 426.8 MW fire burning today, satellite-detected at 95%
> confidence — high-intensity tier. The Rocky Mountain Trench funnels downslope winds
> that can accelerate spread before spring humidity builds.*

**Score:** 66 (threshold 64). Created 2026-05-14T21:14Z.

Humor lens:
- **Violation:** 426.8 MW high-intensity fire. Present.
- **Benign?** Yes.
- **Setup→Punchline?** Data is setup. Second sentence: geographic wind mechanism.
  Explanation, not punchline.
- **Named mechanic?** None. Ecosystem specificity (Rocky Mountain Trench, downslope
  winds).
- **Wodehouse rule?** Clean. "can accelerate spread" hedges slightly but not a
  try-hard signal.

Two improvements over the May 13 fire formula (P6): different opener structure
("has a 426.8 MW fire burning today" vs. "is radiating X MW"), and uses the FRP
tier label ("high-intensity tier"). "today" is baked into the text — draft is 7 days
old and stale per the 48-hour policy. Second sentence is geographic explanation
without a kicker. C+ for opener variety and tier label, held back by "today" staleness
and no punchline.

**Staleness flag:** "today" baked in; created 2026-05-14, >48h old. Bulk-reject
candidate.

#### [7] Western Madagascar coral bleaching — 10.2 DHW — **B**

> *Western Madagascar's reef system has accumulated 10.2°C-weeks of thermal stress —
> past the 8°C-week threshold where mass bleaching is expected. Corals can survive brief
> spikes; DHW measures how long heat persists, and persistence is what kills.*

**Score:** 81 (threshold 76). Created 2026-05-15T03:01Z.

Humor lens:
- **Violation:** 10.2 DHW past the 8°C-week mass-bleaching threshold. Real signal.
- **Benign?** Yes — calm, factual register.
- **Setup→Punchline?** Second sentence teaches the DHW metric while landing a point:
  "persistence is what kills." Setup = "corals can survive brief spikes." Punchline =
  "persistence is what kills." The pivot has setup-punchline shape.
- **Named mechanic?** Near-understatement: "persistence is what kills" is direct, final,
  bare. The closest thing to a voice punch in the coral batch.
- **Wodehouse rule?** Clean.

First coral bleaching draft in the corpus. The DHW framing requires explanation for
general audiences; this draft delivers it efficiently and ends with a punchy phrase.
"Persistence is what kills" does more work than a pure geography line. B for competent
new signal type with a functional closing move; withheld from B+ because the mechanic
is implicit rather than fully landed.

#### [8] Fiji coral bleaching — 10.1 DHW — **B-**

> *Fiji's reefs have accumulated 10.1°C-weeks of thermal stress — past the 8°C-week
> threshold where mass bleaching is expected. The South Pacific Convergence Zone keeps
> waters here warm; sustained heat above the tolerance ceiling is what turns stress into
> die-off.*

**Score:** 81 (threshold 76). Created 2026-05-15T03:02Z.

Same opener structure as Draft [7]: "[Location]'s reefs have accumulated X.X°C-weeks
of thermal stress — past the N°C-week threshold where mass bleaching is expected."
Second sentence adds geographic context (SPCZ) then a mechanism statement: "sustained
heat above the tolerance ceiling is what turns stress into die-off." The SPCZ
specificity is valid; the closer is longer and more technical than Draft [7]'s
"persistence is what kills." Template convergence beginning: same sentence-1 as Draft
[7], same threshold frame, similar mechanism closer. B- for the softer closer and
onset of template pattern.

#### [9] Nauru coral bleaching — 8.2 DHW — **C+**

> *Nauru's reefs have accumulated 8.2°C-weeks of thermal stress — past the 8°C-week
> threshold where mass bleaching is expected. DHW measures heat duration, not just
> intensity; it's persistence above the tolerance ceiling that kills coral.*

**Score:** 80 (threshold 76). Created 2026-05-15T03:04Z.

Third instance of identical sentence-1 structure. Second sentence: "DHW measures heat
duration, not just intensity; it's persistence above the tolerance ceiling that kills
coral." This is explicit metric explanation. "Not just intensity" contrast is a common
science-communication shape. The phrase "kills coral" echoes Draft [7]'s "kills"
closer but is more diluted ("that kills coral" vs. "persistence is what kills"). Third
coral draft with the same opener formula. Template convergence confirmed. C+ for the
formula repetition, narrowly above C because the second sentence does explain the metric.

#### [10] Great Nicobar, India coral — 7.2 DHW — **C**

> *Great Nicobar, India: 7.2°C-weeks of thermal stress — Bleaching Alert Level 1,
> closing in on the 8°C-week threshold where mass bleaching is expected. DHW measures
> heat persistence, not just intensity; it is duration above the tolerance ceiling that
> kills coral.*

**Score:** 75 (threshold 74). Created 2026-05-15T03:47Z.

Below the 8°C-week mass-bleaching threshold (7.2 DHW = Alert Level 1, not mass
bleaching expected). The framing acknowledges this: "closing in on 8." Second sentence
is nearly identical to Draft [9]'s second sentence. Fourth coral draft. Opener shifted
to a colon structure ("Great Nicobar, India: 7.2°C-weeks") which is different from
"has accumulated" — slight variety. But below-threshold signal + repeated DHW
explanation = C.

#### [11] Chagos Archipelago coral — 7.2 DHW — **C**

> *Chagos Archipelago reefs have accumulated 7.2°C-weeks of thermal stress — Bleaching
> Alert Level 1, approaching the 8°C-week threshold where mass bleaching is expected.
> DHW counts how long heat persists above the tolerance ceiling; proximity to 8 is what
> matters.*

**Score:** 75 (threshold 74). Created 2026-05-15T03:48Z.

Below-threshold, same 7.2 DHW as Draft [10]. Opener reverts to "has accumulated"
structure. Second sentence: "proximity to 8 is what matters" is a slight variation —
has some edge compared to the previous iteration's metric explainer. But fifth coral
draft with the same general opener shape and below-threshold signal. C.

#### [12] Southern Borneo coral — 4.4 DHW — **C**

> *Southern Borneo's reefs have reached 4.4°C-weeks of thermal stress — crossing the
> 4°C-week floor where bleaching begins. Borneo sits at the heart of the Maritime
> Continent, where warm seas and island topography drive the convection that keeps
> surrounding waters persistently hot.*

**Score:** 74 (threshold 74). Created 2026-05-15T03:55Z.

Floor-crossing (4.4 DHW, bleaching-watch level), not threshold-exceeded. Sixth coral
draft. Second sentence is geographic: "Borneo sits at the heart of the Maritime
Continent" — Maritime Continent is a real climate-science term, and the
island-topography/convection framing is specific. But the geographic context explains
why Borneo is warm in general; it doesn't explain why this reading matters now or what
the floor-crossing signals. C for lowest-tier signal + geographic-explanation second
sentence.

#### [13] Galapagos coral bleaching — 24.5 DHW — **B+**

> *Galapagos, Ecuador reefs: 24.5°C-weeks of thermal stress — double the 12°C-week
> tier where coral mortality is expected. The Galapagos sits where cold upwelling
> normally buffers heat; when that buffer fails, stress accumulates fast.*

**Score:** 88 (threshold 74). Created 2026-05-15T05:16Z.

Strongest coral draft by signal magnitude and framing. Three things separate this:
1. 24.5 DHW is double the 12°C-week CORAL MORTALITY tier (not just bleaching). The
   most extreme signal in the coral batch by a wide margin.
2. Opener uses colon-lead ("Galapagos, Ecuador reefs: 24.5°C-weeks") — different
   structure from the "has accumulated" pattern.
3. "The Galapagos sits where cold upwelling normally buffers heat; when that buffer
   fails, stress accumulates fast." — this is the first coral second sentence that
   names a system and its failure. Establishes what should prevent this, then names
   that it has failed. The Galapagos cold-upwelling/Darwin-biodiversity narrative is
   real; the buffer-failure framing is doing voice work.

"Stress accumulates fast" is slightly flat as a landing after "when that buffer fails"
— the punch is set up but doesn't fully land. B+ for strongest signal, real mechanism
framing, and genuine incongruity in the system clause. Narrowly misses A- because the
closer doesn't complete the punch.

#### [14] Austral Islands coral — 8.6 DHW — **B-**

> *Austral Islands reefs: 8.6°C-weeks of thermal stress — past the 8°C-week threshold
> where mass bleaching is expected. The Austral chain sits at the southern edge of the
> South Pacific Convergence Zone; heat that persists this far from the warm pool signals
> the band has stretched.*

**Score:** 80 (threshold 74). Created 2026-05-15T05:20Z.

Threshold-exceeded (8.6 DHW). Colon-lead opener (like Drafts [10] and [13]). Second
sentence makes the location do voice work: southern edge of the SPCZ, "heat that
persists this far from the warm pool." The "band has stretched" framing gestures at
something: the SPCZ or warm-pool boundary is expanding. This is the closest the
coral batch comes to a geographic-anomaly framing (place is the unusual part, not just
the number). But "the band has stretched" is underdeveloped — it asserts a trend
without quantifying it. B- for geographic voice move that doesn't quite land.

#### [15] Costa Rica Pacific coral — 12.0 DHW — **A-**

> *Costa Rica Pacific reefs: 12.0°C-weeks of thermal stress — at the tier where NOAA
> Coral Reef Watch expects coral mortality. The Pacific coast here lacks the cold
> upwelling that buffers the Galápagos; heat that builds has nowhere to drain.*

**Score:** 86 (threshold 74). Created 2026-05-18T01:30Z. **Post-F3 critic.**

Humor lens:
- **Violation:** 12.0 DHW at the coral mortality tier. Strong signal.
- **Benign?** Yes, calm authority throughout.
- **Setup→Punchline?** "lacks the cold upwelling that buffers the Galápagos; heat that
  builds has nowhere to drain." First clause establishes what's missing (by contrast
  to the Galápagos); second clause lands the consequence. Setup→punchline shape.
- **Named mechanic?** Comparative framing (Galápagos contrast) + understatement closer
  ("nowhere to drain"). "Nowhere to drain" is British-dry understatement: the coastal
  ecology is described as a system with no escape valve; "drain" is precise and flat.
- **Wodehouse rule?** Clean. "nowhere to drain" does not try too hard. The comparison
  does not overexplain.

The Galápagos comparison is load-bearing: it establishes the cold upwelling mechanism
in the reader's mind (Draft [13] introduced it) and uses it as a contrast baseline.
"Heat that builds has nowhere to drain" is the best closer in the full pending batch.
First A-grade from the two-bot pipeline. The critic passed it; it passes the
stop-mid-scroll / send-it-to-a-friend bar. Deduct for A (vs. A) because the
comparative framing relies on reader recall of Galápagos context rather than carrying
it in full; as a standalone tweet the "buffers the Galápagos" reference assumes
knowledge.

#### [16] Nooksack, WA snow extreme — 109.2 mm SWE — **B-**

> *Mf Nooksack, Washington: 109.2 mm of snow-water equivalent fell over 3 days — more
> than double the previous blizzard record of 50.8 mm. At 1,515 m on the wet side of
> the Cascades, this station sits where Pacific moisture stalls before the range blocks
> it from the interior.*

**Score:** 82 (threshold 76). Created 2026-05-18T03:27Z. **Post-F3 critic.**

Humor lens:
- **Violation:** 109.2 mm SWE, >2× the previous blizzard record. Real signal.
- **Benign?** Yes.
- **Setup→Punchline?** Second sentence: orographic geography ("Pacific moisture stalls
  before the range blocks it"). Mechanism explanation, not a punchline.
- **Named mechanic?** None. Ecosystem specificity (Cascades wet-side, orographic
  forcing).
- **Wodehouse rule?** Clean.

The 2× signal is strong. Voice spec met (specific location, SWE units, elevation, 3-day
window, prior record). Critic passed. Two deductions: (1) "Mf Nooksack" — the "Mf"
station prefix is a data artifact, not a place name; if the station is "Mt. Baker /
Nooksack" or similar, the tweet reads as a garbled name. (2) Second sentence explains
the geography without landing a punch. No timing-anomaly framing (May blizzard in the
Cascades — is this unusual for this date? The draft doesn't say). B- for meeting the
spec without a named mechanic or timing kicker.

#### [17] Stahl Peak, Montana snow extreme — 251.5 mm SWE — **B**

> *Stahl Peak, Montana: 251.5 mm of snow-water equivalent fell in 3 days — nearly five
> times the previous blizzard record of 50.8 mm. The northern Rockies funnel Pacific
> moisture through low passes; when a storm stalls, totals compound fast.*

**Score:** 82 (threshold 76). Created 2026-05-18T15:52Z. **Post-F3 critic.**

Humor lens:
- **Violation:** 251.5 mm SWE, ~5× the previous blizzard record. Very strong signal.
- **Benign?** Yes.
- **Setup→Punchline?** "when a storm stalls, totals compound fast" — causal chain with
  energy. Not a punchline, but more dynamic than pure geography.
- **Named mechanic?** None. Closest to an accelerating-rate framing ("totals compound
  fast").
- **Wodehouse rule?** Clean.

5× the previous blizzard record is the most extreme relative signal in the snow batch.
The second sentence is tighter than Draft [16]'s: "when a storm stalls, totals compound
fast" has a conditional mechanism that reads more energetically than static orographic
description. Critic passed. B for strong signal + functional second sentence; withheld
from B+ because "totals compound fast" is explanation of mechanics, not a voice punch.
No timing anomaly (May blizzard in northern Rockies — is this unusual?) left unexploited.

#### [18] Siberia fire — 601.1 MW — **B+**

> *601.1 MW of radiative heat detected in eastern Siberia today — very-high-intensity
> fire, satellite-confirmed at 95% confidence. At this latitude, snowmelt exposes dry
> litter fast; May fires here ignite before the understory has greened enough to resist.*

**Score:** 70 (threshold 64). Created 2026-05-18T18:06Z. **Post-F3 critic.**

Humor lens:
- **Violation:** 601.1 MW very-high-intensity Siberia fire. Strong signal (top tier by
  FRP intensity).
- **Benign?** Yes.
- **Setup→Punchline?** "May fires here ignite before the understory has greened enough
  to resist" — this is near-timing-incongruity. Spring greenery is racing against fire;
  the fire is winning. The "before" construction names the race and its outcome.
- **Named mechanic?** Near-timing-anomaly: fire outpacing spring greenup is specific and
  visual. Not a named comic mechanic in the traditional sense but the closest thing to a
  functioning punchline in the fire portion of this batch.
- **Wodehouse rule?** Clean. "601.1 MW" is exact, no approximation. "snowmelt exposes
  dry litter fast" is direct.

Best fire draft in the full pending queue. Three improvements over May 13 fire drafts:
(1) number-first opener ("601.1 MW") breaks the P6 formula; (2) "very-high-intensity
fire" uses the FRP tier; (3) second sentence establishes a timing race with some
consequential weight. "today" is baked in — stale at 3 days. Grading on voice quality
irrespective of staleness: B+. Would be A- if "today" were removed and "at this
latitude" were replaced with a named region.

**Staleness flag:** "today" baked in; created 2026-05-18, >48h old. Bulk-reject
candidate.

### Patterns named in this batch

1. **Coral bleaching template convergence (new failure mode).** Seven of eight coral
   drafts use an identical or near-identical sentence-1: "[Location]'s reefs have
   accumulated X.X°C-weeks of thermal stress — [threshold frame]" (or colon-lead
   variant). The F3 critic's system prompt explicitly names this pattern as a kill
   condition ("Six coral drafts opening [same structure] is the failure mode"). However,
   the May 15 coral batch pre-dates the critic's deployment; these drafts entered pending
   without critic review. Going forward, the critic should kill template-convergent coral
   drafts at the gate — but the writer needs variety guidance to produce
   non-convergent options for the critic to choose among. Direct analog to P6 (fire
   template convergence, shipped PR #85).

2. **A-rate ceiling confirmed at B+ without named humor mechanics.** The B-range drafts
   (8 of 14) meet the voice spec and pass the critic's bar; they have non-dead system
   clauses and no Wodehouse violations. But none deploy a named comic mechanic. The
   A-grade (Costa Rica) uses comparative framing + understatement closer. The B+ drafts
   (Galapagos, Siberia) approach this but don't complete the punch. P5's named-mechanics
   palette remains the theoretical lever to move from B to A.

3. **F3 critic is lifting the floor.** May 18 post-critic drafts (Costa Rica, Nooksack,
   Stahl Peak, Siberia) show a noticeably cleaner signal: no dead system clauses, no
   template convergence within the May 18 run, no effort signals. The critic is working
   as designed. May 15 pre-critic coral batch shows what the floor looks like without it
   (6 formula openers in one run, two below-threshold readings). The floor/ceiling
   framing: critic raises the floor; P5's named-mechanics guidance raises the ceiling.

4. **First A-grade from the two-bot pipeline (Costa Rica).** The mechanic: comparative
   framing (Galápagos contrast) + understatement closer ("nowhere to drain"). Three
   observations: (a) the comparison made the system clause load-bearing without being
   expository; (b) "nowhere to drain" is physically precise and dry — it names the
   consequence without editorializing; (c) the WORLD_KNOWLEDGE widening (PR #119)
   likely contributed — "lacks the cold upwelling that buffers the Galápagos" is exactly
   the class of geographic knowledge-claim that #119 unlocked.

5. **Snow extreme drafts pass the critic but plateau at B/B-.** Both snow drafts (Nooksack,
   Stahl Peak) passed the critic with clean voice and non-dead system clauses, but neither
   has a timing-anomaly kicker that would establish May as an unusual month for Cascades
   or northern Rockies blizzards. The signal magnitude (2× and 5× records) does the
   heavy lifting; the voice adds mechanism context without establishing incongruity.

6. **Wodehouse violations: zero observed.** P4 (Wodehouse rule, PR #85) continues to
   hold across three post-critic drafts and the pre-critic coral batch. No restate-padding,
   no explicit-gap math, no defensive justification, no poetry-attempt closers.

### Followups

1. Add coral bleaching variety guidance to writer_prompt.py — analogous to the P6
   fire-variety fix from PR #85. Four alternative sentence-1 forms for coral: lead with
   DHW number, lead with location's ecological role, lead with consequence (bleaching vs
   mortality distinction), lead with the buffer/upwelling system. The F3 critic kills
   template convergence at runtime, but the writer needs options to produce varied
   outputs for the critic to evaluate.
2. Watch for the Costa Rica A- mechanic to recur — next time a post-critic draft uses
   comparative framing + dry consequence closer, note whether 3+ A-grade drafts share
   the pattern (would justify promoting the mechanic in the writer prompt per P5
   evidence standard).
3. Staleness: bulk-reject Draft [6] (BC fire, "today" baked, 7 days old) and Draft [18]
   (Siberia fire, "today" baked, 3 days old). Gh CLI not available in this run; operator
   should reject via dashboard.
4. "Mf Nooksack" station name artifact — the "Mf" prefix should be stripped before the
   draft is approved. Not a voice-engine issue (source data artifact); dashboard reviewer
   should catch it.

### Numbers

- New drafts graded this cycle: 14 (1 monthly_low, 1 fire, 8 coral_bleaching, 2
  snow_extreme, 1 fire + 1 coral_bleaching post-critic)
- May 13 carryovers still pending: 4 (unchanged grades)
- Total pending queue: 18
- A-rate (new drafts): 7% (1/14)
- Grade distribution: 1 A / 8 B-range / 5 C-range / 0 D/F
- Stale bulk-reject: SKIPPED — gh CLI unavailable in this run; 2 candidates (Drafts 6,
  18) flagged for operator action. Token scope not determinable.
- First A-grade from two-bot pipeline: Draft [15] Costa Rica coral (A-)
- P4 (Wodehouse rule) violations: 0
- F3 critic confirmed passing: Drafts 15–18 (post-critic; all passed critic gate)
- New failure mode identified: coral_bleaching template convergence

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
