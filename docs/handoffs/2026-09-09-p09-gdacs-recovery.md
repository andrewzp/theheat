# P09 bounded GDACS parser recovery

## Evidence and cause

The persisted ingestion run `34329327005` on `10832af` reported `GDACS GeoRSS schema drift: GDACS GeoRSS insufficient GeoRSS fields`. One bounded public GET to [the official GDACS RSS feed](https://www.gdacs.org/xml/rss.xml) at 2026-09-09T13:31:15.452114Z returned HTTP 200, `application/xml`, 1,178,766 bytes and 385 items. The response SHA-256 is `174c68ee6624a29da761d93d3590c47f22bc014a1fc63db320129fa17bae6de5`. The original response and retrieval metadata remain private under this worktree's ignored `.gstack/p09-gdacs/` directory.

The unchanged parser reproduced the production failure on those exact bytes. Two Green tropical cyclone items contain an explicit empty `gdacs:country` element; their descriptions say the affected country is unknown. Their event IDs, alert levels, names, valid dates and coordinates are present. The parser required a country before filtering for the requested severity and aborted the entire feed. This was a demonstrated parser assumption, not evidence that GDACS was down or all global coverage was empty.

The capture contains 381 Green, four Orange and zero Red items. Its newest source start date is September 7, which passes the existing three-day freshness check on September 9. The GDACS JSON endpoint was not fetched again during this task; the cause and current state of its original failure remain unverified.

## Change

The GeoRSS parser accepts an explicitly present but empty country only for tropical cyclone items. The retained event keeps its country empty, and its bundle states that the affected country is unknown and must not be inferred from position. Other missing countries remain errors. Every item is still validated before filtering: known alert/type, event identity, parseable source start date, description/name and finite geographic coordinates within bounds are required. Missing alert levels no longer silently become Green.

An empty/non-RSS document, malformed XML, an empty/invalid primary JSON feature collection, a response exceeding the two-million-byte parser bound, or more than 1,000 RSS items cannot masquerade as a valid no-alert result. Schema failures do not trigger unrelated earthquake/cyclone witness calls. Existing network retry policies and call volume are unchanged; the parser byte bound does not replace streaming transport limits.

GeoRSS is now explicitly tagged as the serving leg. A list-compatible result carries validated-item counts, per-level counts, selected-alert counts, unknown-country counts and the primary exception class even when zero events meet the threshold. The runner records this as `degraded` via GeoRSS rather than claiming full JSON-source recovery. A populated, validated feed with zero Red alerts is distinct from an empty or malformed feed.

## P05 readiness

Actual adapter constructors now attach serving `source_product`, `source_url`, `source_event_id` and source provenance. JSON events identify the MAP endpoint; RSS events identify the RSS feed. USGS witnesses keep their USGS event/feed identity; NHC/JTWC witnesses retain their actual advisory source and URL. Missing original URLs remain missing, and legacy hand-constructed events do not acquire invented origin fields. Subtype-witness suppression remains intact, avoiding duplicate stories already handled by their original sources.

The intern carries those fields into the evidence packet. Against the integrated `8ba12ad` strict contract, the four Orange events from the captured feed pass minimum schema/provenance readiness. This is offline evidence-packet validation, not a writer-quality or scientific-correctness certification. No Red alerts existed in this capture; an explicitly engineered Red fixture demonstrates that a source-shaped Green unknown-country cyclone no longer blocks a qualifying event elsewhere in the feed.

## Verification and limits

- 192 focused source, witness, freshness, health and sentinel tests passed with the `8ba12ad` strict-contract module loaded only in an isolated test process. On the standalone branch predating P05, 191 pass and the P05 integration test skips; root integration must run it with the actual current module.
- Focused Ruff, mypy for three changed source files, and diff whitespace checks passed.
- Replaying the single original capture validates all 385 items and selects zero/four/385 at Red/Orange/Green thresholds. The two unknown countries stay unknown. No additional source calls were used for replays.
- Exactly one fresh public request was performed. No models, paid services, posts, corrections, workflow dispatch, production state changes or deployment were performed.

This repairs the demonstrated source failure and its minimum provenance handoff. Existing event-date-based dedup, onset-versus-update chronology, GDACS impact/severity warrant quality and the continuing usefulness of Red-only selection remain separate assessed work. It does not establish the current health of the JSON endpoint or production recovery after rollout.
