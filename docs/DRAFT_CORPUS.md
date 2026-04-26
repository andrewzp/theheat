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

#### #3 Australia fire — signal 68 / copy 82 — **B (ship this one)**

> 333 MW of fire detected in Australia. A small power plant delivers
> about 300 MW. Except it's a forest.

"Except it's a forest" is the best single closer in the fire vocabulary
in this corpus.

#### #4 Australia fire — signal 67 / copy 84 — **C (reject; near-dup of #3)**

> Satellite just picked up a 307 MW fire in Australia. For reference,
> a small power plant is about 300 MW. Except it's a forest.

Same structure, same closer, weaker verb choice ("Satellite just picked
up" buries the number).

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
