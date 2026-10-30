/** The collector's retained CRW packet reference: exact default selection and pairing.
 * Python remains the authority; these checks only keep the browser from offering or
 * accepting anything else. Invented values; nothing is fetched.
 */
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import test from "node:test"
import { MEDIA_HOLD_MESSAGES, retainedPacketReference } from "../lib/graphic-preview.js"

const sha = c => c.repeat(64)
const draft = (raw, signal = "regional_sst_anomaly") => ({ review_context: { two_bot: { bundle: { signal_kind: signal, raw_signal_dump: raw } } } })

test("only a well-formed reference on a CRW bundle is a default selection", () => {
  const value = { schema_version: 1, artifact_sha256: sha("a"), packet_sha256: sha("b") }
  assert.deepEqual(retainedPacketReference(draft({ region_slug: "caribbean", retained_packet: value })), value)
  assert.equal(retainedPacketReference(draft({ region_slug: "caribbean" })), null)  // Legacy/manual retention.
  assert.equal(retainedPacketReference(draft({ retained_packet: value }, "severe_weather")), null)
  for (const bad of [null, "x", [], { ...value, schema_version: 2 }, { ...value, artifact_sha256: sha("A") },
    { ...value, extra: true }, { schema_version: 1, artifact_sha256: sha("a") }])
    assert.deepEqual(retainedPacketReference(draft({ retained_packet: bad })), { invalid: true })
})

test("hold texts are paired exactly with the Python table", () => {
  const python = process.env.THEHEAT_TEST_PYTHON || "python3"
  const run = spawnSync(python, ["-c", "import json; from src.dashboard_preview.errors import MEDIA_HOLDS; print(json.dumps(MEDIA_HOLDS))"],
    { cwd: "..", encoding: "utf8", env: { PATH: process.env.PATH, LC_ALL: "C", PYTHON_DOTENV_DISABLED: "1" } })
  assert.equal(run.status, 0, run.stderr)
  assert.deepEqual(JSON.parse(run.stdout), { ...MEDIA_HOLD_MESSAGES })
})
