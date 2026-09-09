# P09a: preserve GHCN scientific supply before individual selection

This bounded change implements the GHCN half of P09a/G09 from the [original project assessment](../2026-09-08-theheat-project-assessment-and-upgrade-plan.md) and the [input assessment's six-station counterexample](../audits/2026-09-08-inputs-data-assessment.md). It starts from released main `c0774e6`. The original uncommitted assessments and retained tweet corpus remain untouched.

## Changed behavior

`check_extreme_signals_for_stations` now returns every station/date bundle that fires a qualified signal. It no longer applies the misleadingly named `_dedup_by_metro` country cap. Country comparisons already used all readings and keep that behavior. Source telemetry adds `scientific_signal_bundles`; `bundles_after_dedup` remains a compatibility alias for the complete returned count.

The existing individual-station ranking and two-per-country limit move to `orchestrator.caps.select_individual_station_bundles`. The runner invokes it only after the complete source list has reached the records-cluster prepass. Individual candidates still face the existing scoring, final triage, spending and publication controls. Forecast-city candidates pass through this GHCN-specific cap. The default number of individual station candidates does not increase, including when triage/refill is disabled. Metrics distinguish selected individual stations from those excluded by this downstream cap.

GHCN cluster membership reuses the same source-comparison qualification as station detection, plus the existing strict individual StoryBundle audit. GHCN members need coherent station identity, valid date, source type, explicit accepted QC, measurement value, source response revision, unit, verified prior cutoff and usable coordinates. Source threshold computation now retains per-tier comparator values beside its existing record dates. The member must match that comparator's value/date/year and qualify the relevant all-time, monthly or calendar sample years; monthly records must match the valid month. A missing date is never replaced with the run date. Invalid member packets are excluded before spatial clustering and tier counts. Forecast members retain their existing source-level scientific checks and receive the shared structural/date/coordinate check here; this patch does not add a complete forecast aggregate validator.

## Scientific and operational limits

The supported GHCN comparison remains an extreme among available source-accepted station samples through a verified cutoff. Missing/QC-rejected values are exclusions, and unknown reporting intervals remain unknown. The [P06 chronology, revision and retention guarantees](2026-09-09-p06-ghcn-time-integrity.md) remain in effect. This does not establish official national records, complete physical observation history or simultaneous observations across stations.

P06's independent `temperature_aggregate_failures` block remains unchanged. A six-member cluster can now be detected and retained for review, but the legacy aggregate still cannot request generation or supersede individual records until its full member/interval/baseline publication contract is implemented and reviewed. The records-cluster flag is not activated.

The bounded source-verification budget remains at most 20 station archives per run, interleaving new candidates and retained claims. This fix preserves every signal that qualifies within the current acquisition/verification process; it does not promise verification of every station on every run or global coverage. Existing provider partitioning remains unchanged. The rainfall portion of P09a is separate work.

No new model stage, model call or source network request is added. With clustering enabled, local validation and clustering now inspect the complete returned supply. There are no measured claims here about dollars saved, live event recall, engagement or writing quality. No production flags, publishing, public corrections, deployments or VERSION changes were made.

The actual-tweet audit remains the baseline: current GHCN QC/record reconciliation cannot establish when historical QC flags became available. The six-station fixture is wholly engineered and is not new historical evidence or evidence of a missed published event.

## Offline evidence

`tests/test_ghcn_scientific_supply.py` builds nine synthetic US source archives and a stale threshold database. Six nearby stations have complete source-calendar coverage and accepted qualifying highs; a QC-rejected station, a station with omitted source years and a non-finite diff reading do not contribute records. All six qualified stations survive the public source return and form one significant spatial cluster.

The real runner/prepass is exercised with individual limits of zero, one, two and six. The detector always receives six stations; the individual lane receives the configured number. The test keeps the existing aggregate rejection in view, asserts no cluster firing memory is written, and replaces candidate submission before any writer call. Additional malformed member tests cover date, numeric, coordinate, evidence shape, baseline qualification, station, QC, value, source-revision and cutoff defects. Existing individual ranking tests are migrated to the new downstream helper.

Validation: 314 focused tests passed across GHCN detection, source parsing/chronology, scientific supply, spatial clustering and main orchestration. Focused Ruff and mypy for all four changed production modules passed. All execution was offline; no paid replay was performed. Root integration should run the normal integrated checks against the final release tree.
