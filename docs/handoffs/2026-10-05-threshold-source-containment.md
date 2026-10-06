# Contain an unavailable threshold baseline

Previously, failure to verify or recover the threshold database stopped the bot
before unrelated sources ran. The workflow now contains that failure, passes the
verifier's actual outcome to ingestion, and permits GHCN reads only on exact
`success`. Failed, skipped, cancelled, absent and unknown outcomes withhold GHCN.

The workflow uses `steps.thresholds-verify.outcome`, which reflects the step before
`continue-on-error`; its final conclusion may be successful despite an error.
See [GitHub's step-context contract](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#steps-context).
The verifier is bounded to five minutes. Cache restoration and saving are separate;
only verified data can be saved under the existing exact manifest key. Cache service
failure does not grant source permission. Maintenance publication gates are unchanged.

In `both` mode, GHCN continues to own U.S. coverage and the existing Open-Meteo path
receives only non-U.S. cities. GHCN failure no longer prevents world evaluation or
other hazard adapters. There is no U.S. forecast substitution. Combined health
remains degraded when GHCN is failed or degraded; source details retain verification
and failure categories. Global record-streak pruning is withheld while GHCN is
unavailable, preserving continuity through the outage.

Direct/local orchestration without a verifier outcome now withholds GHCN too.
The invocation environment is a trusted operator/workflow input, not a cryptographic
receipt or a substitute for source qualification. Offline fixtures that inject a
GHCN result explicitly supply their synthetic outcome. Production has no fallback
pass. The underlying scientific eligibility checks remain intact.

The artifact helper retains a bounded cache-validation category even when recovery
fails: missing, digest mismatch, metadata mismatch/invalidity, invalid checkpoint,
invalid size, empty, unreadable, unavailable, or unsafe replacement. It preserves
the existing bytes until an exact verified replacement is ready; diagnostics never
include database content, local paths or provider response bodies.

Validation uses synthetic SQLite, source and transport fixtures. It exercises blocked
GHCN reads, retained world queue candidates, country partitioning, independent hazard
execution in both scheduler modes, continuity preservation, normal verified behavior,
fixed error labels and workflow cache gates. The dashboard policy is regenerated;
its deployment must follow the reviewed release. These checks do not demonstrate
runtime recovery, a qualified replacement baseline, global recall or better tweets.
