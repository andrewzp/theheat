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

Files are capped at 16 MiB and output at 2 MiB. Duplicate keys and non-finite
numbers are refused, as are symlinked paths. An invalid envelope exits 2 with one
fixed error code.

## What the packet shows

- Each component's identity comes from its own codec: verified digests,
  binding fields or a recomputed plan, never a caller label or a filename. A
  component that fails its codec stays listed as `unsupported`, with the reason.
  Held components stay present. Exact copies count once, and different bytes under
  one identity are held as a conflict.
- Several revisions of one episode or report lineage, supplied without an order,
  are all held.
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
  global recall.
- `global_recall` and `coverage_denominator` are `null` because no supplied export
  carries qualified reference eligibility. Provider currentness is never inferred
  from a matching hash.
- The unmet requirements for each original package come from the supplied bytes,
  plus requirements no supported input can show. Every package stays `open`.
- The human-review packet lists the missing decisions and their source anchors.
  It records no decision, vote, translation, label, approval or reviewer identity.

`review.txt` escapes every control and non-ASCII character, so values remain
inert text.

Rainfall traces can also be audited on their own with
`scripts/audit_rainfall_opportunity.py --trace FILE --population FILE`.
