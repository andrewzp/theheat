# P05: strict evidence and model-output boundaries

This is a local implementation handoff, based on released `f4773c5` (P04). It completes a bounded P05 boundary slice. It does not complete every adapter's provenance migration or certify any weather claim. Production publishing remains paused. No production state, public post, provider credential, model selection, or publication flag was changed.

## Behavior delivered

Triage, the main two-bot pipeline, the direct writer entry point, and the direct fact-check entry point reject malformed evidence before requesting a model response. Validation checks nonempty candidate identity, real ISO dates and timezone-qualified timestamps, finite JSON-compatible data, usable headline/fact shapes, and explicit primary source identity. Cached readings and incomplete human-impact warrants retain their existing rejection rules.

Source identity must occur in the raw candidate's primary fields, explicit `evidence`/`source`/`provenance` object, or a primary source-labeled current fact. An event ID, station name, editorial region, or URL buried in related news is insufficient. This is a minimum source-identity check. It does not establish source-record identity, acquisition time, freshness, product revision, geographic support, units, completeness, or authority. Those require adapter-specific contracts and the later scientific work.

Evidence rejection retains the received candidate, issue code, affected field, and repair instruction in the private suppression row. Unsupported objects, nonfinite numbers, cycles, and invalid Unicode use explicit diagnostic tags so the rejected packet remains serializable. Such tags cannot be reintroduced as repaired evidence. Nothing fills a missing source field with an invented identity.

The only adapter migration here is the small fire-family provenance addition. `FireEvent` can identify NASA FIRMS for its primary and known sibling product legs, or NOAA HMS for its known witness leg. An unknown witness remains unidentified. The adapter does **not** invent an exact primary satellite product, acquisition timestamp, interval, classification, or source revision that `FireEvent` did not retain. Its existing processing-day `when` is not thereby certified as an acquisition date.

Writer responses require the expected field types, exactly one nonblank tweet or kill reason, a bounded snake_case angle for a tweet, literal used-anchor substrings, and valid Unicode. Local validation is mandatory even when a provider accepts the schema. The writer's existing 280-character enforcement remains.

The fact checker requires supported, nonempty, literal extracted claims; it fails an unknown claim kind instead of dropping it. Every checker response owns its claim inventory, even if a prior extractor supplied claims. An independent local coverage check detects uncovered numbers, ISO dates, and recognizable capitalized entity spans. An empty or incomplete inventory cannot produce approval. This bounded check does not detect every paraphrase, implication, lowercase entity, or unsupported causal assertion.

Decoded JSON with a wrong contract fails immediately. It does not buy another repair pass. Duplicate JSON keys and nonfinite JSON numbers are rejected rather than being salvaged from a later object in the response. The existing tolerance for Markdown fences, preambles, comments, and trailing commas remains; this is not a new general JSON repair service.

## Model requests and cost

No paid or unpaid model-provider request was made during implementation or validation. No new model stage, extractor call, prompt expansion pass, candidate sampling pass, or editorial rewrite loop was added.

The existing writer request carries a provider-native schema: Anthropic `output_config.format`, or Gemini `response_mime_type` plus `response_json_schema`. The existing Gemini fact-check request carries its schema in that same call. Anthropic's schema, refusal handling, and initial tests are reused with attribution from [PR #463](https://github.com/andrewzp/theheat/pull/463), commit `61ae9ee4ab41f333de57ab2400925f2700af98d8`; this work adds stronger local validation and the Gemini path. It does not assume that PR was merged.

Requirements now specify `anthropic>=0.77` (the compatible floor from that patch) and `google-genai>=1.71` (the locally tested schema-capable floor). Installed versions used here were Anthropic 0.94.0 and Google GenAI 1.71.0. These are lower bounds, not a dependency lock. The [Google SDK's JSON-schema example](https://googleapis.github.io/python-genai/#json-response-schema) documents the same generate-content configuration; Google's [structured-output guidance](https://ai.google.dev/gemini-api/docs/structured-output) explicitly distinguishes syntactic structure from semantic correctness. Provider acceptance and billing recovery were not live-tested.

Remaining cost behavior is explicit:

- Invalid evidence or recognizable hazardous scientific claim: zero model calls at that boundary.
- Decoded writer/checker schema failure, unsupported extraction, or incomplete claim coverage: one existing response, then rejection; no paid repair request.
- Empty, truncated, or non-JSON response: the existing one-retry JSON budget remains.
- Overlength writer response: the existing two length retries remain. Nested malformed-response retries and transport retries can still multiply attempts within their existing bounds. This slice does not claim one call per candidate under every failure condition.
- Model choice, token limits, transport retry budgets, writer sample count, critic enablement, and revision flags remain unchanged. No cost saving or quality lift is claimed without prospective usage evidence.

Invalid-JSON exceptions from writer, fact checker, and critic no longer print entire responses. They expose only response size/type and a SHA-256 correlation token. Failed writer/checker outputs are retained in private suppression diagnostics, capped at 65,536 characters each with an explicit truncation flag and full-response digest. Existing suppression retention still applies; this is not an immutable archive. Other workflow logging is not comprehensively audited by this change.

## Honest adapter readiness

`tests/two_bot/test_evidence_contract.py::test_representative_source_bundle_migration_readiness` preserves 28 existing representative builder fixtures without adding fabricated provenance. Five have sufficient **minimum schema identity**; 23 are intentionally withheld for missing primary provenance. The separate calendar-record fixture is also withheld. The following is a fixture and code inventory, not a live source-health report or a coverage guarantee.

| Adapter lane | Status in this P05 branch | Work still required |
| --- | --- | --- |
| FIRMS / known NOAA HMS fire | Minimum identity passes representative fire fixture | Product/acquisition evidence, native classification, volcanic/static-source handling, independent incident warrant |
| Methane milestone, ozone seasonal event, coral DHW | Minimum identity passes representative fixtures | Source-specific retrieval, quality, time, scope, and claim warrants |
| Cyclone basin record | Minimum identity passes representative fixture | Typed archive and agency/wind-period warrants; schema presence does not certify a record |
| Calendar, monthly, all-time, anomaly, country, streak, simultaneous, cluster, and Hot10 temperature | Legacy packets remain unqualified; representative calendar/all-time/anomaly/simultaneous/Hot10 fixtures fail | P06 owns temperature evidence, provider-local dates, immutable baselines, source QC, member completeness, and aggregate withholding |
| Absolute/regional temperature | Not fully migrated or certified by P05; a generic evidence-type label is not complete provenance | P06 source/valid-time and per-member evidence contract; recheck readiness after integration |
| CO2, ENSO, oscillation transition/extreme | Representative fixtures fail primary provenance | Propagate actual source products/records and native valid periods |
| Fire footprint / NIFC-derived path | Representative fixture and dry-run fixture fail primary provenance | Propagate incident source and acquisition/update evidence without fabricating it |
| NWS severe weather, primary GDACS, Copernicus global flood, primary river flood, storm surge | Representative fixtures fail primary provenance | Named source and native advisory/activation/measurement times; an existing historical-context source label is insufficient |
| Cyclone rapid intensification, tier crossing, landfall, and land threat | Code carries primary source facts; not separately certified by the 28-fixture matrix | Complete issued/valid-time and agency-specific checks; completed landfall requires a dated incident warrant |
| Primary sea ice, ice mass, marine heatwave, extreme wave | Representative fixtures fail primary provenance | Native product, time/coverage, archive scope, and forecast/observed typing |
| Regional SST anomaly | Primary source is presently in historical context; primary lane is not fully migrated | Move retained primary provenance into the proper evidence contract; do not invent archive coverage |
| Drought, primary GPM precipitation, snow extreme, seasonal snow, synthesis | Representative fixtures fail primary provenance | Source records, spatial/integration windows, comparator scope, and constituent evidence |
| PM2.5 and dust | Code carries CAMS/Open-Meteo source identity; not certified by the representative matrix | Model-valid time, support, units, exposure wording, and quality handling |
| Wet-bulb | Legacy builder has no complete primary diagnostic warrant | Actual moisture inputs/method or an attributed diagnostic, valid time and source revision |
| Source witnesses | Some already carry source-labeled facts: GloFAS river, Open-Meteo precipitation, OSI SAF ice, NOAA STAR SST, disaster witnesses | Qualify individually. A fallback label does not establish scientific equivalence or freshness |
| USGS earthquake | Primary source identity exists, but the direct writer retains its out-of-scope rejection | No automatic scope expansion |

Orchestration routing/cap tests use an **opt-in** `synthetic_bundle_provenance` fixture when testing behavior after evidence readiness. It labels test-only evidence explicitly; it never changes production builders. The unmodified representative migration fixtures and strict boundary tests verify that missing real provenance remains blocked.

This release can reduce draft supply from unmigrated lanes. That reduction must appear as actionable evidence-repair suppression, not be described as restored global coverage. Do not bypass the gate by copying a source name from unrelated context or filling every adapter with an invented default. Root should integrate the concurrent P06 contracts before assessing temperature availability.

## Historical tweet regressions and evidence limits

The frozen eight-case specification at `tests/fixtures/historical_scientific_cases.json` remains unchanged. New synthetic claim/bundle regressions cover five of its failure classes before the fact-check model:

- T42/T30: alert threshold is not an archived rainfall record. A typed record comparator needs its own source, revision, candidate/date binding, unit, cutoff, and comparison scope. T42 has a receipt; T30 has posted state only. The July 6 record-field repair does not certify the old rainfall totals.
- T47/T60: forecast/model fallback is not an already recorded observation. Complete source temperature maxima were not recovered. P06 supplies more precise temperature-domain enforcement.
- T47: temperature alone cannot justify an event-specific wet-bulb, heat-index, or humidex diagnostic. A typed diagnostic needs attributed evidence or moisture inputs plus a method; shape validation alone does not validate the method.
- T52: completed landfall requires dated confirmation. Unrelated forecast/negation clauses cannot authorize a completed-landfall clause. The exact original JTWC bulletin and historical regex causal path remain unproven; agency wind averaging periods differ.
- T46: ordinary fire/wildfire classification requires an independently attributed vegetation-fire incident warrant. The classification-only Congo wording is rejected even without the unsupported causal ending. Thermal anomaly/FRP/native-confidence wording remains eligible. The exact pixel is not proven volcanic; the unsupported convective-lid explanation remains a separate defect.

T53's rainfall-product disagreement, T34/T43's record progression/later QC, and T02's country/region confusion retain their full limits in the frozen specification. They are **not claimed as fixed by these lexical guards**. T53 remains unreconciled across differing spatial/time support; June 25's later QFLAG=S does not prove when the flag was added; T02 remains generation-memory-only with unverified publication. P04/P06 and later source-specific work own the relevant fixes. No public correction is authorized or produced by P05.

## Integration and validation

All work is local on `codex/p05-strict-schemas` in `/tmp/theheat-p05-schemas`. No VERSION bump, push, deployment, or production model test belongs to this handoff. Root owns integration with the newer main and its protected-state/authority changes. Preserve P06's small `temperature_aggregate_failures` hooks when merging the overlapping `evidence_contract.py` and `fact_check.py` changes. Preserve the original untracked assessment and corpus in the main checkout.

The implementation adds only optional nested suppression/model-output diagnostics, no new top-level durable state key or dashboard contract. Existing Python/JavaScript JSON persistence retains complete suppression rows. Dashboard code is unchanged.

Validation: **2,871 Python tests passed; 41 paid voice replay tests were excluded**. A final small defensive fix preserves a diagnostic for a self-referencing dataclass; all 93 strict-boundary tests pass after that fix. Focused decoded-output/retry tests pass, and existing malformed-JSON and length retry tests remain covered. Ruff and mypy pass (125 source files); `git diff --check` is clean. Root should rerun the full suite after integration. The one observed warning is an upstream Google SDK/Python 3.14 deprecation. Excluding paid replay tests is not a quality benchmark.
