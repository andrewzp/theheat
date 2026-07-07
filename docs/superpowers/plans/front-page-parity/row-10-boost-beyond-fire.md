# Row 10 — Boost beyond fire: heat-class rescue + the next feeds

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. **GATED: do not start until A2 (fire boost) has been live and
> verified for ≥1 week** (track-0 step 3) — the fire lane must prove the mechanism
> before it extends. Score-gate + editorial surface → codex-xhigh MANDATORY.

**Goal:** A Europe-heatwave-class news event (verified heat-mortality reporting) can
rescue a near-miss HEAT signal the way NIFC news rescues a near-miss fire — the second
half of the Congo-vs-Colorado fix, applied to the vertical that produced the worst miss.

**Architecture:** Mirror the fire boost exactly, one seam over. The enrich matcher
already treats `_HEAT_TYPES = {record, monthly_high, all_time_high, anomaly_hot,
absolute_extreme, regional_anomaly, wet_bulb_extreme}` as the `heat_mortality` family
(`src/editorial/newsworthiness.py:44-52`) — only the BOOST path is fire-hardcoded
(`_fire_event_matches_identity`, the `kind != "fire"` early return at ~:558, and
`plan_fire_boosts` being the only planner). Add `plan_heat_boosts` +
`_heat_event_matches_identity` (country + window overlap; heat news is placeless-ish —
NO name-matching leg, and the ambiguity rule attaches to the highest-scored match only,
same as enrich), apply at the heat runners' score gates, behind a NEW sub-flag.

**Tech Stack:** existing newsworthiness module + the heat source runners.

## Global Constraints

All of [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
§Standing rules, plus:
- Same boost law as fire, verbatim: flat `+MAX_NEWS_BOOST (8)`, hard floor
  `threshold − 8`, ≥1 structured/verified impact entry required, provenance string
  `news_boost=+8 per {source} ({url})` in `score.reasons`, rescue-only (passing scores
  untouched), one event rescues at most one candidate per cycle.
- New flag `THEHEAT_NEWS_BOOST_HEAT_ENABLED` (default 0, requires the master AND
  `THEHEAT_NEWS_BOOST_ENABLED`) — independent one-flip rollback for the new vertical;
  bot.yml passthrough in the house pattern.
- A boosted draft that cites impact is still forced `manual_only` by decision 4 —
  no change, verify in tests.

## Task sequence (write the failing test first at every step)

1. **`_heat_event_matches_identity(ev, heat_candidate) -> bool`** in
   `src/editorial/newsworthiness.py`: kind must be `heat_mortality`; candidate
   `legacy_type` ∈ `_HEAT_TYPES`; country equality (both sides normalized the way
   `_fire_event_matches_identity` does); event window
   (`window_start`..`window_end`) overlapping the candidate's `when`/date. NO
   name/incident leg. Tests: the Europe replay (WHO heat_mortality event, France
   window ↔ a France `regional_anomaly` candidate → match; a US fire candidate → no
   match; window disjoint → no match).
2. **`plan_heat_boosts(news_events, heats)`** — batch-scoped like `plan_fire_boosts`
   (`heats`: `{"id", "country", "when", "legacy_type"}` per candidate this runner
   pass); ambiguity rule: an event matching >1 candidate plans ONLY the
   highest-scored (pass scores in, or plan on the runner side after scoring — match
   `plan_fire_boosts`' actual call shape); one candidate takes at most one event.
   Tests mirror the fire planner's suite (`grep -n "plan_fire_boosts" tests/` for the
   file) case-for-case.
3. **Runner wiring** at each heat score gate, guarded by the new flag and the same
   try/except-print isolation as `src/orchestrator/sources/firms.py:44-53`:
   - `src/orchestrator/sources/open_meteo.py` `absolute_extreme` gate (~406-416),
     `anomaly_hot` gate (~437-444) — NOT `anomaly_cold` (heat news never rescues a
     cold signal; assert this in a test),
   - record gates (`all_time_high`/`monthly_high`, ~312-390) — heat-record types are
     in `_HEAT_TYPES`; include them,
   - `src/orchestrator/sources/reanalysis_anomaly.py` gate (~79-83).
   Each site: build the batch list → `plan_heat_boosts` once per runner pass →
   `apply_newsworthiness_boost(score, matched)` between score construction and
   `_should_draft`.
4. **Flag + bot.yml passthrough** (`THEHEAT_NEWS_BOOST_HEAT_ENABLED`, house comment
   pattern), `news_boost_heat_enabled()` helper requiring all three flags.
5. **Replay fixture test** — the spec's Europe case end-to-end: a
   `regional_anomaly` scoring 1 under 76 + a verified WHO heat_mortality event for
   the same country/window → rescued, reasons carry the provenance, draft forced
   manual when impact cited.
6. **Version/changelog/gates/PR/codex loop** — ask codex to attack: double-rescue
   across runners in one cycle (fire partition used namespaces; heat's partition is
   the per-runner batch + highest-score rule — is that airtight when open_meteo and
   reganom both run?); cold-signal leakage; flag-gating completeness (master off ⇒
   no-op even if sub-flags on); floor/cap regressions on the shared
   `apply_newsworthiness_boost` (it must remain UNTOUCHED — reuse, don't modify).
7. **Live verify after Andrew flips the sub-flag:** suppression ledger shows
   `news_boost=` reasons on a heat candidate within the first week of a matching
   news event; one-flip rollback command documented in the PR.

**Feeds half (second PR, after the boost half is live):** add WHO EURO surveillance
as a structured feed leg following the NIFC leg's contract-first pattern
(`src/data/newsworthiness.py` — verify the exact endpoint + a sample payload BEFORE
coding, exactly like Bet A's A0 did; only machine-readable fields become
`confidence="structured"`); ReliefWeb stays blocked on the appname approval (check
its status with Andrew first); NHC/NWS-as-news explicitly deferred until the FPP
data shows cyclone/severe verticals missing. Each feed = its own contract-verified
mini-plan appended to this doc when its turn comes.

**Success criteria:** the Europe-class miss becomes structurally impossible for
detected-but-below-threshold heat signals; FPP's heat vertical parity rises; zero
boosts ever appear without provenance or below the floor.
