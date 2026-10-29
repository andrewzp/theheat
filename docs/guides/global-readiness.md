# Offline global-readiness packet

`scripts/summarize_global_readiness.py` joins detached exports of existing
components and reports what they can and cannot support. It reads one named
envelope file and writes JSON to stdout, or `readiness.json` and `review.txt`
into a new private directory. It never overwrites an existing directory. It makes
no source, database, model, platform or network request, and it never fetches,
renders or follows anything named in an export.

## Input envelope (schema 1)

```json
{"schema_version": 1, "assessment_cutoff": "2026-10-13T00:00:00Z",
 "components": [{"component_type": "physical_episode", "export": {}}]}
```

The envelope has exactly these three keys. `assessment_cutoff` is a UTC instant
ending in `Z`. At most 128 components are accepted. Each component has exactly
`component_type` and `export`, where `export` is the component's existing
detached JSON. Supported types:

- `source_products`: the product contract export.
- `rainfall_opportunity`: a rainfall trace, or its canonical population.
- `scientific_supply`: a GHCN supply envelope.
- `physical_episode`: an NHC episode binding.
- `report_development`: a report review projection.
- `coverage_assessment`: an unscored coverage assessment.
- `portfolio`: a manual portfolio plan.

Files are capped at 16 MiB. Duplicate keys, non-finite numbers and nesting deeper
than the structure bound are refused. An invalid envelope exits 2 with one fixed
error code and no traceback.

File handling:

- The input must be a regular file. A FIFO, device or directory is refused at
  once.
- Every path is walked through held no-follow directory descriptors. A symlink in
  any component is refused, and replacing a checked parent cannot redirect the
  read or the write.
- The exact `readiness.json` (or stdout) and `review.txt` bytes are encoded and
  checked against 2 MiB each before any directory or file is created. Oversized
  output is refused whole, never truncated. Report language fields keep the
  existing 35-byte limit.

## What the packet shows

- Each component's identity comes from its own codec: verified digests,
  binding fields or a recomputed plan, never a caller label or a filename. A
  component that fails its codec stays listed as `unsupported`, with the reason.
  Held components stay present. Exact copies count once, and different bytes under
  one identity are held as a conflict.
- Several revisions of one episode or report lineage, supplied without an order,
  are all held. This includes a revision whose own captures conflict: it still
  identifies a revision, so no other revision becomes current or joins exactly.
- Presence is separate from usability. `component_presence` reports each type as
  absent, supplied and usable, supplied but conflicting, or supplied but
  unsupported. Only absent types are listed as `missing`, and unmet requirements
  use the same distinction (for example `report_development_supplied_conflicting`).
- Joins use exact identities and hashes only:
  - trace to product leg, and trace to population;
  - supply or episode to product contract;
  - report to episode head;
  - coverage reference to report revision;
  - portfolio binding to episode head.

  A join never uses place, date, coordinates or headlines. A binding to a revision
  other than the one supplied is reported as stale.
- Evidence is listed separately as current, missing, corrected/superseded, held,
  untranslated, grouping-unresolved, trace-incomplete, dependency-blocked,
  unsupported and conflict-held.
- Measured rainfall opportunity appears in its own labelled section. It is not
  global recall. Only the populations named by current traces are audited. If one
  audit could not accept them all, the section is held; it is never truncated.
- `global_recall` and `coverage_denominator` are `null` because no supplied export
  carries qualified reference eligibility. Provider currentness is never inferred
  from a matching hash.
- The unmet requirements for each original package come from the supplied bytes,
  plus requirements no supported input can show. Every package stays `open`.
- The human-review packet lists the missing decisions and their source anchors.
  It records no decision, vote, translation, label, approval or reviewer identity.
  Conflicting and unsupported supplied exports are listed too.
- A supplied `human_reviewed` translation label is not proof of review. The
  envelope carries no trusted decision this tool can verify, so the claim stays
  untranslated and is listed as `translation_review_unverified`. The existing rule
  stands: only English claims need no translation.

`review.txt` escapes every control and non-ASCII character, so values remain
inert text.

Rainfall traces can also be audited on their own with
`scripts/audit_rainfall_opportunity.py --trace FILE --population FILE`. The tool
reads regular files only. It refuses a FIFO, device or directory at once, and it
refuses a symlink in any path component.

How the rainfall audit treats traces:

- Each trace is type-checked field by field. A malformed trace is held with a
  fixed reason, and the other traces are still audited.
- Completeness is derived from the trace's own retained bytes. A pending member, a
  missing window record, inconsistent counts or a missing finish keep a trace
  incomplete, whatever its supplied status says. A population count that differs
  from the canonical population makes the run unauditable.
- A day that has a held, conflicting or incomplete capture ends the complete
  window, even when other runs on that day are valid. The valid runs stay listed.
- The recorder keeps independent counters for every grid download and date probe.
  At most 32 of each are retained as records. When some are omitted, the trace is
  marked incomplete; the counts themselves are never truncated.
- HTTP `min`/`max` bound the counted components only. Redirects the HTTP client
  follows, and S3 credential and object requests, are listed as unmeasured. Cost
  stays unknown.
