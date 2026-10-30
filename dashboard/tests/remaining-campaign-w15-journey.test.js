/** Owned invented-data browser journey for the W15 operator surfaces at 1280/390/320.
 * Run only through scripts/w15_feedback_journey.mjs (skipped otherwise). Actual
 * /api/post-feedback and /api/dashboard handlers over invented in-memory Gists; the coverage
 * assessment comes from the real match-coverage CLI on invented input via a fixture boundary.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

test("owned W15 revision feedback, post history lines and coverage match evidence at 1280/390/320", {
  skip: !process.env.THEHEAT_W15_JOURNEY_CONFIG && "Run the owned W15 journey launcher",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_W15_JOURNEY_CONFIG, "utf8"))
  const { chromium } = await import(pathToFileURL(config.playwright).href)
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  const report = { scope: "invented_w15_journey", actual_handlers: ["/api/post-feedback", "/api/dashboard"],
    fixture_boundaries: ["in-memory state and private feedback Gists", "workflow-run list (empty)",
      "coverage GET serves the real match-coverage assessment on invented input", "outcome join with supplied feedback + invented correction report"],
    source_or_platform_calls: 0, publication_calls: 0, widths: [], errors: [], console: [], refused_requests: [] }
  const auth = `Basic ${Buffer.from("fixture:invented").toString("base64")}`
  // Local `next start -H 127.0.0.1` builds request.url with host "localhost", so the unchanged
  // same-origin check in /api/post-feedback would refuse a 127.0.0.1 page origin (reported, not
  // changed). The browser therefore uses the same owned server through http://localhost:<port>.
  const origin = config.origin.replace("//127.0.0.1:", "//localhost:")
  report.browser_origin = origin
  let lastPage = null
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, extraHTTPHeaders: { Authorization: auth } })
      const page = await context.newPage()
      lastPage = page
      page.on("pageerror", error => report.errors.push(String(error)))
      page.on("console", message => { if (message.type() === "error") report.console.push(message.text()) })
      await context.route("**/*", route => {
        const url = new URL(route.request().url())
        if (url.origin !== origin && url.origin !== config.origin) { report.refused_requests.push(url.href); return route.abort() }
        return route.continue()
      })
      const control = async () => (await (await page.request.get(`${origin}/api/fixture-control`)).json())
      assert.ok((await page.request.post(`${origin}/api/fixture-control`, { data: { action: "reset" } })).ok())
      await page.goto(origin, { waitUntil: "networkidle" })
      const row = { width }

      // (1) Revision feedback on one exact draft version: graphic choice disabled without a graphic,
      // nothing pre-selected, save needs a tag, then the per-revision summary line.
      const section = page.getByRole("region", { name: "Feedback on drafts and posts" })
      await section.waitFor()
      await section.getByLabel("Version").selectOption("synthetic-draft")
      const form = section.locator("form.revision-feedback")
      await form.getByText(/^Draft revision 2 · no feedback yet$/).waitFor()
      assert.equal(await form.getByRole("radio", { name: "The graphic" }).isDisabled(), true)
      assert.equal(await form.getByRole("radio", { name: "The words" }).isChecked(), true)
      const save = form.getByRole("button", { name: "Save feedback" })
      assert.equal(await save.isDisabled(), true)
      for (const name of ["Concise", "Useful", "Confusing", "Looks incorrect"]) assert.equal(await form.getByRole("checkbox", { name }).isChecked(), false)
      for (const name of ["Concise", "Useful"]) { await form.getByRole("checkbox", { name }).focus(); await page.keyboard.press("Space") }
      await form.getByLabel("Why? (optional)").fill("Invented note: clear and short.")
      assert.equal(await save.isDisabled(), false)
      await save.focus(); await page.keyboard.press("Enter")
      await page.getByText("Feedback saved. The draft and publishing settings are unchanged.").waitFor()
      await section.getByLabel("Version").selectOption("synthetic-draft")
      await section.locator("form.revision-feedback").getByText(/^Draft revision 2 · 1 saved: concise 1, useful 1$/).waitFor()
      // A second exact version: the posted revision, tagged "Looks incorrect" with the keyboard.
      await section.getByLabel("Version").selectOption("synthetic-post")
      const postForm = section.locator("form.revision-feedback")
      await postForm.getByText(/^Posted revision 1 · no feedback yet$/).waitFor()
      await postForm.getByRole("checkbox", { name: "Looks incorrect" }).focus(); await page.keyboard.press("Space")
      await postForm.getByRole("button", { name: "Save feedback" }).focus(); await page.keyboard.press("Enter")
      await page.getByText("Feedback saved. The draft and publishing settings are unchanged.").waitFor()
      await section.getByLabel("Version").selectOption("synthetic-post")
      await section.locator("form.revision-feedback").getByText(/^Posted revision 1 · 1 saved: looks incorrect 1$/).waitFor()
      const archived = await control()
      assert.equal(archived.writes, 2); assert.equal(Object.keys(archived.archive).length, 2); assert.deepEqual(archived.refused, [])
      const records = Object.values(archived.archive).map(file => JSON.parse(file.content))
      const draftRecord = records.find(r => r.target.draft_id === "synthetic-draft")
      assert.equal(draftRecord.kind, "dashboard_revision_feedback"); assert.deepEqual(draftRecord.tags, ["concise", "useful"])
      assert.deepEqual(records.find(r => r.target.draft_id === "synthetic-post").tags, ["incorrect"])
      row.feedback_saved = true
      await page.screenshot({ path: `${config.screens}/${width}-feedback.png`, fullPage: true })

      // (2) Operations post history from the actual dashboard route (feedback not loaded there),
      // then the outcome join with the saved feedback and a review-only correction candidate.
      await page.getByRole("button", { name: "Refresh outcome views" }).click()
      const operations = page.getByRole("region", { name: "Operating status" })
      await operations.waitFor()
      const history = operations.locator("details", { hasText: "Retained post history" })
      await history.locator("summary").first().click()
      const opsText = await history.innerText()
      assert.match(opsText, /Retained text versions for this post: \d+\. Who edited them is not recorded here\./)
      assert.match(opsText, /Still needed to know more: [^\n]*a metric observation/)
      assert.match(opsText, /Feedback is shown in the feedback section; it is not loaded in this view\./)
      const joined = page.getByRole("region", { name: "Outcome view with supplied feedback and corrections" })
      await joined.locator("summary", { hasText: "Retained post history" }).click()
      await joined.getByText(/^Your feedback: /).waitFor()
      const joinedText = await joined.innerText()
      assert.match(joinedText, /Your feedback: 0 rating\(s\); tags incorrect 1\./)
      assert.match(joinedText, /Correction candidates for your review \(nothing is corrected or deleted automatically\):/)
      assert.match(joinedText, /“49\.1C” — value: Invented table shows 48\.7C\. \(retrieved 2026-10-18T00:00:00Z; uncertainty: Invented: provisional QC\.\)/)
      row.outcome_lines = true
      await page.screenshot({ path: `${config.screens}/${width}-outcomes.png`, fullPage: true })

      // (3) Coverage match evidence from the real match-coverage assessment.
      const coverage = page.getByRole("region", { name: "Coverage evidence" })
      await coverage.getByText("Matched production records").waitFor()
      const near = coverage.locator("details", { hasText: "No match; the closest records differ as shown" })
      await near.locator("summary").first().focus(); await page.keyboard.press("Enter")
      assert.match(await near.innerText(), /place differs/)
      const workflow = coverage.locator("details", { hasText: "Retained workflow evidence" }).first()
      await workflow.locator("summary").first().focus(); await page.keyboard.press("Enter")
      assert.match(await coverage.innerText(), /Draft saved/)
      assert.match(await coverage.innerText(), /invented fixture/)
      row.coverage_evidence = true
      await page.screenshot({ path: `${config.screens}/${width}-coverage.png`, fullPage: true })

      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
      assert.ok(overflow.page <= overflow.viewport + 1, JSON.stringify(overflow))
      const small = await page.evaluate(() => {
        const under = root => [...root.querySelectorAll("*")].filter(el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
          && el.getClientRects().length && parseFloat(getComputedStyle(el).fontSize) < 12).map(el => el.textContent.trim().slice(0, 40))
        // The W15 additions: revision feedback, the post-history details and the coverage match evidence.
        const w15 = [document.querySelector("section[aria-label='Feedback on drafts and posts']"),
          ...[...document.querySelectorAll("details.runtime-details")].filter(el => el.querySelector(":scope > summary")?.textContent === "Retained post history"),
          ...document.querySelectorAll("[aria-labelledby='coverage-evidence-title'] details")].filter(Boolean)
        return { w15: w15.flatMap(under), page: under(document.querySelector("main")).length }
      })
      row.text_under_12px = small
      assert.deepEqual(small.w15, [], "W15 additions keep text at 12px or larger")
      report.widths.push(row)
      await context.close()
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.refused_requests, [])
  } catch (error) {
    report.failure = String(error)
    if (lastPage) {
      writeFileSync(`${config.screens}/failure.txt`, await lastPage.locator("body").innerText().catch(() => "unavailable"))
      await lastPage.screenshot({ path: `${config.screens}/failure.png`, fullPage: true }).catch(() => {})
    }
    throw error
  } finally {
    await browser.close()
    writeFileSync(config.result, JSON.stringify(report, null, 2) + "\n", { flag: "wx" })
  }
})
