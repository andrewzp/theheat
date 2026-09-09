import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ProductHealthPanel } from "../app/components/ProductHealthPanel.js"

function render(props) { return renderToStaticMarkup(React.createElement(ProductHealthPanel, props)) }
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
