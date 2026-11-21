# Saved GHCN acquisition outcomes

The Sources readout distinguishes an unavailable daily-difference payload from
an archive that was parsed but yielded no usable station-days. A current source
run can retain `pipeline_metrics.diff_fetch` (or `ghcn_pipeline_metrics.diff_fetch`
for a combined collector). It records the existing fetch helper's client calls
and fixed final HTTP/error classes, without response bodies, URLs or exception
text. It adds no requests and changes no retry, timeout, date, QC or comparison
rule. Redirects can add wire requests, so these counts are not a wire-request or
provider-billing total.

`payload_returned` means the helper returned a body; it does not establish that
the body is a valid NOAA archive. The separate `diff_intake` records parsing and
station-day exclusions. A saved HTTP401/403 is a response classification, not a
diagnosis of credentials; HTTP404 does not establish zero weather observations.
An all-unavailable capture shows the actual counts and no returned payload.

The readout checks exact fields, conserved counts, the existing target/probe
bounds, missing-date and payload denominators, and the source run's date and
currency. Malformed, contradictory, older or unobserved captures remain unknown.
Retained-byte replay and custom uninstrumented fetches do not acquire live HTTP
facts. Existing intake records remain readable, and source/check rejection and
alternate-product precedence are preserved. The readout grants no review or
publishing authority and performs no credential or source probe.
