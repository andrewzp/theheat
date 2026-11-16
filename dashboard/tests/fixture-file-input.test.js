import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import { mkdtempSync, readdirSync, rmdirSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"
import { spawnFixtureWithFileInput } from "./helpers/fixture-file-input.js"

const python = process.env.THEHEAT_TEST_PYTHON || "python3"
function isolated(run) {
  const directory = mkdtempSync(join(tmpdir(), "theheat-fixture-owner-"))
  const previous = process.env.TMPDIR
  process.env.TMPDIR = directory
  try { run(); assert.deepEqual(readdirSync(directory), []) }
  finally {
    if (previous === undefined) delete process.env.TMPDIR
    else process.env.TMPDIR = previous
    rmdirSync(directory)
  }
}

test("real Python receives the entire unchanged Unicode JSON and immediate EOF", () => isolated(() => {
  const input = JSON.stringify({ text: "−20°C\n站点 🌍".repeat(100000), amount: 180.5 })
  const code = "import sys,json,hashlib,os,stat; raw=sys.stdin.buffer.read(); value=json.loads(raw); print(json.dumps([hashlib.sha256(raw).hexdigest(),value['amount'],stat.S_ISREG(os.fstat(0).st_mode)]))"
  const result = spawnFixtureWithFileInput(python, ["-c", code], { input, encoding: "utf8", timeout: 3000 })
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout), [createHash("sha256").update(input).digest("hex"), 180.5, true])
}))

test("child failures retain their status, output and stderr and remove only owned input", () => isolated(() => {
  const result = spawnFixtureWithFileInput(python, ["-c", "import sys; print('fixture output'); print('fixture error',file=sys.stderr); sys.exit(42)"],
    { input: "{}", encoding: "utf8", timeout: 3000 })
  assert.equal(result.status, 42)
  assert.equal(result.stdout, "fixture output\n")
  assert.equal(result.stderr, "fixture error\n")
}))

test("timeout remains a failed child at the caller's unchanged deadline", () => isolated(() => {
  const result = spawnFixtureWithFileInput(python, ["-c", "import time; time.sleep(10)"],
    { input: "{}", encoding: "utf8", timeout: 150 })
  assert.equal(result.status, null)
  assert.equal(result.error.code, "ETIMEDOUT")
  assert.equal(result.signal, "SIGTERM")
}))

test("missing executable preserves the spawn error and cleans up", () => isolated(() => {
  const result = spawnFixtureWithFileInput("/invented-no-such-python", [], { input: "{}", encoding: "utf8", timeout: 3000 })
  assert.equal(result.status, null)
  assert.equal(result.error.code, "ENOENT")
}))
