"use client"

function AutomationDot({ name, color, tooltip }) {
  const colorClass = {
    green: "automation-dot-green",
    yellow: "automation-dot-yellow",
    gray: "automation-dot-gray",
    red: "automation-dot-red",
  }[color] || "automation-dot-gray"
  return (
    <span className={`automation-dot ${colorClass}`} title={tooltip}>
      <span className="automation-dot-label">{name}</span>
    </span>
  )
}

function dotColorForWorkflow(wf) {
  if (wf.error) return "red"
  if (wf.state === "disabled_manually") return "gray"
  if (wf.state === "active" && wf.last_run_conclusion === "success") return "green"
  if (wf.state === "active" && wf.last_run_conclusion === "failure") return "yellow"
  if (wf.state === "active") return "green"
  return "gray"
}

function dotColorForRoutine(routine) {
  if (!routine?.last_run_at) return "gray"
  // Routine fires daily; mark gray if last beacon older than 25h.
  const ageMs = Date.now() - new Date(routine.last_run_at).getTime()
  if (Number.isNaN(ageMs)) return "gray"
  if (ageMs > 25 * 60 * 60 * 1000) return "gray"
  if (routine.last_run_outcome === "error") return "yellow"
  return "green"
}

export function AutomationStatusStrip({ status, error }) {
  if (error) {
    return (
      <div className="automation-strip automation-strip-error">
        <span className="automation-title">Automation</span>
        <span className="automation-error">unavailable: {error}</span>
      </div>
    )
  }
  if (!status) {
    return (
      <div className="automation-strip">
        <span className="automation-title">Automation</span>
        <span className="automation-loading">loading…</span>
      </div>
    )
  }
  const workflows = status.workflows || []
  const routine = status.routine || {}
  const pm = status.posting_mode_summary

  return (
    <div className="automation-strip">
      <span className="automation-title">Automation</span>
      {workflows.map((wf) => (
        <AutomationDot
          key={wf.file}
          name={wf.name}
          color={dotColorForWorkflow(wf)}
          tooltip={`${wf.name} — state: ${wf.state}, last run: ${
            wf.last_run_at ? new Date(wf.last_run_at).toUTCString() : "never"
          }, conclusion: ${wf.last_run_conclusion || "none"}${
            wf.error ? `, ERROR: ${wf.error}` : ""
          }`}
        />
      ))}
      <AutomationDot
        name="routine"
        color={dotColorForRoutine(routine)}
        tooltip={`${routine.name || "routine"} — last run: ${
          routine.last_run_at ? new Date(routine.last_run_at).toUTCString() : "never"
        }, outcome: ${routine.last_run_outcome || "unknown"}`}
      />
      <span className="automation-spacer" />
      {pm ? (
        <span className="automation-posting-mode">
          {pm.manual_only_count ?? 0} manual / {pm.armed_auto_count ?? 0} auto /{" "}
          {pm.suggested_count ?? 0} suggested
        </span>
      ) : (
        <span className="automation-posting-mode automation-posting-mode-error" title={status.posting_mode_error || ""}>
          posting status unavailable
        </span>
      )}
    </div>
  )
}
