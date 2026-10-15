import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
import { commandRequestSHA, recoveryKey } from "../lib/local-command-recovery.js"

// An explicit, finite browser-unit profile mounts the actual Dashboard and its
// effects. Only API responses are invented; no authority, database or provider
// acceptance is inferred. Ordinary Node CI does not launch browser services.
test("mounted Dashboard retains completion fences until a successful current refresh", {
  skip: !process.env.THEHEAT_REFRESH_FENCE_TEST_CONFIG,
  timeout: 180000,
}, async t => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_REFRESH_FENCE_TEST_CONFIG, "utf8"))
  assert.equal(config.origin, "http://127.0.0.1:3271")
  assert.equal(config.scope, "invented_api_only_dashboard_lifecycle")
  const { chromium } = await import(pathToFileURL(config.playwright_entry).href)
  const origin = config.origin, actor = "invented-operator-a", note = "Invented retained edit; no weather claim."
  const evidence = { cases: [], requests: [], page_errors: [], console: [], failed_requests: [], denied: [] }
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    env: { PATH: "/usr/bin:/bin", TZ: "UTC", LANG: "en_US.UTF-8" },
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })
  let posts = 0, apiReads = 0
  const deadline = Date.now() + 150000
  async function until(predicate, message) {
    const end = Math.min(Date.now() + 10000, deadline)
    while (!await predicate()) {
      assert.ok(Date.now() < end, message)
      await new Promise(resolve => setTimeout(resolve, 20))
    }
  }
  const makeDraft = () => ({ id: "invented-draft", text: "Invented initial saved text.", type: "fire", status: "pending",
    created_at: new Date().toISOString(), local_preview: true, operator_role: "publisher", review_status: "needs_review",
    revision_identity: { content_revision: 1, decision_revision: 1, text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64) } })
  async function scenario(name, run, initialFailure = false) {
    assert.ok(Date.now() < deadline)
    const context = await browser.newContext({ httpCredentials: { username: "unit", password: "invented-unit", origin },
      serviceWorkers: "block", acceptDownloads: false, permissions: [] })
    const page = await context.newPage(); page.setDefaultTimeout(10000); page.setDefaultNavigationTimeout(20000)
    let draft = makeDraft(), subject = actor, local = true, completed = false, resultKind = "applied", command = null
    let holdNext = null, held = null, dashboardRequests = 0, mediaReads = 0, automationReads = 0, closed = false, expectedJSONError = null
    const commands = new Map(), failures = [], localRequests = [], injected = [], consoles = [], failedRequests = []
    const injectedRequests = new WeakSet()
    const recordFault = (route, kind) => {
      injectedRequests.add(route.request()); injected.push({ kind, url: route.request().url() })
    }
    const payload = () => ({ local_preview: local, operator_subject: subject, operator_role: subject === actor ? "publisher" : "viewer",
      state: {}, stateBackend: "invented_browser_unit", drafts: { drafts: [{ ...draft, operator_role: subject === actor ? "publisher" : "viewer" }] },
      candidates: [], config: {}, runs: [], sourceHealth: { sources: [] }, suppressions: { suppressions: [] } })
    const fulfill = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
    page.on("pageerror", error => evidence.page_errors.push({ name, error: String(error) }))
    page.on("console", message => {
      if (["warning", "error"].includes(message.type())) {
        const row = { name, type: message.type(), text: message.text(), url: message.location().url }
        consoles.push(row); evidence.console.push(row)
      }
    })
    page.on("requestfailed", request => {
      const row = { name, at: new Date().toISOString(), url: request.url(), method: request.method(),
        error: request.failure()?.errorText, exact_injected_request: injectedRequests.has(request) }
      failedRequests.push(row); evidence.failed_requests.push(row)
    })
    await context.routeWebSocket(/.*/, ws => {
      if (new URL(ws.url()).origin === "ws://127.0.0.1:3271") ws.connectToServer()
      else { evidence.denied.push(ws.url()); ws.close() }
    })
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== origin) { evidence.denied.push(request.url()); await route.abort("blockedbyclient"); return }
      if (!url.pathname.startsWith("/api/")) { await route.continue(); return }
      const row = { name, at: new Date().toISOString(), path: url.pathname, method: request.method() }
      evidence.requests.push(row); localRequests.push(row)
      try {
        if (request.method() === "POST") {
          assert.ok(++posts <= 11, "fixed invented mutation attempt cap")
          assert.ok(["/api/drafts", "/api/local-command-recovery"].includes(url.pathname))
          if (url.pathname === "/api/local-command-recovery") {
            assert.equal(request.postDataJSON().action, "abandon_submission")
            assert.equal(url.searchParams.get("commandId"), command.command_id)
          } else {
            command = request.postDataJSON(); assert.equal(command.action, "edit_revision")
            assert.ok(!commands.has(command.command_id)); commands.set(command.command_id, structuredClone(command))
            return await fulfill(route, { status: "pending", receipt: { command_id: command.command_id } }, 202)
          }
        } else { assert.equal(request.method(), "GET"); assert.ok(++apiReads <= 150, "fixed passive API read cap") }
        if (url.pathname === "/api/dashboard") {
          dashboardRequests++
          if (initialFailure) { recordFault(route, "initial-http"); return await fulfill(route, { error: "invented initial dashboard outage" }, 503) }
          if (holdNext) {
            assert.equal(held, null); held = route; holdNext = null
            return
          }
          return await fulfill(route, payload())
        }
        if (url.pathname === "/api/automation") { automationReads++; return await fulfill(route, { automation: "invented passive status" }) }
        if (url.pathname === "/api/generate") return await fulfill(route, { enabled: false, briefs: [] })
        if (url.pathname === "/api/editor-media") {
          mediaReads++
          return await fulfill(route, { draft_id: draft.id, target: { draft_id: draft.id, ...draft.revision_identity },
            publication_approved: false, local_preview: true, status: "unavailable", code: "editor_media_unavailable" })
        }
        assert.ok(["/api/drafts", "/api/local-command-recovery"].includes(url.pathname), "unexpected API route")
        const current = commands.get(url.searchParams.get("commandId")); assert.ok(current)
        const receipt = { command_id: current.command_id }, reference = { original_action: current.action, request_sha256: await commandRequestSHA(current) }
        return await fulfill(route, { status: completed ? "completed" : "pending", receipt, recoverable_command: current,
          submission_reference: reference, result: completed ? { command_id: current.command_id, actor_subject: actor,
            status: resultKind === "abandoned" ? "unchanged" : resultKind,
            ...(resultKind === "abandoned" ? { code: "submission_abandoned" } : {}), message: "Invented rejected edit." } : null })
      } catch (error) { failures.push(String(error)); await route.abort("failed").catch(() => {}) }
    })
    const panel = () => page.locator('.card.full[role="status"]').filter({ has: page.locator("strong").filter({ hasText: /^Invented local preview$/ }) })
    const stored = () => page.evaluate(key => sessionStorage.getItem(key), recoveryKey(origin, actor))
    async function settle() { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))) }
    async function submit(text = note) {
      await page.getByRole("button", { name: "Edit", exact: true }).click()
      await page.locator(".draft-edit-area").fill(text)
      await page.getByRole("button", { name: "Save", exact: true }).click()
      await panel().getByText(/Accepted and waiting/).waitFor()
      assert.ok(await stored()); assert.equal(await page.locator(".draft-edit-area").inputValue(), text)
      assert.equal(await page.locator(".draft-edit-area").isDisabled(), true)
      return structuredClone(command)
    }
    async function begin(kind = "applied") {
      completed = true; resultKind = kind; holdNext = true
      await panel().getByRole("button", { name: kind === "abandoned" ? "Resolve missing submission" : "Check result", exact: true }).click()
      await until(() => !!held, "command-result refresh did not reach held response")
      await settle()
    }
    async function release(mode = "success") {
      assert.ok(held); const route = held; held = null
      if (mode !== "success") recordFault(route, mode)
      if (mode === "network") await route.abort("failed")
      else if (mode === "http") await fulfill(route, { error: "invented completion dashboard outage" }, 503)
      else if (mode === "json") {
        expectedJSONError = await page.evaluate(() => {
          try { JSON.parse("{malformed") } catch (error) { return String(error) }
        })
        await route.fulfill({ status: 200, contentType: "application/json", body: "{malformed" })
      }
      else await fulfill(route, payload())
    }
    try {
      await page.goto(origin)
      if (!initialFailure) {
        await page.locator(".tabs").getByRole("button", { name: /^Workbench/ }).click()
        await page.getByText("Graphic unavailable for this saved revision. editor media unavailable", { exact: true }).waitFor()
      }
      await run({ page, panel, stored, submit, begin, release, settle, payload, fulfill, commands, localRequests,
        mediaReads: () => mediaReads, automationReads: () => automationReads,
        setSubject: value => { subject = value }, setLocal: value => { local = value },
        setDraft: value => { draft = { ...draft, ...value } },
        makePending: () => { completed = false },
        assertHeld: async (before, text = note) => {
          assert.equal(await stored(), before); assert.equal(await page.locator(".draft-edit-area").inputValue(), text)
          assert.equal(await page.locator(".draft-edit-area").isDisabled(), true)
          assert.equal(await panel().getByRole("button", { name: "Check result", exact: true }).count(), 1)
        } })
      await settle()
      await context.close(); closed = true
      for (const row of failedRequests) {
        if (name === "network" && row.exact_injected_request && row.error === "net::ERR_FAILED") row.classification = "exact_deliberate_transport_fault"
        else if (row.method === "GET" && new URL(row.url).pathname === "/api/editor-media" && row.error === "net::ERR_ABORTED") {
          // This unit deliberately edits/switches with actual AbortController
          // cleanup active. Keep these observations; they do not establish a
          // clean-network result or adjudicate the prior recovery case.
          row.classification = "retained_media_cancellation_outside_this_unit_acceptance"
        } else assert.fail(`Unrelated failed request: ${JSON.stringify(row)}`)
      }
      const counts = new Map()
      for (const row of consoles) {
        const fault = injected.find(item => item.url === row.url)
        let kind
        if (row.type === "error" && fault && ["http", "initial-http"].includes(fault.kind) &&
          row.text === "Failed to load resource: the server responded with a status of 503 (Service Unavailable)") kind = "http-resource"
        else if (row.type === "error" && fault?.kind === "network" && row.text === "Failed to load resource: net::ERR_FAILED") kind = "network-resource"
        else if (row.type === "error" && name === "http" && row.text.startsWith("Error: invented completion dashboard outage")) kind = "http-handler"
        else if (row.type === "error" && initialFailure && row.text.startsWith("Error: invented initial dashboard outage")) kind = "initial-handler"
        else if (row.type === "error" && name === "network" && row.text.startsWith("TypeError: Failed to fetch")) kind = "network-handler"
        else if (row.type === "error" && name === "json" && expectedJSONError && row.text.startsWith(expectedJSONError)) kind = "json-handler"
        else assert.fail(`Unrelated console event: ${JSON.stringify(row)}`)
        counts.set(kind, (counts.get(kind) || 0) + 1)
        assert.ok(counts.get(kind) <= injected.length, "console events exceed exact injected fault count")
        row.classification = kind
      }
      assert.ok(injected.length <= (initialFailure ? 3 : 1))
      assert.deepEqual(failures, []); evidence.cases.push({ name, passed: true, dashboardRequests, mediaReads, automationReads, injected })
    } finally {
      if (held) await held.abort("failed").catch(() => {})
      if (!closed) await context.close()
    }
  }
  try {
    await t.test("delayed refresh holds original reference, edit and media fence; success clears once", async () => scenario("delayed-success", async h => {
      const sent = await h.submit(), before = await h.stored(), media = h.mediaReads()
      await h.begin(); await h.assertHeld(before); assert.equal(h.mediaReads(), media)
      h.setDraft({ text: note, revision_identity: { ...h.payload().drafts.drafts[0].revision_identity, content_revision: 2, text_sha256: "c".repeat(64) } })
      await h.release(); await until(async () => await h.stored() === null, "successful refreshed command reference retained")
      assert.equal(await h.page.locator(".draft-edit-area").count(), 0)
      assert.equal(await h.page.locator(".draft-text").innerText(), note)
      assert.deepEqual(h.commands.get(sent.command_id), sent); assert.equal(h.commands.size, 1)
    }))
    for (const mode of ["http", "json", "network"]) await t.test(`${mode} refresh failure retains exact original request and unsaved edit`, async () => scenario(mode, async h => {
      const sent = await h.submit(), before = await h.stored(), media = h.mediaReads()
      await h.begin(); await h.assertHeld(before); await h.release(mode)
      await h.panel().getByText(/dashboard could not be refreshed/).waitFor()
      await h.assertHeld(before); assert.equal(h.mediaReads(), media)
      assert.deepEqual(h.commands.get(sent.command_id), sent); assert.equal(h.commands.size, 1)
      assert.equal(h.localRequests.filter(r => r.method === "POST").length, 1)
    }))
    await t.test("returned operator change cannot complete the old actor before identity effects settle", async () => scenario("actor-change", async h => {
      await h.submit(); const before = await h.stored(); await h.begin(); await h.assertHeld(before)
      h.setSubject("invented-operator-b"); await h.release()
      await until(async () => await h.panel().getByRole("button", { name: "Check result", exact: true }).count() === 0, "new actor fence absent")
      await h.settle(); assert.equal(await h.stored(), before)
      assert.equal(h.commands.size, 1)
    }))
    await t.test("late completion cannot clear a newer same-actor command", async () => scenario("new-command-race", async h => {
      const first = await h.submit(); await h.begin()
      // A second explicit status read completes the same accepted command while
      // the first read's refresh is delayed. It performs no mutation/resend.
      await h.panel().getByRole("button", { name: "Check result", exact: true }).click()
      await until(async () => await h.stored() === null, "second current status read did not complete")
      h.makePending(); const second = await h.submit("Second invented edit; retain this request.")
      const before = await h.stored(); assert.notEqual(second.command_id, first.command_id)
      await h.release(); await h.settle()
      await h.assertHeld(before, "Second invented edit; retain this request.")
      assert.deepEqual(h.commands.get(second.command_id), second); assert.equal(h.commands.size, 2)
    }))
    for (const kind of ["rejected", "abandoned"]) await t.test(`${kind} result preserves the edit after successful refresh`, async () => scenario(kind, async h => {
      await h.submit(); const before = await h.stored(); await h.begin(kind); await h.assertHeld(before)
      await h.release(); await until(async () => await h.stored() === null, "resolved reference not cleared")
      assert.equal(await h.page.locator(".draft-edit-area").inputValue(), note)
      assert.equal(await h.page.locator(".draft-edit-area").isDisabled(), false)
      assert.equal(h.commands.size, 1)
    }))
    await t.test("returned nonlocal dashboard cannot clear a local command", async () => scenario("preview-change", async h => {
      await h.submit(); const before = await h.stored(); await h.begin(); h.setLocal(false); await h.release()
      await until(async () => await h.panel().count() === 0, "nonlocal dashboard not rendered")
      await h.settle(); assert.equal(await h.stored(), before)
    }))
    await t.test("independent automation read still runs after initial dashboard failure", async () => scenario("automation-after-failure", async h => {
      await until(() => h.automationReads() > 0, "independent automation read suppressed")
      assert.equal(h.localRequests.filter(r => r.method === "POST").length, 0)
    }, true))
    assert.equal(posts, 11); assert.equal(evidence.cases.length, 10)
    assert.deepEqual(evidence.page_errors, []); assert.deepEqual(evidence.denied, [])
  } finally {
    await browser.close()
    writeFileSync(config.result, JSON.stringify({ ...evidence, posts, apiReads, SDK_calls: 0, database_calls: 0,
      scope: config.scope, authority_acceptance: false, whole_recovery_case_acceptance: false }, null, 2) + "\n", { flag: "wx" })
  }
})
