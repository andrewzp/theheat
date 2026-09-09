# P04: canonical location identity

Status: implemented locally in the isolated `codex/p04-canonical-places` worktree. No live data calls, baseline rebuild, production state edits, publishing or deployment were performed.

## Contract and coverage

This reuses PR #346's location-collision patch (`c6bbb7c`, carried with attribution as `d502dc0`) and extends it beyond the world-cache-only `city|country` approach.

`data/place_registry.json` assigns persistent `pl...` IDs to 633 places represented by the original 638 watchlist rows. Every original row remains in `data/cities.csv` and in registry aliases. Barcelona, Hyderabad and Valencia pairs remain distinct. Amsterdam, Brazzaville, Dubai, Hong Kong and Kinshasa aliases each share one intentional place. The first preexisting point is the explicitly documented v1 active sampling choice; alternate coordinates/elevations are retained and never treated as interchangeable baselines. Hong Kong is a separate coverage territory. Administrative codes not independently qualified remain null. Country-label codes come from a checked-in public-domain IANA table plus explicit project aliases; no runtime geocoding dependency is introduced.

A place ID is separate from `sampling_point_id`, which fingerprints exact requested coordinates. Unknown unregistered points get a coordinate-specific identity and require coordinates. Registered coordinate changes must be deliberate registry revisions; they cannot inherit the prior point's baseline. Source-native GHCN station IDs remain instrument IDs, including absolute-extreme events.

Both direct and cached Open-Meteo paths, world warming/batch maps, absolute/wet-bulb/monthly/all-time/anomaly IDs, record streaks, AQ IDs and tier state, Hot10 normals/movement/streaks, GPM point/history keys, country aggregation/caps, draft city/date/cooldown gates and editorial memory use the shared identity. GPM primary/witness events share event identity, while satellite/model history keys remain product-specific. New bundle identity travels inside evidence, so P02 reviews become stale if that evidence changes.

## Migration safety

`src/data/place_migration.py` is pure and idempotent. Every world-cache row lacking consistent place/point/product provenance is retained verbatim in `_meta.identity_quarantine`. This includes raw-name and PR #346 composite-name caches. Neither current inventory uniqueness nor a matching city display name proves the original sample footprint or provenance. Such rows cannot participate in record evaluation. Normal bounded archive warming recomputes eligible entries; the source reports degraded while quarantined migration history coincides with incomplete active cache coverage. The source note and details show quarantine count. Counts exclude quarantine and retired points. Merge/write performs the same validation, so a fresh remote read cannot resurrect a legacy key as eligible.

`scripts/migrate_place_identity.py INPUT [--output NEW_LOCAL_FILE]` reports counts and optionally creates a new local copy. It never reads or writes production and refuses to overwrite input or an existing output. Keep an export before release; allow only the new version to write the cache during rollout. Do not run old and new cache writers concurrently.

Existing name-only `data/normals.csv` is preserved but excluded from Hot10 comparisons: its rows contain no attributable sampling point. The leaderboard reports degraded when no attributable normals remain. `scripts/build_normals.py` now emits place, point and coordinate fields. **No bulk rebuild has been run.** An explicit qualified maintenance rebuild is required before Hot10 supply resumes. Source/baseline period qualification belongs to P06; metadata alone is not a scientific certificate.

Existing legacy streak/tier/precip history entries remain in their current maps; new identities do not use them as seeds. No new top-level state key is introduced. `Hot10Snapshot.place_ids` is an additive nested field and is preserved by normal JSON storage. No published text, original event ID, receipt or unknown publication outcome is rewritten. Retained legacy publication evidence is checked for unique attribution: proven matches suppress only the covered place; unresolved history puts a new draft in manual review with an explicit reason, rather than declaring both same-name places published.

## Required integration hook with P00b

P00b owns `src/orchestrator/posting.py`. After both branches are integrated, root must import `requires_identity_review` from `src.data.places` and apply its read-only result inside the final automatic-send guard near the approval-policy check:

```python
if mode == "auto" and requires_identity_review(draft):
    draft["post_error"] = "Legacy place evidence requires identity review"
    return "failed"
```

This keeps old pending point-temperature/AQ/Hot10 drafts from automatically shipping name-only scientific evidence. GHCN station-native IDs are exempt. The helper never changes evidence, receipts or unresolved attempts. Manual evidence review remains available. Root must verify both direct-sender and due-draft paths with P00b's combined publication controls before release; the helper alone is not a completed posting integration.

## Validation and limits

Validation: **2,585 Python tests passed; 41 paid voice replays deselected. Ruff and mypy passed (120 source files).** All tests imported this isolated worktree while using the existing dependency environment.

Regression fixtures include the real Barcelona/Hyderabad/Valencia pairs through response, baseline, detector, intern, draft, cooldown and publication dedup; independent AQ tiers and Hot10 baselines; all five intentional alias groups; coordinate revision; invalid coordinates; batch cardinality; country alias coverage; cache quarantine/merge idempotence; preserved old publication receipts; source-specific precipitation histories; and P02 evidence invalidation.

P06 remains necessary: forecasts currently still update provisional historical extrema; provider valid dates/timezones, baseline completeness, archive cutoffs and intervening eligible records need their separate repair. This change does not certify old values, prove that any specific tweet resulted from a location collision, or authorize a public correction. The September 8 published-tweet assessment and its evidence limits remain the baseline.
