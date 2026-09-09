# P07a: offline evaluation of retained scientific failures

This implements bounded executable observations against the existing P00a freeze. It does not finish P07, certify current writing quality, or authorize posting or public corrections. No runtime source adapter, prompt, publishing flag or production state is changed.

## What the runner evaluates

`scripts/evaluate_historical_cases.py` verifies the private incumbent package with its externally retained manifest digest before loading any text. It requires the current eight-case adjudication catalog to match the frozen catalog. The original findings, publication classes and evidence limits remain unchanged.

The new `tests/fixtures/historical_scientific_probes.json` specifies synthetic structural probes, explicit expected codes and remaining scientific requirements. The existing strict-contract historical tests now consume that registry and require the relevant failure code, rather than accepting any failed check. Separate pipeline tests use the same registry. This preserves the original five rejection shapes and adds isolated classification, cause, forecast-tense and qualifier variants.

The report distinguishes four forms of evidence:

1. **Retained packet availability.** Missing packets and incomplete legacy summaries remain missing/incomplete. The runner does not invent required fields to claim historical replay. A complete but unqualified packet can exercise the current generation preflight with the writer trapped; such an abstention is an input-contract observation, not a scientific finding.
2. **Exact retained text with synthetic evidence.** The original private text is supplied to the real deterministic checker against an explicitly engineered structural bundle. This measures whether the specific claim wording triggers its targeted rule. It is not a replay of the complete original source packet or runtime.
3. **Synthetic text through current pipeline gates.** The writer result is injected, the optional LLM safety key is disabled inside a restoring local patch, and the writer sample count is fixed at one. The production safety regex, honesty checks and factual checks run. No safety-model or writer performance is evaluated. Controls stop at the intercepted checker boundary and remain `verification_required`.
4. **Actual frozen NOAA source bytes.** Current GHCN parser, cutoff, acceptance and affected-claim functions process the frozen Beaver Dams file against a deep copy of retained state. This checks current QC exclusion, accepted-sample progression, linked findings, unknown publication-time QC and unchanged retained drafts. Original state is not written.

Expected codes must be present. An unrelated rejection, missing provenance, pipeline error or model-boundary interception cannot satisfy a targeted scientific rejection. An unexpected provider/network/process attempt raises outside production `Exception` handlers and aborts the run. Socket connect/send/DNS, subprocess launch and writer/critic provider boundaries are trapped. All generated diagnostic streams are captured; reports export fixed codes rather than raw rejection text. This is an offline test harness, not a general sandbox for hostile Python.

## Adjudication and remaining gaps

| Frozen case | Bounded executable observation | Still not established |
| --- | --- | --- |
| T42/T30 threshold construction | Require `unwarranted_record`; copied alert threshold is insufficient | Accuracy of each rainfall total, original integration window and product |
| T47/T60 forecast | Require forecast-as-observation rejection of exact retained wording and synthetic variants | Actual contemporaneous observed maximum or full original forecast packet |
| T47 humidity | Require missing diagnostic evidence rejection | Every causal paraphrase; local climatology needs its own source |
| T52 Bavi | Require `unconfirmed_landfall`; a qualifier in a different clause does not excuse completed landfall | Exact JTWC bulletin recovery, subday observation/position reconciliation, independent certification of typed confirmation |
| T46 Congo | Separately require incident classification and atmospheric-cause rejection; thermal-only control still needs verification | Exact pixel classification; a proven volcanic source; vegetation incident or atmospheric cause |
| T53 Barrow | Expose `verification_required` and the unmet product-disagreement quarantine capability | Original granules, masks, units, footprint, windows and qualified cross-product reconciliation; gauge is not cell truth |
| T34/T43 Beaver Dams | Parse frozen source bytes; exclude current suspect candidate; retain an affected-claim finding and source progression | Publication-time QC timing, official record certification or publication-time accepted history |
| T02 country label | Preserve memory-only/unverified-publication classification; expose unmet boundary-check capability | Versioned administrative boundary validation in this pipeline; no invented public receipt |

The Bavi audit's dated offshore-position finding remains the adjudicated baseline, not a newly retrieved advisory. Congo remains strong suspicion concerning volcanic classification, independently of its confirmed unsupported mechanism. T02 remains a retained-generation defect whose publication is unverified.

The full Beaver file includes an additional accepted intervening source cell beyond the June12 point used in the P06 engineered-support fixture. The newly derived value/date and current accepted comparator are recorded only in the private run report, with the source digest and publication-time limits. The existing P06 fixture remains valid for its explicitly engineered source calendar; it is not relabeled as the full historical archive. Neither a blank flag nor complete availability of source cells certifies a complete or official record history.

## Run and review

From the implementation checkout, using its Python environment:

```bash
python scripts/evaluate_historical_cases.py \
  /Users/andrewpuschel/Documents/Claude/theheat/.gstack/benchmarks/2026-09-08-incumbent \
  --manifest-sha256 c928b8d3b4506e27f4579cae5e743458a28645f782fab51f1ab7326b9e543f38 \
  --repository /Users/andrewpuschel/Documents/Claude/theheat \
  --output /Users/andrewpuschel/Documents/Claude/theheat/.gstack/benchmarks/NEW-P07A-RUN
```

Output must be a new direct child of the original checkout's Git-ignored `.gstack/benchmarks`. The runner rejects existing paths, symlink traversal and nonignored destinations. The output directory is mode700 and files are mode600. `private-text-manifest.json` contains exact text, original corpus rows and retained draft context; it must remain private and untracked. `report.json` contains case IDs, hashes, codes, retained publication classes and evidence limits; it contains no exact tweet text. It also records current runtime-source, probe-specification, catalog and baseline hashes. The CLI prints only output location, hashes and any unexpected observation IDs, and exits nonzero if a specified expectation fails.

The 186-file incumbent package remains immutable. Its manifest digest is still `c928b8d3b4506e27f4579cae5e743458a28645f782fab51f1ab7326b9e543f38`; the original corpus/state join retains 31 receipt-backed texts, 7 posted-state texts without receipts and 25 generation-memory texts with unverified publication. Targeted cases are not a sample suitable for estimating account-wide quality, event recall, worldwide reach or cost savings.

The first local run produced nine targeted synthetic rejections, seven controls/unmet-capability probes requiring further verification, and seven targeted exact-text checks across the relevant case references (T47 participates in two failure classes). These are per-probe observations, not a quality score. Missing/incomplete retained packets are not counted as scientific successes. No model, provider or public-platform call was made; schema repair/retry and model cost were not exercised.

## Validation and next work

Focused validation covers the runner, freeze integrity, strict contracts, P06 temperature chronology/QC and compact-prompt contracts. The initial expanded run passed 303 tests, Ruff and direct mypy. Tests use synthetic copy and reuse P06 engineered source serialization; private corpus tests are performed by the verified local runner.

Re-run against the parent's integrated source before relying on its recorded runtime hashes. Review the adjudication/specification and private report before acceptance. Separate work remains for original-product recovery and reconciliation, versioned geography, independent global reference-event denominators, editor-ranked selection, blind evidence-equivalent writing judgments and prospective fixed-age metrics. A passing bounded probe provides no evidence for those unfinished tasks.
