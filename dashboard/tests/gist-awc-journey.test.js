/** New invented AWC scope only; uses no personal browser profile or live service. */
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

test("owned AWC graphic: keyboard, phone widths, exact source, edit/removal, expiry and draft switching", {
  skip: !process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG && "Run the explicit owned AWC journey",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG, "utf8"))
  assert.deepEqual(config.families, ["awc"])
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_awc_only_graphic_journey", actual_handlers: true, actual_python_png: true,
    mocked: ["invented Gist", "invented clock", "recorded GitHub dispatch"],
    source_calls: 0, platform_calls: 0, widths: [], errors: [], refused_requests: [] }
  try {
    for (const width of [1280, 390, 320]) {
      console.error(JSON.stringify({ scope: "invented_awc", width, stage: "start" }))
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
      const saved = async (id = "invented-awc") => (await control()).state.drafts.find(d => d.id === id)
      const press = async locator => { await locator.focus(); await page.keyboard.press("Enter") }
      const action = async locator => {
        const before = Number(await page.locator("#journey-actions").getAttribute("data-count"))
        await press(locator)
        await page.waitForFunction(n => Number(document.querySelector("#journey-actions").dataset.count) > n, before)
        const output = page.locator("#journey-actions")
        return { ok: (await output.getAttribute("data-ok")) === "true", code: await output.getAttribute("data-code") }
      }
      const select = async index => {
        const pattern = index === 0 ? /^At 12:00 UTC/ : /^Second invented draft:/
        await press(page.locator(".queue-item").filter({ has: page.locator(".queue-text").filter({ hasText: pattern }) }))
        await page.waitForFunction(id => document.querySelector("#journey-selected").dataset.draftId === id,
          index === 0 ? "invented-awc" : "invented-awc-secondary")
      }
      await command({ action: "reset" })
      await command({ action: "clock", family: "awc", when: "current" })
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const panel = page.getByRole("region", { name: "Saved-source graphic preview", exact: true })
      await select(0)
      const preview = async () => {
        await press(panel.getByRole("button", { name: /^(Preview graphic|Rebuild preview)$/ }))
        await panel.locator(".graphic-preview-figure > img").waitFor()
        await page.waitForFunction(() => { const image = document.querySelector(".graphic-preview-figure > img"); return image?.complete && image.naturalWidth === 1200 && image.naturalHeight === 1500 })
      }
      await preview()
      const text = await panel.innerText()
      assert.match(text, /Observed airport temperature comparison/)
      assert.match(text, /two observed airport reports/)
      assert.match(text, /Airport A: North Test Arpt, Norway \(TAAA\), −20°C/)
      assert.match(text, /Airport B: South Test Arpt, Chile \(TBBB\), 45°C/)
      assert.match(text, /Colour identifies airports, not hazard categories/)
      assert.match(text, /Image description sent to X/)
      const delivery = await panel.locator(".graphic-full-description p").innerText()
      const opener = panel.getByRole("button", { name: "View full size", exact: true })
      await press(opener)
      const dialog = page.locator("dialog.graphic-full-size[open]")
      await dialog.waitFor()
      assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Close full-size image")
      assert.equal(await dialog.locator("img").getAttribute("alt"), delivery)
      const full = await dialog.locator("img").boundingBox()
      assert.ok(full.width >= Math.min(width, 1200) - 2 && full.width <= Math.min(width, 1200) + 1)
      await page.screenshot({ path: `${config.screens}/${width}-awc-full-size.png` })
      await page.keyboard.press("Escape")
      await dialog.waitFor({ state: "detached" })
      assert.equal(await page.evaluate(() => document.activeElement?.textContent), "View full size")
      await press(opener)
      await dialog.waitFor()
      await press(dialog.getByRole("button", { name: "Close full-size image", exact: true }))
      await dialog.waitFor({ state: "detached" })
      assert.equal(await page.evaluate(() => document.activeElement?.textContent), "View full size")
      const original = await saved()
      assert.equal((await action(panel.getByRole("button", { name: "Attach graphic", exact: true }))).ok, true)
      const attached = await saved()
      assert.equal(attached.media_attachment.kind, "gist_awc_observed_pair_v1")
      assert.equal(attached.media_attachment.description.delivery_text, delivery)
      assert.equal(attached.content_revision, original.content_revision + 1)
      const review = async () => {
        await preview()
        const checkbox = panel.getByRole("checkbox", { name: /I checked the exact text, image, X image description and source details/ })
        const button = panel.getByRole("button", { name: "Record joint review", exact: true })
        assert.equal(await button.isDisabled(), true)
        await checkbox.focus(); await page.keyboard.press("Space")
        assert.equal((await action(button)).ok, true)
        assert.equal((await saved()).review_binding.kind, "human_media")
      }
      await review()
      console.error(JSON.stringify({ scope: "invented_awc", width, stage: "joint_review_passed" }))
      await select(1)
      await panel.locator(".graphic-preview-figure > img").waitFor({ state: "detached" })
      assert.equal((await saved("invented-awc-secondary")).media_attachment, undefined)
      await select(0)
      assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
      const edit = async value => {
        await press(page.getByRole("button", { name: "Edit", exact: true }))
        const field = page.getByLabel("Edit draft text", { exact: true })
        await field.focus(); await page.keyboard.press("ControlOrMeta+A"); await page.keyboard.insertText(value)
        assert.equal((await action(page.getByRole("button", { name: "Save", exact: true }))).ok, true)
        await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
      }
      await edit(original.text + " Invented edit.")
      assert.equal((await saved()).review_binding, undefined)
      assert.deepEqual((await saved()).media_attachment, attached.media_attachment)
      assert.equal((await action(panel.getByRole("button", { name: "Remove graphic", exact: true }))).ok, true)
      assert.equal((await saved()).media_attachment, undefined)
      assert.equal((await saved()).review_binding, undefined)
      await edit(original.text)
      await preview()
      assert.equal((await action(panel.getByRole("button", { name: "Attach graphic", exact: true }))).ok, true)
      await review()
      await command({ action: "clock", family: "awc", when: "expired" })
      const before = await control()
      const refused = await action(page.getByRole("button", { name: "Approve + Post", exact: true }))
      assert.equal(refused.ok, false); assert.equal(refused.code, "media_source_stale")
      assert.equal((await control()).writes, before.writes)
      assert.equal((await control()).dispatches.length, 0)
      await command({ action: "clock", family: "awc", when: "current" })
      assert.equal((await action(page.getByRole("button", { name: "Approve + Post", exact: true }))).ok, true)
      assert.equal((await control()).dispatches.length, 1)
      assert.equal((await control()).dispatches[0].inputs.mode, "manual_tweet")
      await select(1)
      await command({ action: "refuse_preview" })
      const writes = (await control()).writes
      await press(panel.getByRole("button", { name: "Preview graphic", exact: true }))
      await panel.getByRole("status").filter({ hasText: /saved source or display limits cannot support/i }).waitFor()
      assert.equal(await panel.locator(".graphic-preview-figure > img").count(), 0)
      assert.equal((await control()).writes, writes)
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      assert.deepEqual((await control()).refused, [])
      await page.screenshot({ path: `${config.screens}/${width}-awc-refusal.png`, fullPage: true })
      report.widths.push({ width, full_image_width: full.width, overflow, attachment_kind: attached.media_attachment.kind,
        delivery_bytes: Buffer.byteLength(delivery), edit_revoked_review: true, removal_revoked_review: true,
        draft_switch_discarded_preview: true, expired_approval_refused: true, recorded_dispatches: 1, passed: true })
      console.error(JSON.stringify({ scope: "invented_awc", width, stage: "complete" }))
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
