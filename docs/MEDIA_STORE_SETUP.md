# Shared media store, CRW retention and published radar/cone: setup, acceptance and rollback

This is the operator procedure for the store-backed Gist post-image lanes described in
[GIST_POST_IMAGES.md](GIST_POST_IMAGES.md). It prepares the already-selected narrow
design: one immutable, content-addressed `theheat_media.artifacts` table, a read-only
role for the dashboard preview and the manual sender, and an insert-only role for CRW
packet retention and restore. Gist remains the draft, review, approval and receipt
authority. Nothing here is an image-publication authority, a test post or a backend
switch.

**Who runs it.** Root/Andrew, on an existing PostgreSQL provider already used by the
project. No step creates a paid resource, prints a secret or changes the bot's
publishing controls. Native charts (temperature, PM2.5, MODIS, VIIRS, Hot10) and all
text posts need none of this; they keep working whether or not the store exists.

## 1. Server requirements (check before any change)

- PostgreSQL **17 or later**. The adapter sets `transaction_timeout` as a startup option;
  an older server refuses the connection.
- A **direct, non-pooled endpoint** that accepts the libpq `options` startup parameter
  (`-c statement_timeout=... -c default_transaction_read_only=on ...`). Transaction
  poolers that strip or reject startup options are unsupported.
- TLS with a certificate that verifies against the system CA store (`sslrootcert=system`)
  or an absolute CA file; SCRAM-SHA-256 password authentication with channel binding
  (`channel_binding=require` is the adapter default).
- No `PG*` environment variables in the reader or writer process; they are refused.

## 2. Migration (once, as the database owner)

Apply the existing migration unchanged; do not edit it or add tables:

```sh
psql "<owner connection, entered interactively>" -v ON_ERROR_STOP=1 \
  -f src/storage/migrations/009_media_staging.sql
```

It creates schema `theheat_media`, the checked `artifacts` table (SHA256 key equals the
payload hash, 8 MiB per row) and triggers that refuse update, delete and truncate. The
`metadata`/`packages` tables in the same migration are not used by the media adapter.

## 3. Roles (least privilege, as the owner)

Generate each password with the provider's own secret tooling; do not paste it into a
shared terminal log or a file in the repository.

```sql
CREATE ROLE theheat_media_reader LOGIN;   -- then set its password through the provider
CREATE ROLE theheat_media_writer LOGIN;   -- then set its password through the provider
REVOKE ALL ON SCHEMA theheat_media FROM theheat_media_reader, theheat_media_writer;
GRANT USAGE ON SCHEMA theheat_media TO theheat_media_reader, theheat_media_writer;
REVOKE ALL ON ALL TABLES IN SCHEMA theheat_media FROM theheat_media_reader, theheat_media_writer;
GRANT SELECT ON theheat_media.artifacts TO theheat_media_reader;
GRANT SELECT, INSERT ON theheat_media.artifacts TO theheat_media_writer;
```

On every connection the adapter proves the role holds **exactly** these privileges on the
artifact table (reader: SELECT only; writer: SELECT and INSERT only) and refuses
otherwise, so an over-privileged role fails closed rather than silently working.

## 4. Configuration (server-side only; Andrew/root-owned production change)

A DSN is a keyword/value string, never a URL:

```
host=<db host> port=5432 dbname=<db> user=theheat_media_reader password=<secret> sslmode=verify-full sslrootcert=system
```

| Where | Setting | Value |
|---|---|---|
| GitHub repo variable | `THEHEAT_MEDIA_STORE` | `postgres` |
| GitHub repo secret | `THEHEAT_MEDIA_STORE_DSN` | reader DSN (`gh secret set THEHEAT_MEDIA_STORE_DSN`, value typed at the prompt) |
| Vercel (Production) | `THEHEAT_MEDIA_STORE` | `postgres` |
| Vercel (Production, sensitive) | `THEHEAT_MEDIA_STORE_DSN` | reader DSN (`vercel env add THEHEAT_MEDIA_STORE_DSN production`, value at the prompt) |
| GitHub repo variable (only for CRW retention) | `THEHEAT_MEDIA_WRITER_STORE` | `postgres` |
| GitHub repo secret (only for CRW retention) | `THEHEAT_MEDIA_WRITER_DSN` | writer DSN |
| GitHub repo variable (opt-in) | `THEHEAT_CRW_PACKET_RETENTION` | `1` only after acceptance below; `0` otherwise |

`.github/workflows/bot.yml` already passes the reader settings only to `manual_tweet`
runs and the writer settings only to collector runs while retention is `1`. The writer
DSN never goes to Vercel, the browser or the sender. Dashboard environment changes take
effect only after the normal **manual Vercel deployment**; a Git push does not deploy.

## 5. Acceptance: cross-host readback (no post)

Use a genuine retained input, never an invented artifact: rows are immutable and cannot
be removed. The first CRW packet the collector retains after `THEHEAT_CRW_PACKET_RETENTION=1`
(its identity appears on the draft and in the run report's `media_retention.retained`),
or a published cone/radar retained in step 7, serves as the acceptance identity.

1. **Writer host** (where retention ran): the run report shows `media_retention`
   `retained: 1` and the draft carries the packet identity.
2. **Local reader** (an operator shell holding only the reader DSN, no `PG*` variables):

   ```sh
   THEHEAT_MEDIA_STORE=postgres THEHEAT_MEDIA_STORE_DSN="$(read-from-your-secret-manager)" \
     python scripts/retain_gist_media.py readback --crw-packet <SHA256>
   ```

   Expected: exit 0, `"capability": "reader"`, every item `"verified": true`,
   `"credentials_printed": false`. The adapter has also proved SELECT-only privileges.
3. **Vercel preview host**: after the manual deployment, open that draft in the Workbench
   and choose **Preview graphic**. Expected: the image renders and the picker /
   **Operations › Post-image families** names the family as configured. A
   `media_store_unavailable` hold means the deployment lacks the reader settings.
4. **Actions sender host**: the sender reads the store only inside an approved
   `manual_tweet` run, immediately before upload. That is real delivery evidence and is
   a separate, explicitly authorized step (section 8); no test post is part of setup.

Record the identity, the three outcomes and their times in the release notes. A
configured setting is configuration only; it is not hosted-rendering proof until step 3
passes on the deployed dashboard.

## 6. Provider migration or recovery (old store stays untouched)

```sh
python scripts/retain_gist_media.py plan   --state /absolute/private-state.json   # reader of the OLD store
python scripts/retain_gist_media.py export --target /absolute/new-export-dir \
  --manifest <SHA> --crw-packet <SHA>                                          # every item plan lists
# switch THEHEAT_MEDIA_WRITER_* to the NEW store's writer, then:
python scripts/retain_gist_media.py restore --source /absolute/new-export-dir
python scripts/retain_gist_media.py readback --manifest <SHA> --crw-packet <SHA>  # NEW store's reader
```

Include every item referenced by an unresolved delivery, a current joint review or
delivered history (`plan` names each with its reason). Switch the reader settings in
GitHub and Vercel only after `readback` passes against the new store, then redeploy.

## 7. Published radar and NHC cone inputs (rights first)

A published image is used only with a retained **product reference** and **reuse
reference**: the exact bytes of the provider page or statement the operator relies on
for attribution and reuse. Software infers no rights; unknown rights, missing labels,
animation, an unlisted host or changed bytes refuse.

```sh
python scripts/retain_gist_media.py published --product nhc_track_cone_v1 \
  --metadata /abs/META.json --original /abs/ORIGINAL.png \
  --product-reference /abs/PRODUCT.bin --reuse-reference /abs/REUSE.bin --receipt /abs/RECEIPT.bin
python scripts/retain_gist_media.py readback --manifest <printed manifest_sha256>
```

All inputs are absolute, non-symlinked, owner-only (0600) files already acquired by the
operator; the command fetches nothing. Radar is bounded to the NWS KTLX local standard
frame inside a qualifying Tornado Warning ([PUBLISHED_RADAR_PREVIEW.md](PUBLISHED_RADAR_PREVIEW.md));
the cone to the same storm and advisory as an NHC advisory draft. A missing third-party
asset never blocks native graphics.

## 8. Rollback

- **Retention off:** set `THEHEAT_CRW_PACKET_RETENTION=0` (or delete it). Collector runs
  keep drafting text; packets are simply not retained.
- **Store off:** delete `THEHEAT_MEDIA_STORE`/`_DSN` in GitHub and Vercel and redeploy the
  dashboard. Store-backed images show `media_store_unavailable`; native charts and text
  posts are unaffected. An approval made while the store was reachable does not survive
  a store failure: the sender stops before any intent and the draft returns to pending.
- **Credential exposure:** `ALTER ROLE theheat_media_reader NOLOGIN` (or writer), rotate
  through the provider, update the secret, redeploy.
- **Never** drop the schema, delete rows or reuse a role with broader privileges; history
  and unresolved deliveries reference retained identities.

## 9. One qualified native graphics workflow (operating review)

The first useful image to verify needs no store: a native chart on a current, qualified
story. For root's authorized operating review:

1. Pick a pending draft whose family is native and whose source is current, e.g. a
   `gist_pm25_forecast_v1` air-quality forecast inside its local forecast day or a
   `gist_temperature_comparator_v1` GHCN comparator. Not the two drafts held for
   Andrew's discussion.
2. In the Workbench choose **Preview graphic**. Check the image on a phone width
   (**View full size**): title, units, forecast label, source and issue/valid time,
   legend; then **Image description sent to X** and **Expanded source details (not sent)**.
   The posting note must say the source is inside its posting window.
3. Read the draft's **Copy notes** and claims beside the image; text and plot must state
   the same values (hashes bind identity, not agreement).
4. **Attach graphic**, tick the review box and **Record joint review**. Any later text or
   image change revokes it.
5. **Approve + Post** dispatches the existing manual post (human decision; automatic
   sends stay text-only). The sender rebuilds the PNG and description, rechecks source
   time and uploads exactly the reviewed bytes once; a lost acknowledgement is recorded
   unknown and never resent.
6. Verify the receipt in the publish ledger, then **Delivered graphics › Inspect** on the
   posted draft: it must rebuild the identical PNG and description from the receipt-named
   revision.

Rollback before step 5: **Remove graphic** (text-only post remains available). After a
post, no automatic correction or deletion exists; a problem becomes a review-only
correction candidate (`scripts/theheat_evaluation.py correction-candidates`).
