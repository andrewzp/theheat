// Explicit background-only renderer regression. All data below is INVENTED.
// Required explicit clean-caller environment (no discovery or defaults):
// THEHEAT_DIAGNOSIS_PYTHON=/absolute/locked/python
// THEHEAT_DIAGNOSIS_PLAYWRIGHT=/absolute/playwright/index.mjs
// THEHEAT_DIAGNOSIS_CHROMIUM=/absolute/headless/chromium
// node --test tests/private-diagnosis-browser.mjs
import { test } from "node:test"
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { createServer } from "node:http"
import { mkdtempSync, realpathSync, chmodSync } from "node:fs"
import { tmpdir } from "node:os"
import { isAbsolute, join } from "node:path"
import { fileURLToPath } from "node:url"

const root = fileURLToPath(new URL("../", import.meta.url))
const python = process.env.THEHEAT_DIAGNOSIS_PYTHON
const playwright = process.env.THEHEAT_DIAGNOSIS_PLAYWRIGHT
const executablePath = process.env.THEHEAT_DIAGNOSIS_CHROMIUM
for (const [name, value] of Object.entries({ THEHEAT_DIAGNOSIS_PYTHON: python,
  THEHEAT_DIAGNOSIS_PLAYWRIGHT: playwright, THEHEAT_DIAGNOSIS_CHROMIUM: executablePath }))
  assert.ok(typeof value === "string" && isAbsolute(value), `${name} must explicitly name an absolute path`)

function inventedPage() {
  const home = realpathSync(mkdtempSync(join(realpathSync(tmpdir()), "theheat-invented-d4-browser-")))
  chmodSync(home, 0o700)
  const code = [
    "import sys",
    `sys.path.insert(0, ${JSON.stringify(root)})`,
    "from src.evaluation.operator_diagnosis import render_html",
    "report = {'report_sha256': 'a' * 64, 'as_of': '2026-10-23T12:00:00+00:00',",
    " 'components': [{'component': 'archive', 'status': 'complete'}],",
    " 'overview': {'source': {'archives': 1}, 'checks': {'candidates': 1},",
    " 'spend': {'actual_cost_known': False, 'billed_totals': [{'net': '0.125', 'currency': 'USD'}]},",
    " 'preference': {'ratings': {'real_human_ratings_added': 0, 'synthetic_fixture_preferences_by_display_side': {'tie': 1}}},",
    " 'publication': {'engagement_lift': None, 'exclusions': {'stale_opinion_targets': 1}}},",
    " 'generations': [], 'unjoined_posts': [], 'limits': ['INVENTED renderer fixture; zero real human ratings.'],",
    " 'candidates': [{'anchor': 'c-invented', 'event_id': 'invented-event', 'scope_id': 'scope-' + '1' * 32,",
    " 'archive_status': 'complete', 'bundle_sha256': 'b' * 64, 'candidate_text_sha256': 'c' * 64,",
    " 'decision': 'accepted', 'calls': [], 'dispositions': [], 'publication': {'status': 'receipts_absent'},",
    " 'copy_review': {'in_pack': False}}]}",
    "sys.stdout.write(render_html(report))",
  ].join("\n")
  const result = spawnSync(python, ["-I", "-c", code], { encoding: "utf8", cwd: "/", timeout: 20000,
    maxBuffer: 1024 * 1024, env: { PATH: "/usr/bin:/bin", HOME: home, LC_ALL: "C", LANG: "C",
      PYTHON_DOTENV_DISABLED: "1", NETRC: "/dev/null", NO_PROXY: "*", no_proxy: "*" } })
  assert.equal(result.status, 0, "invented renderer process must succeed")
  return result.stdout
}

test("invented diagnosis renders useful qualified evidence at desktop and phone widths", { timeout: 60000 }, async () => {
  const pageHtml = inventedPage()
  const server = createServer((request, response) => {
    if (request.url !== "/invented-diagnosis") { response.writeHead(404).end(); return }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" }).end(pageHtml)
  })
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve))
  let browser
  try {
    const address = server.address()
    const url = `http://127.0.0.1:${address.port}/invented-diagnosis`
    const { chromium } = await import(playwright)
    browser = await chromium.launch({ headless: true, executablePath })
    for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
      const context = await browser.newContext({ viewport })
      try {
        const blocked = [], errors = []
        await context.route("**/*", route => route.request().url() === url ? route.continue()
          : (blocked.push(route.request().url()), route.abort()))
        const page = await context.newPage()
        page.on("pageerror", () => errors.push("pageerror"))
        page.on("console", message => { if (message.type() === "error") errors.push("console-error") })
        await page.goto(url)
        assert.equal(await page.locator("script, form, button, input, select, textarea").count(), 0)
        await page.getByRole("link", { name: "Candidates", exact: true }).focus()
        await page.keyboard.press("Enter")
        assert.equal(await page.evaluate(() => location.hash), "#candidates")
        const body = await page.locator("body").innerText()
        for (const expected of ["Promotion: HOLD", "INVENTED", "0.125", "actual_cost_known",
          "synthetic_fixture_preferences", "real_human_ratings_added", "stale_opinion_targets"])
          assert.ok(body.includes(expected), expected)
        const layout = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }))
        assert.equal(layout.width, viewport.width)
        assert.ok(layout.scroll <= viewport.width)
        assert.deepEqual(blocked, [])
        assert.deepEqual(errors, [])
      } finally { await context.close() }
    }
  } finally {
    if (browser) await browser.close()
    await new Promise(resolve => server.close(resolve))
  }
})
