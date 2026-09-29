# P31-B: immutable private text and graphic review package

An explicit local command now puts a draft, qualified comparator, exact PNG,
generated alt text and retained evidence into one private directory. Re-running
it with identical inputs verifies and reuses the same bytes. Edits invalidate
the binding or produce a distinct package; altered existing packages are refused.
This is local implementation, with no claim of deployment or production attachment.

## Interface and retained contents

`src/media/review_package.py` exposes `prepare_media_review`, taking keyword paths:
`repository`, `output_root`, `draft_path`, `expected_identity_path`, `spec_path`,
`policy_path`, `manifest_path`, and `pdftoppm`. The JSON result contains the output
path, packet SHA, reuse flag, file count, synthetic label, unreviewed claim status
and false publication approval. Errors are bounded `MediaReviewError` diagnostics;
the CLI exits 2 without printing source payloads.

Example, substituting actual absolute paths that do not traverse symlinks:

```sh
python scripts/prepare_media_review.py \
  --repository /absolute/repository \
  --output-root /absolute/repository/.gstack/media-review \
  --draft /absolute/private/draft.json \
  --expected-identity /absolute/private/expected-identity.json \
  --spec /absolute/private/spec.json \
  --policy /absolute/private/current-policy.json \
  --manifest /absolute/private/preview/manifest.json \
  --pdftoppm /absolute/real/rasterizer/binary
```

The rasterizer is only fingerprinted, never executed. A Homebrew alias or `/tmp`
may be a symlink on macOS; deliberately select its actual resolved path. Inputs
and the current policy must be supplied independently by the trusted caller.
The command does not look up drafts, read credentials, query a service, or render.

The output root must be exactly the selected repository's `.gstack/media-review`.
Git must ignore the root, staging/lock files and every package asset. A completed
directory is named by the P31-A packet SHA and contains exactly 13 files:

- The unchanged renderer assets: `input.json`, `preview.svg`, `preview.pdf`,
  `preview.png`, `alt.txt`.
- Canonical snapshots: `draft.json`, `expected-identity.json`, `spec.json`,
  `policy.json`, `renderer-manifest.json`, `packet.json`.
- `README.md`, displaying only the local PNG, with draft/alt text in safe dynamic
  Markdown code fences; and `package.json`, hashing every other file.

Unbound draft metadata can change without changing a P31-A packet SHA. If that
happens, an existing different snapshot is refused rather than overwritten or
silently reused. This conservative collision rule preserves diagnostic evidence.

## Filesystem and provenance boundaries

- Read regular files through descriptor-relative, no-follow opens. Walk all
  directory ancestors without following symlinks. Reject relative/network paths,
  traversal, unexpected asset names, FIFOs, invalid UTF-8, duplicate JSON keys,
  nonfinite numbers and oversized data before parsing. JSON inputs are capped at
  1,000,000 bytes, image/PDF/SVG assets at 8 MiB each, and selected renderer files
  at 64 MiB. Recheck file size and modification metadata after each read.
- Verify the five cached assets against the manifest, then revalidate P31-A's
  exact draft/request/evidence/policy/alt/PNG contract. Verify local renderer,
  graphic contract, adapter, font and selected rasterizer hashes. The recorded
  ReportLab version is provenance, not proof of the installed environment or of
  its linked libraries. No optional renderer dependency is imported by packaging.
- Copy the already validated bytes; never reread a cache path for output. Package
  directories use 0700 and files 0600. Refuse changed permissions, hard-linked
  package files, symlinks, extra/missing files and byte changes on reuse.
- Serialize cooperating writers with a nonblocking private-root lock. Write and
  fsync a unique hidden sibling stage, verify all bytes, fsync the stage, rename
  it to the final packet SHA, then fsync the parent. Existing targets, including
  empty directories, are verified or refused, never intentionally replaced.
- An ordinary failure cleans its stage. Abrupt process death may leave a hidden
  incomplete stage; a retry ignores it and creates a fresh stage. It is never a
  completed package. A parent-sync failure after rename may leave the complete
  package, which a retry fully verifies. Retained abandoned stages need deliberate
  local cleanup later; this command never sweeps unrelated directories.

These guarantees assume a normal local filesystem and cooperating same-user
writers. They do not defend against a hostile process with the same user privileges
renaming owned directories, nor establish cross-host or object-storage durability.

## Validation and limits

Full offline release profile: **3,968 passed**, 41 paid tests excluded; Ruff,
mypy over 141 source files, direct module/CLI typing and both generated contracts
passed. No dashboard code changed, so no new dashboard build/visual-QA claim.

The first full run exposed one calendar-sensitive historical-receipt fixture.
The identical failure reproduced on unchanged main: a September 8 forecast was
compared to an archive generated relative to the current date. Pinning the
fixture's archive and retrieval date to its historical forecast fixes the test
without changing production qualification. All 28 place tests and the affected
test with the clock advanced 365 days passed before the successful full rerun.

Focused packet/package/adapter/graphic tests: **316 passed**. Coverage includes
exact reuse, stale requests, text round trips, changed evidence/policy/media,
ambiguous/oversized inputs, provenance changes, path containment, permissions,
13 staged-write failure positions, verification/rename/fsync failures, process
death, lock contention, unchanged input bytes and inert Markdown payloads.

The existing optional ReportLab/pdftoppm verification passed all four specimens:
the two original templates and both qualified synthetic GHCN adapters. It checked
independent deterministic rendering, real PNG decoding/dimensions, font binding,
reuse and tampering; dense overlapping trajectory labels were correctly refused.
A newly rendered qualified synthetic comparator was packaged, decoded with Pillow,
and reused identically, with every output hash and original input hash verified.

Full-size visual inspection confirmed labels, units, dated comparator, source,
sample scope, unknown reporting interval and synthetic/private markings. At 390px
width the headline/numbers remain recognizable, but the source, dates and scope
qualifications are too small. **The current graphic is not accepted as ready for
mobile publication.** The README provides full-size access and separate alt text;
that does not fix the chart layout. A mobile layout task must preserve all scientific
qualifications rather than hide them to obtain larger headline text.

PNG contract validation remains structural, not a complete decoder or content
certification. Rendered synthetic QA is separate evidence. Hashes prove the
selected inputs match; they do not establish source authenticity or scientific
agreement between text and image. Every package remains unreviewed and unapproved.

No runtime model, API, Gist field, automatic posting flag, dashboard, source fetch,
provider charge or production rendering dependency changed. This local-only slice
does not require Vercel deployment. The original historical tweet findings and
their evidence limits remain intact; no known erroneous post is positive gold.

Next boundaries: readable mobile templates, trusted joint semantic review,
durable hosted assets, exact attachment/approval invalidation, authenticated desk
integration and eventual upload/publishing lifecycle. None is implied by loading
this package or by passing these tests.
