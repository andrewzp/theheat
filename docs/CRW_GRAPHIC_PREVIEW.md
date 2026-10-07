# Local sea-temperature anomaly graphics

`crw_regional_anomaly` renders an exact, retained NOAA Coral Reef Watch v3.1
ERDDAP regional warm-anomaly event. It uses no language/image model or network
call. This is a private review tool; production drafts and publishing stay unchanged.

Supply the saved StoryBundle and a separate source packet containing
`schema_version: 1`, `csv_utf8`, `metadata_utf8`, `csv_retrieved_at` and
`metadata_retrieved_at`. Preserve the exact UTF-8 response bodies and their actual
acquisition times. Both expected fingerprints must come from retained inputs.
The packet is limited to 500,000 UTF-8 JSON bytes, with a 400,000-byte CSV and
100,000-byte metadata limit; the complete graphic input remains below 1 MB.

```sh
python scripts/build_crw_graphic_spec.py \
  --bundle /absolute/private/bundle.json \
  --source-packet /absolute/private/source-packet.json \
  --expected-bundle-sha256 RETAINED_BUNDLE_FINGERPRINT \
  --expected-packet-sha256 RETAINED_PACKET_FINGERPRINT \
  --synthetic false --output /absolute/private/spec.json
```

The specification can be passed to `src.media.evidence_graphic_render.render_preview`
with an explicit local `pdftoppm` path and private output directory. ReportLab is
an optional local rendering dependency. Use `scripts/prepare_media_review.py`
with the unchanged saved draft, independent current policy/identity and all five
rendered assets to create a private text-and-graphic package. Never put real
source bodies, drafts or review packages in a public commit. Invented fixtures
must use `--synthetic true`.

The adapter independently decodes the full strided rectangle and recalculates its
latitude-weighted mean. Dates, region, units, sample coverage, tier, source hashes
and all bundle claims must match. Partial/mixed/duplicate coordinate grids and
fewer than ten accepted cells fail. Native NetCDF fallback, extended/multisignal
bundles and below-threshold or negative events are not supported by this first
adapter. A historical preview does not establish current freshness.

The graphic shows a sampled satellite-analysis anomaly, not absolute water
temperature or a complete regional average. CRW's daily reference is derived
from 1985–2012 data and recentered to 1985–1990 plus 1993; it is not the
1991–2020 average. The date labels a daily product, not a verified instantaneous
measurement. Cloud coverage limits confidence, particularly at high latitudes.
See [NOAA's product methodology](https://coralreefwatch.noaa.gov/product/5km/methodology.php).

New qualified individual CRW v3.1 writer bundles carry a versioned
`historical_context.reference_climatology` warrant with these reference and
derivation years, daily interpolation method, source-body hash and methodology
link. It excludes inference of a modern-normal anomaly, ENSO classification,
absolute SST, record or ecological impact from the anomaly alone. Primary ERDDAP
and native NetCDF events share that product meaning while retaining their own
source receipts. Unqualified products get no warrant. The writer boundary rejects
altered, partial or unsupported warrants before calling a model. This supplies
evidence, not an instruction to repeat all of it in every tweet.

Graphics reconstruct the **entire** retained bundle with an explicit adapter:
`p31-crw-erddap-1` preserves the original snapshot without that context;
`p31-crw-erddap-2` requires the current context and product label. Presence of the
context key selects the version; an empty or unknown context fails validation.
No fields are silently removed to make a saved bundle fit. The plotted value,
template version and visual baseline are unchanged, but new evidence changes its
fingerprint. This compatibility permits readback, not reuse of stale checks or
approvals: current policy, renderer hashes, exact draft identity and joint review
are still required. Native NetCDF graphics remain unsupported.

The figure includes the baseline, sample count and date at a readable size.
Its alt text retains grid bounds, missing-cell counts and separate acquisition
times. Matching earlier source bytes can support the same calculation without
attesting to a later reported HTTP transfer. Neither hashes nor a successfully
rendered chart certify individual pixels, semantic text/graphic agreement or
publication approval. Existing stale-review, revision and approval guards apply.
