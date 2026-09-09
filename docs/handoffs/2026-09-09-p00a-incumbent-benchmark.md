# P00a: frozen incumbent evidence, initial implementation

The September 8 incumbent is now frozen locally before further prompt or scientific pipeline changes. This is the first part of P00a, not a completed performance benchmark or a new adjudication of the old tweets.

## What is preserved

The private package is `.gstack/benchmarks/2026-09-08-incumbent/` in the original checkout. `.gstack/` is ignored by Git. It contains **186 exact files**: the original corpus and complete audited state snapshot, source/prompts/workflow/dependency declarations from incumbent Git commit `4b4d965c0ee040463f63893a7304e53012a909fe`, eight targeted scientific case labels, the existing fact/editorial/archive assessments, and the NOAA Barrow and Beaver Dams station files as retrieved in the original audit. No historical source code is executed; no source, model, metrics or posting API is called.

Package manifest SHA-256, retained outside the package as its integrity anchor:

`c928b8d3b4506e27f4579cae5e743458a28645f782fab51f1ab7326b9e543f38`

Original state snapshot SHA-256:

`659c8a5cfcadfe2a94376fa185218d96ae3039a7a3c0fd11943660a380ac8c44`

The creation and verification results reconcile **63 retained texts: 31 receipt-backed, seven posted-state/no-receipt, and 25 generation-memory-only/publication-unverified**. Twelve receipt-backed texts had been corroborated live during the assessment; eight selected individual pages had public view observations. This is not the complete account history. Selected lifetime views are not fixed-age outcomes, representative engagement, or evidence of causal lift.

The generic freezer and verifier are tracked, as are the scientific case labels and synthetic regression tests. The original 11 assessment/corpus/handoff artifacts remain uncommitted and unaltered by the freezer. Packages are created in a private directory, never overwritten by a second freeze, and checked against an independently retained manifest digest. Changed/missing/extra files, symlinks, duplicate IDs/texts, nonfinite or duplicate-key JSON, mismatched snapshot provenance and invented receipt/metric classifications fail verification.

## Use

From the original checkout:

```sh
.venv/bin/python scripts/freeze_incumbent_benchmark.py verify \
  .gstack/benchmarks/2026-09-08-incumbent \
  --manifest-sha256 c928b8d3b4506e27f4579cae5e743458a28645f782fab51f1ab7326b9e543f38
```

Use `freeze --help` for the generic local creation interface. It requires an immutable full Git SHA and explicit corpus, original snapshot, case labels, evidence files and output location. Keep private corpus packages outside tracked release artifacts; synthetic tests require no access to the original corpus or local package. The package's code snapshot records Git defaults and source, not proven effective historical environment overrides or a fully reproducible runtime.

## Scientific cases and evidence limits

`tests/fixtures/historical_scientific_cases.json` defines expected rejection categories and legitimate narrower claims, linked to original audit IDs. These are case specifications for P05–P07a, not proof that the current writer rejects them. They cover threshold-as-record, forecast-as-observation, unsupported humidity mechanisms, premature landfall, unclassified thermal detections, major rainfall product disagreement, record progression/later QC, and country/region confusion.

Keep the original distinctions: the Congo pixel's volcanic source is strongly suspected, not proven; Barrow's satellite/gauge discrepancy is unresolved, not a license to substitute a gauge as cell truth; Beaver Dams' later QC flag timing is unknown; its old-year comparison is not a literal immediate-previous-record assertion. Forecast evidence misuse does not establish the true observed maximum. T02 is not proven published. The exact historical JTWC bulletin and original precipitation granules are incomplete. Correcting vocabulary does not certify the underlying measurements. These targeted cases cannot establish a population error rate, and no public correction is authorized by this package.

## Validation and remaining acceptance

The focused offline suite covers evidence classification, exact byte retention, altered/missing manifests and payloads, receipt identity, unsafe paths, failed creation, immutable existing packages, case/text joins and reading the named Git commit despite a changed worktree. Ruff and mypy pass. The real local package has been verified against the independent digest above.

Still open: independent reference-event denominator, editor-ranked slate, blinded evidence-equivalent writing comparison, executable scientific rejection evaluation, and append-only supported post-age metrics. The original archive currently has no recent eligible receipt for prospective capture; access is not inferred from an idle metrics lane. No paid replay or human editorial judgment has been invented. P00a remains partial until those gates have their own evidence.
