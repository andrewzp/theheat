import registry from "./source-registry.json" with { type: "json" }

const byHealthKey = new Map()
for (const row of registry.sources) {
  for (const key of row.health_keys) {
    if (byHealthKey.has(key)) throw new Error("Ambiguous source registry")
    byHealthKey.set(key, row)
  }
}
const telemetry = new Set(registry.telemetry_keys)

export function sourceContract(source) {
  const row = typeof source === "string" ? byHealthKey.get(source) : null
  if (!row) return {
    registered: false,
    kind: telemetry.has(source) ? "internal" : "unregistered",
    claim_permission_granted: false,
  }
  return {
    registered: true,
    registry_sha256: registry.registry_sha256,
    source_id: row.source_id,
    kind: row.kind,
    scope: row.scope,
    data_family: row.data_family,
    provenance: row.provenance,
    collection_rule: row.collection_rule,
    time_rule: row.time_rule,
    claim_limit: row.claim_limit,
    claim_policy: registry.claim_policy,
    claim_permission_granted: false,
    provider_quota: null,
    reuse_rights: null,
    current_availability: "unverified",
    unknown_limits: [...registry.unknown_limits],
  }
}

export function sourceInventory(savedKeys) {
  // This denominator describes wired code only, never geographic/event coverage.
  const bounded = Array.isArray(savedKeys) && savedKeys.length <= 4096
  const keys = bounded ? new Set(savedKeys.filter(key => typeof key === "string")) : null
  return {
    schema_version: registry.schema_version,
    registry_sha256: registry.registry_sha256,
    scope: registry.purpose,
    wired_collectors: registry.sources.length,
    named_health_keys: byHealthKey.size,
    saved_key_coverage: bounded ? "supplied_saved_keys_only" : "unknown_bound_or_shape",
    wired_without_saved_rows: keys ? registry.sources.filter(row => !row.health_keys.some(key => keys.has(key))).map(row => row.source_id) : null,
    unregistered_saved_keys: keys ? [...keys].filter(key => !byHealthKey.has(key) && !telemetry.has(key)).length : null,
    internal_saved_keys: keys ? [...keys].filter(key => telemetry.has(key)).length : null,
    current_availability: "unverified",
    effective_activation: null,
    coverage_denominator: null,
    claim_permission_granted: false,
  }
}
