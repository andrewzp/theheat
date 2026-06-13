"use client"

import { timeAgo } from "../../lib/format.js"

export function Hot10Card({ hot10, hot10Stale, hot10StaleAgeDays }) {
  return (
    <div className="card">
      <h2>Last Hot 10</h2>
      <div className="stat stat-with-chip">
        <span>{hot10.date || "—"}</span>
        {hot10Stale && (
          <span className="badge running hot10-stale-chip">(stale {hot10StaleAgeDays}d)</span>
        )}
      </div>
      <div className="stat-label">
        {hot10.date ? timeAgo(hot10.date + "T12:00:00Z") : "no data yet"}
      </div>
    </div>
  )
}

export function Hot10Leaderboard({ hot10 }) {
  return (
    <div className="card">
      <h2>Hot 10 Leaderboard</h2>
      {hot10.cities?.length > 0 ? (
        <ul className="hot10-list">
          {hot10.cities.map((city, i) => (
            <li key={city}>
              <span className="rank">{i + 1}.</span>
              <span className="city">{city}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty">no leaderboard data yet</div>
      )}
    </div>
  )
}
