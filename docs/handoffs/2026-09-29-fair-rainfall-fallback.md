# Fair rainfall fallback within the existing request bound

The full-grid path already inspected the complete valid watchlist. During grid
outages, remote OPeNDAP and the separate weather-model fallback repeatedly sampled
the same first75 cities. CSV order could permanently hide a later city.

Only remote selection changes. Explicit coordinates qualify before canonical
identity deduplication, with a deterministic choice among equivalent labels.
Canonical identities form a circular window. Its start is UTC date ordinal times
the bounded window size modulo the qualified population. The wrapper freezes one
UTC date for both legs; a slow primary crossing midnight or walking back to older
available data cannot select a different fallback window. Concurrent responses
return in selection order. Full-grid extraction retains its existing behavior.

For a stable population N and positive limit K, any ceil(N/K) consecutive daily
attempts select every identity: consecutive windows cover at least N consecutive
positions on the circle. This holds from every starting date, including noncoprime
N/K. Reordering the same CSV or restarting within a day cannot change the selection.
Limits above75 and None remain capped; explicit zero produces no remote selection.
Malformed limits/dates fail rather than silently expanding the remote budget.

The current checked-in watchlist has633 qualified sampling identities, so the
75-city default covers every identity within nine consecutive daily opportunities.
That is a conditional sampling bound, not nine-day successful observation: missed
runs, changing populations and provider failures invalidate such an actual revisit
claim. Nine days is insufficient for complete fast-storm surveillance. Regional
extreme discovery, source recovery and reference-event recall remain separate work.
No omitted city is represented as zero rainfall. Existing freshness, model-source
labels, rolling-day continuity and scientific gates are preserved. No rainfall
record or satellite/gauge reconciliation is established by sampling more fairly.

Validation:118 focused GPM tests pass, including27 new cases across every starting
date residue for several population/limit combinations, reversal/shuffling,
aliases and invalid inputs. Actual primary and witness entry points use fake
network boundaries; source-date walkback, UTC rollover and concurrent ordering are
exercised. Existing complete-grid and credential-failure regressions still pass.
Full suite:4,549 offline Python tests pass,41 paid excluded; three dependency
warnings remain. Ruff, mypy151 source files plus the normally excluded GPM module,
both generated contracts and diff checks pass. Dashboard/policy is unchanged from
the earlier294-test/build result. No provider request, scheduler/configuration,
credential change, paid model call or publishing activation occurred.

Current-model review checked the coverage proof, unchanged city budget and preserved
scientific evidence limits. No independent review or observed source recovery is
claimed. Required reviewed-head CI and release remain outstanding. This broader
branch is separate from the narrow .33 writer repair; reconcile the common fixes
before eventual integration. Exact historical corpus/evidence stays private.
