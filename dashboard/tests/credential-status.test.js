import test from "node:test"
import assert from "node:assert/strict"

import {
  CRED_WARN_DAYS,
  CRED_CRIT_DAYS,
  daysUntil,
  badgeClassForDays,
  credentialRows,
} from "../lib/credential-status.js"

const NOW = Date.parse("2026-06-23T15:00:00Z")

test("daysUntil returns whole days remaining", () => {
  assert.equal(daysUntil("2026-08-22T15:18:07Z", NOW), 60)
  assert.equal(daysUntil("2026-06-24T15:00:00Z", NOW), 1)
})

test("daysUntil is negative once expired and null when unparseable", () => {
  assert.equal(daysUntil("2026-06-20T15:00:00Z", NOW), -3)
  assert.equal(daysUntil("not-a-date", NOW), null)
  assert.equal(daysUntil(undefined, NOW), null)
})

test("badgeClassForDays maps onto the existing palette at the thresholds", () => {
  assert.equal(badgeClassForDays(60), "success") // green, comfortable
  assert.equal(badgeClassForDays(CRED_WARN_DAYS + 1), "success")
  assert.equal(badgeClassForDays(CRED_WARN_DAYS), "running") // amber warn boundary
  assert.equal(badgeClassForDays(CRED_CRIT_DAYS + 1), "running")
  assert.equal(badgeClassForDays(CRED_CRIT_DAYS), "failure") // red crit boundary
  assert.equal(badgeClassForDays(-5), "failure") // expired
  assert.equal(badgeClassForDays(null), "neutral") // unknown
})

test("credentialRows projects, colors, and sorts soonest-to-expire first", () => {
  const rows = credentialRows(
    {
      EARTHDATA_TOKEN: { label: "NASA Earthdata", expires_at: "2026-08-22T15:18:07Z", source: "jwt" },
      SOON_TOKEN: { label: "Soon", expires_at: "2026-06-25T15:00:00Z", source: "jwt" },
    },
    NOW,
  )
  assert.deepEqual(
    rows.map((r) => r.name),
    ["SOON_TOKEN", "EARTHDATA_TOKEN"], // 2 days left sorts before 60
  )
  assert.equal(rows[0].badgeClass, "failure") // SOON_TOKEN: 2d -> red
  assert.equal(rows[1].label, "NASA Earthdata")
  assert.equal(rows[1].daysLeft, 60)
  assert.equal(rows[1].badgeClass, "success")
})

test("credentialRows on empty/missing input is an empty list, never a crash", () => {
  assert.deepEqual(credentialRows({}, NOW), [])
  assert.deepEqual(credentialRows(undefined, NOW), [])
})
