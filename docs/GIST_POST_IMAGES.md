# Gist post images: temperature, PM2.5 forecast, MODIS and VIIRS

A saved Gist draft can carry one explicitly selected, source-derived PNG into the
existing manual X post. Four families are supported, each with its own versioned
kind and renderer:

| Kind | Draft source | Image |
|---|---|---|
| `gist_temperature_comparator_v1` | full retained GHCN station comparator | observed station reading vs its archive comparator |
| `gist_pm25_forecast_v1` | unextended single-source `air_quality_hazard` model forecast | 24 hourly CAMS-via-Open-Meteo samples and their mean |
| `gist_modis_locator_v1` | 1–4 receipt-bound `MODIS_NRT` detections | locator map of pixel centres coloured by FRP |
| `gist_viirs_locator_v1` | 1–4 receipt-bound `VIIRS_NOAA20_NRT` or `VIIRS_NOAA21_NRT` detections | the same locator with VIIRS categorical confidence |

Rendering makes no source request, model call, geocoder lookup or paid call. The
existing strict adapters reconstruct every retained source row first; a dust,
station-corroborated, related or extended forecast, Suomi NPP, NOAA HMS, or any
mixed product, platform or minute is refused rather than altered.

## Operator flow

1. Open the draft in the dashboard. **Preview graphic** builds the image from the
   saved source. On a phone, **View full size** opens it at the full screen width;
   Escape or **Close full-size image** returns to the page.
2. Check the image, the **Image description sent to X**, and the **Expanded source
   details (not sent)**. The posting note says whether the source is currently
   inside its posting window. A historical preview stays available to inspect.
3. **Attach graphic** saves only the image recipe to the draft: source, renderer and
   image identities plus the bounded description. Gist never stores PNG bytes.
4. Tick the review box and **Record joint review**. A text-only review cannot cover
   an attached image, and automatic scheduling is refused.
5. **Approve + Post** dispatches the existing manual post. The sender rebuilds the
   PNG and both descriptions from the saved source, checks every identity and the
   source time again, and uploads exactly the reviewed bytes and description.

Editing the text, changing quote references, replacing or removing the image are
real revisions: they revoke the joint review and any approval. If the renderer or
source no longer matches, preview again and use **Replace attached graphic** or
**Remove graphic**; removal never needs a usable image.

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
