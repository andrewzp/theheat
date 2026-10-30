"use client"
import React, { useEffect, useState } from "react"
import PostOutcomeHistory from "./PostOutcomeHistory.js"
const h = React.createElement
const STORAGE = "theheat.editorial-feedback.pending.v1"
const copy = {
  feedback_write_uncertain:"The save could not be confirmed. Check this request before adding another rating.",
  post_changed:"The saved post changed. Refresh and read the current version before rating.",
  feedback_capacity:"The feedback archive is full. Your existing ratings are preserved.",
}
const message = code => copy[code] || "Feedback is unavailable right now. Your post and publishing settings are unchanged."
const sameInput = (a, b) => (Object.hasOwn(a || {}, "subject")
  ? ["request_id", "subject", "note"].every(k => a?.[k] === b?.[k]) && JSON.stringify(a?.tags) === JSON.stringify(b?.tags)
  : ["request_id", "punch", "clarity", "economy", "note", "own_rating"].every(k => a?.[k] === b?.[k])) &&
  a?.target && b?.target && Object.keys(a.target).every(k => a.target[k] === b.target[k])
const TAGS = [["concise", "Concise"], ["useful", "Useful"], ["confusing", "Confusing"], ["incorrect", "Looks incorrect"]]

// W15.3: optional tags on one exact draft or posted revision. Nothing is required; leaving it blank saves nothing.
export function RevisionFeedbackForm({revision, blocked, busy, onSave}) {
  const [subject, setSubject] = useState("copy")
  const [tags, setTags] = useState([])
  const [note, setNote] = useState("")
  const hasGraphic = revision.target.graphic_sha256 !== null
  const s = revision.summary
  const canSave = tags.length > 0 && !blocked && (subject === "copy" || hasGraphic)
  return h("form", {className:"revision-feedback", onSubmit:e => {e.preventDefault(); if (canSave) onSave({request_id:crypto.randomUUID(),
    target:revision.target, subject, tags:TAGS.map(([k]) => k).filter(k => tags.includes(k)), note})}},
    h("p", {className:"runtime-note"}, `${revision.target.status === "posted" ? "Posted" : "Draft"} revision ${revision.target.content_revision}` +
      (s.status === "recorded" ? ` · ${s.records} saved: ${TAGS.map(([k, l]) => s.tags[k] ? `${l.toLowerCase()} ${s.tags[k]}` : null).filter(Boolean).join(", ")}` : " · no feedback yet")),
    h("fieldset", {disabled:blocked}, h("legend", null, "Optional feedback on this exact version"),
      h("div", {role:"radiogroup", "aria-label":"What are you commenting on?"}, ...[["copy", "The words"], ["graphic", "The graphic"]].map(([key, label]) =>
        h("label", {key}, h("input", {type:"radio", name:`subject-${revision.target.draft_id}`, value:key, checked:subject === key,
          disabled:key === "graphic" && !hasGraphic, onChange:() => setSubject(key)}), label))),
      h("div", {className:"revision-feedback-tags"}, ...TAGS.map(([key, label]) => h("label", {key}, h("input", {type:"checkbox", checked:tags.includes(key),
        onChange:e => setTags(list => e.target.checked ? [...list, key] : list.filter(k => k !== key))}), label))),
      h("label", null, "Why? (optional)", h("textarea", {value:note, maxLength:500, rows:2, onChange:e => setNote(e.target.value)})),
      h("p", {className:"runtime-note"}, "This is your opinion. It does not check facts, change the draft, approve or correct anything."),
      h("button", {type:"submit", className:"btn", disabled:!canSave}, busy ? "Saving…" : "Save feedback")))
}

function RatingForm({post, blocked, busy, onSave}) {
  const [scores, setScores] = useState({punch:"", clarity:"", economy:""})
  const [note, setNote] = useState("")
  const [own, setOwn] = useState(false)
  const recent = post.ratings[0]
  const canSave = own && Object.values(scores).every(v => v !== "") && !blocked
  return h("form", {onSubmit:e => {e.preventDefault(); if (canSave) onSave({request_id:crypto.randomUUID(), target:post.target,
    ...Object.fromEntries(Object.entries(scores).map(([k,v]) => [k, Number(v)])), note, own_rating:true})}},
    h("a", {href:`https://x.com/theheat/status/${post.target.tweet_id}`, target:"_blank", rel:"noreferrer"}, "View on X"),
    h("blockquote", {className:"post-feedback-text"}, post.target.text),
    h("p", {className:"runtime-note"}, `${[...post.target.text].length} characters · posted ${new Date(post.target.posted_at).toLocaleString()}`),
    recent ? h("p", {className:"runtime-note"}, `Last saved: punch ${recent.punch}/5 · clarity ${recent.clarity}/5 · economy ${recent.economy}/5.`,
      recent.note && h("span", {className:"post-feedback-note"}, ` Note: ${recent.note}`)) : h("p", {className:"runtime-note"}, "No editorial rating yet."),
    h("fieldset", {disabled:blocked}, h("legend", null, "How well does this sentence work?"),
      h("div", {className:"post-feedback-scores"}, ...[["punch", "Punch", "Does it make the stakes clear?"], ["clarity", "Clarity", "Is it easy to understand?"], ["economy", "Economy", "Does every word earn its place?"]].map(([key,label,help]) =>
        h("label", {key}, label, h("span", {className:"runtime-note"}, help), h("select", {value:scores[key], onChange:e => setScores(s => ({...s,[key]:e.target.value})), required:true},
          h("option", {value:""}, "Choose a score"), ...[1,2,3,4,5].map(n => h("option", {key:n,value:n}, `${n} — ${n === 1 ? "weak" : n === 5 ? "strong" : n === 3 ? "mixed" : n === 2 ? "needs work" : "good"}`)))))),
      h("label", {className:"post-feedback-note-label"}, "What should change? (optional)", h("textarea", {value:note,maxLength:500,rows:3,onChange:e => setNote(e.target.value)})),
      h("label", {className:"post-feedback-confirm"}, h("input", {type:"checkbox",checked:own,onChange:e => setOwn(e.target.checked)}), "These are my own editorial ratings."),
      h("button", {type:"submit",className:"btn",disabled:!canSave}, busy ? "Saving…" : "Save editorial feedback")))
}

export default function PostFeedback({enabled = true}) {
  const [data, setData] = useState(null), [selected, setSelected] = useState("")
  const [error, setError] = useState(""), [notice, setNotice] = useState("")
  const [serial, setSerial] = useState(0), [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(null), [ready, setReady] = useState(false)
  useEffect(() => {
    try { const value = sessionStorage.getItem(STORAGE); if (value) setPending(JSON.parse(value)) }
    catch { setError("The pending save could not be read. Reload this page before saving feedback."); return }
    setReady(true)
  }, [])
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    const timer = setTimeout(() => {controller.abort(); setData(null); setError(message())}, 15000)
    setError("")
    fetch("/api/post-feedback", {cache:"no-store",signal:controller.signal,redirect:"error"})
      .then(async r => {const value = await r.json(); if (!r.ok) throw new Error(message(value.code)); return value})
      .then(value => { if (!controller.signal.aborted) {setData(value); setSelected(id => value.posts.some(p => p.target.draft_id === id) ? id : value.posts[0]?.target.draft_id || "")} })
      .catch(e => {if (!controller.signal.aborted) {setData(null); setError(e.message || message())}})
      .finally(() => clearTimeout(timer))
    return () => {clearTimeout(timer); controller.abort()}
  }, [enabled, serial])
  const post = data?.posts.find(p => p.target.draft_id === selected)
  const [revisionId, setRevisionId] = useState("")
  const revision = data?.revisions?.find(r => r.target.draft_id === revisionId) || data?.revisions?.[0]
  function clearPending() {sessionStorage.removeItem(STORAGE); setPending(null)}
  async function save(value) {
    if (busy || pending) return
    setError(""); setNotice("")
    // Persist the exact request before the first write; never automatically retry.
    try {sessionStorage.setItem(STORAGE, JSON.stringify(value)); setPending(value)}
    catch {setError("This browser cannot retain a save receipt. Feedback has not been sent."); return}
    setBusy(true)
    try {
      const r = await fetch("/api/post-feedback", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(value),redirect:"error",signal:AbortSignal.timeout(20000)})
      const result = await r.json()
      if (!r.ok || !sameInput(result.record, value)) {
        // Definite validation/refusal responses made no write. Everything else
        // retains the request ID and requires a read-only confirmation.
        if ([400,401,403,409].includes(r.status)) {clearPending(); throw new Error(message(result.code))}
        throw new Error(copy.feedback_write_uncertain)
      }
      clearPending(); setNotice(Object.hasOwn(value, "subject") ? "Feedback saved. The draft and publishing settings are unchanged."
        : "Editorial feedback saved. Publishing settings are unchanged."); setSerial(n => n+1)
    } catch (e) {setError(e.message || copy.feedback_write_uncertain)}
    finally {setBusy(false)}
  }
  async function check() {
    if (!pending || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const r = await fetch(`/api/post-feedback?request_id=${encodeURIComponent(pending.request_id)}`, {cache:"no-store",redirect:"error",signal:AbortSignal.timeout(15000)})
      const result = await r.json()
      if (!r.ok) throw new Error(message(result.code))
      if (result.request && sameInput(result.request, pending)) {clearPending(); setNotice("Editorial feedback confirmed saved."); setSerial(n => n+1)}
      else setNotice("This request is not confirmed in the archive. No retry was sent. Keep its ID for investigation.")
    } catch {setError(copy.feedback_write_uncertain)} finally {setBusy(false)}
  }
  return h("section", {className:"card full post-feedback", "aria-label":"Posted tweet feedback"},
    h("h2", null, "Make the next tweet better"),
    h("p", {className:"runtime-note"}, "Rate the exact published sentence. This saves your editorial opinion; it does not check facts, approve posts or measure engagement."),
    !enabled ? h("p", null, "Feedback is available on confirmed X posts in the production dashboard.") : h(React.Fragment, null,
      error && h("p", {role:"alert"}, error), notice && h("p", {role:"status"}, notice),
      pending && h("div", {className:"post-feedback-pending",role:"status"}, h("p", null, "A previous save needs confirmation."), h("code", null, pending.request_id),
        h("button", {className:"btn",type:"button",disabled:busy,onClick:check}, busy ? "Checking…" : "Check saved feedback")),
      !data && !error && h("p", {role:"status"}, "Loading published tweets…"),
      data && data.posts.length === 0 && h("p", null, "No posts have a matching delivery receipt yet. Feedback will appear here after a confirmed post."),
      data && data.posts.length > 0 && h(React.Fragment, null,
        h("label", null, "Published tweet", h("select", {value:selected,disabled:busy,onChange:e => {setSelected(e.target.value); setNotice("")}},
          ...data.posts.map(p => h("option", {key:p.target.draft_id,value:p.target.draft_id}, `${p.target.text.slice(0,75)}${p.target.text.length > 75 ? "…" : ""}`)))),
        data.remaining === 0 && h("p", {role:"status"}, copy.feedback_capacity),
        post && h(RatingForm, {key:JSON.stringify([post.target, post.ratings[0]?.request_id]),post,busy,blocked:busy || !!pending || !ready || data.remaining === 0,onSave:save})),
      data && data.revisions?.length > 0 && h("section", {"aria-label":"Feedback on drafts and posts"},
        h("h3", null, "Feedback on a draft or post"),
        h("label", null, "Version", h("select", {value:revision?.target.draft_id || "", disabled:busy, onChange:e => {setRevisionId(e.target.value); setNotice("")}},
          ...data.revisions.map(r => h("option", {key:r.target.draft_id, value:r.target.draft_id}, `${r.target.status} · ${r.target.draft_id}`)))),
        revision && h(RevisionFeedbackForm, {key:JSON.stringify([revision.target, revision.summary.records]), revision, busy,
          blocked:busy || !!pending || !ready || data.remaining === 0, onSave:save})),
      data?.outcomes && h("section", {"aria-label":"Published outcomes with your feedback"},
        h("h3", null, "Published outcomes with your feedback"), h(PostOutcomeHistory, {outcomes:data.outcomes})),
      h("button", {className:"btn sm",type:"button",disabled:busy,onClick:() => setSerial(n => n+1)}, "Refresh feedback")))
}
