# THIRTY-LOOP — Progress tracker

> State lives HERE and only here. Each step's PR updates its own row (status → DONE, PR #, note) in the same PR.
> Statuses: `TODO` · `IN-PROGRESS` · `DONE` · `DONE(<qualifier>)` · `BLOCKED(<reason>)` · `AWAITING-ANDREW`.
> Pick: first TODO whose deps are all DONE (any qualifier). See plan §2 for the full protocol.

| Step | Item | Title | Deps | Status | PR | Note |
|---|---|---|---|---|---|---|
| S-01 | #30a | Dead `drafted` plumbing + per-source credit | — | DONE | #222 | Runner returns ignored; drain credits saved drafts per source. |
| S-02 | #30b | pytest config, README, PIPELINE glossary, critic passthrough, action versions | — | DONE | #223 | Local pytest defaults, README, current glossary, critic env, and action versions synced. |
| S-03 | #27 | Dashboard truth fixes | — | DONE | #224 | Dashboard counts, state-read errors, data age, Hot 10 staleness, and funnel label truth fixed. |
| S-04 | #29 | Sentinel 403 classification (PY+JS) | — | DONE | #225 | Earthdata credential 403s classify ours in Python and dashboard; generic gov 403 stays external. |
| S-05 | #13 | error_class telemetry + liveness + failure alarm | S-04 | DONE | #226 | Source error_class telemetry, stale alerts-lane sentinel, hourly cadence, and scheduled-run failure issue alarm added. |
| S-06 | #14 | Sentinel stale-success / zero-yield watch | S-05 | DONE | #228 | Unknown-labeled yield-watch advisory issue now tracks green zero-observed sources. |
| S-07 | #1a | _http.py jitter + shared Session | — | DONE | #229 | Shared pooled Session and jittered retry sleeps added with retry-seam tests updated. |
| S-08 | #1b | Migrate bare requests.get callers | S-07 | DONE | #230 | Safe public data fetches now use fetch_with_retry; GHCN/GPM exemptions documented. |
| S-09 | #1c | WAF-aware 403/429 retry + gpm unify | S-07 | DONE | #231 | Host-scoped WAF retry budget added; GPM per-city fetches now use fetch_with_retry. |
| S-10 | #20 | Conditional requests (ETag) for CSVs | S-08 | DONE | #232 | Static CO2, ONI, sea-ice, and snow feeds now revalidate with process-local ETag/Last-Modified caches. |
| S-11 | #8 | Decompose common.py | S-08 | DONE | #233 | common.py split into focused helper modules with legacy shim exports and sync coverage preserved. |
| S-12 | #4a | gpm chain datapool→s3→opendap + pre-mint | S-09 | DONE | #238 | Datapool now chains through S3 before OPeNDAP; preflight noted external GDACS #234. |
| S-13 | #4b | GDACS GeoRSS fallback + mirror survey | S-09 | DONE | #239 | GeoRSS fallback added; mirror survey records 8 official-source verdicts. |
| S-14 | #3a | assert_freshness rollout | S-06 | DONE | #240 | Freshness guards now cover all 15 planned source parsers. |
| S-16 | #10 | Record-store caps + state pruning | — | DONE | #243 | Durable prune pass, shipped-tweet cap, tier TTL sidecar, and 800 KB state-size warning added. |
| S-15 | #3b | Last-good cache (slow movers) | S-14, S-16 | DONE | #245 | Slow movers now cache compact last-good readings with provenance guards and degraded cache telemetry. |
| S-17 | #12 | Double-post hardening + optimistic lock | — | DONE | #246 | Durable publish ledger, half-post repair, state rev re-merge, and dashboard tweet_id payload added. |
| S-18 | #21 | SQLite backend CI smoke | — | DONE | #247 | CI now runs env-driven SQLite backend smoke over the existing state suite. |
| S-19 | #28 | Dashboard payload trim + visibility polling | S-03 | DONE | #248 | Dashboard state is projected to page-read keys and hidden tabs stop interval polling. |
| S-20 | #7 | DAG concurrency + budgets + breaker (flag) | S-05, S-08, S-11 | DONE | #250 | Dark scheduler added with timeout budgets, breaker skips, locked triage enqueue, and thread-local suppression. |
| S-21 | #23 | Orchestrator test gaps + voice fixtures | — | DONE | #251 | CO-OPS, NIFC, and marine runners covered; six new voice replay bundle fixtures collect. |
| S-22 | #2 | Multi-draft best-of + critic REVISE (flags) | S-21 | DONE | #252 | Dark writer sampling, slate critic selection, one-pass REVISE, and draft-cap passthrough added. |
| S-23 | #16 | Coral reef-system angle library | S-21 | TODO | | |
| S-24 | #17 | Record margin-percentile fact | S-21 | TODO | | |
| S-25 | #15 | AQ ground-station corroboration (OpenAQ) | S-08 | TODO | | |
| S-26 | #19 | air_quality chunk pacing | S-09 | TODO | | |
| S-27 | #6 | Synthesis: SST×coral + global FDH | S-21 | TODO | | |
| S-28 | #24 | Reganom readiness runbook (NO flip) | — | TODO | | |
| S-29 | #26 | Hot 10 audience-unit fix | — | TODO | | |
| S-30 | #25 | Inter-tweet spacing guard | — | TODO | | |
| S-31 | #22 | Cyclone advisory source links | S-21 | TODO | | |
| S-32 | #18 | Engagement-window scheduling (flag) | S-30 | TODO | | |
| S-33 | #9 | Hot 10 image card + alt text (flag) | S-29 | TODO | | |
| S-34 | #5 | Engagement metrics ingestion (flag) | S-17 | TODO | | |
| S-35 | #11 | Dashboard component extraction | S-19 | TODO | | |

## Session log

| Date | Session | Steps shipped | Notes |
|---|---|---|---|
| | | | |
