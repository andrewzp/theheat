# P06 temperature chronology, baseline qualification and source revisions

This continues the completed September 8 assessment. It is a local implementation handoff, not evidence of production rollout or completion of the full upgrade plan. See the companion [GHCN implementation handoff](2026-09-09-p06-ghcn-time-integrity.md) for station coverage, QC revisions, durable history and the actual-tweet regression limits.

## Behavior

Open-Meteo forecast daily values retain the provider's local valid date, IANA timezone and daily UTC interval through detectors, intern bundles, writer facts and the P02 evidence hash. New Year, leap-day and DST fixtures cover the places where the run date and local date diverge. Retrieval time remains separate; issue/model-run time stays unknown when the endpoint does not return it. Requested sampling coordinates and provider-returned grid coordinates/elevation remain separate, with source units and unknown uncertainty retained.

Forecast values never update historical extrema. The world cache now holds immutable qualified ERA5 reanalysis snapshots with a declared query interval, source/model, snapshot revision and independent high, low and wet-bulb sample counts, coverage and cutoffs. Before a record comparison, that variable must have complete source coverage through the configured latest archive day. The implementation uses a five-day ERA5 availability lag and explicitly exposes the unverified intervening interval; it does not call a forecast an observed station record. A higher forecast cannot fill the gap or become the next historical baseline.

A bounded fresh archive read can revise the stored maximum downward. Same-time disagreement is quarantined until a later source verification, including disagreement concealed behind the same claimed revision ID. Conflict variants are keyed by their whole semantic payload, retained across merge order and normalized by actual UTC timestamp. Historical comparator values are never merged by choosing the greatest extreme. An old worker cannot revive a rejected larger maximum after a newer corrected snapshot.

High and low anomaly means use independent sample counts and sampled-year descriptions. A low-temperature mean cannot inherit the high-temperature archive's years. An absolute wet-bulb tier can remain available while its historical comparator is withheld for missing or stale wet-bulb coverage. Existing names-only or forecast-mutable caches are preserved in quarantine and need source-qualified recomputation.

Hot 10 carries each city's valid date and its normal's actual product and period. Newly built normal rows declare either 1991–2020 or the explicit 1961–1990 fallback. Old unqualified normal files remain excluded; no bulk normals build was run. The list compares selected city points on their individual local dates, not a simultaneous observed global maximum. Marine forecasts now retain their provider daily time contract, and missing/invalid Snow Today valid dates fail instead of becoming retrieval-day observations.

## Claim containment and retained detections

A deterministic pre-model check contains the audited forecast-to-observation failure. Record comparisons must identify the source, supported archive scope and the relevant variable's exact cutoff. Forecast-versus-ERA5 comparisons must retain forecast wording and disclose the recent unverified interval. Sampled-network country comparisons must name the sampled network; they do not certify official national records. For a network with different member cutoffs, one member's cutoff cannot silently stand in for the others.

Legacy record clusters, simultaneous-record summaries, record streaks and compound synthesis containing a temperature component are withheld before writing. Their existing reductions do not retain and validate the complete per-member/per-day comparison contract. Available member evidence is preserved; the bundle contains an explicit withheld reason, and the durable suppression entry carries `temperature_aggregate_unqualified`. A withheld cluster cannot suppress eligible individual drafts. Qualified regional reanalysis anomalies and unrelated marine compounds are not blocked merely because their names mention heat.

This is deliberate containment, not a claim that aggregation is solved. Re-enabling those lanes requires a typed aggregate adapter retaining each member's identity, value, valid interval, evidence class, source/QC revision, relevant baseline and common comparison scope. It also requires deterministic validation of dates, membership, completeness and tense. P05 schema work must preserve this P06 readiness hook when integrated.

## Material source findings and approval

`temperature_history` retains material record points, comparator/QC revisions and exact affected-claim links in both state implementations and their SQLite contract. Full global observation history and original provider bytes remain future durable-source work.

For the world cache, all-time, monthly, calendar-day, monthly-mean and wet-bulb comparator changes create retained findings. An advancing archive interval is not a retroactive refutation of a claim explicitly limited to the earlier cutoff. A missing source cell can lower a computed maximum without disproving the earlier value. Revoking an unpublished draft's obsolete evidence and approval therefore requires a complete comparison over the same interval, matching source/model/sampling identity and known matching provider grid. Incomplete coverage, unknown grid attribution and changed query intervals produce findings with historical correctness undetermined. Posted drafts, receipts and uncertain send outcomes remain unchanged.

## Collection cost and worldwide coverage

The cached world path retains its existing cap of eight archive refresh attempts per run. Candidate comparator refreshes use that same allowance ahead of routine warming; they do not add a second budget. Forecast evaluation happens before archive work and retains the existing shared request-weight budget and leaderboard reserve. This is a per-run bound, not a persistent daily source budget. Direct compatibility scanning paths retain their existing limits.

GHCN adds at most twenty bounded station-archive verification attempts per run, with four workers, thirty-second request timeouts and an eight-megabyte response cap. Exhausted, failed and unscanned verification is visible. The existing recent-diff collection is separate. There is no claim of a twenty-per-day budget; persistent daily budgets and avoiding repeated verification across runs remain operational efficiency work.

Rollout initially reduces record coverage while old caches are quarantined and a bounded set of qualified baselines is rebuilt. Metrics distinguish identity quarantine, refresh attempts/failures, forecast failures, archive gaps and withheld candidates. That loss of coverage must remain visible rather than be reported as a healthy global sensor network. Ordinary non-record individual signals with adequate current evidence continue; widening collection or silently relaxing comparator scope is not part of this change.

## Actual-tweet evidence limits

The retained Chennai and Bishkek copies used observed wording for forecast values. Offline tests reproduce those exact evidence-type defects with engineered comparators and require rejection before a model runs. They do not establish the actual observed maxima or recover the original publication-time provider responses. The Beaver Dams progression/QC fixtures and their limitations are described in the GHCN handoff. No old publication is rewritten or publicly corrected.

## Integration and rollout

This worktree branches from the P04 release and predates the already-released malformed-send-outcome helper. Root must integrate with current main, retain the P02 uncertainty semantics, regenerate/check the Python–JavaScript storage contract and rerun all checks on that combined code. The only intended dashboard changes in this slice are durable state/history compatibility; no production authentication or automatic-publication control is changed.

Before rollout, preserve the current world cache and verify no old writer overlaps the new implementation. Keep automatic publication paused. A paused queue run may verify loaded runtime metadata without calling models or publishing. Do not force source collection, a bulk cache rebuild, a paid replay or test publication simply to demonstrate deployment. Record production cache/coverage results separately from offline tests.

## Local validation

The full Python suite passes 2,866 tests, with 41 paid replay tests deselected, when the already-released 10832af P02 revision helper is loaded only into an isolated test process. No duplicate helper patch is included here; root must still test the actual integrated branch. The unmodified older helper has three expected malformed-outcome failures. The dashboard suite passes 228 tests and its production build succeeds. Ruff, mypy on 123 source files, and diff whitespace checks pass. These cover the member-cutoff, wet-bulb, independent-year, comparator-refutation, cache-collision and actual cross-runtime SQLite cases. All new fixtures are offline and no provider/model calls were introduced into them.
