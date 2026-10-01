# NHC public advisory product parsing

NHC's [CurrentStorms feed](https://www.nhc.noaa.gov/CurrentStorms.json) supplies
`publicAdvisory` as an object containing a URL, advisory number, issuance and file
update time. The old parser treated it as a string. That produced an unusable link
and lost the number, even though the source could still report a successful fetch.

The parser now extracts the typed product fields. Existing scalar URL aliases and
top-level advisory numbers remain supported. Forecast-product parsing continues
independently, including when the optional public product is missing or malformed.
This change does not modify historical draft records or publication receipts.

## Metadata and time rules

- A valid nested public `advNum` identifies the selected public product and takes
  precedence over a legacy number. Strings containing digits and an optional letter
  suffix are accepted. Legacy non-Boolean integers are also supported. Containers,
  booleans, floats and malformed values are not converted into advisory numbers.
- Storm measurement time comes from a qualified top-level issue field. A public
  product's `issuance` is a fallback when no qualified top-level issue time exists.
  `fileUpdateTime` and forecast-product dates are never substituted for validity.
- Issue instants require a valid ISO date and time with an explicit UTC offset or
  `Z`. A bare date or unspecified timezone cannot become an issue instant. If neither
  source supplies one, the row is withheld before optional text requests, preventing
  downstream date-only defaults from presenting it as current.
- The existing source freshness guard still applies to the returned issue times.
  This repair does not replace the broader source and observation qualification work.

The storm issue time and public product metadata are distinct source fields. An
advisory link or number does not itself establish the time, location or intensity
of a completed landfall.

## Optional product requests

Official NHC HTTP/HTTPS URLs and relative paths are accepted. Other hosts or schemes,
credentials, malformed authorities, unexpected ports, control characters, malformed
Unicode, container representations and oversized values are rejected before a
request. The same validation applies to forecast-product URLs.

A missing or invalid public product leaves otherwise qualified storm and forecast
data available. Optional text fetches retain the existing timeout and retry bounds.
No new LLM calls, model selection, writer sampling or revision loop is introduced.

The adapter is now part of editorial policy identity. Its source changes invalidate
obsolete policy-bound checks and approvals. The dashboard manifest must be deployed
manually after merging; a Git push alone does not deploy it.

## Verification and limits

Synthetic regressions cover the nested product shape, legacy fields, exact fetched
URLs, metadata reaching the normal evidence and review context, forecast retention,
category deduplication, malformed types/URLs, time precedence and optional failures.
A bounded read of the official feed also verified exact URL/number/time retention
for three current nested public products. Secondary product fetches and model calls
were disabled in that qualification probe; it verifies feed shape, not scientific
truth or completed advisory-text retrieval in the production workflow.

Three synthetic source sentences expose a separate legacy detector problem:
forecast wording, negation and another historical storm can be promoted into a
landfall candidate. End-to-end tests verify that the existing dated-source-warrant
gate rejects the corresponding completed-landfall claim before paid safety or
factual checks. This repair does not invent such a warrant from an event label or
URL. Qualified upstream landfall classification and intensity remain separate work;
no historical false-post conclusion is drawn from these synthetic cases.

Publishing stays paused. Successful tests and parsing do not establish better copy,
global coverage, provider billing totals or measured operating savings.
