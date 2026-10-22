# Domain schema and read-only architecture, version 1

The domain contract is a view over existing owners. It introduces no authority,
database tables, migrations, mutable current pointer, source acquisition, model
execution, or publication path. Gist remains the production state store. The
SQLite and PostgreSQL command repositories retain their experimental scopes.

`python -m src.commands.local_cli --database /private/tmp/invented.sqlite
domain-status --verify` is the existing inspection entry point. Its
`typed_domain` member now contains the domain view. Repeating
`--projection-record /private/tmp/owner-record.json` includes explicitly selected
owner artifacts. The command never discovers or opens another database. Operator
configuration, credentials, network clients and original source database paths
are not inspection inputs.

The source of this contract is `src/commands/domain_projection.py`. Public
JSON Schemas describe the closed [domain object](../schemas/domain-object-v1.schema.json)
and [explicit owner packet](../schemas/domain-owner-packet-v1.schema.json).

## Ownership and identity

An `OwnerRef` contains the existing module owner, namespace, record ID, artifact
SHA256 and an optional JSON pointer within that artifact. A pointer identifies
an occurrence in an immutable owner artifact; it is not a new global entity ID.
The domain view neither merges places by name nor creates global event IDs.

| Domain class | Existing owner and immutable identity | Projected core and relationships |
| --- | --- | --- |
| Place | `src.data.places`, public `place_registry.json`, exact `place_id`; sampling point uses the existing `sampling_point_id` codec | Registry ID, sampling point, country code, city and original numeric coordinates. A supplied row must match the existing registry bytes under its declared ID. No city lookup or ambiguous-name resolution. |
| Source run | `src.storage.scientific_supply`, `scientific-supply-ghcn-v1`, `run:<supply_run_id>`; `src.storage.cyclone_supply`, `cyclone-supply-nhc-v1`, same run codec | Source/product, capture instant, existing run ID, retained outcome and evidence class. This is the reported run outcome, not present-day availability. |
| Observation | GHCN supply bundle/variable pointer or NHC supply row pointer under its existing run artifact | Station/storm subject, variable, exact integer/float value, explicit unit/product/evidence class, time and known/unknown interval. Links to the exact source run. A station ID is not a registry place ID. |
| Baseline revision | `src.storage.ghcn_runtime_inputs`, `ghcn-source-result-input-v1`, `run:<id>`, `/baseline`; produced by the existing GHCN source-result client | Existing database, manifest, station-set, threshold-row and provenance hashes. Links to the exact supply and dependency artifacts. This is a pinned threshold artifact, not a certified historical record. No baseline database is opened by inspection. |
| Physical-event revision | `src.storage.physical_events`, `physical-episode-revision-v1`, existing `digest(episode_id):<10-digit-sequence>` | Existing source-scoped `ep1:cyclone:nhc:*` identity, revision sequence, predecessor hash, state, policy and observation instant. Links to exact run hashes and members matching both source assertion key and content hash, plus predecessor. Cross-agency equivalence is not inferred. |
| Claim revision | Existing GHCN signal `event_id` and source pointer; physical episode `opportunity_id` and revision pointer; report `claim_id` and revision pointer | Claim type, source evidence class and comparator/report scope, exact quantity where present and source time. A report claim remains an unverified report assertion, never an observation. A GHCN comparator claim retains its source-specific comparison scope. |
| Draft revision | `src.commands.domain_journal`, existing `domain_revisions.revision_id` and `domain_entities.entity_id` | Legacy alias, exact revision ID, content counter, text hash and editorial evidence fingerprint. The revision hash uses the existing canonical `[entity_id, identity]` material; original text/evidence artifacts are separate references. The evidence fingerprint is not substituted for an artifact hash. |
| Review | `src.commands.batch_result_journal`, `batch_result_reviews.review_id`, original report artifact | Exact job/receipt/fence/time and job relationship. The stored machine result review is not a human decision or approval. Its binding is checked without re-evaluating or rewriting its report. Legacy imported decisions remain opaque. |
| Check execution | `src.commands.check_journal` and `check_execution_journal`, existing check-set/grant IDs and packet/request/observation/receipt hashes | Required stage, job, exact grant and artifact references, and the retained stage disposition. Missing attempts stay pending; missing terminal receipts stay unresolved. The view does not evaluate currentness or declare required checks complete. Raw observations and their exact scoped requests are read through existing owner functions. |
| Job | `src.commands.batch_journal`, existing `batch_jobs.job_id` and exact plan SHA256 | Existing job/plan/spending-intent IDs and registration/useful-until times. The existing owner reader checks the original plan/intent relationship. No spending hold, grant, dispatch, lease or clock is changed. |

Source-specific scientific interpretation remains in its existing owner codecs
and validators. Inspection checks supported shapes and exact joins; it does not
replace any scientific, historical, safety, approval, spending or delivery gate.
Missing place/claim/job relationships are not filled from similarly named fields.

## Envelope and extension policy

Each domain object is a closed version-1 envelope containing `reference`, a
discriminated closed `core`, `extensions`, `relationships`, an explicit
`disposition`, `qualification: unverified`, and `publication_authorized: false`.
Every core field is reserved. Source fields cannot override or extend core keys.
All projected number fields reject booleans and nonfinite values. Integer and
float types are retained; the implementation does not normalize `1` into `1.0`.

Each supported extension declares its exact existing source namespace,
schema version, supported core projection, and immutable artifact reference.
The full extension values stay in that artifact, rather than being flattened
into core. A bounded source artifact is finite lossless JSON under the existing
codec, or opaque original bytes. Recognized owner top-level shapes are closed;
unsupported versions, extra fields and malformed nested core values produce an
explicit `opaque_unverified` record with no supported projection. Unknown
namespaces remain opaque. Raw artifacts, undeclared fields, provider response
bytes and original numeric spellings survive unchanged in base64 artifacts.

The explicit packet has exactly `schema_version`, `owner`, `namespace`,
`record_id`, `sha256` and `payload_base64`. Its hash covers the exact decoded
bytes. `projection_packet(receipt, value, owner=...)` exports an already obtained
PostgreSQL owner read and checks its existing canonical hash; it never opens a
repository. These are canonical application JSON bytes, not original provider
wire bytes. Where a producer retained raw bytes separately, export that original
artifact as well. The inspection does not reconstruct missing raw inputs.

A caller can construct a packet without consulting an owner. Therefore every
external packet is labeled `caller_supplied_integrity_only`, even if its hash
and supported schema match. A file proves local artifact integrity only; it
does not authenticate the database owner, source, producer execution, currentness
or scientific truth. The local journal path labels its own validated reads
separately. All projected objects remain unverified in both cases.

Import origins, namespace aliases and hashes retain their existing codecs.
Int/float, byte-spelling or source-ID collisions remain distinct artifacts and
explicit identity conflicts. This contract does not repair either historical
import collision by normalization. Conflicting owner/namespace/record-ID hashes
remain visible, and dependent joins are marked conflicting. A missing selected
artifact yields a missing relationship; an available opaque artifact yields an
opaque relationship. These are inspection dispositions, not authority decisions.

## Time and evidence semantics

`TimeValue` distinguishes an original source-calendar date, an instant, a known
interval, and an unknown time/interval. GHCN source dates retain unknown timezone
and unknown reporting interval when their source evidence does not establish
one. Capture timestamps do not supply observation interval boundaries. Retained
report time precision, original label and unknown timezone survive. Forecast
points remain source-specific extension data and are never reclassified as
observed values. Observation, source-report, forecast, reanalysis, threshold,
available-sample comparator and certified-record meanings are not interchangeable.

Imported legacy snapshots remain exact artifacts and retain their existing
occurrence dispositions and immutable reconciliation reports. Their asserted
`source_runs`, observations, checks, historical decisions and receipt fields do
not become typed executions or qualified evidence just because they resemble a
newer record. No historical source/QC finding changes.

## Bounds, read-only behavior and validation

An artifact is limited to 16 MiB, selected packets/artifacts to 128 records,
aggregate decoded artifacts to 32 MiB, and typed objects to 10,000. External file
reads are individually bounded to 32 MiB before decoding and aggregate external
file bytes to 32 MiB. Excess bounds fail explicitly; there is no truncation or
partial import. This is a bounded local inspection, not a paginated general
query service or a lifetime storage quota.

The view performs no schema installation, snapshot import, journal write or
mutable-state update. Re-reading and a fresh process produce the same identities.
The existing exact import-idempotency reports are unchanged. Invented producer
tests exercise real GHCN parser/capture, pinned baseline descriptors, NHC capture
and physical revisions, and retained report writes in a temporary PostgreSQL
database, then obtain genuine owner reads, export artifacts and invoke the actual
CLI in fresh processes. PostgreSQL backup/restore preserves those exports and
inspection identities. SQLite tests exercise actual job/review/check producers,
raw deterministic execution, passive imports and backup/restore while comparing
the full database dump before/after inspection. No provider, real source,
original private database, account, publishing or hosted workflow is involved.

This acceptance defines the minimum domain schema and its connected local
inspection. It does not establish production authority, a backend cutover,
source qualification, independent human/scientific acceptance, global coverage,
current check completion, approval or measured product improvement.
