/** Read-only invented-data view scope; no graphic/send cases are replayed. */
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

test("retained airport source facts are readable by keyboard at desktop and phone widths", {
  skip: !process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG && "Run the explicit source-facts-only owned journey",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_GIST_HAZARD_JOURNEY_CONFIG, "utf8"))
  assert.deepEqual(config.families, ["awc"])
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_awc_source_facts_only", widths: [], errors: [], refused_requests: [], writes: [] }
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      page.on("pageerror", error => report.errors.push(String(error)))
      await context.route("**/*", route => {
        const request = route.request(), url = new URL(request.url())
        if (url.origin !== config.origin) { report.refused_requests.push(url.href); return route.abort() }
        if (request.method() !== "GET") report.writes.push({ path: url.pathname, method: request.method() })
        return route.continue()
      })
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const panel = page.getByRole("region", { name: "Claims and saved source evidence", exact: true })
      const summary = panel.locator("summary").filter({ hasText: /^Saved source facts · 15$/ })
      await summary.waitFor()
      await summary.focus(); await page.keyboard.press("Enter")
      assert.equal(await panel.locator("details.claim-source").getAttribute("open"), "")
      const text = await panel.innerText()
      for (const value of ["North Test Arpt (TAAA), Norway (NO)", "South Test Arpt (TBBB), Chile (CL)",
        "-20 °C", "45 °C", "2026-11-15T12:00:00Z", "Source capture (UTC)",
        "not per-claim citations or a new source check", "does not run checks, record a review or authorize publication"])
        assert.ok(text.includes(value), value)
      assert.equal(await panel.locator("a").count(), 0)
      assert.ok(!text.includes("source facts are incomplete"))
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      await panel.screenshot({ path: `${config.screens}/${width}-awc-source-facts.png` })
      await page.getByRole("button", { name: "Edit", exact: true }).focus(); await page.keyboard.press("Enter")
      await page.getByLabel("Edit draft text", { exact: true }).fill("Invented unsaved local edit.")
      assert.match(await panel.innerText(), /Editing in progress\. Saved model claims are hidden/)
      await page.getByRole("button", { name: "Cancel", exact: true }).focus(); await page.keyboard.press("Enter")
      assert.ok(!(await panel.innerText()).includes("Editing in progress"))
      report.widths.push({ width, overflow, passed: true })
      await context.close()
    }
    assert.deepEqual(report.errors, [])
    assert.deepEqual(report.refused_requests, [])
    assert.deepEqual(report.writes, [])
    report.passed = true
  } finally {
    await browser.close()
    writeFileSync(config.result, JSON.stringify(report, null, 2) + "\n", { flag: "wx" })
  }
})
