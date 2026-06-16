import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"

import {
  SourceHealthContent,
  fetchSourceHealth,
  truncateError,
} from "./page.js"

const h = React.createElement
const NOW = new Date("2026-05-14T21:30:00Z").getTime()
const LONG_ERROR = `Ocean SST fetch failed: ${"provider returned empty JSON ".repeat(8)}`

const SOURCES = [
  {
    source: "ocean_sst",
    runs: 8,
    successes: 0,
    failures: 8,
    degraded: 0,
    partial_failures: 0,
    skipped: 0,
    total_observed: 0,
    total_promoted: 0,
    total_drafted: 0,
    last_error: LONG_ERROR,
    last_error_at: "2026-05-14T21:12:40Z",
    last_run_at: "2026-05-14T21:12:40Z",
    last_run_status: "failed",
    success_rate: 0,
    health: "unhealthy",
    troubleshooting_log: [
      {
        at: "2026-05-14T21:12:40Z",
        status: "failed",
        diagnostic: LONG_ERROR,
        error_class: "upstream",
        duration_ms: 80800,
        observed: 0,
        promoted: 0,
        triaged_in: 0,
        triaged_out: 0,
        writer_attempted: 0,
        drafted: 0,
      },
    ],
  },
  {
    source: "open_meteo_extreme_signals",
    runs: 8,
    successes: 6,
    failures: 0,
    degraded: 2,
    partial_failures: 0,
    skipped: 0,
    total_observed: 11907,
    total_promoted: 4,
    total_drafted: 0,
    last_error: "provider:ghcn diff_dates_missing:4",
    last_error_at: "2026-05-14T21:12:40Z",
    last_run_at: "2026-05-14T21:12:40Z",
    last_run_status: "degraded",
    success_rate: 0.75,
    health: "degraded",
  },
  {
    source: "nws_alerts",
    runs: 8,
    successes: 8,
    failures: 0,
    degraded: 0,
    partial_failures: 0,
    skipped: 0,
    total_observed: 48,
    total_promoted: 2,
    total_drafted: 1,
    last_error: null,
    last_error_at: null,
    last_run_at: "2026-05-14T21:12:40Z",
    last_run_status: "success",
    success_rate: 1,
    health: "healthy",
  },
  {
    source: "drought",
    runs: 2,
    successes: 0,
    failures: 0,
    degraded: 0,
    partial_failures: 0,
    skipped: 2,
    total_observed: 0,
    total_promoted: 0,
    total_drafted: 0,
    last_error: null,
    last_error_at: null,
    last_run_at: "2026-05-14T21:12:40Z",
    last_run_status: "skipped",
    success_rate: null,
    health: "idle",
  },
]

const STATS = {
  runs_analyzed: 20,
  unhealthy_count: 1,
  degraded_count: 1,
  healthy_count: 1,
  idle_count: 1,
}

function render(props = {}) {
  return renderToStaticMarkup(
    h(SourceHealthContent, {
      sources: SOURCES,
      stats: STATS,
      loading: false,
      now: NOW,
      ...props,
    })
  )
}

test("health page renders all sources from the API payload", () => {
  const markup = render()

  assert.match(markup, /ocean_sst/)
  assert.match(markup, /open_meteo_extreme_signals/)
  assert.match(markup, /nws_alerts/)
  assert.match(markup, /drought/)
})

test("health page preserves the API's worst-first source order", () => {
  const markup = render()

  const oceanIndex = markup.indexOf("ocean_sst")
  const openMeteoIndex = markup.indexOf("open_meteo_extreme_signals")
  const nwsIndex = markup.indexOf("nws_alerts")
  const droughtIndex = markup.indexOf("drought")

  assert.ok(oceanIndex > -1)
  assert.ok(oceanIndex < openMeteoIndex)
  assert.ok(openMeteoIndex < nwsIndex)
  assert.ok(nwsIndex < droughtIndex)
})

test("health page maps each bucket to the correct pill class", () => {
  const markup = render()

  assert.match(markup, /class="health-pill unhealthy"/)
  assert.match(markup, /class="health-pill degraded"/)
  assert.match(markup, /class="health-pill healthy"/)
  assert.match(markup, /class="health-pill idle"/)
})

test("health page truncates long last_error text while keeping the full title", () => {
  const markup = render()
  const clipped = truncateError(LONG_ERROR)

  assert.ok(markup.includes(`>${clipped}</strong>`))
  assert.ok(markup.includes(`title="${LONG_ERROR}"`))
  assert.ok(!markup.includes(`>${LONG_ERROR}</strong>`))
})

test("health page renders troubleshooting log details for failing sources", () => {
  const markup = render()

  assert.match(markup, /Troubleshooting log/)
  assert.match(markup, /failed/)
  assert.match(markup, /upstream/)
  assert.match(markup, /observed 0/)
})

test("health page renders empty state when no sources are available", () => {
  const markup = render({ sources: [], stats: { ...STATS, runs_analyzed: 0 } })

  assert.match(
    markup,
    /Source health data not yet available\. The next alerts cron will populate this view\./
  )
})

test("health page stats card renders the four health counts", () => {
  const markup = render()

  assert.match(markup, /<div class="stat-card unhealthy"><div class="stat-value">1<\/div><div class="stat-label">unhealthy<\/div><\/div>/)
  assert.match(markup, /<div class="stat-card degraded"><div class="stat-value">1<\/div><div class="stat-label">degraded<\/div><\/div>/)
  assert.match(markup, /<div class="stat-card healthy"><div class="stat-value">1<\/div><div class="stat-label">healthy<\/div><\/div>/)
  assert.match(markup, /<div class="stat-card idle"><div class="stat-value">1<\/div><div class="stat-label">idle<\/div><\/div>/)
})

test("health page renders inline API errors instead of crashing", () => {
  const markup = render({ error: "Gist state unavailable" })

  assert.match(markup, /role="alert"/)
  assert.match(markup, /Source health unavailable: Gist state unavailable/)
})

test("source health fetch helper preserves API error responses", async () => {
  await assert.rejects(
    () =>
      fetchSourceHealth(async () => ({
        ok: false,
        status: 500,
        async json() {
          return { sources: [], stats: null, error: "readStateStore failed" }
        },
      })),
    /readStateStore failed/
  )
})
