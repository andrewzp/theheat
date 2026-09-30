# Cost prerequisites, honest copy evaluation and repair gating

This local slice prevents known-impossible drafting work, stops an unconfigured
repair agent from starting, and provides an offline way to compare shorter copy.
It does not activate publishing, repair, paid evaluations or a batch transport.
Version: 0.9.108.20, based on the local 0.9.108.19 media-package implementation.
Local implementation, release, runtime recovery and measured improvement remain
separate states; check the actual branch and deployment before claiming any release.

## Drafting prerequisite boundary

`src/two_bot/provider_preflight.py` resolves the loaded writer route and required
credential presence. The main pipeline calls it after policy/evidence validation
and before memory construction or any writer call. It checks the writer credential,
Google fact-check/critic credentials, and the separate safety key loaded at import.
Whitespace-only values are absent. Unsupported writer providers are blocked.

The result is `blocked` or `configured_unverified`. Both retain
`provider_access_verified: false` and `funding_verified: false`. Missing
prerequisites produce a bounded `provider_preflight` suppression without printing
keys, marking a factual pass or entering the rejected-evidence cache. Reused
telemetry cannot retain an earlier writer pass or evidence-cache authorization.

This is presence validation, not a funded-access probe, durable provider circuit
breaker or universal call interceptor. A configured but invalid/depleted account
still requires classified runtime failures and recovery. Standalone writer,
canary, repair and enrichment routes are not all governed by this pipeline check.
Source eligibility, shared reservations and complete accounting remain necessary.

The new module is part of the editorial-policy source identity. The generated
dashboard manifest changed accordingly. After eventual release, manually deploy
the dashboard and verify the same policy revision. Do not reuse obsolete approvals.

## Self-heal boundary

`.github/workflows/workflow-self-heal.yml` retains the existing detector. Its new
prerequisite step starts the paid agent only when red workflows exist,
`THEHEAT_SELFHEAL_REPAIR_ENABLED` is exactly `1`, and both `SELFHEAL_PAT` and
`ANTHROPIC_API_KEY` are present. Presence booleans, not secret values, enter the
gate. An unset opt-in is OFF; adding a token does not implicitly enable repair.

A blocked red run writes `outcome: error` when beacon access works. The hourly
observer now reports that error immediately instead of treating its recent
timestamp as recovery. Allowed repairs remain `pending` until completion; green
days remain `ok`. The existing beacon-write alarm remains necessary because a
missing PAT may also prevent variable writes. Neither a turn/time bound nor a
credential guarantees an account spending ceiling or successful repair.

## Supplied copy and human-rating contract

`src/evaluation/copy_comparison.py` exposes:

```python
prepare_copy_comparison(pairs, side_assignments=assignments)
summarize_copy_comparison(pairs, side_assignments=assignments, ratings=ratings)
```

Both are pure transformations, capped at two million serialized bytes per input,
100 pairs and 1,000 ratings. Tests supply the canonical synthetic input shape.
Each pair supplies a stable ID, shared evidence SHA, adjudication status/method/
reference, source context, and exactly two candidates. Each candidate includes
its exact text SHA, origin, factual disposition, rejection reasons and supplied
material-claim annotations. Text is at most 280 Python characters with no minimum
length; that count is descriptive, not a complete platform-weighted validator.

Explicit side assignments use each candidate once. `display_pairs` hides explicit
origin fields; `private_mapping` retains origins and rating bindings separately.
The caller must keep that mapping off the rating screen and avoid disclosing the
origin in IDs/context. This API alone does not guarantee a blind or representative
study and does not authenticate raters or certify their qualification assertions.

Ratings require the current exact binding, a rater ID, timezone-aware timestamp,
integer 1–5 punch/clarity/unnecessary-words scores and explicit A/B/tie/abstain
preference. Higher unnecessary-words scores mean more excess. Only abstention can
omit scores. Exact duplicate ballots are counted once; conflicting ballots or
changed text/evidence/qualification/context/origin/side assignments are rejected.

Both texts and their evidence must be qualified before a ballot enters quality
counts. Other ballots remain auditable. Summaries distinguish rated/unrated pairs,
eligible/ineligible ratings, ties and abstentions. Length deltas use all eligible
pairs, including unrated ones. Display-side totals are not a model winner. With
no eligible ratings there is no preference result. No length reduction is a
quality, engagement or viral-lift claim, and publication approval stays false.

The banner in `docs/QUALITY_TREND.md` preserves the old table while explaining
that old AI prose grades cannot qualify historical claims. The existing actual-
tweet regressions and missing-source, publication and QC-timing limitations remain.
Offline historical probes explicitly inject configured preflight and model results;
they evaluate downstream boundaries, not real access or model quality.

## Batch follow-up

Read [the revised batch specification](../plans/2026-09-29-batch-writer-respec.md).
Implement shared request construction and parity first; then immutable planning/
results, durable reservations/lifecycle, and bounded default-OFF transport.
Keep one routine sample until a separately authorized, funded private comparison
supports more. Do not revert containment to resume posting. Provider billing
settings, actual access, a complete spending ceiling and production state authority
remain separate prerequisites, not consequences of this code passing tests.

## Verification

The full offline Python profile passed **4,088 tests**, with 41 paid tests excluded.
Ruff, mypy over 143 source files, direct copy-comparison/workflow-health typing and
both generated contracts passed. Dashboard tests passed **294 cases** and the
production build passed using its locked Next.js 15.5.25 dependency installation.
No changed user flow or signed-in visual QA is claimed for the policy manifest.
One existing Google SDK deprecation warning remains.

The private frozen historical run verified all 186 inputs and reported no unexpected
observations, with no provider call. Original source packets were not reconstructed
and no human ratings or real model-quality improvement were measured.

Focused coverage exercises real pipeline and dispatch boundaries, real workflow
shell steps with a fake `gh`, and pure rating contracts. Model calls in orchestration
fixtures remain mocked, with explicit dummy credential presence where appropriate;
missing-prerequisite regressions still exercise the real production gate.

No provider call, credit purchase, secret creation, paid replay, public tweet,
public correction or production flag change was made by this implementation.
