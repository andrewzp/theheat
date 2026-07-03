# @theheat — What we're trying to achieve

> The north star. Read this before designing or building anything: it says what
> "good" means, and it names the failure we are organizing the work around.

## The mission

@theheat surfaces the most significant climate and extreme-weather events on Earth,
in real time, as tweets a climate-literate reader stops scrolling for and sends to a
friend. **The data is the product; the voice is the chassis it rides in.**

## What "good" looks like — three bars we are NOT yet clearing

1. **Editorially excellent.** Every tweet should be genuinely well-written — the quality
   of a sharp news story or an Economist paragraph, not a data-ticker readout. It should
   teach, land, and be worth a smart reader's attention. Honest and accurate is the floor,
   not the goal.

2. **Carries interesting anecdotes, like a good news story.** The best coverage carries
   the human and concrete detail — the death toll, the firefighters killed, "buses
   crashed, drivers passed out," the record that fell for the second year running. A
   number without a human stake is a stat; a number *with* one is a story. Every such
   detail must be **sourced, cited, and real — never invented.**

3. **Global coverage.** We cover the whole planet, not the loudest sensor. The biggest
   story *anywhere* on Earth should reach the feed, wherever it happens — not just where a
   single sensor happens to spike highest.

## The failure that proves the gap

In late June 2026, a heat wave killed **more than 1,200 people across Europe** (the WHO
counted **1,300+ excess deaths**; about 1,000 in France alone) — one of the deadliest
weather events of the year. **@theheat missed it ENTIRELY.** Not "covered it weakly" — the
death toll never had *any path* into the bot at all.

On the same days, the bot **posted** a remote 1,468 MW fire in the Congo Basin, DR Congo,
while **suppressing** the deadly Colorado/Utah wildfire outbreak — 3 firefighters killed,
79 fires across 10 states, the lead of the Washington Post — because its sensor score fell
*one point* below an arbitrary cutoff (62 < 64). And the one Western fire it did draft was
"595 MW in the Rocky Mountains, Colorado" — a lonely satellite pixel, never "the West is on
fire, 3 dead."

**It surfaced the biggest NUMBER and missed the biggest STORY.** Twice, in one week, on the
two deadliest weather events on Earth.

## Why (the root cause)

The bot ranks signals by **raw sensor magnitude** (megawatts, °C anomaly) and is **blind to
newsworthiness and human stakes.** It sees disaggregated sensor pixels, not events. It has
no sense of what is actually happening in the world, and no way to carry the human toll of
what it does detect.

## How we get there ("Bet A")

Make the bot's selection **autonomously smart**: give it a *sourced* sense of newsworthiness
and human impact so it (a) tweets the stories that matter — the Colorado fire beats the
Congo one — and (b) carries the human stakes — the tweet says "3 firefighters killed," not
just "595 MW." Design in progress:
[docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md).

## The non-negotiable constraint

Everything above is bounded by one iron rule: **no false claims, ever.** Every figure — a
death toll, a record, an anecdote — must come from **real, cited retrieval, never the
model's imagination.** Current news is past the writer model's knowledge cutoff, so a
hallucinated death toll is the one unforgivable error — worse than a boring tweet, worse
than a missed one. **Editorial excellence, anecdotes, and global coverage are the goal;
verifiable truth is the constraint that never bends.**
