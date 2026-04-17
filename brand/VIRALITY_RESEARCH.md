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

*Compiled April 2026 for @theheat editorial reference. Update when new research materially changes recommendations.*
