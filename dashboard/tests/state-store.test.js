import test from "node:test"
import assert from "node:assert/strict"

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

    assert.equal(result.state.drafts.length, 2)
    assert.equal(result.draft.status, "approved")
  } finally {
    globalThis.fetch = originalFetch
  }
})
