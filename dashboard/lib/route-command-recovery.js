// Browser-safe P00c follow-up for one submitted serialized-route command. It reports the
// consumer's real outcome (applied / refused) and resubmits the SAME retained bytes only after
// an uncertain (lost) submission whose command is still unknown. Never synthesizes success.
export async function followRouteCommand(saved, { fetchImpl = globalThis.fetch, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  attempts = 6, delayMs = 20000 } = {}) {
  let uncertain = saved.status === "submission_uncertain"
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await sleep(delayMs)
    let status
    try {
      const response = await fetchImpl(`/api/commands/${encodeURIComponent(saved.command_id)}?digest=${encodeURIComponent(saved.digest)}`, { cache: "no-store" })
      status = await response.json()
    } catch { continue }
    if (status.status === "applied" || status.status === "refused") return status
    if (status.status === "pending") { uncertain = false; continue }
    if (status.status === "unknown" && uncertain && typeof saved.command === "string") {
      try {
        const response = await fetchImpl("/api/commands", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: saved.command }) })
        const body = await response.json()
        if (response.ok && body.status === "pending") uncertain = false
      } catch { /* Still uncertain: check again before any further resubmission. */ }
    }
  }
  return { command_id: saved.command_id, status: uncertain ? "unknown" : "pending" }
}

export function routeCommandMessage(status) {
  if (status.status === "applied") return { type: "success", text: "The serialized writer applied this change." }
  if (status.status === "refused") return { type: "error", text: `The serialized writer refused this change (${status.code}). Refresh and review the latest version.` }
  if (status.status === "pending") return { type: "success", text: "Submitted; it applies after the current bot run finishes. Refresh later to see it." }
  return { type: "error", text: "This submission could not be confirmed. Refresh before retrying; nothing is assumed saved." }
}
