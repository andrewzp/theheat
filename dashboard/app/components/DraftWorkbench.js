"use client"

import { useState } from "react"
import { formatDuration, timeAgo } from "../../lib/format.js"
import { draftReviewControls, draftTextLength, revisionKey } from "../../lib/draft-review-ui.js"
import {
  ScoreMeter,
  clipText,
  countdownText,
  delayLabel,
  findDraftRun,
  findDraftSourceRun,
  policySummary,
} from "./shared.js"

export function DraftWorkbench({
  drafts,
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
  botRuns,
}) {
  const [reviewConfirmedIdentity, setReviewConfirmedIdentity] = useState("")
  const selectedDraft = drafts.find((d) => d.id === selectedDraftId) || drafts[0] || null
  const controls = draftReviewControls(selectedDraft)
  const currentRevisionKey = revisionKey(selectedDraft?.revision_identity)
  const reviewKey = `${selectedDraft?.id}:${currentRevisionKey}`
  const editConflict = editingId === selectedDraft?.id && revisionKey(editingRevision) !== currentRevisionKey
  const selectedDraftRun = findDraftRun(selectedDraft, botRuns)
  const selectedDraftSourceRun = findDraftSourceRun(selectedDraft, botRuns)
  const selectedCandidate =
    selectedDraft?.candidates?.find((c) => c.text === selectedDraft?.text) ||
    selectedDraft?.candidates?.[0]

  return (
    <div className="card full desk-panel">
      <div className="section-head">
        <div>
          <h2>Draft Workbench</h2>
          <p className="card-kicker">
            Review the queue with source facts, score context, alternate copy, and approval policy in one place.
          </p>
        </div>
        <span className="backend-pill">{drafts.length} awaiting publication</span>
      </div>

      {drafts.length > 0 ? (
        <div className="draft-desk">
          <div className="draft-queue">
            {drafts.map((draft) => (
              <button
                key={draft.id}
                type="button"
                className={`queue-item ${selectedDraft?.id === draft.id ? "selected" : ""}`}
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
                  <span>{draft.publish_blocked ? "publication needs reconciliation" : draft.status === "approved" ? "awaiting publication" : draft.review_status !== "passed" ? "review needed" : draft.review_kind === "human" ? "human reviewed" : policySummary(draft)}</span>
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
                    {selectedDraft.publish_blocked ? "publication needs reconciliation" : selectedDraft.status === "approved" ? "awaiting publication" : controls.conflict ? "conflicting versions" : controls.needsReview ? "review needed" : selectedDraft.review_kind === "human" ? "human reviewed" : "model checks current"}
                  </span>
                  <span className="workbench-pill">
                    signal {selectedDraft.score?.total ?? "—"}
                    {selectedDraft.score?.label ? ` · ${selectedDraft.score.label}` : ""}
                  </span>
                  <span className="workbench-pill">
                    copy {selectedDraft.candidate_score?.total ?? "—"}
                    {selectedCandidate?.source ? ` · ${selectedCandidate.source}` : ""}
                  </span>
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
                    <textarea
                      className="draft-edit-area"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={4}
                    />
                    <div className={`draft-chars ${draftTextLength(editText) > 280 ? "over" : ""}`}>
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

                {controls.canReview && editingId !== selectedDraft.id && (
                  <div className="workbench-panel">
                    <h3>Review this version</h3>
                    <p>Previous checks do not cover this text. Check it against the source evidence below. Recording your review permits manual approval; it does not run or replace model checks.</p>
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
                      onClick={() => draftAct(selectedDraft.id, "review", { reviewConfirmed: true, expectedRevision: selectedDraft.revision_identity })}
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
                      {controls.needsReview
                        ? "This version needs review before approval."
                        : selectedDraft.review_kind === "human"
                        ? "Human review permits manual posting. Automatic scheduling requires current model checks."
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
                              alt #{c.rank} · copy {c.score?.total || 0} · {c.source}
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
                        onClick={() => draftAct(selectedDraft.id, "edit", { editedText: editText })}
                      >
                        Save
                      </button>
                      <button type="button" className="btn sm" onClick={() => setEditingId(null)}>
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
                        {draftAction === selectedDraft.id ? "..." : "Approve + Post"}
                      </button>
                      <button
                        type="button"
                        className="btn sm"
                        disabled={!!draftAction || !controls.canEdit}
                        onClick={() => startEditing(selectedDraft)}
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
                          {selectedDraft.status === "approved" ? "Cancel queued approval" : `Cancel ${countdownText(selectedDraft.auto_approve_at)}`}
                        </button>
                      ) : !controls.canSchedule ? (
                        <button type="button" className="btn sm" disabled>
                          {selectedDraft.review_kind === "human" ? "Manual posting only" : "Auto unavailable"}
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
          No drafts waiting. Trigger a run on the Pipeline tab or compose one manually.
        </div>
      )}
    </div>
  )
}
