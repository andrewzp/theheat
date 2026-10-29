"use client"
import { useEffect, useState } from "react"
import { DraftWorkbench } from "../../../../app/components/DraftWorkbench.js"
const headers = { "Content-Type": "application/json", authorization: "Basic Zml4dHVyZTppbnZlbnRlZA==" }
export default function Journey() {
  const [drafts, setDrafts] = useState([]), [selected, setSelected] = useState("invented-station")
  const [editing, setEditing] = useState(null), [text, setText] = useState(""), [revision, setRevision] = useState(null)
  const [action, setAction] = useState(null), [feedback, setFeedback] = useState(null)
  async function refresh() {
    const response = await fetch("/api/drafts", { headers, cache: "no-store" })
    if (!response.ok) throw new Error("Invented fixture refresh failed")
    setDrafts((await response.json()).drafts)
  }
  useEffect(() => { refresh().catch(error => setFeedback({ type: "error", text: error.message })) }, [])
  return <main className="container">
    <h1>Invented temperature graphic journey</h1>
    <p>Real PNG renderer and draft handlers; invented in-memory Gist transport. No source or publication request.</p>
    <DraftWorkbench drafts={drafts} selectedDraftId={selected} setSelectedDraftId={setSelected}
      editingId={editing} setEditingId={setEditing} editText={text} setEditText={setText} editingRevision={revision}
      startEditing={draft => { setEditing(draft.id); setText(draft.text); setRevision(draft.revision_identity); setFeedback(null) }}
      acceptLatestEditRevision={draft => setRevision(draft.revision_identity)}
      draftAct={async (draftId, verb, payload) => {
        if (!["edit", "attach_graphic", "remove_graphic", "review"].includes(verb)) throw new Error("Publication is unavailable in this invented journey")
        setAction(draftId)
        try {
          const response = await fetch("/api/drafts", { method: "POST", headers, body: JSON.stringify({ action: verb, draftId, ...payload,
            expectedRevision: verb === "edit" ? revision : payload.expectedRevision }) })
          const body = await response.json()
          setFeedback({ type: response.ok ? "success" : "error", draftId, text: response.ok ? "Your saved draft is updated." : body.error })
          if (response.ok && verb === "edit") { setEditing(null); setText(""); setRevision(null) }
          await refresh()
        } finally { setAction(null) }
      }} draftAction={action} draftFeedback={feedback} pendingCommand={null} botRuns={[]} />
  </main>
}
