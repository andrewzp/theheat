# Lane 3 — Fire Footprint / Acreage Design

**Date:** 2026-04-20
**Branch:** `andrewzp/fire-footprint-gwis`
**Lane prompt:** `docs/conductor-lanes/03-fire-footprint.md`

## Goal

Upgrade wildfire coverage from point detections (FIRMS, "is there a fire at
lat/lon?") to footprint detections ("fire X has burned N hectares"). Acreage
is the viral headline; MW intensity is not.

## MVP scope

Per-fire tier-crossing signal only. A fire complex crosses a hectare tier →
we draft a tweet. We draft at most once per tier per complex.

Out of MVP (deferred to a follow-up): country-YTD percentile detection. The
per-fire signal is editorially self-sufficient and doesn't need historical
day-of-year baselines.

## Data source

**Primary: GWIS (EFFIS Global Wildfire Information System).**
`https://gwis.jrc.ec.europa.eu/` — public, no token required for the
majority of products. Goal product: active fire perimeters with cumulative
burned area per complex.

**Fallback: NIFC (US National Interagency Fire Center).** US-only, cleaner
schema, documented endpoint. Used only if GWIS mapping stalls.

**Access budget:** 60–90 minutes to get a working GWIS endpoint returning
structured data. If the timebox expires without a working call, switch to
NIFC for MVP and file GWIS as a follow-up. This decision is captured
explicitly at the top of `src/data/fire_footprint.py` with the URL,
auth posture, and date of the decision.

Endpoint URL, auth posture, and quota caveats go into `BRIEFING.md`
alongside other source notes.

## Tier ladder

```python
TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
```

Six tiers. 20K is the MVP floor — below that, a fire isn't viral regardless
of location. 1M is the generational-complex ceiling (Black Summer scale).
Each threshold is a round number that survives intact as a tweet headline.

Dedup rule: a complex's tier is the highest ladder index whose threshold is
≤ its current hectares. We draft iff `current_tier > state's_last_tier` for
that complex. Tiers are stored as integer indices, not hectare values, so
we can tune the ladder later without retroactively re-tweeting.

## Module — `src/data/fire_footprint.py`

```python
@dataclass
class FireComplex:
    complex_id: str           # GWIS's stable per-fire id
    name: str | None          # agency-assigned human name if present
    country: str
    region: str               # sub-national label ("Yakutia", "California")
    hectares: float           # cumulative burned area
    start_date: date | None   # ignition date if GWIS reports it
    tier: int                 # index into TIERS_HECTARES (0..5)
    event_id: str             # f"fire_footprint_{complex_id}_tier{tier}"

TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]

def fetch_active_fire_perimeters() -> list[FireComplex]: ...
def detect_tier_crossings(
    complexes: list[FireComplex],
    state: dict,
) -> list[FireComplex]: ...
def _classify_tier(hectares: float) -> int: ...
```

`fetch_active_fire_perimeters`:
- Hits GWIS, returns complexes with hectares ≥ `TIERS_HECTARES[0]`.
- On any network / parse error, returns `[]` (follows `firms.py` convention
  — a source failure is never fatal).
- No API key: returns `[]` with a debug log.

`detect_tier_crossings`:
- For each complex, compares its current tier to
  `state["fire_complex_tiers"].get(complex_id, -1)`.
- Emits the complex iff its tier is strictly higher.
- Does not mutate state. The main orchestrator writes the updated tier
  only after a draft is successfully saved (mirrors
  `state.record_event` usage by other sources).

## State additions — `src/state.py`

Add to `DEFAULT_STATE`:

```python
"fire_complex_tiers": {},   # {complex_id: last_tier_notified_index}
```

Merge semantics: take the max tier across concurrent writes, so two
simultaneous cron runs don't lose a tier bump (same pattern as
`co2_annual_count`).

Helper: `update_fire_complex_tier(state, complex_id, tier)` — sets the
entry to `max(current, new_tier)`.

No cleanup / pruning in MVP. Fire complexes are bounded (thousands globally
at any time), keys are small, and stale entries don't cause incorrect
behavior — they just sit. We can add a prune pass if the dict exceeds
~10K entries after a year.

## Scoring — `src/editorial/scoring.py`

```python
def score_fire_footprint(
    hectares: float,
    tier: int,
    *,
    region: str = "",
    has_name: bool = False,
) -> EditorialScore:
    shoulder_season = date.today().month in {1, 2, 3, 4, 11, 12}
    severity = 58 + tier * 6 + min(hectares, 1_500_000) / 30_000
    novelty = 52 + tier * 4 + (12 if shoulder_season else 0)
    timeliness = 88
    confidence = 82  # GWIS is authoritative
    shareability = 58 + tier * 5 + (10 if has_name else 0)
    reasons = [f"{int(hectares):,} ha cumulative burn area"]
    if has_name:
        reasons.append("named fire complex")
    if shoulder_season:
        reasons.append("out-of-season fire signal")
    if tier >= 3:  # 250K+ ha
        reasons.append("top-tier historical scale")
    if region and region != "Unknown":
        reasons.append(f"location hook: {region}")
    return _build_score(
        "fire_footprint",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=34,
        threshold=72,
        reasons=reasons[:3],
    )
```

Threshold 72 matches the lane prompt. The sensitivity 34 mirrors
`score_fire_event` — fires have human-impact risk.

## Template — `src/voice/templates.py`

```python
def fire_footprint_template(
    name: str | None,
    country: str,
    region: str,
    hectares: float,
) -> str:
    subject = name if name else f"A fire complex in {region}"
    acres = round(hectares * 2.47105, 0)
    variants = [
        f"{subject}, {country} has burned {int(hectares):,} hectares. That's {int(acres):,} acres.",
        f"{subject}: {int(hectares):,} hectares burned. {country}.",
        f"Fire footprint: {subject} in {country} now at {int(hectares):,} hectares.",
    ]
    return random.choice(variants)
```

Named and unnamed paths both produce a credible tweet. No "ravaging,"
"destroying," or meta-commentary.

## Generator — `src/voice/generator.py`

```python
def generate_fire_footprint_tweet(
    name: str | None,
    country: str,
    region: str,
    hectares: float,
    tier_hectares: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    subject = name if name else f"A fire complex in {region}"
    acres = round(hectares * 2.47105, 0)
    data = (
        f"Fire complex: {subject}. Country: {country}. Region: {region}. "
        f"Cumulative burned area: {int(hectares):,} hectares ({int(acres):,} acres). "
        f"Just crossed the {tier_hectares:,}-hectare threshold. "
        f"Source: GWIS (EFFIS Global Wildfire Information System). "
        f"Lead with the acreage and the subject. No 'ravaging' / 'raging' — "
        f"the number is the story. Frame honestly: the largest complex of "
        f"{date.today().year}, not 'largest ever.'"
    )
    return generate_tweet(
        data,
        category="fire_footprint",
        return_bundle=return_bundle,
        fallback_fn=templates.fire_footprint_template,
        fallback_args={
            "name": name, "country": country, "region": region,
            "hectares": hectares,
        },
    )
```

## Category hint — `src/editorial/candidates.py`

```python
CATEGORY_HINTS["fire_footprint"] = ("hectares", "burned", "complex")
```

These keywords signal the ranker that the candidate lands on the scale
anchor we care about. "MW" (FIRMS hint) is deliberately omitted —
footprint and intensity are distinct signals.

## Approval policy — `src/editorial/approval.py`

Add `"fire_footprint"` to the existing `manual_only` set alongside
`"fire"`. Fires carry human-impact risk; keep humans in the loop.

## Main orchestrator — `src/main.py`

New section between FIRMS (#2) and CO2 (#3), gated to **one run per day**
to keep GWIS load low:

```python
# 2b. Fire footprint / GWIS (once per day)
today_iso = date.today().isoformat()
if bot_state.get("fire_footprint_last_run") != today_iso:
    print("[alerts] Checking fire footprints (GWIS)...")
    ff_start = time.perf_counter()
    try:
        complexes = fire_footprint.fetch_active_fire_perimeters()
        crossings = fire_footprint.detect_tier_crossings(complexes, bot_state)
        # ... score → generate → save draft → update tier + event_id
        bot_state["fire_footprint_last_run"] = today_iso
    except Exception as e:
        state.log_error(bot_state, "fire_footprint", str(e))
```

Gate approach: a `fire_footprint_last_run` string in state. Simpler than
a weekday check because GWIS updates daily, not on a fixed weekday. If
the gate day boundary matters less than we think, we can relax it later.

Event flow per crossing:
1. Score via `score_fire_footprint`.
2. `_should_draft` check.
3. `generator.generate_fire_footprint_tweet(return_bundle=True)`.
4. `_review_context` with GWIS as source; facts include complex name,
   country, region, hectares, tier, days since ignition if available.
5. `_save_generated_draft` → on success, `state.record_event` AND
   `update_fire_complex_tier(bot_state, complex_id, tier)`.

## Tests — `tests/test_fire_footprint.py`

Mirrors `tests/test_firms.py` shape. At minimum:

- `fetch_active_fire_perimeters`: happy-path with mocked response,
  threshold filtering, malformed rows skipped, network error returns `[]`,
  empty env returns `[]`.
- `_classify_tier`: 19,999 → -1, 20,000 → 0, 99,999 → 1, 250,000 → 3,
  2,000,000 → 5.
- `detect_tier_crossings`: new complex with tier 2 emits; same complex at
  tier 2 again (next run) suppressed; same complex upgraded to tier 3
  re-emits.

Also extend existing tests:
- `tests/test_editorial_scoring.py`: `score_fire_footprint` passes at 50K ha
  and fails at a hypothetical sub-threshold case (if any reach it).
- `tests/test_editorial_approval.py`: `fire_footprint` returns
  `manual_only`.
- `tests/test_main.py`: run_alerts integration test stubs the fetcher,
  asserts a draft is created, asserts `fire_complex_tiers` is updated,
  asserts a second run in the same day is gated out.

## BRIEFING updates

- Pipeline diagram: add GWIS row alongside NASA FIRMS.
- Scoring-table row for `fire_footprint`.
- Secrets section: GWIS URL, auth posture, rate-limit notes (or a
  `# none required` if that's the reality after the endpoint mapping
  step).

## Definition of done

- [ ] GWIS (or NIFC fallback) endpoint mapped, URL documented in
      BRIEFING.
- [ ] Tier dedup prevents re-tweeting the same complex at the same tier.
- [ ] Named and unnamed complexes both produce acceptable tweets.
- [ ] `score_fire_footprint`, approval policy, category hint, template,
      generator, main integration all wired.
- [ ] Full suite green (BRIEFING notes 310 passing today; target
      ≥320 after this lane's additions).
- [ ] Pipeline diagram + scoring table updated.

## Non-goals (from lane prompt, restated)

- Not doing country-YTD percentile detection in MVP.
- Not computing burn areas from FIRMS detections ourselves. GWIS does it.
- Not merging this with FIRMS. Two distinct signals: detection (FIRMS) vs.
  footprint (GWIS).

## Decisions log

- **Data source:** GWIS first with a 60–90 min timebox; NIFC as
  MVP fallback if GWIS access stalls. Global coverage beats US-only if
  cheap; don't pay the cost if GWIS is painful.
- **MVP scope:** per-fire tier-crossing only. Country-YTD deferred.
- **Tier ladder:** `[20K, 50K, 100K, 250K, 500K, 1M]` hectares — round,
  shareable headlines over geometric cleanness.
- **Tier storage:** integer indices, not hectare values — lets us tune
  the ladder without retroactive re-tweeting.
- **Named-fire handling:** always include the complex; prefer the name
  when available; fall back to regional descriptor. Don't drop unnamed
  global complexes (would cost us Russia/Africa/Australia stories).
- **Cadence:** once-per-day gate via a `fire_footprint_last_run` field
  in state. Simpler than a fixed-weekday check.
- **Approval:** reuse the existing `manual_only` policy (add
  `"fire_footprint"` to the set). Fires carry human-impact risk.
- **Dedup identity:** `fire_footprint_{complex_id}_tier{N}` — mirrors
  GDACS's `gdacs_TC_{id}_tier{N}` pattern.
