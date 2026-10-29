import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

test("owned invented warning source inspection, edit, review and approval at1280/390/320", {
  skip: !process.env.THEHEAT_WARNING_JOURNEY_CONFIG && "Run the owned official-warning journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_WARNING_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_official_warning_journey", actual_handlers: true,
    mocked: ["model transports", "Gist in memory", "fixture clock", "workflow dispatch recorder"],
    source_model_platform_calls: 0, posts: 0, widths: [], errors: [], refused_requests: [] }
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      await context.route("**/*", route => {
        if (new URL(route.request().url()).origin !== config.origin) { report.refused_requests.push(route.request().url()); return route.abort() }
        return route.continue()
      })
      const page = await context.newPage()
      // Only the page's source clock is invented; timer/deadline clocks stay real.
      await page.addInitScript(() => { Date.now = () => Date.parse("2026-10-29T12:00:00.000Z") })
      page.on("pageerror", error => report.errors.push(String(error)))
      assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data: { action: "reset" } })).ok())
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const source = page.getByRole("region", { name: "Saved official warning", exact: true })
      await source.waitFor()
      assert.match(await source.innerText(), /Invented Warning Agency/)
      const expand = source.locator("summary")
      await expand.focus(); await page.keyboard.press("Enter")
      await source.getByText(/INVENTED official bulletin/).waitFor()
      assert.match(await source.innerText(), /does not authenticate/)
      const action = async button => {
        const marker = page.locator("#journey-actions"), before = Number(await marker.getAttribute("data-count"))
        await button.focus(); await page.keyboard.press("Enter")
        await page.waitForFunction(value => Number(document.querySelector("#journey-actions").dataset.count) > value, before)
      }
      await page.getByRole("button", { name: "Edit", exact: true }).focus(); await page.keyboard.press("Enter")
      const editor = page.getByRole("textbox", { name: "Edit draft text" })
      await editor.fill("Example Island faces possible dangerous winds tonight, Invented Warning Agency warns.")
      await action(page.getByRole("button", { name: "Save", exact: true }))
      assert.equal(await page.getByRole("button", { name: "Approve + Post", exact: true }).isEnabled(), false)
      const confirmation = page.getByRole("checkbox", { name: /checked this exact text/ })
      await confirmation.focus(); await page.keyboard.press("Space")
      await action(page.getByRole("button", { name: "Record human review", exact: true }))
      assert.equal(await page.getByRole("button", { name: "Approve + Post", exact: true }).isEnabled(), true)
      await page.screenshot({ path: `${config.screens}/${width}-reviewed-warning.png`, fullPage: true })
      await action(page.getByRole("button", { name: "Approve + Post", exact: true }))
      let state = await (await page.request.get(`${config.origin}/api/fixture-control`)).json()
      assert.equal(state.dispatches.length, 1)
      assert.equal(state.state.drafts[0].status, "approved")
      assert.deepEqual(state.refused, [])
      assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data: { action: "expire" } })).ok())
      await page.evaluate(() => { Date.now = () => Date.parse("2026-10-30T00:00:00.000Z") })
      await page.getByRole("button", { name: "Refresh invented fixture" }).click()
      await source.getByRole("status").waitFor()
      assert.match(await source.innerText(), /expired/)
      const dimensions = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth }))
      assert.ok(dimensions.document <= dimensions.viewport, JSON.stringify(dimensions))
      report.widths.push({ width, dimensions, dispatches: state.dispatches.length })
      await page.screenshot({ path: `${config.screens}/${width}-expired-warning.png`, fullPage: true })
      await context.close()
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.refused_requests, [])
    report.passed = true
  } finally {
    await browser.close()
    writeFileSync(config.result, JSON.stringify(report, null, 2) + "\n")
  }
})
