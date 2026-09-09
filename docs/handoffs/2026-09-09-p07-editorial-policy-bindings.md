# P07: current editorial policy on review and approval

An unchanged tweet can need a new review after its prompt, model, checking settings or scientific rules change. Reviews and approvals now bind to a separate editorial-policy descriptor as well as their existing exact text, evidence and check identities. Legacy or malformed policy bindings fail closed. Content identity, publication identity and retained receipts do not acquire a policy field, so a policy change cannot reinterpret a confirmed or uncertain publication as an unsent new revision.

## How policy is established

`src/editorial/policy.py` recomputes a bounded source manifest and actual loaded execution settings. The descriptor contains the source hash, loaded prompt/output-schema hash, writer/provider/checker/critic/safety model identifiers and effective checking flags. The source list includes the review and posting rules, approval classification, strict response/evidence contracts, writer context and prompts, intern adapters, and the GHCN/Open-Meteo temperature scientific rules. It deliberately excludes VERSION. A source-only change, loaded-prompt change or model/configuration change invalidates old review eligibility; unreadable or malformed policy inputs establish no current policy.

The pipeline captures policy before its existing stages and rejects a successful result if policy has changed before those stages finish. Its metadata includes `reviewed_policy_sha256`; attaching old check metadata to a new draft cannot stamp it with a new policy. No extra model stage or evaluation is added. The P08 negative-cache epoch includes the same canonical current descriptor, so a policy-only change reopens a previously deferred event; unknown policy disables reuse.

Python authorization uses the current process, never a historical runtime snapshot. The final sender checks again after durable intent creation and media preparation, immediately before transport. If policy changed, that newly created, known-unsent attempt becomes `not_sent` and transport is not invoked. Existing submitted, unknown and confirmed attempts retain their evidence and reconciliation behavior.

## Dashboard and human intent

Runtime inventory now records the descriptor. The dashboard requires a report no older than the existing six-hour inventory limit, from the latest run, whose source hash matches its generated manifest. Missing, expired, malformed or mismatched reports show **editorial policy unverified** and cannot record review or approval. A fresh report provides context for operator intent, not authority to send; the Python sender independently recomputes policy. A report can precede a runtime-only model change, so the final check remains necessary.

An explicit new human review can attest to a valid current policy. The checkbox identity includes the displayed policy hash separately from the content revision. The dashboard review POST requires `expectedPolicySha256` and refuses a changed/missing hash inside the state update. It cannot silently adopt a later policy after the operator checked the box. Human review remains an explicit manual attestation, not a claim that model checks ran again.

The local experimental command authority has the same rule. New `record_review` request payloads require `confirmed`, `reason` and **`expected_policy_sha256`**, the canonical fingerprint of the displayed descriptor. The pure reducer receives a trusted execution policy from its caller; it does not read live files or treat request metadata as authority. The SQLite adapter supplies live Python policy at consume time. Older stored commands without the field are parsed only to produce a durable terminal `editorial_policy_changed` refusal, allowing later journal commands to proceed. New ingress requests missing the field are rejected.

## Build and integration

Run `python scripts/gen_editorial_policy.py` after integrating changes to any listed policy source or prompt/adapter directory. Commit `dashboard/lib/editorial-policy-manifest.js` with those changes. The required bot test job and a regression run `python scripts/gen_editorial_policy.py --check`, so a stale generated artifact fails CI. The manifest contains source hashes only, not credentials or machine-specific model defaults. The existing state contract already retains nested review bindings and run inventories; no new top-level storage field is required.

This branch starts from P08 `c9d1fbc`. Root's newer source-supply integration includes P09a `8d91247` (integrated as `a5ac1d7`) and the rainfall input changes. Regenerate the manifest after integrating that base, especially `src/data/ghcn.py`, `src/data/ghcn_format.py` and `src/orchestrator/sources/open_meteo.py`; do not reuse this branch's earlier manifest blindly.

## Validation and limits

Before rebasing onto the source-supply release: **288 focused offline Python tests, 293 dashboard tests, Ruff and mypy (132 source files) passed.** These cover legacy metadata, prompt/model/source/checking drift, late responses, exact Python/JavaScript fingerprints and strict types, stale/missing inventory, human checkbox/API/queued-command races, final pre-transport rejection, cache reopening and byte-for-byte confirmed/submitted/unknown receipt preservation. Independent review reproduced and verified the human-attestation race and Python bool/int mismatch fixes, then cleared the policy and cache integration. Integrated full-suite/build results will be recorded after rebasing.

No paid calls, provider bulk work, deployment, publishing, public correction, VERSION change or account/environment configuration write was performed. Provider behavior changing behind an unchanged model alias is not independently detectable by this identity. The earlier actual-tweet audit and its source-evidence limits remain the baseline; policy freshness does not certify historical tweets or make unsupported global aggregates eligible.
