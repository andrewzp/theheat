# Review a week of retained outcomes

This report joins saved posts to their exact delivery receipts and keeps explicit
editorial opinions separate from factual checks, model evaluation and engagement.
It reads local snapshots only. It never fetches, generates copy, posts, changes
settings or schedules work.

With Node24 or the project's supported runtime:

```sh
node scripts/weekly_review.mjs --state /private/snapshots/state.json \
  --feedback /private/snapshots/opinions.json \
  --as-of 2026-10-18T12:00:00Z --output /private/reviews
```

Choose your actual private paths and an aware timestamp. The opinion file contains
`{"records": [...]}` with unchanged saved editorial-feedback records. Omit
`--feedback` when none is available; omission means unknown, whereas supplied
`{"records": []}` means zero records in that supplied snapshot. No account access
or token is required. Inputs are bounded at8MiB each,1024drafts/1000opinion records.
Duplicate JSON keys and invalid data refuse rather than being repaired.

The previous168hours form a half-open window: its start is included and the as-of
instant is excluded. Only unambiguous, exact current draft/confirmed-ledger joins
count as retained deliveries. Conflicting IDs, missing or future dates and legacy
posted-state labels cannot establish a post. Saved receipts do not independently
verify the public page, and the retained archive is incomplete.

Length statistics are descriptive. A manually edited sentence is not proof of
model improvement; model authorship remains unverified. Opinions are unblinded
single-post ratings, not independent paired preferences or fact checks. The report
shows at most the latest eligible opinion per post, counts repeat saves separately
and distinguishes opinions on older posts from new weekly deliveries. Raw tweets,
notes, source text and provider errors are omitted.

Costs are a separate **month-to-date daily-bucket context**, using the existing
retained estimate reader. They are not a weekly total, invoice or same-period cost
per post. Intra-day alignment, missing calls and complete charging remain unknown.
No historical repricing occurs. Operations summaries retain their own windows;
missing telemetry is unknown, never a healthy/zero-activity certificate.

The command writes private JSON and Markdown artifacts with content-derived names.
With the same reader version/runtime, identical supplied inputs and clock reproduce
the same files; conflicting existing
bytes refuse and are never overwritten. Keep source snapshots privately for exact
reproduction; input fingerprints in the report describe semantic JSON values.

Promotion always stays **HOLD**. A report does not qualify sources, establish blind
copy preference, measure global opportunity recall, authorize a paid experiment or
resume publishing. Review actual evidence before proposing one bounded experiment.
The full weekly-learning contract still needs that experiment and measured review;
a single generated report does not complete it.

## Turn the selected improvement into one bounded plan

The report's `improvement` names the week's single proposed change. When it is a
`local_repair` or `source_uncertainty` (not an `owner_action` such as an expired
credential), freeze a default-off plan for exactly that improvement:

```sh
python scripts/theheat_evaluation.py experiment-plan \
  --weekly-review /private/reviews/weekly-review-<date>-<id>.json \
  --spec /private/reviews/experiment-spec.json --output /private/reviews/plan.json
```

The spec supplies only `question`, two to four `arms` (each with `arm_id`,
`code_revision`, `brief_sha256`, `policy_sha256` and `model`) and an `allowance`
(`max_candidates`, `max_model_calls`); the improvement is copied from the review
and bound to its report ID. Plans fix one writer sample and no revisions, list the
required checks and rollback criteria, and are never authorized to run or publish.
Running an arm is a separate, explicitly authorized operation.

After real, bound results exist, read the decision without changing anything:

```sh
python scripts/theheat_evaluation.py experiment-accept \
  --plan /private/reviews/plan.json --result /private/reviews/result.json \
  --output /private/reviews/decision.json
```

Missing arms, unproven required checks, too few supplied ratings, more factual
failures or an exceeded allowance all `HOLD`. `PROMOTE_RECOMMENDED` makes no
automatic change; a person applies the reviewed arm's revision and policy.
