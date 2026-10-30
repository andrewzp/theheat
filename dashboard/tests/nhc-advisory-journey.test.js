import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

test("owned invented NHC advisory inspection, edit, review, approval and deadline hold at 1280/390/320", {
  skip: !process.env.THEHEAT_NHC_JOURNEY_CONFIG && "Run the owned NHC advisory journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_NHC_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_nhc_advisory_journey", actual_handlers: true,
    mocked: ["Gist in memory", "fixture clock", "workflow dispatch recorder"],
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
      await page.addInitScript(() => { Date.now = () => Date.parse("2026-10-29T21:30:00.000Z") })
      page.on("pageerror", error => report.errors.push(String(error)))
      assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data: { action: "reset" } })).ok())
      await page.goto(config.origin, { waitUntil: "networkidle" })
      const source = page.getByRole("region", { name: "Saved NHC public advisory", exact: true })
      await source.waitFor()
      const card = await source.innerText()
      for (const value of [/National Hurricane Center \(NHC\)/, /Upstream expiry\s+Not stated by NHC \(unknown\)/,
        /Operator freshness deadline \(UTC\)\s+2026-10-29T21:56:00Z \(our recheck limit, not an NHC expiry\)/, /not a report that/])
        assert.match(card, value)
      const expand = source.locator("summary")
      await expand.focus(); await page.keyboard.press("Enter")
      await source.getByText(/INVENTED FIXTURE DEPRESSION INVENTA/).waitFor()
      assert.match(await source.innerText(), /does not authenticate/)
      const link = source.getByRole("link", { name: "Open the NHC advisory (opens in a new tab)" })
      assert.equal(await link.getAttribute("href"), "https://www.nhc.noaa.gov/text/MIATCPEP5.shtml")
      const action = async button => {
        const marker = page.locator("#journey-actions"), before = Number(await marker.getAttribute("data-count"))
        await button.focus(); await page.keyboard.press("Enter")
        await page.waitForFunction(value => Number(document.querySelector("#journey-actions").dataset.count) > value, before)
      }
      const approve = page.getByRole("button", { name: "Approve + Post", exact: true })
      assert.equal(await approve.isEnabled(), false)
      // An edit that drops the attribution is saved, then held for source review: no review control.
      await page.getByRole("button", { name: "Edit", exact: true }).focus(); await page.keyboard.press("Enter")
      await page.getByRole("textbox", { name: "Edit draft text" }).fill("Up to 3 inches of rain could flood Example Province tonight.")
      await action(page.getByRole("button", { name: "Save", exact: true }))
      await source.getByRole("status").waitFor()
      assert.match(await source.getByRole("status").innerText(), /attribute the forecast to NHC/)
      assert.equal(await page.getByRole("button", { name: "Record human review", exact: true }).count(), 0)
      await page.getByRole("button", { name: "Edit", exact: true }).focus(); await page.keyboard.press("Enter")
      await page.getByRole("textbox", { name: "Edit draft text" })
        .fill("Example Province could see up to 3 inches of rain and flash flooding tonight, NHC forecasts.")
      await action(page.getByRole("button", { name: "Save", exact: true }))
      assert.equal(await approve.isEnabled(), false)
      const confirmation = page.getByRole("checkbox", { name: /checked this exact text/ })
      await confirmation.focus(); await page.keyboard.press("Space")
      await action(page.getByRole("button", { name: "Record human review", exact: true }))
      assert.equal(await approve.isEnabled(), true)
      await page.screenshot({ path: `${config.screens}/${width}-reviewed-advisory.png`, fullPage: true })
      await action(approve)
      let state = await (await page.request.get(`${config.origin}/api/fixture-control`)).json()
      assert.equal(state.dispatches.length, 1)
      assert.equal(state.dispatches[0].inputs.mode, "manual_tweet")
      assert.equal(state.state.drafts[0].status, "approved")
      assert.equal(state.state.drafts[0].review_context.two_bot.bundle.raw_signal_dump.nhc_advisory.times.upstream_expiry, null)
      assert.deepEqual(state.refused, [])
      assert.ok((await page.request.post(`${config.origin}/api/fixture-control`, { data: { action: "deadline" } })).ok())
      await page.evaluate(() => { Date.now = () => Date.parse("2026-10-29T21:56:30.000Z") })
      await page.getByRole("button", { name: "Refresh invented fixture" }).click()
      await source.getByRole("status").waitFor()
      assert.match(await source.getByRole("status").innerText(), /operator freshness deadline passed \(this is not an NHC expiry\)/)
      const dimensions = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth }))
      assert.ok(dimensions.document <= dimensions.viewport, JSON.stringify(dimensions))
      state = await (await page.request.get(`${config.origin}/api/fixture-control`)).json()
      report.widths.push({ width, dimensions, dispatches: state.dispatches.length, writes: state.writes })
      await page.screenshot({ path: `${config.screens}/${width}-deadline-held-advisory.png`, fullPage: true })
      await context.close()
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.refused_requests, [])
    report.passed = true
  } finally {
    await browser.close()
    writeFileSync(config.result, JSON.stringify(report, null, 2) + "\n")
  }
})
