# P31: qualified GHCN evidence to local graphics

2026-09-09. Isolated `codex/p31-qualified-evidence-adapter` worktree, based on
`9dcb63d`. This is the next local integration slice after the P31 prototype.
Graphics are **not live**: no dashboard, publisher, upload, production dependency,
provider request, image-model call, public correction or publication flag changed.
The existing uncommitted assessment reports and historical tweet corpus remain
untouched in the original checkout.

## Implemented interface

`src/media/temperature_graphic_adapter.py` converts qualified individual GHCN
daily maximum/minimum record StoryBundles into the existing comparator or
trajectory specification. Call `temperature_graphic_spec(template, bundles,
expected_bundle_sha256=[...], synthetic=...)`. Each expected hash must come from
the caller's retained serialized bundle; `story_bundle_snapshot` applies the
existing finite P05 JSON boundary without mutating the input. The returned
`template`, `evidence`, and `expected_evidence_sha256` are the arguments accepted
by the optional local renderer.

- A comparator takes exactly one supported archive, monthly or calendar-date
  high/low bundle. It retains the candidate value and the exact selected tier's
  dated prior value. A generic prior year or peak/count is insufficient.
- A trajectory takes 2–8 separately qualified, ordered, consecutive daily
  bundles for the same station, variable and location. Every point must come
  from **one shared archive payload and retrieval snapshot**. A retained
  comparator that references another plotted day must agree with that point.
  Different revisions are refused, never silently reconciled under a later
  as-of timestamp. No gaps, interpolation, mixed stations or inferred streaks.
- P05's `audit_story_bundle` and P06/P09a's
  `ghcn.record_comparison_qualified` remain shared prerequisite gates. The adapter
  additionally checks the plotted fields against their retained warrants:
  source/station/event/date/variable identity; observed type and units; accepted
  candidate QC; candidate/comparator archive byte SHA equality; per-variable
  source-calendar coverage through the day before the candidate; accepted and
  excluded counts; minimum per-variable/per-period years; selected prior value,
  date, year and period; and agreement with headline/current/historical facts.
- The graph cannot acquire an official-record title. The headline is the exact
  candidate, such as `42.2°C observed`; the comparison footer states accepted
  GHCN archive/month/calendar sample scope and `no official record`.
- World forecasts, reanalysis/grid comparisons, absolute thresholds, anomalies,
  country aggregates, record clusters, legacy streaks and synthesis have no
  adapter in this slice and are explicitly refused. This is a limited supported
  subset, not an assertion that those sources are inherently unusable.

## Source dates, completeness and identity

GHCN evidence supplies a station calendar date, with reporting interval and
timezone unknown. The P31 contract now has an explicit `source_calendar_date`
time basis: points retain `valid_date` and never acquire an invented `valid_time`.
Date-only station graphics require a qualified adapter input binding. Exact
instant examples retain the original timestamp contract. `TEMPLATE_VERSION`
advances to `p31-preview-2`; the adapter version is `p31-ghcn-observed-1`.

The chart distinguishes a UTC **retrieval/as-of** timestamp from the station's
source calendar dates. It visibly states that interval/timezone are unknown;
trajectory axes and comparison dates do not label those unknown times UTC or
claim simultaneity. The bounded observed adapter conservatively refuses a source
calendar date later than the retrieval's UTC date instead of assuming a timezone.

Complete source-calendar coverage is not complete accepted-temperature history.
The new date-only comparator form retains accepted sample counts separately from
source calendar cells, missing cells and QC-rejected cells. Its `complete: true`
refers only to the declared `available_accepted_source_samples` contract with a
verified source calendar. It does not turn excluded cells into observations.
For monthly/calendar comparisons, the accepted count is specific to that period;
missing/QC counts describe the whole retained source interval. Alt text says so.
The latest accepted sample cutoff is retained separately from the verified
source-calendar cutoff; a regression exercises a missing final baseline day.

Each graphic packet retains every full serialized input StoryBundle, expected
bundle SHA, source evidence revision and exact baseline-payload SHA. Each point
also retains the archive-byte SHA and station source URL. The URL is derived
from the qualified GHCN product/station using the existing fetcher's exact
`.../daily/all/{station_id}.dly` route; it never claims the value came from an RSS
feed or substitutes a diff URL. Original synthetic source bytes are saved beside
the local specimens for reproduction.

Before rendering or cache reuse, the validator replays the adapter projection
from those retained inputs. Changing the graph value, comparator, scope, unit,
date or binding fails even if someone recalculates only the graph hash. The
renderer cache identity now also includes the adapter source-file SHA, alongside
the existing full graphic hash, template/version, renderer/contract sources,
font, backend, rasterizer and dimensions. Final bytes, alt text and manifest
remain checked on reuse, and `publication_approved` remains false.

### Trust boundary and known upstream limitation

The caller-supplied retained **full StoryBundle hash is the trust root**. A
changed comparator cannot keep using the caller's original hash. If the caller
deliberately selects a newly changed bundle hash, that is newly selected input
evidence; this adapter does not independently recover/certify the source again.

Existing GHCN `baseline.revision_id` is a chained digest: the qualification and
reconciliation stages include the previous revision ID when hashing again.
It is therefore treated as opaque lineage, not falsely verified as a self-hash
of the final retained baseline. The newly recorded baseline-payload SHA is useful
for exact forensic comparison; it is **not a second independent authenticity
proof**. Parent accepted this bounded interpretation and retained a producer
revision-semantics follow-up. No producer identity was changed in this slice.

The existing actual-tweet evidence limits remain: absent/unavailable archives do
not disprove old claims, current QC is not publication-time certainty, and a
local graphic is not a public correction. This code mutates no drafts, receipts,
evidence approval or posting state.

## Chart contract and demonstration evidence

Both outputs use the established dark Hot10 palette, DejaVu Sans Mono, exact
1200×675 footprint and existing ReportLab plots. These are explicitly **synthetic
private previews**, generated from engineered `.dly` source bytes through the
real parser, archive qualifier, detector and StoryBundle builders. No historical
bad tweet or invented purported actual weather event is used as an example.

| Question | Chart | Supplied evidence and permitted reading |
| --- | --- | --- |
| How does this accepted daily maximum compare with its dated archive comparator? | Two-point horizontal comparison | 42.2°C versus 41.8°C, +0.4°C, within 9,379 accepted synthetic GHCN samples; two excluded source cells remain explicit. |
| How do the daily maxima vary over this short event? | Six consecutive daily points and connecting line | 40.2°C through 42.2°C over September 3–8, all from one synthetic source snapshot; no longer-term trend or unmeasured interval is inferred. |

The comparator uses a quantitative temperature axis with exact numeric labels,
not bar lengths or a misleading zero-baseline comparison. Date-only observed
marks are solid; the original forecast specimens retain hollow/dashed marks.
No new color semantics or decorative elements were introduced.

Final specimens, each with `input.json`, full retained bundles, `manifest.json`,
`alt.txt`, PDF and embedded-font SVG in the same folder:

- Comparator: `/private/tmp/theheat-p31-evidence-adapter/.gstack/p31-adapter-previews/d83879683a71db23091f40226b726f75d5394d1ad60d4843b1560c5d511cc76e/preview.png`
- Trajectory: `/private/tmp/theheat-p31-evidence-adapter/.gstack/p31-adapter-previews/2d6512be1db94396c64d7fd555b126b783980571ec2993e620c957c8d457b1a1/preview.png`
- Source bytes: `/private/tmp/theheat-p31-evidence-adapter/.gstack/p31-adapter-previews/synthetic-source-9b95c3c88da12058d57e1f6536f6aa2761a72af8fca671e2ed04f3c8d32a3590.dly`

Both PNGs were visually inspected at original size. Independent code/visual
review confirmed source-date/as-of separation, unknown interval/timezone,
accepted-sample/no-official-record wording, units and source, synthetic labels,
asset hashes and retained bindings, with no clipping. This is not a physical
mobile-device test or an external SVG-consumer/production-backend certification.

## Reproduction and verification

Normal code/tests require only existing bot dependencies. ReportLab remains an
optional local renderer. The desktop bundle's Python 3.12.14 has ReportLab4.4.9
but no `requests`; the existing bot Python3.14.3 has requests and Pillow12.2.0.
Actual source-to-chart rendering used the existing ReportLab package via an
isolated `/tmp` import overlay with the bot runtime. No package was installed:

```sh
/Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python - <<'PY'
from pathlib import Path
root = Path('/tmp/theheat-p31-reportlab-runtime')
root.mkdir(mode=0o700, exist_ok=True)
target = Path('/Users/andrewpuschel/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages/reportlab')
link = root / 'reportlab'
if not link.exists():
    link.symlink_to(target, target_is_directory=True)
assert link.resolve() == target
PY
PYTHONPATH=/tmp/theheat-p31-reportlab-runtime /Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python scripts/preview_ghcn_graphics.py --pdftoppm /opt/homebrew/bin/pdftoppm
PYTHONPATH=/tmp/theheat-p31-reportlab-runtime /Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python scripts/verify_evidence_graphics.py --pdftoppm /opt/homebrew/bin/pdftoppm --include-ghcn-adapter
```

The existing pdftoppm26.04.0 rasterizer was reused. This verified local import
overlay is not a proposed production package layout or a guarantee of binary
compatibility across hosts. Normal bot imports never require ReportLab/PDF tools.

Focused source/contract validation:

```sh
/Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python -m pytest tests/test_evidence_graphic.py tests/test_temperature_graphic_adapter.py tests/test_ghcn.py tests/test_ghcn_format.py tests/test_ghcn_time_integrity.py tests/test_ghcn_scientific_supply.py tests/two_bot/test_evidence_contract.py -q
/Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python -m ruff check src/media/evidence_graphic.py src/media/evidence_graphic_render.py src/media/temperature_graphic_adapter.py tests/ghcn_graphic_helpers.py tests/test_temperature_graphic_adapter.py scripts/preview_ghcn_graphics.py scripts/verify_evidence_graphics.py
/Users/andrewpuschel/Documents/Claude/theheat/.venv/bin/python -m mypy src/media/evidence_graphic.py src/media/evidence_graphic_render.py src/media/temperature_graphic_adapter.py
```

The actual renderer verifier covers both original timestamp templates and both
new source-calendar specimens: independent deterministic outputs, 1200×675 PNGs,
exact embedded font, no-repeat rasterization on cache hits, asset/metadata tamper
refusal, adapter-code binding, modified projection refusal even with a new graph
hash, and dense-label refusal. The regression suite includes actual source-byte
correction between trajectory points, distinct accepted/source cutoffs, all six
supported record kinds, malformed/legacy/forecast refusals and immutable inputs.

Final focused result: **315 tests passed**; Ruff and mypy passed for all changed
Python files/production modules respectively. The final alt-text-only cutoff
clarification regenerated cache identities; both final PNG byte hashes are
identical to the independently visually reviewed versions.

## Remaining integration

1. Review representative **actual qualified** private bundles after the existing
   collection path supplies them; these fixtures prove behavior, not production
   coverage, visual appeal of real events or source availability.
2. Bind reviewed tweet text, selected bundles, chart/spec, template/adapter/font/
   backend revisions, alt text and final media bytes into joint P02/P07 approval.
   This adapter still has no posting approval or publisher hook.
3. Select and package a production backend, establish its CI verification,
   storage/concurrency/lifecycle behavior and mobile/external-consumer QA.
4. Add a separately qualified world/grid adapter and source-revision history
   reconciliation before supporting those evidence paths.
5. Follow up upstream on self-verifiable GHCN baseline revision semantics.

Root handles the later reviewed integration. This local-only slice needs no
runtime-policy source-list expansion today because no writer/publisher imports
it; future production wiring must inventory the adapter and graphic contract in
the exact policy/approval boundary. Do not label this full P31 completion.
