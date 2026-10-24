# Integration packet

`scripts/prepare_integration_packet.py` turns a donor's local evidence into one
packet root can read: exact commits and trees, changed paths with byte hashes,
clean/dirty state, ordered donor commits, generator impact, and the supplied
command receipts with their raw hashes. Root can then integrate without
reconstructing commands, source identity and failures from a long conversation.

It is a local preparer and validator only. It is not CI, an orchestrator or an
authority, and it never promotes anything.

## What a packet can and cannot say

| Stage | Set by the packet |
|---|---|
| `implemented` | `verified_commits` once the donor chain is verified |
| `locally_tested` | `claimed`, `partial` or `unperformed`, from the supplied receipts |
| `stronger_review`, `exact_head_ci`, `merged`, `deployed`, `runtime_observed`, `product_accepted` | always `not_established_by_local_packet` |

**Refusals.** A request that tries to set a later stage is refused, and a
re-signed packet that carries one fails validation.

**Identity versus claims.**
- **Identity is verified.** The packet hashes every input file and reads git
  objects.
- **Exit codes are claims.** A receipt's `returncode` or `exit_code` is
  recorded as supplied. Receipts are parsed as data and never executed.
- **Missing is not passing.**
  - A required check with no receipt is `unperformed`.
  - A declared skip is `skipped`.
  - A malformed or nonfinite receipt is `malformed`.

  None of these counts as passing.

**Check outcomes.** Each check has one status:

| Status | Meaning |
|---|---|
| `claimed_pass` | every supplied receipt claims success |
| `claimed_pass_after_failure` | the last receipt claims success; earlier failures are kept |
| `claimed_fail` | the last receipt claims failure |
| `contradictory` | a receipt contradicts this head (see below) |

Receipts are kept in the order supplied, so earlier failures stay visible. A
receipt is `contradictory` when any of these holds:
- its claimed head differs from the line head;
- its log bytes do not match the log hash it states;
- the source hashes it records differ from the head's blobs;
- the same receipt bytes appear under a different binding
  (`conflicting_duplicate_binding`);
- the same check is also declared skipped.

**Duplicates.** Each receipt's complete binding (kind, log bytes, claimed head
and source prefix) is validated before any deduplication. Malformed binding
metadata is refused even on a repeated receipt.
- **Equal binding:** a repeat of the same bytes collapses into one row with a
  `duplicates` count.
- **Different binding:** the same bytes stay as separate rows, all
  contradictory, in the order supplied.

Nothing is replaced by a newer green row.

`locally_tested` is `claimed` only if every required check passes, nothing is
contradictory and the worktree has no tracked edits. Even then, it is a local
claim and not CI. An `allow_dirty` packet is labeled DIRTY, is never more than
`partial`, and never validates as clean.

## Request

A request is one JSON file the caller writes explicitly. Nothing else is read:
- no home directory, environment, `.env`, credentials or network;
- no install, shell or paid call.

```json
{
  "schema": "theheat.integration-packet-request/v1",
  "evidence_root": "/absolute/path/to/private/evidence",
  "lines": [{
    "label": "E3",
    "worktree": "/absolute/path/to/checkout",
    "branch": "codex/example",
    "base": "<40-hex commit>",
    "head": "<40-hex commit>",
    "donors": [{"label": "harness", "commit": "<40-hex>"}, {"label": "repair", "commit": "<40-hex>"}],
    "depends_on": [],
    "required_checks": ["focused-node", "gen_state_contract"],
    "receipts": [
      {"check": "focused-node", "path": "run/focused-node-receipt.json", "log": "run/focused-node.log"},
      {"check": "journey", "path": "run/launcher-receipt.json", "kind": "journey_launcher", "source_prefix": "dashboard/"}
    ],
    "skipped_checks": [{"check": "exact-head-ci", "reason": "root-owned"}],
    "artifacts": ["run/journey-result.json"],
    "local_claims": {"implemented": true, "locally_tested": true}
  }]
}
```

**Paths.**
- Receipt, log and artifact paths are relative to `evidence_root`.
- Each must be a regular file reached without `..` or any symlink.
- The packet records only these relative paths, never the root or the
  worktree.
- **Canonical paths only.** `evidence_root`, the `--out` directory's parent
  and the `--packet` directory must be absolute and canonical: no component
  anywhere, from `/` down, may be a symlink.
  - **Enforcement.** Every component is opened without following links,
    relative to its parent's descriptor. The output directory and its files
    are created through those descriptors, so a symlinked ancestor can never
    redirect a read or write.
  - **OS aliases are refused too.** For example, macOS `/var -> /private/var`
    and `/tmp -> /private/tmp` are symlinks. Pass the resolved path (for
    example `/private/var/...`).
  - **Relative paths.** A relative `--out` is refused.

**Donors.** `donors` must equal the exact first-parent chain `base..head`, in
cherry-pick order, so a reordered, missing or foreign commit is refused.

**Branches and checkout state.**
- If a `branch` is named, it must point at `head`.
- The packet records the worktree's actual `HEAD` commit and its tracked and
  untracked changes (bounded lists plus counts). These are commit IDs and
  repository-relative paths only.
- If the worktree's `HEAD` is the line head, tracked edits are refused unless
  `allow_dirty` is true.

**Receipt kinds.**
- `command` (default): `returncode`, `seconds` and `log_sha256`, the format of
  the private receipt runners.
- `journey_launcher`: `scripts/operator_media_journey.mjs`'s
  `launcher-receipt.json`, with `exit_code`, `steps` and `source_sha256`.
  `source_prefix` maps its dashboard-relative paths to repository paths, so
  the journey's source hashes are compared with the head's blobs.

**Generator impact.**
- **Outputs.** The six generator outputs are listed explicitly in the script;
  they are never guessed. Changed outputs are flagged.
- **Checks.** Each generator's status comes only from a supplied
  `gen_<name>` receipt; without one it is `unperformed`.
- **Regeneration.** Root owns ordered regeneration on a combined release.

## Commands

```bash
python scripts/prepare_integration_packet.py prepare --request REQUEST.json --out NEW_PRIVATE_DIR
```

```bash
python scripts/prepare_integration_packet.py validate --packet NEW_PRIVATE_DIR --evidence-root EVIDENCE --worktree E3=/path/to/checkout
```

**`prepare` refuses**, writing nothing, on any of these:
- an existing output directory, a relative output path, or a symlink in any
  component of the output's parent or the evidence root;
- an input file or git identity that changes while the packet is prepared;
- inputs over the size bounds.

**On success** it creates the directory with mode 0700 and three files with
mode 0600:
- `packet.json`: canonical, sorted and deterministic, with no timestamps and
  no absolute paths;
- `packet.md`: a compact summary rendered from that JSON;
- `packet.sha256`.

**`validate` checks:**
- that the packet directory and its files are reached through no symlink in
  any component;
- the marker, the packet ID and the canonical form;
- that the Markdown is exactly the rendering of the JSON;
- that no later stage is set.

Optional arguments add two more checks:
- `--evidence-root`: re-hashes every receipt, log, duplicate path and
  artifact.
- `--worktree LABEL=DIR`: reports two separate results per line.
  - `commit_identity` is `unchanged` or `moved`, from the trees and named
    branch.
  - `current_state` compares the checkout now with the recording: its actual
    `HEAD` and its tracked and untracked changes. It is one of:
    - `clean`;
    - `dirty_as_recorded`;
    - `not_at_line_head_as_recorded`;
    - `drifted`;
    - `unavailable`.

  Any drift makes the result `invalid`. A moved `HEAD`, even with the branch
  left in place, gives `worktree_head_changed`; changed edits or files give
  `worktree_state_changed`. A packet from schema v1 still verifies its
  integrity, but a requested current-state check fails with
  `current_state_unrecorded_in_packet`.

It exits 0 for `valid` and 1 for `invalid`.

Git runs read-only:
- fixed arguments, no pager and no optional locks;
- `GIT_CONFIG_NOSYSTEM`, with `GIT_CONFIG_GLOBAL=/dev/null` and
  `HOME=/nonexistent`.

## Walkthrough (invented, clean caller)

This was executed for E3/E4. The private outputs stay under
`.gstack/implementation/results/CLAUDE-E1-E4/`.

1. **Select the E3 focused journey and its retained result.** The journey runs
   only through `node scripts/operator_media_journey.mjs` with explicit pins
   into a new private directory; ordinary `node --test` skips it as
   unperformed. The walkthrough selects the final E3 run's retained files
   instead of repeating an unchanged green browser run:
   - `launcher-receipt.json`: exit code, steps and source hashes;
   - `journey-result.json`: named observations, with zero API mutations and
     zero denied requests.
2. **Write a request** with only those explicit files. Run it with
   `env -i PATH=/usr/bin:/bin HOME=<empty> LC_ALL=C`, using the locked Python.
3. **Prepare** into a new directory. The journey receipt's source hashes must
   match the head blobs, or the check is `contradictory`.
4. **Read back:** run `validate` with `--evidence-root` and `--worktree`, then
   read `packet.md`.

Also show the real donors without overclaiming. A packet over the E1/E2/E3
donor identities marks PostgreSQL, native, CI and deployment steps as skipped
or unperformed, and every later stage as not established.

## Limits

- **Identities, not quality.** The packet proves which bytes were present and
  which exit codes were claimed. It does not prove that a command ran as
  claimed, nor CI, review, cost, quality or coverage.
- **Paths.** The relative evidence paths come from the caller's private tree.
  Real packets stay private; do not commit them.
- **Bounds.** At most:
  - 16 lines, 64 donors per line and 2,000 changed paths per line;
  - 256 receipts and 256 artifacts per line;
  - 1 MiB per receipt and 64 MiB per artifact or log;
  - a 4 MiB packet.
