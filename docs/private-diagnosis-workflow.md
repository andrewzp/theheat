# Private diagnosis workflow (operator guide)

One offline command joins the private tools into a single diagnosis that answers
four questions:

1. What exactly did the models receive and return? ([request evidence](private-request-evidence.md))
2. Which attempts were expensive, rejected, missing usage or still uncertain?
   ([cost reconciliation](private-cost-reconciliation.md))
3. Does a person prefer the sharper copy on exactly the same qualified evidence?
   ([blind copy review](private-copy-review.md))
4. Which concrete source, writing, checking or accounting issue should be fixed
   next? (this guide)

It is private, local and **default OFF**. It never generates, replays a
provider, approves, releases budget, posts, corrects, reads live Gist/DB
state, or follows a path found inside an input. Weekly promotion stays
**HOLD**.

## Inputs

All inputs are explicit absolute owner-only files or directories.

| Input | Flag | Required | Verified as |
|---|---|---|---|
| Private request archives | `--archive DIR` (repeatable) | yes | D1 read API: canonical hash chain, artifacts, bindings |
| Reconciliation report | `--reconciliation FILE` | no | D2 `report_sha256`; every capture it counted must be a counted capture here (scope and manifest), each counted once |
| Copy-review private record | `--copy-private FILE` | no | D3 v2 complete private-record identity and rebuilt pack; archive manifests, status and unique candidate provenance checked against supplied archives |
| Copy-review import report | `--copy-import FILE` | no | D3 v2 report/private/pack/rubric identities; summaries reconstructed from bound ratings; import clock cannot exceed diagnosis clock |
| Retained state snapshot | `--state FILE` | no | Read by the existing Node readers; the state's semantic fingerprint must match |
| Feedback records | `--feedback FILE` | no | Passed to the existing weekly reader unchanged |
| Clock | `--as-of ISO` | yes | Timezone-aware; the only clock used |

**Readers.** The existing `dashboard/lib/weekly-review.js#buildWeeklyReview`
and `dashboard/lib/post-outcomes.js#postOutcomes` are invoked unchanged through
`scripts/private_review_inputs.mjs`. Configure your installed Node 24 executable
with `THEHEAT_DIAGNOSIS_NODE`; there is no default or executable discovery.
The absolute, canonical path must be named `node` or `nodejs`, and `--node` must
equal that process pin. This is your explicit executable choice, not authentication
of the binary. The call uses fixed arguments, no shell and
no input-specified module. The bridge whitelists content-free status, identity and
nullable metric fields; malformed retained context payloads never enter stdout.
Python stops and kills the reader when its stdout exceeds 16 MiB, discards its
stderr, and enforces a 120-second deadline while reading.

**Bounds.** Each standalone file is at most 8 MiB. One diagnosis takes at most
128 MiB of explicit input.

**Missing inputs.** A missing optional input is shown as `absent`. It never
becomes zero usage, zero cost, zero engagement or an empty proof.

**Lineage mismatch.** A component that fails verification or lineage is held
(`invalid` or `lineage_mismatch`) and joins nothing.

## What the diagnosis shows

- **Overview, with separate denominators:**
  - **source:** archives by status, generations and distinct bundles;
  - **checks:** candidates, accepted, rejected, decided without a provider call;
  - **spend:** SDK calls, attempts, responses, unknown sends, usage, billing
    matches and quarantines, and the named scenario figure. `actual_cost_known`
    is always false.
  - **preference:** pairs, held pairs, human-asserted and synthetic ratings kept
    apart, and `real_human_ratings_added`;
  - **publication:** outcome inventory rows separately from confirmed context-bound
    receipts, those joined to an archived candidate, unjoined posts, manual or
    edited posts, feedback exclusions and unknown engagement. Observations retain
    metric nulls, known zero, association, conflicts and missing post-age status.
    Nested preference and monetary fields remain visible in the HTML/Markdown.
- **Candidate detail:** each archived candidate's exact evidence identities
  (bundle and memory), each call's logical/wire request and raw-response
  availability, usage status, billing status, terminal stage, and its copy-pack
  membership.
- **Mechanical dispositions:**
  - `missing_response:call_N`
  - `unknown_send_outcome:call_N`
  - `invalid_model_output_schema:<stage>`, classified from the pipeline's own
    fixed phrases, never from model text
  - `usage_missing_or_invalid:call_N`
  - `billing_match_unresolved:call_N`
  - `decided_without_provider_call:<stage>`
  - `evidence_changed_since_capture`
  - `published_receipt_joined`
  - `archive_incomplete`
  - `held_capture_identity_conflict` (an unjoined post whose text and bundle match a quarantined export)

  There is no root cause, weather diagnosis or quality grade.
- **Receipt join.** A post joins exactly one accepted archived candidate only
  when the existing retained reader establishes the original writer, source,
  unchanged saved revision and confirmed receipt relationship. Event, text and
  bundle identities must match; original and published revision identities must
  be equal. Actor identity remains unknown even after a mechanical join.
  - Identical text alone is insufficient.
  - Several equal matches are ambiguous, and rejected candidates never join.
  - Unknown/conflicting writer context, manual same-text revisions, changed then
    reverted copy, incomplete history and differing revision/evidence stay separate.
  - Generations and candidate attempts retain manifest sequence identities. Their
    calls and terminal reasons never merge merely because text or bundles repeat.

Default stdout and all three views (`diagnosis.json`, `diagnosis.md`,
`diagnosis.html`) are content-free: identifiers, hashes, counts and
dispositions only.

The HTML is static. It has no scripts, forms, buttons or external resources,
escapes every value, and links to each candidate's evidence anchors. Exact copy
leaves only through `export-copy`, written to a new private file. That command
refuses a text hash naming multiple candidate records, before writing any output.
For a unique candidate it exports reasons only within that candidate's generation
and attempt; identical text never selects the first generation implicitly.

## Repeated, copied and conflicting inputs

Every consumer uses one rule: a capture is its verified scope ID plus manifest
hash (`identity_reconciliation`, also a `capture_identity` component). A caller
path, a body hash, a label or a supplied "complete" flag is never an identity.

| You supplied | The diagnosis does |
|---|---|
| The same `--archive` twice | Counts it once; the second argument is `duplicate_not_counted` with `duplicate_of_input` |
| A byte-identical copied export | Same as a repeat (same scope and manifest) |
| Two separate captures with identical requests or texts | Counts both: they are two physical attempts. A post matching both stays `ambiguous_multiple_accepted_candidates` |
| Two exports claiming one scope with different contents | Quarantines both from every count, total and join (`conflict_quarantined`); exits 1; nothing is chosen |
| An export that fails integrity checks | `invalid_not_counted`; it has no identity and never hides behind a valid copy |

Optional components follow the same rule:
- A reconciliation, copy pack or import naming a quarantined capture is
  `held_identity_conflict` (ratings bound to a held pack are `held`).
- A sealed older reconciliation that counted one capture twice, or two contents
  of one identity, is `unverifiable_identity`. It is read, never repaired, re-sealed
  or re-derived; rebuild it with the current `reconcile` command.
- A supplied component that does not verify is shown as `held` in the overview
  with its `component_status`. Only an unsupplied component is `absent`, and
  neither is ever zero. Under a held pack, candidate membership is unknown.
- Spend reports `token_totals_status` and its unknown reasons, derived from the
  reconciliation's own retained rows. An `incomplete` total is a known partial
  subtotal (partial coverage), never a complete or zero amount.

Changing the order of `--archive` arguments can only reorder input-indexed
provenance; it never selects a different counted contribution.

`next_actions` lists fixed mechanical steps (for example
`compare_conflicting_exports`, `rebuild_older_component`,
`totals_are_known_partial_subtotals`). None fetches, retries, repairs or approves.

## Durability and restart

1. The views are written first, then `diagnosis.complete.json`. The marker
   records the sha256 of each view and the report identity.
2. Without the marker, the output is **incomplete** and never readable as a
   diagnosis.
3. `verify` re-reads every component in a new process. It checks the hashes,
   checks the report identity, and re-renders the Markdown and HTML from the
   JSON. Any tampered, partial or mismatched component is `invalid`.
4. With the same inputs and the same `--as-of`, the bytes are identical. An
   exact rerun reports `identical_existing`.
5. Different content refuses to overwrite (`private_file_conflict`).
6. An interrupted run is restarted by running the same command again. The
   identical components already written are reused, and nothing is deleted or
   adopted.

## Commands

```sh
export THEHEAT_DIAGNOSIS_NODE=/ABS/NODE/bin/node
PY=/ABS/VENV/bin/python
$PY scripts/theheat_diagnose.py diagnose --as-of 2026-10-23T12:00:00+00:00 --output-dir /ABS/PRIVATE/diagnosis \
  --archive /ABS/A/scope-… --archive /ABS/B/scope-… \
  --reconciliation /ABS/PRIVATE/reconciliation/reconciliation.json \
  --copy-private /ABS/PRIVATE/copy/pack-private-….json --copy-import /ABS/PRIVATE/imports/import-….json \
  --state /ABS/PRIVATE/state.json
$PY scripts/theheat_diagnose.py verify --output-dir /ABS/PRIVATE/diagnosis
$PY scripts/theheat_diagnose.py export-copy --archive /ABS/A/scope-… --candidate <candidate_text_sha256> \
  --output /ABS/PRIVATE/exports/candidate.json
```

Exit codes: `0` complete, `1` completed with held components (or an incomplete
`verify`), `2` refused or invalid, `64` usage.

## Complete copyable synthetic journey (invented, offline)

This runs the whole chain:

1. Real pipeline and SDK serialization over invented transports produce nine
   archives: accepted, a second accepted text, factual/safety/critic
   rejections, post-dispatch uncertainty, malformed output, a local precheck,
   and a second evidence bundle.
2. Reconciliation runs with an invented invoice mismatch (one quarantined
   item).
3. A blind copy pack is built with a manual edit and a held unqualified pair.
4. Synthetic ballots record a rating, a tie and an abstention.
5. An invented receipt-bound snapshot holds one exact post and one manually
   edited post.
6. One diagnosis is produced and then verified.

```sh
cd /ABS/THEHEAT
export THEHEAT_DIAGNOSIS_NODE=/ABS/NODE/bin/node
PY=/ABS/VENV/bin/python
DEMO=$(/usr/bin/python3 -c 'import os;print(os.path.realpath("/tmp"))')/theheat-diagnosis-demo
umask 077 && mkdir -p "$DEMO" && chmod 700 "$DEMO"
env -i PATH=/usr/bin:/bin HOME="$DEMO" LC_ALL=C LANG=C NO_PROXY='*' no_proxy='*' NETRC=/dev/null \
  PYTHON_DOTENV_DISABLED=1 DEMO="$DEMO" $PY - <<'EOF'
# Invented setup only: archives, invented billing/state/selection inputs.
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
from tests.test_private_copy_pack import configure_offline_environment, qualification
from tests.test_operator_diagnosis import build_scenario_archives, retained_state, write_private, TWEET
from tests.test_request_archive_sdk import FIXTURE, private_root
from src.editorial.revisions import text_hash
from src.two_bot.request_archive_replay import load_archive
configure_offline_environment()
demo = Path(os.environ["DEMO"])
runs = build_scenario_archives(demo)
inputs = private_root(demo, "inputs")
fixtures = Path("tests/fixtures/private_workflow")
for source in sorted(fixtures.iterdir()):
    write_private(inputs, source.name, source.read_bytes())
mismatch = json.loads((fixtures / "billing-anthropic-itemized-invented.json").read_text())
mismatch.update(document={"id": "INVENTED-anthropic-statement-0002"},
                items=[{"item_id": "inv-item-tax", "kind": "tax", "amount": "0.0004"}])
write_private(inputs, "billing-anthropic-mismatch-invented.json", mismatch)
write_private(inputs, "state.json", retained_state(runs))
a, b = load_archive(runs["accepted"].archive), load_archive(runs["second"].archive)
one = {"scope_id": a.scope_id, "candidate_text_sha256": text_hash(TWEET)}
two = {"scope_id": b.scope_id, "candidate_text_sha256": text_hash(FIXTURE["revised_tweet"])}
evidence = {"bundle_sha256": a.inputs[0]["bundle_sha256"], "qualification": qualification(),
            "evidence_scope": "observed", "evidence_time": "2032-03-01T00:00:00+00:00",
            "source_context": "Invented fixture: a thermal detection."}
q = lambda ref: {"archive_candidate": ref, "factual_status": "qualified", "rejection_reasons": [], "material_claims": ["invented"]}
manual = {"manual_edit": {"text": "361 MW of thermal power in Mali.", "edited_from": one, "author_assertion": "invented-operator"},
          "factual_status": "qualified", "rejection_reasons": [], "material_claims": ["invented"]}
write_private(inputs, "selection.json", {"schema": "theheat.copy-review-selection/v1", "pairs": [
    {"label": "model vs model", "evidence": evidence, "candidates": [q(one), q(two)]},
    {"label": "model vs manual edit", "evidence": evidence, "candidates": [q(one), manual]},
    {"label": "unqualified", "evidence": {**evidence, "qualification": qualification("unverified", "not_reviewed")},
     "candidates": [q(one), q(two)]}]})
with open(demo / "archives.txt", "w") as handle:
    handle.write("\n".join(f"{name} {run.archive}" for name, run in runs.items()) + "\n")
EOF
ARGS=(); while read -r name dir; do ARGS+=(--archive "$dir"); done < "$DEMO/archives.txt"
ACCEPTED=$(awk '$1=="accepted"{print $2}' "$DEMO/archives.txt"); SECOND=$(awk '$1=="second"{print $2}' "$DEMO/archives.txt")
mkdir -m 700 "$DEMO/reconciliation" "$DEMO/copy-private" "$DEMO/imports" "$DEMO/ballots" "$DEMO/diagnosis"
$PY scripts/reconcile_request_archive.py reconcile "${ARGS[@]}" --as-of 2026-10-23T12:00:00+00:00 \
  --output-dir "$DEMO/reconciliation" --scenario google-standard-paid-2026-10-02 \
  --account-binding anthropic:acct-invented-0001:proj-invented-0001 --account-binding google:acct-invented-google-0001 \
  --billing-with-document "$DEMO/inputs/billing-anthropic-itemized-invented.json" "$DEMO/inputs/original-document-invented.txt" \
  --billing "$DEMO/inputs/billing-anthropic-mismatch-invented.json" --billing "$DEMO/inputs/billing-google-aggregate-invented.json"
$PY scripts/private_copy_review.py build --selection "$DEMO/inputs/selection.json" --archive "$ACCEPTED" --archive "$SECOND" \
  --created-at 2026-10-23T09:00:00+00:00 --pack-dir "$DEMO/copy-pack" --private-dir "$DEMO/copy-private"
env -i PATH=/usr/bin:/bin LC_ALL=C DEMO="$DEMO" $PY - <<'EOF'
# SYNTHETIC ballots (a rating, a tie, an abstention). These are not human opinions.
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
from tests.test_private_copy_pack import ballot, rating
from tests.test_operator_diagnosis import write_private
demo = Path(os.environ["DEMO"])
public = json.loads((demo / "copy-pack/pack-data.js").read_text().split(" = ", 1)[1].rstrip(";\n"))
first, second = public["pairs"]
write_private(demo / "ballots", "rater-1.json", ballot(public, [rating(first, "A"), rating(second, "tie")], rated_at="2026-10-23T10:00:00Z"))
write_private(demo / "ballots", "rater-2.json", ballot(public, [rating(first, "abstain")], rater="synthetic-rater-2", rated_at="2026-10-23T10:05:00Z"))
EOF
PRIVATE=$(ls "$DEMO"/copy-private/pack-private-*.json)
$PY scripts/private_copy_review.py import --private "$PRIVATE" --ballot "$DEMO/ballots/rater-1.json" \
  --ballot "$DEMO/ballots/rater-2.json" --as-of 2026-10-23T12:00:00+00:00 --output-dir "$DEMO/imports"
$PY scripts/theheat_diagnose.py diagnose "${ARGS[@]}" --as-of 2026-10-23T12:00:00+00:00 --output-dir "$DEMO/diagnosis" \
  --reconciliation "$DEMO/reconciliation/reconciliation.json" --copy-private "$PRIVATE" \
  --copy-import "$(ls "$DEMO"/imports/import-*.json)" --state "$DEMO/inputs/state.json"
$PY scripts/theheat_diagnose.py verify --output-dir "$DEMO/diagnosis"
```

Expected results:

- Reconcile: `completed_with_gaps`, with one quarantined mismatching invoice
  item.
- Copy-review build: `pack_built_with_held_pairs`, with 2 pairs and 1 held
  pair.
- Import: synthetic A = 1, tie = 1, abstain = 1, and **0 real human ratings**.
- Diagnosis: `completed`, with 7 candidates, 9 generations and 1 unjoined post
  (the manual edit), promotion `HOLD`.
- Verify: `complete`.

Open `$DEMO/diagnosis/diagnosis.html` locally to browse it. Every figure is
invented.

## Operational limits

- **Invented scope.** Results cover only the supplied archives, documents,
  ratings and snapshot. Nothing is a complete account, history or census.
- **Mechanical only.** Diagnosis is mechanical. Model rejections are not
  scientific adjudication, and code hashes are provenance, not authority.
- **Assertions, not truth.** Billing truth, rater humanity and qualification
  remain operator assertions. Synthetic ballots add zero human preference.
- **Receipts are retained records.** Receipts and outcome samples come from
  the retained snapshot. They are not public-page verification, a comparable
  post-age engagement sample or a measured improvement.
- **HOLD stays.** No result approves, settles a hold, releases or changes a
  budget, replays a provider, posts or corrects. Promotion stays HOLD.

## Route families (v2 archives)

When a supplied archive is v2, the JSON report gains a `routes` section, and the views (renderer v4) summarize its totals status, unknown reasons and result conflicts. v1-only reports have no route section.

For each archive, the section lists:
- the families observed and not observed;
- reused provider batch IDs;
- mechanical dispositions per route, for example:
  - `acknowledgment_not_completion_or_usage`, `status_read_not_generation`;
  - `results_partial`, `predecessor_durable_status_reference`, `duplicate_custom_ids_visible`;
  - `entity_not_observed`, `no_physical_send`, `billing_unknown`;
  - `evidence_gap:<gap>`, `batch_identity_<identity>`, `status_not_certified_for_requested_batch`, `result_conflict_with_other_retained_line`.

The same capture supplied twice is listed once (`identity_reconciliation`). The section also lists `result_conflicts`, each with every source scope, route and line, `route_totals_status` and `route_totals_unknown_reasons`. No conflicting line is chosen or counted, and a quarantined identity keeps the route totals incomplete.

Weekly promotion stays HOLD. No route disposition is a root cause, a quality grade or an approval.

## Malformed results and safe local views

A fully retained provider result with a malformed classification or message is
retained evidence, not a corrupt archive. The lineage reader marks the result
invalid while retaining every observed custom ID, including duplicate IDs.
Unknown classification never becomes an invented result type or zero usage.
Diagnosis keeps conflicting result sources and incomplete usage totals visible.

Markdown views serialize dynamic values in code spans whose delimiters exceed
every backtick run in the value. Table separators, angle brackets and line
controls have readable escaped representations; JSON preserves the exact value.
The renderer identity is v4. A sealed report from an older renderer still has its
component hashes checked, then reports `unverifiable_views`; it is never rewritten
or resealed by verification.
