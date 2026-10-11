import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ForecastEvidence } from "../app/components/ForecastEvidence.js"
import { forecastDraft, savedWindow } from "./fixtures/forecast-evidence.js"

const render = draft => renderToStaticMarkup(React.createElement(ForecastEvidence, { draft }))

test("actual component renders forecast scope, saved timing and all 120 unchanged samples", () => {
  const draft = forecastDraft(), html = render(draft)
  for (const text of ["Forecast behind this draft", "Model forecast", "Asia/Kolkata", "2026-01-15", "CAMS via Open-Meteo",
    "Requested place", "Sampled grid point", "10, 75.5", "10.12, 75.24", "UTC interval end (exclusive)",
    "2026-01-14T18:30:00Z", "2026-01-15T18:30:00Z", "2026-01-15T00:01:02Z", "not station measurements",
    "does not identify the exact model", "do not establish an event-specific cause", "source checks still apply"])
    assert.ok(html.includes(text), text)
  assert.equal((html.match(/<details/g) || []).length, 6)
  assert.equal((html.match(/<table/g) || []).length, 5)
  assert.equal((html.match(/<th scope="row">/g) || []).length, 120)
  for (const entry of Object.values(savedWindow(draft).series)) for (const value of entry.values)
    assert.ok(html.includes(`<td>${value}</td>`))
  assert.equal((html.match(/href=/g) || []).length, 1)
  assert.ok(html.includes('href="https://open-meteo.com/en/docs/air-quality-api"'))
  assert.ok(!html.includes("<button") && !html.includes("<input"))
})

test("source-like labels are escaped and never become arbitrary links", () => {
  const draft = forecastDraft()
  savedWindow(draft).requested_location.city = '<img src=x onerror="alert(1)"> https://invalid.example/'
  savedWindow(draft).requested_location.country = "L".repeat(160)
  const html = render(draft)
  assert.ok(html.includes("&lt;img"))
  assert.ok(!html.includes("<img"))
  assert.ok(!html.includes('href="https://invalid.example/"'))
  assert.ok(html.includes("L".repeat(160)))
})

test("legitimate gaps and unusable or absent variables keep distinct labels", () => {
  const draft = forecastDraft(), window = savedWindow(draft)
  window.series.pm2_5.status = "incomplete"; window.series.pm2_5.values[3] = null
  window.series.pm10 = { status: "missing", unit: "μg/m³", values: null }
  window.series.dust = { status: "invalid", unit: "μg/m³", values: null }
  const html = render(draft)
  assert.ok(html.includes("23/24 samples · incomplete"))
  assert.ok(html.includes("<td>Missing</td>"))
  assert.ok(html.includes("PM10 · Not supplied"))
  assert.ok(html.includes("Dust · Unusable source values"))
  assert.equal((html.match(/<th scope="row">/g) || []).length, 72)
})

test("missing and malformed input explain the next review step; other hazards add no panel", () => {
  const draft = forecastDraft()
  savedWindow(draft).hours = []
  const malformed = render(draft)
  assert.ok(malformed.includes("cannot be displayed"))
  assert.ok(malformed.includes("Check the original source"))
  assert.ok(!malformed.includes("<table"))
  delete draft.review_context.two_bot.bundle.raw_signal_dump.forecast_window
  assert.ok(render(draft).includes("hourly forecast was not saved"))
  assert.equal(render(forecastDraft("rainfall")), "")
})
