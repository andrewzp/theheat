import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

// New, opt-in invented-data scope for the three hazard image families. Never opens a
// personal profile or reruns an old browser case. Ordinary npm test records it as unperformed.
const FAMILIES = {
  pm25: { kind: "gist_pm25_forecast_v1", queue: "Invented PM2.5 model forecast", label: "Model forecast chart" },
  modis: { kind: "gist_modis_locator_v1", queue: "Invented satellite heat detections", label: "MODIS satellite detections" },
  viirs: { kind: "gist_viirs_locator_v1", queue: "Invented NOAA-20 VIIRS", label: "NOAA-20/NOAA-21 VIIRS satellite detections" },
}

test("owned hazard PNG preview, full-size view, attach, joint review, edits, approval and refusal at 1280/390/320", {
  skip: !process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG && "Run the new owned hazard journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_gist_hazard_journey", actual_handlers: true, actual_python_png: true,
    mocked: ["Gist in-memory transport", "fixture-only preview HTTP boundary", "explicit invented clock", "recorded workflow dispatch"],
    source_or_platform_calls: 0, publication_calls: 0, widths: [], errors: [], refused_requests: [] }
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      page.on("pageerror", error => report.errors.push(String(error)))
      await context.route("**/*", route => {
        const url = new URL(route.request().url())
        if (url.origin !== config.origin) { report.refused_requests.push(url.href); return route.abort() }
        return route.continue()
      })
      const control = async () => (await (await page.request.get(`${config.origin}/api/fixture-control`)).json())
      const command = async data => assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data })).ok())
      const saved = async id => (await control()).state.drafts.find(d => d.id === id)
      await command({ action: "reset" })
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const panel = page.getByRole("region", { name: "Saved-source graphic preview", exact: true })
      const press = async locator => { await locator.focus(); await page.keyboard.press("Enter") }
      // Wait for this exact action's response, not an earlier feedback message.
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
      const preview = async () => {
        await press(panel.getByRole("button", { name: /^(Preview graphic|Rebuild preview)$/ }))
        await panel.locator(".graphic-preview-figure > img").waitFor()
        await page.waitForFunction(() => { const image = document.querySelector(".graphic-preview-figure > img"); return image?.complete && image.naturalWidth === 1200 && image.naturalHeight === 1500 })
      }
      const row = { width, families: {} }
      for (const family of Object.keys(FAMILIES)) {
        const id = `invented-${family}`, spec = FAMILIES[family]
        await command({ action: "clock", family, when: "current" })
        await select(family)
        await preview()
        const text = await panel.innerText()
        assert.match(text, /Image description sent to X/); assert.match(text, /Expanded source details \(not sent\)/)
        assert.match(text, /Within its posting window when previewed/)
        assert.ok(text.includes(spec.label), spec.label)
        const delivery = await panel.locator(".graphic-full-description p").innerText()
        const inline = await panel.locator(".graphic-preview-figure > img").boundingBox()
        // Full-size inspection with the keyboard: Escape and the close button both restore focus.
        const opener = panel.getByRole("button", { name: "View full size", exact: true })
        await press(opener)
        const dialog = page.locator("dialog.graphic-full-size[open]")
        await dialog.waitFor()
        assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Close full-size image")
        await page.waitForFunction(() => { const image = document.querySelector("dialog[open] img"); return image?.complete && image.naturalWidth === 1200 })
        const full = await dialog.locator("img").boundingBox()
        assert.ok(full.width >= Math.min(width, 1200) - 2 && full.width <= Math.min(width, 1200) + 1, JSON.stringify({ width, full }))
        assert.equal(await dialog.locator("img").getAttribute("alt"), delivery)
        await page.screenshot({ path: `${config.screens}/${width}-${family}-full-size.png` })
        await page.keyboard.press("Escape")
        await dialog.waitFor({ state: "detached" })
        assert.equal(await page.evaluate(() => document.activeElement?.textContent), "View full size")
        await page.keyboard.press("Enter")
        await dialog.waitFor()
        await press(dialog.getByRole("button", { name: "Close full-size image", exact: true }))
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
          await preview()
          const checkbox = panel.getByRole("checkbox", { name: /I checked the exact text, image, X image description and source details/ })
          const button = panel.getByRole("button", { name: "Record joint review", exact: true })
          assert.equal(await button.isDisabled(), true)
          await checkbox.focus(); await page.keyboard.press("Space")
          assert.equal((await act(button)).ok, true)
          await page.locator(".queue-item.selected", { hasText: "text and graphic reviewed" }).waitFor()
          const reviewed = await saved(id)
          assert.equal(reviewed.review_binding.kind, "human_media")
          return reviewed
        }
        const reviewed = await review()
        const result = { attached_png_sha256: attached.media_attachment.image.png_sha256, delivery_chars: [...delivery].length,
          inline_width: Math.round(inline.width), full_width: Math.round(full.width) }
        if (family === "pm25") {
          // Out-of-window approval is refused without a write; inside the window it dispatches once.
          await command({ action: "clock", family, when: "expired" })
          const writes = (await control()).writes
          const refused = await act(page.getByRole("button", { name: "Approve + Post", exact: true }))
          assert.equal(refused.ok, false); assert.equal(refused.code, "media_forecast_ended")
          assert.match(refused.text, /cannot be approved for posting; the draft is unchanged/)
          assert.match(await page.locator(".draft-feedback.error").last().innerText(), /cannot be approved for posting/)
          assert.equal((await control()).writes, writes); assert.equal((await control()).dispatches.length, 0)
          await command({ action: "clock", family, when: "current" })
          assert.equal((await act(page.getByRole("button", { name: "Approve + Post", exact: true }))).ok, true)
          const approved = await saved(id), dispatches = (await control()).dispatches
          assert.equal(approved.status, "approved"); assert.equal(dispatches.length, 1)
          assert.deepEqual(dispatches[0].inputs, { mode: "manual_tweet", tweet_text: reviewed.text, draft_id: id, publish_intent_id: approved.publish_intent_id })
          result.expired_approval_refused = true; result.approved_dispatches = 1
        } else if (family === "modis") {
          // A quote-reference-only edit keeps text, source and image but revokes joint review.
          const references = page.getByRole("region", { name: "Operator-selected source references", exact: true }).first()
          await press(page.getByRole("button", { name: "Edit", exact: true }))
          const quote = references.getByLabel("Select a quote from the current draft")
          await quote.focus(); await page.keyboard.press("ControlOrMeta+A")
          await page.keyboard.press("Tab")
          assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Use selected quote")
          await page.keyboard.press("Enter")
          const fact = references.getByRole("checkbox", { name: /source product: MODIS_NRT/ })
          await fact.focus(); await page.keyboard.press("Space")
          await press(references.getByRole("button", { name: "Add reference", exact: true }))
          assert.equal((await act(page.getByRole("button", { name: "Save", exact: true }))).ok, true)
          await references.getByText("Saved for this exact text and source snapshot.", { exact: true }).waitFor()
          const edited = await saved(id)
          assert.equal(edited.text, reviewed.text); assert.deepEqual(edited.media_attachment, reviewed.media_attachment)
          assert.equal(edited.review_binding, undefined); assert.equal(edited.content_revision, reviewed.content_revision + 1)
          await review()
          result.reference_edit_revoked_joint_review = true
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
          assert.equal((await act(panel.getByRole("button", { name: "Remove graphic", exact: true }))).ok, true)
          await panel.getByRole("button", { name: "Remove graphic", exact: true }).waitFor({ state: "detached" })
          const removed = await saved(id)
          assert.equal(removed.media_attachment, undefined)
          assert.ok(removed.revision_history.some(r => r.media_attachment?.image?.png_sha256 === attached.media_attachment.image.png_sha256))
          result.text_edit_revoked_joint_review = true; result.removed = true
        }
        row.families[family] = result
      }
      // Switching drafts discards the old image; a refused preview writes nothing.
      await select("modis"); await preview()
      await select("pm25"); await panel.locator(".graphic-preview-figure > img").waitFor({ state: "detached" })
      assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
      await select("viirs")
      const writes = (await control()).writes
      await command({ action: "refuse_preview" })
      await press(panel.getByRole("button", { name: "Preview graphic", exact: true }))
      await panel.getByRole("status").filter({ hasText: /saved source or display limits cannot support/i }).waitFor()
      assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
      assert.equal((await control()).writes, writes)
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      const final = await control()
      assert.deepEqual(final.refused, [])
      assert.equal(final.dispatches.length, 1)
      assert.ok(!JSON.stringify(final.state).includes("iVBORw0KGgo"))
      await page.screenshot({ path: `${config.screens}/${width}-refusal.png`, fullPage: true })
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
