# Row 7 — Precipitation four-moves: retire P9, keep #372's honesty

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. Editorial-gate diff → **codex-xhigh MANDATORY**. Do row 4 first
> — its detection-plumbing ban and pairing pattern are assumed in force here.

**Goal:** `precipitation_extreme` drafts stop reading as the P9 ticker ("X mm of rain
fell in Y over Z days" + restate-math) and start reading as findings — while making the
#372 lesson (a threshold is not a record) part of the writer's own voice rules, not just
the bundle's construction.

**Architecture:** The E1 pattern, third type: a dedicated writer-prompt section naming
the four moves for precip bundles, every loosening paired with a fact-check rule in the
same PR, `writer_dryrun --type precipitation_extreme` with both fixture shapes (a
record-path daily event and a threshold-path multi-day accumulation), and prompt-content
tests. No intern changes needed — the bundle already carries everything (post-#376).

**Tech Stack:** prompts + harness + tests only.

## Global Constraints

All of [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
§Standing rules, plus the bundle's own iron rule (post-#372, enforced at construction):
`previous_record_mm` and `alert_threshold_mm` are mutually exclusive by construction —
record language is warranted ONLY when the record fields exist.

## The bundle contract the prompt teaches (verified 2026-07-06)

From `build_precipitation_bundle` (`src/two_bot/intern/precipitation.py:15-87`):
- Always: `event_kind` ("daily_record" | "multi_day_accumulation"), `location`,
  `country`, `date`, `rainfall_mm` (1-decimal, the headline), `period_days`,
  `city_count`, `sample_cities`, `lat`, `lon`, plus climate-context facts
  (`region_climate_system`, optionally `climate_mechanism_note`,
  `local_topography_note`, `season_context`).
- Record path ONLY: `previous_record_mm`, `previous_record_year`,
  `deviation_from_record_mm`.
- Threshold path ONLY: `alert_threshold_mm` (a static trigger — NOT a record).
- Witness path: `evidence_grade="model_fallback"` + `data_source` (Open-Meteo stood in
  for GPM — never "observed/measured/recorded").
- NOT carried: the accumulation window's start date (only the END date survives as
  `date`), any annual-normal figure, any flood-impact figure.

## File map (one PR)

- Modify: `src/two_bot/prompts/writer_prompt.py`, `src/two_bot/prompts/fact_check_prompt.py`
- Modify: `scripts/writer_dryrun.py`, `.github/workflows/writer-dryrun.yml`
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/two_bot/test_prompts.py`, `tests/test_writer_dryrun.py`

Branch: `git checkout main && git pull && git checkout -b feat/precip-four-moves`

---

### Task 1: Prompt section + pairing, test-first

- [ ] **Step 1: Failing prompt tests** (append to `tests/two_bot/test_prompts.py`;
every assertion pins NEW exact phrases):

```python
class TestPrecipFourMoves:
    """E1 pattern, third type. P9 evidence: opener-template + restate-math
    reopened on first reappearance (corpus, Jul 4); #372: a threshold cited
    as 'the previous record' was the false-record class."""

    def test_precip_section_present(self):
        assert 'signal_kind = "precipitation_extreme"' in WRITER_SYSTEM_PROMPT

    def test_move_one_retires_the_p9_opener(self):
        assert "Lead with what the water did" in WRITER_SYSTEM_PROMPT

    def test_move_two_bans_restate_math(self):
        assert "never re-derive a per-day rate" in WRITER_SYSTEM_PROMPT

    def test_move_three_threshold_is_not_a_record(self):
        assert "a trigger the bot watches, not a record the sky broke" in WRITER_SYSTEM_PROMPT

    def test_move_four_names_the_water_stakes(self):
        assert "where the water goes" in WRITER_SYSTEM_PROMPT

    def test_fact_check_pairing_rule_o(self):
        assert "record language requires the record fields" in FACT_CHECK_SYSTEM_PROMPT.lower()
        assert "alert_threshold_mm" in FACT_CHECK_SYSTEM_PROMPT
        assert "period_days" in FACT_CHECK_SYSTEM_PROMPT
```

- [ ] **Step 2:** Run `-k TestPrecipFourMoves` → FAIL on all.

- [ ] **Step 3: Writer prompt.** Insert a `## Precipitation bundles
(`signal_kind = "precipitation_extreme"`)` section after the fire-bundles section,
same shape as the fire/reganom sections:

```markdown
## Precipitation bundles (`signal_kind = "precipitation_extreme"`)

Two kinds ride this signal, and the bundle tells you which: `event_kind =
"daily_record"` (a real archive record fell — `previous_record_mm`,
`previous_record_year`, `deviation_from_record_mm` are present) or
`"multi_day_accumulation"` (a multi-day total crossed a monitoring trigger —
`alert_threshold_mm` is present INSTEAD; there are no record fields because no record
is known). The failure mode is the rain ticker: *"[Place] recorded X mm of rain in
N days"* as the opener, then the same numbers restated as arithmetic. Four moves:

1. **Lead with what the water did, not the gauge.** The measurement is attribution —
   weave it (*"satellite-measured"*, *"per the IMERG record"*); open on the thing a
   reader feels: a week of rain in a day, a record that stood since {previous_record_year}
   falling, rain where rain doesn't go.
2. **One number does the work — never re-derive a per-day rate.** Cite `rainfall_mm`
   verbatim with its `period_days` window stated once (*"358 mm across seven days"*).
   Do NOT restate it as arithmetic ("that's 51 mm a day") — derived rates are
   BUNDLE_FACT mismatches waiting to happen and read as effort. Well-established
   climatological comparison (*"roughly an entire annual average's worth"*) is fair
   WORLD_KNOWLEDGE when you are confident of the place's climate — the ratio is the
   scale anchor, and it must survive a one-search check.
3. **A threshold is a trigger the bot watches, not a record the sky broke.** When the
   bundle carries `alert_threshold_mm`, you may say the total *crossed* that
   monitoring threshold — never that it "broke the record," "set a new mark," or beat
   "the previous record of {alert_threshold_mm}." Record language exists ONLY when
   `previous_record_mm`/`previous_record_year` exist, and then cite them verbatim.
4. **Name where the water goes.** The system clause is the hydrology the bundle and
   world knowledge can see: `climate_mechanism_note`/`season_context` facts, frozen
   ground shedding rain instead of soaking it, monsoon timing, terrain funneling. No
   invented flood impacts — no deaths, homes, evacuations, road closures unless a
   `human_impact` entry carries them (then the SOURCED HUMAN IMPACT rules govern).
   If `evidence_grade` is `model_fallback`, the number is a model estimate — never
   "observed/measured/recorded."
```

- [ ] **Step 4: Fact-check rule (o)** (after rule (n) if row 5 has merged, else after
(m) — letter it to follow whatever the file currently ends at, and say which in the
commit message):

```markdown
**o) Precipitation — record language requires the record fields.** For
`precipitation_extreme` bundles: "record", "broke/beat the previous record", "new
mark", "highest since {year}" are warranted ONLY by `previous_record_mm` +
`previous_record_year` present in the bundle, cited verbatim. A bundle carrying
`alert_threshold_mm` instead has NO known record: threshold-crossing language
("crossed the 300 mm monitoring threshold") is BUNDLE_FACT; record language is a
FAILURE. The accumulation window must match `period_days` exactly (a "week" claim on
period_days=7 is fine; on 3 it is a mismatch). Derived per-day rates the bundle does
not carry are UNVERIFIABLE arithmetic (rule c applies). Annual-normal comparisons are
WORLD_KNOWLEDGE — accept when the claimed normal is broadly right for the place;
reject invented specificity (an exact local normal to the millimetre).
```

- [ ] **Step 5:** Run → all `TestPrecipFourMoves` PASS + the whole prompt suite green.
- [ ] **Step 6:** Commit
`"feat(voice): precipitation four-moves + fact-check rule (o) — P9 retired, threshold≠record in the writer's own rules"`.

### Task 2: `writer_dryrun --type precipitation_extreme`

Mirror row-04 Task 4 exactly. DEFAULTS: an Astana-class accumulation fixture
(`kind="multi_day_accumulation"`, `location="Astana"`, `country="Kazakhstan"`,
`mm_total=358.0`, `period_days=7`, `alert_threshold_mm=300.0`, record fields None,
`city_count=1`, `sample_cities=["Astana"]`, plausible lat/lon 51.17/71.43, `date` =
today) with a `--record-path` flag variant swapping in the record shape
(`previous_record_mm=210.0`, `previous_record_year=2013`,
`deviation_from_record_mm=+148.0`, `alert_threshold_mm=None`). Construct
`PrecipExtremeEvent` (from `src.data.gpm_imerg`) keyword-style, `event_id`
`"dryrun_precip_astana"`, date today-relative → `build_precipitation_bundle`. Fixture
tests in `tests/test_writer_dryrun.py`: both shapes pass the evidence contract; the
accumulation fixture carries `alert_threshold_mm` and NO record fields; the record
fixture the reverse. Workflow choice list gains the type. Commit
`"feat(dryrun): --type precipitation_extreme — accumulation + record-path fixtures"`.

### Task 3: Version, changelog, gates, PR, codex, live verify

- [ ] VERSION bump + CHANGELOG entry.
- [ ] Full gates green.
- [ ] PR + codex-xhigh loop. Ask codex to attack: (a) can move 2's WORLD_KNOWLEDGE
annual-ratio loosening be exploited to smuggle a fake normal? (rule o's "broadly right"
bar — is it tight enough, should it name a tolerance?); (b) does move 3 contradict the
gpm bundle builder's comment or #376 fields anywhere; (c) does the "week" =
period_days=7 example create a 7-vs-"a week" trap like reganom's (it should MATCH the
reganom precedent: state the window once, exactly); (d) restate-math ban vs the
`deviation_from_record_mm` field (citing the bundle's own pre-computed deviation is
sanctioned — make sure the prompt says so if codex flags ambiguity).
- [ ] Merge on green + verify squash. Dispatch `writer-dryrun --type
precipitation_extreme` both shapes; drafts must clear all gates with the new voice.

**Success criteria:** the next precip drafts in the grading corpus stop hitting P9
(opener + restate-math both gone); threshold-path drafts never use record language;
P9 moves to Resolved.
