"use client"

import { credentialRows } from "../../lib/credential-status.js"

// Counters so a credential's expiry is visible BEFORE it silently breaks a
// source (the 2026-06-23 NASA Earthdata 401 outage). Soonest-to-expire on top;
// green > 14d, amber <= 14d, red <= 3d or expired. Exact date on hover.
export function CredentialsCard({ credentialExpiry, nowMs }) {
  const rows = credentialRows(credentialExpiry, nowMs)
  return (
    <div className="card">
      <h2>Credentials</h2>
      {rows.length === 0 ? (
        <div className="stat-label">no credentials tracked yet</div>
      ) : (
        rows.map((r) => (
          <div
            key={r.name}
            className="stat stat-with-chip"
            title={r.expiresAt ? `${r.name} expires ${r.expiresAt}` : `${r.name}: expiry unknown`}
          >
            <span>{r.label}</span>
            <span className={`badge ${r.badgeClass}`}>
              {r.daysLeft === null ? "—" : r.daysLeft < 0 ? "EXPIRED" : `${r.daysLeft}d left`}
            </span>
          </div>
        ))
      )}
    </div>
  )
}
