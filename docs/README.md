# TheHeat documentation — current index

Start here. This page lists the documents that describe how the system works and
how to operate it **now**. Everything under [handoffs](handoffs/README.md), the
dated `docs/plans/` files and the dated review/investigation notes are preserved
history: they record past states and proposals, not current settings or
instructions. Production configuration is whatever the bot itself last reported
(Operations → Bot settings and evidence), not what any document says.

## Set up and check a checkout

- [Local development](local-development.md) — fixture checks, optional native and
  PostgreSQL profiles, and what each does not prove.
- Onboarding preflight: `python scripts/theheat_onboard.py preflight` reports
  pinned dependencies, the dashboard lock/cache match, all six generated-file
  checks and which optional features are unavailable, without credentials or
  network. `inspect-draft --state <saved-state.json> --draft-id <id>` explains one
  saved draft's review, holds and delivery state.
- [Integration packet](INTEGRATION_PACKET.md) — how a finished change set is
  handed to the release owner.

## Operate the live bot

- [Upgrade acceptance ledger](upgrade-progress.md) — what each original package
  delivered and what still needs evidence.
- [Qualified source inputs](runbooks/source-inputs.md) — normals, GHCN thresholds, Earthdata and HMS.
- [Production pause](runbooks/production-pause.md), [source redundancy](runbooks/source-redundancy.md),
  [workflow self-heal](runbooks/workflow-self-heal.md) and
  [regional-anomaly activation](runbooks/reganom-activation.md).
- [Live content](guides/live-content.md) — automatic text, opt-in forecast text and
  native graphics, each behind its own control.
- [Generation candidate budget](GENERATION_CANDIDATE_BUDGET.md) and
  [cost evidence in the editor](LOCAL_COST_EVIDENCE.md).
- [Saved source runs](guides/saved-source-runs.md), [source scope](guides/source-inventory.md),
  [source product contracts](guides/source-product-contracts.md) and the
  [offline global-readiness packet](guides/global-readiness.md).
- [NHC advisory publication](NHC_ADVISORY_PUBLICATION.md) and
  [supplied official warnings](OFFICIAL_WARNING_CONTENT.md).
- [Source-to-writer evidence contract](source-to-writer-evidence-contract.md) and
  [manual event portfolio planning](editorial-portfolio.md).

## Graphics

- [Gist post images](GIST_POST_IMAGES.md) — native charts, CRW anomaly, published
  maps and radar, and what each needs before it can be attached.
- [Temperature graphics in the Workbench](guides/gist-temperature-graphics.md).
- [Media store setup](MEDIA_STORE_SETUP.md) — shared store/CRW and published radar/cone hosting,
  cross-host readback, acceptance and rollback; native graphics do not need it.

## Review, learn and recover

- [Weekly outcome review](guides/weekly-outcome-review.md) — retained outcomes,
  the week's one selected improvement and a bounded, default-off experiment plan.
- [Feedback on a published tweet](guides/posted-tweet-feedback.md).
- Private operator guides: [blind copy review](private-copy-review.md),
  [cost reconciliation](private-cost-reconciliation.md),
  [diagnosis](private-diagnosis-workflow.md) and
  [model-request evidence](private-request-evidence.md).
- [Local delivery rehearsal](LOCAL_DELIVERY_REHEARSAL.md).

## Ground rules that do not change with a release

- Gist is the production state authority and its writes are not transactional.
  Local SQLite/PostgreSQL authority workflows are development targets until an
  explicit, accepted cutover.
- A deployment is not a pipeline run, a pipeline run is not a post, and a post is
  not a measured improvement. Missing telemetry is unknown, never zero.
- One routine writer sample, no automatic revision, bounded retries and explicit
  required checks. Unknown cost is not free.
- Known historical errors are negative test cases, never positive examples.
