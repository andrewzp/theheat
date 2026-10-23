# Private model-request evidence (operator guide)

TheHeat can retain an exact, private, local record of what its synchronous
model calls sent and received during an explicitly enabled rehearsal, then
verify, inspect and compare that record offline. It is **OFF by default**.
Nothing enables it automatically: there is no environment flag, home/profile
discovery or startup hook.

What it is: mechanical evidence binding the actual source bundle, the memory
slice, each candidate text, every logical request, every physical SDK request
body, every returned HTTP entity, the stage outcomes and the terminal pipeline
result, with local code/prompt hashes as provenance.

What it is not: a factual, editorial, approval, billing, invoice, cost-saving or
completeness authority. Code hashes and caller labels never certify anything.
A request hash or a selected candidate is not a full archive. Unknown cost stays
unknown. Model rejection is not scientific adjudication.

## Privacy contract

- Full prompts, responses, memory/source snapshots and candidate texts are
  written only under an operator-selected absolute directory that is
  canonical (no symlinked component), owned by you and mode `0700`; files are
  `0600`. Nothing is written to Gist, ordinary bot state, suppression rows,
  saved drafts, public logs, the dashboard or the repository.
- Authentication headers, API keys, client objects, cookies, environment
  dumps, query strings and exception messages/reprs are never captured. Only
  exception class names, integer HTTP status codes and allowlisted response
  headers (`content-type`, `content-encoding`, `content-length`, `request-id`,
  `x-request-id`) are retained. Provider IDs are recorded only when actually
  exposed (Anthropic `request-id` header and message `id`; Google `responseId`).
- Per-request transport overrides (`extra_headers`, `extra_query`, `extra_body`,
  timeout and Google config HTTP options) are refused before logical retention.
  Capture accepts only the pinned synchronous SDK method with this scope's request
  and response hooks installed. Earlier/unhooked clients and arbitrary wrappers
  are refused before execution. Model-body content itself is retained verbatim;
  it must not be used to carry credentials.
- Directory components are opened without following symlinks. Capture pins its
  original private directory handles; reads and exports use descriptor-relative
  operations. Renaming or substituting a directory cannot redirect a write.
- Every error raised by the archive is a fixed code such as
  `archive_scope_held`, never content or a path.
- Default CLI output is a content-free JSON summary (identities, hashes,
  counts, availability). Exact content goes only to a new private file via
  `export`.

## Capturing a local rehearsal

```python
from pathlib import Path
from src.two_bot import request_archive

root = Path("/Users/YOU/theheat-private/request-evidence")  # absolute, canonical, 0700
with request_archive.capture(root, operation="local rehearsal 2026-10-23") as scope:
    draft, result_out = scope.run_generation(bundle, state)
print(scope.directory)  # scope-<32 hex>; record this path
```

`run_generation` runs the actual `pipeline.generate_draft` and appends a
`terminal` record built from its real return value. Calling `generate_draft`
directly inside the scope also captures every call, but then the terminal
association is reported as `unavailable`.

Scope rules: one scope per process, owned by the thread that opened it.
Nested, concurrent, reused and closed scopes are refused. While a scope is open,
a provider call from any other thread or context is refused **before sending**
and recorded as `foreign_call_refused`. The context resets on every exit,
including exceptions.

## What is recorded, in order

1. `scope_opened`: limits, sha256 of the named pipeline/stage/prompt source
   files, the editorial-policy fingerprint, SDK versions, and your label
   (marked `caller_label_only`).
2. `generation_input`: the exact `BundleCapture` serialization and the
   memory slice. `bundle_sha256` equals the draft's `reviewed_bundle_sha256`.
3. `candidate`: the exact selected text before checks. Its hash equals the
   draft's `reviewed_text_sha256` when accepted.
4. `call_intent`: written and fsynced **before** the SDK runs, with a
   type-tagged logical view of the kwargs (`tagged_kwargs_json_v1`). This is
   a serialization of the arguments, not the sent bytes.
5. `wire_request`: the exact request entity bytes at the SDK's own HTTP
   client (`httpx2` for Anthropic, `httpx` for Google), written and fsynced
   inside the client's request hook, **before** the transport sends.
6. `wire_response`: status, allowlisted headers and the decoded HTTP entity.
   Content-encoding has already been removed by the transport, so this is not
   compressed wire bytes.
7. `call_result`: returned/raised, the exception class only, attempt
   counts, `billing: "unknown"`, and an archival label.
8. `stage_outcome`: each pipeline pass or kill, bound to the exact candidate
   hash at that moment. A revised text never inherits an earlier verdict.
9. `terminal`: the accepted/kill result of `generate_draft`, with
   `approval: none` and `publication: none`.
10. `scope_closed`: totals. An archive without this record is never complete.

Each manifest line is canonical JSON (sorted keys, no floats or NaN, strict
UTF-8) and chained to the previous line's sha256. Artifacts are
content-addressed exact bytes. Exact duplicates are stored once.

## Limits (per scope; never truncated)

| Bound | Value |
|---|---|
| Logical request | 2 MiB |
| Raw wire request | 2 MiB |
| Raw response retained | 2 MiB |
| One manifest record | 64 KiB |
| Provider calls / physical send attempts | 128 / 128 |
| Total retained artifact content | 32 MiB |

Beyond a limit, new capture is refused before sending. A response over 2 MiB is
recorded as `not_retained_over_limit` with its size and hash, and the scope is
**held**. It is never zero cost, never an approved result and never
permission to resend.

There is no automatic deletion, garbage collection or rotation. Storage grows
by at most 32 MiB of artifacts per scope plus its manifest (at most a few MiB of
small records). Remove old scopes manually only when you no longer need the
evidence.

## Failure semantics (no rebuy)

| Event | Result |
|---|---|
| Refusal before the send (limits, streaming/unsupported endpoint, foreign thread, pre-send write failure) | Nothing is sent. `refused_before_send` or `call_refused` is recorded. |
| Write failure after a possible send (response artifact or record) | The scope is **held** permanently. The call raises `RequestArchiveHeld`. Outer retries are refused before sending, so no replacement is bought. |
| Transport timeout or read failure after the send | `raised_after_send` with `provider_outcome: unknown` and `billing: unknown`. The caller's existing retry rules still apply, and each retry is its own recorded call. |
| Trial budget active | The trial's reservation and wire guard run **first**. Evidence is recorded only for a send the trial allowed. Reservations are never refunded. |
| Process interrupted | Every record already written stays durable. The archive validates as `incomplete` (`scope_not_sealed`, `call_without_result:N`, `stray_temporary_file`). Nothing is repaired or adopted. |

Streaming (`stream=True`, `:streamGenerateContent`, `alt=sse`) is unsupported
and refused before any send. Writer slates with samples > 1 run in worker
threads, so they are refused. Batch, experimental command transports and other
paid routes are not covered.

## Offline inspection

Use the locked SDK interpreter. No command sends, generates, executes archive
content, opens URLs or reads live state, and none of them has a
force/send/retry/repair mode.

```sh
PY=/ABS/VENV/bin/python
$PY scripts/replay_request_archive.py validate /ABS/ROOT/scope-<id>
$PY scripts/replay_request_archive.py inspect  /ABS/ROOT/scope-<id>
$PY scripts/replay_request_archive.py lineage  /ABS/ROOT/scope-<id>
$PY scripts/replay_request_archive.py compare  /ABS/A/scope-<a> /ABS/B/scope-<b> --call-a 3 --call-b 3
$PY scripts/replay_request_archive.py export   /ABS/ROOT/scope-<id> --call 1 --output /ABS/PRIVATE-0700-DIR/call-1.json
```

Exit codes: `0` complete, `1` incomplete, `2` invalid or refused, `64` usage.

- `validate` verifies, from the retained files alone, the canonical bytes,
  hash chain, sequence, record schema, artifact hashes and sizes, call/attempt
  ordering, result counts, sealed totals, permissions and the absence of
  symlinks. It also recomputes bundle/memory identities, candidate and revision
  associations, call/stage bindings and terminal text/source hashes. This checks
  consistency, not authorship: an unsigned hash chain cannot authenticate its author.
  Changed, missing, duplicated, reordered, forged-but-rechained,
  oversize or partial input is `invalid` or `incomplete`, never upgraded.
- `lineage` shows input → candidates → bound calls and stage outcomes →
  terminal. A stage decided without a provider call (for example the local
  factual precheck) is shown as `decided_without_provider_call`. No paid
  response is invented for it.
- `compare` reports field differences and, for logical requests, JSON-pointer
  paths with the sha256 of each side's value, never the content.
- `export` writes one call's exact logical request, wire bodies and responses
  to a new `0600` file. It refuses an existing different file and is
  idempotent for identical bytes.

Programmatic access (versioned): `request_archive_replay.load_archive(path)`
returns a `VerifiedArchive` (`api_version == 1`) with `status`, `problems`,
`calls`, `inputs`, `candidates`, `stage_outcomes`, `terminals` and
`artifact(digest)`, which re-verifies the bytes on every read. Each `Body` has
an explicit `availability` (`captured`, `unavailable`,
`not_retained_over_limit`, `read_failed`, `not_observed`).

## Copyable synthetic example (invented, offline)

From the worktree, this runs the actual pipeline with real SDK serialization.
The HTTP transport is the invented test fixture, and nothing leaves the
machine.

```sh
PY=/ABS/VENV/bin/python
umask 077 && mkdir -p /tmp/theheat-private-demo && chmod 700 /tmp/theheat-private-demo
env -i PATH=/usr/bin:/bin HOME=/tmp/theheat-private-demo LC_ALL=C LANG=C NO_PROXY='*' no_proxy='*' \
  NETRC=/dev/null PYTHON_DOTENV_DISABLED=1 $PY - <<'EOF'
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, os.getcwd())
os.environ.update(ANTHROPIC_API_KEY="invented-offline", GEMINI_API_KEY="invented-offline",
                  THEHEAT_WRITER_SAMPLES="1", THEHEAT_CRITIC_ENABLED="1")
from src.two_bot import retry
retry.time = SimpleNamespace(sleep=lambda seconds: None)
from src.voice import safety
safety.GEMINI_API_KEY = "invented-offline"
from tests.test_request_archive_sdk import accepted_script, run_journey
root = Path(os.path.realpath("/tmp/theheat-private-demo")) / "archive"
run = run_journey(accepted_script(), root=root)
print(run.archive)
EOF
```

Then pass the printed `scope-…` path to `validate`, `lineage` and `export`
above. The expected `validate` status is `complete`, with four calls: writer,
safety, fact_check and critic. These outcomes are fixture outcomes, not
weather truth, copy quality, approval or a model result.

## Recovery

- A `held` scope stays held. Open a new scope for a new rehearsal. Do not
  edit, repair or adopt the old one, and do not delete it to hide a failure.
- `incomplete` means some evidence is missing: unsealed, truncated tail,
  stray temporary file, a call without a result, unobserved physical transport,
  or a held scope. Absence of a wire observation is never proof of `not_sent`. Inspect it
  as it is. Missing historical inputs remain missing.
- `invalid` means the bytes no longer verify. Keep the copy for diagnosis and
  never treat it as evidence.
- If the private directory's permissions are wrong, the tools refuse it. Fix
  the mode yourself (`chmod 700`/`600`) only if you know why it changed.
