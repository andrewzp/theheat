// Product-level source outcomes, honest coverage rows and draft counts from retained
// state only. Plain language for the Health tab and Workbench; nothing here fetches,
// probes a credential or infers availability. Unknown stays unknown (null), never 0.
import { automaticTextHold } from "./automatic-text.js"
import { latestIncidentState } from "./source-incidents.js"

const OUTCOMES = Object.freeze({
  access_expired: ["Access expired", "Renew the expired credential (operator action). A stored key is not recovery."],
  baseline_unavailable: ["Comparison baseline unavailable", "Rebuild and upload the checksum-bound station thresholds asset; the release currently has none."],
  unqualified_input: ["Too few qualified inputs", "Qualified point normals are missing: run scripts/build_normals.py plan, then the bounded acquire and admit steps; Root installs the admitted file so ten places can qualify."],
  selector_or_budget_hold: ["Held by selector or budget", "Check the configured candidate budget and selector; no source fault is implied."],
  writer_or_check_rejection: ["Checked copy rejected", "Read the rejection reason; the source supplied a candidate."],
  stale_data: ["Data stale", "Wait for a newer source day; stale data is withheld, not posted."],
  endpoint_missing: ["Product endpoint missing", "HTTP 404/410 is not 'no events'. Supply an operator endpoint confirmation (scripts/source_incident_plan.py plan); no replacement URL is guessed."],
  reachable_unqualified: ["Reachable, not qualified", "The provider answered without qualified product rows; this is not recovery."],
  alternate_served: ["Served by an alternate leg", "The primary product is not recovered; an alternate leg of the same adapter is not independent corroboration."],
  regional_hold: ["Regional service held", "Each named national service needs its owner access and schema contract; supplied regions are unaffected and nothing is inferred for the held ones."],
  unavailable: ["Source unavailable", "Retry on the next scheduled run; other sources are unaffected."],
  no_event: ["Checked, no qualifying event", "Nothing to do; an empty result is not proof of complete coverage."],
  supplying: ["Supplying candidates", "Review the resulting drafts."],
  unknown: ["Unknown", "No retained run row explains this source yet."],
})

function text(value) { return typeof value === "string" ? value : "" }
function count(value) { return Number.isInteger(value) && value >= 0 ? value : null }

export function sourceOutcome(row, rejections = []) {
  if (!row || typeof row !== "object") return outcome("unknown", row)
  const error = text(row.error), note = text(row.note), details = row.details && typeof row.details === "object" ? row.details : {}
  const gate = details.rainfall_opportunity?.primary_gate
  if (gate === "credential_expired" || /token expired|credential_expired|expired \d{4}-\d{2}-\d{2}/i.test(error)) {
    return outcome("access_expired", row, row.source === "gpm_imerg" ? "GPM Earthdata token expired: a named access block." : null)
  }
  if (/threshold_baseline(?:_asset)?_unavailable/.test(error) || details.threshold_verification === "failure") return outcome("baseline_unavailable", row)
  if (/^hot10_short_slate/.test(note)) return outcome("unqualified_input", row)
  if (/candidate_budget|selector_(?:unavailable|invalid)|global_cap/.test(`${note} ${error}`)) return outcome("selector_or_budget_hold", row)
  if (/stale/i.test(error)) return outcome("stale_data", row)
  // Product-level incident payload (W03): name the exact leg, never the whole source.
  const incident = latestIncidentState(row)
  const named = incident?.failing?.map(item => `${item.product_id}: ${item.text ?? item.outcome}`).join("; ") || null
  if (incident?.product_state === "unavailable" && incident.failing.some(item => item.outcome === "endpoint_missing")) {
    return outcome("endpoint_missing", row, named)
  }
  if (incident?.product_state === "reachable_unqualified") return outcome("reachable_unqualified", row, named)
  const regional = details.regional_observed?.regions
  const held = regional && typeof regional === "object"
    ? Object.entries(regional).filter(([, r]) => r?.status !== "processed").map(([id, r]) => `${id}: ${text(r?.text) || text(r?.hold)}`)
    : []
  if (held.length && !((count(row.promoted) ?? 0) > 0)) return outcome("regional_hold", row, held.join("; "))
  if (row.status === "failed") return outcome("unavailable", row, named)
  if (rejections.some(r => r?.source === row.source && ["writer", "safety", "fact_check", "critic", "honesty_gate"].includes(r?.stage))) {
    return outcome("writer_or_check_rejection", row)
  }
  if ((count(row.promoted) ?? 0) > 0) return outcome("supplying", row)
  if (incident?.product_state === "alternate_served") return outcome("alternate_served", row, named)
  if (["success", "degraded", "partial_failure"].includes(row.status)) return outcome("no_event", row)
  return outcome("unknown", row)
}

function outcome(state, row, detail = null) {
  const [label, next_action] = OUTCOMES[state]
  return { state, label, next_action, detail, source: row?.source ?? null, status: row?.status ?? null }
}

// Coverage denominators exactly as retained; sampled sources are never "global recall".
export function coverageRow(row) {
  const details = row?.details && typeof row.details === "object" ? row.details : {}
  const aq = details.aq_availability && typeof details.aq_availability === "object" ? details.aq_availability : null
  const regions = details.regional_observed?.regions && typeof details.regional_observed.regions === "object"
    ? Object.values(details.regional_observed.regions).filter(r => r?.status === "processed") : null
  const sum = key => regions.reduce((total, r) => total === null || count(r?.[key]) === null ? null : total + r[key], 0)
  const universe = regions?.length
    ? { checked: sum("requested_stations"), usable: sum("qualified_station_days"), label: "named stations in supplied packets" }
    : aq
    ? { checked: count(aq.requested_cities), usable: count(aq.observed_cities), label: "sampled catalogue cities" }
    : Number.isInteger(details.world_total)
      ? { checked: count(details.world_total), usable: count(details.cached_count), label: "sampled world cities", quarantined: count(details.identity_quarantined) }
      : { checked: null, usable: null, label: "unknown universe" }
  return {
    source: row?.source ?? null,
    observed: count(row?.observed), promoted: count(row?.promoted), triaged_in: count(row?.triaged_in),
    triaged_out: count(row?.triaged_out), writer_attempted: count(row?.writer_attempted), drafted: count(row?.drafted),
    universe, scope: "Checked sample only; not global recall and not a count of posts.",
  }
}

// Current draft counts: retained posted/rejected records are history, never a backlog.
export function draftStatusCounts(state) {
  const drafts = Array.isArray(state?.drafts) ? state.drafts : null
  if (!drafts) return { known: false, posted: null, rejected: null, pending: null, approved: null, retained_total: null }
  const by = status => drafts.filter(d => d?.status === status)
  const pending = by("pending")
  return {
    known: true, retained_total: drafts.length, posted: by("posted").length, rejected: by("rejected").length,
    pending: pending.length, approved: by("approved").length,
    automatic_text_ready: pending.filter(d => d.auto_approve_at && !Object.hasOwn(d, "media_attachment") && !automaticTextHold(d.text)).length,
    manual_image_review: pending.filter(d => Object.hasOwn(d, "media_attachment")).length,
    source_or_check_hold: pending.filter(d => d.automatic_source_hold || d.automatic_text_hold || d.post_error).length,
    note: "Posted and rejected drafts are retained history, not work waiting for review.",
  }
}
