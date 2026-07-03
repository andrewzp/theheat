# Design — Newsworthiness & sourced human-impact ("Bet A")

- **Date:** 2026-07-03 (brainstorm resumed and completed 2026-07-03 evening session)
- **Status:** 🟢 **DESIGN COMPLETE — awaiting Andrew's review of this spec.** All five
  brainstorm decisions are resolved (3 locked live with Andrew; Q4/Q5 adopted from the
  documented recommendations he directed the session to resume from — flagged inline).
  Next step after his review: `superpowers:writing-plans` → codex-xhigh → build behind
  default-OFF flags.
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
   catastrophe.
2. **The European heat deaths (a coverage gap).** WHO reported **1,300+ excess deaths**
   (≈1,000 in France). The bot has **no mortality signal at all** — that story has zero
   path into the pipeline.

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

## Decisions (all five resolved)

1. **Source of newsworthiness = HYBRID** *(locked with Andrew 2026-07-03)*. Curated
   authoritative feeds for the big verticals PLUS grounded LLM search (Gemini
   `google_search` grounding — Gemini is already in-stack for fact-check/critic) for the
   long tail. Feeds are clean/citable but narrow; grounded search is broad but noisy and
   leans hardest on verify-against-source.

2. **v1 scope = RE-RANK + ENRICH** *(locked with Andrew 2026-07-03)*. For events the bot
   **already detects**: (a) **boost** them by newsworthiness so the Colorado fire beats
   the Congo one, and (b) **attach sourced human-impact** so the tweet carries "3
   firefighters killed," not just "595 MW." The "trigger coverage of events we have no
   sensor for" (pure death-toll stories) is an explicit **fast-follow (v2)**.

3. **Boost power = RESCUE, CAPPED** *(locked with Andrew 2026-07-03)*. A strong, sourced
   newsworthiness match can pull a **below-threshold** detected signal back into
   contention — but capped: bounded score boost, a real cited source required, never
   below a hard floor. "The data is still required; the news decides which real data
   leads."

4. **Autonomy for impact tweets = manual_only, enforced by content not type**
   *(adopted from the documented recommendation; confirm at spec review)*. Any draft
   whose text cites a `human_impact` fact is **forced `manual_only`** regardless of its
   signal type — including record types that #352 made auto-shippable. Death tolls and
   fatalities are life-safety-adjacent (like cyclones) and carry the highest
   hallucination stakes; a human stays in the loop for every impact-carrying tweet in
   v1. A record draft that does NOT cite impact keeps its #352 autoship eligibility —
   the rule keys on what the tweet *says*, not what lane produced it.

5. **MVP sources = NIFC (US fire feed) + grounded search (heat mortality)**
   *(adopted from the documented recommendation; confirm at spec review)*.
   - **NIFC** is structured and reliable, and directly fixes the Colorado case —
     but note (codex-verified): the bot's existing WFIGS fetch requests only
     name/complex/size/state/dates/IDs; `FireComplex` carries **no
     fatality/personnel/PL fields** today. The newsworthiness leg therefore needs
     its **own field contract, verified at A0 build time** (exact endpoint +
     `outFields` + a sample payload — WFIGS exposes more fields than we request;
     the NIFC Sit Report carries PL). Any impact figure NIFC does not expose
     machine-readably (e.g. firefighter fatalities) routes through the
     grounded-search + verify lane instead — `structured` confidence is claimed
     only for fields actually fetched from the feed.
   - **Grounded search** covers heat mortality (WHO / Santé publique France publish no
     clean machine feed) and the global long tail. Highest-risk lane → strictest
     verification (below).

## v1 scope

**In:**
- A per-cycle newsworthiness retrieval lane (NIFC + grounded search) → normalized,
  cited `NewsEvent` list persisted in state.
- **Boost (re-rank):** capped, source-required rescue applied fire-first at the score
  gate; Colorado-class near-misses clear the bar.
- **Enrich:** `human_impact[]` on matched StoryBundles; writer may cite it only with
  attribution; fact-check + deterministic gates enforce; impact-citing drafts forced
  `manual_only`.
- **Gap flag (read-only miss-detector):** a major news event that matches *nothing* the
  bot detected opens an advisory auto-closing GitHub issue (reuses the sentinel
  machinery — same pattern as coverage-watch/yield-watch). No drafting from it in v1;
  it is the "are we missing an obvious event?" alarm from IDEAS.md #9, at zero
  editorial risk.
- Default-OFF flags throughout; live dispatch verification; then flip on.

**Out (v2 fast-follows, explicitly deferred):**
- New-coverage-trigger (drafting a story the sensors never saw — the pure death-toll
  tweet). The gap flag collects the evidence for whether/when to build it.
- Feeds beyond NIFC (WHO EURO surveillance, NWS/NHC as *news* inputs, ReliefWeb when
  the appname is approved).
- Boost on classes beyond fire (heat records already pass their gates; extend after
  fire proves the mechanism).

## Architecture

One lane, two consumers, five gates. New code in `src/data/newsworthiness.py`
(retrieval + normalization) and `src/editorial/newsworthiness.py` (matching + boost).

### 1. Retrieval (per alerts cycle, cycle start)

```
NewsEvent = {
  "kind": "fire" | "heat_mortality",          # v1 verticals
  "headline": str,                             # short factual label
  "place": {"country": str, "admin1": str|None, "name": str|None},
  "window_start": str, "window_end": str,      # ISO dates the event spans
  "impact": [ {"claim": str,                   # e.g. "3 firefighters killed"
               "value": float|int|str,         # the load-bearing figure
               "source_name": str,             # "NIFC", "WHO", "France24"
               "url": str, "as_of": str} ],    # citation, mandatory
  "retrieved_via": "feed:nifc" | "grounded_search",
  "confidence": "structured" | "verified" | "unverified",
}
```

- **NIFC leg:** a **new fetch with its own field contract** (the existing WFIGS
  plumbing requests only name/complex/size/state/dates/IDs — see decision 5; no Sit
  Report fetch exists today). A0 verifies the exact endpoint + `outFields` + a
  sample payload first; only fields actually returned by the feed (e.g. large-fire
  counts; PL if the Sit Report exposes it machine-readably) become
  `confidence="structured"` with the API URL as citation. Impact figures the feed
  does not expose (e.g. firefighter fatalities) route through the grounded-search +
  verify lane. No LLM anywhere in this leg.
- **Grounded-search leg:** one Gemini `google_search`-grounded call per cycle with a
  fixed prompt ("major heat-mortality and extreme-weather impact reports in the last
  72h, with figures, sources, dates"), parsed to `NewsEvent`s with grounding-metadata
  URLs. Everything arrives `confidence="unverified"` until the verification step
  promotes it.
- Persisted to `state["news_events"]` (rolling window, merge-spec entry, pruned like
  `coverage_log`) so the dashboard can show what the bot believes the world is saying
  and the gap flag can compare across cycles.
- Retrieval failure = the lane reports `degraded` in source-health like any other
  source and the cycle proceeds WITHOUT news (never blocks drafting; boost/enrich just
  don't fire). No silent failure: it's a source row, sentinel-visible.

### 2. Verification ladder (before any consumer sees an entry)

- `confidence="structured"` (NIFC): trusted as-is — the figure IS the feed field; the
  citation is the API response we fetched this cycle.
- `confidence="unverified"` (grounded search): a **separate** verify step — fetch the
  cited URL (bounded: ≤3 fetches/cycle, 10s timeout) and ask Gemini Flash (a different
  call from the one that produced the claim): *does this page support "{claim,
  value}"?* Yes → `verified`. No / fetch fails → the entry is **dropped and logged**
  (`news_verify_failed` counter in the lane's source-health details). Only
  `structured` or `verified` entries reach boost/enrich.
- **Deterministic floor:** any `impact` entry missing `source_name`, `url`, or `as_of`
  is dropped at parse time — unconditionally, before verification. (Claim/warrant
  principle: an impact claim without a warrant is unrepresentable downstream.)

### 3. Matching (news event ↔ detected signal)

`match_news_to_candidates(news_events, cycle_candidates)` in
`src/editorial/newsworthiness.py`:
- Match on **country (+ US state when both sides have it) + category + window
  overlap**. Fire↔fire, heat_mortality↔heat classes. Signals carry city/country/lat-lon
  (bundles) — news events carry place fields; v1 matching is deliberately coarse and
  **conservative: no match beats a wrong match** (a wrong match risks attaching a
  death toll to the wrong event — worse than missing it).
- Ambiguity rule: if a news event matches >1 candidate, attach impact only to the
  highest-scored match; never duplicate the same impact fact across drafts in a cycle.

### 4. Boost (rescue, capped — fire-first)

Applied between score construction and the `passes` check in the fire runner(s)
(`src/orchestrator/sources/firms.py` + NIFC complexes), via one helper:

```
apply_newsworthiness_boost(score, match) -> EditorialScore
  boost   = MAX_NEWS_BOOST                             # flat +8 in v1; no grading yet
  applies ONLY if score.total >= score.threshold - MAX_NEWS_BOOST   # hard floor
  applies ONLY if match has >= 1 structured/verified impact entry   # source-required
  result  = score with total += boost,
            reasons += ["news_boost=+8 per {source_name} ({url})"]
```

- The hard floor (threshold − 8) means news can rescue a **near-miss** (Colorado at
  62 < 64 clears), never resurrect a far-miss — the sensor still has to have nearly
  cleared the bar on its own. This is decision 3 made concrete: bounded, source-
  required, floored.
- The boost is visible end-to-end: `score.reasons` carries it into the suppression
  ledger, dashboard, and triage — an operator can always see *why* a signal cleared.
- Non-fire classes: helper exists, wired fire-only in v1.

### 5. Enrich (`human_impact` on the StoryBundle)

- Matched candidate's bundle gains `human_impact: [ImpactFact]` (optional field on
  `StoryBundle`; absent = today's behavior everywhere).
- **Writer prompt:** a new section (patterned on the reganom honesty sections): the
  writer MAY cite impact facts ONLY from `bundle.human_impact`, ONLY with attribution
  ("per NIFC," "the WHO says"), verbatim-or-rounded figures, past tense with the
  as-of window; never self-supplied impact, no alarmism (state the sourced figure
  plainly; existing safety-pipeline bans on "deadly/lethal" alarm-words stay).
- **Fact-check prompt:** new rule — any death-toll / casualty / impact claim in the
  tweet MUST match a `human_impact` entry (value + source attribution present in
  text); an impact claim with no matching entry is a KILL. Unsourced impact is already
  UNVERIFIABLE by the current rules; this makes the kill explicit and mechanical.
- **Deterministic pre-writer gate (evidence-contract style):** a bundle carrying
  `human_impact` entries with missing source/url/as_of blocks the writer
  (`stage="evidence_contract"`) — belt to the parse-time suspenders.
- **Approval policy:** the content-based override lives in `save_draft`
  (`src/orchestrator/draft_save.py`, where `recommend_approval_policy` from
  `src/editorial/approval.py` is applied and the draft TEXT is in hand — the
  type-only approval module cannot see content). It forces `manual_only` when the
  draft cites impact (decision 4). Detection is deterministic: the writer's JSON
  output gains a `cited_impact: bool` field, cross-checked by a regex sweep for the
  attached sources' names/values in the text (either signal → manual_only;
  disagreement → manual_only + warning log).

### 6. Gap flag (the read-only miss-detector)

**Matching inputs, made explicit (codex):** there is no durable candidate registry
today — suppressions capture only near-miss score kills. So: (a) *in-cycle*
matching (boost/enrich) runs at the triage **drain step**, where the full candidate
queue is in memory; (b) the *gap flag* compares across cycles against a new
lightweight `candidates_log` rolling state list (`{event_id, category, country,
date}`, recorded at `_enqueue_story_candidate`, 7-day prune, MERGE_SPEC entry —
the `coverage_log` pattern) plus `posted_events` and pending drafts.

After matching, any `structured`/`verified` NewsEvent with **no** match among the
`candidates_log` window AND no match against recent `posted_events`/pending drafts →
`news_gap` finding. Surfaced exactly like coverage-watch: one advisory auto-closing
issue (marker comment, updated in place, closes when the gap clears or ages out).
v1 flags only the two verticals we retrieve (fire, heat mortality) — precision over
recall; silence is impossible (a no-retrieval cycle marks the lane degraded, not
quietly gapless).

## Flags and rollout

| Flag (repo variable) | Default | Gates |
|---|---|---|
| `THEHEAT_NEWSWORTHINESS_ENABLED` | `0` | the retrieval lane entirely (master) |
| `THEHEAT_NEWS_BOOST_ENABLED` | `0` | boost application (needs master on) |
| `THEHEAT_NEWS_ENRICH_ENABLED` | `0` | human_impact attachment (needs master on) |

Rollout order (each step live-verified before the next; one-flip rollback each):
1. Master on, both consumers off → watch `state["news_events"]` populate, verify
   citations by hand, watch the gap flag against known events. **Zero editorial
   surface.**
2. Enrich on → impact-carrying drafts appear in the manual queue; verify writer
   attribution + fact-check kills on live dispatch (reganom-dryrun-style harness
   extended to a fire fixture with `human_impact`).
3. Boost on → watch the suppression ledger for `news_boost` reasons; confirm a
   near-miss rescue produces a draft with visible provenance.

## Cost envelope

Per 4h cycle: 1 NIFC fetch (free) + 1 grounded-search Gemini call + ≤3 verify fetches
with 1 Flash call each ≈ **≤5 LLM calls/cycle, ~30/day** — small against the existing
fact-check/critic volume; no Anthropic (writer) tokens spent until a rescued/enriched
candidate actually drafts. The lane is metered by the cycle cadence, not by news
volume (caps at parse time: ≤10 NewsEvents/cycle kept, ranked by impact severity).

## Testing

- Unit: normalization (feed row → NewsEvent; grounded response → NewsEvents; entries
  missing source/url/as_of dropped), matcher (country/state/category/window; ambiguity
  rule), boost helper (cap, floor, source-required, reasons string), approval forcing
  (cited_impact → manual_only, including for autoship-eligible record types).
- Replay the two incidents as fixtures: **Colorado** (fire near-miss 62/64 + a NIFC
  fire NewsEvent for the boost match, carrying a `verified` grounded-search
  fatalities impact entry per the corrected NIFC contract → rescued, enriched,
  manual_only, reasons carry the sources) and
  **Europe heat** (no detected mortality signal → gap flag opens; reganom heat signal
  present → mortality impact attaches to it when countries/windows overlap).
- Fact-check contract: a draft citing an impact figure absent from `human_impact` is
  killed; attribution-less citation killed; verbatim + attributed passes.
- Live: extend the dispatch harness (reganom-dryrun pattern) to run writer→critic on a
  fire bundle with `human_impact` before any flag flips.

## Reconciliation with prior art (check-dormant-before-building)

- **Coverage-watch (#333, LIVE — note: its design doc's "awaiting review" status is
  stale):** measures whether *our sensors'* output is geographically representative
  (inward-looking). The gap flag measures whether *the world's* biggest reported events
  reached us (outward-looking). Complementary, not duplicate — and the gap flag
  deliberately REUSES its advisory-issue machinery (marker, update-in-place,
  auto-close), so ops has one alarm grammar.
- **GDACS/Copernicus lane:** the existing precedent that sourced impact (population
  affected) can flow into scoring (flood `population_bonus`) and bundles. Bet A
  generalizes the pattern: impact facts as first-class, cited bundle data.
- **IDEAS.md #9/#10:** this design IS those two items; #9's v1 = the gap flag +
  boost, #10 = enrich. Both share the one retrieval/citation/verification core, built
  once, as #232's note requested.
- **Claim/warrant (#324, docs-only, awaiting Andrew):** the deterministic
  source/url/as_of floor is that principle applied to impact claims. If claim/warrant
  ships later, `ImpactFact` becomes one of its claim kinds; nothing here conflicts.
- **Throughput Phase D (`related_signals`, dark):** enrich attaches EXTERNAL facts;
  Phase D attaches sibling SENSOR signals. Different fields, no interaction; both are
  additive bundle context.

## Terminal step

Andrew reviews this spec → `superpowers:writing-plans` (Bet A becomes Pillar 2 of the
2026-07-03 three-pillar upgrade plan) → codex-xhigh the plan → subagent build → codex
the diff → ship behind the default-OFF flags above → live dispatch verify → flip on
in the rollout order.
