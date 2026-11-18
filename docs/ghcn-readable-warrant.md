# Complete readable GHCN station evidence

New eligible individual GHCN records use a lossless, readable layout inside the
existing complete StoryBundle. It is a representation of retained source inputs;
it does not certify source freshness, a record, a model verdict or permission to
publish. Existing full bundles and genuine typed references keep their own
contracts. Historical drafts are not migrated.

The layout replaces the four calendar maps in each variable's baseline with one
table. Its schema is `theheat-ghcn-complete-readable-table-v1`. The exact profile
contains `format: ghcn-complete-readable-table-v1`, `original_schema_version: 2`
and `all_null_group: absent_calendar_key_not_zero`. The table's variables are the
supported subset of `temperature_2m_max`, `temperature_2m_min`, in that order.
Columns are `calendar_day`, then `accepted_years`, `accepted_samples`,
`previous_date`, `previous_c` prefixed with each variable and a colon. Rows contain
the sorted union of valid MM-DD keys, at most 366. Four nulls mean an absent key
in that variable's four source maps; they never mean zero or a missing reading
converted into an observation. Partial-null groups are invalid.

`historical_context.baseline` contains only `same_document_baseline` with the
literal value `raw_signal_dump.evidence.baseline` and `full_baseline_sha256`.
This is a fixed same-document relationship, not an executable path or external
reference. The digest covers the complete original schema-2 baseline, encoded
as sorted compact UTF-8 JSON with `ensure_ascii=False` and nonfinite values
refused. Materialization reconstructs two detached complete baseline copies and
verifies the digest and exact re-encoding. All other source fields survive,
including monthly/all-time comparisons, secondary observations, flags, dates,
coverage, revisions and explicit optional field presence.

The entire writer capture still has the existing 32,768-byte limit, using its
actual JSON encoding and escaping, including enrichment. Expanded canonical
input is limited to 262,144 bytes, depth 32 and 65,536 nodes. Unsafe integers,
nonfinite values, malformed Unicode, ambiguous JSON keys, unknown schemas,
mixed representations and inconsistent tables/aliases are refused. Unsupported
or oversized fresh inputs are held before generation rather than truncated.
Inputs whose original discarded observation cannot be reconstructed from the
retained accepted set also stay held before generation.

Approval, cache, capture, retained requests and archives bind the complete saved
wire. Scientific checks and native graphics use a separately validated full
view. Graphics keep their full calculation-input identity; the outer attachment
binds the saved wire. Strict materialization runs before native calculation
cache access. The live source guard independently verifies the current archive
at each existing sender boundary. A render-cache hit never supplies that verdict.

The Workbench disclosure is passive and initially collapsed. It displays retained
metadata and the complete table, with keyboard scrolling on narrow screens. It
does not reconstruct scientific evidence in JavaScript, fetch a source, approve
a draft, infer a UTC reporting interval or change the existing scalar claim
panel. Text edits preserve saved numeric lexemes; evidence, text or implementation
changes require the existing fresh checks and approval.

Deploy all readers and generation entry points together. Older readers must hold
this schema, including after rollback. Adoption changes neither source-family
arming, provider models, routine sample count, spending limits, nor publishing or
automatic-image controls. Fixture tests establish software behavior only;
real model comprehension, station fit, useful copy and published receipts need
separate operational evidence.
