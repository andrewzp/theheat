import { execFile } from "node:child_process"

// The fixture's HTTP server/client share this event loop. A synchronous worker
// delays socket close/deadline handling; await the child without blocking it.
// Preserve the caller's timeout and spawnSync's 1 MiB per-stream output bound.
export function runFixtureWorker(file, args, options) {
  return new Promise((resolve) => {
    execFile(file, args, { ...options, shell: false, maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
      resolve({
        status: error ? (Number.isInteger(error.code) ? error.code : null) : 0,
        stdout, stderr, error, signal: error?.signal || null,
      })
    })
  })
}
