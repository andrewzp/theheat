import { readStateStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"

export const runtime = "nodejs"

// Phase A funnel telemetry view. Reads the per-run `funnel` objects frozen onto
// run_history (NOT source_health — codex must-fix #2: source_health rows are
// written with drafted=0 at source-runner time and undercount), sums them over
// a trailing window, and derives pass/kill rates.
//
// Denominator math MUST stay in sync with src/orchestrator/funnel.py
// (funnel_rates / rollup_funnels). Per pass-stage: attempts = passes + kills,
// pass_rate = passes / attempts (null when no attempts).

const WINDOW_DAYS = 7
const PASS_STAGES = ["writer", "fact_check", "critic"]
const VOLUME_KEYS = [
  "observed",
  "promoted",
  "triaged_in",
  "triaged_out",
  "billing_aborted",
  "writer_attempted",
  "drafted",
]
const MAX_RECENT_SLATES = 5

function tsValue(run) {
  const raw = run?.ended_at || run?.started_at
  if (!raw) return 0
  const parsed = Date.parse(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

function emptyFunnel() {
  const funnel = {}
  for (const key of VOLUME_KEYS) funnel[key] = 0
  funnel.passes = { writer: 0, fact_check: 0, critic: 0 }
  funnel.kills = {}
  return funnel
}

function rollupFunnels(runs) {
  const rollup = emptyFunnel()
  let counted = 0
  for (const run of runs) {
    const funnel = run?.funnel
    if (!funnel || typeof funnel !== "object") continue
    counted += 1
    for (const key of VOLUME_KEYS) {
      rollup[key] += Number(funnel[key]) || 0
    }
    const passes = funnel.passes || {}
    for (const stage of PASS_STAGES) {
      rollup.passes[stage] += Number(passes[stage]) || 0
    }
    const kills = funnel.kills || {}
    for (const [stage, count] of Object.entries(kills)) {
      rollup.kills[stage] = (rollup.kills[stage] || 0) + (Number(count) || 0)
    }
  }
  return { rollup, counted }
}

function rate(passes, kills) {
  const attempts = passes + kills
  return attempts === 0 ? null : passes / attempts
}

function funnelRates(funnel) {
  const passes = funnel.passes || {}
  const kills = funnel.kills || {}
  const stages = {}
  for (const stage of PASS_STAGES) {
    const p = Number(passes[stage]) || 0
    const k = Number(kills[stage]) || 0
    stages[stage] = {
      passes: p,
      kills: k,
      attempts: p + k,
      pass_rate: rate(p, k),
      kill_rate: p + k === 0 ? null : k / (p + k),
    }
  }
  const triagedIn = Number(funnel.triaged_in) || 0
  const triagedOut = Number(funnel.triaged_out) || 0
  // Billing-aborted candidates were skipped by the circuit breaker, not cut
  // by triage — mirror of src/orchestrator/funnel.py funnel_rates.
  const billingAborted = Number(funnel.billing_aborted) || 0
  const triageCut = Math.max(triagedIn - triagedOut - billingAborted, 0)
  const writerAttempted = Number(funnel.writer_attempted) || 0
  const drafted = Number(funnel.drafted) || 0
  return {
    critic_pass_rate: stages.critic.pass_rate,
    writer_pass_rate: stages.writer.pass_rate,
    fact_check_pass_rate: stages.fact_check.pass_rate,
    stages,
    triage_cut: triageCut,
    triage_cap_rate: triagedIn === 0 ? null : triageCut / triagedIn,
    billing_aborted: billingAborted,
    draft_yield: writerAttempted === 0 ? null : drafted / writerAttempted,
  }
}

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }
  try {
    const state = await readStateStore()
    const runs = Array.isArray(state.run_history) ? state.run_history : []

    const cutoff = Date.now() - WINDOW_DAYS * 24 * 60 * 60 * 1000
    const windowRuns = runs.filter((run) => tsValue(run) >= cutoff)

    const { rollup, counted } = rollupFunnels(windowRuns)
    const rates = funnelRates(rollup)

    const recentSlates = windowRuns
      .filter((run) => Array.isArray(run.shadow_slate))
      .slice(0, MAX_RECENT_SLATES)
      .map((run) => ({
        run_id: run.id || null,
        started_at: run.started_at || null,
        slate: run.shadow_slate,
      }))

    return Response.json({
      window_days: WINDOW_DAYS,
      runs_counted: counted,
      funnel: rollup,
      rates,
      recent_slates: recentSlates,
    })
  } catch (e) {
    return Response.json({ funnel: null, rates: null, error: e.message }, { status: 500 })
  }
}
