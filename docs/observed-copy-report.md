# Observed-copy report

An offline, advisory command that shows what happened to the copy the bot saved. It reads only
the local JSON exports you name, writes a new private directory, and changes nothing else.

```
python scripts/observed_copy_report.py --input EXPORT.json [--input OTHER.json] --out NEW_PRIVATE_DIR
```

Each input is a state snapshot (`drafts`, optional `suppressions`) or a list of drafts. Inputs are
read without following symlinks, devices or FIFOs, up to 64 MB each and 16 inputs. The output
directory must not exist; it is created `0700` with three `0600` files:

- `report.json` and `report.md`: counts only, with no draft text.
- `review-sheet.md`: the private editor sheet, the only file that contains exact copy.

## What it reports

- **Identities:** the same draft id with identical bytes in two exports counts once. Different
  bytes for the same id are a conflict, held and excluded, never picked.
- **Recorded stages:** generation, fact-check, critic, status, publication, and whether the saved
  text equals the writer's accepted output (by its recorded hash).
  - Missing records are `unknown`.
  - Recorded generation failures are activity, not zero.
  - A saved draft is not a post.
  - A stored tweet id is a recorded receipt, not verified X visibility.
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

The report makes no factual verdict, model-quality score, preference, engagement result, invoice
amount or X visibility claim. It cannot select stories, change prompts, approve, post or rewrite.

## Invented example

An export with one pending observed draft, "Invented Station reached 40.2°C on 3 September, its
highest in the available GHCN archive through 2026-09-02.", reports:
- one included identity, one sentence, and no warnings;
- fact-check `passed` and critic `PASS`, as recorded;
- publication `not_published`.

The review sheet lists the retained source facts (for example `observed_high_c: 40.2`), the copy,
and a blank line for the editor's nonblind judgment of why a reader should care.
