# Lane 07 — Plan A Lane C: Dashboard Source-Health View

**Branch:** `plan-a/dashboard-health-view`
**Plan-of-record:** `docs/PLAN_A.md` (in-repo)
**Scope:** Plan A Phase 5 only — UI route only
**Estimated time:** 1-2 hours CC, single PR

## Why this lane exists

Plan A Phase 1 (PR #99) added a working `/api/source-health` endpoint at
[/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/api/source-health/route.js](/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/api/source-health/route.js)
that aggregates `bot_state.run_history` into a per-source health rollup.

What's missing: a UI surface that consumes it. Today Andrew has to `gh gist view` + jq queries to know which sources are degraded. The whole point of Plan A's observability work is **at-a-glance** source health.

Lane C builds the dashboard view. Pure UI work — API contract is already defined and stable on main.

## What ships from Phase 1 (already on main)

The API at `/api/source-health` returns this shape (newest-worst-first sort):

```json
{
  "sources": [
    {
      "source": "ocean_sst",
      "runs": 8,
      "successes": 0,
      "failures": 8,
      "degraded": 0,
      "partial_failures": 0,
      "skipped": 0,
      "total_observed": 0,
      "total_promoted": 0,
      "total_drafted": 0,
      "last_error": "Ocean SST fetch failed: Expecting value: line 1 column 1 (char 0)",
      "last_error_at": "2026-05-14T21:12:40Z",
      "last_run_at": "2026-05-14T21:12:40Z",
      "last_run_status": "failed",
      "success_rate": 0,
      "health": "unhealthy"
    },
    ...
  ],
  "stats": {
    "runs_analyzed": 20,
    "unhealthy_count": 1,
    "degraded_count": 1,
    "healthy_count": 7,
    "idle_count": 5
  }
}
```

Health buckets: `unhealthy` | `degraded` | `healthy` | `idle`. Sources are pre-sorted worst-first by health bucket, then alphabetical within bucket.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) — Plan A doc, Phase 5 section
2. [/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/api/source-health/route.js](/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/api/source-health/route.js) — API contract you're consuming
3. [/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/page.js](/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/page.js) — existing dashboard root; copy the `"use client"` pattern, `timeAgo` helper, badge styles
4. [/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/layout.js](/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/layout.js) — global layout (header, nav, theme)
5. [/Users/andrewpuschel/Documents/Claude/theheat/dashboard/tests/](/Users/andrewpuschel/Documents/Claude/theheat/dashboard/tests/) — existing dashboard tests for naming + structure conventions

## What to build

### Files

- `dashboard/app/health/page.js` (new) — the source-health route. Client component (`"use client"`).
- `dashboard/app/health/page.test.js` (new) — Jest/RTL coverage for the page.
- Possibly a small shared component file if the badge / health-pill rendering is extracted: `dashboard/components/HealthBadge.js`. Optional — inline is fine if the component is small.
- Add a nav link (or tab) to `/health` from the main dashboard `page.js` or `layout.js` so Andrew can navigate to it without typing the URL.

### Page behavior

- Fetch `/api/source-health` on mount (and on a 30-second polling interval — match the existing dashboard polling cadence if `page.js` already polls; otherwise just on-mount + manual refresh button).
- Render a header card showing the stats: total unhealthy / degraded / healthy / idle counts. Big numbers, colored to match the health-bucket convention.
- Render the sources as a list/grid sorted worst-first (the API already sorts; preserve that order — don't re-sort client-side).
- Each source row shows:
  - **Source name** (e.g. `ocean_sst`, `open_meteo_extreme_signals`)
  - **Health pill** (unhealthy = red, degraded = amber, healthy = green, idle = neutral grey)
  - **Success rate** (e.g. "0%", "100%", "—" when null)
  - **Last run** as relative time (e.g. "8m ago") — reuse `timeAgo()` from existing `page.js`
  - **Last run status** (success / degraded / failed / partial_failure / skipped)
  - **Last error** (truncated to ~120 chars, with full text on hover/click)
  - **Counter pills**: success / degraded / failed / skipped counts across the runs analyzed
- Empty state: if API returns `sources: []` (or before Phase 1 runs land any data), show "Source health data not yet available. The next alerts cron will populate this view."

### Style

- Match the existing dark terminal aesthetic from `page.js` and `layout.js`.
- Health colors should be the same palette as the existing `badge` classes in `page.js`:
  - red/failure → unhealthy
  - amber/warning → degraded
  - green/success → healthy
  - grey/neutral → idle
- Don't introduce new design tokens. Reuse what exists.

### Auth

The existing dashboard requires auth (`requireDashboardAuth` is called inside the API route). The new page lives behind the same auth wall — no additional auth wiring needed; if the user can hit `/` they can hit `/health`.

### Tests

Add Jest/RTL tests covering:
- Renders all sources from API mock
- Sorts worst-first (verify by reading first row's source name)
- Health pill class is correct for each bucket
- `last_error` is truncated when long
- Empty state renders when `sources: []`
- Stats card renders the four counts correctly
- API error response renders an inline error message (not a crash)

Aim for ~6-10 tests. Mirror the test file structure already used in `dashboard/tests/`.

## Acceptance

- `cd dashboard && npm test` passes (existing 16 tests + ~6-10 new = ~22-26 passing).
- `cd dashboard && npm run build` passes.
- Run dev server locally: `cd dashboard && npm run dev`, visit `http://localhost:3000/health`, see all sources rendered correctly with the current `/api/source-health` data (you can mock this by running `npm run dev` against a live state.json, OR use the test fixtures).
- After deploy to Vercel: visit the deployed `/health` route; confirm sources render with current production data; confirm `ocean_sst` shows unhealthy (red); confirm at least some healthy sources show green.

## Constraints

- **Don't touch the API route.** The contract is fixed; if you find a bug there, fix it in a separate PR.
- **Don't change other dashboard routes.** Adding a nav link to existing routes is fine, but don't refactor `page.js`.
- **No new dependencies.** Use what's already in `dashboard/package.json`.
- **Subagent model floor:** Sonnet 4.6 default, never Haiku.
- **Verify the wire:** after deploy, click the deployed URL yourself, confirm data renders correctly. Don't trust local-dev-only confirmation.

## Branch / PR sequence

1. Branch `plan-a/dashboard-health-view` from `main`.
2. Implement + tests + lint clean.
3. PR → CI green → Claude merges per the standing rule (Andrew never merges).
4. After merge, verify on Vercel deploy.

Done. ~1-2 hours CC end-to-end.
