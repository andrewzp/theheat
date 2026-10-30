// W06.6: retained regional scans and named rainfall packet holds reach the real Sources payload
// and view. The run history is produced by the real GPM runner and real scan_regions in a
// Python child (invented places, network trapped); the reader never fetches or estimates recall.
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { buildSourceHealthPayload } from "../lib/source-health.js"
import { rainfallReadiness } from "../lib/rainfall-readiness.js"
import { RainfallReadiness } from "../app/components/RainfallReadiness.js"

function produce(mode) {
  const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "tests.remaining_campaign.w06_readiness_child", mode], {
    cwd: new URL("../..", import.meta.url).pathname, encoding: "utf8",
    env: { PATH: process.env.PATH, HOME: "/nonexistent-invented-w06", LC_ALL: "C", TZ: "UTC", PYTHONDONTWRITEBYTECODE: "1" },
  })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout.trim().split("\n").at(-1))
}

test("a held packet and the regional scan appear in the Sources payload with their named holds", () => {
  const state = produce("held")
  const payload = buildSourceHealthPayload(state, { asOf: "2026-10-30T00:00:00Z" })
  const gpm = payload.sources.find(s => s.source === "gpm_imerg").rainfall_readiness
  assert.deepEqual(gpm.packet_holds.rows.map(r => [r.location, r.holds.map(h => h.code)]), [["Ficta",
    ["accumulation_window_missing", "footprint_missing", "evidence_type_unknown", "source_product_missing"]]])
  assert.equal(gpm.scan, null)
  const regional = payload.sources.find(s => s.source === "regional_rainfall").rainfall_readiness
  assert.deepEqual(regional.regions.map(r => [r.region, r.outcome, r.hold, r.revisit_age_days]), [
    ["basin-fx-1", "qualified", null, 3], ["basin-fx-2", "failed", null, 3], ["basin-fx-3", "access_expired", "earthdata_renewal", 2]])
  assert.deepEqual(regional.scan.not_attempted, ["basin-fx-1"])
  assert.equal(regional.recall, null)
  assert.match(regional.scan.scope, /no global recall/)
  const html = renderToStaticMarkup(React.createElement(RainfallReadiness, { source: "gpm_imerg", readiness: gpm }))
  assert.match(html, /Ficta<\/strong>: stopped before paid generation — Accumulation start\/end missing; Grid cell/)
  const scanHtml = renderToStaticMarkup(React.createElement(RainfallReadiness, { source: "regional_rainfall", readiness: regional }))
  assert.match(scanHtml, /basin-fx-3<\/strong>: access expired — hold: earthdata_renewal; last examined 2 day/)
  assert.match(scanHtml, /not attempted within the call\/deadline limit: basin-fx-1/)
})

test("a complete packet and a source without rainfall details add nothing", () => {
  const state = produce("complete")
  const payload = buildSourceHealthPayload(state, { asOf: "2026-10-30T00:00:00Z" })
  assert.equal(payload.sources.find(s => s.source === "gpm_imerg").rainfall_readiness, null)
  assert.equal(rainfallReadiness([{ started_at: "2026-10-29T00:00:00Z", sources: [{ source: "firms", details: { incident: {} } }] }], "firms"), null)
  assert.equal(renderToStaticMarkup(React.createElement(RainfallReadiness, { source: "firms", readiness: null })), "")
})
