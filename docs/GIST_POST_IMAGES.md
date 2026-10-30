# Gist post images: native charts, CRW anomaly, published maps and radar

A saved Gist draft can carry one explicitly selected image into the existing manual
X post. Graphics help tell a story; no tweet needs one, and a text-only story with
its own evidence never waits for an image. Seven kinds are supported, each with its
own versioned recipe. Four native families are rebuilt from the saved source alone:

| Kind | Draft source | Image |
|---|---|---|
| `gist_temperature_comparator_v1` | full retained GHCN station comparator | observed station reading vs its archive comparator |
| `gist_pm25_forecast_v1` | unextended single-source `air_quality_hazard` model forecast | 24 hourly CAMS-via-Open-Meteo samples and their mean |
| `gist_modis_locator_v1` | 1–4 receipt-bound `MODIS_NRT` detections | locator map of pixel centres coloured by FRP |
| `gist_viirs_locator_v1` | 1–4 receipt-bound `VIIRS_NOAA20_NRT` or `VIIRS_NOAA21_NRT` detections | the same locator with VIIRS categorical confidence |

Three more need one exact retained input from the durable media store (below):

| Kind | Draft source | Image |
|---|---|---|
| `gist_crw_anomaly_v1` | qualified primary NOAA CRW regional SST anomaly + its retained CSV/metadata packet | sampled 1° cells on a blue-white-red scale, cos-latitude mean |
| `gist_published_radar_v1` | catastrophic NWS Tornado Warning with its full retained alert + a retained KTLX Local Standard frame | the unchanged NWS reflectivity image (pixel-equivalent PNG) |
| `gist_published_chart_v1` | an NHC advisory draft + a retained NHC track-forecast cone for the same storm and advisory | the unchanged NHC cone graphic (pixel-equivalent PNG) |

Rendering makes no source request, model call, geocoder lookup or paid call. The
existing strict adapters reconstruct every retained source row first; a dust,
station-corroborated, related or extended forecast, Suomi NPP, NOAA HMS, CRW native
fallback or multisignal bundle, any non-KTLX radar, any other published product, or
any mixed product, platform or minute is refused rather than altered.

## What each image claims, and what it does not

- **CRW**: an L4 satellite analysis against the product's own daily climatology
  (1985–2012, recentred to 1985–1990 + 1993), not a 1991–2020 average or a
  thermometer reading. Each square is one sampled cell on a 1° stride; gaps are
  unsampled and grey outlines are excluded cells. Not a continuous surface, a
  full-grid census, a record, an El Niño classification or an impact.
- **Radar**: station reflectivity in dBZ at one minute. Not rainfall, accumulation,
  a tornado detection or damage. "Radar context at Oklahoma City" is a named-point
  relation inside the warning polygon, not the warning footprint.
- **NHC cone**: the forecast probable track of the storm's centre (circles enclose
  about two-thirds of historical official errors). Not storm size and not the
  hazard area; hazards can occur outside it. A forecast, never an observation.

## Operator flow

1. Open the draft in the dashboard. For CRW, radar or a cone, first paste the exact
   retained identity printed by the retention command (below). A CRW draft whose
   collector retained its packet arrives with that packet already selected (the help
   text says so); any other packet is refused. **Preview graphic**
   builds the image from the saved source. On a phone, **View full size** opens it at
   the full screen width; Escape or **Close full-size image** returns to the page.
   For a published image, **Original as retained** shows the exact original beside
   the pixel-equivalent PNG that X receives, with attribution, reuse basis, issue/
   frame time, quantity, legend and context. Small original labels may need the
   full-size view on a phone; that is inspection, not a mobile-readability claim.
2. Check the image, the **Image description sent to X**, and the **Expanded source
   details (not sent)**. The posting note says whether the source is currently
   inside its posting window. A historical preview stays available to inspect.
3. **Attach graphic** saves only the image recipe to the draft: source, renderer and
   image identities plus the bounded description. Gist never stores PNG bytes.
4. Tick the review box and **Record joint review**. A text-only review cannot cover
   an attached image, and automatic scheduling is refused. A published image also
   needs its three checks ticked by you (labels/time, context and unaltered reuse
   conditions); none defaults to confirmed and software does not read the image.
5. **Approve + Post** dispatches the existing manual post. The sender rebuilds the
   PNG and both descriptions from the saved source, checks every identity and the
   source time again, and uploads exactly the reviewed bytes and description.

The picker and **Operations › Post-image families** name each family's lane (native,
retained packet or published), what it needs and the input missing on this deployment.
A store setting is reported as configuration only, never as proven access or hosted
rendering. **Delivered graphics** rebuilds a delivered CRW, radar or cone image from the
retained identity its own receipt-named revision recorded (the same reader as the
preview and sender); a missing store or artifact holds and nothing is substituted.
In the retained-input field only the exact SHA256 is accepted: a web address, file path
or name is named and refused before any request.

Editing the text, changing quote references, replacing or removing the image are
real revisions: they revoke the joint review and any approval. If the renderer or
source no longer matches, preview again and use **Replace attached graphic** or
**Remove graphic**; removal never needs a usable image.

## Portable exact image bytes (recipe schema 2)

The reviewed PNG bytes are what X receives, so they must be identical wherever the
preview (dashboard) and the sender (scheduled bot) rebuild them. Every native family
now writes its PNG with one small canonical serializer, `src/media/canonical_png.py`
(profile `canonical-png-fixed-huffman-1`): only IHDR, one IDAT and IEND; a fixed
per-row Sub/Up filter rule; one fixed-Huffman DEFLATE block. The host's zlib no longer
chooses any byte, so its version is no longer part of the recipe. The codec source,
fonts, Pillow/FreeType versions, layout and source bindings still are.

Drawing, fonts, data and pixels are unchanged: every invented .46 test image decodes
to exactly the same RGB pixels; only the compressed bytes differ (about 215–250 KB,
under the 750,000-byte bound).

A schema-1 attachment saved before this change is refused with "render profile
changed; preview and review again". Preview it again, attach the new recipe and
record a new joint review; nothing upgrades an old recipe or its approval silently.
**Remove graphic** stays available for an old or broken attachment.

## Source time for approval and sending

These are image-path rules, not provider-certified expiry times.

- PM2.5 forecast: the request precedes retrieval, which precedes now; now lies in
  the forecast's local calendar day `[valid_start, valid_end)` in UTC; and the
  request is at most 24 hours old.
- MODIS/VIIRS: every selected receipt must be fresh under the unchanged
  `fire_source_contract.freshness` rule (0–2 UTC source days; a future minute refuses).

Approval refuses outside these rules. The sender checks again after rebuilding the
image and immediately before the first upload. A failed or uncertain upload or
create is recorded as unknown and is never resent, downgraded to text-only or
replaced by another card.

## Descriptions

The full adapter description stays available as expanded source details. The
description sent to X is a separate versioned projection (`pm25_delivery_v1`,
`modis_delivery_v1`, `viirs_delivery_v1`). It must fit both 1000 Unicode scalars
and 1000 UTF-8 bytes, the existing conservative house limit, not a claim about
X's current byte policy. Text is never truncated, rounded or rewritten by a model.
If the mandatory content cannot fit, the image is refused and the text draft is
unchanged.

- PM2.5: forecast, source and grid nature; city and grid point; local day,
  timezone and UTC window; retrieval time; all 24 exact values keyed by local
  hour; the exact mean; straight-line reading; and no station, exposure,
  health-category or model-run claim.
- MODIS/VIIRS: product, platform and reported UTC minute; each detection's exact
  centre, FRP, confidence (MODIS percent, VIIRS category) and version, with shared
  fields stated once only when identical; the linear colour range and equal
  markers; and the pixel, perimeter, severity, same-minute, projection,
  coarse-land, small-island, inset, dateline and close-up limits.

Hashes bind the reviewed choice. Joint review assesses the text and image
against the saved source.

## Durable media store and retained inputs

Published originals, their pixel-equivalent PNGs and retained CRW source packets
need exact bytes that both the dashboard preview and the bot's sender can read.
They live in an immutable content-addressed store; Gist keeps only a SHA256
reference. Without a configured store those lanes show a named hold and native
charts and text posts are unaffected. There is never a fallback to another store,
a URL, an older asset or another rendering profile.

### Store configuration (two separate capabilities)

| Who | Capability | Settings (server-side only) |
|---|---|---|
| Vercel preview function | read-only | `THEHEAT_MEDIA_STORE=postgres`, `THEHEAT_MEDIA_STORE_DSN=<reader DSN>` |
| Actions manual sender (`manual_tweet`) | read-only | repo variable `THEHEAT_MEDIA_STORE=postgres`, secret `THEHEAT_MEDIA_STORE_DSN` |
| CRW collector retention (opt-in) | insert-only | variable `THEHEAT_CRW_PACKET_RETENTION=1`, variable `THEHEAT_MEDIA_WRITER_STORE=postgres`, secret `THEHEAT_MEDIA_WRITER_DSN` |
| Local operator | either | `--store sqlite:<absolute path>` (both), or the variables above |

`.github/workflows/bot.yml` passes the reader settings only to `manual_tweet` runs and
the writer settings only to other runs, and only when retention is `1`. Never give
the writer DSN to the preview, the browser or the sender. A DSN is a keyword/value
string (`host= port= dbname= user= password= sslmode=verify-full sslrootcert=system`
or an absolute CA file; `channel_binding=require` is implied). URLs, service names,
password files, client certificates and ambient `PG*` variables are refused before
any connection. Each operation uses one short transaction (5 s connect, 10 s
statement, 20 s transaction) and closes its connection. The PostgreSQL table is
`theheat_media.artifacts` (migration 009); the reader role needs only `SELECT`, the
writer only `SELECT, INSERT`. Provisioning the database, roles and secrets is a
separate operator step this code does not perform; the exact procedure, cross-host
readback acceptance and rollback are in [MEDIA_STORE_SETUP.md](MEDIA_STORE_SETUP.md).

### Collector retention (CRW, default off)

With `THEHEAT_CRW_PACKET_RETENTION=1` the CRW collector keeps the exact primary
ERDDAP CSV and metadata bytes it already downloaded (no extra request), verifies
them with the same rules the preview uses, retains the packet through the writer and
saves only its identity on the draft. The run report's `media_retention` counts each
outcome: `retained`, `store_unavailable`, `retention_unknown` (acknowledgement lost:
not counted as retained; rerunning retention is safe), `unsupported_source_leg` (the
NOAA STAR fallback is never relabelled as primary), `source_unqualified`,
`packet_unavailable`, `packet_too_large`, `packet_invalid`, `retention_error`. Any
outcome other than `retained` only holds the image; the text story is unchanged.

### Retention, export and restore commands

Retain already acquired private files locally (no fetch, upload endpoint, review or
approval):

```sh
python scripts/retain_gist_media.py published --product nhc_track_cone_v1 \
  --metadata META.json --original ORIGINAL.png --product-reference PRODUCT.bin \
  --reuse-reference REUSE.bin --receipt RECEIPT.bin
python scripts/retain_gist_media.py crw-packet --packet PACKET.json
python scripts/retain_gist_media.py verify --manifest SHA256
python scripts/retain_gist_media.py backup --target /absolute/new-backup.sqlite3
python scripts/retain_gist_media.py export --target /absolute/new-dir \
  --manifest SHA256 --crw-packet SHA256
python scripts/retain_gist_media.py restore --source /absolute/export-dir
python scripts/retain_gist_media.py plan --state /absolute/private-state.json
python scripts/retain_gist_media.py readback --manifest SHA256 --crw-packet SHA256
```

`readback` re-reads named identities through this host's read-only store and prints
only kinds, identities and counts; run on each host it is the cross-host acceptance read.

`plan` reads an owner-only local copy of the saved state (nothing is fetched) and lists
every retained item its drafts need, why (unresolved delivery, current joint review or
approval, delivered history, attached) and whether this store can serve it. Missing or
changed items are named holds (`media_original_missing`, `media_source_packet_missing`,
`media_asset_changed`, ...), exactly the holds the preview and the sender apply before
any attachment or upload; present items are grouped into `export` arguments.

`export` writes a new owner-only directory with each selected item's complete,
re-verified closure (manifest, original, canonical PNG, receipt, product and reuse
references; or the CRW packet) under their exact SHA256 names. `restore` checks every
file, size, hash and relation before inserting anything through the writer, and
refuses missing, corrupt, oversized, conflicting, symlinked, FIFO/device or
unexpected entries and any existing output. Include every asset referenced by an
unresolved delivery or a current review. Export is not a database backup or a draft
migration; PostgreSQL has no `backup` command here, and SQLite backups keep working.

Inputs must be absolute, non-symlinked, owner-only (0600) files. A product
reference and a reuse reference are both required; unknown rights, missing labels,
an unlisted host, animation or changed bytes refuse. The derivative is the
canonical RGBA PNG of the decoded original, never cropped, recoloured or rescaled;
the original keeps its own identity. Nothing deletes retained assets: never remove
one referenced by history, an unresolved delivery or a current review.

## Named holds

| Hold | Meaning and safe next action |
|---|---|
| `media_store_unavailable` | No media store here; native charts still work. Configure the store or post text only. |
| `media_retained_input_required` | Paste the retained packet/asset identity. |
| `media_source_packet_mismatch` | Not the CRW packet the collector retained for this draft; select the draft's own packet. |
| `media_source_packet_invalid` | The draft's packet reference is malformed; the image stays held (text is unaffected). |
| `media_source_packet_missing`, `media_original_missing` | Retain the input locally again; nothing is fetched. |
| `media_asset_changed`, `media_asset_invalid` | Bytes, rights, labels, times or format changed or are incomplete; retain again. |
| `media_context_mismatch` | The image is for another storm, advisory, warning, place or time. |
| `media_published_stale`, `media_forecast_ended`, `media_detection_stale`, `media_source_stale` | Past its posting window; it stays inspectable but cannot be approved or sent. |
| `media_renderer_changed` | Recipe/profile changed; preview again and record a new joint review, or remove. |
| unknown delivery | An upload or post acknowledgement was lost; reconcile, never resend. |
| store fails after approval | The send stops before any intent; the draft returns to pending. When the store is back, approve again (a reconnected store authorizes nothing). |

Recency rules for the store-backed kinds: CRW uses the unchanged 0–5 day product
rule; radar the 15-minute editorial ceiling inside its warning interval; the cone
a 6-hour editorial ceiling from its advisory issue time. Each is rechecked at
approval and immediately before the first upload.
