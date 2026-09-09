# P07: compact, evidence-grounded editorial prompts

Local implementation on top of main `10832af`, in `/tmp/theheat-p07-compact-prompts` on `codex/p07-compact-prompts`. This is a prompt-policy change, not a production quality result.

Andrew's September 9 priorities govern this work: shorter and harder-hitting tweets, useful worldwide coverage, reliable sources, useful graphics, lower LLM cost, and less breakage. The completed assessment and actual-tweet evidence remain the baseline. This change advances writing and prompt economy; it does not claim to repair source coverage or produce graphics.

## Editorial behavior requested

The writer leads with the strongest supported fact and defaults to one complete sentence. A second sentence must add essential qualification or genuinely new sourced information. There is no minimum character count and no 240–270-character target. Required place, units, date/window, forecast status, uncertainty and archive scope outrank optional color.

Writer, checker and critic now agree on these points:

- A complete measurement or comparison can be the finished report. A grand system explanation, causal ending, joke or rhetorical flourish is not required.
- Reach and engagement are intended outcomes. Hype, fabricated context and unsupported scientific implications are failures.
- Necessary forecast/estimated/may/likely/about qualifiers are evidence discipline. There is no blanket prohibition on uncertainty.
- A later human or model is never promised as a repair mechanism.
- Same hazard does not mean same story worldwide. Category history and partial pending excerpts are context, not a worldwide category veto. A material update can earn follow-up coverage.
- The critic judges this draft; it cannot kill, edit, approve or retract another pending item, and cannot assume a missed event will return tomorrow.
- Short archives are not an automatic kill condition or automatic evidence of an extraordinary climate signal. Scope and significance are assessed together.

All old positive exemplars were removed, including the problematic geographical explanations, forecast-to-observation examples, FRP/suppression implications, implied coral-buffer failure and invented claim that heat records previously arrived one city at a time. Historical posts are not supplied as validated positive training examples.

## Scientific constraints retained

The writer and checker share one fixed evidence block. The critic has a shorter review summary so the expensive critic call does not grow simply by repeating every source field. All three retain the source/evidence-class, time, scope, record-versus-threshold, snapshot-versus-trend, member-evidence, thermal-versus-incident, cyclone-confirmation, marine/air-quality and impact-attribution requirements.

The compact policy specifically refuses to infer this event's cause from general geography, seasonality, climate-mechanism notes or reef context. A familiar definition can be paraphrased narrowly; it cannot stand in for a missing current-event warrant. Regional anomalies stay scoped to N sampled cities and daily maxima. A model/forecast stays a model/forecast. A limited archive stays limited. Rainfall ratios require a compatible actual normal. Thermal detection confidence cannot establish vegetation-fire identity or cause. A cyclone label or track proximity cannot establish completed landfall.

The concurrent P05/P06 deterministic guards remain the enforcement baseline. No prompt change weakens them. Current record comparisons are deliberately demanding: GHCN needs its available/accepted archive wording and exact verified cutoff; forecast/ERA5 comparisons need forecast, ERA5 reanalysis, cutoff, unverified recent-gap wording where relevant, and sampled scope. The writer is told to choose a simpler supported value/forecast when a defensible record comparison cannot fit. Moving those qualifiers to a graphic/source card would require a separate scientific and revision-binding review; this patch does not do that.

The frozen eight historical cases and their limits are unchanged. The new prompt tests map all eight to policy coverage but do not pretend that finding a phrase proves model compliance. Executable P05/P06 historical negative tests remain separate and must be retained at integration. In particular: T46 is not proven volcanic; T53's rain discrepancy is unreconciled across different support/windows; the later GHCN quality flag has unknown addition time; T02's publication is unverified.

## Measured prompt size

Measured from the actual assembled system strings against `10832af`, excluding per-candidate bundle/memory and optional user-message riders:

| Call | Before characters | After characters | Character reduction | Before/after whitespace words |
| --- | ---: | ---: | ---: | ---: |
| Writer | 60,404 | 9,854 | 83.7% | 9,050 / 1,293 |
| Fact checker | 26,915 | 9,077 | 66.3% | 3,859 / 1,180 |
| Critic | 8,933 | 5,939 | 33.5% | 1,376 / 813 |
| One of each | 96,252 | 24,870 | 74.2% | — |

These are character/word measurements, **not provider-token counts, billed savings or throughput results**. Bundle size, caching, output length, retries and call frequency still matter. The first request after a changed system prefix will not reuse the prior prefix's cache entry; subsequent identical requests retain the existing caching mechanism.

No new model stage, candidate variant, prompt-repair pass, source lookup or provider request was added or run. Models, max tokens, sampling, retry budgets, critique/revision flags and publication flags are unchanged. The existing code comments that describe the old approximately 15.1K-token writer prompt are historical; they are not a fresh token count for this prompt.

## Runtime and test compatibility

Only the three prompt modules, prompt-oriented tests and this handoff change. The writer's current seven-field JSON output, fact-check claim kinds/fields, critic verdict modes and runtime format placeholders remain compatible. Optional impact/cross-signal riders remain in the user message; Anthropic's cached system wrapper is unchanged.

Tests that locked stale policy phrases and required the old positive exemplars were removed or replaced. Their required behaviors survive in the shared scientific policy and external executable guards. New tests cover exact template fields, JSON/parser compatibility, a short complete response, bounded prompt growth, retired contradictory instructions, historical-policy coverage, and mocked Gemini requests containing the intended policy exactly once in one existing call. The existing Anthropic cache-identity and optional-rider wiring tests remain.

Focused validation passed 217 tests. After final critic shortening, all 34 prompt-contract tests passed. The full offline suite passed **2,994 tests; 41 paid voice replay tests were excluded**. Ruff passes; mypy passes for 128 source files. No paid replay or live model quality evaluation was run.

## Integration and evidence still needed

Root owns review, integration and release; no VERSION, push, deployment or production-state change was made here. Preserve P05's output validation and P06's source/temperature gates when merging. A small overlap in `tests/two_bot/test_writer.py`, `tests/test_writer_dryrun.py` and `tests/test_news_enrich.py` should retain P05's strict fixtures while retiring the old prompt phrase/exemplar locks.

This branch changes no approval fingerprint/version constant and does not revalidate existing drafts. Pre-policy-change checks must not be presented as evidence of compliance with P07. Root's last live snapshot contained 40 drafts with no review_binding or approval_binding, plus two preserved old intent IDs; root will refresh this before release. That observation is not a permanent migration or policy-version guarantee. Runtime policy-version binding remains open before automatic activation, and the full P07 package is not complete.

P08's proposed `kill_scope`/`kill_code` metadata is intentionally absent from this independently shippable prompt contract. A separate prompt-only follow-up can be integrated atomically with P08's writer schema/parser; asking for those fields before the parser supports them would create a P05 contract failure.

Actual craft improvement needs blind human comparisons on the same independently qualified evidence, recording unnecessary words, lost qualifiers, clarity and editing effort. Actual cost improvement needs provider-attributed tokens/calls/retries/cache usage and observed cost per usable draft/publication/major event. Virality needs appropriately aged audience metrics and an evaluation design; neither the retained selective view counts nor this offline work proves it.
