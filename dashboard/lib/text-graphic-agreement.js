// Joint-review aid (P31 text/plot agreement): which measured values in the tweet are
// not stated by the graphic's own description (the projection rendered from the same
// source rows). Deterministic and advisory: a value can be correct from the source
// and still be absent from the image (a departure, a multiple); software never reads
// pixels, and an empty list is not proof of agreement or truth.

const UNIT = String.raw`(°\s?C|°\s?F|µg\/m³|μg\/m³|ug\/m3|MW|mm|km\/h|km|mph|kt|knots|hPa|cm|m|%)`
const VALUE = new RegExp(String.raw`(?<![\w.])([-−]?\d{1,3}(?:,\d{3})+|[-−]?\d+(?:\.\d+)?)\s?` + UNIT + String.raw`(?![A-Za-z])`, "g")
const MAX_TEXT = 4000

function parse(raw) { return Number(raw.replace(/,/g, "").replace("−", "-")) }
function dimension(unit) {
  return unit.replace(/\s/g, "").replace(/^(?:µg\/m³|μg\/m³|ug\/m3)$/, "pm_mass")
    .replace(/^(?:kt|knots)$/, "knots")
}
function decimals(raw) { const dot = raw.indexOf("."); return dot < 0 ? 0 : raw.length - dot - 1 }
function roundTo(value, places) { const f = 10 ** places; return Math.round(value * f) / f }

export function textGraphicAgreement(text, description) {
  if (typeof text !== "string" || typeof description !== "string" || !description.trim()
      || text.length > MAX_TEXT || description.length > 16 * MAX_TEXT) {
    return { status: "not_comparable", unmatched: [], compared: 0 }
  }
  const stated = [...description.matchAll(VALUE)].map(m => ({ value: parse(m[1]), unit: dimension(m[2]) }))
    .filter(row => Number.isFinite(row.value))
  const unmatched = []
  let compared = 0
  for (const match of text.matchAll(VALUE)) {
    const [whole, raw, unit] = match
    const value = parse(raw), places = decimals(raw.replace(/,/g, ""))
    if (!Number.isFinite(value)) continue
    compared += 1
    const wanted = dimension(unit)
    const candidates = stated.flatMap(row => row.unit === wanted ? [row.value]
      : wanted === "°F" && row.unit === "°C" ? [row.value * 9 / 5 + 32]
        : wanted === "°C" && row.unit === "°F" ? [(row.value - 32) * 5 / 9] : [])
    if (!candidates.some(c => roundTo(c, places) === roundTo(value, places))) unmatched.push(whole.trim())
  }
  return { status: compared ? "compared" : "no_measured_values", unmatched: [...new Set(unmatched)], compared }
}
