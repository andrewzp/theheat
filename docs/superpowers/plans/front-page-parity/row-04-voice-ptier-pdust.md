# Row 4 — P_tier + P_dust: detection-plumbing ban + a real dust WHO anchor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first — they apply to every task here. This is an **editorial-gate +
> intern diff → codex-xhigh is MANDATORY** (Task 6).

**Goal:** Kill the two highest-evidence voice failure modes from the grading corpus:
P_tier (the writer quoting the bot's internal detection taxonomy — 10 instances across 4
signal types, hard-caps grades at B) and P_dust (11 of 11 dust drafts missing a WHO-scale
anchor — because the dust bundle carries none).

**Architecture:** Intern-first for P_dust (the bundle must hold the anchor before the
writer can cite it): add `pm10` to the existing Open-Meteo hourly fetch, pre-compute a
24-hour PM10 mean + its WHO multiple onto `DustEvent` and the dust bundle. Prompt-side
for both: one new WHAT-NEVER-SHIPS bullet (P_tier), one dust-anchor convention (P_dust),
each paired with a fact-check rule and a critic kill condition in the same PR — the E1
discipline (#379 precedent).

**Tech Stack:** existing only — Python 3.12, pytest, the three prompt files, the
writer-dryrun harness.

## Global Constraints

All of [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
§Standing rules, plus:
- The WHO 2021 PM10 24-hour AQG is **45 μg/m³** — hardcode as the canonical guideline
  fact exactly as PM2.5 hardcodes 15.
- The anchor is **co-measured PM10, mean-vs-mean**. Open-Meteo's `dust` variable is
  mineral/Saharan dust, NOT PM10 — never label a dust value with the PM10 guideline, and
  never compare a daily MAX against the 24h-MEAN guideline.
- Editing `WRITER_SYSTEM_PROMPT` invalidates the Anthropic prompt cache once on deploy —
  expected, no action needed; the byte-identity tests only require faithful pass-through.

## File map (whole PR)

- Modify: `src/data/air_quality.py` (hourly request + `CityAirQuality` + `DustEvent` + `detect_dust_event`)
- Modify: `src/two_bot/intern/air_quality.py` (`build_dust_event_bundle` anchor facts)
- Modify: `src/two_bot/prompts/writer_prompt.py` (one bullet + dust convention)
- Modify: `src/two_bot/prompts/fact_check_prompt.py` (rule m)
- Modify: `src/two_bot/prompts/critic_prompt.py` (kill bullet + example)
- Modify: `scripts/writer_dryrun.py` + `.github/workflows/writer-dryrun.yml` (`--type dust`)
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/two_bot/test_air_quality_intern.py`, `tests/two_bot/test_prompts.py`, `tests/test_writer_dryrun.py`

Branch: `git checkout main && git pull && git checkout -b feat/voice-ptier-pdust`

---

### Task 1: The dust data anchor (fetcher + event)

**Files:**
- Modify: `src/data/air_quality.py`
- Test: `tests/test_air_quality.py` (the existing detector tests live here; its fixture helper is `_obs(...)` at line ~63 — extend THAT helper with a `pm10_24h_mean=None` keyword default)

**Interfaces:**
- Consumes: the existing `_slice`/`_daily_mean`/`_daily_max` helpers in `src/data/air_quality.py` and the hourly request string at `src/data/air_quality.py:242`.
- Produces: `CityAirQuality.pm10_24h_mean: float | None`; `DustEvent.pm10_24h_mean: float | None` and `DustEvent.who_pm10_multiple: float | None` (pre-rounded to 1 decimal); constant `WHO_PM10_24H_GUIDELINE = 45.0`.

- [ ] **Step 1: Write the failing detector test** (in the file that currently tests `detect_dust_event`; construct events keyword-style; dates today-relative):

```python
def test_detect_dust_event_carries_pm10_anchor_when_available():
    """P_dust root cause: dust drafts had no WHO-scale anchor because the
    event carried none. The anchor is CO-MEASURED PM10 (a separate hourly
    variable from `dust`), 24h mean vs the WHO 2021 PM10 24h AQG (45)."""
    obs = _obs(dust=2400.0, pm10_24h_mean=900.0)
    event = detect_dust_event(obs)
    assert event is not None
    assert event.pm10_24h_mean == 900.0
    assert event.who_pm10_multiple == 20.0  # round(900/45, 1)


def test_detect_dust_event_is_none_safe_without_pm10():
    # A cycle where the pm10 series is missing must still mint the dust
    # event (tier logic unchanged) with the anchor fields None.
    obs = _obs(dust=2400.0, pm10_24h_mean=None)
    event = detect_dust_event(obs)
    assert event is not None
    assert event.pm10_24h_mean is None
    assert event.who_pm10_multiple is None
```

(`_obs` is `tests/test_air_quality.py`'s existing `CityAirQuality` fixture helper —
its dust kwarg is `dust=` (NOT `dust_daily_max=`); extend the helper with a
`pm10_24h_mean=None` keyword default and do not write a new helper.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ -k "dust_event_carries_pm10 or none_safe_without_pm10" -v`
Expected: FAIL — `TypeError` (unexpected keyword) or `AttributeError` (no field).

- [ ] **Step 3: Implement.** Four edits in `src/data/air_quality.py`:

(a) The request string at line ~242 — add `pm10`:

```python
                "hourly": "pm2_5,pm10,dust,aerosol_optical_depth,us_aqi",
```

(b) `CityAirQuality` — append after `dust_daily_max: float | None`:

```python
    pm10_24h_mean: float | None
```

and in the constructor call near line ~166, beside `dust_daily_max=_daily_max(_slice("dust"))`:

```python
        pm10_24h_mean=_daily_mean(_slice("pm10")),
```

(c) Module constant, next to the existing WHO PM2.5 constant:

```python
# WHO 2021 Air Quality Guideline, PM10 24-hour mean. The dust anchor is
# CO-MEASURED PM10 (Open-Meteo `pm10`), never the `dust` variable itself —
# `dust` is mineral dust only and has no 24h-average standard.
WHO_PM10_24H_GUIDELINE = 45.0
```

(d) `DustEvent` — append two optional fields (keyword construction throughout, so
appending is safe):

```python
    pm10_24h_mean: float | None = None
    who_pm10_multiple: float | None = None
```

and in `detect_dust_event` (line ~348), thread them through the constructor:

```python
    who_pm10_multiple = (
        round(obs.pm10_24h_mean / WHO_PM10_24H_GUIDELINE, 1)
        if obs.pm10_24h_mean is not None
        else None
    )
```

with `pm10_24h_mean=obs.pm10_24h_mean, who_pm10_multiple=who_pm10_multiple,` added to
the `DustEvent(...)` call.

- [ ] **Step 4: Run tests** — same command → PASS. Then sweep for broken constructors:
`.venv/bin/python -m pytest tests/ -k "air_quality or dust" -q` → PASS (fix any test
building `CityAirQuality`/`DustEvent` positionally by switching it to keywords).

- [ ] **Step 5: Commit**

```bash
git add src/data/air_quality.py tests/
git commit -m "feat(dust): co-measured PM10 24h-mean anchor on DustEvent (P_dust data half)"
```

**Request-weight note for the reviewer (put in the PR body):** the hourly variable count
goes 4→5 (+25% weight) on the already-rate-limited 638-city sweep. The recovery passes
(`RECOVERY_PASSES`) absorb tail losses; runner reports `success` at ≥90% coverage. The
live verify in Task 7 watches exactly this. Contingency if coverage drops below 90% for
2+ cycles: split `pm10` into a second, dust-candidate-cities-only request (follow-up PR).

### Task 2: The dust bundle facts (intern)

**Files:**
- Modify: `src/two_bot/intern/air_quality.py` (`build_dust_event_bundle`, line ~48)
- Test: `tests/two_bot/test_air_quality_intern.py`

**Interfaces:**
- Consumes: `DustEvent.pm10_24h_mean` / `.who_pm10_multiple` (Task 1).
- Produces: dust-bundle `current_facts` labels `pm10_24h_mean_ug_m3`, `who_pm10_multiple`, `who_pm10_24h_guideline_ug_m3` — present ONLY when the event carries the data (the conditional-fact pattern, like `evidence_grade` on fire bundles).

- [ ] **Step 1: Write the failing intern tests**

```python
def test_build_dust_event_bundle_carries_who_pm10_anchor():
    event = _dust_event(dust_daily_max=2400.0, pm10_24h_mean=900.0,
                        who_pm10_multiple=20.0)
    bundle = build_dust_event_bundle(event)
    facts = {f["label"]: f.get("value") for f in bundle.current_facts}
    assert facts["pm10_24h_mean_ug_m3"] == 900.0
    assert facts["who_pm10_multiple"] == 20.0
    assert facts["who_pm10_24h_guideline_ug_m3"] == 45


def test_build_dust_event_bundle_omits_anchor_when_absent():
    event = _dust_event(dust_daily_max=2400.0, pm10_24h_mean=None,
                        who_pm10_multiple=None)
    bundle = build_dust_event_bundle(event)
    labels = [f["label"] for f in bundle.current_facts]
    assert "pm10_24h_mean_ug_m3" not in labels
    assert "who_pm10_multiple" not in labels
```

(Extend the existing dust-event fixture helper in this file with the two new keyword
defaults; do not fork a new helper.)

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/two_bot/test_air_quality_intern.py -k who_pm10 -v` → FAIL.

- [ ] **Step 3: Implement** in `build_dust_event_bundle`, after the existing dust facts:

```python
    if event.pm10_24h_mean is not None and event.who_pm10_multiple is not None:
        # Co-measured PM10 anchor (mean-vs-mean against the WHO 2021 PM10
        # 24h AQG). The `dust` value itself has no 24h-average standard —
        # the anchor claim is about PM10 during the event, never about dust.
        bundle.current_facts.extend([
            {"label": "pm10_24h_mean_ug_m3", "value": event.pm10_24h_mean, "unit": "μg/m³"},
            {"label": "who_pm10_multiple", "value": event.who_pm10_multiple},
            {"label": "who_pm10_24h_guideline_ug_m3", "value": 45},
        ])
```

(Match the file's actual construction style — if facts are built as one literal list,
append conditionally after construction exactly as fire.py's `evidence_grade` does.)

- [ ] **Step 4: Run** — same command → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/two_bot/intern/air_quality.py tests/two_bot/test_air_quality_intern.py
git commit -m "feat(dust): dust bundle carries the pre-computed PM10 WHO anchor (conditional facts)"
```

### Task 3: The prompt changes, test-first (writer + fact-check + critic)

**Files:**
- Modify: `src/two_bot/prompts/writer_prompt.py`, `src/two_bot/prompts/fact_check_prompt.py`, `src/two_bot/prompts/critic_prompt.py`
- Test: `tests/two_bot/test_prompts.py`

**Interfaces:**
- Consumes: the bundle facts from Task 2; `band_label` (exists at `src/two_bot/intern/temperature.py:347`); the sanctioned pre-existing phrase `above the 100 MW high-intensity threshold` (writer prompt frp_tier convention).
- Produces: the exact strings the tests below pin.

- [ ] **Step 1: Write the failing prompt tests** (append to `tests/two_bot/test_prompts.py`; every assertion targets NEW text — `who_multiple`/`dust_event` alone already appear in the prompt and would pass vacuously):

```python
class TestDetectionPlumbingBan:
    """P_tier (10 instances, 4 signal types, grade-capping at B in the
    grading corpus): internal detection taxonomy leaking into tweets.
    Observed actuals and bundle-designed anchors stay citable; the
    detector's own config never is."""

    def test_writer_bullet_present(self):
        assert "DETECTION PLUMBING IS NOT A FACT" in WRITER_SYSTEM_PROMPT
        assert "band_label" in WRITER_SYSTEM_PROMPT

    def test_observed_actuals_stay_sanctioned(self):
        assert "a fact about the storm" in WRITER_SYSTEM_PROMPT
        # Pre-existing sanctioned phrasing must SURVIVE this change:
        assert "above the 100 MW high-intensity threshold" in WRITER_SYSTEM_PROMPT

    def test_fact_check_pairing(self):
        assert "the bot's config is not a citable fact" in FACT_CHECK_SYSTEM_PROMPT.lower()
        assert "band_label" in FACT_CHECK_SYSTEM_PROMPT

    def test_critic_kill_condition(self):
        assert "internal_taxonomy_leak" in CRITIC_SYSTEM_PROMPT


class TestDustWhoAnchor:
    """P_dust (11/11 corpus instances): dust drafts carried no WHO-scale
    anchor. The anchor is the new co-measured PM10 bundle fact."""

    def test_dust_anchor_move_present_and_paired(self):
        assert "who_pm10_multiple" in WRITER_SYSTEM_PROMPT
        assert "who_pm10_multiple" in FACT_CHECK_SYSTEM_PROMPT
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/two_bot/test_prompts.py -k "Plumbing or DustWho" -v` → FAIL on every test.

- [ ] **Step 3: Writer prompt.** Insert this bullet in **WHAT NEVER SHIPS**, immediately
after the "Tier explainers" bullet (which it generalizes):

```markdown
- **DETECTION PLUMBING IS NOT A FACT.** The bot's own detection configuration —
  latitude-band names (`band_label`, e.g. "the northern subtropical band"), per-class
  editorial score thresholds, detector trigger definitions ("the rapid-intensification
  threshold is 30 kt in 24 hours") — is how the bot decided to LOOK, not something a
  reader can verify anywhere. Never cite it. What stays: observed actuals (the storm's
  real `delta_kt_24h` — "winds climbing 40 kt in 24 hours" is a fact about the storm,
  not the bot) and bundle-designed reader anchors (`frp_tier` words including "above
  the 100 MW high-intensity threshold", Saffir-Simpson, DHW alert levels, Beaufort,
  the WHO multiples). Test: is this a fact about the WORLD a reader could look up, or
  a fact about this bot's configuration? World: cite. Bot: never.
```

And extend the **PM2.5 / dust signal-kind conventions** bullet (Field conventions
section) with the dust anchor:

```markdown
  For `dust_event` bundles carrying `who_pm10_multiple`, that multiple is the scale
  anchor — *"during the event, PM10 averaged 20× the WHO 24-hour guideline"* — cite it
  verbatim. The claim is about co-measured PM10 (`pm10_24h_mean_ug_m3`), never about
  the dust concentration itself, and never a daily max against the 24h-mean guideline.
  When the bundle has no `who_pm10_multiple`, write the dust tweet without a WHO claim.
```

- [ ] **Step 4: Fact-check prompt.** Append rule (m) after rule (l):

```markdown
**m) Detection plumbing — the bot's config is not a citable fact.** Latitude-band
names (`band_label`), per-class editorial score thresholds, and detector trigger
definitions ("the rapid-intensification threshold is 30 kt in 24 hours") are internal
configuration: UNVERIFIABLE as tweet claims — a reader cannot verify the bot's config.
Distinguish: the OBSERVED `delta_kt_24h` ("winds climbed 40 kt in 24 hours") is
BUNDLE_FACT and fully citable; so are canonical published scales (Saffir-Simpson,
NOAA DHW alert levels, Beaufort), the bundle-designed `frp_tier` phrasings, and the
WHO multiples (`who_multiple`, `who_pm10_multiple`) — verify those against the bundle
values exactly as always. A PM10/WHO claim on a `dust_event` bundle must match
`who_pm10_multiple`/`pm10_24h_mean_ug_m3`; a WHO-multiple claim on a dust bundle
carrying NO such fields is UNVERIFIABLE.
```

- [ ] **Step 5: Critic prompt.** Under **Voice / craft**, add:

```markdown
- **Internal taxonomy leak** — the draft cites the bot's own detection config as if it
  were a published scale: a latitude-band name ("the absolute extreme threshold for
  the northern subtropical band"), a detector trigger definition ("the
  rapid-intensification threshold is 30 kt in 24 hours"), a score threshold. Observed
  actuals ("winds climbed 40 kt in 24 hours") and published scales (Saffir-Simpson,
  DHW levels, WHO multiples) are fine. Config-as-authority: kill.
```

And add to the kill_reason examples list:

```markdown
- `"internal_taxonomy_leak: cites the detector's band/threshold config as if it were a published scale"`
```

- [ ] **Step 6: Run** — `.venv/bin/python -m pytest tests/two_bot/test_prompts.py -q` → ALL pass (new and pre-existing).

- [ ] **Step 7: Commit**

```bash
git add src/two_bot/prompts/ tests/two_bot/test_prompts.py
git commit -m "feat(voice): detection-plumbing ban + dust WHO anchor, paired across writer/fact-check/critic (P_tier, P_dust)"
```

### Task 4: `writer_dryrun --type dust`

**Files:**
- Modify: `scripts/writer_dryrun.py`, `.github/workflows/writer-dryrun.yml`
- Test: `tests/test_writer_dryrun.py`

**Interfaces:**
- Consumes: `DustEvent` + `build_dust_event_bundle` (Tasks 1–2); the harness's existing `DEFAULTS` dict / `_build_bundle(args)` dispatch / `_print_bundle` (see the file — the fire/fire_footprint branches are the template).
- Produces: `--type dust` end-to-end through the same gate chain; Phalodi-class DEFAULTS (`dust_daily_max=2400.0`, `pm10_24h_mean=900.0` → multiple 20.0, city "Phalodi", country "India"); dust ignores the impact knobs (no `human_impact` on dust fixtures — state this in the docstring).

- [ ] **Step 1: Write the failing fixture tests** (append to `tests/test_writer_dryrun.py`):

```python
class TestDustFixture:
    def test_dust_bundle_carries_the_anchor_and_passes_evidence(self):
        bundle = _build_bundle(_args(type="dust"))
        assert bundle.signal_kind == "dust_event"
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["who_pm10_multiple"] == 20.0
        assert facts["pm10_24h_mean_ug_m3"] == 900.0
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_dust_fixture_never_attaches_impact(self):
        bundle = _build_bundle(_args(type="dust"))
        assert not getattr(bundle, "human_impact", None)
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/test_writer_dryrun.py -k Dust -v` → FAIL (`invalid choice: 'dust'` or KeyError on DEFAULTS keys).

- [ ] **Step 3: Implement.** In `scripts/writer_dryrun.py`: extend `DEFAULTS` with
`"dust_daily_max": 2400.0, "pm10_24h_mean": 900.0, "dust_city": "Phalodi",
"dust_country": "India", "dust_lat": 27.13, "dust_lon": 72.36`; add `"dust"` to the
`--type` choices + argparse knobs (`--dust-daily-max`, `--pm10-24h-mean`,
`--dust-city`, `--dust-country`); add the `_build_bundle` branch:

```python
    if args.type == "dust":
        who_multiple = (
            round(args.pm10_24h_mean / 45.0, 1)
            if args.pm10_24h_mean is not None else None
        )
        event = DustEvent(
            city=args.dust_city,
            country=args.dust_country,
            lat=args.dust_lat,
            lon=args.dust_lon,
            date=datetime.now(UTC).date().isoformat(),
            dust_daily_max=args.dust_daily_max,
            tier=_tier(args.dust_daily_max, DUST_TIERS),
            aod_daily_max=None,
            event_id=f"dryrun_dust_{args.dust_city.lower()}",
            pm10_24h_mean=args.pm10_24h_mean,
            who_pm10_multiple=who_multiple,
        )
        return build_dust_event_bundle(event)
```

(Import `DustEvent`, `DUST_TIERS`, `_tier` from `src.data.air_quality` and
`build_dust_event_bundle` from `src.two_bot.intern` alongside the existing imports —
if `_tier` is private, compute the tier with the same comparison the detector uses and
say so in a comment. `_print_bundle` gets a dust branch printing the anchor fields.)
In `.github/workflows/writer-dryrun.yml`: add `dust` to the `type` choice options —
inputs already flow via `INPUT_*` env (do not change that).

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest tests/test_writer_dryrun.py -q` → PASS; then the no-keys smoke: `.venv/bin/python scripts/writer_dryrun.py --type dust > /dev/null 2>&1; echo "exit=$?"` → `exit=2`.

- [ ] **Step 5: Commit**

```bash
git add scripts/writer_dryrun.py .github/workflows/writer-dryrun.yml tests/test_writer_dryrun.py
git commit -m "feat(dryrun): --type dust — Phalodi-class fixture with the PM10 WHO anchor"
```

### Task 5: Version, changelog, full gates

- [ ] **Step 1:** Bump `VERSION` by one minor (read it first; e.g. `0.9.82.0` → `0.9.83.0`).
- [ ] **Step 2:** Add a CHANGELOG `[Unreleased]` entry:

```markdown
### Voice floor — detection-plumbing ban + the dust WHO anchor (P_tier, P_dust)

- **[#<PR>]**: the writer may never cite the bot's own detection config
  (`band_label`, score thresholds, trigger definitions) — observed actuals and
  published scales stay; paired fact-check rule (m) + critic `internal_taxonomy_leak`
  kill. Dust events now carry a real scale anchor: co-measured PM10 24h mean vs the
  WHO 2021 PM10 guideline (45 μg/m³), pre-computed on the bundle
  (`who_pm10_multiple`); `writer_dryrun --type dust` added. Corpus evidence: P_tier
  10 instances/4 types; P_dust 11/11.
```

- [ ] **Step 3: Full local gates** — all three, in order, all green:

```bash
.venv/bin/python -m ruff check src/ tests/ scripts/writer_dryrun.py
.venv/bin/python -m mypy src/
THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q
```

- [ ] **Step 4: Commit** — `git add VERSION CHANGELOG.md && git commit -m "chore: bump + changelog for P_tier/P_dust voice floor"`

### Task 6: Push, PR, codex-xhigh loop, merge

- [ ] **Step 1:** `git push -u origin feat/voice-ptier-pdust` → `gh pr create --repo andrewzp/theheat --title "feat(voice): detection-plumbing ban + dust PM10 WHO anchor (P_tier, P_dust)" --body "<summarize tasks 1-5; include the request-weight note from Task 1>"`
- [ ] **Step 2:** codex-xhigh review loop per INDEX standing rules. Review prompt must ask it to hunt: (a) can the plumbing ban be read to outlaw `frp_tier_floor_mw` phrasing or observed `delta_kt_24h`? (b) is the PM10 anchor exact-match-safe end to end (event → bundle → prompts)? (c) does any test construct `CityAirQuality`/`DustEvent` positionally and now break? (d) prompt-law contradictions with rules a–l and the E1 fire section. Fix findings, re-run gates, loop until clean APPROVE; LAST round starts after the LAST edit.
- [ ] **Step 3:** Merge on green + verify the squash landed (INDEX rules verbatim).
- [ ] **Step 4: Live verifies:** (a) dispatch `gh workflow run writer-dryrun.yml --repo andrewzp/theheat -f type=dust` → read the log: the draft must carry the WHO-multiple phrasing and clear fact-check + critic; (b) after the next 2 alerts cycles, confirm the air-quality source still reports ≥90% coverage (`success`, not `degraded`) — if it degrades 2+ cycles, execute the Task-1 contingency as a follow-up PR.

**Success criteria for the row:** next graded corpus cycles show P_tier instances → 0
and dust drafts carrying the WHO anchor; both proposals move to Resolved in
IMPROVEMENT_PLAN.md.
