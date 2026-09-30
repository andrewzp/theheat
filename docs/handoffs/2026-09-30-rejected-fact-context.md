# Private context for selected factual rejections

A rejected candidate previously retained a reason and, for model failures, a
bounded response diagnostic. It did not retain exact candidate text together with
the complete source bundle, making later investigation incomplete.

New synchronous factual rejections now carry a private `rejected_candidate` field
through the existing suppression store and authenticated API. It records the exact
text/hash, complete fact-check input bundle/hash, attempt (initial or revised),
structured failure verdict and response correlation diagnostic. Multi-sample
selection records the selected text. The checking path is `local_precheck` or
`required_checker`; the full checker repeats local rules, so this path label is
not a receipt proving a paid call occurred. Raw response retention and its explicit
truncation marker remain in the existing `model_diagnostics` field.

The complete new field is limited to 40,960 serialized bytes and text to 4,096
UTF-8 bytes. Bundle capture keeps its existing 32,768-byte bound. Invalid values,
changed input or oversized capture produce a bounded `unavailable` disposition,
without partial evidence pretending to be complete. A rejected candidate remains
rejected regardless of capture availability. Copies are detached on capture and
insertion; reused result dictionaries and negative-cache skips discard old context.

The bundle snapshot is taken before the local/full fact-check sequence and compared
again at rejection. It cannot prove absence of transient restored mutation, and
it does not contain memory, checker state or a complete provider request. It is
operational evidence, never scientific approval or negative-cache authorization.

Existing retention keeps the latest 100 suppression rows. At the new field's
ceiling, those fields add at most 3.90625 MiB before outer formatting, separate
from reasons, existing raw responses and other state. This does not cap total
state growth or provide an immutable archive. Legacy rows are not backfilled.
Writer-no-text, unselected slate, safety, critic, transport and post-generation
URL failures remain outside this slice.

Validation uses explicit offline model fixtures through real generation/dispatch,
state write/merge/read and JavaScript authenticated API access, including rejection
before unauthenticated storage access. Regression cases cover exact byte limits,
Unicode/invalid input, revision/slate identity, mutation, stale context, legacy
retention and no extra provider calls. This release adds no runtime model/sample,
retry, billing, backend or publishing-setting change. Measured copy quality,
scientific adjudication and operating-cost improvement remain separate evidence.

Local result: 26 new cases, 229 focused cases and 5,089 full offline Python tests
passed (41 paid cases excluded). All 294 dashboard tests and its build passed,
as did Ruff, mypy across 160 source files, both generated contracts and the frozen
historical harness. Explicit model fixtures do not establish scientific truth or
measured writing quality. Required CI and deployment are separate release steps.
