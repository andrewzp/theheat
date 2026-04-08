"use client"

import { useEffect, useState, useCallback } from "react"

function timeAgo(dateStr) {
  if (!dateStr) return "never"
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function RunStatus({ conclusion, status }) {
  if (status === "in_progress") return <span className="badge running">RUNNING</span>
  if (conclusion === "success") return <span className="badge success">OK</span>
  if (conclusion === "failure") return <span className="badge failure">FAIL</span>
  return <span className="badge neutral">{conclusion || status}</span>
}

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(null)
  const [triggerResult, setTriggerResult] = useState(null)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/state")
      setData(await res.json())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  async function trigger(mode) {
    setTriggering(mode)
    setTriggerResult(null)
    try {
      const res = await fetch("/api/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      })
      const result = await res.json()
      setTriggerResult(result.ok ? `Triggered ${mode}` : `Error: ${result.error}`)
      setTimeout(fetchData, 5000)
    } catch (e) {
      setTriggerResult(`Error: ${e.message}`)
    } finally {
      setTriggering(null)
    }
  }

  const state = data?.state
  const runs = data?.runs || []
  const hot10 = state?.last_hot10 || {}
  const streaks = state?.streaks || {}
  const errors = state?.errors || []
  const pending = state?.pending_confirmations || []
  const todayCount = state?.daily_tweet_count
    ? Object.values(state.daily_tweet_count)[0] || 0
    : 0

  const sortedStreaks = Object.entries(streaks)
    .sort((a, b) => b[1].consecutive_days - a[1].consecutive_days)
    .slice(0, 10)

  return (
    <>
      <style jsx global>{`
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          font-family: "SF Mono", "Fira Code", "Consolas", monospace;
          background: #0a0a0a;
          color: #e0e0e0;
          min-height: 100vh;
        }
        .dash {
          max-width: 960px;
          margin: 0 auto;
          padding: 24px 16px;
        }
        header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 32px;
          padding-bottom: 16px;
          border-bottom: 1px solid #222;
        }
        h1 {
          font-size: 20px;
          font-weight: 600;
          color: #ff4d00;
        }
        h1 span { color: #666; font-weight: 400; font-size: 14px; margin-left: 8px; }
        .refresh-btn {
          background: none;
          border: 1px solid #333;
          color: #888;
          padding: 6px 12px;
          border-radius: 4px;
          cursor: pointer;
          font-family: inherit;
          font-size: 12px;
        }
        .refresh-btn:hover { border-color: #555; color: #ccc; }

        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
        @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }

        .card {
          background: #111;
          border: 1px solid #222;
          border-radius: 8px;
          padding: 16px;
        }
        .card h2 {
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 1px;
          color: #666;
          margin-bottom: 12px;
        }
        .card.full { grid-column: 1 / -1; }

        .stat { font-size: 28px; font-weight: 700; color: #ff4d00; }
        .stat-label { font-size: 12px; color: #666; margin-top: 4px; }

        .hot10-list { list-style: none; }
        .hot10-list li {
          display: flex;
          justify-content: space-between;
          padding: 4px 0;
          border-bottom: 1px solid #1a1a1a;
          font-size: 13px;
        }
        .hot10-list li:last-child { border-bottom: none; }
        .rank { color: #666; width: 24px; }
        .city { flex: 1; }
        .anomaly { color: #ff4d00; font-weight: 600; }

        .streak-list { display: flex; flex-wrap: wrap; gap: 8px; }
        .streak-chip {
          background: #1a1a1a;
          padding: 4px 10px;
          border-radius: 4px;
          font-size: 12px;
        }
        .streak-chip .days { color: #ff4d00; font-weight: 600; }

        .runs-table { width: 100%; font-size: 12px; }
        .runs-table th {
          text-align: left;
          color: #444;
          font-weight: 400;
          padding: 4px 8px 8px 0;
        }
        .runs-table td { padding: 6px 8px 6px 0; border-top: 1px solid #1a1a1a; }
        .runs-table a { color: #888; text-decoration: none; }
        .runs-table a:hover { color: #ff4d00; }

        .badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 3px;
          font-size: 10px;
          font-weight: 600;
          letter-spacing: 0.5px;
        }
        .badge.success { background: #0a2a0a; color: #4ade80; }
        .badge.failure { background: #2a0a0a; color: #f87171; }
        .badge.running { background: #1a1a0a; color: #facc15; }
        .badge.neutral { background: #1a1a1a; color: #888; }

        .error-list { list-style: none; max-height: 200px; overflow-y: auto; }
        .error-list li {
          font-size: 12px;
          padding: 6px 0;
          border-bottom: 1px solid #1a1a1a;
        }
        .error-source { color: #f87171; font-weight: 600; }
        .error-ts { color: #444; margin-left: 8px; }
        .error-msg { color: #888; display: block; margin-top: 2px; }

        .trigger-bar {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .trigger-btn {
          background: #1a1a1a;
          border: 1px solid #333;
          color: #e0e0e0;
          padding: 8px 16px;
          border-radius: 4px;
          cursor: pointer;
          font-family: inherit;
          font-size: 12px;
          font-weight: 600;
        }
        .trigger-btn:hover { border-color: #ff4d00; color: #ff4d00; }
        .trigger-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .trigger-btn.primary { background: #ff4d00; border-color: #ff4d00; color: #000; }
        .trigger-btn.primary:hover { background: #ff6620; }
        .trigger-result { font-size: 12px; color: #4ade80; }

        .pending-list { list-style: none; font-size: 12px; }
        .pending-list li { padding: 4px 0; color: #888; }
        .pending-city { color: #facc15; }

        .empty { color: #333; font-size: 13px; font-style: italic; }
        .loading { text-align: center; color: #333; padding: 60px; font-size: 14px; }
      `}</style>

      <div className="dash">
        <header>
          <h1>@theheat <span>control panel</span></h1>
          <button className="refresh-btn" onClick={fetchData}>refresh</button>
        </header>

        {loading ? (
          <div className="loading">loading...</div>
        ) : (
          <>
            {/* Trigger Controls */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Manual Trigger</h2>
              <div className="trigger-bar">
                <button
                  className="trigger-btn primary"
                  disabled={!!triggering}
                  onClick={() => trigger("both")}
                >
                  {triggering === "both" ? "..." : "Run Both"}
                </button>
                <button
                  className="trigger-btn"
                  disabled={!!triggering}
                  onClick={() => trigger("alerts")}
                >
                  {triggering === "alerts" ? "..." : "Alerts Only"}
                </button>
                <button
                  className="trigger-btn"
                  disabled={!!triggering}
                  onClick={() => trigger("leaderboard")}
                >
                  {triggering === "leaderboard" ? "..." : "Leaderboard Only"}
                </button>
                {triggerResult && <span className="trigger-result">{triggerResult}</span>}
              </div>
            </div>

            {/* Stats Row */}
            <div className="grid">
              <div className="card">
                <h2>Tweets Today</h2>
                <div className="stat">{todayCount}</div>
                <div className="stat-label">of 10 daily cap</div>
              </div>
              <div className="card">
                <h2>Last Hot 10</h2>
                <div className="stat">{hot10.date || "—"}</div>
                <div className="stat-label">
                  {hot10.date ? timeAgo(hot10.date + "T12:00:00Z") : "no data yet"}
                </div>
              </div>
            </div>

            <div className="grid">
              {/* Hot 10 Leaderboard */}
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

              {/* Streaks */}
              <div className="card">
                <h2>Streaks</h2>
                {sortedStreaks.length > 0 ? (
                  <div className="streak-list">
                    {sortedStreaks.map(([city, s]) => (
                      <span className="streak-chip" key={city}>
                        {city} <span className="days">{s.consecutive_days}d</span>
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="empty">no active streaks</div>
                )}
              </div>
            </div>

            {/* Pending NOAA Confirmations */}
            {pending.length > 0 && (
              <div className="card full" style={{ marginBottom: 16 }}>
                <h2>Pending NOAA Confirmations</h2>
                <ul className="pending-list">
                  {pending.map((p) => (
                    <li key={p.event_id}>
                      <span className="pending-city">{p.city}</span> — detected {p.detected}, waiting for NOAA
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recent Runs */}
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
                <div className="empty">no runs yet — trigger one above or wait for cron</div>
              )}
            </div>

            {/* Errors */}
            <div className="card full">
              <h2>Recent Errors</h2>
              {errors.length > 0 ? (
                <ul className="error-list">
                  {errors.slice(-10).reverse().map((e, i) => (
                    <li key={i}>
                      <span className="error-source">{e.source}</span>
                      <span className="error-ts">{timeAgo(e.ts)}</span>
                      <span className="error-msg">{e.msg}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty">no errors. suspicious.</div>
              )}
            </div>
          </>
        )}
      </div>
    </>
  )
}
