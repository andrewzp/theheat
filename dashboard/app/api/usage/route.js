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
      if (typeof day === "string" && day.startsWith(monthPrefix)) {
        mtdUsd += dayTotalUsd(bucket)
      }
    }
    const budgetUsd = monthlyBudgetUsd()
    const projectedUsd = (mtdUsd / Math.max(now.getUTCDate(), 1)) * daysInMonth

    const recent = Object.keys(ledger)
      .sort()
      .slice(-RECENT_DAYS)
      .map((day) => ({
        day,
        usd: Number(dayTotalUsd(ledger[day]).toFixed(4)),
        by_stage_model: ledger[day] && typeof ledger[day] === "object" ? ledger[day] : {},
      }))

    return Response.json({
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
