"use client"

import React from "react"
import { copyNotes } from "../../lib/copy-gates.js"

const h = React.createElement

// Advisory copy notes for the text on screen. They mirror the free generation
// gate's bundle-blind rules; they never approve, block an operator edit, rewrite
// text or stand in for the required source/factual/safety checks.
export function CopyNotes({ text, id, live = false }) {
  const notes = copyNotes(text)
  return h("div", { id, className: "copy-notes", "aria-live": live ? "polite" : undefined },
    notes.length === 0
      ? h("p", { className: "copy-notes-empty" }, "No copy notes. This is not a factual or editorial check.")
      : h(React.Fragment, null,
        h("p", { className: "copy-notes-title" }, "Copy notes (advice only; checks still decide)"),
        h("ul", null, notes.map(item => h("li", { key: item.code, "data-code": item.code },
          h("strong", null, item.blocking ? "Generation rule" : "Note"), ": ", item.message, " ",
          h("span", { className: "copy-notes-excerpt" }, `“${item.excerpt}”`))))))
}
