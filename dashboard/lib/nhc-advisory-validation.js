// Server-only exact retained-byte validation; a bulletin hash is not authentication
// and this never re-reads NHC. The Python sender re-reads the fixed products itself.
import { createHash } from "node:crypto"
import { nhcAdvisoryForDisplay, nhcAdvisoryTiming } from "./nhc-advisory-evidence.js"
const digest = value => createHash("sha256").update(value, "utf8").digest("hex")
const ATTRIBUTED = ["issuing_authority", "storm", "advisory_number", "issued_at", "forecast_hazard_statement", "forecast_place"]

export function nhcAdvisoryValidation(draft, now = Date.now()) {
  const value = nhcAdvisoryForDisplay(draft)
  if (value.status === "unsupported") return { blocked: false }
  const invalid = { blocked: true, message: "The exact retained NHC advisory changed or is unreadable. Fresh source review is required." }
  if (value.status !== "present") return invalid
  try {
    const { record } = value, bundle = draft.review_context.two_bot.bundle
    if (digest(record.bulletin_utf8) !== record.bulletin_sha256) return invalid
    // Writer facts must be exactly the attributed record-derived facts: no expiry, no extra claim.
    const expected = [["National Hurricane Center (NHC)", "issuing_authority"], [value.storm, "storm"],
      [value.advisory, "advisory_number"], [record.times.issued_at, "issued_at"], [value.statement, "forecast_hazard_statement"],
      [value.place, "forecast_place"], ...value.context.map(text => [text, "source_reported_context"])]
    const facts = bundle.current_facts
    if (!Array.isArray(facts) || facts.length !== expected.length) return invalid
    for (const [index, [factValue, label]] of expected.entries()) {
      const fact = facts[index]
      if (fact?.label !== label || fact.value !== factValue || fact.source_name !== "NHC" || fact.source_url !== value.sourceUrl
          || fact.issued_at !== record.times.issued_at || fact.content_sha256 !== record.bulletin_sha256
          || Object.keys(fact).sort().join("|") !== "content_sha256|issued_at|label|source_name|source_url|value") return invalid
    }
    if (!ATTRIBUTED.every(label => facts.some(fact => fact.label === label))
        || bundle.headline_metric?.label !== "nhc_forecast_hazard" || bundle.headline_metric?.value !== value.statement
        || bundle.when !== record.times.issued_at) return invalid
    return nhcAdvisoryTiming(draft, now)
  } catch { return invalid }
}
