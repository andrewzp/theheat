/** Synchronous invented-data fixtures need a complete, EOF-terminated input.
 * A regular file avoids intermittent macOS pipe stalls in Python json.load.
 * Keep the caller's executable, deadline, environment and result unchanged.
 */
import { spawnSync } from "node:child_process"
import { closeSync, constants, mkdtempSync, openSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

export function spawnFixtureWithFileInput(command, args, { input, ...options }) {
  const directory = mkdtempSync(join(tmpdir(), "theheat-fixture-input-"))
  const filename = join(directory, "input.json")
  let fd
  try {
    writeFileSync(filename, input, { flag: "wx", mode: 0o600 })
    fd = openSync(filename, constants.O_RDONLY | constants.O_NOFOLLOW)
    return spawnSync(command, args, { ...options, stdio: [fd, "pipe", "pipe"] })
  } finally {
    if (fd !== undefined) closeSync(fd)
    try { unlinkSync(filename) } catch (error) { if (error.code !== "ENOENT") throw error }
    rmdirSync(directory)
  }
}
