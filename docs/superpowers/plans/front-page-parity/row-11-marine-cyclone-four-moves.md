# Row 11 — Marine/coral + cyclone four-moves: the template-convergence types

> **✅ MERGED 2026-07-07** (PR-1 marine #402, PR-2 cyclone #404). Both dryrun voice-verified.
> The plan's "verified bundle contracts" MISSED `cyclone_basin_record` (a live 5th cyclone
> kind) and had fabricated coral vocab ("Alert Level 3" — real caps at "Bleaching Alert
> Level 2"/"mortality expected") — both caught pre-dispatch/in-review. Open follow-up:
> **#403** (`_stress_level_for_dhw` under-labels vs the NOAA scale). Plan retained for reference.

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. Editorial-gate diffs → **codex-xhigh MANDATORY**. Ship as TWO
> PRs (marine, then cyclone) — each is a full E1-pattern pass. Do row 7 first; if row 5
> has merged, its land-threat convention block gets absorbed into the cyclone section
> here (do not duplicate rules).

**Goal:** The two remaining high-volume signal families with documented voice failures
get their four-moves sections: coral/marine (the original template-convergence family —
"7 of 8 coral drafts identical two-sentence template" in the corpus) and cyclones
(alarmism-adjacent, currently guided by one convention bullet + bans only).

**Architecture:** The E1 pattern, types four and five. Bundle contracts below are
verified against the interns (2026-07-06); prompt sections must name ONLY these fields.
Both PRs: prompt section + paired fact-check additions + `writer_dryrun --type` fixtures
+ pinned prompt tests + codex loop. No intern changes.

## Verified bundle contracts (name nothing else)

**coral_bleaching** (`src/two_bot/intern/marine.py:33-70`): `region_id`,
`region_full_name`, `dhw_value` (°C-weeks), `dhw_tier`, `bleaching_level`,
`stress_level`, `source_name`, `lat`, `lon`, climate-context facts, up to 3
`reef_context` facts (these carry a `kind` sibling key); optional
`data_source`+`evidence_grade="observed_alt_host"` (ERDDAP witness).
`historical_context = {scope, thresholds_c_weeks: [4, 8, 12]}`. NO trend field — a DHW
value is a snapshot (rule b applies; the NOAA alert-level semantics are WORLD_KNOWLEDGE
per fact-check rule a).

**marine_heatwave** (`marine.py:142-168`): `kind` ("first"|"milestone"), `streak_days`
(the headline; a REAL trend field — direction language is fair), `today_c`,
`peak_anomaly_c`; `historical_context = {archive_max_c, archive_max_year,
archive_years, scope: noaa_oisst_global_archive}`. `where` is hardcoded
"Global ocean (60°S–60°N)".

**regional_sst_anomaly** (`marine.py:170-219`): `region_slug`, `region_display_name`,
`anomaly_c` (2dp), `tier`, `tier_threshold_c`, `spatial_aggregation` ("cos-latitude
area-weighted basin mean"), `grid_cells_used`, `anomaly_basis`, `signal_note` (says
explicitly: NOT a Hobday MHW classification — the writer must never call it a "marine
heatwave" by that name).

**cyclone_* bundles** (`src/two_bot/intern/disasters.py:139-303`): common facts
`source, storm_name, basin, category, wind_speed_kt, central_pressure_mb, lat, lon,
advisory_number, public_advisory_url` + climate context; RI adds `previous_wind_kt,
previous_category, delta_kt_24h` (headline; `historical_context` carries
`rapid_intensification_threshold_kt: 30` — which is exactly the P_tier trap: the
OBSERVED delta is citable, the trigger definition is NOT, per row 4's plumbing ban);
tier crossing adds `from_category, to_category`; landfall adds `landfall_location`;
land-threat (row 5) adds its own documented fields.

## PR-1: Marine/coral four-moves

- [ ] **Failing prompt tests** (pin NEW phrases; template):

```python
class TestMarineFourMoves:
    def test_sections_present(self):
        assert 'signal_kind = "coral_bleaching"' in WRITER_SYSTEM_PROMPT
        assert "regional_sst_anomaly" in WRITER_SYSTEM_PROMPT  # in the same section header

    def test_move_one_leads_with_the_reef_not_the_unit(self):
        assert "Lead with what the heat is doing to the reef" in WRITER_SYSTEM_PROMPT

    def test_move_two_dhw_semantics_are_the_anchor(self):
        assert "°C-weeks is a dose, not a temperature" in WRITER_SYSTEM_PROMPT

    def test_move_three_one_reef_fact_does_the_work(self):
        assert "ONE reef_context fact" in WRITER_SYSTEM_PROMPT

    def test_move_four_snapshot_discipline(self):
        assert "a DHW reading is a snapshot" in WRITER_SYSTEM_PROMPT

    def test_fact_check_pairing(self):
        assert "not a Hobday" in FACT_CHECK_SYSTEM_PROMPT
        assert "°C-weeks is a dose" in FACT_CHECK_SYSTEM_PROMPT
```

- [ ] **The section** (after precipitation's; full text drafted at implementation
following the fire/precip sections' shape, containing at minimum): move 1 — lead with
the reef's situation, not "X has accumulated Y °C-weeks" (the corpus's convergent
opener); move 2 — DHW as dose ("°C-weeks is a dose, not a temperature — 8 °C-weeks is
four weeks of +2°C or eight of +1°C"), NOAA alert-level semantics as the published
scale (fair game per fact-check rule a), tier words from `bleaching_level`/
`stress_level` verbatim; move 3 — ONE `reef_context` fact as the differentiator per
draft (the anti-template move: with 8 coral drafts in a cycle, the reef fact is what
makes each distinct; the critic's template-convergence kill stays the backstop); move
4 — snapshot discipline (a DHW reading is a snapshot: no "still climbing/accumulating"
without a trend field — restate rule b's precip/coral shapes), `regional_sst_anomaly`
must be framed as the area-weighted basin-mean anomaly it is and never called a
"marine heatwave" (the `signal_note` says so), while `marine_heatwave` (OISST streak)
DOES carry `streak_days` and direction language is fair there.
- [ ] **Fact-check pairing** — extend the marine parts of WORLD_KNOWLEDGE/(b) with two
explicit lines: the dose framing is canonical (accept); "marine heatwave" naming on a
`regional_sst_anomaly` bundle contradicts the bundle's own `signal_note` (reject —
BUNDLE_FACT inconsistency, quote the note).
- [ ] **Dryrun (self-contained):** add BOTH types to `scripts/writer_dryrun.py`.
DEFAULTS: `"dhw_value": 24.5, "dhw_region": "galapagos", "mhw_streak_days": 12`.
argparse: the two types in `--type` choices + `--dhw-value/--dhw-region/--mhw-streak-days`.
`_build_bundle` branches (keyword construction, dates today-relative):

```python
    if args.type == "coral_bleaching":
        event = CoralBleachingEvent(
            region_id=args.dhw_region,
            region_full_name="Galápagos Islands",
            date=datetime.now(UTC).date().isoformat(),
            dhw_value=args.dhw_value,
            dhw_tier=12,
            bleaching_level="Alert Level 3",
            stress_level="multi-species mortality risk",
            event_id=f"dryrun_coral_{args.dhw_region}",
            lat=-0.6, lon=-90.4,
        )
        return build_coral_bleaching_bundle(event)
    if args.type == "marine_heatwave":
        event = MarineHeatwaveStreakEvent(
            kind="milestone",
            days=args.mhw_streak_days,
            peak_anomaly_c=0.31,
            today_c=21.1,
            archive_max_c=21.05,
            archive_max_year=2024,
            years_of_data=44,
            date=datetime.now(UTC).date().isoformat(),
            event_id=f"dryrun_mhw_{args.mhw_streak_days}d",
        )
        return build_marine_heatwave_bundle(event)
```

(imports from `src.data.coral_dhw` / `src.data.ocean_sst` / `src.two_bot.intern`.
BEFORE writing the fixtures, read both event dataclasses and copy their REAL field
names/vocabulary — the `bleaching_level`/`stress_level` strings above must match the
intern's actual emitted vocabulary; adjust from the dataclass defaults if they differ.)
Fixture tests in `tests/test_writer_dryrun.py`: each type → correct `signal_kind`,
evidence contract PASS, no `human_impact`; the coral bundle carries
`thresholds_c_weeks == [4, 8, 12]` in `historical_context`. Workflow choices gain both
types.
- [ ] Version/changelog/gates/PR/codex loop (attack: does move 3 conflict with the
critic's template-convergence kill or double-teach it; dose-analogy arithmetic
correctness; any loosening unpaired) → merge → dispatch both dryrun types.

## PR-2: Cyclone four-moves

- [ ] **Failing prompt tests** pinning: section header for the cyclone family; move
phrases ("Lead with the storm's change, not its category label", "the observed delta
is the anchor", "one mechanism the basin explains", "everything lands forecast-tense
when the bundle is a forecast"); fact-check additions.
- [ ] **The section** consolidates + supersedes the current single convention bullet
(`writer_prompt.py:68` — keep the bullet's field list, move the guidance here): move
1 — lead with change/consequence, never "X is now a Category N" (the existing
category-bait ban, integrated); move 2 — the observed anchor per kind (`delta_kt_24h`
for RI — "winds climbed 40 kt in 24 hours", `from_category → to_category` for
crossings, `landfall_location` for landfalls, `min_distance_nm`/`closest_tau_h` for
land threats) with row 4's plumbing rule restated in-context: the RI trigger
definition is the bot's config, never citable; move 3 — basin mechanism as the system
clause (warm-pool depth, shear, SSTs — WORLD_KNOWLEDGE), one mechanism only; move 4 —
tense discipline: observed kinds in past/present-observed tense, land-threat
(forecast) kinds forecast-tense-only (absorb row 5's convention block here verbatim if
it merged first), all alarmism bans restated by reference.
- [ ] **Fact-check pairing:** one cyclone block collecting the tense rule (n) (if row
5 landed) + the delta-vs-trigger distinction + basin-mechanism acceptance, so cyclone
rules read in one place.
- [ ] **Dryrun:** `--type cyclone_rapid_intensification` (Bavi-class: 105→145 kt,
delta 40) fixture + tests.
- [ ] Version/changelog/gates/PR/codex loop (attack: consolidation didn't DROP any
existing ban; the moved convention bullet's field list still test-pinned; land-threat
absorption didn't change row 5's semantics) → merge → dispatch the dryrun type.

**Success criteria:** coral cycles stop producing near-identical templates (critic
template-kills on coral drop measurably in the suppression ledger); cyclone drafts'
corpus grades clear B consistently with the observed-delta lead; the P_tier cyclone
instances never recur.
