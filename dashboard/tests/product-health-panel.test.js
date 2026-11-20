import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ProductHealthPanel } from "../app/components/ProductHealthPanel.js"
import { buildProductHealth } from "../lib/product-health.js"

function render(props) { return renderToStaticMarkup(React.createElement(ProductHealthPanel, props)) }

test("panel explains the latest rejected draft's retained window and text hold without implying approval", () => {
  const value = buildProductHealth({ drafts: [{ id: "draft_latest", created_at: "2026-09-08T17:00:00Z",
    status: "rejected", text: "x".repeat(201), rejected_reason: "awc_source_window_elapsed" }], publish_ledger: {} },
  { now: Date.parse("2026-09-08T18:00:00Z") })
  const markup = render({ health: value })
  assert.match(markup, /data-latest-draft-disposition="rejected"/)
  assert.match(markup, /Latest saved draft: rejected/)
  assert.match(markup, /airport observations expired/i)
  assert.match(markup, /200 characters/)
  assert.doesNotMatch(markup, /xxxxx|Approved to post|publishing has recovered/)
})

test("latest draft panel keeps ambiguous and unknown outcomes distinct and never renders arbitrary reason strings", () => {
  const draft = { id: "invented", created_at: "2026-09-08T17:00:00Z", status: "rejected", text: "A short fact.",
    automatic_text_hold: "automatic_text_over_200_scalars", rejected_reason: "<script>private-reason</script>",
    post_error: "Observed airport report needs fresh source review: awc_source_changed" }
  const state = buildProductHealth({ drafts: [draft], publish_ledger: {} }, { now: Date.parse("2026-09-08T18:00:00Z") })
  const markup = render({ health: state })
  assert.match(markup, /Current text no longer has that automatic text hold/)
  assert.match(markup, /Last recorded send hold: the airport source changed at recheck/)
  assert.doesNotMatch(markup, /private-reason|<script>/)
  assert.match(render({ health: { ...state, latest_saved_draft: { status: "ambiguous" } } }), /cannot be uniquely identified/)
  assert.match(render({ health: { ...state, latest_saved_draft: { status: "unknown" } } }), /outcome is unavailable/)
})
const health = {
  milestones: { post_confirmed: { at: "2026-07-23T12:00:00Z", age_hours: 47 * 24 } },
  queue: { waiting_count: 2, unresolved_publish_count: 1, oldest_waiting_at: "2026-06-11T12:00:00Z", oldest_waiting_age_hours: 90 * 24 },
  writer: { status: "unknown", notes: ["No retained writer call proves current access."] },
  metrics: { status: "inactive", lookback_days: 30, eligible_post_count: 0, notes: ["No retained receipt-backed post is within the collection window."] },
}

test("missing operating evidence renders unknown instead of a zero healthy dashboard", () => {
  const markup = render({})
  assert.match(markup, /Operating evidence is unavailable/)
  assert.doesNotMatch(markup, /0 waiting|0 unresolved|healthy<\/|Present/)
})

test("panel exposes old queue, uncertain delivery and inactive metrics without treating missing data as zero", () => {
  const markup = render({ health, config: { status: "unknown" } })
  assert.match(markup, /2 waiting · 1 unresolved deliveries/)
  assert.match(markup, /90d ago/)
  assert.match(markup, /Writing pipeline · unknown/)
  assert.match(markup, /Engagement collection · inactive/)
  assert.match(markup, /Last post with receipt/)
  assert.match(markup, /47d ago/)
  assert.match(markup, /<summary>Bot settings and evidence · unknown/)
  assert.match(markup, /Last saved draft<\/dt><dd>Unknown/)
  assert.doesNotMatch(markup, /0 likes|self-heal will|claude-sonnet/)
})

test("panel labels stale views and credential presence separately from successful access", () => {
  const markup = render({ health, stale: true, config: {
    status: "stale", writer_model: "recorded-writer", flags: { autoship_on_critic_pass: false },
    credentials_present: { anthropic: true, twitter: false },
  } })
  assert.match(markup, /Refresh failed/)
  assert.match(markup, /Present · access unverified/)
  assert.match(markup, /twitter<\/dt><dd>Missing/)
  assert.match(markup, /Automatic scheduling after critic pass<\/dt><dd>Off/)
  assert.match(markup, /recorded-writer/)
})

test("configuration-only refresh cannot claim continued ingestion or successful provider access", () => {
  const markup = render({ health, config: { status: "recorded", report_kind: "configuration_only",
    flags: { automatic_publication_enabled: false } } })
  assert.match(markup, /Configuration refreshed only/)
  assert.match(markup, /did not collect stories, write drafts or verify provider access/)
  assert.doesNotMatch(markup, /Ingestion and review continue/)
})

const observationClock = Date.parse("2026-11-17T07:00:00Z")
function publicationEvidence(at) {
  return buildProductHealth({ drafts: [], publish_ledger: at === null ? {} : {
    invented: { tweet_id: "123456789", at },
  }, source_health: { awc_observed: { runs: [{ ts: "2026-11-17T06:59:00Z", status: "success", observed: 1 }] } } },
  { now: observationClock })
}

test("enabled publication with fresh collection but old receipt needs visible attention", () => {
  const value = publicationEvidence("2026-11-13T07:00:00Z")
  assert.equal(value.milestones.source_observed.age_hours, 1 / 60)
  const markup = render({ health: value, config: { flags: { automatic_publication_enabled: true } } })
  assert.match(markup, /data-publication-evidence="old_receipt"/)
  assert.match(markup, /No recent X receipt in saved data/)
  assert.match(markup, /latest dated receipt is 4d ago/)
  assert.doesNotMatch(markup, /X is down|healthy|publishing has recovered/)
})

test("enabled publication with missing or invalid receipt clocks stays unverified", () => {
  for (const at of [null, "not-a-clock", "2026-11-18T07:00:00Z", "2026-11-31T07:00:00Z"]) {
    const value = publicationEvidence(at)
    const markup = render({ health: value, config: { flags: { automatic_publication_enabled: true } } })
    assert.match(markup, /data-publication-evidence="undated_receipt"/)
    assert.match(markup, /No dated X receipt is available in saved data/)
    assert.doesNotMatch(markup, /0 posts|No posts were published|publishing has recovered/)
  }
})

test("publication attention threshold changes no receipt, pause or stale-view semantics", () => {
  const config = { flags: { automatic_publication_enabled: true } }
  const recent = render({ health: publicationEvidence("2026-11-16T07:00:01Z"), config })
  assert.doesNotMatch(recent, /data-publication-evidence=/)
  assert.doesNotMatch(recent, /healthy|publishing has recovered/)
  const boundary = render({ health: publicationEvidence("2026-11-16T07:00:00Z"), config, stale: true })
  assert.match(boundary, /data-publication-evidence="old_receipt"/)
  assert.match(boundary, /Refresh failed · showing the last loaded evidence/)
  for (const flags of [{}, { automatic_publication_enabled: false }]) {
    const markup = render({ health: publicationEvidence(null), config: { flags } })
    assert.doesNotMatch(markup, /data-publication-evidence=/)
    assert.match(markup, /publication paused|publication state is unverified/)
  }
})
