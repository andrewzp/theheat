import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import test from "node:test"
import { fingerprint } from "../lib/draft-revisions.js"
import { validGistTemperatureMedia } from "../lib/gist-temperature-media.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const hash = value => createHash("sha256").update(value).digest("hex")
function fixture(alt) {
  const source = { revision_id: "a".repeat(64), baseline: { revision_id: "b".repeat(64) },
    station_id: "USC99000001", valid_date: "2026-09-08" }
  const bundle = { raw_signal_dump: { evidence: source } }
  return { review_context: { two_bot: { bundle } }, media_attachment: {
    schema_version: 1, kind: "gist_temperature_comparator_v1", bundle_sha256: fingerprint(bundle),
    source_revision_sha256: source.revision_id, baseline_revision_sha256: source.baseline.revision_id,
    station_id: source.station_id, valid_date: source.valid_date, png_sha256: "c".repeat(64),
    alt_text: alt, alt_sha256: hash(alt), renderer: {
      implementation_sha256: manifest.identity.files["src/media/gist_temperature_media.py"],
      font_sha256: manifest.identity.files["src/media/fonts/DejaVuSansMono.ttf"],
      pillow: "12.2.0", freetype: "invented", zlib: "invented", width: 1200, height: 1500,
    },
  } }
}

for (const [name, alt, accepted] of [
  ["exact scalar bound", "x".repeat(1000), true],
  ["over scalar bound", "x".repeat(1001), false],
  ["exact UTF8 bound", "é".repeat(500), true],
  ["over UTF8 bound", "é".repeat(501), false],
  ["exact supplementary UTF8 bound", "🧊".repeat(250), true],
  ["over supplementary UTF8 bound", "🧊".repeat(251), false],
  ["unpaired surrogate", "\ud800", false],
]) test(`temperature description: ${name}`, () => {
  assert.equal(validGistTemperatureMedia(fixture(alt)), accepted)
})
