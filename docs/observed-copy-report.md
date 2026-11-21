# Observed-copy report

An offline, advisory command that shows what happened to the copy the bot saved. It reads only
the local JSON exports you name, writes a new private directory, and changes nothing else.

```
python scripts/observed_copy_report.py --input EXPORT.json [--input OTHER.json] --out NEW_PRIVATE_DIR
```

The versioned summary schema is `theheat.observed-copy-report/v2`. Each input is a
state snapshot (`drafts`, optional `suppressions`) or a list of drafts. A dashboard
projection is not a whole-state export and is refused if it lacks this shape. Inputs are
read without following symlinks, devices or FIFOs, up to 64 MB each and 16 inputs. The output
directory must not exist; it is created `0700` with three `0600` files:

- `report.json` and `report.md`: counts only, with no draft text.
- `review-sheet.md`: the private editor sheet, the only file that contains exact copy.

## What it reports

- **Identities:** the same draft id with identical JSON content in two exports counts once.
  Different content for the same id is a conflict, held and excluded, never picked. Every
  supplied argument and record pointer stays listed, including repeated paths and exact copies.
- **Retained suppression rows:** an explicit suppression id with identical content counts once
  across captures; conflicting variants are held and excluded, with every pointer retained.
  Rows without ids are scoped to the exact input bytes and row index. Repeating an export or
  supplying a byte-identical copy cannot inflate the counts; separate rows and nonidentical
  captures can overlap. These are retained rows, never unique failed generations or paid
  attempts. The v1 `generation_failures_recorded` field is removed because not every
  suppression is a generation failure. `supplied_rows` counts raw argument occurrences;
  `stage_counts` counts only included rows after identity handling. Missing or null history
  is unavailable, distinct from an explicitly empty list. Neither attempt count is inferred.
- **Recorded stages:** generation, fact-check, critic, status, publication, and whether the saved
  text equals the writer's accepted output (by its recorded hash).
  - Missing records are `unknown`.
  - Recorded suppression rows are activity; missing history is not a zero count.
  - A saved draft is not a post.
  - A stored tweet id is a recorded receipt, not verified X visibility.
  - A nonposted status means `no_publication_recorded`, not proof of nonpublication.
    Unknown, submitted or contradictory delivery remains `unknown`.
  - Unrecognized stage labels are classified as `unknown`; arbitrary source text is never
    copied into stdout's count labels.
- **Text measures:** length, body length without links, link count, and sentence count. The
  sentence counter protects links, decimals, listed abbreviations and dates. An unlisted
  abbreviation followed by a capital letter can over-count.
- **Warnings:** lexical prompts for an editor. They are not verdicts.
  - a source- or acronym-heavy lead;
  - a repeated date;
  - four or more competing measurements;
  - three or more stacked qualifiers;
  - a link longer than the rest of the post;
  - an observed story with no explicit observation date.

Duplicate JSON keys (including nested keys), nonfinite numbers, exponent overflow and
malformed suppression rows are refused with bounded error codes before any report is written.
Counts and conflict dispositions do not depend on input order; supplied pointers do, so full
report hashes can change with argument order. Source fields in the review sheet are unverified
retained claims, not a source endorsement. Keep dated historical cohorts separate from current
model or production results.

The report makes no factual verdict, model-quality score, preference, engagement result, invoice
amount or X visibility claim. It cannot select stories, change prompts, approve, post or rewrite.

## Invented example

An export with one pending observed draft, "Invented Station reached 40.2°C on 3 September, its
highest in the available GHCN archive through 2026-09-02.", reports:
- one included identity, one sentence, and no warnings;
- fact-check `passed` and critic `PASS`, as recorded;
- publication `no_publication_recorded`.

The review sheet lists unverified retained source fields (for example `observed_high_c: 40.2`), the copy,
and a blank line for the editor's nonblind judgment of why a reader should care.
