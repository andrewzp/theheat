# Local delivery rehearsal

This experimental path delivers invented, reviewed text and graphics to an
explicit loopback HTTP fixture. It does not publish to X or Bluesky. Gist remains
the production authority and automatic publishing stays paused. A local receipt
does not establish a provider account, permission, post, delivery cost or live
service reliability.

The existing editor workflow supplies one generated/admitted draft, retained
native PNG and full alt text, human joint review, four fresh revision checks and
a publisher's parked `local_joint_media` approval. The draft remains pending and
`publication_approved` remains false. Delivery does not renew those checks, alter
their state version or change what any live sender accepts.

## Explicit setup

Use an isolated local PostgreSQL database and the existing owner/runtime roles.
The owner explicitly calls `PostgresCommandAuthority.initialize_delivery(now=…)`
after installing media staging. Migration012 atomically adds the delivery schema
and immutable command-catalog upgrade receipt. It preserves original command
metadata and earlier migration receipts. Runtime cannot install it; old command
validators refuse the upgraded catalog. There is no automatic migration, reverse
migration or production backend switch.

Create one operator-owned fixture configuration file, mode0600 under a mode0700
directory. It has exactly these fields (replace the instance UUID and assigned
nonzero local port for the owned fixture):

```json
{
  "schema_version": 1,
  "scope": "local_http_fixture_v1",
  "invented": true,
  "instance_id": "7f98606b-1713-4ac7-950d-ec2ee20634e6",
  "origin": "http://127.0.0.1:3138",
  "routes_version": 1,
  "actor": "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
}
```

Supply its absolute path with `--delivery-fixture` to the local ingress and
command worker, alongside the existing explicit socket/database/operator/source
and native-renderer configuration. Its bytes are pinned on configuration and
rechecked on use. It contains no secrets. No provider credentials, production
environment, PG override variables, arbitrary hosts, proxies or redirect routes
are accepted. Changing the file requires a new explicit setup, not a dispatch
retry. The test server in `tests/local_delivery_helpers.py` implements this fixed
invented protocol and retains an independent acceptance journal.

Only a new `approve_media_revision` consumed with the verified fixture
configuration enrolls two obligations in the same transaction as the original
parked approval, state and result. An existing parked approval is never silently
backfilled by a read. Unconfigured P31 behavior remains unchanged.

## One explicit phase at a time

`python -m src.commands.preview_delivery_worker` uses the same local connection,
operator/source/native configuration arguments, plus `--delivery-fixture`,
`--intent-id`, `--platform`, `--stage` and `--owner`. Without `--execute` it reports
disabled before accessing a clock, database or network. Use `--execute` only for
an invented local fixture. There is no scheduler or HTTP execution control.

The stage order is X `upload` → `alt` → `create`, and Bluesky `upload` → `create`.
Each phase requires confirmed predecessors. The real pinned SDK serializes its
request and parses the actual local HTTP response. PNG, full text, alt text and
upstream media references must match the retained review exactly.

The worker commits a unique request barrier before the socket, then independently
rechecks original currentness. The original absolute deadline also follows the
child to the socket. A phase has at most one mutation attempt: no retry on upload,
alt, create, timeout or error. The new delivery lease does not extend editorial
eligibility. Database revocation and an external socket cannot be atomic; a
crash in the final gap remains unknown unless conclusive evidence is retained.

## Recovery and readback

Restart the same intent/platform/stage to interpret already retained observations.
It will not send another mutation. Raw response bytes commit before derived
receipts, including bounded partial prefixes. A completed late response may be
retained passively after expiry; it cannot enable the next stage.

An unknown outcome permits an explicitly requested `--execute --reconcile` on
the same original phase. This performs one read-only GET of the fixture's
independent acceptance journal, bound to the original instance, attempt and exact
wire request hash. Empty lookup, mismatched witness, malformed response or a
contradictory receipt remains unknown and never releases a retry. A confirmed
upload is not a confirmed post. Platforms retain independent outcomes; partial
success does not resend a confirmed platform.

The authenticated draft-scoped graphic view shows local stage status, including
unknown outcomes and stale review. It has no send/retry button and exposes no
generic artifact reader. The database retains all original receipts and holds
unresolved effects across edits, restarts and full restore. A new parked intent
cannot hide unknown work or repeat a confirmed local post for the same event.

## Compact station claims

An explicitly configured retained GHCN resolver can supply the full evidence for
a compact saved station claim. It resolves before opening a mutation transaction;
each locked enrollment, acquisition and dispatch boundary authorizes the actor
and checks the exact source, baseline, selection, policy and draft revision again.
No downloaded table is added to model requests, and resolving evidence does not
extend the original review or source lifetime.

The worker's committed request barrier is itself an unknown outcome until a
response is retained. Final preflight recognizes only that exact worker-owned
transition, through a typed single-use context constructed with the committed
write. It does not waive an earlier or unrelated unknown outcome, allow a second
mutation, refresh a lease, or authorize delivery from a passive view.

The connected invented low-temperature case exercises one writer, all required
checks, native PNG preparation, joint review, attachment and fresh saved-revision
checks. Its three loopback SDK POSTs end with a lost create response; restart
does not resend, and one same-attempt journal GET reconciles the retained receipt.
Cancellation, editing and owned dump/restore preserve the original history.
Passive cost views keep initial and later check requests distinct and do not buy
calls or turn an unknown charge into zero. Full descriptions retain their exact
UTF-8 bytes, including a trailing newline; oversized representations still refuse.

This connected case is not the entire regression matrix. Opposite-comparator,
source/role/lease drift, source-outage history and existing delivery families
remain mandatory release checks. Hosted authority, live delivery, source truth,
human editorial judgment and provider invoices require separate evidence.

## Focused validation

```sh
THEHEAT_TEST_POSTGRES=1 THEHEAT_POSTGRES_BINDIR=/path/to/postgres/bin \
  python -m pytest tests/test_postgres_delivery.py tests/test_local_delivery_transport.py tests/test_posting.py
cd dashboard
node --test tests/editor-media.test.js
```

The PostgreSQL profile uses temporary owned databases and invented MODIS/PM2.5
inputs. It includes native graphics, actual HTTP/SDK phases, authenticated Next
handler readback, role/expiry drift, commit failures, conflicting receipts,
duplicate workers, full catalog/row/sequence restore and one pending command
resumed exactly once. Browser interaction, hosted/live transport qualification,
production migration and fencing every old publisher remain separate acceptance
requirements. This local rehearsal does not satisfy them.
