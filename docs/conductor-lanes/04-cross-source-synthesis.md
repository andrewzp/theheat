# Lane 4 — Cross-Source Story Synthesis

## Mission

Add a meta-detection layer that fires signals when multiple source types
align on the same region at the same time — "California is on fire AND
in extreme drought AND breaking heat records." These cross-source
stories are more interesting than any single data point and get closer
to the breakout-viral register described in `brand/EXEMPLARS.md`.

## Why this matters

Our current pipeline is per-source: fires from FIRMS, drought from US
Drought Monitor, heat from Open-Meteo, each scored and drafted
independently. But the real climate story is often the **convergence**:
- Drought + fire weather + record heat = the conditions that produce the
  Camp Fire / Dixie Fire / Black Summer
- Hurricane + extreme rainfall + storm surge = the compound flooding
  story
- Marine heatwave + coastal heat dome + coral-region location = the
  ecosystem-collapse story

Cross-source tweets have higher editorial value AND higher social
currency (the reader learns something specific about a region they may
know personally). But they are harder to detect and require careful
scope.

## Scope philosophy

This lane is explicitly smaller in data surface, larger in reasoning.
No new external data sources — we're using what the pipeline already
fetches and adding a correlation layer. That means this lane depends on
the **existing** pipeline state being clean:

- Fire source ✓ (FIRMS, already fixed)
- Heat source ✓ (Open-Meteo, 613 cities, country records)
- Drought ✓ (US Drought Monitor, Fridays)
- NWS ✓ (recently widened)
- GDACS ✓

If Lane 1 (Ocean SST) or Lane 3 (Fire Footprint) lands first, this lane
can pull from those too.

## Detection approach

Keep it simple. Start with 2–3 high-value compound patterns. Each one is
a named synthesis rule that runs once per alerts cycle after all
individual sources have been processed.

### Suggested MVP rules

1. **Fire × Drought × Heat co-occurrence (US region)**
   Fires if: in the last 14 days, state X has (a) exceptional drought
   (D4 from USDM), (b) at least one FIRMS fire ≥ threshold, (c) at
   least one Open-Meteo city in that state has broken a heat record.
   Signal: "California has D4 drought AND a 1200 MW fire AND just
   broke a calendar-date record in Sacramento. Weeks behind the Camp
   Fire anniversary."

2. **Marine heatwave × coastal heat dome**
   (only if Lane 1 has shipped) When global/regional SST is breaking a
   record AND a coastal metro in that basin is in Open-Meteo top 10
   anomaly. Signal: "North Atlantic SST at record levels AND Lisbon is
   7°C above its April normal. Couplings matter."

3. **Hurricane × storm surge × flood (US Gulf/East coast)**
   Already-ingested sources: NWS (Hurricane Warning + Storm Surge
   Warning) and USGS river floods and NOAA CO-OPS surge. When all three
   fire in the same region within 72 hours, emit a synthesis signal.
   "Hurricane Warning for X, Storm Surge at Y, and the Z river is above
   flood stage. Compound flooding in progress."

**Start with 1–2 rules.** Prove the synthesis layer works. Add more
rules via separate PRs once the scaffolding is solid.

## Scope (what to build)

1. **New module:** `src/editorial/synthesis.py`
   - `SynthesisSignal` dataclass (region, components, headline, event_id).
   - One function per rule: `detect_fire_drought_heat(bot_state,
     fires, drought_entries, bundles) -> list[SynthesisSignal]`.
   - Shared helpers: region-matching (lat/lon → state/country),
     time-windowing (did X happen in last N days).
2. **State additions:**
   - Consider a `synthesis_cooldown: {rule_name: last_fired_at}` so a
     long-running compound event (3-week California heat wave) doesn't
     produce daily synthesis tweets.
3. **Scoring:** `score_synthesis_signal` in `src/editorial/scoring.py`.
   Threshold 82 — synthesis is elite by definition.
4. **Template + generator:** `synthesis_template` /
   `generate_synthesis_tweet`. Generator prompt should emphasize
   compound framing — the rule that fired is context for Gemini to
   write the compound story.
5. **Approval policy:** `suggested_auto` with 120min delay. Synthesis
   claims are higher-stakes (factually more brittle) — keep review
   window.
6. **Main orchestrator:** Run synthesis at the END of `run_alerts`,
   after all individual sources, so it has access to the cycle's fires
   list, bundles list, drought state, etc. Pass the raw source outputs
   through `run_alerts`'s call stack rather than re-fetching.
7. **Tests:**
   - Unit test per rule: construct a test scenario where all components
     fire, assert the synthesis signal emits.
   - Edge cases: only some components fire → no signal. Region mismatch
     (fire in US, drought in Australia) → no signal.
   - Cooldown: same rule fires on consecutive days → second suppressed.

## Key voice rules

- Never chain claims without separators. "California is in D4 drought,
  burning a fire, and broke a heat record" reads flat. Use short beats.
- Compound framings beat aggregates. "D4 drought. 1200 MW fire.
  Sacramento broke the record. All in California. All today." —
  period-separated cadence matches the voice doc's deadpan rules.
- **Do not invent causality.** "Heat caused the fire" is a claim we
  cannot assert in one tweet. Stick to co-occurrence.
- **Time-range honesty.** "in the last 14 days" beats "recently."

## Definition of Done

- [ ] At least one synthesis rule shipped with tests.
- [ ] Rule correctly fires on a test scenario matching all components.
- [ ] Rule correctly suppresses when components don't all match (region,
      time).
- [ ] Cooldown prevents daily re-firing on a multi-week compound event.
- [ ] Full suite green.
- [ ] New section in BRIEFING + PIPELINE.
- [ ] Examples of rule-fired outputs in the PR description.

## Non-goals

- **Don't** try to build a general "correlation engine." This is a
  small, named-rules layer. A general LLM-driven synthesis layer is a
  separate design discussion.
- **Don't** tweet "X is in heat wave" when we already have the per-city
  heat-record tweet. The compound story must add reader value beyond
  any single component tweet.
- **Don't** block individual-source tweets when a synthesis fires. The
  per-source tweets can still ship (subject to city cooldown); the
  synthesis adds a new story, doesn't replace.
- **Don't** add rules that require data we don't already have. If a
  rule needs marine heatwaves, wait for Lane 1.

## Budget expectations

- 1 rule shipped: ~4–6 hours.
- 3 rules shipped: ~10 hours.
- Reasoning complexity > data-source complexity. Expect the bulk of
  work in the rule-matching logic and test scenarios.
