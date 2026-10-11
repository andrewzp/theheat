import React from "react"
import { forecastEvidenceForDisplay } from "../../lib/forecast-evidence.js"

const h = React.createElement
const point = (lat, lon) => `${lat}, ${lon} (latitude, longitude)`
const field = (title, value) => h("div", { key: title }, h("dt", null, title), h("dd", null, value))

function Series({ series, date, timezone }) {
  const status = series.status === "missing" ? "Not supplied"
    : series.status === "invalid" ? "Unusable source values"
      : `${series.count}/24 samples${series.status === "incomplete" ? " · incomplete" : ""}`
  return h("details", { className: "forecast-series" },
    h("summary", null, `${series.label} · ${status}`),
    series.rows ? h("table", null,
      h("caption", null, `${series.label} · ${date} · ${timezone}`),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Local hour"), h("th", { scope: "col" }, series.unit))),
      h("tbody", null, series.rows.map(row => h("tr", { key: row.hour },
        h("th", { scope: "row" }, row.hour), h("td", null, row.value === null ? "Missing" : String(row.value))))))
      : h("p", null, `${status}. No hourly values are available in this saved input.`))
}

export function ForecastEvidence({ draft }) {
  const evidence = forecastEvidenceForDisplay(draft)
  if (evidence.status === "unsupported") return null
  const heading = h("h3", null, "Forecast behind this draft")
  if (evidence.status !== "present") return h("section", { className: "forecast-evidence", "aria-label": "Saved forecast evidence" },
    heading,
    h("p", null, evidence.status === "missing" ? "The hourly forecast was not saved with this draft."
      : "The saved forecast cannot be displayed because its fields are incomplete or inconsistent."),
    h("p", null, "Check the original source’s date, time window and values before recording a review. The compact saved facts remain below."))
  return h("section", { className: "forecast-evidence", "aria-label": "Saved forecast evidence" },
    heading, h("span", { className: "forecast-kind" }, "Model forecast"),
    h("dl", { className: "forecast-fields" },
      field("Local forecast day", `${evidence.date} · ${evidence.timezone}`),
      field("Requested place", `${evidence.location.city}, ${evidence.location.country}`),
      field("Sampled grid point", point(...evidence.grid)),
      field("Source", "CAMS via Open-Meteo")),
    h("p", null, "Saved model inputs, not station measurements or measured exposure. A grid point does not represent every location in the city. Required source checks still apply."),
    h("details", { className: "forecast-details" },
      h("summary", null, "Inspect timing, scope and hourly values"),
      h("dl", { className: "forecast-fields" },
        field("UTC interval start", evidence.validStart), field("UTC interval end (exclusive)", evidence.validEnd),
        field("Requested at (UTC)", evidence.requestedAt), field("Retrieved at (UTC)", evidence.retrievedAt),
        field("Requested coordinates", point(evidence.location.lat, evidence.location.lon))),
      h("p", null, evidence.method, ". PM2.5 and PM10 use the sample mean; dust, aerosol optical depth and US AQI use the sample maximum."),
      h("p", null, "Automatic domain selection does not identify the exact model, model run or native resolution. Co-reported dust and PM10 do not establish an event-specific cause."),
      h("p", null, "These are the saved values. Displaying them does not authenticate the source or approve this draft."),
      h("a", { href: "https://open-meteo.com/en/docs/air-quality-api", target: "_blank", rel: "noreferrer noopener" }, "Open-Meteo source documentation (opens in a new tab)"),
      h("div", { className: "forecast-series-list" }, evidence.series.map(series => h(Series, {
        key: series.key, series, date: evidence.date, timezone: evidence.timezone,
      })))))
}
