import assert from "node:assert/strict"
import test from "node:test"
import { forecastEvidenceForDisplay as display } from "../lib/forecast-evidence.js"
import { forecastDraft, savedWindow } from "./fixtures/forecast-evidence.js"
import { draftReviewControls } from "../lib/draft-review-ui.js"

test("both primary AQ kinds retain exact values, saved times and separate grid scope", () => {
  for (const kind of ["air_quality_hazard", "dust_event"]) {
    const draft = forecastDraft(kind), original = structuredClone(draft), view = display(draft)
    assert.equal(view.status, "present")
    assert.equal(view.timezone, "Asia/Kolkata")
    assert.equal(view.validStart, "2026-01-14T18:30:00Z")
    assert.equal(view.requestedAt, "2026-01-15T00:01:00Z")
    assert.deepEqual(view.grid, [10, 75.5])
    assert.equal(view.location.lat, 10.12)
    for (const series of view.series) {
      assert.equal(series.count, 24)
      assert.deepEqual(series.rows.map(row => row.value), savedWindow(draft).series[series.key].values)
      assert.deepEqual(series.rows.map(row => row.hour), savedWindow(draft).hours.map(hour => hour.slice(11)))
    }
    view.grid[0] = 90; view.location.city = "Changed"; view.series[0].rows[0].value = 500
    assert.deepEqual(draft, original)
  }
})

test("missing inputs and unsupported hazards stay distinct", () => {
  assert.equal(display(null).status, "unsupported")
  assert.equal(display(forecastDraft("rainfall")).status, "unsupported")
  const draft = forecastDraft()
  delete draft.review_context.two_bot.bundle.raw_signal_dump.forecast_window
  assert.equal(display(draft).status, "missing")
  draft.review_context.two_bot.bundle.raw_signal_dump.forecast_window = false
  assert.equal(display(draft).status, "unreadable")
})

test("null slots, absent variables and invalid source values are not zero", () => {
  const draft = forecastDraft(), window = savedWindow(draft)
  window.series.pm2_5.status = "incomplete"; window.series.pm2_5.values[4] = null
  window.series.pm10 = { status: "missing", unit: "μg/m³", values: null }
  window.series.dust = { status: "invalid", unit: "μg/m³", values: null }
  const view = display(draft)
  assert.equal(view.status, "present")
  assert.equal(view.series[0].count, 23)
  assert.equal(view.series[0].rows[4].value, null)
  assert.equal(view.series[0].rows[0].value, 0)
  assert.equal(view.series[1].status, "missing")
  assert.equal(view.series[1].rows, null)
  assert.equal(view.series[2].status, "invalid")
})

const corruptions = {
  schema: w => { w.schema_version = true }, product: w => { w.source_product = "other" },
  source: w => { w.source_url = "javascript:alert(1)" }, evidence: w => { w.evidence_type = "station" },
  domain: w => { w.domain_selection = "global" }, method: w => { w.method = "Observed mean" },
  date: w => { w.date = "2026-02-30" }, timezone: w => { w.timezone = "Invented/Zone" },
  offsetInsteadOfZone: w => { w.timezone = "+05:30" },
  offset: w => { w.utc_offset_seconds = "19800" },
  invalidUtcDate: w => { w.valid_start = "2026-02-30T00:00:00Z" },
  endBeforeStart: w => { w.valid_end = "2026-01-01T00:00:00Z" },
  missingUtc: w => { delete w.valid_start },
  nonUtc: w => { w.requested_at = "2026-01-15T00:01:00+05:30" },
  invalidHour: w => { w.requested_at = "2026-01-15T24:00:00Z" },
  retrievalBeforeRequest: w => { w.retrieved_at = "2026-01-14T00:00:00Z" },
  missingHours: w => { w.hours.pop() }, duplicateHour: w => { w.hours[1] = w.hours[0] },
  reorderedHour: w => { w.hours.reverse() }, sparseHours: w => { delete w.hours[1] },
  badGrid: w => { w.grid_location[0] = 91 }, missingGrid: w => { w.grid_location = null },
  badRequested: w => { w.requested_location.lon = true },
  cityTooLong: w => { w.requested_location.city = "x".repeat(161) },
  emptyCountry: w => { w.requested_location.country = " " },
  missingVariable: w => { delete w.series.pm10 },
  extraVariable: w => { w.series.unexpected = w.series.pm10 },
  unknownUnit: w => { w.series.pm10.unit = "µg/m³" },
  unknownStatus: w => { w.series.pm10.status = "okay" },
  statusMismatch: w => { w.series.pm10.status = "incomplete" },
  missingWithValues: w => { w.series.pm10.status = "missing" },
  shortSeries: w => { w.series.pm10.values.pop() },
  longSeries: w => { w.series.pm10.values.push(0) },
  sparseSeries: w => { delete w.series.pm10.values[0] },
  nullInComplete: w => { w.series.pm10.values[0] = null },
  negative: w => { w.series.pm10.values[0] = -1 }, stringNumber: w => { w.series.pm10.values[0] = "1" },
  boolNumber: w => { w.series.pm10.values[0] = true }, nan: w => { w.series.pm10.values[0] = NaN },
  infinite: w => { w.series.pm10.values[0] = Infinity },
  oversized: w => { w.extra = "x".repeat(32768) }, utf8Oversized: w => { w.extra = "界".repeat(12000) },
  cyclic: w => { w.extra = w }, nonJson: w => { w.extra = () => true },
  hugeSparseArray: w => { w.extra = new Array(1_000_000) },
}
for (const [name, mutate] of Object.entries(corruptions)) test(`unreadable saved shape: ${name}`, () => {
  const draft = forecastDraft(); mutate(savedWindow(draft))
  assert.equal(display(draft).status, "unreadable")
})

test("unrelated event inputs cannot be presented as this draft's forecast", () => {
  for (const target of ["draft", "bundle", "raw"]) {
    const draft = forecastDraft(), bundle = draft.review_context.two_bot.bundle
    const object = target === "draft" ? draft : target === "bundle" ? bundle : bundle.raw_signal_dump
    object.event_id = "another-event"
    assert.equal(display(draft).status, "unreadable")
  }
})

test("display does not verify hashes, decide freshness or modify approval controls", () => {
  const draft = forecastDraft(), before = draftReviewControls(draft)
  savedWindow(draft).selected_record_sha256 = "not-proof-of-source-truth"
  assert.equal(display(draft).status, "present") // Historical date remains historical.
  assert.deepEqual(draftReviewControls(draft), before)
  assert.equal(before.canApprove, false)
  assert.equal(before.canSchedule, false)
})
