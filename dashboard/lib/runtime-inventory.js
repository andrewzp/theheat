// Bot settings come from the bot process, never from the dashboard's environment.
export const RUNTIME_MAX_AGE_HOURS = 6
const FLAG_KEYS = [
  "automatic_publication_enabled", "automatic_publication_epoch", "automatic_publication_reason",
  "autoship_on_critic_pass", "autoship_max_age_hours", "critic_enabled",
  "critic_revise_enabled", "writer_samples", "triage_enabled", "refill_enabled",
  "funnel_telemetry", "concurrent_sources", "metrics_enabled", "reganom_enabled",
  "records_cluster_enabled", "newsworthiness_enabled", "news_enrich_enabled",
  "news_boost_enabled", "engagement_window_enabled", "shadow_ab_enabled",
  "signals_provider", "gpm_source", "aq_pm25_enabled", "aq_dust_enabled", "wetbulb_enabled",
]
const CREDENTIAL_KEYS = ["anthropic", "gemini", "safety_gemini", "twitter", "bluesky", "nasa_firms", "earthdata", "github_state"]

function text(value) {
  return typeof value === "string" && value.trim() ? value.slice(0, 160) : null
}

function timestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return NaN
  const calendar = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  if (!Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== value.slice(0, 10)) return NaN
  if (Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59) return NaN
  return Date.parse(value)
}

function sha(value) {
  return typeof value === "string" && /^[a-f0-9]{40,64}$/i.test(value) ? value : null
}

export function buildRuntimeConfig(state = {}, { now = Date.now() } = {}) {
  const result = {
    status: "unknown", captured_at: null, age_hours: null, run_id: null, mode: null,
    reason: "No bot runtime inventory is recorded. Settings cannot be inferred from the dashboard server.",
    bot_git_sha: null, bot_version: null, state_backend: null,
    writer_model: null, writer_provider: null, fact_check_model: null,
    critic_model: null, safety_model: null, claim_extract_model: null,
    editorial_policy: null, flags: {}, credentials_present: {}, capabilities: {},
  }
  const history = Array.isArray(state?.run_history) ? state.run_history : []
  const latest = [...history].filter((run) => Number.isFinite(timestamp(run?.started_at)))
    .sort((a, b) => timestamp(b.started_at) - timestamp(a.started_at))[0]
  if (!latest) return result
  // A newer uninstrumented run must not inherit an older run's settings.
  const snapshot = latest.runtime_inventory
  if (!snapshot || snapshot.schema_version !== 1) return result
  const capturedAt = timestamp(snapshot.captured_at)
  if (!Number.isFinite(capturedAt) || capturedAt > now || timestamp(latest.started_at) > now || capturedAt < timestamp(latest.started_at)) {
    return { ...result, reason: "The latest bot inventory has an invalid or future timestamp." }
  }
  const ageHours = (now - capturedAt) / 3600000
  const flags = Object.fromEntries(FLAG_KEYS.flatMap((key) => {
    const value = snapshot.flags?.[key]
    return typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value)) || text(value)
      ? [[key, typeof value === "string" ? text(value) : value]] : []
  }))
  return {
    ...result,
    status: ageHours > RUNTIME_MAX_AGE_HOURS ? "stale" : "recorded",
    captured_at: new Date(capturedAt).toISOString(), age_hours: ageHours,
    reason: ageHours > RUNTIME_MAX_AGE_HOURS
      ? `Last bot report is older than ${RUNTIME_MAX_AGE_HOURS} hours; present settings are unverified.`
      : "Settings reported by this bot invocation; credentials and provider credits are not verified.",
    run_id: text(latest.id || latest.run_id), mode: text(snapshot.mode),
    bot_git_sha: sha(snapshot.git_sha), bot_version: text(snapshot.version),
    state_backend: text(snapshot.state_backend),
    editorial_policy: snapshot.editorial_policy ?? null,
    writer_model: text(snapshot.models?.writer), writer_provider: text(snapshot.models?.writer_provider),
    fact_check_model: text(snapshot.models?.fact_check), critic_model: text(snapshot.models?.critic),
    safety_model: text(snapshot.models?.safety), claim_extract_model: text(snapshot.models?.claim_extract),
    flags,
    credentials_present: Object.fromEntries(CREDENTIAL_KEYS.flatMap((key) =>
      typeof snapshot.credentials_present?.[key] === "boolean" ? [[key, snapshot.credentials_present[key]]] : [])),
    capabilities: Object.fromEntries(["claim_extraction", "legacy_voice_generation", "safety_llm"].flatMap((key) =>
      text(snapshot.capabilities?.[key]) ? [[key, text(snapshot.capabilities[key])]] : [])),
  }
}

export function dashboardDeployment(env = process.env) {
  return {
    git_sha: sha(env.VERCEL_GIT_COMMIT_SHA),
    environment: text(env.VERCEL_ENV) || "local / unknown",
  }
}

export function summarizeSourceAttempts(sources) {
  const rows = Array.isArray(sources) ? sources : []
  const succeeded = rows.filter((row) => row?.status === "success").length
  const skipped = rows.filter((row) => row?.status === "skipped").length
  const active = rows.filter((row) => ["success", "failed", "partial_failure", "degraded"].includes(row?.status)).length
  return { succeeded, skipped, active, unknown: rows.length - active - skipped, success_rate: active ? succeeded / active : null }
}
