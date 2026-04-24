# Voice Failure Analysis — April 24 Draft Corpus

Analysis of the 35-draft pending queue on 2026-04-24 as a learning set
for the voice engine. Not ship-curation — each draft is a data point
about where Gemini falls into template traps under the current system
prompt.

## The corpus, graded

### 7 A/B grade (genuinely shippable)

- **#2 Sevilla record** — "when most people alive now were in elementary
  school." Era anchor lands because it triggers a *feeling* (my own
  grade-school memory) not a fact lookup.
- **#20 Jacobabad** — dual cultural anchor ("the year the euro entered
  circulation and the Winter Olympics were in Salt Lake City") on a
  Pakistan heat record. Two anchors is risky (can feel show-offy) but
  pays off here because both are widely recognizable.
- **#24 Ipoh** — "Two hottest Aprils in the 30-year archive: back to
  back." Accelerating-warming story in 11 words. Colon-then-restate is a
  voice move worth naming.
- **#30 Medan** — 1998 + "30 years of archives" is plain-honest. No
  gimmicks, no era anchor. Works because the fact is big enough.
- **#31 Chicago anomaly** — "That 29-degree jump used to define an
  entire season." *Used to define.* Past-tense framing of a normal
  anomaly as a new normal. Strongest framing move in the corpus.
- **#32 Kathmandu** — "The year the world worried about Y2K." From the
  voice exemplars. Reliable.
- **#35 Hawaii Big Island fire** — "In APRIL. The average rainfall there
  this month is 2.5 inches." Location-specific + seasonal twist. Rare
  example of a fire draft that works.

### Observation: what all A/B drafts share

1. **Specific named place** (Sevilla, Jacobabad, Ipoh, Medan, Chicago,
   Kathmandu, Hawaii) — not continents.
2. **Comparison anchor the reader already carries** — an era, a season,
   a personal memory, a widely-known event.
3. **Honest framing** — "30 years," "used to," explicit timeframes.
4. **No "powers N homes" formula** — record-type drafts sidestep this
   because records don't have MW values to compare.

## Template fatigue — where Gemini falls into ruts

### Rut 1: "Enough to power N homes"

Count across the corpus: 7 fire drafts use this comparison verbatim
or near-verbatim.

> *#8:* "enough to power 220,000 homes"
> *#11:* "enough to run 250,000 homes"
> *#12:* "enough to power roughly 200,000 homes"
> *#16:* "Enough to power 200,000 homes. Except it's burning them."
> *#17:* "enough to run roughly 100,000 American homes"
> *#18:* "enough to run roughly 150,000 average US homes"
> *#22:* "That is enough to power 100,000 homes. It is powering nothing."

Why it fails: the conversion (MW → homes) is arbitrary, feels
calculator-y, and produces the same sentence shape every time. Reader
retrieves no real scale because "250,000 homes" is still an abstraction.
By the 3rd use, Gemini is auto-filling with a different integer.

### Rut 2: "A coal/nuclear power plant runs at N MW. This fire is X of that."

Count: 8+ drafts.

> *#3, #4:* "A small power plant delivers about 300 MW. Except it's a forest."
> *#10:* "A typical coal power plant generates around 300 MW — to power a city."
> *#13:* "Seattle, the whole city, averages about 1,000 MW."
> *#14:* "A standard nuclear reactor runs at around 1,000 MW."
> *#15:* "The average nuclear reactor runs at about 1,000 MW."
> *#21:* "A coal power plant produces about 1,000 MW."
> *#27:* "A coal power plant produces around 150 MW."
> *#29:* "A coal power plant runs at about 1,000 MW. This fire is a third of a power plant. Made of trees."
> *#33:* "A large coal plant outputs around 1,000 MW."
> *#34:* "A typical coal plant runs at 600 MW."

Note the numbers drift: 150, 300, 600, 1,000. Gemini is picking whatever
makes the math favorable. Reader loses trust.

Seattle (#13) is the ONE instance where the comparison lands, because
"Seattle the whole city" is a concrete place-in-the-reader's-head.
Generic "power plant" isn't.

### Rut 3: "Somewhere in [continent]" / "Location unknown"

Count: 12 drafts.

> *#8, #10, #11, #12, #13, #14, #15, #16, #17, #18, #28, #33, #34*

All pre-geocoder-fix (landed today as `22cbc8e`). Gemini echoed the
weak prompt (`{region} = Asia, {country} = Unknown`) and produced
drafts that literally admit ignorance. Future drafts should get
specific region labels.

### Rut 4: "It has no name yet"

> *#1 Kazakhstan:* "The fire has no name yet."
> *#19 Mexico:* "It has no name yet."

Gemini is modeling named fires (Camp, Dixie) as the norm and flagging
unnamed ones as anomalous. They're not. Most fires never get named.
This closer implies a missing story beat that isn't there.

### Rut 5: "It is powering nothing" / "Loose in a field" / "Made of trees"

> *#15:* "loose in a field"
> *#16:* "Except it's burning them"
> *#22:* "It is powering nothing"
> *#28:* "No structure. No city. Just a forest."
> *#29:* "Made of trees"

All attempts to subvert the power-plant comparison. #29 ("Made of
trees") lands because it's short and concrete. The others are
rhetorical filler ("it is powering nothing") or broken syntax
("except it's burning them" — them? the homes it's hypothetically
powering? The reader has to do too much work).

## What the fire drafts need

Drawing from the 7 A/B examples + identifying failures:

1. **Specific location in the first 5 words.** Not "A wildfire burning
   in Africa." Try "Angola's Benguela Province has…" or "The Congo
   Basin just…" Today's geocoder fix makes this possible. The
   generator prompt now needs to *require* the region name in the
   opener, not allow Gemini to bury it.

2. **Kill the home-count comparison.** It's stale. Replace with
   concrete landscape/seasonal anchors:
   - *"A fire big enough to show up on satellite from 705 km away"*
   - *"A fire the size of [named recognizable landmark]"*
   - *"April. Fire season here ended in October."*

3. **Kill the "power plant" comparison unless the reader can visualize
   it.** Seattle works because Seattle is a city. "A coal power plant"
   is an abstraction. If we keep the power-plant move, pin it to a
   named plant or a recognizable metro.

4. **Ban "no name yet" closer.** Implies missing story beat.

5. **FRP floor raised** (done this pass: 100 → 250 MW). Below that, the
   numbers are too small to carry a tweet.

## What the record drafts do right

All 6 record-type A/B drafts (Sevilla, Jacobabad, Ipoh, Medan, Chicago,
Kathmandu) follow the pattern:

**[Named city] [forecast/actual number]F. [Honest framing with
year/timeframe]. [Anchor or closer].**

The framing is the story. The number is proof, not the lead.

The fire drafts break this because fires don't have a "record" in the
same way. A fire is just a fire. So Gemini reaches for MW-based
comparisons and falls into the template traps above.

This is the real voice-engine problem: **fires need a different voice
recipe than records.** The current single system prompt doesn't
distinguish.

## Concrete intervention sketch (for the voice-engine lane)

The simplest cut is per-signal-type prompt specialization — already
parked in `docs/IDEAS.md` → "Voice engine upgrade." Drawing from this
corpus, a first pass might look like:

### Fire-specific prompt additions

```
- LEAD with the named region/country in the first 5 words.
  "Angola's Benguela Province" not "A wildfire in Africa."
- DO NOT compare fire intensity to "homes powered" — it's stale.
- DO NOT compare to "a coal power plant" in generic terms. If you
  compare to a plant, name it ("larger than the Palo Verde reactor").
- DO NOT write "The fire has no name yet." Most fires never get
  named. This closer implies a story beat that isn't there.
- DO use seasonal anchors ("The continent's fire season normally
  begins in November").
- DO use landscape scale ("larger than the Big Sur fire of 2020").
```

### Record-specific prompt additions

```
- Historical-human anchors are your strongest move ("the year the
  euro entered circulation"). Weave them through whenever the record
  is 10+ years old.
- Past-tense framing of current normal ("used to define a season")
  is underused and powerful — propose it in the candidate set.
- When a record is broken by a thin margin (<1.0°C or <2°F), the
  "back-to-back" / accelerating framing lands better than a delta.
```

### Universal additions

```
- First 5-7 words are the whole tweet. No throat-clearing
  ("Satellite just picked up…") in the opener.
- One idea per tweet. The corpus shows Gemini stacking 3 comparisons
  when one would land — kill the second and third.
```

## Status going in to next session

- FIRMS `frp_min` raised 100 → 250 MW (this session's code change).
- Geocoder now specific (shipped `22cbc8e` earlier today).
- The 35 drafts preserved for learning. Voice engine upgrade is the
  next real lift.
