import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

// New, opt-in invented-data scope for the store-backed families (CRW, published radar, NHC
// cone). Owned headless browser, private result directory; ordinary npm test records it as
// unperformed. Retained inputs live in a new local store inside the run's result directory.
const FAMILIES = {
  crw: { kind: "gist_crw_anomaly_v1", queue: "Invented Caribbean satellite analysis", label: "Satellite-analysis anomaly chart",
    input: "Retained CRW source packet (SHA256)", natural: 1200, published: false },
  radar: { kind: "gist_published_radar_v1", queue: "Invented catastrophic tornado warning", label: "Published NWS radar",
    input: "Retained published radar asset (SHA256)", natural: 600, published: true },
  cone: { kind: "gist_published_chart_v1", queue: "Invented hurricane forecast cone", label: "Published NHC forecast cone",
    input: "Retained published forecast cone (SHA256)", natural: 897, published: true },
  // The collector retained this draft's exact packet; the Workbench selects it by default.
  crw_collected: { kind: "gist_crw_anomaly_v1", queue: "Invented collector-retained Caribbean", label: "Satellite-analysis anomaly chart",
    input: "Retained CRW source packet (SHA256)", natural: 1200, published: false, collected: true },
}

test("owned retained-asset preview, inspection, attach, attested review, approval, edits and holds at 1280/390/320", {
  skip: !process.env.THEHEAT_GIST_STORE_JOURNEY_CONFIG && "Run the new owned retained-asset journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_GIST_STORE_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_gist_store_journey", actual_handlers: true, actual_python_preview: true, actual_local_store: true,
    mocked: ["Gist in-memory transport", "fixture-only preview HTTP boundary", "explicit invented clock", "recorded workflow dispatch"],
    source_or_platform_calls: 0, publication_calls: 0, widths: [], errors: [], refused_requests: [] }
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      page.on("pageerror", error => report.errors.push(String(error)))
      await context.route("**/*", route => {
        const url = new URL(route.request().url())
        if (url.origin !== config.origin && url.protocol !== "blob:") { report.refused_requests.push(url.href); return route.abort() }
        return route.continue()
      })
      const control = async () => (await (await page.request.get(`${config.origin}/api/fixture-control`)).json())
      const command = async data => assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data })).ok())
      const saved = async id => (await control()).state.drafts.find(d => d.id === id)
      // One invented clock for both sides: the route's Date.now and the page's (NWS warning view).
      const clock = async (family, when) => {
        await command({ action: "clock", family, when })
        await page.clock.setFixedTime(new Date((await control()).clock))
      }
      await command({ action: "reset" })
      const retained = (await control()).retained
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const panel = page.getByRole("region", { name: "Saved-source graphic preview", exact: true })
      const press = async locator => { await locator.focus(); await page.keyboard.press("Enter") }
      const act = async locator => {
        const marker = page.locator("#journey-actions")
        const before = Number(await marker.getAttribute("data-count"))
        await press(locator)
        await page.waitForFunction(n => Number(document.querySelector("#journey-actions").dataset.count) > n, before)
        return { ok: (await marker.getAttribute("data-ok")) === "true", code: await marker.getAttribute("data-code"),
          text: await marker.textContent() }
      }
      const select = async family => {
        await press(page.locator(".queue-item", { hasText: FAMILIES[family].queue }))
        await page.locator(".queue-item.selected", { hasText: FAMILIES[family].queue }).waitFor()
      }
      const enter = async (family, value) => {
        const field = panel.getByLabel(FAMILIES[family].input, { exact: true })
        await field.focus(); await page.keyboard.press("ControlOrMeta+A"); await page.keyboard.insertText(value)
      }
      const preview = async family => {
        await press(panel.getByRole("button", { name: /^(Preview graphic|Rebuild preview)$/ }))
        await panel.locator(".graphic-preview-figure > img").waitFor()
        await page.waitForFunction(n => { const image = document.querySelector(".graphic-preview-figure > img"); return image?.complete && image.naturalWidth === n },
          FAMILIES[family].natural)
      }
      const row = { width, families: {} }
      for (const family of Object.keys(FAMILIES)) {
        const id = `invented-${family}`, spec = FAMILIES[family]
        await clock(family, "current")
        await select(family)
        assert.equal(await panel.getByRole("button", { name: "Preview graphic", exact: true }).isDisabled(), !spec.collected)
        if (spec.collected) {
          // Default selection is the draft's own collected packet; nothing typed, no newest/region lookup.
          assert.equal(await panel.getByLabel(spec.input, { exact: true }).inputValue(), retained[family])
          assert.match(await panel.innerText(), /Selected from the packet the collector retained for this draft/)
        } else {
          if (spec.published) {
            // W10.3: a pasted web address is named and refused before any request; Preview stays disabled.
            await enter(family, "https://www.nhc.noaa.gov/invented/AL052026_5day_cone_with_line_and_wind.png")
            await panel.locator("[data-retained-input-refusal='url']").waitFor()
            assert.match(await panel.locator("[data-retained-input-refusal='url']").innerText(), /never fetched/)
            assert.equal(await panel.getByRole("button", { name: "Preview graphic", exact: true }).isDisabled(), true)
            // W10.6: the picker names this family's lane and requirements.
            assert.match(await panel.locator(`[data-graphic-family='${family}'] summary`).innerText(), /unaltered published image retained in the media store/)
          }
          await enter(family, retained[family])
        }
        await preview(family)
        const text = await panel.innerText()
        assert.match(text, /Image description sent to X/); assert.match(text, /Expanded source details \(not sent\)/)
        assert.match(text, /Within its posting window when previewed/)
        assert.ok(text.includes(spec.label), spec.label)
        const delivery = await panel.locator(".graphic-full-description p").innerText()
        if (spec.published) {
          // Inspect the exact retained original with the keyboard (the image sent is the PNG above).
          const details = panel.locator("details", { hasText: "Original as retained" })
          await press(details.locator("summary"))
          await page.waitForFunction(n => { const image = [...document.querySelectorAll(".graphic-preview-figure details img")][0]; return image?.complete && image.naturalWidth === n },
            spec.natural)
          assert.match(text, /no endorsement implied/); assert.match(text, /nothing is fetched now/)
        }
        const inline = await panel.locator(".graphic-preview-figure > img").boundingBox()
        const opener = panel.getByRole("button", { name: "View full size", exact: true })
        await press(opener)
        const dialog = page.locator("dialog.graphic-full-size[open]")
        await dialog.waitFor()
        assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Close full-size image")
        await page.waitForFunction(n => { const image = document.querySelector("dialog[open] img"); return image?.complete && image.naturalWidth === n }, spec.natural)
        const full = await dialog.locator("img").boundingBox()
        assert.ok(full.width >= Math.min(width, 1200) - 2 && full.width <= Math.min(width, 1200) + 1, JSON.stringify({ width, full }))
        assert.equal(await dialog.locator("img").getAttribute("alt"), delivery)
        await page.screenshot({ path: `${config.screens}/${width}-${family}-full-size.png` })
        await page.keyboard.press("Escape")
        await dialog.waitFor({ state: "detached" })
        assert.equal(await page.evaluate(() => document.activeElement?.textContent), "View full size")
        await page.screenshot({ path: `${config.screens}/${width}-${family}-preview.png`, fullPage: true })

        const before = await saved(id)
        assert.equal((await act(panel.getByRole("button", { name: "Attach graphic", exact: true }))).ok, true)
        await panel.getByRole("button", { name: "Remove graphic", exact: true }).waitFor()
        const attached = await saved(id)
        assert.equal(attached.media_attachment.kind, spec.kind)
        assert.equal(attached.media_attachment.description.delivery_text, delivery)
        assert.equal(attached.content_revision, before.content_revision + 1)
        const review = async () => {
          await preview(family)
          const button = panel.getByRole("button", { name: "Record joint review", exact: true })
          const checkbox = panel.getByRole("checkbox", { name: /I checked the exact text, image, X image description and source details/ })
          await checkbox.focus(); await page.keyboard.press("Space")
          const attestations = panel.locator(".graphic-attestations input[type=checkbox]")
          const count = await attestations.count()
          assert.equal(count, spec.published ? 3 : 0)
          for (let index = 0; index < count; index++) {
            assert.equal(await button.isDisabled(), true)  // Every attestation is required, none default.
            await attestations.nth(index).focus(); await page.keyboard.press("Space")
          }
          assert.equal((await act(button)).ok, true)
          await page.locator(".queue-item.selected", { hasText: "text and graphic reviewed" }).waitFor()
          const reviewed = await saved(id)
          assert.equal(reviewed.review_binding.kind, "human_media")
          assert.equal(Boolean(reviewed.review_binding.published_attestations), spec.published)
          return reviewed
        }
        const reviewed = await review()
        const identity = spec.published ? attached.media_attachment.asset.derivative_sha256 : attached.media_attachment.image.png_sha256
        const result = { attached_png_sha256: identity, delivery_chars: [...delivery].length,
          inline_width: Math.round(inline.width), full_width: Math.round(full.width) }
        if (family === "radar") {
          // Past the 15-minute radar ceiling approval is refused without a write; inside it, one dispatch.
          await clock(family, "expired")
          const writes = (await control()).writes
          const refused = await act(page.getByRole("button", { name: "Approve + Post", exact: true }))
          assert.equal(refused.ok, false); assert.equal(refused.code, "media_published_stale")
          assert.match(refused.text, /cannot be approved for posting; the draft is unchanged/)
          assert.equal((await control()).writes, writes); assert.equal((await control()).dispatches.length, 0)
          await clock(family, "current")
          assert.equal((await act(page.getByRole("button", { name: "Approve + Post", exact: true }))).ok, true)
          const approved = await saved(id), dispatches = (await control()).dispatches
          assert.equal(approved.status, "approved"); assert.equal(dispatches.length, 1)
          assert.deepEqual(dispatches[0].inputs, { mode: "manual_tweet", tweet_text: reviewed.text, draft_id: id, publish_intent_id: approved.publish_intent_id })
          result.expired_approval_refused = true; result.approved_dispatches = 1
        } else if (family === "crw_collected") {
          // Any other valid packet is a named hold with no write; then the attached graphic is removed.
          const writes = (await control()).writes
          assert.notEqual(retained.crw_other, retained[family])
          await enter(family, retained.crw_other)
          await press(panel.getByRole("button", { name: "Preview graphic", exact: true }))
          await panel.getByRole("status").filter({ hasText: /not the CRW source packet retained for this draft/ }).waitFor()
          assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
          assert.equal((await control()).writes, writes)
          assert.equal((await act(panel.getByRole("button", { name: "Remove graphic", exact: true }))).ok, true)
          await panel.getByRole("button", { name: "Remove graphic", exact: true }).waitFor({ state: "detached" })
          assert.equal((await saved(id)).media_attachment, undefined)
          await page.screenshot({ path: `${config.screens}/${width}-${family}-removed.png`, fullPage: true })
          result.default_selected = true; result.other_packet_refused = true; result.removed = true
        } else if (family === "crw") {
          // A retained packet that is not in the store is a named hold; nothing is written or fetched.
          const writes = (await control()).writes
          await enter(family, "0".repeat(64))
          assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
          await press(panel.getByRole("button", { name: "Preview graphic", exact: true }))
          await panel.getByRole("status").filter({ hasText: /retained CRW source packet is not in the media store/ }).waitFor()
          assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
          assert.equal((await control()).writes, writes)
          result.missing_packet_hold = true
        } else {
          const editor = async value => {
            await press(page.getByRole("button", { name: "Edit", exact: true }))
            const field = page.getByLabel("Edit draft text", { exact: true })
            await field.focus(); await page.keyboard.press("ControlOrMeta+A"); await page.keyboard.insertText(value)
            assert.equal((await act(page.getByRole("button", { name: "Save", exact: true }))).ok, true)
            await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
          }
          await editor(reviewed.text + " Changed.")
          const changed = await saved(id)
          assert.equal(changed.review_binding, undefined); assert.deepEqual(changed.media_attachment, reviewed.media_attachment)
          await editor(reviewed.text)  // Reverting the text never resurrects the earlier review.
          const reverted = await saved(id)
          assert.equal(reverted.text, reviewed.text); assert.equal(reverted.review_binding, undefined)
          assert.equal((await act(panel.getByRole("button", { name: "Remove graphic", exact: true }))).ok, true)
          await panel.getByRole("button", { name: "Remove graphic", exact: true }).waitFor({ state: "detached" })
          const removed = await saved(id)
          assert.equal(removed.media_attachment, undefined)
          result.text_edit_revoked_joint_review = true; result.revert_did_not_resurrect = true; result.removed = true
        }
        row.families[family] = result
      }
      // Switching drafts discards the old image; an unconfigured store is a named hold with no write.
      await select("crw"); await enter("crw", retained.crw); await preview("crw")
      await select("cone"); await panel.locator(".graphic-preview-figure > img").waitFor({ state: "detached" })
      assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
      await clock("radar", "current"); await select("radar")
      const writes = (await control()).writes
      await command({ action: "refuse_preview" })
      await enter("radar", retained.radar)
      await press(panel.getByRole("button", { name: /^(Preview graphic|Rebuild preview)$/ }))
      await panel.getByRole("status").filter({ hasText: /No media store is configured here/ }).waitFor()
      assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
      assert.equal((await control()).writes, writes)
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      const final = await control()
      assert.deepEqual(final.refused, [])
      assert.equal(final.dispatches.length, 1)
      assert.ok(!JSON.stringify(final.state).includes("iVBORw0KGgo") && !JSON.stringify(final.state).includes("R0lGOD"))
      await page.screenshot({ path: `${config.screens}/${width}-hold.png`, fullPage: true })
      report.widths.push({ ...row, passed: true, writes: final.writes, previews: final.previews, overflow })
      await context.close()
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.refused_requests, [])
  } catch (error) {
    report.failure = String(error)
    for (const context of browser.contexts()) for (const page of context.pages()) {
      writeFileSync(`${config.screens}/failure.txt`, await page.locator("body").innerText())
      await page.screenshot({ path: `${config.screens}/failure.png`, fullPage: true })
    }
    throw error
  } finally {
    await browser.close()
    writeFileSync(config.result, JSON.stringify(report, null, 2) + "\n", { flag: "wx" })
  }
})
