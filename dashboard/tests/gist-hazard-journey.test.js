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

// W01: the Hot10 family through the same owned app, actual handlers and genuine Python PNG.
test("owned Hot10 table: ten readable rows, states, attach, re-review, approval refusal, delivered snapshot at 1280/390/320", {
  skip: !process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG && "Run the new owned hazard journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_hot10_journey", actual_handlers: true, actual_python_png: true,
    mocked: ["Gist in-memory transport", "fixture-only preview HTTP boundary", "explicit invented clock", "recorded workflow dispatch",
      "seeded earlier delivery through the real sender with fake X SDK factories"],
    source_or_platform_calls: 0, publication_calls: 0, widths: [], steps: [], errors: [], console: [], refused_requests: [] }
  const hot10 = { queue: "Invented Hot 10 forecast", mixed: "Invented mixed-day Hot 10 forecast" }
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      page.on("pageerror", error => report.errors.push(String(error)))
      // Expected refusals (409 approval, 422 preview) log resource errors; they are recorded, not failures.
      page.on("console", message => { if (message.type() === "error") report.console.push(message.text()) })
      await context.route("**/*", route => {
        const url = new URL(route.request().url())
        if (url.origin !== config.origin) { report.refused_requests.push(url.href); return route.abort() }
        return route.continue()
      })
      const control = async () => (await (await page.request.get(`${config.origin}/api/fixture-control`)).json())
      const command = async data => assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data })).ok())
      const saved = async id => (await control()).state.drafts.find(d => d.id === id)
      await command({ action: "reset" })
      await command({ action: "clock", family: "hot10", when: "current" })
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const panel = page.getByRole("region", { name: "Saved-source graphic preview", exact: true })
      const press = async locator => { await locator.focus(); await page.keyboard.press("Enter") }
      const act = async locator => {
        const marker = page.locator("#journey-actions")
        const before = Number(await marker.getAttribute("data-count"))
        await press(locator)
        await page.waitForFunction(n => Number(document.querySelector("#journey-actions").dataset.count) > n, before)
        return { ok: (await marker.getAttribute("data-ok")) === "true", code: await marker.getAttribute("data-code") }
      }
      const select = async text => {
        await press(page.locator(".queue-item", { hasText: text }))
        await page.locator(".queue-item.selected", { hasText: text }).waitFor()
      }
      const state = async () => panel.locator("[data-graphic-state]").last().getAttribute("data-graphic-state")
      const preview = async () => {
        await press(panel.getByRole("button", { name: /^(Preview graphic|Rebuild preview)$/ }))
        await panel.locator(".graphic-preview-figure > img").waitFor()
        await page.waitForFunction(() => { const image = document.querySelector(".graphic-preview-figure > img"); return image?.complete && image.naturalWidth === 1200 && image.naturalHeight === 1500 })
      }
      // Rows are readable text at this width: ten list items, none wider than the panel.
      const rows = async () => page.evaluate(() => {
        const list = document.querySelector(".graphic-preview .hot10-preview-rows ol")
        const items = [...list.querySelectorAll("li")]
        return { count: items.length, overflow: items.some(li => li.scrollWidth > li.clientWidth + 1 || li.getBoundingClientRect().right > innerWidth + 1),
          minFont: Math.min(...items.map(li => parseFloat(getComputedStyle(li).fontSize))), text: list.innerText }
      })
      const row = { width }
      await select(hot10.queue)
      assert.equal(await state(), "none")
      await preview()
      const text = await panel.innerText()
      assert.match(text, /Forecast departure table \(sampled cities\)/); assert.match(text, /Image description sent to X/)
      assert.match(text, /Preview only:/); assert.equal(await state(), "preview")
      const listed = await rows()
      assert.equal(listed.count, 10); assert.equal(listed.overflow, false); assert.ok(listed.minFont >= 12, JSON.stringify(listed))
      assert.match(listed.text, /Riyadh, Saudi Arabia \+9\.2 °C vs normal/)
      await page.screenshot({ path: `${config.screens}/${width}-hot10-preview.png`, fullPage: true })

      // Attach: the image stays attached through a text edit, which needs a new joint review.
      const before = await saved("invented-hot10")
      assert.equal((await act(panel.getByRole("button", { name: "Attach graphic", exact: true }))).ok, true)
      await panel.getByRole("button", { name: "Remove graphic", exact: true }).waitFor()
      const attached = await saved("invented-hot10")
      assert.equal(attached.media_attachment.kind, "gist_hot10_bulletin_v1"); assert.equal(attached.content_revision, before.content_revision + 1)
      assert.ok(attached.hot10_rows.length === 10, "the legacy rows stay beside the family image")
      await preview()
      assert.equal(await state(), "needs_review")
      const review = async () => {
        await preview()
        const checkbox = panel.getByRole("checkbox", { name: /I checked the exact text, image, X image description and source details/ })
        const record = panel.getByRole("button", { name: "Record joint review", exact: true })
        assert.equal(await record.isDisabled(), true)
        await checkbox.focus(); await page.keyboard.press("Space")
        assert.equal(await checkbox.isChecked(), true); assert.equal(await record.isDisabled(), false)
        const result = await act(record)
        assert.equal(result.ok, true, JSON.stringify(result))
        await page.locator(".queue-item.selected", { hasText: "text and graphic reviewed" }).waitFor()
        await preview()
        assert.equal(await state(), "attached")
        return saved("invented-hot10")
      }
      await review()
      await press(page.getByRole("button", { name: "Edit", exact: true }))
      const field = page.getByLabel("Edit draft text", { exact: true })
      await field.focus(); await page.keyboard.press("ControlOrMeta+A"); await page.keyboard.insertText(attached.text + " Revised.")
      assert.equal((await act(page.getByRole("button", { name: "Save", exact: true }))).ok, true)
      await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
      const edited = await saved("invented-hot10")
      assert.equal(edited.review_binding, undefined); assert.deepEqual(edited.media_attachment, attached.media_attachment)
      await preview()
      assert.equal(await state(), "needs_review")
      await page.screenshot({ path: `${config.screens}/${width}-hot10-needs-review.png`, fullPage: true })

      // W09.1: link a quote to one exact ranked row through the real editor, keyboard only.
      await press(page.getByRole("button", { name: "Edit", exact: true }))
      const quoteField = page.getByLabel("Select a quote from the current draft", { exact: true })
      // Same keyboard selection as the owned claim-reference journey: the whole draft, then Tab to the button.
      await quoteField.focus(); await page.keyboard.press("ControlOrMeta+A")
      await page.keyboard.press("Tab")
      assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Use selected quote")
      await page.keyboard.press("Enter")
      const rankedRow = page.getByRole("checkbox", { name: /^ranking\[0\]: rank 1 · city / })
      await rankedRow.focus(); await page.keyboard.press("Space")
      assert.equal(await rankedRow.isChecked(), true)
      await press(page.getByRole("button", { name: "Add reference", exact: true }))
      assert.equal((await act(page.getByRole("button", { name: "Save", exact: true }))).ok, true)
      await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
      const linked = await saved("invented-hot10")
      assert.equal(linked.text, edited.text); assert.deepEqual(linked.media_attachment, attached.media_attachment)
      assert.deepEqual(linked.review_context.operator_claim_references.items.map(item => item.sources.map(source => source.pointer)),
        [[`/current_facts/${linked.review_context.two_bot.bundle.current_facts.findIndex(fact => fact.label === "ranking")}/value/0`]])
      await page.getByText(/^ranking\[0\]: rank 1 · city /).first().waitFor()
      report.steps.push({ width, step: "hot10_row_reference_saved" })
      await page.screenshot({ path: `${config.screens}/${width}-hot10-row-reference.png`, fullPage: true })
      const reviewed = await review()

      // A ranked local day over: approval refused without a write; current again: one dispatch.
      await command({ action: "clock", family: "hot10", when: "expired" })
      const writes = (await control()).writes
      const refused = await act(page.getByRole("button", { name: "Approve + Post", exact: true }))
      assert.equal(refused.ok, false); assert.equal(refused.code, "media_hot10_local_day_over")
      assert.equal((await control()).writes, writes); assert.equal((await control()).dispatches.length, 0)
      await command({ action: "clock", family: "hot10", when: "current" })
      assert.equal((await act(page.getByRole("button", { name: "Approve + Post", exact: true }))).ok, true)
      const approved = await saved("invented-hot10"), dispatches = (await control()).dispatches
      assert.equal(approved.status, "approved"); assert.equal(dispatches.length, 1)
      assert.deepEqual(dispatches[0].inputs, { mode: "manual_tweet", tweet_text: reviewed.text, draft_id: "invented-hot10", publish_intent_id: approved.publish_intent_id })

      // Long names, both signs and two local days stay readable.
      await command({ action: "clock", family: "hot10-mixed", when: "current" })
      await select(hot10.mixed)
      await preview()
      const mixed = await rows()
      assert.equal(mixed.count, 10); assert.equal(mixed.overflow, false)
      assert.match(mixed.text, /Santiago de los Caballeros, Dominican Republic \+9\.4 °C vs normal/)
      assert.match(mixed.text, /Kinshasa, DR Congo −8\.0 °C vs normal/); assert.match(mixed.text, /2026-10-30 \(Africa\/Lubumbashi\)/)
      assert.match(await panel.innerText(), /each row shows its own local day/)
      await page.screenshot({ path: `${config.screens}/${width}-hot10-mixed.png`, fullPage: true })

      // The earlier delivered post: its exact PNG, posted text and X description, read-only.
      const delivered = page.getByRole("region", { name: "Delivered graphics", exact: true })
      await delivered.getByText("X post invented-x-receipt-invented-hot10-delivered").waitFor()
      const inspect = delivered.getByRole("button", { name: "Inspect delivered graphic", exact: true })
      assert.equal(await inspect.isDisabled(), false)
      await press(inspect)
      await page.waitForFunction(() => {
        const region = document.querySelector(".delivered-graphics")
        return region?.querySelector(".graphic-preview-figure > img") || region?.querySelector("[role=status]")?.textContent.trim()
      })
      const status = (await delivered.locator("[role=status]").last().textContent()).trim()
      assert.ok(!status || /Rebuilding/.test(status), status)
      await delivered.locator(".graphic-preview-figure > img").waitFor()
      await page.waitForFunction(() => { const image = document.querySelector(".delivered-graphics .graphic-preview-figure > img"); return image?.complete && image.naturalWidth === 1200 })
      const shown = await delivered.innerText()
      const posted = (await control()).state.drafts.find(d => d.id === "invented-hot10-delivered")
      assert.ok(shown.includes(posted.text)); assert.ok(shown.includes(posted.media_attachment.image.png_sha256))
      assert.ok(shown.includes(posted.media_attachment.description.delivery_text.slice(0, 60)))
      await delivered.locator(".graphic-preview-figure").scrollIntoViewIfNeeded()
      await page.screenshot({ path: `${config.screens}/${width}-hot10-delivered.png`, fullPage: true })
      // Last: a refused preview of the mixed draft writes nothing and leaves its text reviewable.
      const mixedWrites = (await control()).writes
      await command({ action: "refuse_preview" })
      await press(panel.getByRole("button", { name: "Rebuild preview", exact: true }))
      await panel.getByRole("status").filter({ hasText: /saved source or display limits cannot support/i }).waitFor()
      assert.equal(await state(), "unavailable"); assert.match(await panel.innerText(), /the text draft is unchanged and can still be reviewed on its own/)
      assert.equal((await control()).writes, mixedWrites)
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      const final = await control()
      assert.deepEqual(final.refused, []); assert.ok(!JSON.stringify(final.state).includes("iVBORw0KGgo"))
      report.widths.push({ ...row, passed: true, writes: final.writes, previews: final.previews, overflow })
      await context.close()
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.refused_requests, [])
  } catch (error) {
    report.failure = String(error)
    for (const context of browser.contexts()) for (const page of context.pages()) {
      writeFileSync(`${config.screens}/hot10-failure.txt`, await page.locator("body").innerText())
      await page.screenshot({ path: `${config.screens}/hot10-failure.png`, fullPage: true })
    }
    throw error
  } finally {
    await browser.close()
    writeFileSync(config.result.replace(/\.json$/, "-hot10.json"), JSON.stringify(report, null, 2) + "\n", { flag: "wx" })
  }
})
