import { readStateStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"

export const runtime = "nodejs"

// Economics P1.1 — the ledger dashboard line. Reads the P0.6 usage ledger
// (state.llm_usage: day → "stage|model" → counters + est $) and returns
// month-to-date spend, a straight-line projection, the configured budget,
// and a recent per-day series. Estimate semantics mirror
// src/orchestrator/budget.py — the Console is the invoice, this is the trend.

const RECENT_DAYS = 14
const DEFAULT_BUDGET_USD = 14.0

// Canonical-date validation, mirroring usage_ledger._is_valid_day_key: this
// route reads RAW state — the ledger validates at drain/merge, but a reader
// must not trust it (codex P2: "2026-07-zz" or "9999-99-00" would pollute
// the MTD sum and steal 14-day-slice slots from real days).
const DAY_KEY_RE = /^\d{4}-\d{2}-\d{2}$/
function isValidDayKey(day) {
  if (typeof day !== "string" || !DAY_KEY_RE.test(day)) return false
  const parsed = new Date(`${day}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === day
}

function monthlyBudgetUsd() {
  const raw = Number(process.env.THEHEAT_MONTHLY_BUDGET_USD)
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_BUDGET_USD
}

function dayTotalUsd(bucket) {
  if (!bucket || typeof bucket !== "object") return 0
  let total = 0
  for (const agg of Object.values(bucket)) {
    const usd = Number(agg?.usd)
    if (Number.isFinite(usd)) total += usd
  }
  return total
}

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }
  try {
    const state = await readStateStore()
    const ledger =
      state.llm_usage && typeof state.llm_usage === "object" ? state.llm_usage : {}

    const now = new Date()
    const monthPrefix = now.toISOString().slice(0, 8) // "YYYY-MM-"
    const daysInMonth = new Date(now.getUTCFullYear(), now.getUTCMonth() + 1, 0).getDate()

    let mtdUsd = 0
    for (const [day, bucket] of Object.entries(ledger)) {
      if (isValidDayKey(day) && day.startsWith(monthPrefix)) {
        mtdUsd += dayTotalUsd(bucket)
      }
    }
    const budgetUsd = monthlyBudgetUsd()
    const projectedUsd = (mtdUsd / Math.max(now.getUTCDate(), 1)) * daysInMonth

    const recent = Object.keys(ledger)
      .filter(isValidDayKey)
      .sort()
      .slice(-RECENT_DAYS)
      .map((day) => ({
        day,
        usd: Number(dayTotalUsd(ledger[day]).toFixed(4)),
        by_stage_model: ledger[day] && typeof ledger[day] === "object" ? ledger[day] : {},
      }))

    return Response.json({
      // Echo the clock the computation used, so consumers (and tests) can
      // verify the projection deterministically instead of guessing our now.
      as_of_day: now.getUTCDate(),
      days_in_month: daysInMonth,
      budget_usd: budgetUsd,
      mtd_usd: Number(mtdUsd.toFixed(4)),
      projected_usd: Number(projectedUsd.toFixed(2)),
      pct_of_budget: budgetUsd ? Number((mtdUsd / budgetUsd).toFixed(4)) : 0,
      recent_days: recent,
    })
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 })
  }
}
