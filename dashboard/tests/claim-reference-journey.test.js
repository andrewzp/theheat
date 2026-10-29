import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

// This new opt-in journey owns a fresh background Chromium context and an
// invented server. The actual GET/POST, state-store and Workbench run; only
// Gist transport is mocked. Ordinary npm test never starts a browser/server.
test("owned actual-handler quote/fact journey at desktop, 390 and 320", {
  skip: !process.env.THEHEAT_CLAIM_JOURNEY_CONFIG && "Run the new owned claim-reference journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_CLAIM_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true, args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_claim_reference_journey", actual_handlers: true, mocked: ["Gist in-memory transport"], source_or_platform_calls: 0, publication_calls: 0, widths: [], errors: [], refused_requests: [] }
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      page.on("pageerror", error => report.errors.push(String(error)))
      await context.route("**/*", route => {
        if (new URL(route.request().url()).origin !== config.origin) { report.refused_requests.push(route.request().url()); return route.abort() }
        return route.continue()
      })
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const panel = page.getByRole("region", { name: "Operator-selected source references", exact: true }).first()
      const fixtureState = async () => (await (await page.request.get(`${config.origin}/api/fixture-control`)).json()).state
      const savedDraft = async () => (await fixtureState()).drafts.find(d => d.id === "invented-reference")
      // Each viewport removes any prior viewport's saved references through the
      // same actual edit action before creating a fresh keyboard connection.
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      const oldRemove = panel.getByRole("button", { name: /^Remove reference/ })
      while (await oldRemove.count()) await oldRemove.first().click()
      const quote = panel.getByLabel("Select a quote from the current draft")
      await quote.focus()
      await page.keyboard.press("ControlOrMeta+A")
      const selected = await quote.evaluate(element => ({ start: element.selectionStart, end: element.selectionEnd, length: element.value.length }))
      assert.deepEqual(selected, { start: 0, end: selected.length, length: selected.length })
      await page.keyboard.press("Tab")
      assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Use selected quote")
      await page.keyboard.press("Enter")
      await panel.getByRole("group", { name: "Connect source facts" }).waitFor()
      const boxes = panel.getByRole("checkbox")
      await boxes.nth(0).focus(); await page.keyboard.press("Space")
      await boxes.nth(1).focus(); await page.keyboard.press("Space")
      await panel.getByRole("button", { name: "Add reference", exact: true }).focus(); await page.keyboard.press("Enter")
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "Quote selection must fit the viewport")
      await page.screenshot({ path: `${config.screens}/${width}-selection.png`, fullPage: true })
      const before = await savedDraft()
      await page.getByRole("button", { name: "Save", exact: true }).focus(); await page.keyboard.press("Enter")
      await panel.getByText("Saved for this exact text and source snapshot.").waitFor()
      const added = await savedDraft()
      assert.equal(added.content_revision, before.content_revision + 1)
      assert.equal(added.review_context.operator_claim_references.items.length, 1)
      assert.equal(added.review_context.operator_claim_references.items[0].sources.length, 2)
      assert.equal(added.review_binding, undefined)
      assert.equal(added.approval_binding, undefined)
      await page.screenshot({ path: `${config.screens}/${width}-saved.png`, fullPage: true })
      await page.reload({ waitUntil: "networkidle" })
      await panel.getByText("Saved for this exact text and source snapshot.").waitFor()
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      await panel.getByRole("button", { name: "Change reference 1" }).click()
      await panel.getByRole("checkbox").nth(1).uncheck()
      await panel.getByRole("button", { name: "Update reference", exact: true }).click()
      await page.getByRole("button", { name: "Save", exact: true }).click()
      await panel.getByText("Saved for this exact text and source snapshot.").waitFor()
      assert.equal((await savedDraft()).review_context.operator_claim_references.items[0].sources.length, 1)
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      await panel.getByRole("button", { name: "Remove reference 1" }).click()
      await page.getByRole("button", { name: "Save", exact: true }).click()
      await panel.getByText(/No operator-selected references were saved/).waitFor()
      assert.equal((await savedDraft()).review_context.operator_claim_references, undefined)
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      const editor = page.getByLabel("Edit draft text", { exact: true }), originalText = await editor.inputValue()
      await editor.fill(originalText + ".")
      await page.getByRole("button", { name: "Save", exact: true }).click()
      await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      await editor.fill(originalText)
      await page.getByRole("button", { name: "Save", exact: true }).click()
      await panel.getByText(/No operator-selected references were saved/).waitFor()
      assert.equal((await savedDraft()).review_context.operator_claim_references, undefined)
      // A different draft cannot inherit the editor's selected quote/facts.
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      const queues = page.locator(".queue-item")
      await queues.nth(1).click()
      assert.equal(await page.getByLabel("Edit draft text", { exact: true }).count(), 0)
      await queues.nth(0).click()
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      await editor.fill(originalText + " Changed.")
      const control = await page.request.post(`${config.origin}/api/fixture-control`, { data: { action: "change_source" } })
      assert.ok(control.ok())
      await page.getByRole("button", { name: "Save", exact: true }).click()
      await page.getByRole("alert").filter({ hasText: "changed while you were editing" }).waitFor()
      assert.equal(await editor.inputValue(), originalText + " Changed.")
      assert.equal(await page.getByRole("button", { name: "Save", exact: true }).isDisabled(), true)
      assert.equal((await savedDraft()).text, originalText)
      await page.getByRole("button", { name: "Use my edit on this version", exact: true }).click()
      await page.getByRole("button", { name: "Save", exact: true }).click()
      await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
      assert.equal((await savedDraft()).review_context.operator_claim_references, undefined)
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      await page.screenshot({ path: `${config.screens}/${width}.png`, fullPage: true })
      const finalControl = await (await page.request.get(`${config.origin}/api/fixture-control`)).json()
      assert.deepEqual(finalControl.refused, [])
      report.widths.push({ width, passed: true, saved_revision: (await savedDraft()).content_revision, transport_writes: finalControl.writes, overflow })
      await context.close()
    }
    assert.deepEqual(report.errors, [])
    assert.deepEqual(report.refused_requests, [])
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
