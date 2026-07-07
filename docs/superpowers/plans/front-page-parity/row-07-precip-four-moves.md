# Row 7 — Precipitation four-moves: retire P9, keep #372's honesty

> **✅ MERGED 2026-07-07 (#397).** 3 codex rounds — the plan's "verified contract" missed
> a live kind (`country_precip_event`), caught in review and given a voice path. P9 retired
> (accumulation + record-path + country-cluster all dryrun-verified). Open follow-up:
> **#401** (fact-check rule (o) sanctions "the 300 mm monitoring threshold" the critic kills
> as `internal_taxonomy_leak` — cross-gate contradiction). Plan retained for reference.

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

### Task 2: `writer_dryrun --type precipitation_extreme` (self-contained)

**Files:** `scripts/writer_dryrun.py`, `.github/workflows/writer-dryrun.yml`,
`tests/test_writer_dryrun.py`.

- [ ] **Step 1: Failing fixture tests:**

```python
class TestPrecipFixture:
    def test_accumulation_shape(self):
        bundle = _build_bundle(_args(type="precipitation_extreme"))
        assert bundle.signal_kind == "precipitation_extreme"
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["alert_threshold_mm"] == 300.0
        assert "previous_record_mm" not in facts
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_record_path_shape(self):
        bundle = _build_bundle(_args(type="precipitation_extreme", record_path=True))
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["previous_record_mm"] == 210.0
        assert "alert_threshold_mm" not in facts
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement — DEFAULTS additions:

```python
    # precipitation_extreme (Astana-class) knobs
    "precip_location": "Astana",
    "precip_country": "Kazakhstan",
    "precip_mm": 358.0,
    "precip_period_days": 7,
    "precip_threshold_mm": 300.0,
    "record_path": False,
```

argparse: `"precipitation_extreme"` in `--type` choices; `--precip-location`,
`--precip-country`, `--precip-mm`, `--precip-period-days`, `--precip-threshold-mm`,
and `--record-path` (store_true, dest `record_path`). `_build_bundle` branch:

```python
    if args.type == "precipitation_extreme":
        record = bool(args.record_path)
        event = PrecipExtremeEvent(
            kind="daily_record" if record else "multi_day_accumulation",
            location=args.precip_location,
            country=args.precip_country,
            date=datetime.now(UTC).date().isoformat(),
            mm_total=args.precip_mm,
            period_days=1 if record else args.precip_period_days,
            deviation_from_record_mm=148.0 if record else None,
            previous_record_mm=210.0 if record else None,
            previous_record_year=2013 if record else None,
            lat=51.17,
            lon=71.43,
            city_count=1,
            sample_cities=[args.precip_location],
            event_id="dryrun_precip_astana",
            alert_threshold_mm=None if record else args.precip_threshold_mm,
        )
        return build_precipitation_bundle(event)
```

(imports: `PrecipExtremeEvent` from `src.data.gpm_imerg`,
`build_precipitation_bundle` from `src.two_bot.intern`). `_print_bundle` gets a precip
branch (mm/period/threshold-or-record). Workflow: add the type to choices; add a
`record_path` boolean input wired via `INPUT_RECORD_PATH` env → `--record-path` flag,
same `EXTRA` pattern as `no_impact`.

- [ ] **Step 4:** PASS + smoke exit 2. **Step 5:** Commit
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
