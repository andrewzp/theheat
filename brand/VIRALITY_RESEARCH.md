# The Science of Viral Content — Research Reference

A deep dive on what the academic and industry research actually says about why content goes viral, documented for @theheat editorial reference. Compiled April 2026.

**Use this when:**
- Editing the generator system prompt
- Updating the evaluator scoring dimensions
- Debating whether a specific draft is viral or just informational
- Writing new voice rules

---

## Executive Diagnosis for @theheat

The bot's default output is informational/weather-report content. Peer-reviewed research is unambiguous: **informational content triggers low-arousal cognitive processing, which is the single most reliable predictor of NON-sharing.** The fix is not "more emotion" — it's engineering content that specifically activates high-arousal states (awe, anger, anxiety) while satisfying social currency needs.

**Sadness is the default emotional response to climate data. Sadness is specifically named in peer-reviewed research as the emotion that suppresses sharing.**

---

## 1. Berger & Milkman 2012 — "What Makes Online Content Viral?"

*Journal of Marketing Research* 49(2): 192–205. The foundational empirical paper in the field.

**Study:** Analyzed ~7,000 NYT articles over 3 months, tracking which hit the "most emailed" list. Controlled for author fame, timing, day of week, length, complexity, section, prominence.

**Findings:**
- **Positive content is more viral than negative content** (all else equal, ~13% bump).
- **But arousal trumps valence.** The mechanism is physiological activation, not positivity.
- **High-arousal positive emotion (awe) → more viral.** A one SD increase in awe-evoking-ness raised probability of hitting "most emailed" by ~30%.
- **High-arousal negative emotions (anger, anxiety) → more viral.**
- **Low-arousal emotion (sadness, contentment) → LESS viral, even if valenced.**
- Practically useful, surprising, and interesting content are also independently more viral.

---

## 2. Berger 2011 — "Arousal Increases Social Transmission of Information"

*Psychological Science* 22(7): 891–893.

**The jogging experiment:** 40 undergrads. Group A sat still 60 seconds. Group B jogged in place. Both then read a neutral news article. **Joggers forwarded the article significantly more.**

**Implication:** Arousal is sufficient by itself to increase sharing — it doesn't need to be "about" the content. **Our job is to activate readers, not just to report facts.**

(2024 replication by Tian et al. had mixed results in modern social media contexts, so effect size may be smaller today, but the core mechanism is well-supported.)

---

## 3. STEPPS Framework (Berger 2013, *Contagious*)

Six drivers of word-of-mouth transmission:

- **S — Social Currency:** People share what makes them look smart/cool/in-the-know. Most neglected lever.
- **T — Triggers:** Environmental cues that prompt recall. Heat waves trigger climate thoughts.
- **E — Emotion:** High-arousal only. "When we care, we share." Low-arousal = no care.
- **P — Public:** Things that are visible spread. Easily quotable, screenshot-able.
- **P — Practical Value:** Useful content spreads because sharing signals care for the recipient.
- **S — Stories:** Narratives are Trojan horses for information.

---

## 4. Emotional Drivers: Which Emotions Drive vs Kill Sharing

### DRIVERS (high-arousal)
| Emotion | Notes |
|---|---|
| **Awe** | Most powerful. Self-transcendent. Makes people feel small in a good way. Scale-shock. Associated with expanded perspective, prosocial behavior. |
| **Anger** | Highly viral. Yuan et al. 2024 found aggressive climate messaging drives more retweets (at some cost to perceived credibility). Anger > anxiety on retweet cascade depth. |
| **Anxiety** | Viral, but elicits avoidance long-term (climate fatigue). |
| **Amusement/hilarity** | High-arousal positive; extremely shareable. |
| **Excitement** | Signals novelty. |
| **Surprise** | Doesn't work alone but amplifies whatever emotion is attached. |

### KILLERS (low-arousal)
| Emotion | Notes |
|---|---|
| **Sadness** | Explicitly suppresses sharing (Berger & Milkman). Triggers withdrawal. Most climate content defaults here. |
| **Contentment** | No one shares a tweet that makes them feel warm and cozy about climate. |
| **Boredom/neutrality** | What "weather report" voice produces. |
| **Helplessness** | Low-arousal AND actively demotivating. |

**Chen et al. 2023 (Communication Monographs):** On Twitter specifically, **anger > anxiety** on every measure of retweet cascade. Anger creates deeper chains because it mobilizes moral outrage and group identity.

---

## 5. Karen Nelson-Field — *Viral Marketing: The Science of Sharing* (2013)

Ehrenberg-Bass Institute. ~1,000 videos, 9 studies, 5 datasets, 2+ years. Most rigorous video-virality study ever done.

**Key findings:**
- **High-arousal positive content shared ~70% more** than the next-highest category. Awe > anger in absolute sharing rates.
- Arousal matters more than valence (same as Berger & Milkman).
- **"Getting big is largely about getting seen."** Virality is overwhelmingly a function of reach/distribution. Creative quality is secondary. Implication: fight for one genuinely great tweet per week, not daily mediocrity.
- Brand prominence doesn't hurt sharing (contra popular belief).
- Brand linkage (viewers remembering the brand) is typically <25% even for viral videos. **Being clearly "@theheat" in voice throughout every post is free performance.**

---

## 6. Loewenstein 1994 — The Information Gap Theory of Curiosity

*Psychological Bulletin* 116(1): 75–98.

**Core thesis:** Curiosity is an aversive deprivation state — *like hunger for information*. People are motivated to close the gap.

**The inverted-U (confirmed by Kang et al. 2009):**
- Know nothing → **no curiosity** (no gap perceived).
- Know a little → **peak curiosity** (sweet spot).
- Know almost everything → **low curiosity** (gap too small).

**For @theheat:**
- Headlines must imply the reader is one piece of information away from knowing something.
- **"Temperature in Texas hit 110°F today" contains the full answer. Nothing pulls the reader forward.**
- "A country just hit its hottest temperature ever." creates a gap (which country? how hot?).

**Upworthy caveat (important):** Curiosity-gap headlines worked 2012–2015 but have partially decayed through overuse. Both *Nature's Scientific Reports* (2024) and Upworthy itself find descriptive headlines now outperform pure teasers. **The gap still works, but it needs to be filled by something specific and concrete, not "you won't believe what happened next."**

---

## 7. Fractl / HBR — The Valence-Arousal-Dominance Model

*Harvard Business Review*, May 2016. 65,000 articles analyzed.

**Three-dimensional emotional model:**
1. **Valence** — positive/negative.
2. **Arousal** — activation level.
3. **Dominance** — feeling of being in control (new dimension Berger & Milkman didn't include).

**Critical finding:** Shares and comments are driven by DIFFERENT emotional combinations.

- **Shares are driven by HIGH-dominance emotions.** Admiration, feeling "right" or "empowered." When readers feel *in control* of the emotion, they share. People share to signal their perspective.
- **Comments are driven by HIGH-arousal + LOW-dominance.** Anger + fear (feeling out of control + activated) generates debate in comments.

**For @theheat:**
- Likes/retweets = share behaviors → use **high-dominance framing** (reader feels knowledgeable, in control).
- Replies = comment behaviors → use low-dominance framing (reader feels threatened, uncertain).
- Tweet that makes reader feel "I need to tell people about this" (high arousal + high dominance) beats "the world is ending" (high arousal + low dominance) on shareability.
- **First builds audience; second farms replies and rage-quits.**

---

## 8. Heath & Heath — *Made to Stick* (SUCCESs)

Six principles for sticky ideas:

| Principle | Application |
|---|---|
| **Simple** | Core message stripped to essentials. JFK's "man on moon, back safely, in a decade" — three constraints, each testable. |
| **Unexpected** | Violate schemas. CSPI popcorn: medium buttered = 37g saturated fat, more than a full Big Mac + steak dinner combined. Violated expectation drove behavior change. |
| **Concrete** | Sensory detail. Not "a lot of money" but "five bags of groceries." |
| **Credible** | Anti-authorities beat authorities. Vivid detail > statistics. |
| **Emotional** | The Rokia study. |
| **Stories** | Narrative as Trojan horse. |

### The Rokia Study (Small, Loewenstein & Slovic 2007)
*Organizational Behavior and Human Decision Processes* 102(2): 143–153.

Subjects shown:
- (a) Rokia's story (7-year-old girl in Mali, named, photographed)
- (b) Statistical data ("more than 11 million people face hunger")
- (c) Both combined

**Results:**
- Rokia alone got **~2x the donations** of statistics alone.
- **Rokia + statistics got LESS than Rokia alone** — adding numbers suppressed emotional activation.
- Priming analytical thinking (doing math first) REDUCED donations to identifiable victims.

**"If I look at the mass, I will never act. If I look at the one, I will."** (Mother Teresa, famously attributed.)

**For @theheat:** Climate data IS "the mass." "3 million lbs of plastic" is statistics worst-case. Fix: lead with the single identifiable thing.

---

## 9. Twitter/X-Specific Research

**Core 2024–2026 benchmarks:**
- **Median engagement rate:** ~0.035%. A 1% rate beats 95% of the platform.
- **71–100 characters generate ~17% more engagement** than shorter tweets.
- **Images: +150% retweets.** Video: **6x engagement** of text.
- **First 5–7 words are decisive.** Users scroll past in ~1.5 seconds.
- **Hashtags:** 1–2 optimal. 3+ actively suppresses engagement.
- **Threads:** 5–10 tweets sweet spot. ~63% more impressions than single posts.
- **Questions drive replies** but not necessarily retweets (Fractl dominance effect).
- **Bookmarks** are the purest value signal — no social signaling.

### Vosoughi, Roy, Aral 2018 — *Science* 359: 1146–1151
"The Spread of True and False News Online"

- 126,000 stories, 3M people, 4.5M tweets, 2006–2017.
- **False news is 70% more likely to be retweeted than true news.**
- **True stories take ~6x longer to reach 1,500 people than false stories.**
- **Top 1% of false cascades reached 1,000–100,000 people; true stories rarely exceed 1,000.**
- **Why?** False news is more novel. Replies to false news carried more surprise and disgust; replies to true news more sadness, anticipation, trust.
- **Novelty is the master variable of diffusion.**
- Humans, not bots, drive this. Bots amplify true and false equally.

**For @theheat:** We cannot compete with falsehood's novelty advantage through accuracy alone. Must *engineer novelty* within true content — overlooked angles, new records, comparisons never made before.

---

## 10. Reply-Bait / Engagement Farming

Not a formal academic field but well-documented pattern.

**Structure of high-reply tweets:**
- Open-ended questions ("Name a movie that…")
- Inflammatory takes designed for quote-tweet outrage
- Identity-group A vs identity-group B pitting
- "Unpopular opinion:" followed by popular or inflammatory opinion
- Deliberately low-resolution bad takes — forces readers to correct
- Phrases: "Let that sink in," "a thread 🧵", "nobody is talking about"

**Academic grounding:** *Journal of Politics* study found **anger (more than anxiety) drives information-seeking and click-through**. Rage posts get shared AND drive users into comments. X monetizes ads in reply threads — the platform rewards this.

**For @theheat (productive cousin of rage-bait):** **Leave a curiosity gap readers want to close with their own knowledge/opinion.** A surprising climate fact without explanation creates the "wait, how?" moment that triggers replies/quotes/shares.

---

## 11. Social Currency — Why People Share to Signal

**Signaling theory (Spence 1973):** Every share is a costly signal attaching the sharer's identity to the content.

**Findings:**
- **Insider information** has the highest social currency. Content that implies "I have seen this before you did" is maximally shareable.
- **Making people feel smart** is a primary sharing driver — the reader is not sharing the content, they're sharing the fact that they understood the content.
- **Exclusivity** boosts sharing even for unremarkable content.
- **Tribal alignment** — content that lets the sharer reaffirm group identity.

**Engineering social currency for @theheat:**
- Lead with what the reader won't have seen ("this chart hasn't been shared yet")
- Let the reader play expert ("you can see this right now in X location")
- Provide an observation, not a lecture
- Avoid obvious statements ("climate change is bad"); reward attentive readers with NEW information
- **Specificity signals expertise.** "Tuesday was the hottest June 9 in 127 years of records for Phoenix" > "record heat in Phoenix."

---

## 12. Data & Statistics Going Viral

### Tversky & Kahneman 1974 — Anchoring
*Science* 185: 1124–1131.

**Wheel of Fortune experiment:** Subjects spun wheel (10 or 65), then estimated % of African nations in the UN. Anchored on 10 → answered ~25%. Anchored on 65 → answered ~45%. **Arbitrary numbers shift judgment by ~20 percentage points.**

**Multiplication experiment:** 1×2×3×4×5×6×7×8 got median estimate of 512. 8×7×6×5×4×3×2×1 got 2,250. **Same operation, 4x difference in perceived magnitude.**

**For @theheat:** The first number you drop in a tweet becomes the anchor. Lead with the biggest/most extreme numerical anchor.

### The concreteness principle (Paivio, dual-coding theory)

**Abstract numbers fail:** "3 million lbs of plastic" fails because millions of pounds is abstract, the magnitude isn't anchored, there's no image, no pathos.

**Concrete comparisons succeed:** "Equivalent to a blue whale every hour" succeeds because:
- Blue whale = concrete visual.
- "Every hour" = temporal concreteness, forces imagined duration.
- Rate framing triggers continued accumulation (not a one-off).
- Compares to something emotional (whales = majesty).
- Arithmetic: reader multiplies in their head, creating a participation moment.

**Heath rule:** Don't use a number. Use a comparison that makes the number mean something.

**For @theheat specifically — historical-human comparisons win over physical metaphors:**
- "Last time it was this hot in Buenos Aires, the Great Depression hadn't started yet" beats "hotter than a blue whale's body temperature"
- Historical records give the reader social currency (they feel cultured, not just informed)
- The physical metaphor feels like a science-museum placard
- The human era makes it viscerally feel-able without being cute

---

## 13. Surprise, Novelty, and Expectation Violation

**Finding:** Novelty increases virality because it violates schema-driven processing, forces "stop and think," and earns social currency. Vosoughi et al. 2018 confirms novelty as the mechanism of viral diffusion.

**But — optimal, not maximal, surprise.** Shang et al. 2022 (COVID-misinformation study) found novelty increased sharing intention through surprise, but simultaneously decreased credibility and positive emotion, pulling sharing back down.

**Sweet spot:** surprise that feels earned — "I didn't know that but now I do, and it fits what I already suspected."

**Template:** "Everyone thinks [common belief]. Actually [surprising truth]."

---

## 14. The Pratfall Effect (Aronson, Willerman & Floyd 1966)

**Study:** 48 male undergrads listened to recording of confederate answering quiz questions. Confederate was either highly competent (92%) or mediocre (30%). Then confederate either spilled coffee or didn't.

**Findings:**
- Competent + pratfall → **most liked.**
- Competent + no pratfall → less liked than competent + pratfall.
- Mediocre + pratfall → **least liked.**

**Mechanism:** High-competence targets seem superhuman; a small mistake humanizes them. Low-competence targets are already dismissed.

**For @theheat:** Must establish competence FIRST (consistent accuracy, crisp data, tight voice). ONCE competence is established, occasional self-aware imperfection increases likability. But a bot starting sloppy doesn't get the pratfall bonus — it just seems sloppy.

---

## 15. Climate-Specific Communication Research

### Pew Research 2021
- **45% of Gen Z and 40% of Millennials** interact with climate content monthly vs. 27% of Boomers.
- **32% of Gen Z** have taken climate action vs. 21% of Boomers.
- **Gen Z is the core sharing audience** for climate content.

### Gen Z emotional profile (Penn, Yale E360)
- 40–70% report dread/sadness about climate.
- Fear and helplessness widespread.
- **Determination (not anger) is the strongest predictor of Gen Z climate action.** Approach-oriented emotions > avoidance-oriented emotions.

### Key findings
- **>80% of climate news uses disaster/doom frame** (Oxford Institute of Journalism).
- **3 consecutive days of doom exposure produces more fear, less hope, MORE disengagement.** Climate fatigue is empirically real.
- **Hope is the single most consistent predictor** of political engagement, policy support, and conservation behavior.
- Solutions journalism increases positive affect and decreases negative affect WITHOUT sacrificing urgency.
- Ettinger et al. 2021 (*Climatic Change*): hope and doom frames both generated engagement, but hope frames produced higher sustained behavior change.
- **Crisis framing wins initial sharing. Opportunity framing wins sustained engagement and memory.**
- Falkenberg et al. 2022 (*Nature Climate Change*): climate contrarian content grew **16x in retweet engagement 2015–2021** vs. **4x for pro-climate content.**
- Visual content dramatically outperforms text on climate (Wang et al. 2022, *Climate Policy*).

**For @theheat:** Pure doom is underperforming. Audience exists and is Gen Z-weighted. Playbook that works: **awe + anger at specific actors + occasional wins/solutions, anchored in concrete local or human detail, with novelty.** Sadness should be rare; when used, pair with high-arousal emotion.

---

## 16. Anti-Patterns — What KILLS Virality

### Fatal patterns for @theheat

1. **Weather-report voice** — "Temperatures in the Southwest reached…". No arousal. No narrator.
2. **Label:value syntax** — "Phoenix: 118°F. Record: 122°F (2017)." Data-dump triggers analytical/cognitive mode, which **kills emotional activation** (Small-Loewenstein-Slovic sympathy-callousness effect).
3. **Hedges** — "according to," "experts warn," "a new study shows." Drains urgency.
4. **Date repetition** — "Yesterday, 7/14, Tuesday, July 14, 2024…" wastes character count.
5. **Closing the curiosity gap immediately** — giving the full answer in the same breath as the question.
6. **Explaining what things mean** — if you explain why something matters, you've converted the reader from discoverer to student. Students don't share.
7. **Tier explainers** — "Category 4 means winds over 130 mph." Once you're explaining definitions, social-currency-by-expertise is gone.
8. **Sadness without anger or awe** — Berger & Milkman's documented sharing killer.
9. **Preachy tone / moralizing** — robs the reader of the opportunity to react themselves.
10. **Abstract statistics without anchor** — "3 million lbs of plastic."
11. **Zero stance** — pure-neutral reporting triggers no dominance emotion.
12. **Too-familiar facts** — violates Loewenstein's inverted-U. If the reader could write this tweet, they have nothing to gain by sharing it.
13. **Over-hashtagging** (>2 tags) — empirically suppresses engagement.
14. **Buried lede** — the first 5–7 words are everything on X.
15. **Meta-commentary** — "THIS IS SERIOUS," "HURRICANE-FORCE," "EXTREME force," "catastrophic," "life-threatening," "dangerous conditions." Tell-don't-show failure.

---

## 17. Integrated Playbook for @theheat

### 1. Optimize for arousal, not accuracy
Accuracy is the floor, not the ceiling. Every tweet must pass: **"what physical state does this trigger in the reader?"** If answer is "mild sadness" or "neutral informed," kill it.

### 2. The four-emotion shortlist
Lead with **awe, anger, anxiety, or amusement**. Everything else is a ceiling on reach. Awe + specificity (scale-shock) is the bonus track.

### 3. The anchor rule
First 5–7 words carry the whole tweet. A number. A shocking verb. A specific place. Never "Today," "Yesterday," "Recently," "According to."

### 4. Concrete > abstract, always
"A blue whale every hour" > "3 million pounds per hour." "Hotter than any day your grandparents lived through" > "record-breaking."

### 5. Leave the gap open
State the shocking fact. Don't explain the mechanism. Don't interpret. Let the reader fill it in with their own outrage/awe.

### 6. Identifiable > statistical
One farmer in one county. One glacier. One bird. One day. Then the context. NOT the aggregate first.

### 7. The "wait, what?" test
Say the tweet out loud. If a smart non-expert wouldn't stop and say "wait, what?" it fails. If the response is "yeah, the planet is warming, I know" — rewrite.

### 8. Novelty engineering
Every tweet must contain *something new*. A new record, comparison, juxtaposition, rate, local angle. Vosoughi et al. 2018: novelty is the master variable of diffusion.

### 9. Social currency fit
Before posting: does sharing this make the reader look (a) informed, (b) caring, (c) righteous, or (d) witty? If none, kill it.

### 10. Dominance framing for shares
Tone that makes the reader feel INSIDE the knowledge — not threatened by it — spreads farther. "Look what's happening" beats "we're doomed."

### 11. Establish competence, then use pratfall sparingly
Consistent accuracy, crisp data, tight voice. Occasional humanized moments. Competence is the precondition.

### 12. Character budget
71–100 characters for peak engagement. Images beat no-images 2.5x on retweets. 1–2 hashtags max.

### 13. The Gen Z emotional frame
Determination > anger > sadness. Approach-oriented. Hope + awe + urgency beats pure crisis framing on sustained engagement.

### 14. Voice rules (bans)
- No "experts warn."
- No "according to."
- No "a new study shows."
- No "this is a wake-up call."
- No label:value date strings.
- No explaining what tier/category means.
- No explaining why the reader should care. **Trust them.**

### 15. The editorial bar
Tweet must be (awe-inducing OR anger-inducing OR anxiety-inducing OR laugh-inducing) **AND** contain a novel concrete fact the reader hasn't seen **AND** give the reader social currency to share.

**Hit the bar or skip the day. Frequency is not your friend; arousal-per-post is.**

---

## Citations

### Foundational virality
- Berger, J. & Milkman, K. (2012). "What Makes Online Content Viral?" *Journal of Marketing Research* 49(2): 192–205.
- Berger, J. (2011). "Arousal Increases Social Transmission of Information." *Psychological Science* 22(7): 891–893.
- Berger, J. (2013). *Contagious: Why Things Catch On.* Simon & Schuster.
- Nelson-Field, K. (2013). *Viral Marketing: The Science of Sharing.* Oxford University Press.

### Curiosity & emotional dimensions
- Loewenstein, G. (1994). "The Psychology of Curiosity." *Psychological Bulletin* 116(1): 75–98.
- Fractl/Hudson (2016). "The Emotional Combinations That Make Stories Go Viral." *HBR*.
- Kang, M.J. et al. (2009). Inverted-U curiosity empirical confirmation.

### Narrative & data
- Heath, C. & Heath, D. (2007). *Made to Stick.* Random House.
- Small, D., Loewenstein, G. & Slovic, P. (2007). "Sympathy and Callousness." *OBHDP* 102(2): 143–153.
- Tversky, A. & Kahneman, D. (1974). "Judgment under Uncertainty." *Science* 185: 1124–1131.

### Twitter/X research
- Vosoughi, S., Roy, D. & Aral, S. (2018). "The Spread of True and False News Online." *Science* 359: 1146–1151.
- Chen, Y. et al. (2023). "The secret to successful evocative messages: Anger takes the lead." *Communication Monographs*.
- Yuan, S. et al. (2024). "More aggressive, more retweets?"

### Perception
- Aronson, E., Willerman, B. & Floyd, J. (1966). "The Effect of a Pratfall on Increasing Interpersonal Attractiveness." *Psychonomic Science* 4: 227–228.
- Rathje, S. et al. (2024). "When curiosity gaps backfire." *Scientific Reports*.

### Climate-specific
- Pew Research Center (2021). "Gen Z, Millennials Stand Out for Climate Change Activism."
- Ettinger, J. et al. (2021). "Climate of hope or doom and gloom?" *Climatic Change*.
- Falkenberg, M. et al. (2022). "Growing polarization around climate change on social media." *Nature Climate Change*.
- Oxford Institute of Journalism / Shorenstein Center climate fatigue reports.

---

# PART 2 — Expanded Research (April 2026 update)

The original sections above cover the foundational academic work on what makes content viral. Part 2 expands into platform mechanics, copywriting craft, memetics, recent academic research, and tweet-anatomy patterns — all areas surfaced as gaps when the bot was producing accurate-but-flat content.

---

## 18. Memetics & Meme Theory

### 18.1 Dawkins (1976) — *The Selfish Gene*
Coined "meme" as "a unit of cultural transmission, or a unit of imitation." Argued evolution depends on any self-replicating unit. The meme, like the gene, is a **replicator**.

**For @theheat:** A tweet is not the unit — the **transmissible kernel** inside it is (a number, a record, a phrasing). Design tweets so the kernel can be ripped out and retold.

### 18.2 Blackmore (1999) — *The Meme Machine*
Three criteria for successful replicators: **fidelity** (copied accurately), **fecundity** (produces many copies), **longevity** (persists over time).

**For @theheat:** A tweet that wants memetic life must be easy to retype by hand (fidelity), easy to attach to a chart (fecundity), and stay true longer than the news cycle (longevity).

### 18.3 Shifman (2014) — *Memes in Digital Culture* (MIT Press)
Distinguishes **meme** (a cluster of derivatives, transformed by users) from **viral** (a single unit that spreads unchanged).

Three dimensions of every meme:
- **Content** — ideas conveyed
- **Form** — physical incarnation (image macro, GIF, quote format)
- **Stance** — tone, participation structure, communicative posture

Six features of highly spreadable content: positivity-tinged humor, simplicity, repetitiveness, incongruous juxtaposition, whimsical content, and a provocative/participatory hook.

**Conclusion:** Memes with a "hook" that invites participation outperform "closed" content. **Give people a socket to plug into.**

### 18.4 The Format Mechanic
Research on meme spreadability finds the **verbal component has greater remix capacity than the visual component**. The visual anchors recognition; the text is the variable.

**For @theheat:** A house visual template (specific chart style, specific card layout) turns every tweet into a recognizable meme format. Readers know "this is a Heat card." The text inside is the variable.

---

## 19. The X/Twitter Algorithm — What the Leaked Source Code Says

The core recommendation code was open-sourced by Twitter on March 31, 2023 (github.com/twitter/the-algorithm).

### 19.1 Engagement weights (simplified scoring formula)
- **Reply + author engages back** — ~150× a like (the single highest-weighted signal)
- **Retweet** — ~20× a like
- **Reply** — ~13.5× a like
- **Profile click** — ~12× a like
- **Link click** — ~11× a like
- **Bookmark** — ~10× a like
- **Like** — 1× baseline
- **Video watch ≥50%** — ~0.005 baseline weight

**The algorithm prices conversation far above passive approval.** A tweet that sparks a dialog between author and replier is the richest possible outcome.

### 19.2 TweepCred — hidden account reputation
Every account has a 0–100 reputation score. Below ~65, **only three of your tweets are considered for broad distribution at any time.** Factors include account age, follower/following ratio, device usage, verification, and prior restrictions.

### 19.3 Engagement velocity — the first-hour multiplier
**The first 30–60 minutes determine whether the For You feed distributes the post or lets it die.** A tweet getting 5 engagements in 10 minutes reaches 10–100× more people than the same engagement spread over 24 hours.

### 19.4 Dwell time — the silent signal
The algorithm tracks dwell time on tweet detail (15+ seconds threshold) and profile view (20+ seconds). If dwell time drops, a Quality Multiplier on the account can drop 15–20%.

**This directly favors data + chart content** that makes readers stop and look.

### 19.5 What the algorithm actively suppresses (2024–2026)
- **External links from non-Premium accounts** — median engagement effectively zero. 30–50% reach penalty.
- **More than 2–3 hashtags** — flagged as spam.
- **Repetitive content / copy-paste** — flagged.
- **"Like if you agree, RT if you disagree"** — actively downweighted.
- **@-mention stuffing** — deboosted similarly to links.
- **10+ tweets in 5 minutes** — spam pattern.

### 19.6 What the algorithm rewards
- **Long-form posts** (4000-char) over multi-tweet threads — Musk explicitly instructed this Oct 2023.
- **Native video** watched ≥10 seconds — major boost.
- **Replies-to-replies** — the conversational chain weighted ~75–150× a like.
- **Bookmarks** — Musk: "as much as a like, if not more."
- **Premium accounts** — documented 4×/2× visibility boosts.

### 19.7 TikTok and Instagram for comparison
- **TikTok:** Watch time / completion rate is #1. A 10s video at 80% completion beats a 60s video at 50%. **Shares (DM/cross-app) carry the heaviest weight** — stronger than likes or comments.
- **Instagram (Mosseri Jan 2025):** Watch time is #1 ranking factor for Reels. The first 3 seconds are critical. DMs are the most powerful share signal. Carousel posts averaged 10.15% engagement (vs single image 7%, Reels 6%).
- **Aggregator accounts on Instagram lost 60–80% reach in Dec 2025** while original creators gained 40–60%. Same pattern likely on X.

---

## 20. Copywriting Canon

### 20.1 Ogilvy — *Ogilvy on Advertising* (1985)
> "On the average, five times as many people read the headlines as read the body copy. Unless your headline sells your product, you have wasted 90% of your money."

**For @theheat:** The first line IS the tweet. The first line must carry the lead fact + context. Saving the zinger for line 3 wastes 90% of potential impressions in the feed preview.

### 20.2 Schwartz — *Breakthrough Advertising* (1966)
**Five Stages of Market Sophistication:**
1. First to market — simple claim works
2. Competitors enter — bigger claims
3. Saturation — mechanism differentiator
4. More saturation — mechanism elaboration
5. Total fatigue — identification > claim; audience wants to *be* someone

**Climate Twitter is at Stage 4–5.** Nobody believes a new "the planet is warming" claim. The wedge isn't the claim — it's the specific evidence, the novel mechanism, or **identity resonance**.

Schwartz's core principle: **"Channel existing desires; do not try to create them."** @theheat's existing desire = the reader's suspicion that something is deeply wrong. The job is to supply the proof.

### 20.3 Cialdini — *Influence* (1984, rev. 2021)
Seven principles: **Reciprocity, Commitment & Consistency, Social Proof, Authority, Liking, Scarcity, Unity** (added 2016).

**For @theheat:** Scarcity is the natural climate lever (species lost, ice lost, days below freezing lost). Authority comes from clean data + sourcing. Unity ("people who can see what's happening") is the strongest and least-used.

### 20.4 Bly — *The Copywriter's Handbook*
8 headlines that work: Direct, Indirect, News, How-to, Question, Command, Reason-why, Testimonial.

**4 S formula** for body copy: Simple, Short, Sincere, Specific.

### 20.5 Wiebe / Copyhackers — Five-second test
If a reader can't state what the headline promises after five seconds of exposure, kill or rewrite it.

### 20.6 The Curiosity Loop / Open Loop (Zeigarnik)
Bluma Zeigarnik 1927: uncompleted tasks are remembered better than completed ones. Open the loop in line 1, resolve within 1–3 lines.

### 20.7 PAS over AIDA
For short-form content, **PAS (Problem → Agitate → Solution)** outperforms AIDA because it starts in pain. State the problem (a record). Agitate (specifically what's unusual). Solution (the unspoken prompt: look, and keep looking).

---

## 21. Cognitive Biases That Drive Sharing

### 21.1 Negativity Bias — Rozin & Royzman 2001
Four manifestations:
1. **Negative potency** — negatives are stronger than equivalent positives
2. **Steeper negative gradients** — negativity grows more rapidly with proximity
3. **Negativity dominance** — when positive + negative combine, result is more negative than arithmetic predicts
4. **Negative differentiation** — negatives have richer, more elaborated mental representations

### 21.2 Soroka, Fournier & Nir 2019 (PNAS)
17-country, 6-continent psychophysiological study. **Across all cultures, humans show a negativity bias in physiological arousal when watching news.** Heart rate and skin conductance rise more for negative stories. Species-level, not cultural.

### 21.3 Why negative beats positive even when people SAY they prefer positive
- **Robertson et al. 2023** (Nature Human Behaviour): 23,000 Upworthy A/B-tested headlines. Each additional negative word **raises CTR by 2.3%**, each positive word **lowers it by 1.0%**.
- **Scientific Reports 2024:** 95,282 articles, 579M social posts. Negative news is **1.91× more likely to be shared**. With retweets factored in: **34%–61% increase in shares**.
- **Cambridge Judge Business School 2024:** Negativity is shared more between weak ties; positivity between close ties. **Twitter's default network is weak-tie, so the platform structurally selects for negative content.**

### 21.4 Availability Heuristic (Tversky & Kahneman 1973)
People estimate probability by how easily examples come to mind. Vivid, recent, emotional events feel more probable than their actual frequencies.

**For @theheat:** A tweet that vividly renders a single extreme event (specific town, specific number) updates the reader's internal frequency estimate of climate events far more than aggregate statistics do.

### 21.5 Mere Exposure Effect (Zajonc 1968)
Repeated exposure to a neutral stimulus increases liking. Bornstein 1989 meta-analysis (208 experiments): effect size r = 0.26, peaks at 10–20 exposures.

**For @theheat:** A daily rhythm builds preference independent of content quality. Miss two weeks → mere-exposure accumulation resets.

### 21.6 Peak-End Rule (Kahneman et al. 1993)
People judge experiences by the **peak intensity** and the **ending**, not the integral.

**For @theheat:** A tweet needs a peak moment (the number that hits) and a strong ending (not a trailing reservation). Do not end with "but it's complicated."

### 21.7 Von Restorff / Isolation Effect
A distinctive item in a list is remembered better than its neighbors.

**For @theheat:** Whatever makes a tweet visually or structurally distinct in the feed (chart style, card format, voice cadence) compounds recall far more than any single fact.

### 21.8 Status Quo Bias and Loss Framing
Kahneman's prospect theory: losses loom ~2× as large as gains.

**For @theheat:** "You could lose this" beats "you could gain this." Loss-frame: what is **going away**, what is **being broken**, what **will not happen again**.

---

## 22. Moral Contagion & Out-Group Animosity

### 22.1 Brady, Wills, Jost, Tucker, Van Bavel 2017 (PNAS)
*Emotion shapes the diffusion of moralized content in social networks.*

**Each additional moral-emotional word in a tweet increases diffusion by ~20%.** Effect is within-group only — moral-emotional language travels *inside* ideological networks, not between them.

A 2024 meta-analysis (PNAS Nexus 2025) replicated this at ~17% per word.

### 22.2 The MAD Model (Brady, Crockett, Van Bavel 2020)
Three drivers of moral contagion:
- **Motivation** — self-presentation, group membership
- **Attention** — moral content captures attention preferentially
- **Design** — platform features amplify moral content

### 22.3 Rathje, Van Bavel, van der Linden 2021 (PNAS) — Out-Group Animosity
2.7M posts. **Each additional out-group word raised share probability by 35%–57%.** Out-group language was the **single strongest predictor of sharing** — stronger than in-group language, stronger than moral-emotional language, stronger than negative emotion.

Posts about political opponents are ~2× as shareable as posts about political allies.

**For @theheat:** Naming a specific antagonist (deniers, specific companies, specific politicians) has structurally higher share probability. BUT — comes with brand cost. Safe path: frame "inaction," "the status quo," or "the oil majors" (factually) as antagonist, without partisan invective.

---

## 23. Tweet Anatomy — Structural Patterns

### 23.1 Unexpected Specificity
Brain registers a precise number as **higher-credibility** than a round number.
- "It rained for 37 days" beats "It rained for a month"
- "41.8°C" beats "very hot"
- "189 consecutive days" beats "almost a year"

### 23.2 The Negation Flip
**"Not X. Actually Y."** or **"X. But Y."**

Examples:
- "It's not just hot. It's the hottest week in recorded history."
- "Not one city. Twelve."
- "The heat wave didn't break a record. It broke three."

The negation activates the reader's expectation, then violates it. Structurally distinct in the feed (Von Restorff).

### 23.3 The Rule of Three (Rising Stakes)
Lists of three escalate better than two or four.
- "Faster. Hotter. Deadlier."
- "In 1910, never. In 1990, once. In 2025, monthly."

### 23.4 The Open Loop (Zeigarnik)
State surprise in line 1. Resolve in line 2–3.
- "Tokyo just hit 41.8°C. / Here's what's weird: / That used to be impossible for this month."

### 23.5 The "Stop and Think" Hook
Questions activate generative processing — the reader mentally attempts an answer before reading the provided one. Increases dwell time.
- "When was the last time it was this hot in Paris? Answer: never."

(But avoid generic questions — "what do you think?" is engagement-farming and penalized.)

### 23.6 The Twist
Set up expectation, then violate it.
- "This is a heat map of Europe. (Normal.) It's from February. (Not normal.)"

### 23.7 One-Line vs Two-Line vs Three-Line
- **One-line tweets** — highest virality potential per word. Best for aphorism, hot take, shock number.
- **Two-line tweets** — allow open-loop setup + resolution. Strong for data (claim + context).
- **Three-line tweets** — allow setup + build + punch. Strong for narrative.
- **Multi-paragraph** — only succeeds if dwell time stays high.

### 23.8 The List-of-Three with Escalation
> 1990: X
> 2005: Y
> 2025: Z
Where each is a worse escalation. Format requires no commentary because the escalation speaks.

---

## 24. Patterns from Successful Twitter Accounts

### 24.1 Naval Ravikant
Aphoristic compression + contrast structure. **Three-part taxonomies.** **"Not X. Y." negation-flip.** **Single-thought tweets** — one idea, no caveats. **Portability** — the line works on a mug, a Notion page, a screenshot.

### 24.2 Visakan Veerasamy (@visakanv)
- "Dumb tweeting to precipitate smart writing" — post low-stakes to find what resonates.
- Twitter as a second brain — every thread references older threads.
- "Be purpose-driven. Know your end-goal."

### 24.3 Paul Graham — "Founder Mode" (2024)
Went viral because it **named a latent feeling**. Schwartz Stage-5 work: market saturated with generic startup advice. Graham coined a label that splits insiders from outsiders. **Language that pre-activates identity.**

### 24.4 NASA & Astro Accounts
- Carina Nebula post: NASA's all-time most-engaged social post (>7M engagements).
- The image is the product. Text annotates; it does not carry the load. **Institutional reticence earns trust; one striking image does the work.**

### 24.5 @extremetemps
Run by a climatologist (mherrera.org/temp.htm).
- **Near-identical card format**: flag emoji + country + station + value + context.
- **No commentary.** The data is the whole tweet.
- Heavy use of **records broken** as the unit of news.
- **Always the same visual grammar.**

This is a textbook **Shifman meme format**: fixed template (form) + varying payload (content) + stable stance (deadpan record-keeping).

### 24.6 The Decline of the Thread Bro
Oct 2023: Musk explicitly stated X's algorithm deprioritizes threads, prefers long-form posts ≤4000 chars.

**Single long-form posts now outperform multi-tweet threads** for algorithmic distribution. Structural shift, not taste shift.

---

## 25. Climate Viral Content — Case Studies

### 25.1 Greta Thunberg — "How Dare You" (Sept 2019)
The phrase trended globally within 72 hours and templated into image macros across YouTube and Twitter.

Mechanics:
- **Negation with moral-emotional weight** — "how dare you" is pure outrage in three words
- **Repetition** — spoken as a refrain, templates for re-quotation
- **Pratfall generator** — adults mocking a 16-year-old triggered counter-amplification
- **Identity activation** — split audiences instantly into for/against camps (Rathje 35–57% multiplier)

Converted a generational grievance into a portable phrase that carried the full emotional payload.

### 25.2 Warming Stripes (Ed Hawkins, 2018)
Most successful single climate visualization of the 2010s–2020s:
- 1M+ downloads in week 1
- Used on murals, T-shirts, climate strike posters, *The Economist* cover (2019)
- Hawkins received an MBE in 2020 specifically for science communication

Why it works (Shifman decomposition):
- **Form:** Fixed grammar (stripes, blue→red, chronological) infinitely re-deployable to any region/city/time
- **Content:** Zero text, zero chart chrome, zero axis labels — visual is the argument
- **Stance:** Scientific authorial restraint

**The single most instructive meme for @theheat's own chart system. A house visual template with zero chrome that admits infinite payload substitution.**

### 25.3 Hockey Stick Graph (Mann et al. 1999)
The *shape* (flat handle, dramatic blade) **IS** the argument, parseable in under one second. Became a symbol on both sides — rallying icon for advocates, target for deniers.

### 25.4 What Viral Climate Charts Share
- **One variable** — temperature, ice, CO₂. Not multi-variable dashboards.
- **One time axis** — no zoom switcher. Reader sees the full span at once.
- **A dramatic shape** — a line that hockey-sticks, stripes that redshift.
- **Zero chart chrome when possible** — no axis labels, no gridlines, just the data.
- **One color grammar** — red means worse, always.
- **Regional derivative variants** — meta-chart spawns city/state/country variants.

### 25.5 Bravo, Silva Luna, Walter 2025 (Journalism Studies)
Viral climate imagery analysis on Twitter:
- **Maps outperform charts** for regional resonance.
- **Before/after photos** outperform abstract visualization.
- **People in images** increase sharing vs pure landscape.
- **Iconic species** (polar bears, coral, koalas) still work despite "cliché" critique.

---

## 26. Imagery & Visual Content

### 26.1 Tweet Engagement Multipliers with Images
- **AdWeek 2014:** +150% retweets, +89% favorites, +18% clicks
- **AJNR 2021 academic study:** image presence increased engagement by **28.75×**
- Lower-authority accounts: 5–9× retweets, 4–12× favorites with images

**Every @theheat tweet should have a visual unless there is a specific reason not to.**

### 26.2 Maps vs Charts
Maps outperform charts for regional resonance. Self-reference (finding your own city) is a known memory enhancer.

### 26.3 Before/After Format
Photographs of glaciers, coral, deforestation in before/after pairs consistently viralize. Zero cognitive load for interpretation, maximum concreteness.

### 26.4 Video / GIF / Still
- **Native video** ≥10s watch: algorithmic boost but requires playback commitment
- **GIFs / silent looping video**: dwell-time winners — auto-play, increase signal without requiring tap
- **Animated stills** (e.g. warming stripes over time): best of both worlds

---

## 27. What KILLS Engagement on X (Specific)

1. **External links in free accounts** — effectively zero engagement. 30–50% reach penalty. Workaround: post the tweet, then reply with the link.
2. **Hashtag bloat** — 3+ = penalty. Hashtags are also largely irrelevant for discovery in 2026.
3. **@-mention stuffing** — same suppression as links.
4. **Engagement farming patterns** — "Like if you agree" style, downweighted.
5. **Repetitive posting** — copy-paste flagged. 10 tweets in 5 minutes = spam.
6. **Low dwell time** — Quality Multiplier drops 15–20%, compounds into less reach.
7. **Reposting without adding** — aggregator accounts losing 60–80% reach.

---

## 28. Operational Levers (Additive Playbook)

These are the *new* levers from Part 2 research. Combine with Section 17 from Part 1.

1. **Ship a house visual template.** The Hawkins Warming Stripes lesson. Fixed card grammar = recognizable Heat-brand meme format.
2. **First line carries the lead.** Ogilvy: 90% never read past the headline.
3. **Reply to your own tweet.** Author-reply-in-reply chain is the algorithm's single richest signal (~150× a like). Engineer for it: post, wait for reply, engage.
4. **Get Premium verified.** Documented 4×/2× algorithmic boost.
5. **Post at engagement-velocity windows.** First 30–60 minutes determine if the post gets expanded or killed.
6. **Minimize external links in main tweets.** If a source link is required, reply to self with it.
7. **Aim for bookmarkable content.** Bookmarks weighted 10×. Records, data references, regional stats are bookmark-bait.
8. **Each moral-emotional word = +17–20% shares** (Brady et al. meta-analysis). Calibrate against brand voice bans.
9. **Out-group framing without partisan invective.** Antagonists: inaction, the status quo, industries identified by data.
10. **Unexpected specificity.** "41.8°C, a new national record" beats "record heat."
11. **Unity framing.** "People who see what's happening" — activate identity without partisan tribe.
12. **Negation flip as default sentence structure.** "Not X. Actually Y."
13. **Rule of three with escalation.** Format requires no commentary.
14. **Peak-end rule.** Don't trail off with caveats. End on the punch.
15. **Mere-exposure rhythm.** Daily cadence builds preference independent of content quality.
16. **Use maps for regional resonance.** Self-reference encoding.
17. **Reply-to-self for sources, second-beat fact.** Splits the signal, activates conversational chain multiplier.

---

## Citations (Part 2)

### Memetics
- Dawkins, R. (1976). *The Selfish Gene.* Oxford University Press.
- Blackmore, S. (1999). *The Meme Machine.* Oxford University Press.
- Shifman, L. (2014). *Memes in Digital Culture.* MIT Press.
- Dancygier, B. & Vandelanotte, L. (2017). *Internet memes as multimodal constructions.* Cognitive Linguistics.

### X/Twitter Algorithm
- Twitter, Inc. (2023). *Source code for the Twitter recommendation algorithm* — github.com/twitter/the-algorithm
- Axios (2023-10-03). Musk on long-form vs threads.
- Buffer (2025). Links on X performance analysis.

### Negativity Bias
- Rozin, P. & Royzman, E. B. (2001). *Negativity bias, negativity dominance, and contagion.* Personality and Social Psychology Review 5: 296–320.
- Soroka, S., Fournier, P., Nir, L. (2019). *Cross-national evidence of a negativity bias in psychophysiological reactions to news.* PNAS 116(38): 18888–18892.
- Robertson, C. E. et al. (2023). *Negativity drives online news consumption.* Nature Human Behaviour 7: 812–822.

### Copywriting Canon
- Ogilvy, D. (1985). *Ogilvy on Advertising.* Crown Publishing.
- Schwartz, E. M. (1966). *Breakthrough Advertising.* Boardroom, Inc.
- Cialdini, R. B. (1984, rev. 2021). *Influence: The Psychology of Persuasion.* HarperBusiness.
- Bly, R. W. (1985, 4th ed. 2020). *The Copywriter's Handbook.* Henry Holt.
- Wiebe, J. (2011–present). Copyhackers — copyhackers.com
- Zeigarnik, B. (1927). *On finished and unfinished tasks.*

### Cognitive Biases
- Tversky, A. & Kahneman, D. (1973). *Availability: A heuristic for judging frequency and probability.* Cognitive Psychology 5: 207–232.
- Zajonc, R. B. (1968). *The attitudinal effects of mere exposure.* JPSP Monograph Supplement 9.
- Bornstein, R. F. (1989). *Exposure and affect: Overview and meta-analysis.* Psychological Bulletin 106: 265–289.
- Kahneman, D. et al. (1993). *When more pain is preferred to less.* Psychological Science 4: 401–405.
- von Restorff, H. (1933). *Über die Wirkung von Bereichsbildungen im Spurenfeld.* Psychologische Forschung 18: 299–342.
- Samuelson, W. & Zeckhauser, R. (1988). *Status quo bias in decision making.* Journal of Risk and Uncertainty 1: 7–59.

### Moral Contagion & Out-Group
- Brady, W. J. et al. (2017). *Emotion shapes the diffusion of moralized content in social networks.* PNAS 114(28): 7313–7318.
- Brady, W. J., Crockett, M. J., Van Bavel, J. J. (2020). *The MAD Model of Moral Contagion.* Perspectives on Psychological Science 15: 978–1010.
- Rathje, S., Van Bavel, J. J., van der Linden, S. (2021). *Out-group animosity drives engagement on social media.* PNAS 118(26): e2024292118.

### Climate Visualization
- Hawkins, E. (2018–present). *Warming Stripes* — showyourstripes.info
- Mann, M. E., Bradley, R. S., Hughes, M. K. (1999). *Northern hemisphere temperatures during the past millennium.* Geophysical Research Letters 26: 759–762.
- Bravo, I., Silva Luna, D., Walter, S. (2025). *Viral climate imagery: examining popular climate visuals on Twitter.* Journalism Studies.

### Image Engagement
- AdWeek (2014). *Tweets With Images Get 18% More Clicks, 89% More Favorites And 150% More Retweets.*
- Brady, A. L. et al. (2017). *Maximizing the Tweet Engagement Rate in Academia.* American Journal of Neuroradiology 38: 1866–1871.

### Costly Signaling
- Smaldino, P. E. & Pérez, M. (2022). *Strategic identity signaling in heterogeneous networks.* PNAS 119(14): e2117898119.
- Spence, M. (1973). *Job market signaling.* Quarterly Journal of Economics 87: 355–374.

---

*Compiled April 2026 for @theheat editorial reference. Update when new research materially changes recommendations. Part 2 added April 17, 2026.*
