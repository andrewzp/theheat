# P31: local evidence-bound graphics prototype

2026-09-09. Based on scientific integration commit `36997a8` in isolated branch
`codex/p31-verified-graphics`. This is the first local P31 slice, not production
graphics completion. It changes no dashboard, publishing flags, upload path,
existing image, provider integration, production dependency, or VERSION.

## What is implemented

- `src/media/evidence_graphic.py`: renderer-independent validation and alt text,
  bound to the caller's exact expected evidence SHA using the existing P02
  canonical fingerprint. The renderer never chooses or edits evidence.
- `src/media/evidence_graphic_render.py`: optional ReportLab `LinePlot` backend,
  generating a 1200×675 PNG plus vector SVG/PDF, exact `input.json`, `alt.txt`, and
  `manifest.json`. No network or language-model calls. Imports of ReportLab occur
  only inside the explicit local renderer function.
- Two templates: one candidate versus a dated archive comparator, and a 2–8 point
  temperature trajectory. Daily maximum and daily minimum temperature are the
  only supported variables. The comparator headline is derived directly from
  the candidate, for example `40.2°C forecast`; it never declares a record.
- Exact source product, URL, source revision SHA, valid timestamp, temperature
  unit, observed/forecast/reanalysis class, scope, and evidence cutoff are required.
  Full source URLs and revision hashes remain in the input artifact. Source
  product, variable, scope, dates, units, and class are visible on the chart.
- A comparator must have explicit complete coverage, matching positive actual
  and expected sample counts, an observed/reanalysis comparator in its interval,
  and a cutoff strictly before the candidate and no later than the evidence cutoff.
  Mixed units, missing/nonfinite/coerced values, unsupported variables, incomplete
  coverage, undated sources, and obsolete caller evidence bindings are rejected.
- Observations/reanalysis cannot be after the evidence cutoff. This bounded
  prototype accepts only forecasts valid after that cutoff. Trajectory times are
  strictly increasing; observations cannot follow forecasts; reanalysis cannot be
  mixed with other trajectory classes. Observations are solid, forecasts are
  hollow/dashed, including the transition from the last observation.
- Cache identity contains exact evidence hash, template/version, renderer and
  contract source-file hashes, ReportLab version, rasterizer binary SHA, font SHA,
  and dimensions. Cache reuse checks exact input, asset hashes, metadata and
  `publication_approved: false`. Changed or partial cached artifacts are refused;
  they are never silently overwritten. Long labels and overlapping time labels
  are refused instead of clipped or crammed into an unreadable image.

Validation here establishes a structural contract and exact binding, **not truth
of the supplied weather data**. A caller could supply a fabricated but structurally
valid packet with a matching hash. The production adapter must select actual
reviewed P05/P06 evidence, independently qualify its baseline and source revisions,
and pass the expected hash from that review. The synthetic fixture CLI computes
its own fixture hash solely to demonstrate this interface.

## Branding and local rendering environment

Reviewed existing `src/media/hot10_card.py`, its bundled DejaVu Sans Mono font and
license, and `brand/handoff/Brand Book.html`. The prototype uses the actual Hot10
dark palette, warm forecast accent and bundled mono font. It does not fetch the
brand book's unbundled Inter/IBM Plex Mono faces. The PDF embeds the TTF; the SVG
embeds the same exact font as a data-URL `@font-face`. SVG title/description carry
the generated title and full alt text. Numeric ISO dates avoid locale-sensitive
month names. PNGs are rasterized from the newly generated PDF; no existing images
are modified.

The configured desktop runtime had no Matplotlib or other available general
charting package tested during this slice. Its existing ReportLab chart library
worked for scientific plots. ReportLab's direct PNG backend was unavailable, so
the parent approved the existing optional local PDF rasterizer for this prototype.

Verified runtime on this host:

- Python 3.12.14 at
  `/Users/andrewpuschel/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`
- ReportLab 4.4.9 and Pillow 12.3.0 in that bundle. Pillow is used only to inspect
  generated PNG dimensions and format in the standalone verification script.
- Poppler `pdftoppm` 26.04.0 at `/opt/homebrew/bin/pdftoppm`.
- Existing repository font `src/media/fonts/DejaVuSansMono.ttf`.

These are **local tools, not assumed production dependencies**. No dependency was
added. Normal project tests and bot imports do not require this optional backend.
Byte-identical independent renders were verified in this environment; cross-host
rasterizer/shared-library equivalence is not established. Production packaging
must pin/test its actual backend and full font/rendering environment.

## Reproduce and inspect

From the worktree or integrated repository, render the explicitly synthetic fixture:

```sh
/Users/andrewpuschel/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/preview_evidence_graphics.py --pdftoppm /opt/homebrew/bin/pdftoppm
```

Run actual rendering verification separately from normal pytest:

```sh
/Users/andrewpuschel/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/verify_evidence_graphics.py --pdftoppm /opt/homebrew/bin/pdftoppm
```

Private previews at handoff, each with `input.json`, `manifest.json`, `alt.txt`,
`preview.svg`, and `preview.pdf` in the same folder:

- Comparator PNG:
  `/private/tmp/theheat-p31-graphics/.gstack/p31-previews/5461c21a39b0045efcb1858772578bbdaf14e9698a44b4847c014f732a7481c0/preview.png`
- Trajectory PNG:
  `/private/tmp/theheat-p31-graphics/.gstack/p31-previews/a3c60a04ef187c831a8cc4d746cdbe197fe3c8b87586bb9181a546b704ff298e/preview.png`

Rendered artifacts are ignored private local files; the committed source fixture
is `tests/fixtures/evidence_graphics_synthetic.json`. Every demonstration is visibly
marked synthetic/private and states that its values are not actual weather. These
examples do not reuse historical tweets or imply any real event, correction, or
forecast. Both final PNGs were visually inspected at full size for readable text,
source/date/cutoff visibility and forecast/observation distinction.

## Validation completed

- `pytest tests/test_evidence_graphic.py -q`: 31 passed without the optional renderer.
- Ruff on the five new Python files: passed.
- Mypy on the two new source modules: passed.
- Actual bundled-runtime verification: both templates produced byte-identical
  independent renders and 1200×675 PNGs; repeat requests reused the cache without
  rasterizing; asset and approval-metadata tampering was rejected. Embedded SVG
  font bytes match the bound font SHA, and SVG description equals full alt text.
  A dense trajectory that would overlap timestamp labels was rejected.
- Independent review prompted explicit variable labels, a portable embedded SVG
  font, and locale-independent dates. The parent requested the fact-first
  comparator headline. All were implemented and the final outputs re-inspected.
  Parent visual review and independent re-review cleared this local prototype.
  SVG font bytes are verified, but visual rendering in external SVG consumers
  has not been exercised; the delivered PNG/PDF path received visual review.

## Remaining P31 integration

1. Add an adapter from actual qualified P05/P06 evidence, retaining reviewed outer
   evidence revision as well as the exact chart packet. Do not turn absent archives,
   sparse history, models, reanalysis or sampled networks into observed official
   records. Validate spatial/temporal comparability, actual coverage and source
   products before calling this interface; this module does not infer them.
2. Bind reviewed tweet text, exact chart packet, template/font/renderer revision,
   final media bytes and alt text into one posting approval. Editing any of these
   must invalidate obsolete checks/approval through P02. This prototype has no
   approval state mutation or posting capability.
3. Choose and package a production rendering backend, pin its complete environment,
   and add CI renderer verification there. Keep the local PDF toolchain optional
   until that decision. Add storage lifecycle/concurrency/error recovery appropriate
   to that production adapter; current cache refuses partial/inconsistent entries.
4. Review actual-data chart/editorial examples privately with the source evidence,
   test real mobile presentation, and approve upload/publisher integration separately.
   Existing tweet-assessment evidence limits remain unchanged. No public correction
   or production publishing was activated by this work.
