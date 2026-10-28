# Private usage and billing-evidence reconciliation (operator guide)

This tool answers one question from local, explicitly supplied files: which
model attempts were made, which returned usage, which outcomes are still
unknown, and which supplied billing items can be tied to an archived response
by a stable provider identifier.

It reads verified private request archives (see
[private-request-evidence.md](private-request-evidence.md)), operator-supplied
billing evidence, and optionally one retained-state file. It writes a private
JSON report and a matching Markdown view.

It never calls a provider, reads Gist/DB state, follows a URL or a path found
inside an input, settles a reservation, enforces a ceiling, changes a budget or
configuration, or claims a complete account bill, proven savings, factual truth
or publishing access.

## Evidence classes stay separate

| Class | Source | Meaning |
|---|---|---|
| Observed attempts | archive `call_intent` / `wire_request` / `wire_response` | What was attempted and what came back |
| Parsed usage | the existing `retained_usage.extract` on each retained response | Provider-reported token fields; missing ≠ zero |
| Named price scenario | the existing `usage_cost_scenario.project_usage_cost`, one row at a time | A fixed dated Google token scenario, never a billed amount |
| Supplied billing | your billing-evidence JSON | What a document you hold says; authenticity and coverage are your assertions |
| Identifier matches | stable provider IDs inside your declared account binding | A join, not a payment proof |

The denominators are reported separately: `sdk_calls`, `physical_attempts`,
`responses_received`, `unknown_send_outcomes`, responses with
present/absent/invalid usage, HTTP error responses, rejected answers with usage,
and provider-ID conflicts. No window is applied: every call in the supplied
archives is listed, and nothing beyond them is implied.

## Billing-evidence contract `theheat.billing-evidence/v1`

You fill this in from a document you hold. It is **not** a parser for any live
Anthropic or Google export. Strict JSON is required: duplicate keys, floats,
NaN and booleans in place of amounts or counts are refused. Money is decimal
text. The file is at most 8 MiB and must be an owner-only (`0600`) file in a
`0700` directory.

```json
{
  "schema": "theheat.billing-evidence/v1",
  "document": {"id": "STATEMENT-ID", "sha256": "<sha256 of the original document, optional>"},
  "provider": "anthropic",
  "scope": {"account": "ACCOUNT-ID", "project": "PROJECT-ID or omit"},
  "currency": "USD",
  "period": {"start": "2026-10-01T00:00:00+00:00", "end": "2026-11-01T00:00:00+00:00"},
  "coverage": {"assertion": "asserted_partial", "asserted_by": "operator"},
  "statement": "itemized",
  "items": [
    {"item_id": "LINE-1", "kind": "charge", "amount": "0.004125",
     "quantity": "1100", "quantity_unit": "input_tokens", "model": "claude-sonnet-4-6",
     "provider_request_id": "req_…", "provider_response_id": "msg_…",
     "occurred_at": "2026-10-23T12:00:00+00:00"},
    {"item_id": "LINE-2", "kind": "credit", "amount": "-0.001"}
  ]
}
```

- `coverage.assertion` is one of `asserted_complete_for_scope_and_period`,
  `asserted_partial` or `unknown`. It is always reported as an operator
  assertion.
- `statement: "aggregate"` replaces `items` with
  `"totals": {"charges": "…", "credits": "-…", "net": "…"}`. When both
  charges and credits are given, they must add up to net.
- Credits must be zero or negative. Amounts are kept exactly, with no
  binary-float drift. Addition uses a local precision derived from the accepted
  decimal digits and number of terms; an unrelated caller Decimal context does
  not round the result.
- An optional original document is checked only when you pass it explicitly
  with `--billing-with-document BILLING DOCUMENT`. Its sha256 must equal
  `document.sha256`. No path is ever read from inside the JSON.

## Matching rules (conservative)

- A billing item matches an archived response only through
  `provider_request_id` (the Anthropic `request-id` header) or
  `provider_response_id` (Anthropic message `id`, Google `responseId`). The
  response time must also fall inside the item's period.
- The account and project must be bound explicitly with
  `--account-binding provider:account[:project]`, which is your assertion of
  where the archived calls ran. Without a binding, nothing matches
  (`archive_account_scope_not_bound`).
- This version accepts only one distinct account/project assertion per provider
  for matching. Multiple distinct bindings for that provider produce
  `archive_account_scope_ambiguous`; they do not assign arbitrary archives to
  accounts. Run different scopes separately. Aggregate comparisons explicitly
  label ambiguous bindings and can include other accounts' counts.
- Request identifiers match actual request identifiers; response identifiers
  match actual response identifiers. When both are supplied, every identifier
  also present in the archive must agree with the same attempt. A known
  contradiction is reported separately and supports no match.
- Never matched on: similar token totals, text, model or time; different
  accounts, projects or periods carrying the same ID; and IDs that appear on
  more than one archived response (`identifier_matches_multiple_responses`).
- Exact repeated documents or items are deduplicated. Conflicting evidence
  with the same identity is quarantined and supports no match.
- Itemized scope subtotals use only unique, nonconflicting items. If any item
  identity in that scope is quarantined, the scope total is unknown and the
  remaining accepted-item subtotal is labeled separately. Original per-document
  stated totals remain available; they are not added as reconciled item money.
- Separate aggregate documents remain separate assertions even if their periods
  overlap. Missing charges or credits remain null/unknown; a supplied net amount
  does not make either missing component zero. A dash in the Markdown money
  table means unavailable, not zero.
- Aggregate statements get a side-by-side comparison only: billed money
  versus the archive's attempts and responses in that period, plus an optional
  scenario figure. Money is never allocated to calls, and currencies are never
  converted.
- An unmatched billing item is **not** evidence of an unpaid call. An attempt
  without a billing item is **not** evidence of a free one.

## Commands

```sh
PY=/ABS/VENV/bin/python
$PY scripts/reconcile_request_archive.py validate /ABS/PRIVATE/billing.json --document /ABS/PRIVATE/original.pdf
$PY scripts/reconcile_request_archive.py reconcile \
  --archive /ABS/ARCHIVES/scope-<a> --archive /ABS/ARCHIVES/scope-<b> \
  --billing-with-document /ABS/PRIVATE/billing.json /ABS/PRIVATE/original.pdf \
  --billing /ABS/PRIVATE/aggregate.json \
  --account-binding anthropic:ACCOUNT:PROJECT --account-binding google:ACCOUNT \
  --state /ABS/PRIVATE/retained-state.json \
  --scenario google-standard-paid-2026-10-02 \
  --as-of 2026-10-23T12:00:00+00:00 --output-dir /ABS/PRIVATE/REPORT-DIR
$PY scripts/reconcile_request_archive.py inspect /ABS/PRIVATE/REPORT-DIR/reconciliation.json
$PY scripts/reconcile_request_archive.py export /ABS/PRIVATE/REPORT-DIR/reconciliation.json --output /ABS/PRIVATE/REPORT-DIR/view.md
```

- `--as-of` is the only clock used, and it must be timezone-aware. The same
  inputs and the same clock reproduce identical bytes. A rerun into the same
  directory is idempotent (`identical_existing`), and different content
  refuses to overwrite (`private_file_conflict`).
- `--state` is optional. It is summarized by the existing `summarize_usage`
  at `--as-of`, read-only, and the file is never rewritten. Without it, the
  report says the state is absent; it is never zero.
- `--scenario` is optional and accepts only an existing named scenario.
  Anthropic responses are listed as `no_named_scenario_for_provider`.
- Input bounds: each standalone file is at most 8 MiB, and one run takes at
  most 128 MiB of explicit input. Exit codes are `0` complete, `1` completed
  with gaps (incomplete archives, rejected or quarantined billing), `2`
  refused/invalid, and `64` usage.
- Default stdout is a content-free summary. The JSON report contains
  identifiers, counts and amounts, but no prompts or responses. Keep it
  private all the same.

## Copyable synthetic example (invented, offline)

First create three archives (accepted, rejected and uncertain) from the actual
pipeline using invented transports. Then reconcile them against the invented
billing fixtures.

```sh
cd /ABS/THEHEAT
PY=/ABS/VENV/bin/python
DEMO=$(/usr/bin/python3 -c 'import os;print(os.path.realpath("/tmp"))')/theheat-reconcile-demo
umask 077 && mkdir -p "$DEMO/inputs" "$DEMO/report" && chmod 700 "$DEMO" "$DEMO/inputs" "$DEMO/report"
cp tests/fixtures/private_workflow/* "$DEMO/inputs/" && chmod 600 "$DEMO"/inputs/*
env -i PATH=/usr/bin:/bin HOME="$DEMO" LC_ALL=C LANG=C NO_PROXY='*' no_proxy='*' NETRC=/dev/null \
  PYTHON_DOTENV_DISABLED=1 DEMO="$DEMO" $PY - <<'EOF'
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, os.getcwd())
os.environ.update(ANTHROPIC_API_KEY="invented-offline", GEMINI_API_KEY="invented-offline",
                  THEHEAT_WRITER_SAMPLES="1", THEHEAT_CRITIC_ENABLED="1")
from src.two_bot import retry
retry.time = SimpleNamespace(sleep=lambda seconds: None)
from src.voice import safety
safety.GEMINI_API_KEY = "invented-offline"
from tests.test_archive_usage import d2_accepted_script, d2_rejected_script, d2_uncertain_script
from tests.test_request_archive_sdk import run_journey
for name, script in (("accepted", d2_accepted_script()), ("rejected", d2_rejected_script()),
                     ("uncertain", d2_uncertain_script())):
    print(run_journey(script, root=Path(os.environ["DEMO"]) / f"archive-{name}").archive)
EOF
$PY scripts/reconcile_request_archive.py reconcile \
  --archive "$DEMO"/archive-accepted/scope-* --archive "$DEMO"/archive-rejected/scope-* \
  --archive "$DEMO"/archive-uncertain/scope-* \
  --billing-with-document "$DEMO/inputs/billing-anthropic-itemized-invented.json" "$DEMO/inputs/original-document-invented.txt" \
  --billing "$DEMO/inputs/billing-google-aggregate-invented.json" \
  --billing "$DEMO/inputs/billing-anthropic-other-account-invented.json" \
  --account-binding anthropic:acct-invented-0001:proj-invented-0001 --account-binding google:acct-invented-google-0001 \
  --state "$DEMO/inputs/retained-state-invented.json" --scenario google-standard-paid-2026-10-02 \
  --as-of 2026-10-23T12:00:00+00:00 --output-dir "$DEMO/report"
```

Expected result: `"status": "completed"` with 10 SDK calls, 10 physical
attempts, 7 responses received, 3 unknown send outcomes and 2 identifier
matches. Unmatched items are reported with their reasons. The other-account
statement never matches. Running the same command again reports
`identical_existing`. All accounts, IDs and amounts are invented.

## Limits

- The report covers only the calls retained in the supplied archives. It is
  never a monthly or account total, an invoice, a forecast or a saving.
- Billing truth, authenticity and coverage are your assertions. The tool
  checks shape, arithmetic, identity and hash bindings, not truth.
- Google token-scenario amounts use fixed 2026-10-02 rates with their own
  documented exclusions. No Anthropic rate table exists here, and none is
  invented.
- Missing usage, missing responses, HTTP errors and timeouts remain separate
  and unknown, never zero.

## Route families in the usage projection (v2 archives only)

When any supplied archive is v2, `archive_usage` adds `routes`, `route_result_lines`, `route_denominators`, `route_conflicts`, `route_totals_status` and `route_token_totals`.

**One capture counts once (v1 and v2).** Before any row or denominator, inputs are reconciled by verified scope ID and manifest hash (`identity_reconciliation`):
- The same path given twice, or a byte-identical copy, is one capture. Later inputs are listed with `duplicate_of_input` and `used: false`, so repeated `--archive` never doubles sends, generations or tokens.
- Distinct captures always count separately, even with byte-equal requests: a body hash or a caller label never proves two sends are one.
- One scope ID with different manifests is an unresolved conflict (`identity_conflict_with`, `conflicting_scope_ids`): none of those inputs is used, and nothing is chosen.

| Route row | Counted as |
|---|---|
| `batch_submit` | not a generation; `usage_status: not_in_acknowledgment`; `completion_evidence: none` |
| `batch_metadata` | not a generation; `usage_status: not_applicable` |
| `batch_results` | per result line, derived from the parsed line's message (`usage_source: parsed_results_line_message`) |
| `command_check` | a generation, parsed by the same unchanged usage parser as synchronous calls |

**Counting rules:**
- Lines for one (provider batch ID, custom ID) are compared by their full retained content, inside one stream and across archives, in any order.
  - Exactly equal lines count once; the others are listed as `duplicate_not_counted`.
  - Any difference (usage, result type, model, missing vs present usage, a value's type) makes every such line `conflict`. None is counted, and `route_conflicts` keeps every source reference. No input order selects a winner.
- Errored, expired or canceled lines carry no usage.
- A cut tail of an incomplete entity is never a result line.
- Missing usage stays missing.
- `route_totals_status` is `complete_for_retained_rows` only without any conflict, evidence gap or unknown usage; otherwise the known subtotals are `incomplete`. Neither label is a system, account or invoice total.

**Scenarios.** A named scenario prices none of these rows. Each is listed as `excluded: route_family_not_in_named_scenario`.

**Billing.** No billing, account binding or invoice is inferred: `billing` stays `unknown` and `actual_cost_known` stays `false`.
