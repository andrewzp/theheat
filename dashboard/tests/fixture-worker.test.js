import test from "node:test"
import assert from "node:assert/strict"
import { createServer } from "node:http"
import { runFixtureWorker } from "../test-support/fixture-worker.js"

test("fixture HTTP remains responsive while a real child waits for its response", async () => {
  let requests = 0
  const server = createServer((request, response) => {
    requests += 1
    assert.equal(request.url, "/invented-worker-ready")
    response.end("invented fixture response")
  })
  await new Promise((resolve, reject) => {
    server.once("error", reject)
    server.listen(0, "127.0.0.1", resolve)
  })
  try {
    const url = `http://127.0.0.1:${server.address().port}/invented-worker-ready`
    const result = await runFixtureWorker(process.execPath, ["--input-type=module", "-e",
      'const response = await fetch(process.argv[1]); console.log(await response.text())', url],
    { encoding: "utf8", timeout: 3000 })
    assert.equal(result.status, 0, result.stdout + result.stderr)
    assert.equal(result.stdout.trim(), "invented fixture response")
    assert.equal(requests, 1)
  } finally {
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
  }
})

test("fixture worker preserves nonzero exit, separate bounded outputs and original timeout", async () => {
  const failed = await runFixtureWorker(process.execPath, ["-e",
    'process.stdout.write("invented stdout"); process.stderr.write("invented stderr"); process.exit(7)'],
  { encoding: "utf8", timeout: 3000 })
  assert.equal(failed.status, 7)
  assert.equal(failed.stdout, "invented stdout")
  assert.equal(failed.stderr, "invented stderr")
  const oversized = await runFixtureWorker(process.execPath, ["-e", 'process.stdout.write("x".repeat(2 * 1024 * 1024))'],
    { encoding: "utf8", timeout: 3000 })
  assert.equal(oversized.status, null)
  assert.equal(oversized.error.code, "ERR_CHILD_PROCESS_STDIO_MAXBUFFER")
  assert.ok(oversized.stdout.length <= 1024 * 1024)
  const expired = await runFixtureWorker(process.execPath, ["-e", 'setTimeout(() => {}, 60000)'],
    { encoding: "utf8", timeout: 100 })
  assert.equal(expired.status, null)
  assert.equal(expired.error.killed, true)
  assert.equal(expired.signal, "SIGTERM")
})
