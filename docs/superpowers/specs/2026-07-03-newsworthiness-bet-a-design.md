# Design — Newsworthiness & sourced human-impact ("Bet A")

- **Date:** 2026-07-03
- **Status:** 🟡 **BRAINSTORM IN PROGRESS — resume here.** 3 of ~5 clarifying
  questions answered (decisions locked below). NOT yet a completed/approved spec.
  Do NOT implement — finish the brainstorm → approaches → design → spec → writing-plans.
- **Skill in flight:** `superpowers:brainstorming` (paused after Q3).
- **Owner decision:** Andrew chose **Bet A** ("make autonomous selection smart") over
  Bet B ("assistant / human-curated").

---

## Why this exists (the problem)

@theheat ranks signals by **raw sensor magnitude** (megawatts, °C anomaly) and is
**blind to newsworthiness and human stakes**. Two real failures on 2026-06-29/30:

1. **Congo vs Colorado (a ranking failure).** The bot **posted** *"1,468 MW of radiative
   heat in the Congo Basin, DR Congo"* while **suppressing** the deadly Colorado/Utah
   fires (scored **62 < the 64 cutoff**) that killed 3 firefighters and led the
   Washington Post. It surfaced a remote big number and filtered out the front-page
   catastrophe. Even the one Western fire it drafted was *"595 MW in the Rocky Mountains,
   Colorado"* — a lonely pixel, never "79 fires, 10 states, 3 dead."
2. **The European heat deaths (a coverage gap).** WHO reported **1,300+ excess deaths**
   (≈1,000 in France). The bot has **no mortality signal at all** — that story has zero
   path into the pipeline. The reganom heat *anomaly* tweet can't carry it (anomaly data
   only; the death toll is sourced news past the writer model's knowledge cutoff).

**Bet A's thesis:** give the bot an external, *sourced* sense of "what is actually
happening in the world" so it (a) tweets the stories that matter and (b) carries the
human stakes — without ever inventing a figure.

## THE IRON CONSTRAINT (non-negotiable, applies to every part)

Every newsworthiness/impact fact MUST come from **real, cited retrieval** — a named
source with a URL and an as-of date — **never the model's imagination**. Current news is
past the writer model's knowledge cutoff; a hallucinated death toll is the one
unforgivable error, far worse than a boring or missed tweet. Citation + verify-against-
source + the human review gate are mandatory throughout.

---

## Locked decisions (from the brainstorm, 2026-07-03)

1. **Source of newsworthiness = HYBRID.** Curated authoritative feeds for the big
   verticals (e.g. **NIFC** for US fire, **WHO / Santé publique France** for heat
   mortality, **NWS/NHC** for storms) **PLUS grounded LLM search** (Gemini
   google-search grounding — already in-stack) for the long tail. Start with 1–2 clean
   feeds + grounded search; widen over time. Feeds are clean/citable but narrow; grounded
   search is broad but noisy and leans hardest on verify-against-source.

2. **v1 scope = RE-RANK + ENRICH (not new-coverage-trigger yet).** For events the bot
   **already detects**: (a) **boost** them by newsworthiness so the Colorado fire beats
   the Congo one, and (b) **attach sourced human-impact** so the tweet carries "3
   firefighters killed," not just "595 MW." Bounded risk (reordering/annotating verified
   signals, not inventing them). The "trigger coverage of events we have no sensor for"
   (pure death-toll stories) is an explicit **fast-follow (v2)**, deferred to keep v1
   from becoming a money sink.

3. **Boost power = RESCUE, CAPPED.** A strong, sourced newsworthiness match can pull a
   **below-threshold** detected signal back into contention (the Colorado fire at 62<64
   drafts because the world says it's a major deadly event) — **but capped**: bounded
   score boost, a **real cited source required**, never below a hard floor. "The data is
   still required; the news decides which real data leads." (Not "reorder-only," which
   wouldn't have saved the Colorado fire; not "strong override," which inverts the bot's
   data-first identity.)

---

## Open questions (RESUME the brainstorm from Q4)

Ask one at a time, multiple-choice preferred:

- **Q4 — Autonomy for impact tweets.** Even with the autoship expansion (records now
  auto-post), should tweets carrying **sourced human-impact / death tolls** auto-post on
  a critic PASS, or stay **manual_only** (human-gated)? *Recommendation: manual_only* —
  they're life-safety-adjacent (like cyclones) and carry the highest hallucination stakes;
  keep a human in the loop for v1. Confirm.
- **Q5 — MVP feeds.** Which 1–2 authoritative feeds to wire first? *Recommendation:
  **NIFC** (US fire — fixes the Colorado case, structured/reliable) + **grounded search**
  for heat mortality (WHO/SpF don't expose a clean machine feed; grounded search with
  strict verify-against-source is the pragmatic start).* Confirm / adjust.
- (Then) **verification mechanism** detail — how a claim is checked against its source
  (fetch the URL + LLM match, or structured-field match for feeds); the deterministic
  gate that requires source+as_of and kills a source-less impact claim.

## Draft approaches (to present after Q4/Q5 — not yet proposed to Andrew)

A newsworthiness/impact **lane** (`src/data/newsworthiness.py` or
`src/editorial/newsworthiness.py`) that, per cycle, retrieves current major events
(hybrid source) → normalizes to `{event, where, when, magnitude/impact, source_name,
url, as_of}` → and produces two outputs:

- **A. Boost map (re-rank):** match retrieved events to the cycle's detected signals
  (place + category + window fuzzy-match) and emit a capped score boost applied in
  scoring/triage (rescues the Colorado fire). Candidate seams: `src/orchestrator/triage.py`
  (per-cycle selection/caps), the editorial score in `src/editorial/scoring/`.
- **B. Human-impact attachment (enrich):** attach a `human_impact: [{claim, value,
  source_name, url, as_of}]` field to the matched signal's StoryBundle. Writer may cite
  it **only with attribution, only from that field**; fact-check verifies it against the
  source and KILLS a source-less impact claim; life-safety framing (no alarmism).
  (This is IDEAS.md item #10, "Sourced anecdotes / human-impact with citations.")

Present 2–3 concrete variants (e.g. "boost-only v1 vs boost+enrich v1"; grounded-search-
first vs feed-first) with tradeoffs + a recommendation, then design sections, then spec.

## Prior art to READ before designing (check-dormant-before-building)

- **[docs/superpowers/specs/2026-06-25-coverage-monitor-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-06-25-coverage-monitor-design.md)**
  — "Heat coverage watch (geographic representativeness)," Proposed v2, awaiting Andrew's
  review. Sibling problem (the bot ran US-only for ~7 weeks, blind to a European
  heatwave). It's a *monitoring* approach (per-event geography → rolling tally → gap
  alert), NOT newsworthiness scoring, but overlaps Bet A's "are we missing an event?"
  instinct and has a codex-reviewed decision log worth reusing. **Reconcile Bet A with
  it — don't reinvent.**
- **IDEAS.md → "⭐ Requested — wanted, NOT parked"** (local/untracked
  [docs/IDEAS.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/IDEAS.md)): items #9
  (weather-news "are we missing it?" scanner) and #10 (sourced anecdotes with citations)
  — these ARE the two halves of Bet A. Full sketches live there.
- **Existing sourced-impact lane:** the bot already ingests **GDACS** ([src/data/gdacs.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/gdacs.py))
  and Copernicus EMS with a disasters intern — a real precedent for pulling sourced
  human-impact (affected populations, alert tiers). Heat-mortality isn't a GDACS type,
  but the pattern (sourced impact → bundle → attributed writer citation) is the template.
- **No grounded search exists yet** — this is net-new infra (Gemini `google_search`
  grounding tool; the fact-check + critic already use Gemini).

## Terminal step

Finish brainstorm → invoke **`superpowers:writing-plans`** (the ONLY skill after
brainstorming) → codex-xhigh the plan (cross-model outside review) → subagent-driven
build → codex the diff → ship behind a default-OFF repo variable (like every other
lane), verify with the live dispatch harness pattern, then flip on.
