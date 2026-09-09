// Paired with src/two_bot/usage_ledger.py and usage_summary.py.
export const COVERAGE_FIELDS = ["priced_calls", "unpriced_calls", "missing_usage_calls", "priced_usd"]
const COUNT_FIELDS = COVERAGE_FIELDS.slice(0, 3)
const LEGACY_COUNTS = ["calls", "in", "cached_in", "cache_write", "out"]
const object = (value) => value && typeof value === "object" && !Array.isArray(value)
const money = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0
const count = (value) => Number.isSafeInteger(value) && value >= 0

export function validUsageDay(day) {
  if (typeof day !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(day) || day.startsWith("0000-")) return false
  const parsed = new Date(`${day}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === day
}

function validCoverage(agg) { return COUNT_FIELDS.every((field) => count(agg[field])) && money(agg.priced_usd) }

const SNAPSHOT_FIELDS = ["calls", "usd", ...COVERAGE_FIELDS]
const SNAPSHOTS = "cost_coverage_snapshots", OVERFLOW = "cost_coverage_overflow", INVALID = "cost_coverage_invalid"
const SNAPSHOT_LIMIT = 32
const tupleCompare = (a, b) => { for (let i=0;i<a.length;i++) { if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1 } return 0 }
const uniqueSnapshots = (rows) => rows.toSorted(tupleCompare).filter((row, i, all) => !i || tupleCompare(row, all[i-1]) !== 0)
function snapshotValid(value) {
  if (!Array.isArray(value) || value.length !== 6) return false
  const [calls, usd, priced, unpriced, missing, pricedUsd] = value
  return [calls, priced, unpriced, missing].every(count) && money(usd) && money(pricedUsd)
    && priced+unpriced <= calls && missing <= unpriced && pricedUsd <= usd+0.000001 && (priced > 0 || pricedUsd === 0)
}
function coverageEvidence(agg) {
  let invalid = Boolean(agg[INVALID]), overflow = Boolean(agg[OVERFLOW]), snapshots = []
  if (Object.hasOwn(agg, SNAPSHOTS)) {
    const raw = agg[SNAPSHOTS]
    if (!Array.isArray(raw) || !raw.length || !raw.every(snapshotValid)) invalid = true
    else {
      snapshots = raw; overflow ||= raw.length > SNAPSHOT_LIMIT
      if (!count(agg.calls) || !money(agg.usd) || !validCoverage(agg)
          || raw.some((value) => SNAPSHOT_FIELDS.some((field,i) => agg[field] < value[i]))
          || (!overflow && COVERAGE_FIELDS.some((field) => agg[field] !== Math.max(...raw.map((value) => value[SNAPSHOT_FIELDS.indexOf(field)]))))) invalid = true
    }
  } else if (!invalid && !overflow && COVERAGE_FIELDS.some((field) => Object.hasOwn(agg, field))) {
    const candidate = SNAPSHOT_FIELDS.map((field) => agg[field])
    if (snapshotValid(candidate)) snapshots = [candidate]
    else invalid = true
  }
  return {...(snapshots.length ? {[SNAPSHOTS]:uniqueSnapshots(snapshots).slice(0,SNAPSHOT_LIMIT)} : {}),
    ...(invalid ? {[INVALID]:true} : {}), ...(overflow ? {[OVERFLOW]:true} : {})}
}
function unionEvidence(items) {
  const snapshots = uniqueSnapshots(items.flatMap((item) => item[SNAPSHOTS] || []))
  return {...(snapshots.length ? {[SNAPSHOTS]:snapshots.slice(0,SNAPSHOT_LIMIT)} : {}),
    ...(items.some((item) => item[INVALID]) ? {[INVALID]:true} : {}),
    ...(snapshots.length > SNAPSHOT_LIMIT || items.some((item) => item[OVERFLOW]) ? {[OVERFLOW]:true} : {})}
}
function evidenceInconsistent(agg) {
  const evidence = coverageEvidence(agg), snapshots = evidence[SNAPSHOTS] || []
  if (evidence[INVALID] || evidence[OVERFLOW]) return true
  return snapshots.some((left,i) => snapshots.slice(i+1).some((right) => !snapshotValid(left.map((value,j) => Math.max(value,right[j])))))
}

function legacyCount(raw) {
  if (typeof raw === "string" && !/^[+-]?\d+$/.test(raw.trim())) return 0
  if (!["number", "string", "boolean"].includes(typeof raw)) return 0
  const value = Number(raw)
  return Number.isFinite(value) ? Math.max(0, Math.min(Math.trunc(value), 1e12)) : 0
}

function legacyUsd(raw) {
  if (!["number", "string", "boolean"].includes(typeof raw)) return 0
  if (typeof raw === "string" && !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(raw.trim())) return 0
  const value = Number(raw)
  return Number.isFinite(value) ? value : 0
}

export function mergeUsageLedgers(base, incoming) {
  const a = object(base) ? base : {}, b = object(incoming) ? incoming : {}
  const result = {}
  for (const day of [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(validUsageDay).sort().slice(-45)) {
    const left = object(a[day]) ? a[day] : {}, right = object(b[day]) ? b[day] : {}
    const bucket = {}
    for (const key of new Set([...Object.keys(left), ...Object.keys(right)])) {
      const rows = [left[key], right[key]].map((value) => object(value) ? value : {})
      const agg = Object.fromEntries(LEGACY_COUNTS.map((field) => [field, Math.max(...rows.map((row) => legacyCount(row[field])))]))
      agg.usd = Math.max(...rows.map((row) => legacyUsd(row.usd)))
      const coverage = rows.filter((row) => COVERAGE_FIELDS.some((field) => Object.hasOwn(row, field)))
      const valid = coverage.filter(validCoverage)
      if (coverage.length) {
        for (const field of COVERAGE_FIELDS) agg[field] = Math.max(0, ...valid.map((row) => row[field]))
      }
      Object.assign(agg, unionEvidence(rows.map(coverageEvidence)))
      Object.defineProperty(bucket, key, { value: agg, enumerable: true, configurable: true, writable: true })
    }
    result[day] = bucket
  }
  return result
}

export function summarizeUsage(state, { now = Date.now() } = {}) {
  const today = new Date(now).toISOString().slice(0, 10), prefix = today.slice(0, 8)
  const ledger = object(state?.llm_usage) ? state.llm_usage : {}
  let recorded = 0, priced = 0, legacyUsd = 0, calls = 0, pricedCalls = 0, unpricedCalls = 0, missingUsage = 0, legacyCalls = 0
  let rowCount = 0, legacyRows = 0, inconsistent = 0, excluded = 0
  for (const [day, bucket] of Object.entries(ledger)) {
    if (!validUsageDay(day) || !day.startsWith(prefix) || day > today) continue
    if (!object(bucket)) { excluded += 1; continue }
    for (const agg of Object.values(bucket)) {
      if (!object(agg) || !money(agg.usd)) { excluded += 1; continue }
      rowCount += 1; recorded += agg.usd
      if (!count(agg.calls) || evidenceInconsistent(agg)) { inconsistent += 1; continue }
      calls += agg.calls
      if (!COVERAGE_FIELDS.some((field) => Object.hasOwn(agg, field))) {
        legacyRows += 1; legacyCalls += agg.calls; legacyUsd += agg.usd; continue
      }
      if (!validCoverage(agg) || agg.priced_calls + agg.unpriced_calls > agg.calls
          || agg.missing_usage_calls > agg.unpriced_calls || agg.priced_usd > agg.usd + 0.000001
          || (agg.priced_calls === 0 && agg.priced_usd > 0)) { inconsistent += 1; continue }
      priced += agg.priced_usd; pricedCalls += agg.priced_calls; unpricedCalls += agg.unpriced_calls; missingUsage += agg.missing_usage_calls
      const oldCalls = agg.calls - agg.priced_calls - agg.unpriced_calls, oldUsd = Math.max(0, agg.usd - agg.priced_usd)
      legacyCalls += oldCalls; legacyUsd += oldUsd; legacyRows += Number(oldCalls > 0 || oldUsd > 0)
    }
  }
  if (![recorded, priced, legacyUsd].every(money) || !count(calls)) inconsistent += 1
  const available = rowCount > 0 && inconsistent === 0, hasEstimate = available && (pricedCalls > 0 || legacyUsd > 0)
  const round = (value) => Number(value.toFixed(6))
  return {
    coverage: inconsistent ? "inconsistent" : rowCount ? "partial" : "unavailable",
    pricing_coverage: inconsistent ? "inconsistent" : !rowCount ? "unavailable" : unpricedCalls || excluded || legacyRows ? "partial" : "priced",
    known_cost_usd: available && pricedCalls ? round(priced) : null,
    legacy_estimate_usd: available && legacyRows ? round(legacyUsd) : null,
    recorded_estimate_usd: hasEstimate ? round(recorded) : null,
    recorded_calls: available ? calls : null, priced_calls: available ? pricedCalls : null,
    unpriced_calls: available ? unpricedCalls : null, missing_usage_calls: available ? missingUsage : null,
    legacy_calls: available ? legacyCalls : null, legacy_rows: legacyRows, inconsistent_rows: inconsistent, excluded_rows: excluded,
    instrumented_stages: ["writer", "fact_check", "critic", "safety", "newsworthiness_search", "newsworthiness_verify"],
    untracked_stages: ["workflow_agents", "other_account_usage"],
    scope: "Instrumented writer, checker, critic, safety and news responses in state-writing runs; table estimates, not account totals or invoices.",
    limitations: [
      "Instrumented stages describe this code version, not proof that retained runs captured every call; historical usage is not backfilled.",
      "Workflow agents, other account usage and non-state-writing evaluations remain untracked; no budget enforcement is implemented here.",
      "Pre-response failures, late source threads and failed persistence can leave usage untracked; a recorded response is not proof of billing.",
      "The shared buffer retains 500 responses; new stage traffic can evict earlier writer responses before a drain.",
      "Google thought/tool/modality/tier and grounding charges are not priced or fully represented; Google responses remain unpriced.",
      "The ledger retains 45 day buckets. MAX cumulative merges can undercount concurrent writers and cannot prove zero spending on missing days.",
      "Coverage keeps up to 32 original cumulative snapshots per day/model; conflicts or overflow make the subtotal unknown.",
      "The unchanged price table was last documented as checked on 2026-07-13; historical values are never repriced by this reader."
],
    budget_enforced: false,
  }
}
