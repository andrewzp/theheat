# P09 GPM access failure: evidence, not a recovery claim

The saved production ingestion run `34329327005` used `10832af` on September 9. Its configured GPM source was `datapool`. Reading that existing workflow log, without rerunning the collector, established the attempted fallback sequence:

1. The GES DISC HTTPS daily-grid download returned HTTP 401.
2. The GES DISC temporary S3-credential endpoint did not yield parseable JSON. The existing log does not establish its HTTP status, content type or redirect destination; do not infer those details.
3. The legacy GPM OPeNDAP point request also returned HTTP 401 and stopped after the first authentication failure.

This is more specific than a generic missing-data status. It does **not** determine whether the production Earthdata token is expired, invalid, missing a required authorization, or encountering a changed access flow. A configured credential-presence boolean is not proof of usable access. The credential itself was not retrieved or printed, and no login, credential rotation or additional source request was performed for this diagnosis.

The source remains operationally unresolved. Recover it with a bounded, authorized access check against the actual configured production credential and documented NASA endpoint requirements, preserve sanitized status/host/content-type diagnostics, then demonstrate a valid current product read. Do not repeatedly change dates or buy model-powered diagnosis for the same 401. An independent model fallback must remain explicitly modeled and pass its own validation; its availability does not establish recovered satellite observations.

The actual-tweet Barrow satellite/gauge discrepancy remains separate. Access recovery alone cannot reproduce the original granules, reconcile their integration window/footprint, or establish a cause for the historical difference. Keep that claim on hold pending the assessed scientific reconciliation.
