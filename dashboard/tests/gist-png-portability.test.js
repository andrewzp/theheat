/** Schema-2 canonical PNG recipes in the paired browser/route validators. Invented data only;
 * one Python call renders real descriptors with sockets trapped. Node's own zlib inflates
 * every PNG independently of Python and Pillow.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import path from "node:path"
import { inflateSync } from "node:zlib"
import { validGistMedia } from "../lib/gist-media.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const root = path.resolve(process.cwd(), "..")
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const code = `
import base64,json,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from src.editorial import revisions
from src.media import gist_hazard_media as hazard, gist_temperature_media as temperature
from tests.gist_png_vectors import CASES, GOLDEN
out={}
for name in ('temperature-high-all_time','pm25-sendable-varying','modis-four','viirs-noaa20-four'):
    family,build,synthetic=CASES[name]
    bundle=build()
    prepared=(temperature if family=='temperature' else hazard).prepare_media(bundle)
    draft=dict(id='invented-'+name,event_id=bundle.get('event_id','invented'),type='invented',status='pending',
      text='Invented portable graphic draft.',review_context=dict(two_bot=dict(bundle=bundle)))
    revisions.initialize_revision(draft)
    revisions.invalidate_media_attachment(draft,prepared['descriptor'],at='2026-06-08T12:00:00Z')
    out[name]=dict(draft=json.dumps(draft,ensure_ascii=False),png=base64.b64encode(prepared['png']).decode(),golden=GOLDEN[name])
print(json.dumps(out))
`
let cached
function vectors() {
  if (!cached) {
    const result = spawnSync(python, ["-c", code], { cwd: root, encoding: "utf8", timeout: 120000, maxBuffer: 16 * 1024 * 1024,
      env: { PATH: process.env.PATH, HOME: "/nonexistent-invented-png", LC_ALL: "C", LANG: "C", NETRC: "/dev/null",
        PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
    assert.equal(result.status, 0, result.stderr?.slice(-3000))
    cached = JSON.parse(result.stdout)
  }
  return cached
}
const sha = bytes => createHash("sha256").update(bytes).digest("hex")

// W3C PNG filter reconstruction written for this test (only Sub and Up are expected).
function decode(png) {
  assert.ok(png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])))
  const chunks = []
  for (let at = 8; at < png.length;) {
    const length = png.readUInt32BE(at), kind = png.toString("latin1", at + 4, at + 8)
    chunks.push([kind, png.subarray(at + 8, at + 8 + length)])
    at += 12 + length
  }
  assert.deepEqual(chunks.map(([kind]) => kind), ["IHDR", "IDAT", "IEND"])
  const width = chunks[0][1].readUInt32BE(0), height = chunks[0][1].readUInt32BE(4)
  assert.deepEqual([...chunks[0][1].subarray(8)], [8, 2, 0, 0, 0])
  const filtered = inflateSync(chunks[1][1]), stride = width * 3, out = Buffer.alloc(stride * height)
  let previous = Buffer.alloc(stride)
  for (let y = 0; y < height; y++) {
    const kind = filtered[y * (stride + 1)], line = filtered.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1))
    assert.ok(kind === 1 || kind === 2)
    const row = out.subarray(y * stride, (y + 1) * stride)
    for (let x = 0; x < stride; x++) row[x] = (line[x] + (kind === 1 ? (x >= 3 ? row[x - 3] : 0) : previous[x])) & 255
    previous = row
  }
  return { width, height, rgb: out }
}

for (const name of ["temperature-high-all_time", "pm25-sendable-varying", "modis-four", "viirs-noaa20-four"]) {
  test(`${name}: Node inflates the exact golden pixels and accepts only the schema-2 recipe`, () => {
    const value = vectors()[name], draft = JSON.parse(value.draft), png = Buffer.from(value.png, "base64")
    const [rgbSha, pngSha, size] = value.golden
    assert.equal(png.length, size)
    assert.equal(sha(png), pngSha)
    const decoded = decode(png)
    assert.deepEqual([decoded.width, decoded.height], [1200, 1500])
    assert.equal(sha(decoded.rgb), rgbSha)
    assert.equal(validGistMedia(draft), true)
    const attachment = draft.media_attachment, temperature = attachment.kind === "gist_temperature_comparator_v1"
    assert.equal(attachment.schema_version, 2)
    assert.equal(attachment.renderer.png_codec, "canonical-png-fixed-huffman-1")
    assert.equal(Object.hasOwn(attachment.renderer, "zlib"), false)
    const codec = manifest.identity.files["src/media/canonical_png.py"]
    assert.equal(temperature ? attachment.renderer.codec_sha256 : attachment.renderer.files["src/media/canonical_png.py"], codec)
    const mutations = [
      d => { d.media_attachment.schema_version = 1 },
      d => { d.media_attachment.renderer.png_codec = "canonical-png-fixed-huffman-0" },
      d => { d.media_attachment.renderer.zlib = "1.2.11" },
      d => { delete d.media_attachment.renderer.png_codec; d.media_attachment.renderer.zlib = "1.3.1.zlib-ng" },
      d => { if (temperature) d.media_attachment.renderer.codec_sha256 = "0".repeat(64)
             else d.media_attachment.renderer.files["src/media/canonical_png.py"] = "0".repeat(64) },
      d => { if (temperature) delete d.media_attachment.renderer.codec_sha256
             else delete d.media_attachment.renderer.files["src/media/canonical_png.py"] },
      d => { if (!temperature) d.media_attachment.renderer.version = "gist-hazard-png-1"
             else d.media_attachment.renderer.font_sha256 = "0".repeat(64) },
    ]
    for (const mutate of mutations) {
      const changed = structuredClone(draft)
      mutate(changed)
      assert.equal(validGistMedia(changed), false)
    }
  })
}
