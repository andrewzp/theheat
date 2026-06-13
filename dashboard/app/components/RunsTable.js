"use client"

import { timeAgo } from "../../lib/format.js"
import { RunStatus } from "./Badge.js"

export function RunsTable({ runs }) {
  return (
    <div className="card full" style={{ marginBottom: 16 }}>
      <h2>Recent Runs</h2>
      {runs.length > 0 ? (
        <table className="runs-table">
          <thead>
            <tr><th>Status</th><th>Trigger</th><th>When</th><th>Link</th></tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td><RunStatus conclusion={r.conclusion} status={r.status} /></td>
                <td>{r.event === "schedule" ? "cron" : r.event}</td>
                <td>{timeAgo(r.created_at)}</td>
                <td><a href={r.html_url} target="_blank" rel="noopener">logs</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="empty">no runs yet</div>
      )}
    </div>
  )
}
