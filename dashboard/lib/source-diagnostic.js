export function sourceDiagnosticClass(health) {
  if (health === "unhealthy") return "source-diagnostic-unhealthy"
  if (health === "external") return "source-diagnostic-external"
  return "source-diagnostic-degraded"
}

export function sourceDiagnosticLabel(health) {
  if (health === "unhealthy") return "last error"
  if (health === "external") return "external issue"
  return "diagnostic"
}
