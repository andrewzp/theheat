"use client"

import React, { useId, useRef, useState } from "react"
import { operatorClaimKindMatches, operatorReferencesForDisplay, quoteFromSelection, referenceChoices, resolveReference, retainedClaimFacts, validateReferenceItems } from "../../lib/operator-claim-reference-input.js"

const h = React.createElement
const factText = fact => `${fact.label.replaceAll("_", " ")}: ${fact.value === null ? "Not supplied" : String(fact.value)}${fact.unit ? ` ${fact.unit}` : ""}`
const disclaimer = "These connections were selected by an operator. They do not establish scientific support, source authenticity or independent verification."

// Mount with key=draft id + editing revision; parent owns the edit transaction.
// items is always the unsigned request shape, never a saved envelope/digest.
export function OperatorClaimReferences({ draft, text = draft?.text ?? "", items = [], onChange, editing = false, disabled = false }) {
  const selection = useRef(null), id = useId()
  const [quote, setQuote] = useState(null), [pointers, setPointers] = useState([])
  const [editingItem, setEditingItem] = useState(null), [message, setMessage] = useState("")
  const bundle = draft?.review_context?.two_bot?.bundle
  let facts = [], sourceProblem = ""
  try {
    if (bundle?.event_id !== draft?.event_id || !operatorClaimKindMatches(draft?.type, bundle?.signal_kind)) throw new Error("The source snapshot does not match this draft. Refresh before adding references.")
    facts = retainedClaimFacts(bundle)
  } catch (error) { sourceProblem = error.message }
  const view = operatorReferencesForDisplay(draft)
  const change = next => {
    try {
      validateReferenceItems(text, bundle, next)
      onChange(next)
      setQuote(null); setPointers([]); setEditingItem(null); setMessage("Reference changes are ready. Save the draft to keep them.")
    } catch (error) { setMessage(error.message) }
  }
  const selectQuote = () => {
    try {
      setQuote(quoteFromSelection(text, selection.current.selectionStart, selection.current.selectionEnd))
      setEditingItem(null); setPointers([]); setMessage("Quote selected. Choose its saved source facts below.")
    } catch (error) { setMessage(error.message) }
  }
  const inputItems = editing ? items : view?.status === "saved" ? view.items : []
  return h("section", { className: "forecast-evidence claim-evidence", "aria-label": "Operator-selected source references", style: { overflowWrap: "anywhere", minWidth: 0 } },
    h("h3", null, "Operator-selected source references"), h("p", { className: "text-muted" }, disclaimer),
    editing ? h(React.Fragment, null,
      h("p", null, "Saved references are hidden while editing. Select an exact quote, then choose the saved facts you want to connect. Save the draft to keep your changes."),
      sourceProblem ? h("p", { role: "status", className: "draft-feedback error" }, sourceProblem)
        : h(React.Fragment, null,
          h("label", { htmlFor: `${id}-quote` }, "Select a quote from the current draft"),
          h("textarea", { id: `${id}-quote`, ref: selection, readOnly: true, value: text, rows: 4, disabled,
            "aria-describedby": `${id}-help`, style: { width: "100%", boxSizing: "border-box", resize: "vertical" } }),
          h("p", { id: `${id}-help`, className: "text-muted" }, "Use the mouse or hold Shift with the arrow keys to select text. Then choose Use selected quote."),
          h("button", { type: "button", className: "btn sm btn-ghost", style: { minHeight: 44 }, disabled, onClick: selectQuote }, "Use selected quote"),
          quote && h("fieldset", { disabled, style: { minWidth: 0 } },
            h("legend", null, editingItem === null ? "Connect source facts" : "Change connected facts"), h("blockquote", null, quote.text),
            facts.length ? referenceChoices(facts).map(({ pointer, fact }) =>
              h("label", { key: pointer, style: { display: "flex", gap: 8, padding: "10px 0", alignItems: "flex-start" } },
                h("input", { type: "checkbox", checked: pointers.includes(pointer), onChange: event => setPointers(current => event.target.checked ? [...current, pointer] : current.filter(p => p !== pointer)) }),
                h("span", null, factText(fact))))
              : h("p", null, "No structured facts were saved. Add references after a source snapshot is available."),
            h("button", { type: "button", className: "btn sm btn-blue", style: { minHeight: 44 }, disabled: !pointers.length,
              onClick: () => {
                const item = { claim: quote, sources: pointers.map(pointer => ({ pointer })) }
                change(editingItem === null ? [...items, item] : items.map((old, index) => index === editingItem ? item : old))
              } }, editingItem === null ? "Add reference" : "Update reference"),
            h("button", { type: "button", className: "btn sm btn-ghost", style: { minHeight: 44 }, onClick: () => { setQuote(null); setEditingItem(null); setPointers([]) } }, "Cancel quote selection"))),
      message && h("p", { role: "status" }, message))
      : h("p", { role: "status" }, view?.status === "saved" ? "Saved for this exact text and source snapshot."
        : view?.status === "unavailable" ? "Saved references no longer match this text or source snapshot. Refresh, then select them again."
          : "No operator-selected references were saved. Edit the draft to connect a quote with retained source facts."),
    inputItems.length > 0 && h("ol", { className: "claim-list" }, inputItems.map((item, index) => h("li", { key: `${item.claim.start}:${item.claim.end}:${index}` },
      h("blockquote", null, item.claim.text),
      h("ul", null, item.sources.map(source => {
        let fact = source.fact
        if (editing) try { fact = resolveReference(facts, source.pointer).view } catch { fact = null }
        return h("li", { key: source.pointer }, fact ? factText(fact) : "Saved fact unavailable; select the source again.")
      })),
      editing && h(React.Fragment, null,
        h("button", { type: "button", className: "btn sm btn-ghost", style: { minHeight: 44 }, disabled, onClick: () => {
          setQuote(item.claim); setPointers(item.sources.map(row => row.pointer)); setEditingItem(index); setMessage("")
        } }, `Change reference ${index + 1}`),
        h("button", { type: "button", className: "btn sm btn-ghost", style: { minHeight: 44 }, disabled, onClick: () => change(items.filter((_, i) => i !== index)) }, `Remove reference ${index + 1}`))))),
    !editing && view?.status === "saved" && h(React.Fragment, null,
      h("p", null, `Saved source label: ${view.source_label || "Unknown"}`),
      h("p", null, `Saved source type: ${view.source_type || "Unknown"}`), h("p", null, `Saved source time: ${view.when || "Unknown"}`),
      h("p", null, `Saved place: ${view.where || "Unknown"}`), h("p", null, `Source scope: ${view.scope || "Unknown"}`),
      h("p", null, `Issue time: ${view.issued_at || "Unknown"}`), h("p", null, `Valid time: ${view.valid_start || "Unknown"} to ${view.valid_end || "Unknown"}`),
      h("p", { className: "text-muted" }, "A retained source fact is not an external official citation.")))
}

export function OperatorClaimReferenceHistory({ draft, editing = false }) {
  const history = draft?.operator_claim_reference_history
  if (editing || !Array.isArray(history) || !history.length) return null
  return h("details", { className: "forecast-evidence", "aria-label": "Historical operator-selected references" },
    h("summary", null, "Earlier operator-selected references"),
    h("p", null, "Historical connections only. They do not apply to the current draft or record a current review."),
    history.map((row, index) => h("article", { key: index },
      h("h4", null, row.content_revision === null ? "Earlier version unavailable" : `Earlier version ${row.content_revision}`),
      h(OperatorClaimReferences, { draft: row }))))
}
