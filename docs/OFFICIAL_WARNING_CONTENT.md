# Supplied official warnings

The warning lane accepts one explicitly nominated English-original warning. It
uses the existing candidate queue, writer, required safety/factual/editorial
checks, pending Gist draft and manual X delivery workflow. It does not fetch
warnings, enable collection/generation or turn on publication. A graphic is
optional; a warning is not evidence for a satellite map or a warning footprint.

The initial implementation is default absent. The existing `run_alerts` owner can
inject a `WarningSource` plus an existing `EditorialScore` nomination using its
optional `warning_source` / `warning_score` arguments. No environment-selected
file, HTTP upload, database, new paid command or automatic translation is added.
The score is editorial input, not a measured impact or calibrated global ranking.
When no source is supplied, no warning row or extra model work is created.

## Evidence and source responsibility

`SuppliedWarning` contains exact UTF-8 source bytes, exact metadata JSON bytes and
a separate `WarningNomination` from the trusted operator/source adapter. The
nomination pins the known issuer/origin, report/revision, both byte hashes and
English-original determination. Packet labels such as "official", "reviewed" or
"English" cannot nominate themselves. The adapter must establish these input
facts; constructing the Python object or matching a hash is not authentication,
language detection, scientific truth or an external review certificate.

The strict `theheat.official-warning/v1` metadata has these exact keys:

- `schema`, `issuer_id`, `report_id`, `revision`, `source_url`, `content_sha256`;
- `issued_at`, `captured_at`, `valid_until` (complete UTC timestamps ending in Z);
- `original_language` (`en`) and `translation` (`null`);
- `warning`: exact UTF-8 byte `start`, `end`, `text` for the nominated statement;
- `place`: `name`, two-letter `country` and the exact place `anchor` inside that
  statement. Do not infer geography from a nearby event, city-name resemblance or
  an unrelated mention elsewhere in the source.

The packet validator preserves the existing 128KiB metadata, 8MiB artifact and
16KiB excerpt ceilings. The complete writer bundle must fit the existing 32KiB
capture limit, including JSON escaping. Oversize input is held, never truncated.
Source and metadata UTF-8 spellings remain exact through Gist editing/restore;
metadata numbers, byte anchors or whitespace are not silently repaired.

A warning asserts what an issuer warned, not that forecast conditions occurred.
No observed harm, historical record, population, inferred preparation advice or
cross-border physical incident is supplied by this class. Required model checks
still evaluate the actual copy. A few deterministic attribution/place/modality
rules are necessary bindings, not a complete semantic or factual verifier.

## Writing and reviewing

The source resolver is independently reread around generation and admission.
Expired, missing, changed, contradictory or unqualified inputs stop before the
next paid stage or save. This class requires one writer sample, no revise and the
required critic; incompatible settings hold this lane rather than change global
runtime flags or silently omit a check. Existing caches, caps, retries, provider
prerequisites and unknown-usage behavior remain in force.

Eligible copy becomes a pending, manual-only draft. The Workbench shows issuer,
place, issue/capture/expiry, exact warning and the saved original/source link.
Read the original before reviewing. Ordinary text/reference edits invalidate old
checks and approval. Reference selection uses the existing scalar-fact limits;
an oversized fact may be unavailable for linking even though its full source
remains readable. A bad text edit is correctable and must not be labelled a
source correction. A known changed source is held and cannot regain approval by
restoring old text. Resolve a changed source explicitly; this first lane does not
automatically rewrite or replace an existing warning draft.

## Manual delivery and failure handling

The sender process needs its own independently current `WarningSource`, supplied
by its trusted owner through `warning_source_scope`. A saved draft, JSON English
label or old source hash is not a default resolver. If that current input is
missing, expired or changed, delivery stops before paid final safety or intent.
The collection pause continues to stop generation; inspecting or validating an
existing warning does not itself generate or authorize anything.

Manual delivery uses the existing exact revision/approval, durable intent and
receipt/history rules. Source expiry is checked again after safety and storage,
before transport. An uncertain X response stays unknown and is never blindly
resent. No credentials or platform entitlement are established by local tests.

## Qualification and limitations

Offline fixtures use clearly invented warnings, explicit provider responses,
in-memory Gist and fake X. They demonstrate software paths, not fresh source
authentication, real model-copy quality, global recall, invoice savings or a
published tweet. The real runtime needs an appropriate current source packet and
the owner's configured resolver in each process; those inputs are separate from
shipping this default-absent code. There is no independent scientific panel or
formal research cohort requirement.

Root owns consequential review, reviewed-head required CI, final union manifests,
merge and manual Vercel deployment. A policy manifest change invalidates checks
made under the older policy; obtain fresh review rather than restore old approval.
Collection/draft-generation automation, automatic publication and autoship remain
paused until separately authorized. Bluesky remains deferred.
