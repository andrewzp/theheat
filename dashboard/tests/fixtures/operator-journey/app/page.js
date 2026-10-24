"use client"

// Invented operator-journey harness. The actual DraftWorkbench mounts the
// actual GraphicPreview and EditorMedia with their real library controllers.
// Every draft and API reply is invented by the browser test through request
// interception. Callbacks are spies: they record exact envelopes and never
// send a command. Nothing here is source, check, review or approval authority.
import { useEffect, useState } from "react"
import { DraftWorkbench } from "../../../../app/components/DraftWorkbench.js"

const record = { calls: [], urls: [], revoked: [], errors: [] }

function instrumentObjectURLs() {
  if (typeof window === "undefined" || URL.createObjectURL.__operatorJourney) return
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL)
  const created = (blob) => {
    const url = create(blob)
    record.urls.push({ url, type: blob?.type ?? null })
    return url
  }
  created.__operatorJourney = true
  URL.createObjectURL = created
  URL.revokeObjectURL = (url) => { record.revoked.push(url); return revoke(url) }
}

// Optional adversarial transport: graphic preview requests ignore their abort
// signal, so an aborted request still resolves later (selected per page load).
function instrumentTransport() {
  if (typeof window === "undefined" || window.fetch.__operatorJourney) return
  const original = window.fetch.bind(window)
  const ignoring = new URLSearchParams(window.location.search).get("transport") === "abort-ignoring"
  const wrapped = (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url
    if (ignoring && url.startsWith("/api/graphic_preview")) {
      const { signal, ...rest } = init
      record.calls.push({ kind: "transport_signal_ignored", aborted_at_send: !!signal?.aborted })
      return original(input, rest)
    }
    return original(input, init)
  }
  wrapped.__operatorJourney = true
  window.fetch = wrapped
}

const clone = (value) => (value === undefined ? undefined : structuredClone(value))

export default function OperatorJourney() {
  const [scenario, setScenario] = useState(null)
  const [drafts, setDrafts] = useState([])
  const [selectedDraftId, setSelectedDraftId] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [editText, setEditText] = useState("")
  const [editingRevision, setEditingRevision] = useState(null)
  const [draftAction, setDraftAction] = useState(null)
  const [pendingCommand, setPendingCommand] = useState(null)
  const [mounted, setMounted] = useState(true)

  useEffect(() => {
    instrumentObjectURLs()
    instrumentTransport()
    const spy = (name) => (...args) => { record.calls.push({ name, args: clone(args) }); return Promise.resolve({ recorded: true }) }
    window.__operatorJourney = {
      record,
      spies: {
        draftAct: spy("draftAct"), submitLocalCommand: spy("submitLocalCommand"), candidateAct: spy("candidateAct"),
        refreshCandidates: spy("refreshCandidates"), acceptLatestEditRevision: spy("acceptLatestEditRevision"),
        checkLocalCommand: spy("checkLocalCommand"), retryLocalCommand: spy("retryLocalCommand"),
      },
      act: {
        setDrafts: (value) => setDrafts(clone(value)),
        // The dashboard's 30-second poll: fresh objects with identical values.
        passiveRefresh: () => setDrafts((current) => clone(current)),
        setRole: (role) => setDrafts((current) => current.map((draft) => ({ ...draft, operator_role: role }))),
        setUpdating: (on) => setDraftAction(on ? selectedDraftId : null),
        setPending: (on) => setPendingCommand(on ? { command: { command_id: "00000000-0000-4000-8000-0000000000aa" } } : null),
        setMounted: (on) => setMounted(!!on),
        cancelEditing: () => { setEditingId(null); setEditText(""); setEditingRevision(null) },
      },
      state: () => ({ selectedDraftId, editingId, draftAction, pending: !!pendingCommand, mounted, drafts: drafts.length }),
    }
  })

  useEffect(() => {
    const control = new AbortController()
    fetch("/api/operator-journey/scenario", { cache: "no-store", signal: control.signal })
      .then((response) => response.json())
      .then((value) => {
        setScenario(value.name)
        setDrafts(value.drafts)
        setSelectedDraftId(value.selected)
      })
      .catch((error) => { if (!control.signal.aborted) record.errors.push(String(error)) })
    return () => control.abort()
  }, [])

  const spies = typeof window === "undefined" ? null : window.__operatorJourney?.spies
  if (!scenario || !spies) return <main className="container"><p role="status">Loading invented operator journey…</p></main>
  return (
    <main className="container" data-scenario={scenario}>
      <h1 className="operator-journey-title">Invented operator media journey</h1>
      {mounted && (
        <DraftWorkbench
          drafts={drafts}
          localCandidates={[]}
          localRole={drafts.find((draft) => draft.id === selectedDraftId)?.operator_role}
          candidateAct={spies.candidateAct}
          refreshCandidates={spies.refreshCandidates}
          selectedDraftId={selectedDraftId}
          setSelectedDraftId={(id) => { record.calls.push({ name: "setSelectedDraftId", args: [id] }); setSelectedDraftId(id) }}
          editingId={editingId}
          setEditingId={setEditingId}
          editText={editText}
          setEditText={setEditText}
          editingRevision={editingRevision}
          startEditing={(draft) => {
            record.calls.push({ name: "startEditing", args: [draft.id] })
            setEditingId(draft.id); setEditText(draft.text); setEditingRevision(clone(draft.revision_identity))
          }}
          acceptLatestEditRevision={spies.acceptLatestEditRevision}
          draftAct={spies.draftAct}
          draftAction={draftAction}
          draftFeedback={null}
          pendingCommand={pendingCommand}
          checkLocalCommand={spies.checkLocalCommand}
          retryLocalCommand={spies.retryLocalCommand}
          submitLocalCommand={spies.submitLocalCommand}
          botRuns={[]}
        />
      )}
    </main>
  )
}
