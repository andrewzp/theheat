import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import os from "node:os"
import path from "node:path"

import { importFresh } from "./helpers/import-fresh.js"

function gistResponse(state) {
  return {
    ok: true,
    status: 200,
    async json() {
      return {
        files: {
          "state.json": {
            content: JSON.stringify(state),
          },
        },
      }
    },
    async text() {
      return JSON.stringify(state)
    },
  }
}

test("updateDraftStore merges an edited draft into the latest gist state", async () => {
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"

  const initialState = {
    drafts: [
      { id: "draft_1", text: "Original draft", status: "pending", created_at: "2026-04-09T00:00:00Z" },
    ],
    posted_events: ["event_1"],
    run_history: [{ id: "run_1", mode: "alerts", status: "success", sources: [] }],
    errors: [],
    last_hot10: { date: null, cities: [] },
    streaks: {},
    daily_tweet_count: {},
    pending_confirmations: [],
  }
  const latestState = {
    ...initialState,
    drafts: [
      { id: "draft_1", text: "Original draft", status: "pending", created_at: "2026-04-09T00:00:00Z" },
      { id: "draft_2", text: "Fresh bot draft", status: "pending", created_at: "2026-04-09T00:05:00Z" },
    ],
    posted_events: ["event_1", "event_2"],
    run_history: [
      { id: "run_2", mode: "alerts", status: "success", sources: [] },
      { id: "run_1", mode: "alerts", status: "success", sources: [] },
    ],
    memory: {
      ongoing_events: [{ event_id: "storm_1", last_seen: "2026-05-09T00:00:00Z" }],
      used_era_anchors: ["Spider-Man 2002"],
      used_peer_comparisons: [],
      used_framings: [],
      shipped_tweets: [],
    },
    data_source_failures: { ghcn: 2 },
  }

  const fetchCalls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options })
    if (!options.method || options.method === "GET") {
      const getCount = fetchCalls.filter((call) => !call.options.method || call.options.method === "GET").length
      return getCount === 1 ? gistResponse(initialState) : gistResponse(latestState)
    }
    assert.equal(options.method, "PATCH")
    return {
      ok: true,
      status: 200,
      async json() {
        return {}
      },
      async text() {
        return ""
      },
    }
  }

  try {
    const stateStore = await importFresh("lib/state-store.js")
    const result = await stateStore.updateDraftStore("draft_1", async (draft) => {
      draft.status = "approved"
      draft.text = "Reviewed draft"
      return draft
    })

    const patchCall = fetchCalls.find((call) => call.options.method === "PATCH")
    assert.ok(patchCall, "expected a PATCH write to the gist")
    const written = JSON.parse(JSON.parse(patchCall.options.body).files["state.json"].content)

    assert.deepEqual(written.posted_events, ["event_1", "event_2"])
    assert.equal(written.run_history[0].id, "run_2")
    assert.equal(written.drafts.length, 2)
    assert.equal(written.drafts.find((draft) => draft.id === "draft_1").status, "approved")
    assert.equal(written.drafts.find((draft) => draft.id === "draft_2").text, "Fresh bot draft")
    assert.deepEqual(written.memory, latestState.memory)
    assert.deepEqual(written.data_source_failures, { ghcn: 2 })

    assert.equal(result.state.drafts.length, 2)
    assert.equal(result.draft.status, "approved")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("sqlite state store preserves Python-owned metadata keys", async () => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "theheat-state-store-"))
  const dbPath = path.join(tmp, "state.sqlite")
  process.env.THEHEAT_STATE_BACKEND = "sqlite"
  process.env.THEHEAT_DB_PATH = dbPath
  process.env.GIST_ID = ""
  process.env.GITHUB_TOKEN = ""

  try {
    const stateStore = await importFresh("lib/state-store.js")
    const sourceState = {
      last_hot10: { date: null, cities: [] },
      streaks: {},
      posted_events: [],
      daily_tweet_count: {},
      pending_confirmations: [],
      drafts: [],
      run_history: [],
      errors: [],
      suppressions: [
        {
          id: "supp_1",
          ts: "2026-05-09T00:00:00Z",
          source: "ghcn",
          stage: "fact_check",
          event_id: "ev_1",
        },
      ],
      memory: {
        ongoing_events: [{ event_id: "storm_1", last_seen: "2026-05-09T00:00:00Z" }],
        used_era_anchors: ["Spider-Man 2002"],
        used_peer_comparisons: [],
        used_framings: [],
        shipped_tweets: [],
      },
      data_source_failures: { ghcn: 2 },
      synthesis_components: {
        fires: { CA: [{ event_id: "fire_1", at: "2026-05-09T00:00:00Z" }] },
        heats: {},
        drought_snapshot: null,
      },
      synthesis_cooldown: { fire_drought_heat: { CA: "2026-05-09T00:00:00Z" } },
      fire_complex_tiers: { complex_1: 3 },
      record_streaks: { station_1: { days: 2, last_date: "2026-05-08" } },
      ice_mass_last_seen: { greenland: "2026-03" },
    }

    await stateStore.writeStateStore(sourceState)
    await stateStore.writeStateStore({
      drafts: [
        {
          id: "draft_1",
          text: "Dashboard-only partial write",
          status: "pending",
          created_at: "2026-05-09T00:10:00Z",
        },
      ],
    })
    const loaded = await stateStore.readStateStore()

    assert.equal(loaded.drafts[0].text, "Dashboard-only partial write")
    assert.deepEqual(loaded.memory.used_era_anchors, ["Spider-Man 2002"])
    assert.deepEqual(loaded.memory.ongoing_events, sourceState.memory.ongoing_events)
    assert.deepEqual(loaded.data_source_failures, { ghcn: 2 })
    assert.deepEqual(loaded.synthesis_components, sourceState.synthesis_components)
    assert.deepEqual(loaded.synthesis_cooldown, sourceState.synthesis_cooldown)
    assert.deepEqual(loaded.fire_complex_tiers, { complex_1: 3 })
    assert.deepEqual(loaded.record_streaks, sourceState.record_streaks)
    assert.deepEqual(loaded.ice_mass_last_seen, { greenland: "2026-03" })
    assert.equal(loaded.suppressions.length, 1)
    assert.equal(loaded.suppressions[0].stage, "fact_check")
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})
