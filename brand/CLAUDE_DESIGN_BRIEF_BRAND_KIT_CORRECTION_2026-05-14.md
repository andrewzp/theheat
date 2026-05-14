# Claude Design Brief — @theheat Brand Kit Correction

**Date:** 2026-05-14
**Project:** @theheat (climate-data Twitter account)
**Scope:** Correct the positioning baked into the existing brand kit. The "climate data wire / logbook of a planet running a fever" framing was invented during the brand-book pass and does not match @theheat's canonical Purpose / Vision / Mission. **The visual system is correct.** The wordmark, mark, lockup geometry, palette, and typography all stay. What needs to change is positioning copy across the kit and the small number of over-designed visual surfaces that were built on top of the wrong positioning.

This brief has two parallel deliverables, both ship in the same pass:

- **Phase 1 — replace the over-designed visual surfaces** (Twitter banner, OG card, brand-book cover) with simplified versions.
- **Phase 2 — correct off-brief copy** on the rest of the kit (four brand-book sections, the usage guide intro, the operator dashboard mockup).

Phase 2 is not optional and not aspirational. It is the same correction Phase 1 makes, applied everywhere else the wrong framing lives. Without Phase 2, the simplified Phase 1 surfaces land in a brand kit that still contradicts them at every other touchpoint.

---

## 1. What @theheat is (read this first)

> **@theheat** is an automated climate desk that watches the entire planet every day and surfaces events extraordinary enough to deserve a stranger's attention. Each post pairs a precise, verifiable number with one calm sentence explaining the system that produced it — so the reader leaves slightly smarter about how the climate actually works, not just startled by another record. Over time, the feed becomes a quiet, trustworthy daily reading of the planet's vital signs.

**Purpose** — Make climate data impossible to ignore.

**Vision** — The most-followed climate account on the internet. Not because it lectures. Because the data is that striking when you actually present it clearly.

**Mission** — Turn real-time planetary data into content people understand, share, and talk about.

**Canonical tagline (use this; do not write a new one):** *Diary of a warming planet.*

Voice references for tone calibration: David Attenborough (calm expert observation, no flourish), The Economist (precise, data-as-load-bearing, trusts the reader), Reuters wire alerts (clean, authoritative, no padding).

---

## 2. The diagnosis — what's wrong with the current brand kit

The brand kit in the source zip (`The Heat - Brand Design _ Design System.zip`) was built around a fictional positioning that does not exist anywhere in the canonical messaging architecture. The cover of the brand book reads:

> *"A climate data wire. The brand is the reading: extraordinary numbers, plainly reported, sourced. Not amber. Not a dashboard. A logbook of a planet running a fever."*

That tagline isn't in the messaging architecture. Nobody approved it. It was invented during the brand-book design pass. And from that one sentence, an entire visual and verbal system was extruded — a "wire desk" metaphor, a fake newspaper masthead (`THE HEAT · CLIMATE DATA WIRE · VOL. I · NO. 138 · 26 APR 2026`), a "logbook, not a dashboard" framing rule, an operator dashboard called the "Wire Desk" with items tagged `WIRE-0142`, and a banner that bakes live data into a static PNG.

The visual system underneath all of this is correct. The wordmark, the thermometer mark, the lockup, the palette, the typography are all fine. **Only the positioning copy and the visual applications built on top of it (the banner, the OG card, the brand-book cover treatment) are wrong.**

Specifically, every instance of the following framings needs to leave the brand kit:

- `climate data wire` (and `CLIMATE DATA WIRE` masthead variants)
- `wire desk` (as a name for anything internal or external)
- `logbook` / `logbook of a planet running a fever` / `running a fever`
- `amber` (as a referenced concept)
- `not a dashboard` (the defining-by-negation pattern)
- `the brand is the reading`
- `editing the wire from inside it`
- The `WIRE-XXXX` ID prefix on draft cards
- The newspaper-pastiche `VOL. I · NO. 138 · [DATE]` masthead overlay
- The fake source-list meta line (`SOURCES · NOAA · NASA · ECMWF · USGS · GDACS · 9 MORE · UTC TIMES · CONFIDENCE TAGS ON EVERY POST`)
- Embedded live-data callouts on static assets (e.g. `54.4°C · FURNACE CREEK · 06:18 UTC` on the banner; `Kayes, Mali · 47.2°C` on the OG card)

The corrected positioning is the canonical Purpose / Vision / Mission / Tagline from §1 above. Everywhere the wrong framing currently appears, the correction either:

1. Replaces the wrong copy with the canonical tagline ("Diary of a warming planet.") and/or the one-sentence product description, or
2. Deletes the wrong copy entirely (e.g. the fake masthead overlay), or
3. Renames a structural element (e.g. "Wire Desk" → "Operator Dashboard").

---

## 3. Phase 1 — replace three over-designed visual surfaces

### 3.1 Twitter / X banner — light version (1500×500)

**Current state:** The banner shows a fake newspaper masthead (`THE HEAT · CLIMATE DATA WIRE`), volume/edition/date (`VOL. I · NO. 138 · 26 APR 2026`), a source list (`SOURCES · NOAA · NASA · ECMWF · USGS · GDACS · 9 MORE`), a station count (`11,907 STATIONS · 179 COUNTRIES · REFRESHED HOURLY` — the actual current number is 638 stations across 180 countries), the lockup centered, a tagline below (`Climate data, on the wire — every record, as it breaks.`), and a frozen-in-time live reading on the right (`HIGHEST READING · TODAY · 54.4°C · FURNACE CREEK · 06:18 UTC`).

**Replace with:** Just the horizontal lockup (mark + wordmark), centered or left-anchored with generous clear space. Optionally the canonical tagline "Diary of a warming planet." set small in Inter Regular ≤16px below the wordmark. **That's the entire banner.** No volume number. No edition. No source list. No station count. No live data reading. No "CLIMATE DATA WIRE" subhead. No "Climate data, on the wire" tagline.

**Background:** existing brand cream (#FAF6F0 / paper-white).
**Source files:** `handoff/svg/lockup.svg` for the lockup; `handoff/svg/wordmark.svg` if pure wordmark is preferred.

### 3.2 Twitter / X banner — reverse version (1500×500)

Same composition as 3.1 on dark ground (#16181B / `--ink`). Source: `handoff/svg/lockup-reverse.svg`.

### 3.3 Avatar (1500×500 → 400px and smaller)

**Current state:** Already correct — just the thermometer mark with the orange accent bulb on a cream circle.

**Action:** Verify only. Do not redesign. Confirm `mark-thermometer.svg` is the SVG source and that all four PNG sizes (48, 96, 200, 400) render cleanly.

### 3.4 OG card (1200×630)

**Current state:** A tweet-style data card showing `EXTRAORDINARY · SAHEL / Kayes, Mali / 47.2°C / +1.4°C above prev. record / Old record: 45.8°C, 1998 / SOURCE · MALI-MÉTÉO · OGIMET · 2026-04-26 06:42 UTC · CONF=HIGH`. Anyone sharing the @theheat profile or dashboard sees this frozen-in-April-2026 card as the link preview indefinitely.

**Replace with:** Just the lockup, centered, with the canonical tagline "Diary of a warming planet." set in Inter Regular below it. Two color treatments:
- Light ground (cream) — primary
- Dark ground (ink) — for dark-mode shares

No masthead, no volume/edition, no specific data point. Source: `handoff/svg/lockup.svg` and `handoff/svg/lockup-reverse.svg`.

### 3.5 Brand book cover

**Find** (in `handoff/Brand Book.html`):

```
<p class="tagline">A climate data wire. The brand is the reading: extraordinary numbers, plainly reported, sourced. Not amber. Not a dashboard. A logbook of a planet running a fever.</p>
```

**Replace with:**

```
<p class="tagline">Diary of a warming planet.</p>
```

**Cover gets ONLY the wordmark + tagline + book metadata footer.** No sub-deck, no descriptor, no "An automated climate desk…" line. If the previous brand book had a `.sub` element under `.tagline`, remove it entirely. The cover is calm and minimal — anything beyond wordmark + tagline is overproduction.

---

## 4. Phase 2 — correct off-brief copy across the rest of the kit

Copy corrections only. No redesign. Six surfaces.

### 4.1 Brand Book §02 COLOR deck

**Find:**

```
Mostly neutral. One warm accent, applied only where a number needs emphasis. The page is a logbook, not a dashboard — if you find yourself adding a second hue, the layout is wrong.
```

**Replace with:**

```
Mostly neutral. One warm accent, applied only where a number needs emphasis. The accent earns its place once per surface — on a value that matters. If you find yourself adding a second hue, the layout is wrong.
```

### 4.2 Brand Book §07 TWITTER section

This page mocks up the @theheat profile composite — banner, avatar, bio, and a pinned tweet sample. Three separate corrections.

**a) Banner mockup.** Rebuild to show the simplified banner from §3.1 (lockup + tagline, nothing else). Remove the source-list meta line (`SOURCES · NOAA · NASA · ECMWF · USGS · GDACS · 9 MORE · UTC TIMES · CONFIDENCE TAGS ON EVERY POST`) entirely.

**b) §07 deck.** Find:

```
Profile composite. The brand fights for the thumb-stop on the avatar and banner; the body fights with copy alone.
```

Replace with:

```
Profile composite. The avatar and banner are the masthead — a single lockup + tagline, nothing else. Everything that makes the brand specific (the data, the sources, the time-stamping, the confidence flags) lives in the tweets themselves, not the chrome.
```

**c) Sample bio inside the profile mockup.** Find:

```
Climate data, on the wire. Records, anomalies, readings from 11,907 stations satellite data. Every post sourced. UTC times.
```

Replace with:

```
Diary of a warming planet. Records, anomalies, and readings from across the climate system. Every post sourced. UTC times.
```

(Drop the inflated `11,907 stations` count entirely — the bio doesn't need a station number, and the actual count is 638 anyway.)

**d) Sample pinned tweet inside the profile mockup.** Find:

```
A wire service for a planet running a fever. Every post is a record, an anomaly, or a reading that crossed a line — sourced, time-stamped, in plain language. Quiet by default. Loud when the data is.
```

This is the single biggest hit in the brand book — a sample pinned tweet that teaches the wrong voice. Replace with a real Attenborough/Economist-style sample that demonstrates the corrected voice:

```
This is a record of the planet's vital signs. Every post pairs an exact, sourced number with one sentence on the system behind it — the western Pacific warm pool, the Sahel dry season, the cold-air drainage in a topographic bowl. Calm by default. The data carries the weight.
```

**e) Avatar overflow / positioning in the profile composite.** The previous delivery shipped with the avatar (thermometer mark on cream circle) positioned awkwardly — partially overflowing the banner edge or sitting at an incorrect Y position. On real Twitter, the avatar sits centered on the banner's bottom edge so exactly half is on the banner and half is on the profile body below. The mockup must reflect this layout faithfully:

- A complete circle (not cropped or cut off)
- Centered vertically on the banner/profile-body boundary line
- Clear separation between avatar edge and surrounding chrome (no overlap with text)
- Drop shadow or border treatment optional but consistent with real Twitter conventions

Render the avatar correctly in the mockup. Verify by looking at the rendered image (see §7 visual self-review).

### 4.3 Brand Book §08 DASHBOARD deck

**Find:**

```
Andrew uses this every day. Same masthead, same dateline, same source-line conventions as the public-facing brand — the brand is the workflow. Editing the wire from inside it.
```

**Replace with:**

```
Andrew uses this every day. Internal editorial console — pending drafts, suppressions, source health. Functional first; the typography and accent system are inherited from the public brand, but the dashboard is tooling, not masthead. No volume number, no edition, no public-facing flourish.
```

### 4.4 Brand Book §09 TWEET SYSTEM

The "brand-render vs. timeline-render" comparison structure is correct and instructive — keep it. The two sample tweets currently in the section (Kayes Mali heat record + Mauna Loa CO₂) are actually well-voiced — keep both verbatim except for the corrections below.

- **Replace stale dates.** The sample data is dated `2026-04-26` everywhere. Replace specific dates with `[DATE]` or `[UTC TIMESTAMP]` placeholders so the page doesn't age out.
- **Replace inflated station counts.** `OGIMET 11907` in the Kayes Mali sample meta line — `11907` is a stale station-network count. Replace with `[STATION ID]` or the real station identifier if available.
- **Keep the metadata lines** (`SOURCE · MALI-MÉTÉO · OGIMET · [UTC TIMESTAMP] · CONF=HIGH`). Source attribution, time-stamping, and confidence flags belong on the editorial surface — just not on the banner.

**Replace the §09 deck:**

Find:
```
Every tweet has both beats: the data point and one sentence of real consequence — body, infrastructure, ecosystem, future. Each shown two ways: brand-render (left, owned surface) vs. timeline-render (right, plain text).
```

Replace with:
```
Every tweet pairs a precise data point with one calm sentence explaining the system that produced it. Two renderings shown: brand-render (left, owned surface — for embed, blog, screenshot) vs. timeline-render (right, plain text as it appears in the Twitter feed).
```

**Note the back-reference:** §09 ends with *"Six more samples in The Heat - Brand Directions Round 3 v4.html §06."* If that file is in scope and accessible, those six additional samples should be checked for the same wrong-voice / wrong-tagline issues. If the file isn't accessible, flag this in your delivery notes so the user can audit it separately.

### 4.5 Usage Guide intro deck

**Find** (in `handoff/Usage Guide.html`):

```
A climate data wire. The brand is the reading: extraordinary numbers, plainly reported, sourced. Not amber. Not a dashboard. A logbook. Use this when you're about to post, design a card, or pick a color.
```

**Replace with:**

```
Diary of a warming planet. Use this guide when you're about to post, design a card, or pick a color.
```

### 4.6 Brand Book — running header on every page

Every one of the 10 brand-book pages has a running header at the top reading:

```
THE HEAT · CLIMATE DATA WIRE   BRAND BOOK · v1.0   §XX · [SECTION NAME]
```

The `CLIMATE DATA WIRE` subhead is wrong on every page. Find-and-replace it across all 10 pages:

`THE HEAT · CLIMATE DATA WIRE` → `THE HEAT`

(or, if the running header benefits from a subhead to mirror the brand-book context: `THE HEAT · BRAND BOOK` — but a clean single-line `THE HEAT` is preferable and matches the simplified social masthead approach.)

### 4.7 Inflated station-count cleanup

The number `11,907` appears in multiple places as a fake station-count:

- Banner (`11,907 STATIONS · 179 COUNTRIES · REFRESHED HOURLY`) — already addressed by §3.1's replacement.
- §07 Twitter bio sample (`Records, anomalies, readings from 11,907 stations`) — addressed by §4.2(c).
- §09 sample-tweet meta line (`OGIMET 11907`) — addressed by §4.4.

The actual current count is **638 stations across 180 countries**. The number changes as we add cities; the brand kit should not hard-code any specific count in static assets. If a station/country count is genuinely needed somewhere, use `[STATION COUNT]` / `[COUNTRY COUNT]` placeholders. Better yet: don't reference station counts in the brand kit at all — that's product-page territory, not masthead territory.

### 4.8 Operator Dashboard mockup

Copy corrections only — the typography, tables, accent system, and layout are all correct for an editorial console. Five literal find-and-replaces:

**a) HTML title:**

```html
<title>The Heat — Operator Dashboard (Wire Desk)</title>
```
becomes:
```html
<title>The Heat — Operator Dashboard</title>
```

**b) Top header subtitle:**

`WIRE DESK · 1440 × n · STANDALONE REFERENCE`
becomes:
`OPERATOR DASHBOARD · 1440 × n · STANDALONE REFERENCE`

**c) Hero block:**

```html
<h1>The wire desk.</h1>
<p>Andrew uses this every day. Same masthead, same dateline, same source-line conventions as the public-facing brand — the brand is the workflow. Editing the wire from inside it.</p>
```
becomes:
```html
<h1>The operator dashboard.</h1>
<p>Andrew uses this every day. Pending drafts, suppressions, source health, daily quality grading. Internal editorial console — the public brand's typography and accent system carry through; the masthead conventions do not. Tooling, not pastiche.</p>
```

**d) Card / item ID prefix:**

`WIRE-0142 → DRAFT-0142`
`WIRE-0141 → DRAFT-0141`
(and any other `WIRE-XXXX` instances in the file)

**e) Header masthead inside the dashboard mockup:**

`THE HEAT · CLIMATE DATA WIRE`
becomes:
`THE HEAT · OPERATOR DASHBOARD`

---

## 5. Brand DNA to preserve (do NOT change)

These elements are correct and load-bearing. Carry them forward unchanged across both phases:

- **Wordmark.** Inter SemiBold, set tight (−0.022em letter-spacing). `handoff/svg/wordmark.svg` and variants.
- **Mark.** Thermometer with a single accent bulb in orange/red (#C2410C). `handoff/svg/mark-thermometer.svg`.
- **Lockup geometry.** Horizontal only. Mark height = wordmark cap-height × 1.6. Mark-to-wordmark gap = wordmark cap-height × 0.55. Clear space = bulb diameter on every side.
- **Color palette.** Ink `#16181B`, paper `#FAF6F0`, accent `#C2410C`, plus the existing muted gray for `--ink2`.
- **Typography stack.** Inter for wordmark and body; the existing mono (JetBrains Mono or similar) for monospaced detail accents — but minimized or absent on the simplified Phase 1 surfaces (banner, OG card, brand-book cover).
- **Avatar + favicons.** Already correct. Keep.
- **Brand-book section structure.** Ten numbered sections (Cover, §01–§09). The structure stays; only specific decks and the cover tagline change.
- **§09's brand-render vs. timeline-render comparison structure.** Useful and correct; keep the layout.

---

## 6. Hard constraints — what NOT to produce

Across both phases:

- **No "CLIMATE DATA WIRE" subhead anywhere.** Not on the banner. Not on the OG card. Not in any brand-book section header. Not in the dashboard mockup masthead.
- **No "wire desk."** Not as a name, not as a metaphor, not as an ID prefix.
- **No "logbook" / "running a fever" / "amber" / "not a dashboard"** anywhere in the kit.
- **No "the brand is the reading"** or any meta-design abstraction about what the brand "is" to itself.
- **No volume / edition / issue numbers** on any static surface (`VOL. I · NO. 138 · [DATE]`). The banner is not a newspaper masthead. Neither is the brand-book cover.
- **No live data readings embedded in static assets.** No `54.4°C · FURNACE CREEK` on the banner. No `Kayes, Mali · 47.2°C` on the OG card.
- **No source list on the banner.** Sources belong on the website/about page, not on the masthead chrome.
- **No station count / country count on the banner.** These numbers change and don't earn the visual real estate.
- **No new tagline.** The canonical tagline is "Diary of a warming planet." — use it verbatim. Do not invent variants, alternates, or "improvements." Do not invent sub-decks, descriptors, or any additional copy below the tagline.
- **No emoji, no hashtags, no exclamation points** anywhere in any asset copy.
- **No defining-by-negation.** No "not amber. not a dashboard." If a quality is worth naming, name what the brand IS.
- **No net-new branding.** No new positioning, no new color, no new mark, no new typography, no new layout principles.

---

## 7. What "done" looks like

When you ship the corrected kit, the user should be able to:

1. **Upload the new banner to the @theheat X profile** and have it look like a quiet, confident masthead — lockup + tagline, nothing else.

2. **Have any shared @theheat link** render a clean OG preview that's brand-shaped (lockup + tagline) rather than content-shaped (a specific tweet's data card).

3. **Hand a new contributor the brand book** and have them read the cover and immediately understand the product without needing internal context to parse "logbook of a planet running a fever."

4. **Open the operator dashboard mockup** and read it as an editorial console (which is what it is) rather than as wire-desk pastiche.

### Visual self-review protocol — MANDATORY before delivery

The first delivery shipped with the wrong tagline still in place and a visible avatar-overflow issue in the §07 profile composite. Both would have been caught by actually looking at the rendered output. From this delivery forward, every asset must pass this protocol before being considered complete:

1. **Render the asset.**
2. **View the rendered image with your image-viewing capability.** Actually look at it, not just check the source.
3. **Run the relevant visual checklist below against the rendered image.**
4. **If any item fails, identify specifically what's wrong** — quote the failing item, describe the visual issue.
5. **Fix the issue and re-render.**
6. **Repeat from step 2 until every checklist item passes.**
7. **In your delivery notes, report which assets passed, on which iteration, what failed on earlier iterations, and the final grep results.**

If you skip the visual self-review and the delivery has visible bugs, the work has to be redone. The protocol exists to eliminate that loop.

#### Visual checklist — every visual asset (banner, OG card, brand-book cover, brand-book mockups)

- Tagline reads exactly `Diary of a warming planet.` (period included, capitalization as shown). No `The planet's scorecard.`, no older variants.
- Wordmark renders correctly — not truncated, not stretched, not pixelated.
- Thermometer mark is fully visible inside its container — not cropped, not cut off, not overflowing edges.
- Lockup geometry: mark height = wordmark cap-height × 1.6; mark-to-wordmark gap = wordmark cap-height × 0.55.
- Clear space around the lockup is at minimum the bulb diameter on every side.
- Background is the expected color — cream `#FAF6F0` for light surfaces, ink `#16181B` for dark.
- Accent color `#C2410C` appears only on the thermometer bulb. No other element uses the accent.
- No text is truncated or cut off at any edge.
- No unintended layout shift, asymmetry, or overflow.

#### Visual checklist — Brand Book (all 10 pages)

In addition to the above:

- Every page's running header reads `THE HEAT` (not `THE HEAT · CLIMATE DATA WIRE`).
- Cover shows `Diary of a warming planet.` as the tagline.
- **Cover has NO sub-deck.** Just wordmark + tagline + book metadata footer. No "An automated climate desk that surfaces events…" or any other descriptive line below the tagline.
- §07 Twitter mockup shows the simplified banner (lockup + tagline only) and the avatar sits cleanly centered on the banner/profile-body boundary (see §4.2(d) for the avatar-overflow fix).
- §07 Twitter mockup bio reads exactly: `Records, anomalies, and readings from across the climate system. Every post sourced. UTC times.` (no tagline restatement at the start)
- §07 Twitter mockup pinned tweet does not contain `wire service`, `planet running a fever`, or other off-brief framing.
- §09 sample tweets use `[DATE]` or `[UTC TIMESTAMP]` placeholders instead of hardcoded `2026-04-26`.
- §09 sample tweets use `[STATION ID]` placeholder instead of inflated `OGIMET 11907`.
- Cover metadata (`FORMAT · N PAGES · LETTER`) accurately reflects the actual page count of the corrected book.

#### Visual checklist — Operator Dashboard mockup

- HTML `<title>` reads `The Heat — Operator Dashboard` (no `Wire Desk`).
- Hero `<h1>` reads `The operator dashboard.` (no `wire desk`).
- Top header subtitle reads `OPERATOR DASHBOARD · 1440 × n · STANDALONE REFERENCE` (no `WIRE DESK`).
- All item ID prefixes are `DRAFT-XXXX` (no `WIRE-XXXX`).
- Internal dashboard masthead reads `THE HEAT · OPERATOR DASHBOARD` (no `THE HEAT · CLIMATE DATA WIRE`).
- Hero deck describes the dashboard as an internal editorial console (no `editing the wire from inside it`, no `the brand is the workflow`).

### Final grep check — required before delivery

After all assets are rendered and visually reviewed, run a literal text search on the final HTML files for these strings. Any hit means the correction is incomplete and must be fixed before delivery:

```
climate data wire
wire desk
logbook
running a fever
amber
not a dashboard
the brand is the reading
editing the wire from inside it
WIRE-
The planet's scorecard
the planet's scorecard
A climate data wire
Climate data, on the wire
A wire service for a planet running a fever
An automated climate desk
an automated climate desk
```

All 16 strings must return zero matches. The "automated climate desk" line was an unapproved sub-deck from an earlier iteration of this brief — it must not appear on the cover, in the usage guide, or anywhere else in the kit.

Report the grep results in your delivery notes — something like:

> *"Grep results: 0 matches for all 16 banned strings. Tagline `Diary of a warming planet.` confirmed present in: banner-light, banner-reverse, og-card-light, og-card-dark, brand-book-cover, brand-book-§07-banner-mockup. Bio confirmed updated (no tagline restatement). Cover confirmed clean (wordmark + tagline only, no sub-deck). Avatar in §07 mockup renders correctly centered on banner edge. All visual checklist items pass."*

Any hit means the correction is incomplete. The grep-self-test plus the visual self-review are both verification steps before delivering.

---

## 8. Reference files

All source assets and current state live in the handoff directory inside the brand zip:

- `handoff/Brand Book.html` — cover tagline + four section decks need correction (§3.5, §4.1, §4.2, §4.3, §4.4)
- `handoff/Operator Dashboard.html` — five copy corrections (§4.6)
- `handoff/Usage Guide.html` — intro deck (§4.5)
- `handoff/svg/` — SVG primitives (lockups, wordmarks, marks). Use these as sources; do not redraw.
- `handoff/png/banner-light-1500x500.png` — REPLACE (§3.1)
- `handoff/png/banner-reverse-1500x500.png` — REPLACE (§3.2)
- `handoff/png/og-card-1200x630.png` — REPLACE (§3.4)
- `handoff/png/avatar-*.png` — KEEP, verify only (§3.3)
- `handoff/png/favicon-*.png` and `apple-touch-icon.png` — KEEP, verify only

For canonical voice / messaging context if needed, the project's `brand/MESSAGING_ARCHITECTURE.md` is authoritative. The Purpose / Vision / Mission / Tagline at the top of that file are canonical. MA was updated in the same pass as this brief (2026-05-14) to remove all stale "climate data wire service" framing — if you find any conflict between MA and this brief, ping the user, do not invent a resolution.

---

## 9. Open questions worth flagging (NOT in scope here)

Two visual decisions the corrected positioning eventually raises but that this brief deliberately does NOT touch. Both deserve their own future pass once the pipeline is producing consistent quality and the brand has more usage data. Surface them to the user in your delivery notes; do not act on them.

### 9.1 The thermometer mark

The brand currently covers fires, CO₂, ice mass, drought, marine waves, severe weather, river floods, sea ice, and ENSO transitions — not just temperature. A thermometer mark commits the visual identity to *temperature* as the anchor when the actual product is *all of the planet's vital signs*. The Economist has no thermometer; Attenborough has no logo at all (the work is the identity). The thermometer is the most legible single-image proxy available right now, but it under-represents what @theheat is.

**For this pass:** keep the thermometer mark. No edits.
**Flag for future:** a v2 brand evolution might explore a mark that reads as *planetary instrument* rather than *thermometer* — possibly something derived from the seismograph, the rain gauge family, or simply a refined typographic mark with no glyph.

### 9.2 The orange accent applied to all "values that matter"

The current accent rule says #C2410C goes on the value the reader's eye should land on. Visually, that reads as *heat*. When the brand-render template prints a cold record (Bethel May low at 28°F, Verkhoyansk Arctic cold) in heat-orange, the color subtly miscues the reader. The semantic load of the accent is "look here" — but the color doesn't know that.

**For this pass:** keep the single-accent rule and the orange. No edits.
**Flag for future:** consider whether the accent should split into a small palette tied to data class (hot-value warm, cold-value cool, neutral-value mono) or remain a single "this is the headline number" emphasis regardless of polarity. Either decision is defensible; the current state is the one that needs deciding, not changing.

---

## 10. Out of scope (genuinely)

These are out and get their own future work:

- The product UI itself (the @theheat dashboard at the Vercel URL — that's a separate engineering project)
- Tweet-card templates (for in-tweet imagery, if/when those are added)
- Print collateral
- Animated / motion versions of the lockup
- Any net-new branding (no new tagline, no new positioning, no new color, no new mark, no new typography)
- The mark and accent questions flagged in §9 (NOT in scope here)

Subtraction is the goal everywhere in this pass.
