# Read retained writer operating evidence

A successful workflow, configured credential or saved-draft count cannot establish
that the writer is currently usable, its sources are sound or its copy is good.
The operating report now separates those observations using existing state, without
buying a probe or mutating production.

`src/writer_health.py` accepts state, an aware clock and the current source manifest.
It returns fixed diagnostic codes, aggregate counts and normalized UTC times:

- The latest completed drafting run and credential presence. An hourly publishing
  run cannot freshen this evidence; missing or conflicting latest configuration
  cannot silently fall back to an older positive snapshot.
- Recent returned writer responses matching that recorded provider/requested model.
  Missing usage does not erase a response. Metadata cannot prove successful parsing,
  a credit balance or a join to a particular draft or run.
- Recent saved outputs and exact review bindings matching the recorded runtime policy
  and current source files. These bindings cover fact/critic results; they do not
  supply the missing individual safety/scientific receipts or certify source truth.
- Recorded dispositions joined by exact run ID and an in-run timestamp. Typed budget
  exceptions, unclassified pipeline errors, missing prerequisites, invalid writer
  output, refusals and scientific/check rejections remain distinct. Arbitrary error
  prose is never parsed into a billing diagnosis. A checker path can include local
  rules and is not evidence of a paid model call.

The 26-hour freshness window describes monitoring evidence, not a weather-source
validity period or a publishing allowance. Processing is bounded to 20 runs,
100 suppressions, 1,024 drafts and the existing 32-response window. Missing, malformed,
conflicting and truncated evidence remains visible. Exact duplicate identities
are deduplicated; competing identities cannot become positive evidence by row order.
There is no global healthy flag, complete-accounting claim or publication approval.
All-in cost remains null and editorial quality remains unmeasured.

`scripts/writer_health.py STATE.json` reads at most 16 MiB and prints only the
sanitized report. Exit 0 means the report was generated, not that the product is
healthy. Invalid input yields a fixed unavailable message and exit 2. The classifier
makes no network, provider or process calls. It does not print private text, event
identifiers, credentials, URLs or exception bodies.

The existing daily canary job fetches state read-only into runner temporary storage,
prints this report and removes the temporary file. The separate qualification gate
uses `if: always()` so a failed read cannot hide its missing positive evidence.
Its synthetic positive fixtures remain blocked. Cron entries, paid replay opt-in,
weekly replay and publishing behavior are unchanged. No dashboard surface changed.

Offline tests use actual SDK metadata and explicitly injected review controls.
They verify clock and identity boundaries, malformed input, privacy, unchanged input,
missing usage, typed failures, policy/text/evidence changes, CLI failure handling and
workflow separation. Those fixtures do not evaluate models or qualify real sources.
Full exact call/check joins, independent source qualification and human copy ratings
remain separate acceptance work in the larger upgrade.
