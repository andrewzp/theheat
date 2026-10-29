# NHC public-advisory publication workflow

One nominated hazard statement from one current National Hurricane Center public
advisory (`TCP`) can become a pending, manual-only Gist draft, be reviewed in the
ordinary dashboard and be sent by the ordinary manual sender. Everything is default
off. Nothing here schedules, approves or publishes on its own, and Gist remains the
production authority.

## Evidence, times and limits

The only sources are two fixed free NHC products on `https://www.nhc.noaa.gov`:
`CurrentStorms.json` and the nominated bin's `text/MIATCP{bin}.shtml` page. A caller
supplies a nomination, never a URL, host, path, redirect or credential:

```json
{"storm_id": "EP492026", "bin": "EP5", "advisory": "34", "hazard": "RAINFALL",
 "place": "Example Province", "country": "ZZ", "freshness_minutes": 30}
```

`hazard` is one of `RAINFALL`, `WIND`, `STORM SURGE`, `SURF`, `TORNADOES`. `place`
must appear verbatim inside that hazard paragraph. The values above are invented.

Each current-source read is exactly two GETs with no redirects or automatic retries;
every command or trial phase has a budget of 32 requests, and running out holds.
The index row, advisory number, storm identity, WMO/summary/local times and the one
`<pre>` bulletin must agree. A superseded, removed, corrected, contradictory,
redirected, encoded, partial or oversized read holds.

NHC public advisories state no expiry. The saved record keeps
`upstream_expiry: null` with status `not_supplied_by_source`. That unknown is never
turned into a writer fact, a time or a UI label. The separate operator freshness
deadline is capture time plus `freshness_minutes` (at most 60). It is our recheck
limit, labelled as such, and never an NHC expiry. An advisory older than six hours
also holds.

The copy must name NHC or the National Hurricane Center, name the nominated place,
and use forecast wording. It must not claim observed flooding, a landfall, a record or
a population the advisory does not state. These are necessary bindings only; the
ordinary required safety, fact and critic checks still judge the text. The workflow
is text-only and needs no media store or media hosting.

## Route A: finite trial, then pending-only import (while the bot is paused)

1. Deploy the reviewed commit. Then dispatch `runtime-configuration-report` for
   exactly that commit. The importer requires a configuration-only report no more
   than six hours old, with the same git SHA and editorial-policy source hash.
2. Set the repository variable `THEHEAT_NHC_ADVISORY_TRIAL_ENABLED=1`. Keep
   `THEHEAT_PRODUCTION_PAUSED=1`. The trial refuses to run unless the bot is paused.
3. Choose a new 32-hex trial ID. Prepare the nomination JSON from the current NHC
   advisory, and get an approved recipient certificate. Dispatch
   `nhc-advisory-trial.yml` with:
   - `approval=APPROVE-2-USD-NHC-ADVISORY-TRIAL`;
   - the exact `approved_commit_sha`;
   - the nomination;
   - the certificate.

   It runs only on the first attempt, and only once per trial ID.
4. The trial reads NHC for free and binds the plan to this code, models, policy and
   source. It then makes at most four reserved paid stage calls: writer, safety, fact
   check and critic. That is one sample, no revise, no retry and no refill, within the
   unchanged 128 KiB request/output bounds and the $2 reserved-token scenario. A
   rerun, duplicate ID, stale packet, code change or source change refuses. A
   correction after a response keeps that response in the private packet and
   promotes nothing. The only output is an encrypted artifact. When everything passes,
   it contains `pending-proposal.json`: pending, manual-only, unreviewed and
   unapproved.
5. Decrypt the artifact privately and read the proposal. Then, from a clean checkout
   of the same deployed commit on the operator machine (authenticated `gh`, nothing
   printed), set `PROPOSAL_PATH`, its `PROPOSAL_SHA256` and the production `GIST_ID`,
   and run:

   ```bash
   python scripts/nhc_advisory_import.py check --proposal "$PROPOSAL_PATH" --proposal-sha256 "$PROPOSAL_SHA256" --gist-id "$GIST_ID" --repository andrewzp/theheat
   ```

   `check` repeats every check and reads NHC once. It writes nothing. It prints the
   exact `state_sha256` and `payload_sha256`.
6. Review that output. Then, still before the operator deadline, set
   `REVIEWED_STATE_SHA256` to the printed `state_sha256` and `JOURNAL_DIR` to a new
   private directory, and run:

   ```bash
   python scripts/nhc_advisory_import.py apply --proposal "$PROPOSAL_PATH" --proposal-sha256 "$PROPOSAL_SHA256" --gist-id "$GIST_ID" --repository andrewzp/theheat --journal "$JOURNAL_DIR" --expected-state-sha256 "$REVIEWED_STATE_SHA256"
   ```

   `apply` does the following:
   - takes an operator lock;
   - reads Gist and the repository variables twice;
   - re-reads NHC;
   - writes a durable exclusive attempt marker plus before-snapshots;
   - sends one PATCH that inserts the draft without reserializing other drafts, the
     ledger or number spellings;
   - performs one readback.

   It creates no review, approval, intent or schedule.

   | Outcome | Meaning |
   | --- | --- |
   | `confirmed_pending` | Inserted and read back exactly. |
   | `confirmed_pending_after_uncertain_response` | The PATCH response was lost, but the readback shows the exact insert. |
   | `readback_conflict_hold_no_resend` | Gist differs from the expected result. Stop. |
   | `unknown` | The readback failed. Stop. |

Gist is not transactional. The double read and readback detect some concurrent
writers, but a revision number is not a lock. Run the import only when no other
operator, dashboard session or bot run is writing state.

## Route B: the ordinary producer (only when generation is unpaused)

Set both `THEHEAT_NHC_ADVISORY_ACQUISITION=1` and `THEHEAT_NHC_ADVISORY_NOMINATION`
(the JSON above) as repository variables. With either missing, the bot invokes
nothing. When enabled, `run_alerts` reads NHC once and queues the nominated story.
The ordinary one-sample writer and required checks follow, and each provider
attempt (including a retry) re-reads NHC. Admission re-reads NHC once more and saves
a pending, manual-only draft. A repeat with the same evidence reuses the existing
draft. A changed advisory revokes that pending draft and holds it. With
`THEHEAT_PRODUCTION_PAUSED=1`, this holds as `nhc_advisory_generation_paused`.

## Review and send

The dashboard card shows:

- issuer, storm and advisory, hazard and place;
- issue and capture times;
- "Upstream expiry: Not stated by NHC (unknown)";
- the operator freshness deadline (labelled as our recheck limit);
- the exact hazard statement and context;
- the saved original bulletin, with a link to the fixed advisory page.

Reading the card authenticates nothing. The server re-checks the exact bulletin bytes,
hash and record-derived facts before review or approval. A held, aged, tampered or
unattributed draft cannot be reviewed or approved. Edits invalidate earlier checks
and approval. A `human_reviewed`, `reviewed` or `approved` label without a binding
grants nothing. Automatic scheduling is refused (manual-only).

Approving dispatches the ordinary `manual_tweet` run. That process installs its own
NHC owner with a fresh 32-request budget. It re-reads NHC at entry, at the
final-safety provider attempt and after the durable intent. Missing, changed or
aged evidence holds before paid safety or intent, or ends as `not_sent` after the
intent. A confirmed send records the receipt, ledger and history. A lost X response
stays `unknown` and is never resent.

## Stop and recovery

- **Stop:** set `THEHEAT_NHC_ADVISORY_ACQUISITION=0` and
  `THEHEAT_NHC_ADVISORY_TRIAL_ENABLED=0`. A running trial also stops at its `STOP`
  file. Keep `THEHEAT_PRODUCTION_PAUSED=1` and automatic publication `0`.
- **Changed, superseded or aged source:** reject the draft. Do not restore old text
  or extend the deadline. Start again with a new trial ID and a fresh nomination.
- **Import `unknown`, conflict or lost response:** never rerun `apply`, because the
  attempt marker refuses it anyway. Compare the journal's before/after snapshots
  with Gist by hand. Never roll back automatically.
- **Send `unknown`:** check the X account by hand. Never re-approve or resend the
  same event.

## Missing external inputs (not established by this work)

The following are not provided or established by this work:

- operator approval and credits for a paid trial;
- a real active storm and a current nomination;
- the recipient certificate;
- the repository variables;
- a deployed commit with a fresh runtime report;
- an authenticated `gh` session for the importer;
- X credentials or account entitlement.

The parser was built and tested only against visibly invented bulletins in NHC's
documented layout. The first live read may hold as `nhc_advisory_format_drift`, and
that is expected to be reviewed, not bypassed. No live source, model, Gist, platform
or account action was taken here.
