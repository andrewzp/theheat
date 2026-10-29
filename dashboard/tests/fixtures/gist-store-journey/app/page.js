"use client"
import { useEffect, useState } from "react"
import { DraftWorkbench } from "../../../../app/components/DraftWorkbench.js"
const headers = { "Content-Type": "application/json", authorization: "Basic Zml4dHVyZTppbnZlbnRlZA==" }
export default function Journey() {
  const [drafts, setDrafts] = useState([]), [selected, setSelected] = useState("invented-crw")
  const [editing, setEditing] = useState(null), [text, setText] = useState(""), [revision, setRevision] = useState(null)
  const [action, setAction] = useState(null), [feedback, setFeedback] = useState(null)
  // Fixture-only instrumentation: one completed-action counter for the journey test.
  const [done, setDone] = useState({ count: 0, ok: "", error: "", code: "" })
  async function refresh() {
    const response = await fetch("/api/drafts", { headers, cache: "no-store" })
    if (!response.ok) throw new Error("Invented fixture refresh failed")
    setDrafts((await response.json()).drafts)
  }
  useEffect(() => { refresh().catch(error => setFeedback({ type: "error", text: error.message })) }, [])
  return <main className="container">
    <h1>Invented retained-asset graphic journey</h1>
    <p>Real renderer, retained local media store and draft handlers; invented in-memory Gist, fixed invented clock and recorded workflow dispatch. No source or publication request.</p>
    <DraftWorkbench drafts={drafts} selectedDraftId={selected} setSelectedDraftId={setSelected}
      editingId={editing} setEditingId={setEditing} editText={text} setEditText={setText} editingRevision={revision}
      startEditing={draft => { setEditing(draft.id); setText(draft.text); setRevision(draft.revision_identity); setFeedback(null) }}
      acceptLatestEditRevision={draft => setRevision(draft.revision_identity)}
      draftAct={async (draftId, verb, payload = {}) => {
        if (!["edit", "attach_graphic", "remove_graphic", "review", "approve"].includes(verb)) throw new Error("Unavailable in this invented journey")
        const current = drafts.find(draft => draft.id === draftId)
        setAction(draftId)
        try {
          const response = await fetch("/api/drafts", { method: "POST", headers, body: JSON.stringify({ action: verb, draftId, ...payload,
            expectedRevision: verb === "edit" ? revision : payload.expectedRevision ?? current?.revision_identity }) })
          const body = await response.json()
          setFeedback({ type: response.ok ? "success" : "error", draftId, text: response.ok ? "Your saved draft is updated." : body.error })
          if (response.ok && verb === "edit") { setEditing(null); setText(""); setRevision(null) }
          await refresh()
          setDone(value => ({ count: value.count + 1, ok: String(response.ok), error: body.error ?? "", code: body.code ?? "" }))
        } finally { setAction(null) }
      }} draftAction={action} draftFeedback={feedback} pendingCommand={null} botRuns={[]} />
    <output id="journey-actions" hidden data-count={done.count} data-ok={done.ok} data-code={done.code}>{done.error}</output>
  </main>
}
