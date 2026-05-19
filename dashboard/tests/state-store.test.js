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
    last_hot10: {
      date: "2026-05-14",
      cities: [{ city: "Phoenix", anomaly_c: 9.1 }],
    },
    streaks: {
      Phoenix: { consecutive_days: 3, last_seen: "2026-05-14" },
    },
    pending_confirmations: [
      {
        event_id: "pending_1",
        detected: "2026-05-14",
        source: "open_meteo",
        city: "Phoenix",
      },
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
    assert.deepEqual(written.last_hot10, latestState.last_hot10)
    assert.deepEqual(written.streaks, latestState.streaks)
    assert.deepEqual(written.pending_confirmations, latestState.pending_confirmations)
    assert.deepEqual(written.memory, latestState.memory)
    assert.deepEqual(written.data_source_failures, { ghcn: 2 })

    assert.equal(result.state.drafts.length, 2)
    assert.equal(result.draft.status, "approved")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("readStateStore fetches raw gist content when state.json is truncated", async () => {
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"

  const fullState = {
    drafts: [
      { id: "draft_1", text: "Full state draft", status: "pending", created_at: "2026-05-14T00:00:00Z" },
    ],
    posted_events: [],
    run_history: [
      {
        id: "run_1",
        mode: "alerts",
        started_at: "2026-05-14T00:00:00Z",
        sources: [{ source: "ocean_sst", status: "failed", error: "fetch failed" }],
      },
    ],
    errors: [],
    last_hot10: { date: null, cities: [] },
    streaks: {},
    daily_tweet_count: {},
    pending_confirmations: [],
  }

  const fetchCalls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options })
    if (String(url).includes("api.github.com/gists")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            files: {
              "state.json": {
                content: "{\"drafts\":[",
                truncated: true,
                raw_url: "https://gist.githubusercontent.com/raw/state.json",
              },
            },
          }
        },
        async text() {
          return ""
        },
      }
    }
    if (String(url) === "https://gist.githubusercontent.com/raw/state.json") {
      return {
        ok: true,
        status: 200,
        async text() {
          return JSON.stringify(fullState)
        },
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }

  try {
    const stateStore = await importFresh("lib/state-store.js")
    const loaded = await stateStore.readStateStore()

    assert.equal(loaded.drafts[0].text, "Full state draft")
    assert.equal(loaded.run_history[0].sources[0].source, "ocean_sst")
    assert.equal(fetchCalls.length, 2)
    assert.equal(fetchCalls[1].url, "https://gist.githubusercontent.com/raw/state.json")
    assert.match(fetchCalls[1].options.headers.Authorization, /^token /)
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
      last_hot10: { date: "2026-05-14", cities: [{ city: "Phoenix", anomaly_c: 9.1 }] },
      streaks: { Phoenix: { consecutive_days: 3, last_seen: "2026-05-14" } },
      posted_events: [],
      daily_tweet_count: {},
      pending_confirmations: [
        {
          event_id: "pending_1",
          detected: "2026-05-14",
          source: "open_meteo",
          city: "Phoenix",
        },
      ],
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
      cyclone_tiers: { "nhc:al012026": 3 },
      cyclone_wind_history: {
        "nhc:al012026": [{ issued_at: "2026-05-14T00:00:00Z", wind_kt: 80 }],
      },
      cyclone_annual_count: { 2026: 1 },
      precip_daily_records: { "france:paris:05-14": { mm: 75, year: 2026 } },
      precip_recent_by_city: { "france:paris": [{ date: "2026-05-14", mm: 75 }] },
      snow_daily_swe_gain_records: { albro_lake: { mm: 50, year: 2026 } },
      snow_recent_by_station: { albro_lake: [{ date: "2026-05-14", mm: 50 }] },
      snow_annual_count: { 2026: 1 },
      seasonal_snow_records: { albro_lake: { mm: 800, year: 2026 } },
      flood_activation_tiers: { EMSR999: "Major" },
      flood_annual_count: { 2026: 2 },
      nao_annual_count: { 2026: 2 },
      ao_annual_count: { 2026: 3 },
      pdo_annual_count: { 2026: 1 },
      nao_last_phase: "Negative",
      ao_last_phase: "Negative",
      pdo_last_phase: "Positive",
      ozone_hole_last_peak: { 2026: { peak_date: "2026-09-20", area_million_km2: 23 } },
      ozone_hole_annual_count: { 2026: 1 },
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
    assert.deepEqual(loaded.last_hot10, sourceState.last_hot10)
    assert.deepEqual(loaded.streaks, sourceState.streaks)
    assert.deepEqual(loaded.pending_confirmations, sourceState.pending_confirmations)
    assert.deepEqual(loaded.memory.used_era_anchors, ["Spider-Man 2002"])
    assert.deepEqual(loaded.memory.ongoing_events, sourceState.memory.ongoing_events)
    assert.deepEqual(loaded.data_source_failures, { ghcn: 2 })
    assert.deepEqual(loaded.synthesis_components, sourceState.synthesis_components)
    assert.deepEqual(loaded.synthesis_cooldown, sourceState.synthesis_cooldown)
    assert.deepEqual(loaded.fire_complex_tiers, { complex_1: 3 })
    assert.deepEqual(loaded.record_streaks, sourceState.record_streaks)
    assert.deepEqual(loaded.ice_mass_last_seen, { greenland: "2026-03" })
    assert.deepEqual(loaded.cyclone_tiers, sourceState.cyclone_tiers)
    assert.deepEqual(loaded.cyclone_wind_history, sourceState.cyclone_wind_history)
    assert.deepEqual(loaded.cyclone_annual_count, sourceState.cyclone_annual_count)
    assert.deepEqual(loaded.precip_daily_records, sourceState.precip_daily_records)
    assert.deepEqual(loaded.precip_recent_by_city, sourceState.precip_recent_by_city)
    assert.deepEqual(loaded.snow_daily_swe_gain_records, sourceState.snow_daily_swe_gain_records)
    assert.deepEqual(loaded.snow_recent_by_station, sourceState.snow_recent_by_station)
    assert.deepEqual(loaded.snow_annual_count, sourceState.snow_annual_count)
    assert.deepEqual(loaded.seasonal_snow_records, sourceState.seasonal_snow_records)
    assert.deepEqual(loaded.flood_activation_tiers, sourceState.flood_activation_tiers)
    assert.deepEqual(loaded.flood_annual_count, sourceState.flood_annual_count)
    assert.deepEqual(loaded.nao_annual_count, sourceState.nao_annual_count)
    assert.deepEqual(loaded.ao_annual_count, sourceState.ao_annual_count)
    assert.deepEqual(loaded.pdo_annual_count, sourceState.pdo_annual_count)
    assert.equal(loaded.nao_last_phase, "Negative")
    assert.equal(loaded.ao_last_phase, "Negative")
    assert.equal(loaded.pdo_last_phase, "Positive")
    assert.deepEqual(loaded.ozone_hole_last_peak, sourceState.ozone_hole_last_peak)
    assert.deepEqual(loaded.ozone_hole_annual_count, sourceState.ozone_hole_annual_count)
    assert.equal(loaded.suppressions.length, 1)
    assert.equal(loaded.suppressions[0].stage, "fact_check")
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})
