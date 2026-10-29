/** Closed media dispatch paired with src/media/gist_media.py. Invented data only;
 * the single Python call renders the real temperature recipe with sockets trapped.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { spawnSync } from "node:child_process"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { policy } from "./helpers/review-policy.js"
import { fingerprint, projectDraft, recordJointMediaReview, reviewIsCurrent } from "../lib/draft-revisions.js"
import { GIST_HAZARD_KINDS, GIST_MEDIA_KINDS, GIST_STORE_KINDS, gistMediaKind, validGistMedia } from "../lib/gist-media.js"
import { validGistTemperatureMedia } from "../lib/gist-temperature-media.js"

const root = path.resolve(process.cwd(), "..")
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const fixtureCode = `
import json,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from src.editorial import revisions
from src.media import gist_media
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from tests.ghcn_graphic_helpers import graphic_bundles
bundle=story_bundle_snapshot(graphic_bundles()[-1])
draft=dict(id='invented-station',event_id=bundle['event_id'],type='all_time_high',status='pending',
  text='Invented station comparison for a saved observed reading.',review_context=dict(two_bot=dict(bundle=bundle)))
revisions.initialize_revision(draft)
revisions.invalidate_media_attachment(draft,gist_media.prepare_media(bundle)['descriptor'],at='2026-09-09T12:00:00Z')
print(json.dumps(draft,ensure_ascii=False))
`
let saved
function attachedDraft() {
  if (!saved) {
    const result = spawnSync(python, ["-c", fixtureCode], { cwd: root, encoding: "utf8", timeout: 60000,
      env: { PATH: process.env.PATH, HOME: "/nonexistent-invented-gist-media", LC_ALL: "C", LANG: "C", NETRC: "/dev/null",
        PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
    assert.equal(result.status, 0, result.stderr)
    saved = result.stdout
  }
  return JSON.parse(saved)
}

test("temperature stays enabled and its exact validator decides", () => {
  assert.equal(GIST_MEDIA_KINDS[0], "gist_temperature_comparator_v1")
  // Closed list: native hazard kinds, then exactly the three store-backed kinds.
  assert.deepEqual(GIST_MEDIA_KINDS.slice(1), [...GIST_HAZARD_KINDS, ...GIST_STORE_KINDS])
  assert.deepEqual(GIST_STORE_KINDS, ["gist_crw_anomaly_v1", "gist_published_radar_v1", "gist_published_chart_v1"])
  assert.ok(Object.isFrozen(GIST_MEDIA_KINDS))
  const draft = attachedDraft()
  assert.equal(gistMediaKind(draft.media_attachment), "gist_temperature_comparator_v1")
  assert.equal(validGistMedia(draft), true)
  assert.equal(validGistMedia(draft), validGistTemperatureMedia(draft))
  const changed = structuredClone(draft)
  changed.media_attachment.alt_text += " "
  assert.equal(validGistMedia(changed), false)
  assert.equal(validGistMedia(changed), validGistTemperatureMedia(changed))
})

const unknown = [
  ...["gist_pm25_forecast_v1", "gist_modis_locator_v1", "gist_viirs_locator_v1", "gist_crw_anomaly_v1",
    "gist_published_radar_v1", "gist_published_chart_v1"].map(kind => ({ kind, schema_version: 1 })),
  { kind: "gist_temperature_comparator_v2" }, { kind: "postgres_editor_media_v1" }, { kind: "GIST_TEMPERATURE_COMPARATOR_V1" },
  { kind: ["gist_temperature_comparator_v1"] }, {}, null, false, "gist_temperature_comparator_v1", [],
]
for (const attachment of unknown) test(`unknown, malformed or not-yet-enabled attachment ${JSON.stringify(attachment)} never reviews`, () => {
  const draft = attachedDraft()
  draft.media_attachment = structuredClone(attachment)
  // An enabled kind name alone is never a recipe; the family validator refuses it.
  assert.equal(gistMediaKind(attachment), [...GIST_HAZARD_KINDS, ...GIST_STORE_KINDS].includes(attachment?.kind) ? attachment.kind : null)
  assert.equal(validGistMedia(draft), false)
  assert.equal(reviewIsCurrent(draft, policy), false)
  assert.throws(() => recordJointMediaReview(draft, policy), /new preview/)
  const projected = projectDraft(draft, policy)
  assert.equal(projected.media_attachment_sha256, null)
  assert.equal(projected.review_status, "media_review_required")
  // A forged current-looking binding still cannot qualify the unknown kind.
  draft.review_binding = { kind: "human_media", media_sha256: fingerprint(draft.media_attachment ?? null) }
  assert.equal(reviewIsCurrent(draft, policy), false)
})

test("the dispatcher survives either import order of its revision/temperature cycle", () => {
  for (const first of ["gist-temperature-media.js", "gist-media.js", "draft-revisions.js", "lossless-gist.js"]) {
    const url = pathToFileURL(path.join(process.cwd(), "lib", first)).href
    const code = `await import(${JSON.stringify(url)}); const m = await import(${JSON.stringify(pathToFileURL(path.join(process.cwd(), "lib/gist-media.js")).href)}); if (m.GIST_MEDIA_KINDS[0] !== "gist_temperature_comparator_v1" || m.GIST_MEDIA_KINDS.length !== 1 + m.GIST_HAZARD_KINDS.length + m.GIST_STORE_KINDS.length) process.exit(3)`
    const result = spawnSync(process.execPath, ["--input-type=module", "-e", code], { encoding: "utf8", timeout: 30000 })
    assert.equal(result.status, 0, `${first}: ${result.stderr}`)
  }
})
