import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import CollectionControls from "../app/components/CollectionControls.js"
import { collectionAvailability, createCollectionControl, COLLECTION_STATUS_MAX_AGE_MS } from "../lib/collection-control.js"

const unpaused = { dashboard_generation_pause: false, collection_pause: { status: "not_configured" } }
const paused = { dashboard_generation_pause: true, collection_pause: { status: "configured" } }
function setup(status = unpaused) {
  let now = Date.now()
  const control = createCollectionControl({ clock: () => now })
  control.complete(control.begin(), { status, dashboardReady: true })
  return { control, advance: ms => { now += ms }, now: () => now }
}
function render(observation, triggering = null) {
  return renderToStaticMarkup(React.createElement(CollectionControls, { observation, triggering, onTrigger() {} }))
}

test("all three visible controls explain and block pending, paused, unknown, local and failed observations", () => {
  const cases = [null, ...[paused, {}, { dashboard_generation_pause: "false", collection_pause: { status: "not_configured" } },
    { ...unpaused, collection_pause: { status: "unknown" } }, { ...unpaused, collection_pause: { status: "configured" } }]
    .map(status => setup(status).control.observation())]
  for (const options of [{ localPreview: true }, { error: "unavailable" }, { dashboardReady: false }]) {
    const control = createCollectionControl()
    control.complete(control.begin(), { status: unpaused, dashboardReady: true, ...options })
    cases.push(control.observation())
  }
  for (const observation of cases) {
    const markup = render(observation)
    assert.equal((markup.match(/disabled=""/g) || []).length, 3)
    for (const text of ["Run Both", "Alerts Only", "Leaderboard Only"]) assert.ok(markup.includes(text))
    assert.match(markup, /aria-describedby="collection-availability"/)
    assert.equal(collectionAvailability(observation).allowed, false)
  }
  assert.match(render(setup(paused).control.observation()), /Collection and draft generation are paused/)
})

test("explicit aligned unpaused settings enable controls without claiming provider access or publication", () => {
  const { control } = setup()
  assert.equal((render(control.observation()).match(/disabled=""/g) || []).length, 0)
  assert.match(render(control.observation()), /Provider access remains unverified/)
  assert.equal((render(control.observation(), "both").match(/disabled=""/g) || []).length, 3)
})

test("the click fence expires and rejects unknown/future clocks even if an earlier render was enabled", async () => {
  const { control, advance, now } = setup()
  const calls = []
  const fetcher = async (...args) => { calls.push(args); return Response.json({ ok: true }) }
  assert.equal(collectionAvailability(control.observation(), now()).allowed, true)
  advance(COLLECTION_STATUS_MAX_AGE_MS)
  assert.equal((await control.request("both", { fetcher })).attempted, false)
  assert.equal(collectionAvailability(control.observation(), now()).allowed, false)
  assert.equal(collectionAvailability(control.observation(), NaN).allowed, false)
  assert.equal(collectionAvailability(control.observation(), control.observation().observedAt - 1).allowed, false)
  assert.deepEqual(calls, [])
})

test("refresh invalidates an enabled closure synchronously; older success cannot undo a newer pause or failure", async () => {
  const { control } = setup()
  const savedClick = control.request
  const calls = []
  const fetcher = async (...args) => { calls.push(args); return Response.json({ ok: true }) }
  const old = control.begin()
  const current = control.begin()
  assert.equal((await savedClick("alerts", { fetcher })).attempted, false)
  assert.equal(control.complete(current, { status: paused, dashboardReady: true }), true)
  assert.equal(control.complete(old, { status: unpaused, dashboardReady: true }), false)
  assert.equal((await savedClick("both", { fetcher })).attempted, false)
  const failed = control.begin()
  control.complete(failed, { error: true })
  assert.equal((await savedClick("leaderboard", { fetcher })).attempted, false)
  assert.deepEqual(calls, [])
})

test("one physical request per concurrent click group, exact modes and unchanged server response semantics", async () => {
  const { control } = setup()
  const calls = []
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  let starts = 0, finishes = 0
  const fetcher = async (url, options) => { calls.push({ url, options }); await pending; return Response.json({ ok: true }) }
  const first = control.request("both", { fetcher, onStart: () => starts++, onFinish: () => finishes++ })
  assert.equal((await control.request("alerts", { fetcher })).attempted, false)
  assert.equal(calls.length, 1)
  assert.equal(finishes, 0)
  finish()
  assert.equal((await first).ok, true)
  assert.equal(starts, 1); assert.equal(finishes, 1)
  assert.equal(calls[0].url, "/api/trigger")
  assert.equal(calls[0].options.method, "POST")
  assert.deepEqual(JSON.parse(calls[0].options.body), { mode: "both" })
  assert.equal((await control.request("unsupported", { fetcher })).attempted, false)
  for (const mode of ["alerts", "leaderboard"]) {
    const result = await control.request(mode, { fetcher: async (_url, options) => {
      assert.deepEqual(JSON.parse(options.body), { mode })
      return Response.json({ ok: true })
    } })
    assert.equal(result.ok, true)
  }
})

test("failed transport releases the local busy fence without retrying or inventing success", async () => {
  const { control } = setup()
  let calls = 0, finished = 0
  await assert.rejects(control.request("alerts", { fetcher: async () => { calls++; throw new Error("invented outage") }, onFinish: () => finished++ }), /invented outage/)
  assert.equal(calls, 1); assert.equal(finished, 1)
  const refused = await control.request("both", { fetcher: async () => Response.json({ ok: true }, { status: 503 }) })
  assert.equal(refused.ok, false)
  assert.equal(refused.attempted, true)
})
