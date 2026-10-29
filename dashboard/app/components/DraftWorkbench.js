"use client"

import { useEffect, useId, useRef, useState } from "react"
import { ForecastEvidence } from "./ForecastEvidence.js"
import { NwsWarningEvidence } from "./NwsWarningEvidence.js"
import { OfficialWarningEvidence } from "./OfficialWarningEvidence.js"
import { NhcAdvisoryEvidence } from "./NhcAdvisoryEvidence.js"
import { ClaimEvidence } from "./ClaimEvidence.js"
import { OperatorClaimReferenceHistory, OperatorClaimReferences } from "./OperatorClaimReferences.js"
import { operatorReferencesForDisplay } from "../../lib/operator-claim-reference-input.js"
import { GraphicPreview } from "./GraphicPreview.js"
import { GIST_POST_IMAGE_KINDS } from "../../lib/graphic-preview.js"
import { EditorMedia } from "./EditorMedia.js"
import { formatDuration, timeAgo } from "../../lib/format.js"
import { draftReviewControls, draftTextLength, manualReviewLabel, revisionKey } from "../../lib/draft-review-ui.js"
import {
  ScoreMeter,
  clipText,
  countdownText,
  delayLabel,
  findDraftRun,
  findDraftSourceRun,
  policySummary,
} from "./shared.js"

const hasLocalMediaPanel = draft => draft?.local_preview && ["fire", "air_quality_hazard", "severe_weather"].includes(draft.type)

export function DraftWorkbench({
  drafts,
  localCandidates = [],
  localRole,
  candidateAct,
  refreshCandidates,
  selectedDraftId,
  setSelectedDraftId,
  editingId,
  setEditingId,
  editText,
  setEditText,
  editingRevision,
  startEditing,
  acceptLatestEditRevision,
  draftAct,
  draftAction,
  draftFeedback,
  pendingCommand,
  checkLocalCommand,
  retryLocalCommand,
  submitLocalCommand,
  botRuns,
}) {
  const [reviewConfirmedIdentity, setReviewConfirmedIdentity] = useState("")
  const [focusRequest, setFocusRequest] = useState(0)
  const [referenceEdit, setReferenceEdit] = useState(null)
  const focusIntent = useRef(null)
  const editor = useRef(null)
  const editButton = useRef(null)
  const heading = useRef(null)
  const editorId = useId()
  const selectedDraft = drafts.find((d) => d.id === selectedDraftId) || drafts[0] || null
  const controls = draftReviewControls(selectedDraft)
  const currentRevisionKey = revisionKey(selectedDraft?.revision_identity)
  const reviewKey = `${selectedDraft?.id}:${currentRevisionKey}:${selectedDraft?.editorial_policy?.policy_sha256 ?? "unverified"}`
  const editConflict = editingId === selectedDraft?.id && revisionKey(editingRevision) !== currentRevisionKey
  const referenceEditKey = `${selectedDraft?.id}:${revisionKey(editingRevision)}`
  const savedReferences = operatorReferencesForDisplay(selectedDraft)
  const initialReferenceItems = editText === selectedDraft?.text && savedReferences.status === "saved"
    ? savedReferences.items.map(item => ({ claim: item.claim, sources: item.sources.map(({ pointer }) => ({ pointer })) })) : []
  const referenceItems = editConflict ? [] : referenceEdit?.key === referenceEditKey && referenceEdit.text === editText ? referenceEdit.items : initialReferenceItems
  const selectedDraftRun = findDraftRun(selectedDraft, botRuns)
  const selectedDraftSourceRun = findDraftSourceRun(selectedDraft, botRuns)
  const selectedCandidate =
    selectedDraft?.candidates?.find((c) => c.text === selectedDraft?.text) ||
    selectedDraft?.candidates?.[0]

  function requestFocus(action, origin) {
    focusIntent.current = { action, origin, previouslyFocused: origin.ownerDocument.activeElement, draftId: selectedDraft.id }
    setFocusRequest((request) => request + 1)
  }

  useEffect(() => {
    const intent = focusIntent.current
    focusIntent.current = null
    if (!intent || intent.draftId !== selectedDraft?.id) return
    const document = intent.origin.ownerDocument
    const active = document.activeElement
    if (![intent.origin, intent.previouslyFocused, document.body, document.documentElement].includes(active)) return
    if (intent.action === "edit") {
      if (editingId === intent.draftId && editor.current && !editor.current.disabled) editor.current.focus()
    } else if (editingId !== intent.draftId) {
      const target = editButton.current && !editButton.current.disabled ? editButton.current : heading.current
      target?.focus()
    }
  }, [focusRequest, selectedDraft?.id, editingId])

  return (
    <div className="card full desk-panel">
      <div className="section-head">
        <div>
          <h2 ref={heading} tabIndex={-1} className="draft-workbench-heading">Draft Workbench</h2>
          <p className="card-kicker">
            {selectedDraft?.local_preview ? "Invented local preview. Approvals are parked; nothing is published." : "Review the queue with source facts, score context, alternate copy, and approval policy in one place."}
          </p>
        </div>
        <span className="backend-pill">{drafts.length} {selectedDraft?.local_preview ? "local drafts" : "awaiting publication"}</span>
      </div>

      {localCandidates.length > 0 && (
        <section aria-label="Local unchecked candidates" className="card" style={{ marginBottom: 16 }}>
          <h3>Retained candidates</h3>
          <p>Invented local evidence. Required checks run separately. Cost is unknown; nothing is published.</p>
          {localCandidates.map((candidate) => {
            const savedCandidate = candidate.status === "admitted" && !!candidate.saved_draft_id
            return (
            <article key={candidate.admission_input_id} style={{ padding: "12px 0", overflowWrap: "anywhere" }}>
              <strong>{candidate.source?.type}: {candidate.source?.event_id}</strong>
              <p>{candidate.source?.where} · {candidate.source?.when}</p>
              {candidate.source?.headline_metric && <p>{candidate.source.headline_metric.label.replaceAll("_", " ")}: {candidate.source.headline_metric.value} {candidate.source.headline_metric.unit}</p>}
              {candidate.text && <blockquote>{candidate.text}</blockquote>}
              <details><summary>Retained source facts</summary><ul>{(candidate.source?.facts || []).map((fact, i) => <li key={i}>{fact.label.replaceAll("_", " ")}: {fact.value} {fact.unit}</li>)}</ul></details>
              {candidate.last_observed_at && <p className="text-muted">Last check response: {candidate.last_observed_at}</p>}
              {candidate.checks_available_at && <p role="status">The writer result is retained. Checks can begin after {new Date(candidate.checks_available_at).toLocaleTimeString()}. Refresh progress then.</p>}
              <p role="status">{({ not_checked: "Not checked", checks_pending: "Checks pending", checks_completed: "Required checks completed", checks_recorded: "Checks recorded; source validation required", checks_blocked: "Checks blocked", stale: "Candidate changed; stage a new attempt", admitted: "Saved to local drafts" })[candidate.status] || "Unavailable"}{candidate.reason && !savedCandidate ? ` — ${candidate.reason}` : ""}</p>
              {savedCandidate && <p className="text-muted">These candidate checks are historical. Open the saved draft for its current review status.</p>}
              <ul>{Object.entries(candidate.stages || {}).map(([stage, disposition]) => <li key={stage}>{stage.replaceAll("_", " ")}: {disposition}</li>)}</ul>
              {savedCandidate && candidate.reason && <details><summary>Earlier candidate validation</summary><p>{candidate.reason}</p></details>}
              {candidate.saved_draft_id ? <button type="button" className="btn btn-ghost" disabled={!!pendingCommand || !!editingId} onClick={() => setSelectedDraftId(candidate.saved_draft_id)}>Open saved draft</button>
                : candidate.status === "not_checked" ? <button type="button" className="btn btn-blue" style={{ minHeight: 44 }} disabled={localRole === "viewer" || !!pendingCommand || !!editingId || !!candidate.checks_available_at} onClick={() => candidateAct(candidate, "request_candidate_checks")}>Check candidate</button>
                : candidate.important_slate ? (candidate.slate_can_admit ? <button type="button" className="btn btn-blue" style={{ minHeight: 44 }} disabled={localRole === "viewer" || !!pendingCommand || !!editingId} onClick={() => candidateAct(candidate, "admit_checked_slate")}>Add checked important-event draft</button> : null)
                : (candidate.required_checks_completed || candidate.status === "checks_recorded") ? <button type="button" className="btn btn-blue" style={{ minHeight: 44 }} disabled={localRole === "viewer" || !!pendingCommand || !!editingId} onClick={() => candidateAct(candidate, "admit_checked_candidate")}>{candidate.status === "checks_recorded" ? "Validate and add to local drafts" : "Add to local drafts"}</button> : null}
            </article>
            )
          })}
          <button type="button" className="btn btn-ghost" style={{ minHeight: 44 }} onClick={refreshCandidates}>Refresh check progress</button>
          {localCandidates.some((candidate) => candidate.admission_input_id === draftFeedback?.draftId) && <p role="status">{draftFeedback.text}</p>}
          {pendingCommand?.command?.targets?.length === 0 && <div>
            <button type="button" className="btn btn-ghost" style={{ minHeight: 44 }} onClick={checkLocalCommand}>Check command result</button>
            <button type="button" className="btn btn-ghost" style={{ minHeight: 44 }} onClick={retryLocalCommand}>Retry same command</button>
          </div>}
        </section>
      )}

      {drafts.length > 0 ? (
        <div className="draft-desk">
          <div className="draft-queue">
            {drafts.map((draft) => (
              <button
                key={draft.id}
                type="button"
                className={`queue-item ${selectedDraft?.id === draft.id ? "selected" : ""}`}
                disabled={!!pendingCommand}
                onClick={() => {
                  setSelectedDraftId(draft.id)
                  setEditingId(null)
                  setEditText("")
                }}
              >
                <div className="queue-item-head">
                  <span className="draft-type">{draft.type}</span>
                  <span className="queue-score">
                    S {draft.score?.total ?? "—"} · C {draft.candidate_score?.total ?? "—"}
                  </span>
                </div>
                <div className="queue-text">{clipText(draft.text, 118)}</div>
                <div className="queue-meta">
                  <span>{timeAgo(draft.created_at)}</span>
                  <span>{draft.publish_blocked ? "publication needs reconciliation" : draftReviewControls(draft).sourceHold ? "source update needed" : draft.review_status === "media_review_required" ? (hasLocalMediaPanel(draft) ? "Text and graphic status" : "graphic review needed") : draft.review_status === "policy_unverified" ? "editorial policy unverified" : draft.review_status !== "passed" ? "review needed" : draft.status === "approved" ? (draft.local_preview ? "local intent parked" : "awaiting publication") : manualReviewLabel(draft) || policySummary(draft)}</span>
                </div>
              </button>
            ))}
          </div>

          <div className="draft-workbench">
            {selectedDraft && (
              <>
                <div className="draft-meta">
                  <span className="draft-type">{selectedDraft.type}</span>
                  <span className="draft-time">
                    {selectedDraft.review_context?.source || "draft queue"}
                    {" · "}
                    {timeAgo(selectedDraft.created_at)}
                  </span>
                </div>

                <div className="draft-status-row">
                  <span className="workbench-pill">
                    {selectedDraft.publish_blocked ? "publication needs reconciliation" : controls.sourceHold ? "source update needed" : selectedDraft.review_status === "media_review_required" ? (hasLocalMediaPanel(selectedDraft) ? "Text and graphic status" : "graphic review needed") : selectedDraft.review_status === "policy_unverified" ? "editorial policy unverified" : controls.conflict ? "conflicting versions" : controls.needsReview ? "review needed" : selectedDraft.status === "approved" ? (selectedDraft.local_preview ? "local intent parked" : "awaiting publication") : manualReviewLabel(selectedDraft) || "model checks current"}
                  </span>
                  <span className="workbench-pill">
                    signal {selectedDraft.score?.total ?? "—"}
                    {selectedDraft.score?.label ? ` · ${selectedDraft.score.label}` : ""}
                  </span>
                  <span className="workbench-pill">
                    copy {selectedDraft.candidate_score?.total ?? "—"}
                    {selectedCandidate?.source ? ` · ${selectedCandidate.source}` : ""}
                  </span>
                  {selectedDraft.automatic_publication?.enabled !== true && <p className="runtime-note">{selectedDraft.review_status === "media_review_required" ? (hasLocalMediaPanel(selectedDraft) ? "Publishing is unavailable. See Text and graphic for current review status." : "Automatic scheduling is paused or unverified. This graphic needs joint review.") : "Automatic scheduling is paused or unverified. Review remains available."}</p>}
                  {selectedDraft.auto_approve_at ? (
                    <span className="workbench-pill alert">{countdownText(selectedDraft.auto_approve_at)}</span>
                  ) : selectedDraft.approval_policy?.mode === "manual_only" ? (
                    <span className="workbench-pill">manual only</span>
                  ) : (
                    <span className="workbench-pill">
                      {selectedDraft.approval_policy?.recommended_delay_minutes
                        ? `recommended ${delayLabel(selectedDraft.approval_policy.recommended_delay_minutes)}`
                        : "manual approval"}
                    </span>
                  )}
                  {selectedDraft.review_context?.run_mode && (
                    <span className="workbench-pill">{selectedDraft.review_context.run_mode}</span>
                  )}
                </div>

                {editingId === selectedDraft.id ? (
                  <>
                    <label className="draft-edit-label" htmlFor={editorId}>Edit draft text</label>
                    <textarea
                      ref={editor}
                      id={editorId}
                      aria-describedby={`${editorId}-count`}
                      disabled={!!pendingCommand}
                      className="draft-edit-area"
                      value={editText}
                      onChange={(e) => {
                        setEditText(e.target.value)
                        setReferenceEdit({ key: referenceEditKey, text: e.target.value, items: [] })
                      }}
                      rows={4}
                    />
                    <div id={`${editorId}-count`} className={`draft-chars ${draftTextLength(editText) > 280 ? "over" : ""}`}>
                      {draftTextLength(editText)}/280
                    </div>
                  </>
                ) : (
                  <>
                    <div className="draft-text">{selectedDraft.text}</div>
                    <div className="draft-chars">{draftTextLength(selectedDraft.text)}/280</div>
                  </>
                )}

                {editConflict && (
                  <div className="draft-feedback error" role="alert">
                    <p>This draft changed while you were editing. Your edit is preserved. Review the latest saved text before replacing it:</p>
                    <div className="candidate-text">{selectedDraft.text}</div>
                    <button type="button" className="btn sm" disabled={!controls.canEdit || !!draftAction} onClick={() => acceptLatestEditRevision(selectedDraft)}>
                      Use my edit on this version
                    </button>
                  </div>
                )}

                {selectedDraft.publish_blocked && (
                  <div className="draft-feedback error" role="alert">
                    A publication attempt needs reconciliation. Editing and approval are paused until its outcome is known.
                  </div>
                )}

                {controls.conflict && !selectedDraft.publish_blocked && (
                  <div className="draft-feedback error" role="alert">
                    Conflicting versions were found. Edit and save the intended text, then review it against its sources.
                  </div>
                )}

                <ClaimEvidence key={`claims:${reviewKey}:${editingId === selectedDraft.id}`} draft={selectedDraft} editing={editingId === selectedDraft.id} sourceHold={controls.sourceHold} />
                <OperatorClaimReferences key={`operator-references:${reviewKey}:${referenceEditKey}:${editingId === selectedDraft.id}:${editText}`}
                  draft={selectedDraft} text={editingId === selectedDraft.id ? editText : selectedDraft.text}
                  editing={editingId === selectedDraft.id} items={referenceItems}
                  disabled={!!draftAction || !!pendingCommand || editConflict || !controls.canEdit}
                  onChange={items => setReferenceEdit({ key: referenceEditKey, text: editText, items })} />
                <OperatorClaimReferenceHistory draft={selectedDraft} editing={editingId === selectedDraft.id} />
                <ForecastEvidence key={reviewKey} draft={selectedDraft} />
                <NwsWarningEvidence key={"nws:" + reviewKey} draft={selectedDraft} />
                <OfficialWarningEvidence key={"official-warning:" + reviewKey} draft={selectedDraft} />
                <NhcAdvisoryEvidence key={"nhc-advisory:" + reviewKey} draft={selectedDraft} />
                {selectedDraft.local_preview
                  ? <EditorMedia key={`media:${reviewKey}`} draft={selectedDraft} editing={editingId === selectedDraft.id} updating={!!draftAction || !!pendingCommand} submitCommand={submitLocalCommand} />
                  : <GraphicPreview key={`graphic:${reviewKey}`} draft={selectedDraft} editing={editingId === selectedDraft.id} updating={draftAction === selectedDraft.id} onAction={(action, payload) => draftAct(selectedDraft.id, action, payload)} />}

                {controls.canReview && !selectedDraft.media_attachment_sha256 && !selectedDraft.media_attachment && editingId !== selectedDraft.id && (
                  <div className="workbench-panel">
                    <h3>Review this version</h3>
                    <p>Previous checks do not cover this text. Check it against the saved source evidence. Recording your review permits manual approval; it does not run or replace model checks.</p>
                    <label>
                      <input
                        type="checkbox"
                        checked={reviewConfirmedIdentity === reviewKey}
                        onChange={(event) => setReviewConfirmedIdentity(event.target.checked ? reviewKey : "")}
                      />
                      {" "}I checked this exact text against its source evidence.
                    </label>
                    <button
                      type="button"
                      className="btn sm"
                      disabled={!!draftAction || reviewConfirmedIdentity !== reviewKey}
                      onClick={() => draftAct(selectedDraft.id, "review", { reviewConfirmed: true, expectedPolicySha256: selectedDraft.editorial_policy?.policy_sha256, expectedRevision: selectedDraft.revision_identity })}
                    >
                      Record human review
                    </button>
                  </div>
                )}

                {(selectedDraft.score?.reasons?.length > 0 ||
                  selectedDraft.candidate_score?.reasons?.length > 0) && (
                  <div className="draft-reason-block">
                    {selectedDraft.score?.reasons?.length > 0 && (
                      <div className="draft-reason-line">
                        <strong>Signal:</strong> {selectedDraft.score.reasons.join(" · ")}
                      </div>
                    )}
                    {selectedDraft.candidate_score?.reasons?.length > 0 && (
                      <div className="draft-reason-line">
                        <strong>Copy:</strong> {selectedDraft.candidate_score.reasons.join(" · ")}
                      </div>
                    )}
                  </div>
                )}

                {selectedDraft.review_context?.shadow_two_bot?.text && (
                  <div className="shadow-two-bot">
                    <div className="shadow-label">SHADOW (TWO-BOT)</div>
                    <div className="shadow-text">{selectedDraft.review_context.shadow_two_bot.text}</div>
                    <div className="shadow-meta">
                      <span>{draftTextLength(selectedDraft.review_context.shadow_two_bot.text)}/280</span>
                      {selectedDraft.review_context.shadow_two_bot.angle_chosen && (
                        <span>angle: {selectedDraft.review_context.shadow_two_bot.angle_chosen}</span>
                      )}
                      {selectedDraft.review_context.shadow_two_bot.writer_model && (
                        <span>writer: {selectedDraft.review_context.shadow_two_bot.writer_model}</span>
                      )}
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() =>
                          navigator.clipboard?.writeText(selectedDraft.review_context.shadow_two_bot.text)
                        }
                      >
                        copy
                      </button>
                    </div>
                  </div>
                )}

                <div className="workbench-grid">
                  <div className="workbench-panel">
                    <h3>Why This Exists</h3>
                    <div className="workbench-headline">
                      {selectedDraft.review_context?.headline || "Pending draft awaiting review"}
                    </div>
                    {selectedDraft.review_context?.facts?.length > 0 ? (
                      <div className="fact-list">
                        {selectedDraft.review_context.facts.map((fact) => (
                          <div key={`${selectedDraft.id}-${fact.label}`} className="fact-row">
                            <span className="fact-label">{fact.label}</span>
                            <span className="fact-value">{fact.value}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="empty">no structured source facts saved</div>
                    )}
                  </div>

                  <div className="workbench-panel">
                    <h3>Signal Score</h3>
                    {selectedDraft.score ? (
                      <>
                        <ScoreMeter label="severity" value={selectedDraft.score.severity} />
                        <ScoreMeter label="novelty" value={selectedDraft.score.novelty} />
                        <ScoreMeter label="timeliness" value={selectedDraft.score.timeliness} />
                        <ScoreMeter label="confidence" value={selectedDraft.score.confidence} />
                        <ScoreMeter label="shareability" value={selectedDraft.score.shareability} />
                        <ScoreMeter label="sensitivity" value={selectedDraft.score.sensitivity} inverse />
                      </>
                    ) : (
                      <div className="empty">no signal score available</div>
                    )}
                  </div>

                  <div className="workbench-panel">
                    <h3>Copy Score</h3>
                    {selectedDraft.candidate_score ? (
                      <>
                        <ScoreMeter label="clarity" value={selectedDraft.candidate_score.clarity} />
                        <ScoreMeter label="context" value={selectedDraft.candidate_score.context} />
                        <ScoreMeter label="voice" value={selectedDraft.candidate_score.voice} />
                        <ScoreMeter label="punch" value={selectedDraft.candidate_score.punch} />
                      </>
                    ) : (
                      <div className="empty">single-candidate draft</div>
                    )}
                  </div>

                  <div className="workbench-panel">
                    <h3>Approval Policy</h3>
                    <div className="workbench-headline">
                      {selectedDraft.review_status === "media_review_required"
                        ? (hasLocalMediaPanel(selectedDraft) ? "Use Text and graphic for joint review, required checks and local approval status. Publishing is unavailable." : GIST_POST_IMAGE_KINDS.includes(selectedDraft.media_attachment?.kind) ? "Review the text, image and full description together in Graphic preview before approval." : "Review the text and attached graphic together before approval. Joint graphic review is not available here yet.")
                        : selectedDraft.review_status === "policy_unverified"
                        ? selectedDraft.editorial_policy?.reason
                        : controls.needsReview
                        ? "This version needs review before approval."
                        : selectedDraft.review_kind === "delegated"
                        ? "Assistant reviewed under your explicit authorization. Manual posting only; this is not a human rating or current model checks."
                        : selectedDraft.review_kind === "human"
                        ? (selectedDraft.local_preview ? "Human review permits local approval. Nothing will be published." : "Human review permits manual posting. Automatic scheduling requires current model checks.")
                        : selectedDraft.approval_policy?.mode === "armed_auto"
                        ? "Policy armed this draft automatically."
                        : selectedDraft.approval_policy?.mode === "suggested_auto"
                        ? "Policy recommends a timed auto-approval."
                        : "Policy requires explicit human approval."}
                    </div>
                    <div className="fact-list">
                      <div className="fact-row">
                        <span className="fact-label">Policy key</span>
                        <span className="fact-value">{selectedDraft.approval_policy?.key || "—"}</span>
                      </div>
                      <div className="fact-row">
                        <span className="fact-label">Mode</span>
                        <span className="fact-value">{selectedDraft.approval_policy?.mode || "—"}</span>
                      </div>
                      <div className="fact-row">
                        <span className="fact-label">Recommended window</span>
                        <span className="fact-value">
                          {selectedDraft.approval_policy?.recommended_delay_minutes
                            ? delayLabel(selectedDraft.approval_policy.recommended_delay_minutes)
                            : "manual only"}
                        </span>
                      </div>
                      <div className="fact-row">
                        <span className="fact-label">Why</span>
                        <span className="fact-value">{selectedDraft.approval_policy?.reason || "—"}</span>
                      </div>
                    </div>
                  </div>

                  <div className="workbench-panel">
                    <h3>Run Trace</h3>
                    <div className="run-trace">
                      <div className="trace-line">
                        <span>workflow run</span>
                        <strong>{selectedDraftRun?.id || selectedDraft.review_context?.run_id || "—"}</strong>
                      </div>
                      <div className="trace-line">
                        <span>source slot</span>
                        <strong>{selectedDraft.review_context?.source_key || "—"}</strong>
                      </div>
                      <div className="trace-line">
                        <span>source status</span>
                        <strong>{selectedDraftSourceRun?.status || "—"}</strong>
                      </div>
                      <div className="trace-line">
                        <span>observed / promoted</span>
                        <strong>
                          {selectedDraftSourceRun
                            ? `${selectedDraftSourceRun.observed} / ${selectedDraftSourceRun.promoted}`
                            : "—"}
                        </strong>
                      </div>
                      <div className="trace-line">
                        <span>source duration</span>
                        <strong>
                          {selectedDraftSourceRun ? formatDuration(selectedDraftSourceRun.duration_ms) : "—"}
                        </strong>
                      </div>
                      <div className="trace-line">
                        <span>event id</span>
                        <strong>{selectedDraft.event_id || "manual"}</strong>
                      </div>
                    </div>
                  </div>
                </div>

                {selectedDraft.candidates?.length > 1 && (
                  <div className="candidate-list">
                    {selectedDraft.candidates
                      .filter((c) => c.text !== selectedDraft.text)
                      .slice(0, 3)
                      .map((c) => (
                        <div key={`${selectedDraft.id}-${c.rank}`} className="candidate-item">
                          <div className="candidate-head">
                            <span>
                              alt #{c.rank} · {c.score?.total == null ? "score unavailable" : `copy ${c.score.total}`} · {c.source}
                            </span>
                            <button
                              type="button"
                              className="btn sm"
                              disabled={!!draftAction || !controls.canEdit || editingId === selectedDraft.id}
                              onClick={() =>
                                draftAct(selectedDraft.id, "select_candidate", { candidateRank: c.rank })
                              }
                            >
                              Use This
                            </button>
                          </div>
                          <div className="candidate-text">{c.text}</div>
                          {c.score?.reasons?.length > 0 && (
                            <div className="candidate-meta">{c.score.reasons.join(" · ")}</div>
                          )}
                        </div>
                      ))}
                  </div>
                )}

                <div className="draft-actions">
                  {editingId === selectedDraft.id ? (
                    <>
                      <button
                        type="button"
                        className="btn approve sm"
                        disabled={!!draftAction || !controls.canEdit || editConflict || !editText.trim() || draftTextLength(editText) > 280}
                        onClick={() => draftAct(selectedDraft.id, "edit", { editedText: editText, operator_claim_references: referenceItems })}
                      >
                        Save
                      </button>
                      <button type="button" className="btn sm" disabled={!!pendingCommand} onClick={(event) => {
                        requestFocus("cancel", event.currentTarget)
                        setEditingId(null)
                      }}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn approve sm"
                        disabled={!!draftAction || !controls.canApprove}
                        onClick={() => draftAct(selectedDraft.id, "approve")}
                      >
                        {draftAction === selectedDraft.id ? "..." : selectedDraft.local_preview ? "Approve locally" : "Approve + Post"}
                      </button>
                      <button
                        ref={editButton}
                        type="button"
                        className="btn sm draft-edit-button"
                        disabled={!!draftAction || !controls.canEdit}
                        onClick={(event) => {
                          requestFocus("edit", event.currentTarget)
                          setReferenceEdit(null)
                          startEditing(selectedDraft)
                        }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn reject sm"
                        disabled={!!draftAction || !controls.canEdit}
                        onClick={() => draftAct(selectedDraft.id, "reject")}
                      >
                        Reject
                      </button>
                      {selectedDraft.auto_approve_at || selectedDraft.status === "approved" ? (
                        <button
                          type="button"
                          className="btn sm"
                          disabled={!!draftAction || !controls.canEdit}
                          onClick={() => draftAct(selectedDraft.id, "cancel_auto_approve")}
                        >
                          {selectedDraft.status === "approved" ? (selectedDraft.local_preview ? "Cancel parked approval" : "Cancel queued approval") : `Cancel ${countdownText(selectedDraft.auto_approve_at)}`}
                        </button>
                      ) : !controls.canSchedule ? (
                        <button type="button" className="btn sm" disabled>
                          {selectedDraft.local_preview ? "Publication unavailable" : manualReviewLabel(selectedDraft) ? "Manual posting only" : "Auto unavailable"}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn sm"
                          disabled={!!draftAction}
                          onClick={() =>
                            draftAct(selectedDraft.id, "auto_approve", {
                              delayMinutes: selectedDraft.approval_policy?.recommended_delay_minutes,
                            })
                          }
                        >
                          Auto {delayLabel(selectedDraft.approval_policy?.recommended_delay_minutes || 30)}
                        </button>
                      )}
                    </>
                  )}
                </div>
                {pendingCommand && pendingCommand.draftId === selectedDraft.id && (
                  <div className="draft-actions" aria-label="Pending local command">
                    <button className="btn sm" type="button" onClick={checkLocalCommand}>Check result</button>
                    <button className="btn sm" type="button" onClick={retryLocalCommand}>Retry same action</button>
                  </div>
                )}
                {draftFeedback && (!draftFeedback.draftId || draftFeedback.draftId === selectedDraft.id) && (
                  <div className={`draft-feedback ${draftFeedback.type}`} role="alert">
                    {draftFeedback.text}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="draft-empty">
          No drafts waiting. Trigger a run on the Pipeline tab or try a writing preview.
        </div>
      )}
    </div>
  )
}
