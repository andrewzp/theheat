# @theheat — Exemplar Library

The hall of fame. This is what we're reaching for — not "competent bot copy," not "informative," not "on-brand." **Genuinely shareable. Screenshottable. The kind of tweet you'd text to a friend at midnight.**

If a candidate tweet from the generator doesn't belong in this file, it probably shouldn't ship.

## How This File Is Used

At generation time, the pipeline picks 5 exemplars — one from each frame below — and feeds them into the system prompt as few-shot examples. The exemplars shown match the signal type and category.

When a posted tweet scores 9+ in human rating, it gets promoted into this library automatically (see `dashboard/` rating system — to be built).

## The Five Frames

Every viral @theheat tweet sits in exactly one of these intents. The generator produces one candidate per frame, then the evaluator ranks across frames.

1. **ERA ANCHOR** — "Last time this happened, [human-historical moment]." Anchor the number to an era the reader can feel in their body.
2. **ABSURDITY** — Place + number + deadpan tag. The incongruity IS the joke.
3. **SOCIAL CURRENCY** — A fact you'd repeat at dinner. The reader shares to look informed.
4. **REPLY BAIT** — Imply the conclusion. Leave a gap the reader fills in with their own take.
5. **COMEDIC TURN** — A dry punchline closes the tweet. Max 6 words.

Each frame below has 4-6 exemplars with annotation of the mechanic.

---

## FRAME 1: ERA ANCHOR

*The sharer looks cultured, not just informed. The reader feels the timespan in their bones.*

### Exemplar 1.1
> Buenos Aires just hit 42.1C. Last time it was this hot there, the Great Depression hadn't started yet.

**Why it works:** Anchors 1929 to an era people can mentally occupy. The reader does the math: "wait, that long?" and the awe lands.

### Exemplar 1.2
> CO2 at Mauna Loa: 436 ppm. Pre-industrial was 280. The atmosphere had not been this CO2-rich since before modern humans evolved.

**Why it works:** Two anchors in one tweet — pre-industrial as the chemistry reference, pre-human as the scale reference. Social currency on tap.

### Exemplar 1.3
> Delhi just broke its April 17 record. The old record had stood longer than TikTok has existed.

**Why it works:** Internet-native timeframe. "Longer than TikTok" is both precise (the reader knows TikTok is ~7 years old) and cheeky. Updates an old record's era without saying a year.

### Exemplar 1.4
> A temperature record from 1929 fell in São Paulo yesterday. That record had outlasted fifteen presidents.

**Why it works:** "Fifteen presidents" translates 97 years into something viscerally long without requiring math. Specific number, not "many."

### Exemplar 1.5
> The Mississippi at Baton Rouge is 12ft above flood stage. The last river reading this high, Elvis had just signed with Sun Records.

**Why it works:** Unexpected cultural anchor (Elvis, 1954). The juxtaposition of a 1950s icon with a 2026 climate reading is the surprise.

### Exemplar 1.6
> Tokyo hit 41.8C. The last time Tokyo was this hot, the Berlin Wall was still standing.

**Why it works:** "Berlin Wall standing" = 1989 = 37 years ago. Geopolitically anchored, universally recognized, and the emotional distance of the fall of the Wall makes it feel longer ago than the number suggests.

---

## FRAME 2: ABSURDITY

*Place + number + deadpan tag. The incongruity IS the joke.*

### Exemplar 2.1
> Anchorage recorded 82F today. The average for this date is 57F. Anchorage.

**Why it works:** The one-word restatement is the entire punchline. Period-for-comedic-timing. This is a legitimate all-timer in the voice.

### Exemplar 2.2
> It's 54F in Tromsø. That's six degrees above the all-time April record. 200 miles north of the Arctic Circle.

**Why it works:** Three escalating specificities: the temp, the margin, the location. Each line makes the previous one land harder. Ends on the deadpan fact, not a comment on it.

### Exemplar 2.3
> Siberia is 91F today. Siberia.

**Why it works:** Two words as the whole second sentence. Pure confidence in the reader. No explanation. The repetition is the shock.

### Exemplar 2.4
> Kuwait City hit 53.2C. In May.

**Why it works:** Two beats. No editorializing. The "in May" is the knife.

### Exemplar 2.5
> Houston just went under a flash flood emergency. Houston went under literally.

**Why it works:** Double meaning bridges the gap between the alert and the city's geography. Reads like a joke but is also a fact. The reader laughs then realizes they're not supposed to.

### Exemplar 2.6
> A tornado is on the ground in Orlando. In January. Radar-confirmed.

**Why it works:** Three-word sentence structure amplifies each beat. Orlando (wrong place). January (wrong time). Radar-confirmed (this is real). Unadorned.

---

## FRAME 3: SOCIAL CURRENCY

*A fact you'd repeat at dinner. Sharer looks informed, not preachy.*

### Exemplar 3.1
> Phoenix has broken a daily heat record every April 16 for the last four years running.

**Why it works:** The fact is self-contained and quotable. "Every year for four years" is a pattern the reader can retell exactly without looking it up.

### Exemplar 3.2
> Last year, Earth added more CO2 to its atmosphere than in any previous year on record. The year before held the same title.

**Why it works:** The second sentence turns the first into a pattern. Reader thinks "oh, so every year is the new worst year." They'll tell someone this.

### Exemplar 3.3
> The ocean is 3F warmer than it was when Finding Nemo came out. Just the ocean.

**Why it works:** Cultural anchor (2003, universally known film). "Just the ocean" is the understated closer that implies the scale. Peak dinner-party fact.

### Exemplar 3.4
> More heat records were broken in Europe last week than in the entire decade of the 1990s.

**Why it works:** Comparative fact that reframes "a lot" as a specific, shocking proportion. The reader can't un-hear this.

### Exemplar 3.5
> Arctic sea ice is 18% smaller than the 1981-2010 average. That missing ice would cover half of Europe.

**Why it works:** The second sentence makes the abstract percentage physically present. "Cover half of Europe" is a mental picture.

### Exemplar 3.6
> Earth has recorded above-average global temperatures for 14 consecutive months. Fourteen. Straight. Months.

**Why it works:** The period-separated restatement converts a number into a drumbeat. Retelling the tweet preserves the rhythm.

---

## FRAME 4: REPLY BAIT

*Imply the conclusion. Leave a gap the reader fills with their own take.*

### Exemplar 4.1
> Phoenix just hit 121F. NEW RECORD. The old one was from last year.

**Why it works:** Says nothing about climate. But the reader thinks "climate change" before finishing the third sentence. They quote-tweet to complete the thought.

### Exemplar 4.2
> Record high in Warsaw. Record high in Berlin. Record high in Prague. All on the same day.

**Why it works:** Four sentences, zero analysis. The pattern is obvious, the reader wants to point at it, and every reply completes the implicit argument.

### Exemplar 4.3
> São Paulo broke its April record today. That record was set in April 2024.

**Why it works:** Two sentences. The reader does the arithmetic: the record lasted one year. Replies will say "accelerating" so the account doesn't have to.

### Exemplar 4.4
> Mauna Loa: 437 ppm. Pre-industrial: 280 ppm. Human civilization emerged at 280.

**Why it works:** Three facts, no conclusion. The implication ("we have left the conditions civilization evolved in") is too heavy to state. The reader states it instead.

### Exemplar 4.5
> Every record Phoenix broke this decade has fallen again since.

**Why it works:** A single-sentence tweet that's a recursive statement about records. The reader finishes the thought — "so nothing we call a record stays a record" — which is the whole point.

### Exemplar 4.6
> The hottest year on record is 2024. The second hottest is 2023. The third hottest is 2022.

**Why it works:** Pure list. No editorializing. The descending sequence IS the argument. Replies will complete the pattern to 2021, 2020, etc.

---

## FRAME 5: COMEDIC TURN

*One dry punchline, max 6 words, closes the tweet. Rare and surgical — overuse kills the voice.*

### Exemplar 5.1
> New wildfire in Northern California. High confidence. 0% contained. **It's April.**

**Why it works:** Two-word closer. Contextualizes everything above. Turns a fire report into an unspoken statement about fire seasons getting longer.

### Exemplar 5.2
> Satellite picked up a 1,200 MW fire in Siberia. A large power plant is about 1,000 MW. **Except it's a forest.**

**Why it works:** Three-word reversal. Reframes a scale comparison into something visceral. The reader was building a mental image of a power plant; "except it's a forest" replaces that with a physical horror.

### Exemplar 5.3
> Water level at Charleston is 2ft above where it should be. **Nobody issued a warning.**

**Why it works:** The closer is a policy observation wrapped as a comedic beat. Reader interprets it as "the system isn't keeping up," which the tweet never says.

### Exemplar 5.4
> Mississippi at Baton Rouge: 42.3ft. Flood stage: 35ft. **The river doesn't care what month it is.**

**Why it works:** Closing sentence personifies the river in a way that lands as both funny and ominous. Six words, high resonance.

### Exemplar 5.5
> CO2 crossed 433 ppm at Mauna Loa. We added 2.4 ppm in a year. **That used to take a decade.**

**Why it works:** The closer is a compression of decades of climate history into six words. Screenshot bait.

### Exemplar 5.6
> No records broken today. No new fires. CO2 held at 433.18. **Honestly suspicious.**

**Why it works:** The comedic turn on a quiet day. Voice keeps the account alive on days with no extreme data. Establishes that normalcy itself is now strange.

---

## ANTI-PATTERNS (Never ship these)

Each of these failed as a draft. They're here to illustrate the failure modes the generator should never produce.

### ❌ Press-release opener
> **NWS issued a Severe Thunderstorm Warning for Buchanan, MO.** Today is April 10.

**Why it fails:** Opens with the agency name (nobody cares). Ends with a date that adds nothing. Zero voice.

### ❌ Weather-service boilerplate
> Saipan: Extreme Wind Warning. **These are HURRICANE-FORCE conditions.**

**Why it fails:** "HURRICANE-FORCE" is the meteorological category, not a fact the reader can feel. The tweet tells the reader to be scared instead of showing them why.

### ❌ Jargon + tier explainer
> Tropical Cyclone SINLAKU-26. Guam is under a **RED alert**. **This is the highest severity level GDACS issues.**

**Why it fails:** "SINLAKU-26" is bureaucratic noise. Explaining what RED means to the reader is condescending. The agency name (GDACS) should never appear.

### ❌ Label:value format
> Flash Flood Warning for Kauai, HI. **Severity: Severe.** Not a light shower. April 10, 2026.

**Why it fails:** "Severity: Severe" is press-release syntax. "Not a light shower" is defensive. Date twice (the Twitter timestamp already does this job).

### ❌ Pure information, no frame
> **CO2 is at 435 ppm at Mauna Loa this week.**

**Why it fails:** A number without a comparison, without a reaction, without a reason to share. Accurate but mute.

### ❌ Meta-commentary ("telling not showing")
> Tropical Cyclone SINLAKU-26 is now a GDACS Red alert. 178 mph winds. Globally, you might see five of these a year. **THIS ONE IS SERIOUS.**

**Why it fails:** "THIS ONE IS SERIOUS" is the reader's conclusion, not ours to state. The numbers should make them say that themselves. Telling > showing.

### ❌ Truncated numbers (data quality error)
> **1F forecast for Singapore today.** The old record was 88.3F.

**Why it fails:** Generator truncation bug. A single-digit Fahrenheit reading is physically impossible for Singapore. Safety pipeline should (and now does) reject this.

---

## Notes on Use

**Exemplar selection at generation time:**
- For each generation event, pick one exemplar from each of the 5 frames
- Prefer exemplars that match the event category (record, fire, CO2, etc.)
- If no category match, fall back to the universal ones

**Growth strategy:**
- Every tweet Andrew rates 9+ gets promoted automatically
- Every tweet rated ≤5 goes to anti-patterns
- Reviewed quarterly, pruned to keep ~40 total (balance recency with timeless exemplars)

**What counts as "genuinely shareable":**
- Makes the sharer look informed or cultured (not preachy)
- Surprise in the first 5-7 words
- Ends on a punch, not a reservation
- Can be screenshot and understood without context
- A smart friend you text it to responds with "wait, what"

**What does NOT qualify:**
- Anything that requires reading twice to get
- Anything that explains what an alert tier means
- Anything with "experts warn" or "according to"
- Anything that preaches
- Anything that could run as-is on a local news chyron

---

*Compiled April 17, 2026. Living document. Grows as we learn what actually works.*
