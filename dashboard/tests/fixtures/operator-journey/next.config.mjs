// Invented operator-journey fixture. It mounts the dashboard's actual
// components from ../../../app, so externalDir is required. The launcher
// supplies a relative private build directory; nothing is built in the tree.
import { fileURLToPath } from "node:url"

const distDir = process.env.THEHEAT_OPERATOR_JOURNEY_DIST_DIR
if (!distDir || distDir.startsWith("/")) {
  throw new Error("Set THEHEAT_OPERATOR_JOURNEY_DIST_DIR to a relative private build directory (scripts/operator_media_journey.mjs).")
}

export default {
  distDir,
  experimental: { externalDir: true },
  outputFileTracingRoot: fileURLToPath(new URL("../../..", import.meta.url)),
}
