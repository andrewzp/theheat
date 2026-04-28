# Claude Design Brief — @theheat

**Drop this brief into Claude Design alongside the supporting docs listed at the bottom. The codebase at `github.com/andrewzp/theheat` is also available to point Claude at directly.**

---

## At a glance

@theheat is an automated climate-data Twitter bot. It monitors free public data sources for extreme climate signals — heat records, anomalies, wildfires, CO2 milestones, sea ice, drought, severe weather — and posts tweets in under 280 characters with the data and just enough context to make it land. 14 data sources, 613 cities across 179 countries. Run by one person, $25–45/month operating cost, fully automated except for human review of pending drafts on a custom dashboard.

The bot ships. The voice ships. The dashboard works but looks engineered, not designed. The Twitter profile is generic. **We're commissioning a brand identity that lives across Twitter (primary public surface), a future landing site, and the operator dashboard — with a design system underneath that ties them together.** The brand needs to feel as serious about the data as the data is.

This is a utility, not a growth startup. Not climate activism. Not climate science. Climate media — clear, sourced, in the data-ticker genre. The genre operator we admire is @extremetemps (106K followers, manually run, deadpan record-keeping). The data is the editorial.

---

## What we're commissioning, in order

### Phase 1 — Brand identity (immediate) — THREE DIRECTIONS REQUESTED

**Generate three distinct brand directions for review, not one polished system.** Each direction should be a complete enough sketch that the choice is real — wordmark, palette, type pairing, and one applied surface (a Twitter profile mockup is the suggested anchor). After review we pick one direction and Phase 1 deepens into the production-ready identity.

**One starting hypothesis per direction (suggestions, not gospel):**
- **Direction A — "Wire service."** Reuters-meets-Bloomberg authority. Restrained palette, mostly monochrome with one earned accent. Slab or transitional serif wordmark for institutional gravity. Monospace data, sans body. Reads like a credible newsroom.
- **Direction B — "Instrument panel."** FlightRadar24 / earthnullschool / Bloomberg Terminal lineage. Heavy on grids, monospace, sparklines, status pills. Wordmark feels mechanical / technical. Dense data treatment. Reads like an operator console.
- **Direction C — "Atmospheric."** NASA mission / institutional science aesthetic. The data is the awe. Cleaner / more breathing room than B. Wordmark could be confident geometric sans. Type system stays restrained. Reads like a serious science account that takes itself seriously without being cold.

These are starting frames — Claude Design should feel free to remix or replace them if a stronger direction emerges. The constraint is: **three meaningfully different directions**, not three variants of the same idea.

**Each direction must include:**
- **Wordmark.** Primary mark + monochrome variant + favicon-scale glyph. Brand name is "The Heat" — treat "@theheat" lowercase as the social handle.
- **Color system.** Dark base + accent + semantic alerts (good / warn / fail) + one heat-coded accent for editorial moments. Light-theme variant.
- **Typography pairing.** Sans for tweets/body, monospace for metadata/scores/data, optional ceremonial accent.
- **Twitter profile mockup.** Avatar (400×400), banner (1500×500), example pinned tweet visual treatment, bio composition. This is the anchor surface — every direction must show how it lives on Twitter.
- **One dashboard panel applied.** The drafts list panel is the suggested surface — applies the type/color/components in context.
- **Mood notes.** A short paragraph explaining the direction's center of gravity and what it's saying about The Heat.

**Reference points worth pulling from (mix and match across directions):**
- NASA mission graphics + Voyager Golden Record (institutional, trusted, scientific awe)
- FlightRadar24, earthnullschool, windy.com (real-time data + map atmospheres)
- Terminal apps, Bloomberg Terminal, NetHack-era ASCII (operator clarity, information density)
- Linear, Vercel, early Stripe (clean dark UI without aggression)
- Reuters / AP wire alerts, AP Stylebook covers (institutional authority)
- @extremetemps (the actual genre operator — visual grammar of station data + flag emojis + records)

### Phase 2 — Design system
Built on the Phase 1 identity. Targeting Tailwind CSS + shadcn/ui as the implementation foundation (decision locked).
- **Design tokens** — color, typography, spacing, radius, elevation, motion. As CSS variables AND Tailwind theme config.
- **Core components** — Card, Button, Pill / Badge, Tabs, Score grid, Sparkline, Status indicator, Input, Modal, Toast, Empty state.
- **Patterns** — list-detail (the drafts surface), compact metric tiles, sparkline strips, log-style timelines.
- **Iconography** — minimal, line-based, monochrome. Stick with Lucide unless there's a good reason not to.
- **Dark theme primary, light theme as a parallel set.** Mobile-friendly (phone is fallback, not primary).

### Phase 3 — Brand surfaces (Twitter + landing site)

The bot's primary public face is its **Twitter profile**. Every viewer of the bot sees the avatar / banner / pinned tweet before they see the dashboard. The Twitter surface is at least as important as the dashboard — possibly more, because dashboard visitors are operators, while Twitter visitors are everyone else.

**Twitter profile** (deliver in Phase 1 mockups, polish in Phase 3):
- **Avatar.** Square 400×400, must remain legible at 32px circle (timeline) and 16px (notification dot). Single-glyph treatment from the wordmark system.
- **Header / banner.** 1500×500. Two centers of gravity to consider: a typographic banner (wordmark + tagline) versus a data-visualization banner (live-feeling stats, e.g., "47.2C — Mali, today" treated as the hero image). A direction's banner choice is part of how the direction is read.
- **Bio.** 160 chars. Current bio TBD but worth including a draft line.
- **Pinned tweet.** Visual + copy. The pinned tweet is the brand statement — what's the manifesto in one tweet? Each direction should include a candidate.
- **Mobile preview.** All Twitter assets must be checked at iPhone-width (Twitter mobile crops banners aggressively).

**Landing site / website** (Phase 3 scope — direction-aware mockups, not full build):
- One page, marketing-light. Sections: hero (wordmark + tagline + "what is this"), live data ticker or recent-tweet embed, methodology / sources, newsletter signup hook (when ready), link to GitHub repo. Anchored on the brand identity from Phase 1.
- Should feel like the bot's "about page" — a credible explanation of what the bot does and why it can be trusted, not a marketing pitch.
- Domain: **`theheat.ai`** (owned).
- Future-state: also a corpus browser surface, archive of notable tweets, weekly digest. Not Phase 3, but design shouldn't preclude.

### Phase 4 — Dashboard flats
Apply the design system to the dashboard redesign. Key screens:
- **Home / Command Center (desktop).** Grid layout: drafts panel (~60% width, primary), right column for bot-brain status / signal volume sparklines / Hot 10 + streaks. Below the fold: recent runs + recent errors.
- **Home (mobile fallback).** Single-column stack — drafts first.
- **Draft detail focus.** Selected tweet with score breakdown (5 dimensions), candidate alternates, review context, approve / edit / reject.
- **Compose modal.** Manual prompt → Gemini generation → safety review → post.
- **Generate trigger.** Force an alerts cycle, leaderboard, or both.
- **Bot brain deep view (Phase 3 future).** Trend charts, run history, source health over time, in-dashboard corpus browser, analytics scaffold.

We've already done the direction-setting wireframe (single-page command-center grid, with a "functional dark" aesthetic — flatter than current, monospace for metadata, sans-serif for tweets). Reference: gstack mockups in `.superpowers/brainstorm/` and the wireframe in [LEVEL_UP_PLAN.md section 2.4](./LEVEL_UP_PLAN.md). Claude Design is welcome to reinterpret if the direction can be improved — but should respect the locked decisions on grid layout, dark default, and phone-friendly fallback.

---

## Audience

**The data crowd.** Specifically:
- The FlightRadar24 / windy.com / earthnullschool crowd
- Weather nerds, storm chasers, disaster watchers
- Climate-aware professionals (data scientists, journalists, atmospheric researchers, NGO staff)
- People who follow @spectatorindex, @unusual_whales, Reuters wire alerts
- Anyone who unfollows accounts that lecture or panic

**Not** the audience: general public looking for climate education. Casual scrollers. People who want feel-good content. Activists looking for advocacy.

**The dashboard's user is exactly one person right now: the operator** (the project owner). It needs to be a tool they enjoy using daily, not a public-facing product. But a clean operator surface also doubles as evidence of taste — useful when opening to collaborators or showing the project to others.

---

## Brand identity goals

The Heat is the **planetary scoreboard**. The bot reports — it doesn't narrate. The brand should feel like:

- **Authoritative without lecturing.** Reuters wire authority, NASA mission patch credibility, Bloomberg Terminal density. Not academic. Not institutional. Confident in its facts.
- **Clear over clever.** The numbers do the work. Visual design supports the data, never competes with it.
- **Ambient menace, never panic.** The data is alarming. The brand acknowledges that without amplifying it. Earned editorial heat is allowed (per the recently-recalibrated voice spec — `EXTRAORDINARY`, `wild`, `Mind blowing` for elite signals only). Never `catastrophic`, `life-threatening`, `THIS IS SERIOUS` — those are weather-service boilerplate that numb readers.
- **Data-native.** Sparklines, sparkbars, monospace numbers, fine grids, status pills. The visual grammar should feel like reading an instrument panel. Charts should be possible without being decorative.
- **Globally legible.** The bot covers 179 countries; the brand can't read as American. Avoid stars-and-stripes coding, US-centric color metaphors (red/blue politics).
- **Scalable to a future newsletter / website / merch run.** Not so dashboard-specific that it can't extend.

What The Heat is **not**:
- Not climate activism. Not Greenpeace, not 350.org, not visual languages from advocacy.
- Not corporate climate-tech (no faux-innocent green gradients, no "earth pixel-art").
- Not weather-service press release (no orange severity bars, no NWS chrome).
- Not a "fun" bot. Personality comes from data framing, not from cute illustrations.

---

## Voice & tone (summary — see `brand/VOICE.md` for the full spec)

The bot reports, doesn't narrate. Punchy. Short sentences. Periods for emphasis. The personality comes from FRAMING — comparisons, era anchors, deadpan context — not from catchphrases.

Voice references the architecture spec calls out:
- @spectatorindex (just the fact, let people react)
- @unusual_whales (data-forward, dry)
- Reuters / AP wire alerts (clean, authoritative)
- Early @darth (deadpan, never tries hard)
- @extremetemps (the genre operator — ALL-CAPS openers and earned editorial heat are part of the genre)

**Earned editorial heat is allowed** for elite signals (all-time records, country-tier records, ≥18°C anomalies, ≥5-day streaks): `EXTRAORDINARY`, `stunning`, `wild`, `Mind blowing`, ALL-CAPS openers. Never on mid-tier signals. Never weather-service boilerplate (`HURRICANE-FORCE`, `catastrophic`, `life-threatening`, `dangerous conditions`). Never tell-don't-show meta-commentary (`THIS IS SERIOUS`, `you should be worried`).

Examples of the bot's voice (from the corpus):
- "Phoenix just dropped 121F. NEW RECORD. The old one was from last year."
- "Buenos Aires hit 42.1C. That broke a 97-year record set in 1929. Last time it was this hot there, the Great Depression hadn't started."
- "EXTRAORDINARY heat in the Sahel today. 47.2C in Mali, hottest in 28 years of records."
- "CO2 crossed 435 ppm at Mauna Loa. Pre-industrial was 280. We've added more CO2 since 1990 than in the previous 10,000 years."

The brand identity should give that voice a visual home. The wordmark should feel like the kind of voice that produces those tweets — confident, dry, sourced.

---

## Messaging architecture (summary — see `brand/MESSAGING_ARCHITECTURE.md` for the full spec)

**Tagline:** *The planet's scorecard.*

**Positioning:** The Heat is the account you follow because the data is always clear and often surprising, and then one day you realize you've accidentally become the most informed person in the room about climate.

**Core tension:** Everything is factually sourced from NASA, NOAA, and global weather systems. Delivered with dry confidence and enough context to land. The tension between "this is just the data" and "holy shit, that data" is the hook.

**Differentiator:** Most climate accounts either lecture or panic. The Heat just reports the numbers with enough context that they hit on their own. **No opinions needed. The data is the editorial.**

---

## Visual direction (locked decisions from this session)

Already validated through gstack-mockup direction-setting. Claude Design should treat these as constraints unless there's a strong reason to push back:

| Decision | Direction |
| --- | --- |
| Layout | Single-page command-center grid. Multi-panel, no nav rail, everything daily-use visible without scrolling on desktop. |
| Mobile | Phone-friendly fallback. Single-column stack, drafts first. Mostly desktop in practice. |
| Aesthetic | "Functional dark." Flat (less glass / less mood), monospace for metadata and scores, sans-serif for tweet text. Operator-console density without visual fatigue. |
| Tech foundation | Tailwind CSS + shadcn/ui, Next.js 15 + React 19, Vercel deploy. |
| Dark / light | Dark default. Light theme as a parallel set for future use. |

Things deliberately **out of scope** for the immediate brief:
- Newsletter design (eventually; not now — landing site Phase 3 includes a hook for it).
- Merch (eventually; not now).
- Bluesky / Threads / TikTok cross-posts (the brand should adapt naturally; full system extensions later).
- Non-dashboard internal tooling.

---

## Tech & implementation context

- **Stack.** Next.js 15 App Router + React 19, Vercel hosting, server-side API routes proxying a GitHub Gist for state. Auth via middleware (single passphrase).
- **Current state.** One 1735-line `dashboard/app/page.js` file with all UI inline, custom CSS via styled JSX. Will be refactored into composed components as the design system lands.
- **Implementation handoff path.** Claude Design output → Claude Code uses the design tokens + components to refactor the dashboard. Component-by-component, behind a feature flag, with `/dashboard-v2` route for early review.
- **Constraints we care about.** Accessibility (the dashboard is operator-only but should still be navigable by keyboard). Performance (poll every 30s, tweets and stats need to feel real-time). Mobile fallback.

---

## Reference materials in this folder

Two supporting docs, intentionally tight:

1. **`MESSAGING_ARCHITECTURE.md`** — positioning, tagline, voice references, personality, examples by tweet type. The single best document for understanding the brand soul.
2. **`VOICE.md`** — voice specification, golden set examples, and the recently-recalibrated "Earned Editorial Heat" section that defines what the bot is and isn't allowed to sound like.

Other context (engineering plans, virality research, voice patterns, codebase) is intentionally excluded — would muddy the brand decision. Ask if more context becomes useful after the first round of directions.

---

## Deliverables checklist (what we want back from Claude Design)

### Phase 1 — Brand identity (THREE directions)
For each of three directions:
- [ ] Wordmark (primary + monochrome + glyph)
- [ ] Color palette (dark primary + light variant + semantic alerts + heat-coded accent)
- [ ] Typography pairing (sans body + monospace data + optional ceremonial accent)
- [ ] Twitter avatar (400×400) + 32px and 16px legibility check
- [ ] Twitter banner (1500×500) + mobile-crop check
- [ ] Pinned tweet visual + copy candidate
- [ ] One applied dashboard panel (drafts list suggested)
- [ ] Direction notes — center of gravity, what it says about The Heat

After review and selection of one direction:
- [ ] Production-ready wordmark + glyph + favicon set (SVG + PNG, dark + light)
- [ ] Final color tokens (CSS vars + Tailwind theme config)
- [ ] Final typography stack with web-font sources
- [ ] One-page brand guidelines

### Phase 2 — Design system
- [ ] Token system (color / type / spacing / radius / elevation / motion) as CSS variables and Tailwind theme config
- [ ] Component library: Card, Button, Pill / Badge, Tabs, Score grid, Sparkline, Status indicator, Input, Modal, Toast, Empty state
- [ ] Pattern library: list-detail, metric tile, sparkline strip, log timeline
- [ ] Icon set selection + usage guidelines
- [ ] Dark + light themes both ready

### Phase 3 — Twitter profile + landing site
- [ ] Final avatar set (400×400, 200×200, 96×96, favicon)
- [ ] Final banner (1500×500, with mobile-crop variants if needed)
- [ ] Bio draft + pinned tweet visual + copy
- [ ] Landing-site flat — one page, mobile + desktop, sections: hero, what-is-this, sources, repo link, newsletter hook
- [ ] Domain branding for **theheat.ai** (apex, www handling, OpenGraph card)

### Phase 4 — Dashboard flats
- [ ] Home / Command Center (desktop, 1440 + 1280 breakpoints)
- [ ] Home (mobile, 375 width)
- [ ] Draft detail focus state
- [ ] Compose modal
- [ ] Generate trigger flow
- [ ] Empty / loading / error states for each major panel
- [ ] Hover and active interaction states

---

## Working notes for the designer

- The current dashboard at `https://dashboard-phi-beryl-65.vercel.app` is auth-protected (passphrase: `testtest`). Worth seeing the existing surface before redesigning.
- The voice work and corpus grading are very active — the dashboard should anticipate that future versions will surface `docs/DRAFT_CORPUS.md` content and signal trends, even if Phase 3 doesn't build those views yet.
- The bot's brand promise is *clear AND compelling* (per messaging architecture). Both halves matter. Don't sacrifice density for prettiness; don't sacrifice approachability for density.
- The single-operator context means we can lean into power-user density. We're not training new users.

---

*Brief drafted 2026-04-26. Update before each new design phase.*
