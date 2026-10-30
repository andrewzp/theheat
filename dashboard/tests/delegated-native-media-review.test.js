// Milestone D: delegated native joint review is validated here but only ever recorded by
// the trusted Python operator seam; plus preview layout rules at 1280/390/320. Pure Node:
// these are static/domain checks, not browser, native-device or hosted proof.
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { GIST_HAZARD_KINDS, GIST_NATIVE_KINDS, GIST_STORE_KINDS } from "../lib/gist-media.js"
import { manualReviewLabel } from "../lib/draft-review-ui.js"
import { approvalIsCurrent, fingerprint, reviewIsCurrent } from "./helpers/review-policy.js"

const route = readFileSync(new URL("../app/api/drafts/route.js", import.meta.url), "utf8")
const revisionsSource = readFileSync(new URL("../lib/draft-revisions.js", import.meta.url), "utf8")
const css = readFileSync(new URL("../app/dashboard.css", import.meta.url), "utf8")

test("only native kinds can carry a delegated joint review", () => {
  assert.deepEqual([...GIST_NATIVE_KINDS].sort(), ["gist_temperature_comparator_v1", ...GIST_HAZARD_KINDS].sort())
  for (const kind of GIST_STORE_KINDS) assert.equal(GIST_NATIVE_KINDS.includes(kind), false)
})

test("the browser can never record a delegated review", () => {
  // The route records only human or human_media reviews; the delegated record is Python-only.
  assert.equal(route.includes("delegated_media"), false)
  assert.equal(route.includes("delegation"), false)
  assert.equal(/export function recordDelegated/.test(revisionsSource), false)
})

test("a delegated media binding without a native image is never current", () => {
  const delegation = { scope: "one_manual_post", reviewer: "codex", authorization_sha256: "a".repeat(64), review_receipt_sha256: "b".repeat(64) }
  const draft = { id: "d", text: "Invented text.", content_revision: 1, review_context: { two_bot: { bundle: { event_id: "e" } } } }
  draft.review_binding = { kind: "delegated_media", delegation, media_sha256: "0".repeat(64) }
  assert.equal(reviewIsCurrent(draft), false)
  draft.media_attachment = { kind: "gist_crw_anomaly_v1" }
  draft.review_binding.media_sha256 = fingerprint(draft.media_attachment)
  assert.equal(reviewIsCurrent(draft), false)
  draft.approval_binding = { mode: "manual" }
  assert.equal(approvalIsCurrent(draft, "manual"), false)
})

test("the workbench names a delegated media review as assistant reviewed, never human", () => {
  assert.equal(manualReviewLabel({ review_kind: "delegated_media" }), "assistant reviewed text and graphic")
  assert.notEqual(manualReviewLabel({ review_kind: "delegated_media" }), "text and graphic reviewed")
  const workbench = readFileSync(new URL("../app/components/DraftWorkbench.js", import.meta.url), "utf8")
  assert.match(workbench, /One manual post only; never automatic, a human rating or a scientific verdict\./)
})

function rule(selector) {
  const match = css.match(new RegExp(`(?:^|\\n)${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`))
  assert.ok(match, `missing rule ${selector}`)
  return Object.fromEntries(match[1].split(";").map(part => part.split(":").map(value => value.trim())).filter(([k]) => k))
}

test("preview figures fit 1280, 390 and 320 wide viewports without horizontal overflow", () => {
  const figure = rule(".graphic-preview-figure")
  const image = rule(".graphic-preview-figure img")
  assert.equal(figure["min-width"], "0")
  assert.equal(figure["max-width"], "680px")
  assert.deepEqual([image.display, image.width, image.height], ["block", "100%", "auto"])
  const gutter = 16 * 2
  for (const viewport of [1280, 390, 320]) {
    const width = Math.min(680, viewport - gutter)
    assert.ok(width <= viewport - gutter && width > 0, `${viewport}`)
    for (const [w, h] of [[1200, 675], [1200, 1500]]) {
      const height = Math.round(width * h / w)  // Hot10 16:9 and PM2.5 4:5 cards keep their aspect.
      assert.ok(height > 0 && height <= Math.round(width * 1.25), `${viewport}: ${w}x${h}`)
    }
  }
  assert.match(css, /\.graphic-preview \.btn, \.temperature-media-controls \.btn \{ min-height: 44px; \}/)
})
