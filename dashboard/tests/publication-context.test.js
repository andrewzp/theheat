import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { acceptedWriterObservation, admitWriterObservation, draftIdentity, fingerprint, invalidateText,
  mergePassiveMaps, passiveComparisonValue, publicationObservation, publicationObservationStatus, qualifyingPublicationContext } from '../lib/draft-revisions.js'
import { mergeDrafts, mergePublishLedger } from '../lib/state-store.js'
import { postOutcomes } from '../lib/post-outcomes.js'
import History from '../app/components/PostOutcomeHistory.js'

const fixture = JSON.parse(fs.readFileSync(new URL('../../tests/fixtures/publication_context_contract.json', import.meta.url)))
const fresh = () => structuredClone(fixture)
const project = state => postOutcomes(state, { now: Date.parse('2026-10-22T14:00:00Z') }).posts[0]
function stateOf(value = fresh()) {
  return { drafts: [value.draft], publish_ledger: { [value.draft.event_id]: value.receipt }, tweet_metrics: {
    '123': { samples: { invented: { schema_version: 1, tweet_id: '123', sampled_at: '2026-10-22T13:00:00Z',
      source: 'x_api.public_metrics', counts: { likes: 0 }, publication_context_sha256: value.context_sha256 } } },
  } }
}

test('frozen Python origin and send payload have exact JS canonical identities', () => {
  const value = fresh(), draft = structuredClone(value.original)
  delete draft.writer_observations
  const metadata = draft.review_context.two_bot
  assert.deepEqual(acceptedWriterObservation(draft.text, metadata.bundle, 'plain_number', draft.event_id), metadata.accepted_writer_observation)
  admitWriterObservation(draft)
  assert.deepEqual(draft, value.original)
  const payload = publicationObservation(value.draft, value.draft.event_id, value.receipt)
  assert.deepEqual(payload, Object.values(value.receipt.publication_observations)[0])
  assert.equal(fingerprint(payload), value.context_sha256)
  assert.equal(qualifyingPublicationContext(value.receipt, value.draft.event_id), value.context_sha256)
})

test('reverted text is net equal with retained differences, incomplete history and unknown actor', () => {
  const state = stateOf(), before = structuredClone(state), post = project(state)
  assert.equal(post.writer_context.status, 'recorded')
  assert.equal(post.writer_context.writer_reported_angle, 'plain_number')
  assert.equal(post.writer_context.text_comparison, 'matches')
  assert.equal(post.writer_context.retained_different_text, true)
  assert.equal(post.writer_context.actor_status, 'unknown')
  assert.equal(post.observations[0].writer_context_status, 'recorded')
  assert.equal(post.observations[0].counts.likes, 0)
  assert.equal(post.observations[0].counts.impressions, null)
  const html = renderToStaticMarkup(React.createElement(History, { outcomes: { posts: [post] } }))
  assert.match(html, /Writer-reported angle \(captured accepted result\): plain number/)
  assert.match(html, /Retained history includes different text/)
  assert.match(html, /A text match does not establish that no edits occurred/)
  assert.match(html, /Actor and human authorship are unknown/)
  assert.deepEqual(state, before)
})

test('later root metadata or candidate changes cannot relabel send context', () => {
  const state = stateOf(), original = project(state).writer_context
  Object.assign(state.drafts[0], { text: 'Different current candidate.', manual_override: true, selected_candidate_rank: 7 })
  state.drafts[0].review_context.two_bot.angle_chosen = 'unbound_current_angle'
  state.drafts[0].writer_observations = { injected: { invented: 'later-unbound-origin' } }
  assert.deepEqual(project(state).writer_context, original)
  assert.equal(project(state).text, fixture.receipt.text)
})

test('same-text edit preserves origin and creates no invented history', () => {
  const draft = fresh().original, before = structuredClone(draft)
  invalidateText(draft, draft.text)
  assert.deepEqual(draft, before)
  assert.deepEqual(draftIdentity(draft), draftIdentity(before))
})

for (const kind of ['missing', 'null', 'malformed', 'event', 'intent', 'time', 'text', 'source', 'unconfirmed']) {
  test(`${kind} receipt provenance is unknown and cannot be repaired by current root metadata`, () => {
    const value = fresh(), row = value.receipt, payload = Object.values(row.publication_observations)[0]
    if (kind === 'missing') delete row.publication_observations
    else if (kind === 'null') row.publication_observations = null
    else if (kind === 'malformed') row.publication_observations = { bad: { ...payload, writer_observations: { bad: null } } }
    else if (kind === 'event') payload.event_id = 'detached'
    else if (kind === 'intent') payload.intent_id = 'detached'
    else if (kind === 'time') payload.at = '2026-02-30T12:00:00Z'
    else if (kind === 'text') row.text = 'Detached receipt text.'
    else if (kind === 'source') payload.source_bundle_sha256 = 'f'.repeat(64)
    else row.phase = 'unknown'
    assert.equal(qualifyingPublicationContext(row, value.draft.event_id), null)
    const post = project(stateOf(value))
    assert.equal(post.writer_context.status, kind === 'text' ? 'conflict' : 'unknown')
    assert.notEqual(post.observations[0].writer_context_status, 'recorded')
  })
}

test('missing or detached metric reference does not reconstruct receipt context', () => {
  const state = stateOf()
  state.tweet_metrics['123'].samples.invented.publication_context_sha256 = 'f'.repeat(64)
  assert.equal(project(state).observations[0].writer_context_status, 'unknown')
  state.publish_ledger = {}
  state.drafts[0].status = 'posted'; state.drafts[0].tweet_id = '123'
  assert.equal(project(state).writer_context.status, 'unknown')
})

test('conflicting passive receipt variants are inspectable, commutative and one physical attempt', () => {
  const value = fresh(), left = value.receipt, right = structuredClone(left)
  Object.values(right.publication_observations)[0].history_unavailable = true
  right.phase = 'submitted'; right.tweet_id = null; delete right.confirmed_at
  const event = value.draft.event_id
  const merged = mergePublishLedger({ [event]: left }, { [event]: right })
  assert.deepEqual(merged, mergePublishLedger({ [event]: right }, { [event]: left }))
  assert.deepEqual(mergePublishLedger(merged, merged), merged)
  assert.equal(merged[event].phase, 'confirmed'); assert.equal(merged[event].tweet_id, '123')
  assert.equal(Object.hasOwn(merged[event], 'attempt_conflicts'), false)
  assert.equal(Object.keys(merged[event].publication_observations).length, 2)
  assert.equal(qualifyingPublicationContext(merged[event], event), null)
  const state = stateOf(value); state.publish_ledger = merged
  const post = project(state)
  assert.equal(post.writer_context.status, 'conflict')
  assert.equal(post.writer_context.variants.length, 2)
  assert.match(renderToStaticMarkup(React.createElement(History, { outcomes: { posts: [post] } })), /Retained writer and text observation variants/)
})

test('root passive union preserves malformed actual payloads without changing decisions or identity', () => {
  const left = fresh().draft, right = structuredClone(left), before = draftIdentity(left)
  right.writer_observations = { copied_key: null }
  const merged = mergeDrafts([left], [right])
  assert.equal(Object.keys(merged[0].writer_observations).length, 2)
  assert.deepEqual(merged, mergeDrafts([right], [left]))
  assert.deepEqual(mergeDrafts(merged, merged), merged)
  assert.deepEqual(draftIdentity(merged[0]), before)
  assert.equal(Object.hasOwn(merged[0], 'revision_conflicts'), false)
  assert.deepEqual(mergePassiveMaps(null, null), mergePassiveMaps(mergePassiveMaps(null)))
})

test('nested contradictory text observations and writer variants remain conflicts', () => {
  for (const kind of ['writer', 'history']) {
    const value = fresh(), payload = Object.values(value.receipt.publication_observations)[0]
    if (kind === 'writer') {
      const writer = structuredClone(Object.values(payload.writer_observations)[0]); writer.angle_chosen = 'other_angle'
      payload.writer_observations.bad_key = writer
    } else {
      const row = structuredClone(Object.values(payload.text_observations)[0]); row.text_sha256 = 'f'.repeat(64)
      payload.text_observations.bad_key = row
    }
    assert.equal(publicationObservationStatus(payload, value.draft.event_id, value.receipt), 'conflict')
    assert.equal(project(stateOf(value)).writer_context.status, 'conflict')
  }
})

test('same-rank/same-time distinct intents retain legacy physical winner/order for every passive variant', () => {
  const event = fixture.draft.event_id, original = structuredClone(fixture.receipt)
  delete original.publication_observations
  const other = { ...structuredClone(original), intent_id: 'another-distinct-intent' }
  const legacy = mergePublishLedger({ [event]: original }, { [event]: other })
  const strip = row => Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'publication_observations')
    .map(([key, value]) => [key, key === 'attempt_conflicts' ? value.map(strip) : value]))
  for (let variant = 0; variant < 32; variant++) {
    const left = { ...structuredClone(original), publication_observations: { arbitrary: { variant } } }
    const right = { ...structuredClone(other), publication_observations: { arbitrary: { variant: 31 - variant } } }
    const merged = mergePublishLedger({ [event]: left }, { [event]: right })
    assert.deepEqual(strip(merged[event]), legacy[event])
    assert.deepEqual(merged, mergePublishLedger({ [event]: right }, { [event]: left }))
  }
})

test('distinct tweet-ID alternate keys retain passive variants without minting extra attempts', () => {
  const event = fixture.draft.event_id, original = structuredClone(fixture.receipt)
  const alternate = { ...structuredClone(original), tweet_id: '456' }, variant = structuredClone(alternate)
  Object.values(variant.publication_observations)[0].history_unavailable = true
  const merged = mergePublishLedger(mergePublishLedger({ [event]: original }, { [event]: alternate }), { [event]: variant })
  const rows = [merged[event], ...(merged[event].attempt_conflicts || [])]
  assert.equal(rows.length, 2)
  assert.equal(Object.keys(rows.find(row => row.tweet_id === '456').publication_observations).length, 2)
})


test('receipt traversal order cannot change passive conflict variants or their availability', () => {
  const value = fresh(), first = value.receipt, second = structuredClone(first)
  second.intent_id = 'detached-intent'
  const state = stateOf(value)
  state.publish_ledger = { [value.draft.event_id]: first, second }
  const forward = project(state).writer_context
  state.publish_ledger = { second, [value.draft.event_id]: first }
  assert.deepEqual(project(state).writer_context, forward)
  assert.equal(forward.status, 'unknown')
  assert.equal(forward.variants[0].status, 'unknown')
})

test('invalid Unicode passive payloads are losslessly encoded unavailable and never change identities', () => {
  const malformed = { note: '\ud800', nested: { '\udfff': ['café ☀', -0, 1.25], '𐀀': true, '10': 10, '2': 2 } }
  const normalized = mergePassiveMaps({ declared: malformed })
  const unavailable = Object.values(normalized)[0]
  assert.equal(JSON.parse(unavailable.passive_unavailable_record.raw_data)[0], 'object')
  assert.match(unavailable.passive_unavailable_record.raw_data, /\\ud800/)
  assert.match(unavailable.passive_unavailable_record.raw_data, /\\udfff/)
  assert.deepEqual(mergePassiveMaps(normalized, normalized), normalized)
  assert.throws(() => fingerprint(malformed), /Invalid Unicode/)
  const value = fresh(), originalIdentity = draftIdentity(value.draft)
  value.draft.writer_observations = { invalid: malformed }
  assert.deepEqual(draftIdentity(value.draft), originalIdentity)
  const payload = publicationObservation(value.draft, value.draft.event_id, value.receipt)
  value.receipt.publication_observations = { [fingerprint(payload)]: payload }
  assert.equal(qualifyingPublicationContext(value.receipt, value.draft.event_id), null)
  assert.equal(project(stateOf(value)).writer_context.status, 'unknown')
  assert.deepEqual(mergeDrafts([value.draft], [value.draft])[0].writer_observations, normalized)
})


test('P30-H3-01 raw Unicode and its exact ordinary envelope preserve both variants after reload', () => {
  const raw = { note: '\ud800' }
  const legacyEnvelope = { unavailable_unicode_json: passiveComparisonValue(raw) }
  const encoded = mergePassiveMaps({ raw })
  const [key, frame] = Object.entries(encoded)[0]
  assert.match(key, /^unavailable-v1:[a-f0-9]{64}$/)
  for (const envelope of [legacyEnvelope, frame]) {
    const mixed = mergePassiveMaps({ raw, ordinary: envelope })
    assert.equal(Object.keys(mixed).length, 2)
    assert.ok(Object.hasOwn(mixed, fingerprint(envelope)))
    assert.deepEqual(mixed, mergePassiveMaps({ ordinary: envelope }, { raw }))
    assert.deepEqual(mergePassiveMaps(JSON.parse(JSON.stringify(mixed)), mixed), mixed)
  }
  const container = mergePassiveMaps(null, { rawEnvelope: { unavailable_container: null } })
  assert.equal(Object.keys(container).length, 2)
  assert.deepEqual(mergePassiveMaps(JSON.parse(JSON.stringify(container)), container), container)
  const rawFrame = mergePassiveMaps({ unverified: frame })
  assert.equal(Object.keys(rawFrame)[0], fingerprint(frame))
  assert.equal(Object.keys(mergePassiveMaps(encoded, rawFrame)).length, 2)
})

test('P30-H3-01 malformed-container record and identical raw frame occupy separate domains', () => {
  const encoded = mergePassiveMaps(null), [key, frame] = Object.entries(encoded)[0]
  const mixed = mergePassiveMaps(encoded, { ordinary: frame })
  assert.equal(Object.keys(mixed).length, 2)
  assert.ok(Object.hasOwn(mixed, key)); assert.ok(Object.hasOwn(mixed, fingerprint(frame)))
  assert.deepEqual(mergePassiveMaps(mixed, JSON.parse(JSON.stringify(mixed))), mixed)
  const ordinary = Object.values(fixture.original.writer_observations)[0]
  assert.deepEqual(mergePassiveMaps({ [key]: ordinary }), { [fingerprint(ordinary)]: ordinary })
})

for (const [token, recognized] of [['1', true], ['1.0', true], ['1e0', true], ['true', false], ['"1"', false], ['0', false], ['2', false]]) {
  test(`P30-H3-01 reserved codec schema_version literal ${token} uses the shared JSON number model`, () => {
    const valid = mergePassiveMaps(null)
    const literal = JSON.stringify(valid).replace('"schema_version":1', '"schema_version":' + token)
    const parsed = JSON.parse(literal), direct = mergePassiveMaps(parsed), combined = mergePassiveMaps(valid, parsed)
    assert.equal(Object.keys(combined).length, recognized ? 1 : 2)
    assert.deepEqual(mergePassiveMaps(parsed, valid), combined)
    assert.deepEqual(mergePassiveMaps(JSON.parse(JSON.stringify(combined)), combined), combined)
    assert.deepEqual(mergePassiveMaps(JSON.parse(JSON.stringify(direct))), direct)
    const frame = Object.values(parsed)[0]
    assert.deepEqual(mergePassiveMaps({ unverified: frame }), { [fingerprint(frame)]: frame })
  })
}
