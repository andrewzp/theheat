import { policy, runtimeRun } from "./helpers/review-policy.js"
import test from "node:test"

// Explicit policy for these mocked legacy release scenarios.
process.env.THEHEAT_AUTOMATIC_PUBLICATION_ENABLED = "1"
process.env.THEHEAT_AUTOMATIC_PUBLICATION_EPOCH = "offline-test-release"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { importFresh } from "./helpers/import-fresh.js"
import { authorizeDraft, draftIdentity, fingerprint, initializeRevision, invalidateText, recordHumanReview, reviewIsCurrent, textHash } from "./helpers/review-policy.js"

const malformedAttempts = JSON.parse(readFileSync(new URL("../../tests/fixtures/publication_uncertainty_contract.json", import.meta.url))).filter((example) => example.malformed)

function fixture(id = "draft_1") {
  const draft = {
    id, event_id: `event_${id}`, type: "hot10", status: "pending", text: "Example City reached 40°C today.",
    created_at: "2026-09-08T12:00:00Z", score: { total: 60 },
    approval_policy: { can_auto_approve: true, recommended_delay_minutes: 30 },
    review_context: { source: "test observations", two_bot: {
      bundle: { event_id: `event_${id}`, headline_value: 40 },
      fact_check: { passed: true, extracted_claims: [{ kind: "measurement", value: 40 }] },
      critic: { passed: true }, reasoning: "Previous text reasoning",
    } },
  }
  const proof = draft.review_context.two_bot
  proof.reviewed_text_sha256 = textHash(draft.text)
  proof.reviewed_policy_sha256 = fingerprint(policy)
  proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
  return initializeRevision(draft)
}

async function withStore(drafts, run, options = {}) {
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "reviewer", DASHBOARD_PASSWORD: "secret-pass", THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "gist_revision_test", GITHUB_TOKEN: "token_revision_test" })
  let state = { drafts: structuredClone(drafts), publish_ledger: options.ledger || {}, errors: [], run_history: [{ started_at: new Date().toISOString(), runtime_inventory: { editorial_policy: structuredClone(policy), schema_version: 1, captured_at: new Date().toISOString(), flags: { automatic_publication_enabled: true, automatic_publication_epoch: "offline-test-release" } } }] }
  const dispatches = []
  let writes = 0
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, request = {}) => {
    if (String(url).includes("/dispatches")) {
      dispatches.push(JSON.parse(request.body))
      options.onDispatch?.(state)
      if (options.dispatchThrows) throw new Error("request timed out")
      return { ok: !options.dispatchStatus, status: options.dispatchStatus || 204, async text() { return "dispatch failure" } }
    }
    if (request.method === "PATCH") {
      state = JSON.parse(JSON.parse(request.body).files["state.json"].content)
      writes++
      options.onWrite?.(state, writes)
      return { ok: true, status: 200, async json() { return {} } }
    }
    const snapshot = JSON.stringify(state)
    return { ok: true, status: 200, async json() { return { files: { "state.json": { content: snapshot } } } } }
  }
  try {
    const route = await importFresh("app/api/drafts/route.js")
    const headers = { "Content-Type": "application/json", authorization: `Basic ${Buffer.from("reviewer:secret-pass").toString("base64")}` }
    async function post(body) {
      const response = await route.POST(new Request("http://localhost/api/drafts", { method: "POST", headers, body: JSON.stringify(body) }))
      return { status: response.status, body: await response.json() }
    }
    await run({ post, route, headers, state: () => state, dispatches, writes: () => writes })
  } finally { globalThis.fetch = originalFetch }
}
function expected(draft) { return { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 } }
function request(draft, action, more = {}) { return { draftId: draft.id, action, expectedRevision: expected(draft), ...more } }

for (const action of ["edit", "select_candidate"]) {
  test(`${action} revokes scheduled approval and archives old checks`, async () => {
    const original = fixture()
    authorizeDraft(original, "auto")
    Object.assign(original, { auto_approve_at: "2026-09-08T13:00:00Z", auto_approve_requested_at: "2026-09-08T12:00:00Z", autoship_on_critic_pass: true, approved_at: "2026-09-08T12:00:00Z", publish_intent_id: "old-intent", publish_requested_at: "2026-09-08T12:00:00Z", candidates: [{ rank: 2, text: "Example City reached 41°C today.", score: { total: 90 } }] })
    await withStore([original], async ({ post, state, dispatches }) => {
      const result = await post(request(original, action, { editedText: "Example City reached 41°C today.", candidateRank: 2 }))
      assert.equal(result.status, 200)
      const saved = state().drafts[0]
      assert.equal(saved.content_revision, 2)
      assert.equal(saved.status, "pending")
      for (const field of ["auto_approve_at", "auto_approve_requested_at", "approved_at", "approval_binding", "publish_intent_id", "publish_requested_at", "autoship_on_critic_pass", "review_binding"]) assert.equal(saved[field], undefined, field)
      for (const field of ["fact_check", "critic", "reasoning"]) assert.equal(saved.review_context.two_bot[field], undefined, field)
      assert.deepEqual(saved.review_context.two_bot.bundle, original.review_context.two_bot.bundle)
      assert.equal(saved.revision_history[0].text, original.text)
      assert.equal(saved.revision_history[0].review_context.two_bot.fact_check.passed, true)
      assert.equal(result.body.draft.review_status, "needs_revalidation")
      assert.equal(dispatches.length, 0)
    })
  })
}

test("A to B to A never revives the original review or accepts its stale request", async () => {
  const original = fixture()
  await withStore([original], async ({ post, state, dispatches }) => {
    assert.equal((await post(request(original, "edit", { editedText: "Changed wording." }))).status, 200)
    const changed = structuredClone(state().drafts[0])
    assert.equal((await post(request(changed, "edit", { editedText: original.text }))).status, 200)
    assert.equal(state().drafts[0].content_revision, 3)
    assert.equal(draftIdentity(state().drafts[0]).text_sha256, draftIdentity(original).text_sha256)
    assert.equal((await post(request(original, "approve"))).status, 409)
    assert.equal(reviewIsCurrent(state().drafts[0]), false)
    assert.equal(dispatches.length, 0)
  })
})

test("legacy draft needs explicit human review; human review allows manual posting only", async () => {
  const original = fixture()
  delete original.content_revision
  delete original.review_binding
  await withStore([original], async ({ post, state, dispatches }) => {
    assert.equal((await post(request(original, "approve"))).status, 409)
    assert.equal((await post(request(original, "review"))).status, 400)
    const reviewed = await post(request(original, "review", { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) }))
    assert.equal(reviewed.status, 200)
    assert.equal(reviewed.body.draft.review_kind, "human")
    const current = structuredClone(state().drafts[0])
    const schedule = await post(request(current, "auto_approve"))
    assert.equal(schedule.status, 409)
    assert.equal(schedule.body.code, "model_review_required")
    assert.equal((await post(request(current, "approve"))).status, 200)
    assert.equal(dispatches.length, 1)
    const saved = state().drafts[0]
    assert.equal(dispatches[0].inputs.tweet_text, current.text)
    assert.equal(dispatches[0].inputs.publish_intent_id, saved.approval_binding.publish_intent_id)
    assert.equal(saved.approval_binding.text_sha256, draftIdentity(current).text_sha256)
    assert.equal((await post(request(saved, "approve"))).status, 409)
  })
})

test("model review permits scheduling and cancellation clears its authorization", async () => {
  const original = fixture()
  await withStore([original], async ({ post, state }) => {
    assert.equal((await post(request(original, "auto_approve", { delayMinutes: 15 }))).status, 200)
    const current = structuredClone(state().drafts[0])
    assert.equal(current.approval_binding.mode, "auto")
    assert.ok(current.auto_approve_at)
    assert.equal((await post(request(current, "cancel_auto_approve"))).status, 200)
    assert.equal(state().drafts[0].approval_binding, undefined)
    assert.equal(state().drafts[0].auto_approve_at, undefined)
  })
})

test("changed evidence invalidates a stale acknowledgement even with unchanged text", async () => {
  const original = fixture()
  const changed = structuredClone(original)
  changed.review_context.two_bot.bundle.headline_value = 42
  await withStore([changed], async ({ post, writes }) => {
    assert.equal((await post(request(original, "review", { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) }))).status, 409)
    assert.equal(writes(), 0)
  })
})

for (const condition of ["posted", "unknown"]) {
  test(`${condition} publication prevents edits and approval`, async () => {
    const original = fixture()
    if (condition === "posted") original.status = "posted"
    const ledger = condition === "unknown" ? { [original.event_id]: { phase: "unknown", text: original.text } } : {}
    await withStore([original], async ({ post, writes, dispatches }) => {
      assert.equal((await post(request(original, "edit", { editedText: "Replacement text." }))).status, 409)
      assert.equal((await post(request(original, "approve"))).status, 409)
      assert.equal(writes(), 0)
      assert.equal(dispatches.length, 0)
    }, { ledger })
  })
}

for (const example of malformedAttempts) {
  test(`malformed delivery evidence blocks every dashboard action: ${example.name}`, async () => {
    const original = fixture()
    const ledger = { [original.event_id]: structuredClone(example.row) }
    await withStore([original], async ({ post, state, route, headers, writes, dispatches }) => {
      const before = structuredClone(state())
      const response = await route.GET(new Request("http://localhost/api/drafts", { headers }))
      assert.equal((await response.json()).drafts[0].publish_blocked, true)
      for (const action of ["edit", "select_candidate", "review", "approve", "auto_approve", "cancel_auto_approve", "reject", "bulk_reject_below"]) {
        const result = await post(request(original, action, {
          editedText: "Replacement text.", candidateRank: 1, reviewConfirmed: true, expectedPolicySha256: fingerprint(policy),
          expectedRevisions: { [original.id]: expected(original) },
        }))
        assert.equal(result.status, 409, action)
        assert.equal(result.body.code, "publication_unresolved", action)
      }
      assert.equal(writes(), 0)
      assert.equal(dispatches.length, 0)
      assert.deepEqual(state(), before)
    }, { ledger })
  })
}

test("an unrelated dashboard edit preserves malformed publication evidence", async () => {
  const blocked = fixture("blocked"), editable = fixture("editable")
  const bad = { phase: "not_sent", attempt_conflicts: [null, { phase: "unknown", text: "Original uncertain text" }] }
  await withStore([blocked, editable], async ({ post, state, writes }) => {
    assert.equal((await post(request(editable, "edit", { editedText: "A separate corrected draft." }))).status, 200)
    assert.equal(writes(), 1)
    assert.deepEqual(state().publish_ledger[blocked.event_id].attempt_conflicts, [bad])
    const result = await post(request(blocked, "approve"))
    assert.equal(result.status, 409)
    assert.equal(result.body.code, "publication_unresolved")
    assert.equal(writes(), 1)
  }, { ledger: { [blocked.event_id]: bad } })
})

test("known dispatch failure rolls back only its unchanged approval", async () => {
  const original = fixture()
  await withStore([original], async ({ post, state }) => {
    const result = await post(request(original, "approve"))
    assert.equal(result.status, 500)
    assert.equal(result.body.rollbackSkipped, false)
    assert.equal(state().drafts[0].status, "pending")
    assert.equal(state().drafts[0].approval_binding, undefined)
    assert.equal(state().drafts[0].publish_intent_id, undefined)
  }, { dispatchStatus: 503 })
})

test("late dispatch failure cannot roll back a newer reviewed revision and intent", async () => {
  const original = fixture()
  await withStore([original], async ({ post, state }) => {
    const result = await post(request(original, "approve"))
    assert.equal(result.status, 500)
    assert.equal(result.body.rollbackSkipped, true)
    const current = state().drafts[0]
    assert.equal(current.text, "Newer editor text.")
    assert.equal(current.status, "approved")
    assert.equal(current.publish_intent_id, "new-intent")
    assert.equal(current.approval_binding.publish_intent_id, "new-intent")
  }, { dispatchStatus: 503, onDispatch(state) {
    const draft = state.drafts[0]
    invalidateText(draft, "Newer editor text.")
    recordHumanReview(draft)
    authorizeDraft(draft, "manual", "new-intent")
    draft.status = "approved"
  } })
})

test("bulk preflight prevents missing-version writes and reports partial conflicts", async () => {
  const first = fixture("first")
  const second = fixture("second")
  await withStore([first, second], async ({ post, writes }) => {
    const result = await post({ action: "bulk_reject_below", expectedRevisions: { first: expected(first) } })
    assert.equal(result.status, 400)
    assert.equal(result.body.count, 0)
    assert.equal(writes(), 0)
  })
  await withStore([first, second], async ({ post, state }) => {
    const result = await post({ action: "bulk_reject_below", expectedRevisions: { first: expected(first), second: expected(second) } })
    assert.equal(result.status, 409)
    assert.deepEqual(result.body.changedIds, ["first"])
    assert.equal(result.body.count, 1)
    assert.equal(state().drafts.find((d) => d.id === "second").status, "pending")
  }, { onWrite(state, writes) { if (writes === 1) invalidateText(state.drafts.find((d) => d.id === "second"), "Concurrent change.") } })
})

test("GET projects queued approvals and isolates malformed evidence", async () => {
  const current = fixture()
  current.status = "approved"
  const invalid = fixture("invalid")
  invalid.content_revision = "bad"
  await withStore([current, invalid], async ({ route, headers }) => {
    const response = await route.GET(new Request("http://localhost/api/drafts", { headers }))
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.drafts.length, 2)
    assert.deepEqual(payload.drafts.find((d) => d.id === current.id).revision_identity, expected(current))
    const broken = payload.drafts.find((d) => d.id === "invalid")
    assert.equal(broken.review_status, "conflict")
    assert.equal(broken.revision_identity, null)
    assert.equal(broken.publish_blocked, true)
  })
})

test("a dispatch timeout preserves the exact queued approval and tells the editor its outcome is uncertain", async () => {
  const original = fixture()
  await withStore([original], async ({ post, state, dispatches }) => {
    const result = await post(request(original, "approve"))
    assert.equal(result.status, 503)
    assert.equal(result.body.code, "dispatch_uncertain")
    assert.match(result.body.error, /remains queued/)
    const saved = state().drafts[0]
    assert.equal(saved.status, "approved")
    assert.equal(saved.publish_intent_id, dispatches[0].inputs.publish_intent_id)
    assert.equal(saved.approval_binding.publish_intent_id, saved.publish_intent_id)
    assert.equal((await post(request(saved, "approve"))).status, 409)
    assert.equal(dispatches.length, 1)
  }, { dispatchThrows: true })
})

test("draft editing and candidate selection use Unicode code points consistently", async () => {
  for (const action of ["edit", "select_candidate"]) {
    const original = fixture()
    const text = "A storm update: " + "🌀".repeat(141)
    assert.ok(text.length > 280)
    assert.ok(Array.from(text).length < 280)
    original.candidates = [{ rank: 1, text }]
    await withStore([original], async ({ post, state }) => {
      assert.equal((await post(request(original, action, { editedText: text, candidateRank: 1 }))).status, 200)
      assert.equal(state().drafts[0].text, text)
      assert.equal(draftIdentity(state().drafts[0]).text_sha256, textHash(text))
    })
  }
})

test("same-text decision changes invalidate old browser approval and cancellation requests", async () => {
  const original = fixture()
  await withStore([original], async ({ post, state, dispatches }) => {
    assert.equal((await post(request(original, "auto_approve"))).status, 200)
    assert.equal(state().drafts[0].text, original.text)
    assert.equal((await post(request(original, "approve"))).status, 409)
    assert.equal((await post(request(original, "cancel_auto_approve"))).status, 409)
    assert.ok(state().drafts[0].auto_approve_at)
    assert.equal(dispatches.length, 0)
  })
})

test("invalid Unicode is rejected with 422 before an edit or candidate selection can write", async () => {
  for (const action of ["edit", "select_candidate"]) {
    const original = fixture()
    original.candidates = [{ rank: 1, text: "Invalid text: \ud800" }]
    await withStore([original], async ({ post, state, writes, dispatches }) => {
      const result = await post(request(original, action, { editedText: "Invalid text: \ud800", candidateRank: 1 }))
      assert.equal(result.status, 422)
      assert.equal(result.body.code, "invalid_draft_data")
      assert.match(result.body.error, /Invalid Unicode/)
      assert.equal(writes(), 0)
      assert.equal(dispatches.length, 0)
      assert.equal(state().drafts[0].text, original.text)
      assert.equal(state().drafts[0].content_revision, original.content_revision)
      assert.equal(state().drafts[0].revision_history, undefined)
    })
  }
})


test("human confirmation cannot silently adopt a changed or unverified policy", async () => {
  for (const mode of ["changed", "missing", "expired"]) {
    const draft = fixture()
    invalidateText(draft, "New text requiring human review.")
    await withStore([draft], async ({ post, state, writes, dispatches }) => {
      if (mode === "changed") state().run_history[0].runtime_inventory.editorial_policy.models.writer = "new-policy-model"
      if (mode === "expired") state().run_history[0].runtime_inventory.captured_at = "2000-01-01T00:00:00Z"
      const body = request(draft, "review", { reviewConfirmed: true, ...(mode === "missing" ? {} : { expectedPolicySha256: fingerprint(policy) }) })
      const result = await post(body)
      assert.equal(result.status, 409)
      assert.match(result.body.code, /editorial_policy/)
      assert.equal(writes(), 0)
      assert.equal(dispatches.length, 0)
      assert.equal(state().drafts[0].review_binding, undefined)
    })
  }
})
