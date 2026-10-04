// Local synthetic Python/JS parity harness. No network or production state.
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"
import { projectUsageCost } from "../dashboard/lib/usage-cost-scenario.js"
const cases = JSON.parse(readFileSync(0, "utf8"))
const result = Object.fromEntries(Object.entries(cases).map(([name, value]) => {
  const before = structuredClone(value)
  let report
  try { report = projectUsageCost(value.window, {scenario: value.scenario}) }
  catch (error) { report = {error: error.message} }
  assert.deepEqual(value, before)
  return [name, report]
}))
process.stdout.write(JSON.stringify(result))
