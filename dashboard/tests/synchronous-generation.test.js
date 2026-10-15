import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createServer } from "node:http"
import { Readable } from "node:stream"
import { runFixtureWorker } from "../test-support/fixture-worker.js"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import SourcedGeneration, { generationCommand, WriterUsage } from "../app/components/SourcedGeneration.js"
import { createCandidateCommand, createDraftCommand, localCommandEndpoint } from "../lib/draft-command-request.js"

test("actual source API -> separate synchronous/check workers -> admitted draft -> edit", { skip: !process.env.THEHEAT_SYNC_GENERATION_TEST_CONFIG }, async () => {
  const configFile = process.env.THEHEAT_SYNC_GENERATION_TEST_CONFIG
  const config = JSON.parse(readFileSync(configFile, "utf8"))
  const saved = { ...process.env }
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = config.endpoint
  const generate = await import("../app/api/generate/route.js")
  const drafts = await import("../app/api/drafts/route.js")
  const dashboard = await import("../app/api/dashboard/route.js")
  const actualFetch = globalThis.fetch
  globalThis.fetch = (url, options) => {
    assert.ok([config.endpoint, config.origin].includes(new URL(url).origin), "External network refused")
    return actualFetch(url, options)
  }
  const server = createServer(async (incoming, outgoing) => {
    try {
      const request = new Request(`${config.origin}${incoming.url}`, { method: incoming.method, headers: incoming.headers,
        ...(incoming.method === "POST" ? { body: Readable.toWeb(incoming), duplex: "half" } : {}) })
      const route = incoming.url.startsWith("/api/generate") ? generate : incoming.url.startsWith("/api/dashboard") ? dashboard : drafts
      const response = await route[incoming.method](request)
      outgoing.writeHead(response.status, Object.fromEntries(response.headers))
      outgoing.end(Buffer.from(await response.arrayBuffer()))
    } catch (error) { outgoing.writeHead(500); outgoing.end(JSON.stringify({ error: error.message })) }
  })
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(Number(new URL(config.origin).port), "127.0.0.1", resolve) })
  async function request(path, command, role = "editor") {
    console.error("fixture request", path, command?.action || "read", role)
    const response = await actualFetch(config.origin + path, { method: command ? "POST" : "GET",
      headers: { Origin: config.origin, Authorization: `Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`, "Content-Type": "application/json" },
      ...(command ? { body: JSON.stringify(command) } : {}) })
    return { status: response.status, body: await response.json() }
  }
  async function worker(operation, command) {
    console.error("fixture worker", operation)
    const result = await runFixtureWorker(config.python, [config.child, configFile, operation, command], { cwd: config.root,
      env: { PATH: process.env.PATH, PYTHONPATH: config.root, no_proxy: "*" }, encoding: "utf8", timeout: 30000 })
    assert.equal(result.status, 0, result.stdout + result.stderr)
    return JSON.parse(result.stdout)
  }
  try {
    assert.equal((await request("/api/generate", { prompt: "Invent a record" })).status, 400)
    const view = await request("/api/generate")
    assert.equal(view.status, 200, JSON.stringify(view.body))
    const start = generationCommand(view.body.briefs[0])
    assert.equal((await request("/api/generate", start, "viewer")).status, 403)
    const accepted = await request("/api/generate", start)
    assert.equal(accepted.status, 202, JSON.stringify(accepted.body))
    assert.deepEqual((await request("/api/generate", start)).body, accepted.body)
    assert.equal((await worker("consume", start.command_id)).status, "applied")
    assert.equal(view.body.briefs[0].execution_mode, "synchronous")
    assert.equal(localCommandEndpoint(start), "/api/generate")
    assert.equal((await worker("write", start.command_id)).outcome, "response_retained")
    assert.equal((await worker("write", start.command_id)).outcome, "reconciliation_required")
    const usage = (await request("/api/generate")).body.briefs[0].writer_usage
    assert.equal(usage.counts.input_tokens, 11)
    assert.equal(usage.cost_usd, null)
    assert.equal((await worker("remove_source", start.command_id)).changed, true)
    assert.deepEqual((await request("/api/generate")).body.briefs, [])
    const history = (await request(`/api/drafts?commandId=${start.command_id}`)).body
    assert.equal(history.writer_status.status, "result_retained")
    assert.equal(history.writer_status.historical, true)
    assert.equal(JSON.stringify(history).includes("raw_base64"), false)
    assert.equal((await request(`/api/drafts?commandId=${start.command_id}`, undefined, "viewer")).body.writer_status, null)
    assert.equal((await worker("restore_source", start.command_id)).changed, true)
    assert.equal((await worker("capture", start.command_id)).outcome, "candidate_ready")
    let state = (await request("/api/dashboard")).body
    assert.equal(state.candidates.length, 1)
    assert.equal(state.candidates[0].origin_kind, "synchronous_writer_v1")
    assert.equal(state.candidates[0].job_id, undefined)
    assert.equal(state.candidates[0].custom_id, undefined)
    const check = createCandidateCommand(state.candidates[0], "request_candidate_checks")
    assert.equal(localCommandEndpoint(check), "/api/drafts")
    assert.deepEqual(Object.keys(check.payload).sort(), ["origin_kind", "admission_input_id", "admission_input_sha256", "generation_id", "candidate_id", "expected_state_version", "expected_policy_sha256"].sort())
    assert.equal((await request("/api/drafts", check)).status, 202)
    const requested = (await worker("consume", check.command_id))
    assert.equal(requested.status, "unchanged", JSON.stringify(requested))
    assert.equal(requested.candidate.outcome, "checks_requested")
    for (const stage of ["deterministic", "safety", "fact_check", "critic"]) assert.equal((await worker(stage, check.command_id)).outcome, "completed")
    state = (await request("/api/dashboard")).body
    const admit = createCandidateCommand(state.candidates[0], "admit_checked_candidate")
    assert.equal((await request("/api/drafts", admit)).status, 202)
    const admitted = (await worker("consume", admit.command_id))
    assert.equal(admitted.status, "applied")
    const draft = (await request("/api/dashboard")).body.drafts.drafts.find(d => d.id === admitted.changed_ids[0])
    const edit = createDraftCommand(draft, "edit", { editedText: "Edited after sourced generation; review is required." })
    assert.equal((await request("/api/drafts", edit)).status, 202)
    assert.equal((await worker("consume", edit.command_id)).status, "applied")
    const final = (await request("/api/dashboard")).body.drafts.drafts.find(d => d.id === draft.id)
    assert.equal(final.review_binding, undefined)
    assert.equal(final.approval_binding, undefined)
  } finally {
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved, key)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})


test("synchronous command UI uses exact origin fields and existing recovery reference", async () => {
  const { withCommandReference, saveCommandReference, readCommandReference, abandonmentBody } = await import("../lib/local-command-recovery.js")
  const candidate={origin_kind:"synchronous_writer_v1",generation_id:"gss_"+"a".repeat(64),candidate_id:"b".repeat(64),admission_input_id:"c".repeat(64),admission_input_sha256:"d".repeat(64),expected_state_version:0,expected_policy_sha256:"e".repeat(64),job_id:"untrusted",custom_id:"untrusted"}
  const command=createCandidateCommand(candidate,"request_candidate_checks")
  assert.equal(command.payload.job_id,undefined); assert.equal(command.payload.custom_id,undefined)
  const saved=await withCommandReference({command,draftId:candidate.admission_input_id,action:command.action})
  const store=new Map(); const storage={setItem:(k,v)=>store.set(k,v),getItem:k=>store.get(k)}
  assert.ok(saveCommandReference(storage,"invented-scope",saved))
  const recovered=readCommandReference(storage,"invented-scope")
  assert.deepEqual(abandonmentBody(recovered),{action:"abandon_submission",original_action:command.action,request_sha256:saved.request_sha256})
  assert.equal(JSON.stringify(recovered).includes("generation_id"),false)
  const html=renderToStaticMarkup(createElement(SourcedGeneration,{readOnly:true,pendingAction:true}))
  assert.match(html,/Write from retained evidence/)
  assert.match(html,/disabled/)
  assert.equal(localCommandEndpoint(generationCommand({})),"/api/generate")
  assert.match(renderToStaticMarkup(createElement(WriterUsage,{usage:{counts:{input_tokens:0}}})),/final charge unknown/)
})
