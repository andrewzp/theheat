# Readable scientific graphic previews

The old landscape preview made source, date and scope labels too small at phone
width. Both existing temperature templates now use 1200 by 1500 pixels and a
40-pixel minimum for material text (13 pixels when displayed at 390 pixels wide).
The comparison and trajectory retain evidence types, complete source dates,
archive bounds, scope, provenance and explicit synthetic labels. Alt text and
scientific evidence qualification are unchanged. Measured wrapping preserves
whole labels; excessive qualifications and overlapping trajectory dates refuse
rendering instead of becoming clipped or smaller text.

Template `p31-preview-3-mobile` and implementation hashes invalidate old cache
identities. Existing private packages remain unchanged. No normal bot dependency,
model request, upload, attachment, source adapter or publication behavior changed.

## Verification

The optional actual-renderer verifier exercises both general fixtures and both
qualified synthetic GHCN specimens with ReportLab/Pillow and pdftoppm. It checks
PNG decoding/dimensions, embedded font identity, all emitted text at the minimum
font size, complete source/date/scope labels, unchanged alt text, deterministic
independent renders, cache reuse, tamper rejection and refusal before rasterization
when valid evidence cannot fit. All four full-size and 390-pixel specimens were
visually inspected. Synthetic layout approval is not scientific or publication
approval for future actual weather data.

316 focused media tests pass. The full offline Python profile, Ruff, mypy over
145 source files and the excluded verifier script, generated contracts and diff
checks pass. The dashboard was unchanged; its last validation belongs to the
shared-writer-request commit. Paid replay and production publication were not run.

Reproduce optional rendering using an environment with ReportLab and Pillow:

```sh
python scripts/verify_evidence_graphics.py --pdftoppm /absolute/path/to/pdftoppm --include-ghcn-adapter
```

No production dependency installation is needed. Draft attachment, durable asset
hosting, joint human review and exact revision-bound approval remain separate
unfinished work. A good-looking chart alone does not establish text/chart semantic
agreement or a certified weather record.
