import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

// New, opt-in invented-data scope. Never opens a personal profile or reruns an
// old browser case. Ordinary npm test records this journey as unperformed.
test("owned reference selection + real PNG joint-review invalidation UI at 1280/390/320", {
  skip: !process.env.THEHEAT_GIST_TEMPERATURE_JOURNEY_CONFIG && "Run the new owned temperature journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_GIST_TEMPERATURE_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_gist_temperature_journey", actual_handlers: true, actual_python_png: true,
    mocked: ["Gist in-memory transport", "fixture-only preview HTTP boundary"], source_or_platform_calls: 0,
    publication_calls: 0, widths: [], errors: [], refused_requests: [] }
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
      const saved = async () => (await control()).state.drafts.find(d => d.id === "invented-station")
      assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data: { action: "reset" } })).ok())
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const panel = page.getByRole("region", { name: "Saved-source graphic preview", exact: true })
      const press = async locator => { await locator.focus(); await page.keyboard.press("Enter") }
      const preview = async () => {
        const button = panel.getByRole("button", { name: /^(Preview graphic|Rebuild preview)$/ })
        await press(button)
        await panel.locator("img").waitFor()
        await page.waitForFunction(() => { const image = document.querySelector(".graphic-preview img"); return image?.complete && image.naturalWidth === 1200 && image.naturalHeight === 1500 })
      }
      // The composed union's saved legacy GHCN type must expose its actual facts.
      // Connect the exact current quote to the observed reading with the keyboard.
      const references = page.getByRole("region", { name: "Operator-selected source references", exact: true }).first()
      const initial = await saved()
      const factIndex = initial.review_context.two_bot.bundle.current_facts.findIndex(fact => fact.label === "today_temp_c")
      assert.ok(factIndex >= 0)
      await press(page.getByRole("button", { name: "Edit", exact: true }))
      const quote = references.getByLabel("Select a quote from the current draft")
      await quote.focus(); await page.keyboard.press("ControlOrMeta+A")
      const selectedQuote = await quote.evaluate(element => ({ start: element.selectionStart, end: element.selectionEnd, text: element.value }))
      assert.deepEqual(selectedQuote, { start: 0, end: initial.text.length, text: initial.text })
      await page.keyboard.press("Tab")
      assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Use selected quote")
      await page.keyboard.press("Enter")
      const fact = references.getByRole("checkbox", { name: /today temp c: 42\.2/ })
      await fact.focus(); await page.keyboard.press("Space")
      assert.equal(await fact.isChecked(), true)
      await press(references.getByRole("button", { name: "Add reference", exact: true }))
      await press(page.getByRole("button", { name: "Save", exact: true }))
      await references.getByText("Saved for this exact text and source snapshot.", { exact: true }).waitFor()
      const referenceSaved = await saved(), referenceEnvelope = referenceSaved.review_context.operator_claim_references
      assert.equal(referenceSaved.content_revision, initial.content_revision + 1)
      assert.equal(referenceSaved.text, initial.text)
      assert.equal(referenceEnvelope.items.length, 1)
      assert.equal(referenceEnvelope.items[0].claim.text, initial.text)
      assert.equal(referenceEnvelope.items[0].sources[0].pointer, `/current_facts/${factIndex}`)
      assert.equal(referenceSaved.review_binding, undefined)
      assert.equal(referenceSaved.approval_binding, undefined)
      await preview()
      assert.match(await panel.innerText(), /Full graphic description/)
      assert.match(await panel.innerText(), /reporting interval and timezone unknown/)
      await page.screenshot({ path: `${config.screens}/${width}-preview.png`, fullPage: true })
      const before = await saved()
      await press(panel.getByRole("button", { name: "Attach graphic", exact: true }))
      await page.locator(".draft-feedback").last().waitFor()
      assert.doesNotMatch(await page.locator(".draft-feedback").last().getAttribute("class"), /error/, await page.locator(".draft-feedback").last().innerText())
      await panel.getByRole("button", { name: "Remove graphic", exact: true }).waitFor()
      const attached = await saved()
      assert.equal(attached.content_revision, before.content_revision + 1)
      assert.equal(attached.media_attachment.kind, "gist_temperature_comparator_v1")
      assert.equal(attached.review_binding, undefined)
      await preview()
      const checkbox = panel.getByRole("checkbox", { name: /I checked the exact text, image and full graphic description/ })
      const review = panel.getByRole("button", { name: "Record joint review", exact: true })
      assert.equal(await review.isDisabled(), true)
      await checkbox.focus(); await page.keyboard.press("Space")
      assert.equal(await review.isDisabled(), false)
      await press(review)
      await page.getByText("text and graphic reviewed", { exact: true }).first().waitFor()
      const reviewed = await saved()
      assert.equal(reviewed.review_binding.kind, "human_media")
      assert.equal(reviewed.review_binding.media_sha256.length, 64)
      assert.deepEqual(reviewed.media_attachment, attached.media_attachment)
      assert.equal(reviewed.approval_binding, undefined)
      assert.deepEqual(reviewed.review_context.operator_claim_references, referenceEnvelope)
      await preview()
      await page.screenshot({ path: `${config.screens}/${width}-reviewed.png`, fullPage: true })
      // A references-only edit must revoke the existing joint review even though
      // the exact tweet, retained source and reviewed image remain unchanged.
      await press(page.getByRole("button", { name: "Edit", exact: true }))
      await press(references.getByRole("button", { name: "Remove reference 1", exact: true }))
      await press(page.getByRole("button", { name: "Save", exact: true }))
      await references.getByText(/No operator-selected references were saved/).waitFor()
      const referenceRemoved = await saved()
      assert.equal(referenceRemoved.content_revision, reviewed.content_revision + 1)
      assert.equal(referenceRemoved.text, reviewed.text)
      assert.deepEqual(referenceRemoved.media_attachment, reviewed.media_attachment)
      assert.equal(referenceRemoved.review_context.operator_claim_references, undefined)
      assert.equal(referenceRemoved.review_binding, undefined)
      assert.equal(referenceRemoved.approval_binding, undefined)
      assert.ok(referenceRemoved.revision_history.some(row => row.content_revision === reviewed.content_revision
        && row.review_binding?.kind === "human_media" && row.review_context?.operator_claim_references?.items[0].claim.text === initial.text))
      await press(page.getByRole("button", { name: "Edit", exact: true }))
      const editor = page.getByLabel("Edit draft text", { exact: true })
      const edited = reviewed.text + " Changed."
      await editor.focus(); await page.keyboard.press("ControlOrMeta+A"); await page.keyboard.insertText(edited)
      await press(page.getByRole("button", { name: "Save", exact: true }))
      await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
      const changed = await saved()
      assert.equal(changed.text, edited); assert.equal(changed.review_binding, undefined)
      assert.deepEqual(changed.media_attachment, reviewed.media_attachment)
      assert.ok(changed.revision_history.some(row => row.review_binding?.kind === "human_media" && row.text === reviewed.text))
      await press(panel.getByRole("button", { name: "Remove graphic", exact: true }))
      await page.waitForFunction(() => !document.querySelector(".temperature-media-controls button"))
      const removed = await saved()
      assert.equal(removed.media_attachment, undefined)
      assert.ok(removed.revision_history.some(row => row.media_attachment?.png_sha256 === attached.media_attachment.png_sha256))
      await preview()
      const switchDraft = async () => {
        const previous = await page.locator(".queue-item.selected").innerText()
        await press(page.locator(".queue-item:not(.selected)"))
        await page.waitForFunction(previous => document.querySelector(".queue-item.selected")?.innerText !== previous, previous)
        await panel.locator("img").waitFor({ state: "detached" })
        assert.equal(await panel.locator("img").count(), 0, "draft switch must discard old image")
      }
      await switchDraft()
      await switchDraft()
      const writes = (await control()).writes
      assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data: { action: "refuse_preview" } })).ok())
      await press(panel.getByRole("button", { name: "Preview graphic", exact: true }))
      await panel.getByRole("status").filter({ hasText: /saved source or display limits cannot support/i }).waitFor()
      assert.equal(await panel.locator("img").count(), 0)
      assert.equal((await control()).writes, writes)
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      const final = await control()
      assert.deepEqual(final.refused, [])
      assert.equal(final.state.drafts.some(d => d.status === "approved" || d.publish_intent_id), false)
      await page.screenshot({ path: `${config.screens}/${width}-refusal.png`, fullPage: true })
      report.widths.push({ width, passed: true, writes: final.writes, previews: final.previews, overflow,
        operator_reference_selected: true, selected_fact_pointer: `/current_facts/${factIndex}`,
        references_only_edit_invalidated_joint_review: true,
        attachment_png_sha256: attached.media_attachment.png_sha256, attachment_alt_sha256: attached.media_attachment.alt_sha256 })
      await context.close()
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.refused_requests, [])
  } catch (error) {
    report.failure = String(error)
    for (const context of browser.contexts()) for (const page of context.pages()) {
      report.last_control = await (await page.request.get(`${config.origin}/api/fixture-control`)).json()
    }
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
