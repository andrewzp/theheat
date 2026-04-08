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

  // Drafts
  const [drafts, setDrafts] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [editText, setEditText] = useState("")
  const [draftAction, setDraftAction] = useState(null)

  // Compose
  const [composePrompt, setComposePrompt] = useState("")
  const [composeTweet, setComposeTweet] = useState("")
  const [generating, setGenerating] = useState(false)
  const [posting, setPosting] = useState(false)
  const [composeStatus, setComposeStatus] = useState(null)

  const fetchData = useCallback(async () => {
    try {
      const [stateRes, draftsRes] = await Promise.all([
        fetch("/api/state"),
        fetch("/api/drafts"),
      ])
      setData(await stateRes.json())
      const d = await draftsRes.json()
      setDrafts(d.drafts || [])
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

  async function draftAct(draftId, action, editedText) {
    setDraftAction(draftId)
    try {
      const res = await fetch("/api/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, draftId, editedText }),
      })
      await res.json()
      setEditingId(null)
      setEditText("")
      await fetchData()
    } catch (e) {
      console.error(e)
    } finally {
      setDraftAction(null)
    }
  }

  async function generateTweet() {
    setGenerating(true)
    setComposeStatus(null)
    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: composePrompt }),
      })
      const result = await res.json()
      if (result.tweet) {
        setComposeTweet(result.tweet)
      } else {
        setComposeStatus(`Error: ${result.error}`)
      }
    } catch (e) {
      setComposeStatus(`Error: ${e.message}`)
    } finally {
      setGenerating(false)
    }
  }

  async function postComposed() {
    if (!composeTweet.trim()) return
    setPosting(true)
    setComposeStatus(null)
    try {
      const res = await fetch("/api/post", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tweet: composeTweet.trim() }),
      })
      const result = await res.json()
      if (result.ok) {
        setComposeStatus("Sent to post queue")
        setComposeTweet("")
        setComposePrompt("")
        setTimeout(fetchData, 5000)
      } else {
        setComposeStatus(`Error: ${result.error}`)
      }
    } catch (e) {
      setComposeStatus(`Error: ${e.message}`)
    } finally {
      setPosting(false)
    }
  }

  const state = data?.state
  const runs = data?.runs || []
  const hot10 = state?.last_hot10 || {}
  const streaks = state?.streaks || {}
  const errors = state?.errors || []
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
        .dash { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
        header {
          display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 32px; padding-bottom: 16px; border-bottom: 1px solid #222;
        }
        h1 { font-size: 20px; font-weight: 600; color: #ff4d00; }
        h1 span { color: #666; font-weight: 400; font-size: 14px; margin-left: 8px; }
        .refresh-btn {
          background: none; border: 1px solid #333; color: #888;
          padding: 6px 12px; border-radius: 4px; cursor: pointer;
          font-family: inherit; font-size: 12px;
        }
        .refresh-btn:hover { border-color: #555; color: #ccc; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
        @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
        .card {
          background: #111; border: 1px solid #222; border-radius: 8px; padding: 16px;
        }
        .card h2 {
          font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
          color: #666; margin-bottom: 12px;
        }
        .card.full { grid-column: 1 / -1; }
        .stat { font-size: 28px; font-weight: 700; color: #ff4d00; }
        .stat-label { font-size: 12px; color: #666; margin-top: 4px; }

        /* Drafts */
        .draft-item {
          background: #0a0a0a; border: 1px solid #222; border-radius: 6px;
          padding: 14px; margin-bottom: 10px;
        }
        .draft-item.highlight { border-color: #ff4d00; }
        .draft-meta {
          display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 8px; font-size: 11px;
        }
        .draft-type {
          background: #1a1a1a; color: #888; padding: 2px 8px;
          border-radius: 3px; text-transform: uppercase; letter-spacing: 0.5px;
        }
        .draft-time { color: #444; }
        .draft-text { font-size: 15px; line-height: 1.5; color: #fff; margin-bottom: 10px; }
        .draft-chars { font-size: 11px; color: #666; margin-bottom: 10px; }
        .draft-chars.over { color: #f87171; }
        .draft-actions { display: flex; gap: 8px; }
        .draft-edit-area {
          width: 100%; background: #111; border: 1px solid #333; border-radius: 4px;
          color: #fff; font-family: inherit; font-size: 14px; padding: 10px;
          resize: vertical; margin-bottom: 8px;
        }
        .draft-edit-area:focus { outline: none; border-color: #ff4d00; }
        .draft-empty { color: #333; font-size: 13px; font-style: italic; padding: 20px 0; }

        /* Buttons */
        .trigger-bar { display: flex; gap: 8px; align-items: center; }
        .btn {
          background: #1a1a1a; border: 1px solid #333; color: #e0e0e0;
          padding: 8px 16px; border-radius: 4px; cursor: pointer;
          font-family: inherit; font-size: 12px; font-weight: 600;
        }
        .btn:hover { border-color: #ff4d00; color: #ff4d00; }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .btn.primary { background: #ff4d00; border-color: #ff4d00; color: #000; }
        .btn.primary:hover { background: #ff6620; }
        .btn.approve { background: #0a2a0a; border-color: #4ade80; color: #4ade80; }
        .btn.approve:hover { background: #0f3a0f; }
        .btn.reject { background: #1a1010; border-color: #666; color: #888; }
        .btn.sm { padding: 5px 10px; font-size: 11px; }
        .trigger-result { font-size: 12px; color: #4ade80; }

        /* Compose */
        .compose { display: flex; flex-direction: column; gap: 10px; }
        .compose-input {
          background: #0a0a0a; border: 1px solid #333; border-radius: 4px;
          color: #e0e0e0; font-family: inherit; font-size: 13px; padding: 10px;
          resize: vertical;
        }
        .compose-input:focus { outline: none; border-color: #ff4d00; }
        .preview-box {
          background: #0a0a0a; border: 1px solid #ff4d00; border-radius: 6px; padding: 12px;
        }
        .preview-label {
          font-size: 10px; text-transform: uppercase; letter-spacing: 1px;
          color: #ff4d00; margin-bottom: 8px; display: flex; justify-content: space-between;
        }
        .char-count { color: #4ade80; }
        .char-count.over { color: #f87171; }
        .preview-tweet {
          background: transparent; border: none; color: #fff; font-family: inherit;
          font-size: 15px; line-height: 1.5; width: 100%; resize: vertical;
          padding: 0; margin-bottom: 10px;
        }
        .preview-tweet:focus { outline: none; }
        .preview-actions { display: flex; gap: 8px; }
        .compose-status { font-size: 12px; color: #4ade80; }

        /* Tables / lists */
        .hot10-list { list-style: none; }
        .hot10-list li {
          display: flex; justify-content: space-between; padding: 4px 0;
          border-bottom: 1px solid #1a1a1a; font-size: 13px;
        }
        .hot10-list li:last-child { border-bottom: none; }
        .rank { color: #666; width: 24px; }
        .city { flex: 1; }
        .streak-list { display: flex; flex-wrap: wrap; gap: 8px; }
        .streak-chip { background: #1a1a1a; padding: 4px 10px; border-radius: 4px; font-size: 12px; }
        .streak-chip .days { color: #ff4d00; font-weight: 600; }
        .runs-table { width: 100%; font-size: 12px; }
        .runs-table th { text-align: left; color: #444; font-weight: 400; padding: 4px 8px 8px 0; }
        .runs-table td { padding: 6px 8px 6px 0; border-top: 1px solid #1a1a1a; }
        .runs-table a { color: #888; text-decoration: none; }
        .runs-table a:hover { color: #ff4d00; }
        .badge {
          display: inline-block; padding: 2px 8px; border-radius: 3px;
          font-size: 10px; font-weight: 600; letter-spacing: 0.5px;
        }
        .badge.success { background: #0a2a0a; color: #4ade80; }
        .badge.failure { background: #2a0a0a; color: #f87171; }
        .badge.running { background: #1a1a0a; color: #facc15; }
        .badge.neutral { background: #1a1a1a; color: #888; }
        .error-list { list-style: none; max-height: 200px; overflow-y: auto; }
        .error-list li { font-size: 12px; padding: 6px 0; border-bottom: 1px solid #1a1a1a; }
        .error-source { color: #f87171; font-weight: 600; }
        .error-ts { color: #444; margin-left: 8px; }
        .error-msg { color: #888; display: block; margin-top: 2px; }
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
            {/* DRAFTS — primary view */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Drafts to Review ({drafts.length})</h2>
              {drafts.length > 0 ? (
                drafts.map((d) => (
                  <div key={d.id} className={`draft-item ${editingId === d.id ? "highlight" : ""}`}>
                    <div className="draft-meta">
                      <span className="draft-type">{d.type}</span>
                      <span className="draft-time">{timeAgo(d.created_at)}</span>
                    </div>

                    {editingId === d.id ? (
                      <>
                        <textarea
                          className="draft-edit-area"
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          rows={3}
                        />
                        <div className={`draft-chars ${editText.length > 280 ? "over" : ""}`}>
                          {editText.length}/280
                        </div>
                        <div className="draft-actions">
                          <button
                            className="btn approve sm"
                            disabled={draftAction === d.id || editText.length > 280}
                            onClick={() => draftAct(d.id, "edit", editText)}
                          >
                            Save
                          </button>
                          <button className="btn sm" onClick={() => setEditingId(null)}>
                            Cancel
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="draft-text">{d.text}</div>
                        <div className="draft-chars">{d.text.length}/280</div>
                        <div className="draft-actions">
                          <button
                            className="btn approve sm"
                            disabled={!!draftAction}
                            onClick={() => draftAct(d.id, "approve")}
                          >
                            {draftAction === d.id ? "..." : "Approve + Post"}
                          </button>
                          <button
                            className="btn sm"
                            onClick={() => { setEditingId(d.id); setEditText(d.text) }}
                          >
                            Edit
                          </button>
                          <button
                            className="btn reject sm"
                            disabled={!!draftAction}
                            onClick={() => draftAct(d.id, "reject")}
                          >
                            Reject
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))
              ) : (
                <div className="draft-empty">
                  No drafts waiting. Trigger a run below or compose one manually.
                </div>
              )}
            </div>

            {/* Generate Drafts */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Generate Drafts</h2>
              <div className="trigger-bar">
                <button
                  className="btn primary"
                  disabled={!!triggering}
                  onClick={() => trigger("both")}
                >
                  {triggering === "both" ? "..." : "Run Both"}
                </button>
                <button className="btn" disabled={!!triggering} onClick={() => trigger("alerts")}>
                  {triggering === "alerts" ? "..." : "Alerts Only"}
                </button>
                <button className="btn" disabled={!!triggering} onClick={() => trigger("leaderboard")}>
                  {triggering === "leaderboard" ? "..." : "Leaderboard Only"}
                </button>
                {triggerResult && <span className="trigger-result">{triggerResult}</span>}
              </div>
            </div>

            {/* Compose */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Compose Tweet</h2>
              <div className="compose">
                <textarea
                  className="compose-input"
                  placeholder="Describe the data (e.g. 'Phoenix hit 122F today, old record 121F from 2024')..."
                  value={composePrompt}
                  onChange={(e) => setComposePrompt(e.target.value)}
                  rows={2}
                />
                <button className="btn" disabled={generating || !composePrompt.trim()} onClick={generateTweet}>
                  {generating ? "generating..." : "Generate Preview"}
                </button>
                {composeTweet && (
                  <div className="preview-box">
                    <div className="preview-label">
                      PREVIEW
                      <span className={`char-count ${composeTweet.length > 280 ? "over" : ""}`}>
                        {composeTweet.length}/280
                      </span>
                    </div>
                    <textarea
                      className="preview-tweet"
                      value={composeTweet}
                      onChange={(e) => setComposeTweet(e.target.value)}
                      rows={3}
                    />
                    <div className="preview-actions">
                      <button
                        className="btn approve"
                        disabled={posting || !composeTweet.trim() || composeTweet.length > 280}
                        onClick={postComposed}
                      >
                        {posting ? "..." : "Approve + Post"}
                      </button>
                      <button className="btn" disabled={generating} onClick={generateTweet}>
                        Regenerate
                      </button>
                      <button className="btn" onClick={() => { setComposeTweet(""); setComposeStatus(null) }}>
                        Discard
                      </button>
                    </div>
                  </div>
                )}
                {composeStatus && <div className="compose-status">{composeStatus}</div>}
              </div>
            </div>

            {/* Stats */}
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

            {/* Runs */}
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
