# Offline Google token-price scenario

The cumulative ledger deliberately leaves Google calls unpriced. The separate
retained usage window has enough detail to calculate a useful **token component
scenario** for some responses. This release adds a pure projection and offline
command without changing runtime capture, the historical ledger or any model.

```sh
python scripts/usage_cost_scenario.py --state private-state.json \
  --scenario google-standard-paid-2026-10-02
```

Use `--window private-window.json` instead when the file contains only the
`llm_usage_observations` envelope. The two input flags are mutually exclusive.
There is no default scenario, network access, account lookup or file write. The
command reads at most 20 MiB and emits at most 256 KiB. Invalid input returns a
fixed unavailable report and exit 2; a partial report returns 0, which says
nothing about application health, billing completeness or publication readiness.

The named scenario freezes Google's standard paid text-token rates as verified
on [the official pricing page](https://ai.google.dev/gemini-api/docs/pricing) on
October 2, 2026. It supports exact resolved identities `gemini-2.5-flash`,
`gemini-2.5-pro` and `gemini-3.8-flash`. Pro's prompt threshold is applied to the
complete prompt count. The 3.8 promotional rates end December 31, 2026; this
scenario remains a dated comparison after that date, never a live price table.
A requested alias cannot substitute for missing or unsupported resolved identity.
The account's tier and actual charges remain unknown.

GenerateContent usage fields follow the pinned Google SDK: cached input is part
of prompt input, while candidate and thinking tokens are separate output
components. The total must reconcile with those components and tool input.
Absent thinking counts are not zero. An absent tool count is derived as zero
only if the observed components exactly reconcile; this is labeled. Positive
tool input is outside this slice. Text modality and every supplied breakdown
must be consistent.

A known cache count gives one token-component amount. Missing cache count gives
a range covering zero through fully cached prompt input. Integer nano-USD
arithmetic produces exact decimal strings. For an invented example with 1,000
prompt tokens, 200 cached tokens, 100 answer tokens and 300 thought tokens, the
Flash 2.5 scenario is $0.001246. This is not an account charge or an invoice.

Exact repeated observations count once. Competing local observation IDs or
provider response IDs exclude all participating valid records; a malformed
counterpart cannot hide the conflict. Invalid records, other providers and
unsupported quantities are counted separately. No eligible records yields a
null subtotal. Unknown labels never echo arbitrary input content. Stage/model
groups reconcile to the eligible-only subtotal, with truncation and invalid
window flags retained. A recent window is never complete account history.

The report excludes tool/grounding charges, cache storage, taxes, discounts,
other tiers/providers and uncaptured responses. Its range does **not** bound
actual account spend. It cannot establish a cap, monthly forecast, cost per
published tweet or savings. Do not add it to cumulative ledger totals.

Validation covers actual SDK objects offline, rate thresholds, thought/cache
arithmetic, missing and conflicting quantities, duplicate identities, malformed
counterparts, group reconciliation, input/output bounds and private-content
exclusion. Provider, network, process and file-write operations are prohibited
in the relevant fixtures. No paid call is necessary to run the report or tests.

No dashboard or generated policy change is included, so this release needs no
additional Vercel deployment. A later dashboard presentation must retain these
scenario and coverage labels. Production cost authority and invoice reconciliation
remain separate work.
