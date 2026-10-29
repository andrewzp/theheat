"use client"
import { useEffect, useState } from "react"
import { DraftWorkbench } from "../../../../app/components/DraftWorkbench.js"
const headers = { "Content-Type": "application/json", authorization: "Basic Zml4dHVyZTppbnZlbnRlZA==" }
export default function Journey() {
  const [drafts, setDrafts] = useState([]), [selected, setSelected] = useState("invented-official-warning")
  const [editing, setEditing] = useState(null), [text, setText] = useState(""), [revision, setRevision] = useState(null)
  const [action, setAction] = useState(null), [feedback, setFeedback] = useState(null), [done, setDone] = useState(0)
  async function refresh() {
    const response = await fetch("/api/drafts", { headers, cache: "no-store" })
    if (!response.ok) throw new Error("Invented warning fixture refresh failed")
    setDrafts((await response.json()).drafts)
  }
  useEffect(() => { refresh().catch(error => setFeedback({ type: "error", text: error.message })) }, [])
  return <main className="container"><h1>Invented official-warning review journey</h1>
    <p>Made-up test warning. Real queue, pipeline and dashboard handlers; offline model fixtures and in-memory Gist. No publishing or outside requests.</p>
    <DraftWorkbench drafts={drafts} selectedDraftId={selected} setSelectedDraftId={setSelected}
      editingId={editing} setEditingId={setEditing} editText={text} setEditText={setText} editingRevision={revision}
      startEditing={draft => { setEditing(draft.id); setText(draft.text); setRevision(draft.revision_identity) }}
      acceptLatestEditRevision={draft => setRevision(draft.revision_identity)}
      draftAct={async (id, verb, payload = {}) => {
        setAction(id)
        try {
          const current = drafts.find(draft => draft.id === id)
          const response = await fetch("/api/drafts", { method: "POST", headers, body: JSON.stringify({ action: verb, draftId: id,
            ...payload, expectedRevision: verb === "edit" ? revision : payload.expectedRevision ?? current.revision_identity }) })
          const value = await response.json()
          setFeedback({ type: response.ok ? "success" : "error", draftId: id, text: response.ok ? "Invented draft updated." : value.error })
          if (response.ok && verb === "edit") { setEditing(null); setText(""); setRevision(null) }
          await refresh(); setDone(value => value + 1)
        } finally { setAction(null) }
      }} draftAction={action} draftFeedback={feedback} pendingCommand={null} botRuns={[]} />
    <output id="journey-actions" hidden data-count={done} />
    <button type="button" id="fixture-refresh" onClick={refresh}>Refresh invented fixture</button>
  </main>
}
