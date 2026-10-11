# Local MODIS thermal-detection preview

This offline preview plots one to four retained MODIS pixel measurements from one
complete fire StoryBundle. It makes no source, model or image-generation request.
Production rendering, attachment and publication are not activated.

The chart uses pixel-integrated fire radiative power (FRP) in MW. Pixel centers
are not exact flame locations or fire perimeters. Multiple pixels do not establish
a count of separate fires; the same source minute does not establish simultaneity,
one overpass or a common incident. Retained receipts omit scan/track dimensions.
See the [NASA FIRMS MODIS field reference](https://firms.modaps.eosdis.nasa.gov/descriptions/FIRMS_MODIS_Firehotspots.html).

## Input contract

`fire_graphic_spec` requires the full P05-qualified bundle, an independently
retained SHA256 for that bundle, an ordered list of full-receipt hashes (primary,
then every related signal), and an explicit boolean `synthetic`. It validates
source receipts and each primary/related identity, acquisition minute and rounded
FRP headline. No related rows are dropped to make a story fit.

All rows must be MODIS_NRT from the same canonical Terra or Aqua platform and
reported UTC minute. T/Terra and A/Aqua aliases are accepted. Duplicate pixels,
colliding event identities, mismatched summaries, other products, fire footprints,
human-impact extensions and more than four measurements are refused. Geocoder
and climate annotations remain bound in the full story but are not certified by
the measurement validation or displayed as source-derived geography.

Bars start at zero and retain input order. Their lengths use exact source FRP;
labels explicitly round FRP to one decimal and coordinates to four. Exact parsed
values, source confidence, version, precision and qualifications remain in alt
text; original source spelling remains in the bound input. Confidence is a source
quality estimate, not a probability of cause or impact. All-zero charts and values
that cannot fit the readable layout are withheld without clipping or smaller text.

## Local workflow

Use private/ignored input and output paths. Repeat the receipt argument for every
retained measurement, in order:

```sh
python scripts/build_fire_graphic_spec.py \
  --bundle PRIVATE_BUNDLE.json \
  --expected-bundle-sha256 INDEPENDENT_BUNDLE_SHA256 \
  --expected-receipt-sha256 PRIMARY_RECEIPT_SHA256 \
  --expected-receipt-sha256 RELATED_RECEIPT_SHA256 \
  --synthetic false --output PRIVATE_SPEC.json
```

The CLI reads bounded strict local JSON and creates the output exclusively. It
does not read application state, contact a provider or replace an existing file.
Use the existing optional preview renderer and private media-review package flow
described in [the local media-review guide](handoffs/2026-09-10-p31-local-media-review-packet.md).

Template `modis_thermal_detections`, template version `p31-modis-thermal-1`, and
adapter version `p31-firms-modis-1` participate in existing exact cache and review
identities. Validation reconstructs the entire chart projection from the retained
bundle, so rehashing an edited chart value does not make it eligible. Changing
text, evidence, policy or assets invalidates the corresponding prior review.

A package is unreviewed and unapproved. Receipt consistency does not authenticate
the original HTTP response, certify every source claim, establish current source
freshness or prove agreement between the tweet and graphic. Those are separate
review and production integration requirements. Public tests use invented data;
historical source packets and exact draft text stay private.
