import { fileURLToPath } from "node:url"
const distDir = process.env.THEHEAT_GIST_STORE_JOURNEY_DIST_DIR
if (!distDir || distDir.startsWith("/")) throw new Error("Use the owned gist-store journey launcher")
export default { distDir, experimental: { externalDir: true }, outputFileTracingRoot: fileURLToPath(new URL("../../..", import.meta.url)) }
