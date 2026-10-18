"use client"

import React from "react"
import { reportTimestamp } from "../../lib/runtime-report.js"

const h = React.createElement
function RecordedMoment({ at, age }) {
  const parsed = reportTimestamp(at)
  if (!Number.isFinite(parsed) || !Number.isFinite(age) || age < 0) return "Unknown"
  const elapsed = age < 1 ? `${Math.floor(age * 60)}m` : age < 24 ? `${Math.floor(age)}h` : `${Math.floor(age / 24)}d`
  return h(React.Fragment, null,
    h("time", { dateTime: at, title: at }, `${new Date(parsed).toISOString().slice(0, 16).replace("T", " ")} UTC`),
    h("small", null, `${elapsed} before snapshot`))
}

export function SourceHistorySnapshot({ asOf }) {
  const parsed = reportTimestamp(asOf)
  return h("p", { className: "source-history-note" }, "Snapshot assessed at ",
    Number.isFinite(parsed)
      ? h("time", { dateTime: asOf }, `${new Date(parsed).toISOString().replace("T", " ").replace("Z", " UTC")}`)
      : "an unknown time", ".")
}

export function SourceHistoryDates({ timing }) {
  return h("div", { className: "source-history-times" },
    h("span", null, h("strong", null, "Latest dated run"), h(RecordedMoment, { at: timing?.latest_recorded_at, age: timing?.latest_recorded_age_hours })),
    h("span", null, h("strong", null, "Last recorded success"), h(RecordedMoment, { at: timing?.last_successful_at, age: timing?.last_successful_age_hours })),
    timing?.latest_status_ambiguous ? h("small", { className: "source-time-warning" }, "Latest status is ambiguous.") : null,
    timing?.timestamp_coverage !== "supplied_rows_only" ? h("small", { className: "source-time-warning" }, "Some run times or statuses are unavailable.") : null,
    timing?.timestamp_precision === "collection_run_start" ? h("small", null, "Dates use the collection run’s start.") : null)
}
