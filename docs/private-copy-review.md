# Private blind copy review (operator guide)

This workflow lets a person compare two versions of one weather sentence, both
written from exactly the same qualified evidence, without seeing where either
version came from. It wraps the existing
`src/evaluation/copy_comparison.py` contract
(`prepare_copy_comparison` / `summarize_copy_comparison`) unchanged:

1. **Build** a private pack from verified request archives and your selection.
2. **Rate** in a static offline page, then download a ballot file.
3. **Import** the ballots with the CLI, which restores the private bindings and
   runs the existing summarizer.

There is no automatic judge, model rater, generated ballot, invented quality
score, generation or provider call, and no publication decision. A typed rater
ID is an assertion, not authenticated humanity. Synthetic fixture ballots add
zero real human ratings.

## 1. Select what to compare (your assertion)

A selection file (`theheat.copy-review-selection/v1`, strict JSON, at most 8
MiB, in an owner-only `0600` file) names candidates by **archive scope ID and
exact candidate text hash**. It never uses a path; archive locations are
passed only on the command line.

```json
{
  "schema": "theheat.copy-review-selection/v1",
  "pairs": [
    {
      "label": "private note to yourself (hashed; never shown)",
      "evidence": {
        "bundle_sha256": "<the exact bundle identity both candidates came from>",
        "qualification": {"status": "qualified", "adjudicator": "you", "reference": "what you checked",
                          "method": "source_audit"},
        "source_context": "What the rater should know about the evidence",
        "evidence_scope": "observed",
        "evidence_time": "2026-10-23T06:00:00+00:00"
      },
      "candidates": [
        {"archive_candidate": {"scope_id": "scope-…", "candidate_text_sha256": "…"},
         "factual_status": "qualified", "rejection_reasons": [], "material_claims": ["…"]},
        {"manual_edit": {"text": "Your edited sentence.", "edited_from": {"scope_id": "scope-…",
                         "candidate_text_sha256": "…"}, "author_assertion": "your-id"},
         "factual_status": "qualified", "rejection_reasons": [], "material_claims": ["…"]}
      ]
    }
  ]
}
```

A pair enters the pack only when all of the following hold. Otherwise it is
**held**, with fixed reasons, and nothing is bought or fabricated.

- Both candidates resolve in the supplied verified archives.
- Both candidates came from the same bundle as `evidence.bundle_sha256`.
  Newer evidence never pairs with older.
- The evidence is `qualified` by an explicit review method (`source_audit` or
  `human_evidence_review`; never `not_reviewed`).
- Both candidates are `factual_status: qualified`.
- The two texts differ.

Archive capture completeness, passing model checks and an old prose grade are
**not** qualification. They are kept in the private record for transparency
only.

A manual edit keeps its truthful origin (`model_vs_manual_edit`). A preference
for it is never a model A/B result.

## 2. Build the pack

```sh
PY=/ABS/VENV/bin/python
$PY scripts/private_copy_review.py build --selection /ABS/PRIVATE/selection.json \
  --archive /ABS/ARCHIVES/scope-<a> --archive /ABS/ARCHIVES/scope-<b> \
  --created-at 2026-10-23T12:00:00+00:00 \
  --pack-dir /ABS/NEW/review-pack --private-dir /ABS/PRIVATE
```

- `--pack-dir` must be new, and it must sit outside `--private-dir`. It
  receives only `index.html`, `app.js`, `styles.css` and `pack-data.js`
  (display data). All files are `0600` in a `0700` directory.
- The private directory receives `pack-private-<pack-id>.json` (comparison
  inputs, opaque-ID translation, randomized side assignments, origins,
  provenance) and `held-<selection>.json`.
- The retained record uses `theheat.copy-review-private/v2`. Its
  `private_sha256` covers all retained fields, including archive identities,
  provenance, comparison kinds and the private mapping. Verification also checks
  that these fields agree with the reconstructed comparison inputs and origins.
  A retained-field edit requires a new build; old records are not silently adopted.
- Pair and candidate IDs are opaque, and A/B sides are randomized from a fresh
  secret seed. The assignments are persisted in the private record, and the
  seed is not kept.
- After writing, the build scans the page assets for every private identifier
  (candidate IDs, scope IDs, manifest hashes, origins and private keys). It
  refuses to report success if any is found.
- `verify --private FILE --pack-dir DIR` rebuilds the pack identity from the
  private record and repeats the leak scan.

**Blinding limit.** The page hides explicit origins, but the writing style or
the context you supply can still reveal where a version came from. Keep
contexts neutral. Qualification details stay visible on purpose.

## 3. Rate in the static page

Open `index.html` directly from disk, or serve the folder from a local
loopback server. The page is fully offline:

- Its Content-Security-Policy is `default-src 'none'`, with self-hosted
  script and style only.
- It has no fonts, CDNs, trackers, storage, cookies, fetch, `eval` or HTML
  parsing of supplied text. All text is set with `textContent`.

The rubric `theheat.copy-rubric/v1` is version-bound into the pack and the
ballot. Each score is an integer from 1 to 5, and nothing is preselected:

- **punch**: 1 = flat, 5 = sharpest.
- **clarity**: 1 = confusing, 5 = clearest.
- **unnecessary words**: 1 = none, 5 = many. **Higher is worse.**

Preference is A, B, tie or abstain. Lengths are shown as descriptive character
and word counts only; shorter is not truer, and the count is not platform
length.

Rules the page enforces before download:

- A pair may be left unrated.
- A rated pair needs a preference. Unless it abstains, it needs all six scores.
- Notes are at most 2,000 characters and private.
- The rater ID is required, and you must choose a rater kind ("my own
  judgment" or "synthetic test fixture") and confirm it.

Errors are listed with links that move keyboard focus to the field. The layout
works at phone width.

The downloaded ballot (`theheat.copy-review-ballot/v1`) contains the pack ID,
pack hash, rubric hash, your rater ID and kind, `rated_at` (your browser clock
in UTC), and each rating's pair ID and pair hash. It never contains origins or
candidate IDs.

## 4. Import ballots

```sh
$PY scripts/private_copy_review.py import --private /ABS/PRIVATE/pack-private-<id>.json \
  --ballot /ABS/PRIVATE/ballots/one.json --ballot /ABS/PRIVATE/ballots/two.json \
  --as-of 2026-10-23T13:00:00+00:00 --output-dir /ABS/PRIVATE/imports
```

**Clock policy:** `rated_at` must be timezone-aware and satisfy
`pack.created_at ≤ rated_at ≤ --as-of + 5 minutes`.

Each outcome is kept separate:

| Outcome | Meaning |
|---|---|
| `ballot_read` | The ballot is valid. Its ratings are checked one by one. |
| `rejected` | Wrong or changed pack, rubric mismatch, bad rater fields, naive or out-of-policy clock, invalid JSON, or too many ratings |
| `rating_refused` | Unknown pair, stale pair hash (any edit to text, evidence, qualification, sides or context), or rejected by the existing contract (bool, string or out-of-range scores, missing or extra fields) |
| identical retry | The same rating imported again collapses to one |
| conflict | Different ratings by one rater for one pair are quarantined |
| tie / abstain / unrated | Counted by the existing summarizer |

The report keeps human-asserted and synthetic-fixture ballots in **separate**
summaries. `real_human_ratings_added` counts only human-asserted ratings, and
even that is an unauthenticated assertion.

The retained import report uses `theheat.copy-review-import/v2`, with its own
`report_sha256` and the exact `private_sha256`. It preserves the offered bound
ratings, including their asserted-human or synthetic class, so
`verify_import_report(report, private, as_of=...)` can run the unchanged evaluator
again and reconstruct summaries, duplicate retries and conflicts before another
tool joins the report. The import clock must not be later than the downstream
tool's explicit clock; individual ratings retain the stated five-minute skew
policy. These identities detect edits and establish supplied-record consistency;
they authenticate no person and certify no source or scientific claim.

The existing summarizer labels any counted ballots `recorded_human_ballots`.
For synthetic fixtures, the import report states explicitly that they are not
human preference. Any edit to a pack input invalidates every old rating
(`pack_changed_since_export`). Scores are never carried over to revised text.
Changes only to retained provenance or archive metadata instead report
`private_record_identity_mismatch`. Ambiguous text-only candidate references that
identify more than one generation/attempt are held rather than assigned to the
first matching generation.

**Archive identity.** `build` accepts a repeated `--archive` argument or a
byte-identical copied export as the same capture (same scope ID and manifest);
it refuses two exports claiming one scope with different contents
(`archive_scope_identity_conflict`). In a later diagnosis, a repeated or copied
archive never causes a false lineage mismatch, but a pack naming a capture that
the diagnosis quarantines is `held_identity_conflict`, its ratings are `held`,
and candidate membership reads "pack held; membership unknown". Repeated
identical ballot files collapse as identical retries; synthetic ballots never
increase `real_human_ratings_added`.

## Synthetic journey

`tests/private-copy-review-browser.mjs` runs the whole flow:

1. Actual pipeline archives with invented transports.
2. An invented qualified selection, including one held unqualified pair.
3. A CLI build.
4. A fresh headless Chromium context on an OS-assigned `127.0.0.1` port.
5. Keyboard and invalid-form checks, desktop and 390 px layouts, a direct
   `file://` open, and two downloaded **synthetic** ballots.
6. A fresh-process CLI import.

The expected synthetic counts are A = 1, tie = 1, abstain = 1, with 2
identical retries collapsed and **0 real human ratings**.

```sh
NODE=/ABS/NODE/bin/node
env -i PATH=/usr/bin:/bin HOME=/tmp LC_ALL=C LANG=C NO_PROXY='*' no_proxy='*' \
  $NODE tests/private-copy-review-browser.mjs \
  --python /ABS/VENV/bin/python \
  --result-dir /ABS/PRIVATE/browser-evidence \
  --playwright /ABS/NODE/node_modules/playwright/index.mjs \
  --chromium /ABS/CHROMIUM/executable
```

## Limits

- Qualification is your assertion and is not verified here.
- A/B are randomized display sides, not models. Aggregate side counts name no
  winning method.
- One rating is not a representative sample, an engagement prediction or a
  quality score.
- Typed rater IDs are not authentication.
- The page cannot stop a rater from recognizing a style.
