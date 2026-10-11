# Local PM2.5 forecast graphics

`pm25_forecast_day` draws 24 retained hourly forecast samples and their daily
sample mean. It makes no weather or model request. Rendering and text/graphic
review remain private, local operations; production attachment and delivery are
not activated by this tool.

The input must be an exact, unextended `air_quality_hazard` StoryBundle with
`model_estimated` evidence and a complete dated `forecast_window`. Both expected
fingerprints must come from independently selected retained inputs: the full
serialized bundle and its full window including `selected_record_sha256`.
These are the existing canonical `fingerprint` values, not file-byte hashes.
Source-window validation and complete bundle reconstruction must pass. Related
signals, station-corroborated bundles, dust events and additional claims are
unsupported; never remove data from a saved draft to make it pass.

```sh
python scripts/build_pm25_graphic_spec.py \
  --bundle /absolute/private/bundle.json \
  --expected-bundle-sha256 RETAINED_BUNDLE_FINGERPRINT \
  --expected-window-sha256 RETAINED_WINDOW_FINGERPRINT \
  --synthetic false --output /absolute/private/spec.json
```

Inputs are bounded finite JSON. The existing 32 KiB source-window and 1 MB
bundle/graphic bounds apply. Output creation is exclusive; earlier review files
are never overwritten. Invented samples must use `--synthetic true` and remain
visibly labeled as synthetic.

Pass the spec to `src.media.evidence_graphic_render.render_preview` with a local
`pdftoppm` path and private output directory. ReportLab remains an optional local
dependency. The existing `scripts/prepare_media_review.py` accepts the unchanged
saved draft, independently selected current identity/policy, spec and all five
rendered assets. Exact source, text, policy, adapter and asset changes invalidate
the previous review. A matching hash is not semantic review or posting approval.
Keep actual forecasts, draft text and review artifacts out of public commits.

The chart uses a zero-anchored concentration axis and straight segments joining
the 24 samples at local hours 00–23. It neither smooths gaps nor extrapolates
past the final sample. There is no hourly safety threshold or health-category
color scale. Displayed concentrations round to one decimal; exact inputs remain
in the bound spec. Long labels or unrenderable scales are refused, never clipped
or made smaller than the existing mobile-readable minimum.

PM2.5 values are instantaneous forecast concentrations, not station measurements
or measured exposure. The city label is a requested location; the chart displays
the separate model grid coordinates. Automatic domain selection leaves the exact
model run and native temporal/spatial resolution unknown. The 24-sample mean is
not independently observed exposure. Attribution names CAMS and Open-Meteo;
see [the source documentation](https://open-meteo.com/en/docs/air-quality-api).

The retained window is a selected source record, not original HTTP response
bytes or independently authenticated acquisition evidence. The image shows its
local date and timezone; alt text includes hourly samples, UTC interval, request
and retrieval times and these scope limits. A historical preview does not assert
current freshness. Existing GHCN and CRW graphics keep their established contracts.
