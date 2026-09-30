# Empty GDACS backup results retain source health

GDACS falls back to existing earthquake/cyclone feeds on eligible primary-source
failures. An empty fallback list previously lost event-level provenance, allowing
the runner to record a primary success. A surviving empty leg could also hide an
unavailable peer. This release preserves the source-owned batch envelope for all
successful fallback completions, including zero selected alerts.

Each attempted leg records success or failure, records received and records
selected after the unchanged severity threshold. Failed counts are null. These
are supplying-leg records, not distinct global events: two cyclone feeds may
report one storm. The batch identifies the unavailable GeoRSS primary and the
limited earthquake/cyclone scope. It does not establish coverage of other hazards
or the absence of global disasters. All legs failing still raises an error.

The runner records degraded fallback use and a bounded summary even for an empty
batch. Full per-leg details remain in existing run history; durable source health
retains status and summary. Both dashboard projection paths show the backup leg.
No shared state-schema expansion, new upstream call, or new provider-error logging
is introduced. Populated event identities and the existing skip of duplicate
subtype drafting are unchanged.

Existing stale-provider fallback remains eligible. Stale primary records still
fail the scientific freshness guard; independent backup feeds supply their own
records. Authentication, schema and invalid-clock failures cannot be hidden by
these backups. Non-strict transport behavior and three-attempt primary retry
bounds remain unchanged.

## Validation

21 new cases and 199 focused tests pass, alongside 5,136 full offline Python
tests (41 paid cases excluded), 294 dashboard tests/build, Ruff, mypy and generated
contracts. The frozen historical harness has no unexpected observations; it is
not a model-quality evaluation.

Synthetic offline tests exercise strict HTTP fetch, actual adapter aggregation,
real source runner, production Gist serialization/merge/read under mocked HTTP,
and both dashboard health projections. They cover every non-total failed-leg
combination, all legs failed, all successful empty, severity filtering, populated
identities, partial failures with a populated peer, skip propagation and forbidden
fallbacks. The implementation does not activate publishing or change runtime
models, samples, severity or billing settings.

Deployment and offline tests do not prove a production outage occurred or that
source coverage, tweet quality or operating cost improved. This fixes reporting
of the actual source path; provider qualification and the wider upgrade remain
separate work.
