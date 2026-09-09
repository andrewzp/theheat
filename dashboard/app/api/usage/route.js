import { readStateStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"
import { summarizeUsage, validUsageDay } from "../../../lib/usage-ledger.js"

export const runtime = "nodejs"

// Recorded estimate subtotals, never total account spend or enforcement.
const RECENT_DAYS = 14
const DEFAULT_BUDGET_USD = 14.0

function monthlyBudgetUsd() {
  const raw = Number(process.env.THEHEAT_MONTHLY_BUDGET_USD)
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_BUDGET_USD
}

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  try {
    const state = await readStateStore()
    const ledger = state.llm_usage && typeof state.llm_usage === "object" ? state.llm_usage : {}
    const now = new Date()
    const monthPrefix = now.toISOString().slice(0, 8)
    const daysInMonth = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0)).getUTCDate()
    const summary = summarizeUsage(state, { now: now.getTime() })
    const mtdUsd = summary.recorded_estimate_usd
    const budgetUsd = monthlyBudgetUsd()
    const projectedUsd = mtdUsd === null ? null : (mtdUsd / Math.max(now.getUTCDate(), 1)) * daysInMonth
    const pct = mtdUsd === null ? null : mtdUsd / budgetUsd
    const recent = Object.keys(ledger)
      .filter((day) => validUsageDay(day) && day <= now.toISOString().slice(0, 10))
      .sort().slice(-RECENT_DAYS)
      .map((day) => {
        const coverage = summarizeUsage({ llm_usage: { [day]: ledger[day] } }, { now: Date.parse(`${day}T23:59:59Z`) })
        return { day, ...coverage, usd: coverage.recorded_estimate_usd,
          by_stage_model: ledger[day] && typeof ledger[day] === "object" ? ledger[day] : {} }
      })
    return Response.json({
      ...summary,
      month: monthPrefix.slice(0, 7), as_of_day: now.getUTCDate(), days_in_month: daysInMonth,
      budget_usd: budgetUsd,
      // Compatibility names represent the explicitly incomplete recorded subtotal.
      mtd_usd: mtdUsd,
      projected_usd: projectedUsd === null ? null : Number(projectedUsd.toFixed(2)),
      pct_of_budget: pct === null ? null : Number(pct.toFixed(4)),
      level: pct !== null && pct >= 0.90 ? "alarm_90" : pct !== null && pct >= 0.70 ? "warn_70" : "coverage_incomplete",
      recent_days: recent,
    })
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 })
  }
}
