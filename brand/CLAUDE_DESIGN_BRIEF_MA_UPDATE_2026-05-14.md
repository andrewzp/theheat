# Claude Design Brief — Update Document Inventory: MESSAGING_ARCHITECTURE.md

**Date:** 2026-05-14
**Scope:** Replace your cached copy of `brand/MESSAGING_ARCHITECTURE.md` with the version below. The previous version was the source of stale framings (`The planet's scorecard.`, `climate data wire service that developed a personality`, `Reuters meets @spectatorindex`) that produced incorrect output in the earlier delivery. The version below is the new canonical source of truth.

All design work continues per `brand/CLAUDE_DESIGN_BRIEF_BRAND_KIT_CORRECTION_2026-05-14.md`. This brief only updates your reference inventory.

---

## New canonical MESSAGING_ARCHITECTURE.md (replaces previous)

```markdown
# The Heat — Messaging Architecture

---

## STRATEGY

**Purpose**
Make climate data impossible to ignore.

**Vision**
The most-followed climate account on the internet. Not because it lectures. Because the data is that striking when you actually present it clearly.

**Mission**
Turn real-time planetary data into content people understand, share, and talk about.

---

## POSITIONING

**Target Market**
Data people. The FlightRadar24 crowd. Weather nerds. Disaster watchers. People who care about climate but unfollow anyone who lectures them. The overlap between "wants to be informed" and "doesn't want to be preached at."

**Core Essence**
Climate data, delivered clearly.

**Core Tension**
Everything The Heat says is factually sourced from NASA, NOAA, and global weather systems. It's delivered with dry confidence and enough context to land. The tension between "this is just the data" and "holy shit, that data" is the hook.

**Category**
Climate media. Not climate activism. Not climate science. Climate media.

**Differentiator**
Most climate accounts either lecture or panic. The Heat just reports the numbers with enough context that they hit on their own. No opinions needed. The data is the editorial.

**Position**
The Heat is the account you follow because the data is always clear and often surprising, and then one day you realize you've accidentally become the most informed person in the room about climate.

**Value Proposition**
Your city breaks a heat record? The Heat posts it with the old record and when it was set. A wildfire lights up on satellite? You see the MW reading. CO2 crosses a milestone? You see the pre-industrial baseline. A tornado warning hits Oklahoma? You see it. The Mississippi crests flood stage? You see by how much. Arctic sea ice hits a record low? You see the previous record and when it was set. Always clear. Always sourced. Always in under 280 characters.

---

## MESSAGING

**Tagline**
Diary of a warming planet.

**Key Messages**

1. **The numbers speak for themselves.** We don't editorialize. We give you the data point and the context to understand it. That's usually enough.

2. **Faster than your news app.** Satellite-detected wildfires, broken records, CO2 milestones, tornado warnings, flood stages, storm surge, extreme waves, drought, sea ice, ENSO transitions. Real-time data from 13 sources, not yesterday's recap.

3. **The Hot 10.** Every day, the 10 cities furthest above their historical normal. Not who's hottest. Who's most abnormal. Your city makes the list and you send it to your group chat.

4. **No opinions. No politics. Just the data.** We don't tell you what to think. The numbers do that.

5. **Built by one person. Powered by a bot.** Open source. No corporate backing. No agenda. Just data and context in under 280 characters.

---

## PERSONALITY

**Attributes**
- Clear first
- Data-backed
- Confident
- Dry
- Contextual

**Personality**

The Heat is a diary of a warming planet — the planet keeps its own record; we transcribe the entries with calm authority and one sentence on the system behind each number.

Not a scientist explaining climate change. Not an activist begging you to care. A confident, observational voice that leads with data, names the system behind it, and stops.

The voice is David Attenborough meets The Economist — calm expert observation plus compressed precision. Lead with the fact. Add the system clause that gives it scale (the cold-air drainage in a topographic bowl, the western Pacific warm pool, the dry-season vegetation cure). Stop. If the second sentence would be background geography or expository padding, ship the one-sentence version. The data is already striking; the voice is its straight man.

Every tweet should pass this test: **does someone seeing this for the first time understand what happened, where, and why it matters?** If the answer is no, rewrite it. Context is not optional.

**Brand Tension:** Clear AND compelling. The context makes it shareable. The data makes it credible. If it's not clear, nobody understands. If it's not well-sourced, nobody trusts it.

**Promise**
Every number is sourced. Every tweet has enough context to understand. You'll probably send it to someone.

**Voice**
Short sentences. Data first. System clause second — name the mechanism, consequence, or rate behind the data when one exists. The power is in the comparison — "pre-industrial was 280" hits harder than any joke. Historical context is the punchline.

Voice references:
- David Attenborough (calm expert observation; name the system behind the moment, no flourish)
- The Economist (compressed precision; treats data as load-bearing; trusts the reader)
- Reuters / AP wire alerts (clean, authoritative, no padding)

Rules:
- Under 280 characters. Always.
- No emojis. No hashtags. No exclamation points.
- Every tweet must be self-contained with full context.
- Lead with data, add comparison, editorial only when earned.
- Never preachy. Never political.
- Never mock human suffering or trivialize death.
- No sports metaphors. No gaming slang. No forced personality.
- If the data is striking, state it plainly. That's enough.

(Tweet examples retained from the previous version are historical reference; the current writer-prompt standard lives in `src/two_bot/prompts/writer_prompt.py`.)

---

## THE PROBLEM WE SOLVE

Climate content has a distribution problem, not a data problem.

The data is extraordinary. Records falling monthly. Fires starting earlier every year. CO2 at levels unseen in millions of years. Rivers cresting flood stage. Sea ice at record lows. Category 4 cyclones. 40-foot waves. But the data is trapped in NOAA databases, NASA feeds, USGS gauges, and academic papers that nobody reads.

The accounts that try to share it either lecture (unfollowed), panic (muted), or post raw data without context (ignored).

The Heat fixes both problems. Same data. Clear delivery. Enough context to understand. A dry, confident voice that lets the numbers land without getting in the way. You read the tweet, you understand what happened, and you share it because the data itself is striking.

Awareness is the side effect of clarity. That's the model.

---

## FUTURE DIRECTION

The "Diary of a warming planet" tagline sets up a brand arc that today's voice does not yet execute in the tweets themselves. Today's voice is calm, third-person, observational — the planet's transcribers, not the planet's narrator.

The longer-term arc is first-person personification: the heat (or the planet) as the narrator of its own diary, in the spirit of Karl the Fog. Single-author character accounts work on Twitter when written by a human with taste; automated pipelines cannot yet carry the voice discipline this requires consistently.

Hold this as the v2 brand evolution. Revisit when model capability supports consistent first-person personified-heat narration that meets the Attenborough/Economist quality bar without collapsing into "the planet is having a bad day" cuteness.

For now: tagline lives in the brand layer ("Diary of a warming planet."), tweets stay calm Attenborough/Economist observational. The third-person tweets read *through* the diary frame — the planet keeping a record of itself, transcribed by the desk.

Also held for a future v2 pass:

- **The thermometer mark** may eventually over-index on temperature when the brand covers fires, CO2, ice mass, drought, marine waves, severe weather, river floods, sea ice.
- **The orange accent** (#C2410C) is applied to "values that matter" but visually reads as *heat*. When applied to a cold record, the color subtly miscues.
```

---

## Action

Replace your cached `MESSAGING_ARCHITECTURE.md` with the block above. Continue all design work per `CLAUDE_DESIGN_BRIEF_BRAND_KIT_CORRECTION_2026-05-14.md`.
