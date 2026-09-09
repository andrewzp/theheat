import { buildRuntimeConfig } from "./runtime-inventory.js"

export function validPublicationEpoch(value) {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{7,95}$/.test(value)
}

export function mergePublicationControl(current, incoming) {
  const retired = new Set()
  const rows = []
  let invalid = false
  for (const value of [current, incoming]) {
    if (value == null) continue
    if (typeof value !== "object" || Array.isArray(value)) { invalid = true; continue }
    const epochs = Object.hasOwn(value, "retired_epochs") ? value.retired_epochs : []
    if (!Array.isArray(epochs) || epochs.some((epoch) => !validPublicationEpoch(epoch))) invalid = true
    else epochs.forEach((epoch) => retired.add(epoch))
    invalid ||= value.invalid_control === true
    if (value.observed_at) rows.push(value)
  }
  const latest = rows.sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at))).at(-1) || {}
  return { ...Object.fromEntries(["observed_at", "epoch", "enabled", "reason"].filter((key) => Object.hasOwn(latest, key)).map((key) => [key, latest[key]])),
    retired_epochs: [...retired].sort(), ...(invalid ? { invalid_control: true } : {}) }
}

export function configuredAutomaticPolicy(env = process.env) {
  const epoch = validPublicationEpoch(env.THEHEAT_AUTOMATIC_PUBLICATION_EPOCH) ? env.THEHEAT_AUTOMATIC_PUBLICATION_EPOCH : null
  return { enabled: env.THEHEAT_AUTOMATIC_PUBLICATION_ENABLED === "1" && epoch !== null, epoch }
}

export function dashboardAutomaticPolicy(state, { now = Date.now(), env = process.env } = {}) {
  const configured = configuredAutomaticPolicy(env)
  const control = mergePublicationControl(state?.publication_control, null)
  const runtime = buildRuntimeConfig(state, { now })
  const enabled = configured.enabled && !control.invalid_control && !control.retired_epochs.includes(configured.epoch)
    && runtime.status === "recorded" && runtime.flags.automatic_publication_enabled === true
    && runtime.flags.automatic_publication_epoch === configured.epoch
  return { enabled, epoch: configured.epoch,
    reason: enabled ? "Automatic scheduling available for the current release epoch."
      : "Automatic publication is paused or its current release is unverified. Keep reviewing drafts; scheduling returns after the release checks pass." }
}
