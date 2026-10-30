"use client"

import React, { useId, useState } from "react"

const h = React.createElement
const fields = { likes: "Likes", retweets: "Reposts", replies: "Replies", quotes: "Quotes", impressions: "Impressions", bookmarks: "Bookmarks" }
const utc = value => value.replace("T", " ").replace(".000000Z", " UTC").replace(/Z$/, " UTC")
function postAge(seconds) {
  if (seconds === null) return "Unknown"
  if (seconds < 60) return `${seconds}s after posting`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m after posting`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h after posting`
  return `${Math.floor(seconds / 86400)}d ${Math.floor(seconds % 86400 / 3600)}h after posting`
}

function Observation({ item, position, total }) {
  return h("li", { "aria-posinset": position, "aria-setsize": total, style: { borderTop: "1px solid #333", padding: "12px 0", minWidth: 0 } },
    h("p", { style: { fontSize: 12, lineHeight: 1.6, overflowWrap: "anywhere" } },
      item.collected_at ? h("time", { dateTime: item.collected_at }, utc(item.collected_at)) : "Collection time unknown or invalid",
      " · ", item.kind === "legacy" ? "Legacy snapshot" : "Saved observation"),
    item.association === "unusable" && h("p", { className: "runtime-note" }, "Observation identity or source is unusable; values are withheld."),
    item.writer_context_status && h("p", { className: "runtime-note" }, item.writer_context_status === "recorded" ? "This observation references the retained publication context." : item.writer_context_status === "conflict" ? "This observation has conflicting publication context." : "This observation’s publication-context reference is unavailable."),
    item.conflict && h("p", { className: "runtime-note" }, "Conflicting observations at this collection time are all retained."),
    h("p", { className: "runtime-note" }, `Post age: ${postAge(item.post_age_seconds)}${item.age_status === "conflict" ? " · stored age conflicts with the recorded times" : ""}`),
    h("dl", { className: "runtime-settings", style: { gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 8rem), 1fr))", fontVariantNumeric: "tabular-nums" } },
      ...Object.entries(fields).map(([key, label]) => h("div", { key }, h("dt", null, label), h("dd", null, item.counts[key] === null ? "Unknown" : String(item.counts[key]))))))
}

export default function PostOutcomeHistory({ outcomes }) {
  const id = useId()
  const [view, setView] = useState({ post: "", page: 0 })
  const posts = outcomes?.posts || []
  const selected = posts.find(post => post.tweet_id === view.post) || posts[0]
  const total = selected?.observations.length || 0
  const page = Math.min(selected?.tweet_id === view.post ? view.page : 0, Math.max(0, Math.ceil(total / 100) - 1))
  const start = page * 100
  return h("details", { className: "runtime-details", style: { minWidth: 0 } },
    h("summary", { style: { minHeight: 44 } }, "Retained post history"),
    h("p", { className: "runtime-note" }, "Saved observations only. Opening this view does not collect metrics. Missing values are unknown, not zero."),
    !posts.length ? h("p", { className: "runtime-note", role: "status" }, outcomes?.status === "no_retained_receipts"
      ? "No publication receipts are retained in this view." : "Retained publication evidence is unavailable.") : h(React.Fragment, null,
      h("label", { htmlFor: id, className: "runtime-note" }, "Post with a retained receipt"),
      h("select", { id, value: selected.tweet_id, onChange: event => setView({ post: event.target.value, page: 0 }),
        style: { display: "block", width: "100%", minHeight: 44, margin: "8px 0 12px", background: "#161616", color: "#ddd", border: "1px solid #666", padding: 8, font: "inherit" } },
      ...posts.map(post => h("option", { key: post.tweet_id, value: post.tweet_id }, `Post ${post.tweet_id}`))),
      h("div", { "aria-live": "polite", "aria-atomic": true },
        h("p", { className: "runtime-note" }, selected.revision_status === "conflict" ? "Published revision conflicts; no text has been selected."
          : selected.revision_status === "unknown" ? "Published revision is unknown. Today's draft text is not used."
            : selected.text === null ? "Published text fingerprint is retained; the matching text is unavailable." : "Text matches the retained published fingerprint."),
        selected.text !== null && h("blockquote", { style: { margin: "12px 0", lineHeight: 1.6, overflowWrap: "anywhere" } }, selected.text),
        h("p", { className: "runtime-note" }, selected.publication_context?.status === "recorded"
          ? `Recorded type: ${selected.publication_context.type.replaceAll("_", " ")}. ${selected.publication_context.source ? "Source evidence matches the published revision." : "Source evidence details are unknown."}`
          : selected.publication_context?.status === "conflict" ? "Published type or source evidence conflicts; no context has been selected."
            : "Published type and source evidence are unknown."),
        h("p", { className: "runtime-note" }, selected.writer_context?.status === "recorded"
          ? `Writer-reported angle (captured accepted result): ${selected.writer_context.writer_reported_angle.replaceAll("_", " ")}. Published text ${selected.writer_context.text_comparison === "matches" ? "matches" : "differs from"} the captured writer text.`
          : selected.writer_context?.status === "conflict" ? "Writer and text observations conflict; no provenance has been selected."
            : "Writer-reported angle and text provenance are unknown."),
        selected.writer_context?.status === "recorded" && h("p", { className: "runtime-note" },
          `${selected.writer_context.retained_different_text ? "Retained history includes different text. " : ""}Retained history is incomplete${selected.writer_context.history_unavailable ? " and includes unavailable observations" : ""}. A text match does not establish that no edits occurred. Actor and human authorship are unknown.`),
        h("p", { className: "runtime-note" }, `${selected.observations.length} retained observations. Post age uses the platform's recorded creation time; receipt time is not a substitute.`),
        h("p", { className: "runtime-note" }, `Retained text versions for this post: ${selected.retained_text_versions ?? "unknown"}. Who edited them is not recorded here.`),
        selected.evidence_needed?.length ? h("p", { className: "runtime-note" }, `Still needed to know more: ${selected.evidence_needed.map(item => ({
          published_revision: "the exact published revision", published_type_and_source: "the published type and source evidence",
          metric_observation: "a metric observation", platform_creation_time: "the platform's creation time" })[item] || item.replaceAll("_", " ")).join("; ")}.`) : null,
        h("p", { className: "runtime-note" }, selected.feedback?.status === "recorded"
          ? `Your feedback: ${selected.feedback.editorial_opinions} rating(s); tags ${Object.entries(selected.feedback.revision_tags).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join(", ") || "none"}.`
          : selected.feedback?.status === "none_recorded" ? "No feedback recorded for this post. That is not a negative score."
            : "Feedback is shown in the feedback section; it is not loaded in this view."),
        selected.corrections?.status === "candidates" && h("div", { role: "note" },
          h("p", null, "Correction candidates for your review (nothing is corrected or deleted automatically):"),
          h("ul", null, ...selected.corrections.candidates.map((c, i) => h("li", { key: i, style: { overflowWrap: "anywhere" } },
            `“${c.claim}” — ${c.kind}: ${c.source_statement} (retrieved ${c.source_retrieved_at}; uncertainty: ${c.uncertainty})`)))),
        selected.corrections?.status === "evidence_needed" && h("p", { className: "runtime-note" },
          `A supplied discrepancy is incomplete: ${selected.corrections.incomplete.flat().map(item => item.replaceAll("_", " ")).join("; ")}.`)),
      selected.publication_context?.status === "recorded" && selected.publication_context.source && h("details", { className: "runtime-details" },
        h("summary", { style: { minHeight: 44 } }, "Source evidence details"),
        h("dl", { style: { fontSize: 12, lineHeight: 1.6, overflowWrap: "anywhere" } },
          h("dt", null, "Recorded signal"), h("dd", null, selected.publication_context.source.signal_kind.replaceAll("_", " ")),
          h("dt", null, "Event reference"), h("dd", null, selected.publication_context.source.event_id),
          h("dt", null, "Evidence fingerprint"), h("dd", null, selected.publication_context.source.bundle_sha256))),
      !!selected.writer_context?.variants?.length && h("details", { className: "runtime-details" },
        h("summary", { style: { minHeight: 44 } }, "Retained writer and text observation variants"),
        h("ul", { style: { fontSize: 12, lineHeight: 1.6, overflowWrap: "anywhere" } },
          ...selected.writer_context.variants.map(variant => h("li", { key: variant.sha256 }, `${variant.status}: ${variant.sha256}`)))),
      !selected.observations.length && h("p", { className: "runtime-note" }, selected.history_status === "unreadable_or_empty"
        ? "The retained metric row has no readable observations." : "No metric observations were retained for this post."),
      total > 100 && h("nav", { "aria-label": "Observation pages", style: { display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", margin: "12px 0" } },
        h("button", { className: "btn sm", type: "button", disabled: page === 0, style: { minHeight: 44 }, onClick: () => setView({ post: selected.tweet_id, page: page - 1 }) }, "Previous observations"),
        h("button", { className: "btn sm", type: "button", disabled: start + 100 >= total, style: { minHeight: 44 }, onClick: () => setView({ post: selected.tweet_id, page: page + 1 }) }, "Next observations"),
        h("p", { className: "runtime-note", role: "status" }, `Showing ${start + 1}–${Math.min(start + 100, total)} of ${total}`)),
      h("ol", { style: { listStyle: "none", padding: 0, margin: 0 } },
        ...selected.observations.slice(start, start + 100).map((item, index) => h(Observation, { key: item.id, item, position: start + index + 1, total })))),
    h("p", { className: "runtime-note" }, "Counts can change and posts may be different ages. These figures alone don’t show improvement. Writer angles are self-reported; saved text changes don’t identify an editor."))
}
