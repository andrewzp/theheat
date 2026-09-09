import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, mkdtempSync, rmSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { writeStateStore, readStateStore } from "../lib/state-store.js"

const cases = JSON.parse(readFileSync(new URL("../../tests/fixtures/temperature_history_contract.json", import.meta.url)))
for (const fixture of cases) {
  test(`material temperature history: ${fixture.name}`, async () => {
    const directory = mkdtempSync(path.join(os.tmpdir(), "heat-history-"))
    const original = { ...process.env }
    const savedFetch = globalThis.fetch
    try {
      process.env.THEHEAT_STATE_BACKEND = "sqlite"
      process.env.THEHEAT_DB_PATH = path.join(directory, "state.sqlite")
      process.env.GIST_ID = ""
      globalThis.fetch = () => { throw new Error("No network in history test") }
      await writeStateStore({ temperature_history: fixture.base })
      await writeStateStore({ temperature_history: fixture.incoming })
      assert.deepEqual((await readStateStore()).temperature_history, fixture.expected)
      await writeStateStore({ temperature_history: fixture.base })
      assert.deepEqual((await readStateStore()).temperature_history, fixture.expected)
    } finally {
      process.env = original
      globalThis.fetch = savedFetch
      rmSync(directory, { recursive: true, force: true })
    }
  })
}
