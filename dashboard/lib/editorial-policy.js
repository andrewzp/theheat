import { fingerprint } from "./draft-revisions.js"
import { EDITORIAL_POLICY_MANIFEST } from "./editorial-policy-manifest.js"
import { buildRuntimeConfig } from "./runtime-inventory.js"

const MODEL_KEYS = ["critic", "fact_check", "safety", "writer", "writer_provider"]
const FLAG_KEYS = ["critic_enabled", "critic_revise_enabled", "safety_llm_enabled", "writer_samples"]
const keysEqual = (object, keys) => object && typeof object === "object" && !Array.isArray(object)
  && JSON.stringify(Object.keys(object).sort()) === JSON.stringify(keys)

export function validEditorialPolicy(value) {
  return keysEqual(value, ["execution_sha256", "flags", "models", "schema_version", "source_sha256"])
    && typeof value.execution_sha256 === "string" && /^[a-f0-9]{64}$/.test(value.execution_sha256)
    && value.schema_version === 1 && typeof value.source_sha256 === "string" && /^[a-f0-9]{64}$/.test(value.source_sha256)
    && keysEqual(value.models, MODEL_KEYS) && Object.values(value.models).every((v) => typeof v === "string" && v.length > 0 && v.length <= 160)
    && keysEqual(value.flags, FLAG_KEYS)
    && FLAG_KEYS.filter((k) => k !== "writer_samples").every((k) => typeof value.flags[k] === "boolean")
    && Number.isSafeInteger(value.flags.writer_samples) && value.flags.writer_samples >= 1 && value.flags.writer_samples <= 100
}

export function dashboardEditorialPolicy(state, { now = Date.now(), runtimeReport = null } = {}) {
  const runtime = buildRuntimeConfig(state, { now, runtimeReport })
  const value = runtime.editorial_policy
  if (runtime.status !== "recorded" || !validEditorialPolicy(value)
      || value.source_sha256 !== EDITORIAL_POLICY_MANIFEST.source_sha256) {
    return { status: "unverified", policy: null,
      reason: "Editorial policy unverified: a fresh bot report matching this dashboard's policy is required. No current review is established." }
  }
  if (runtime.report_kind === "configuration_only" && (
      runtime.writer_model !== value.models.writer || runtime.writer_provider !== value.models.writer_provider
      || runtime.fact_check_model !== value.models.fact_check || runtime.critic_model !== value.models.critic
      || runtime.safety_model !== value.models.safety
      || runtime.flags.writer_samples !== value.flags.writer_samples
      || runtime.flags.critic_enabled !== value.flags.critic_enabled
      || runtime.flags.critic_revise_enabled !== value.flags.critic_revise_enabled
      || runtime.credentials_present.safety_gemini !== value.flags.safety_llm_enabled)) {
    return { status: "unverified", policy: null, reason: "Configuration report disagrees with its captured editorial policy." }
  }
  return { status: "recorded", policy: value, policy_sha256: fingerprint(value), captured_at: runtime.captured_at,
    reason: "Review intent uses the latest matching bot policy report. The sender rechecks its current policy before posting." }
}
