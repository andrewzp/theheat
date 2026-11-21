// Product-level source outcomes, honest coverage rows and draft counts from retained
// state only. Plain language for the Health tab and Workbench; nothing here fetches,
// probes a credential or infers availability. Unknown stays unknown (null), never 0.
import { automaticTextHold } from "./automatic-text.js"
import { latestIncidentState } from "./source-incidents.js"

const OUTCOMES = Object.freeze({
  access_expired: ["Access expired", "Renew the expired credential (operator action). A stored key is not recovery."],
  baseline_unavailable: ["Comparison baseline unavailable", "The thresholds release has no asset. Run scripts/build_station_thresholds.py resolve-inputs, fetch-inputs and package (one bounded, byte-pinned NOAA GHCN-Daily input set), upload the printed asset to thresholds-latest, then install-manifest; the next run's threshold ensure verifies it."],
  unqualified_input: ["Too few qualified inputs", "Qualified point normals are missing: run scripts/build_normals.py plan, then the bounded Meteostat acquire, admit and install-plan steps; Root installs the admitted file so ten places can qualify."],
  access_refused: ["Access refused", "Owner checks the refused account or key. The same credential is retried only on its bounded backoff; a renewed credential is tried at the next run. A stored key is not recovery."],
  selector_or_budget_hold: ["Held by selector or budget", "Check the configured candidate budget and selector; no source fault is implied."],
  writer_or_check_rejection: ["Checked copy rejected", "Read the rejection reason; the source supplied a candidate."],
  stale_data: ["Data stale", "Wait for a newer source day; stale data is withheld, not posted."],
  endpoint_missing: ["Product endpoint missing", "HTTP 404/410 is not 'no events'. Supply an operator endpoint confirmation (scripts/source_incident_plan.py plan); no replacement URL is guessed."],
  reachable_unqualified: ["Reachable, not qualified", "The provider answered without qualified product rows; this is not recovery."],
  alternate_served: ["Served by an alternate leg", "The primary product is not recovered; an alternate leg of the same adapter is not independent corroboration."],
  regional_hold: ["Regional service held", "Each named national service needs its owner access and schema contract; supplied regions are unaffected and nothing is inferred for the held ones."],
  unavailable: ["Source unavailable", "Retry on the next scheduled run; other sources are unaffected."],
  no_event: ["Checked, no qualifying event", "Nothing to do; an empty result is not proof of complete coverage."],
  policy_excluded: ["Excluded by observed-only policy", "Forecast air-quality collection was intentionally skipped. Current service availability is unverified; previous errors remain in history."],
  supplying: ["Supplying candidates", "Review the resulting drafts."],
  metrics_returned: ["Saved X metrics lookup", "Compare saved samples at matching post ages."],
  metrics_partial: ["X metrics lookup incomplete", "Inspect the missing samples."],
  metrics_skipped: ["X metrics polling skipped", "Check the saved polling history."],
  metrics_unavailable: ["X metrics result unavailable", "Inspect this polling run's status and counts."],
  rainfall_nominations: ["Rainfall report nominations recorded", "Inspect the saved nomination dispositions; nomination and queue counts do not establish a saved draft."],
  rainfall_reports_held: ["Rainfall reports held", "Check the named saved configuration hold; no nomination result was established."],
  rainfall_grid_held: ["Inland rainfall scan held", "Inspect the scan reason; city results remain separate."],
  rainfall_nominations_unavailable: ["Rainfall report nomination unavailable", "Inspect this source run's retained details; missing or inconsistent counts are not zero."],
  ghcn_intake_empty: ["No usable GHCN station-days retained", "Inspect the recorded exclusions and missing diffs; historical record qualification is a separate step."],
  ghcn_intake_unavailable: ["GHCN intake details unavailable", "Inspect a complete bound source run; missing or contradictory diagnostics cannot establish zero observations."],
  ghcn_fetch_unavailable: ["No GHCN diff payload returned", "Inspect the recorded HTTP or transport outcomes; archive validity and station observations remain unverified."],
  fire_reports_held: ["Incident reports held", "Inspect the held reports and admission decisions; a partial or withheld result is not an empty feed."],
  fire_reports_checked: ["Incident reports checked", "No candidate was queued in this saved run. Inspect size-tier, duplicate and selection decisions; complete event coverage is not established."],
  fire_reports_unavailable: ["Incident report details unavailable", "Inspect a complete bound source run; missing or inconsistent counts are unknown, not zero."],
  unknown: ["Unknown", "No retained run row explains this source yet."],
})

function text(value) { return typeof value === "string" ? value : "" }
function count(value) { return Number.isInteger(value) && value >= 0 ? value : null }

function fireReportStatus(row, current) {
  if (row.source !== "fire_footprint" || !["success", "degraded", "partial_failure"].includes(row.status)) return null
  const unavailable = { state: "fire_reports_unavailable", detail: "Saved incident-report counts are unavailable or inconsistent." }
  const d = row.details
  const integer = n => Number.isSafeInteger(n) && n >= 0 && n <= 2000
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
  const reasons = new Set(["child", "inactive_or_other_type", "invalid_size", "below_floor", "identity", "region",
    "report_clock", "discovery_clock", "stale", "name", "record_shape", "record_invalid"])
  const excluded = new Set(["child", "inactive_or_other_type", "below_floor"])
  const labels = { invalid_size: "invalid size", identity: "missing or invalid identity", region: "unsupported region",
    report_clock: "invalid report time", discovery_clock: "invalid discovery time", stale: "stale report",
    name: "invalid incident name", record_shape: "invalid record shape", record_invalid: "invalid record" }
  if (current !== true || !object(d) || !object(d.row_holds)
      || ![d.raw_rows, d.qualified_rows, d.held_rows, row.observed, row.promoted].every(integer)
      || !["triaged_in", "triaged_out", "writer_attempted", "drafted"].every(key => integer(row[key]))
      || !Object.keys(d).every(key => ["raw_rows", "qualified_rows", "held_rows", "row_holds", "coverage_truncated", "admission_holds"].includes(key))
      || typeof d.coverage_truncated !== "boolean"
      || !Object.entries(d.row_holds).every(([key, value]) => reasons.has(key) && integer(value))) return unavailable
  const partition = Object.values(d.row_holds).reduce((a, b) => a + b, 0)
  const held = Object.entries(d.row_holds).filter(([key]) => !excluded.has(key)).reduce((a, [, n]) => a + n, 0)
  const admission = Object.hasOwn(d, "admission_holds") ? d.admission_holds : 0
  if (!integer(partition) || partition + d.qualified_rows !== d.raw_rows || held !== d.held_rows
      || row.observed !== d.qualified_rows || !integer(admission) || admission + row.promoted > d.qualified_rows) return unavailable
  if (["triaged_in", "triaged_out", "writer_attempted", "drafted"].some(key => row[key] > row.promoted)) return unavailable
  const hasHold = held > 0 || admission > 0 || d.coverage_truncated
  if (row.status !== (hasHold ? "degraded" : "success")) return unavailable
  const holdReasons = Object.entries(d.row_holds).filter(([key, n]) => !excluded.has(key) && n > 0)
    .sort(([a], [b]) => a.localeCompare(b)).map(([key, n]) => `${labels[key]}: ${n}`).join("; ")
  const detail = `Saved incident reports: ${d.qualified_rows} qualified; ${held} held; ${admission} admission holds; ${row.promoted} queued. `
    + (holdReasons ? `Held rows: ${holdReasons}. ` : "")
    + `${d.coverage_truncated ? "Provider coverage was truncated." : "No provider truncation was recorded."} `
    + "These are report rows, not a complete count of fires or published posts."
  return { state: hasHold ? "fire_reports_held" : "fire_reports_checked", detail }
}

function twitterMetricsOutcome(row) {
  const unavailable = () => outcome("metrics_unavailable", row,
    "The saved polling result is missing or inconsistent. Missing counts are unknown.")
  // The existing producer's observed/promoted fields mean requested post IDs /
  // responses with usable public counts. They never denote weather or drafts.
  if (!["triaged_in", "triaged_out", "writer_attempted", "drafted"].every(key => row[key] === 0)
      || !safeCount(row.observed) || !safeCount(row.promoted) || row.promoted > row.observed) return unavailable()
  const noError = row.error == null || row.error === ""
  if (row.status === "skipped" && noError && row.promoted === 0) {
    let detail = null
    if (row.observed === 0 && row.note === "Metrics already polled today") {
      detail = "The daily polling opportunity was already used; it may have failed."
    } else if (row.observed === 0 && row.note === "No recent tweet ids to poll") {
      detail = "No recent post IDs were selected for polling."
    } else if (row.observed > 0 && row.note === "No Twitter credentials configured") {
      detail = "Polling credentials were unavailable in this saved run."
    }
    return detail ? outcome("metrics_skipped", row, `${detail} No new engagement counts were established.`) : unavailable()
  }
  if (row.observed < 1) return unavailable()
  const detail = `${row.observed} requested posts; ${row.promoted} with usable counts. Missing counts are unknown.`
  if (row.status === "success" && noError && row.promoted === row.observed) return outcome("metrics_returned", row, detail)
  if (row.status === "partial_failure" && row.promoted < row.observed) return outcome("metrics_partial", row, detail)
  return unavailable()
}

function ghcnFetch(m, context) {
  const f = m?.diff_fetch, c = f?.counts
  const names = ["payload_returned", "http_404", "http_401", "http_403", "http_429",
    "http_other_4xx", "http_5xx", "http_other_error", "timeout", "connection_error", "request_error"]
  const integer = n => Number.isSafeInteger(n) && n >= 0
  const day = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
  const start = typeof context?.started_at === "string" ? Date.parse(context.started_at) : NaN
  const end = typeof context?.ended_at === "string" ? Date.parse(context.ended_at) : NaN
  const fetchStart = typeof f?.started_at === "string" ? Date.parse(f.started_at) : NaN
  const fetchEnd = typeof f?.ended_at === "string" ? Date.parse(f.ended_at) : NaN
  if (context?.current !== true || !Number.isFinite(start) || !Number.isFinite(end) || end < start
      || !f || Array.isArray(f) || f.schema_version !== 1 || f.scope !== "client_get_invocations"
      || Object.keys(f).sort().join() !== "counts,ended_at,get_calls,schema_version,scope,started_at,target_count,window_day"
      || !Number.isFinite(fetchStart) || !Number.isFinite(fetchEnd)
      || fetchStart < start || fetchEnd > end || fetchEnd < fetchStart
      || !day(f.window_day) || f.window_day < new Date(start).toISOString().slice(0, 10)
      || f.window_day > new Date(end).toISOString().slice(0, 10)
      || !integer(f.target_count) || f.target_count < 1 || f.target_count > 366
      || !integer(f.get_calls) || !c || Array.isArray(c)
      || Object.keys(c).sort().join() !== [...names].sort().join() || !names.every(name => integer(c[name]))
      || names.reduce((total, name) => total + c[name], 0) !== f.get_calls
      || ![m.diff_dates_attempted, m.diff_dates_fetched, m.diff_dates_missing].every(integer)
      || m.diff_dates_attempted !== f.target_count || c.payload_returned !== m.diff_dates_fetched
      || m.diff_dates_fetched + m.diff_dates_missing !== f.target_count
      || f.get_calls > 10 * f.target_count
      || f.get_calls < c.payload_returned + 10 * (f.target_count - c.payload_returned)
      || !Array.isArray(m.diff_missing_dates) || m.diff_missing_dates.length !== m.diff_dates_missing
      || new Set(m.diff_missing_dates).size !== m.diff_dates_missing) return null
  const targets = new Set(Array.from({ length: f.target_count }, (_, i) =>
    new Date(Date.parse(f.window_day) - (i + 1) * 86400000).toISOString().slice(0, 10)))
  if (!m.diff_missing_dates.every(value => day(value) && targets.has(value))
      || (c.payload_returned === 0 && (m.diff_fetch_failed !== 1 || Object.hasOwn(m, "diff_intake")
        || ![m.station_obs_pairs, m.stations_with_obs].every(n => n === undefined || n === 0)))) return null
  const labels = {
    http_404: "HTTP 404", http_401: "HTTP 401", http_403: "HTTP 403", http_429: "HTTP 429",
    http_other_4xx: "other HTTP 4xx", http_5xx: "HTTP 5xx", http_other_error: ["other HTTP error", "other HTTP errors"],
    timeout: ["timeout", "timeouts"], connection_error: ["connection error", "connection errors"], request_error: ["other request error", "other request errors"],
  }
  const errors = Object.entries(labels).filter(([key]) => c[key] > 0)
    .map(([key, label]) => `${c[key]} ${Array.isArray(label) ? label[c[key] === 1 ? 0 : 1] : label}`)
  const detail = `Saved GHCN acquisition: ${f.get_calls} client calls; ${c.payload_returned} payloads returned`
    + (errors.length ? `; ${errors.join("; ")}` : "")
    + ". Redirects can add network requests; returned payloads still need validation."
  return { detail, noPayload: c.payload_returned === 0 }
}

function ghcnIntake(row, context) {
  if (row.source !== "open_meteo_extreme_signals") return null
  const d = row.details ?? {}
  const m = d.provider === "ghcn" ? d.pipeline_metrics
    : ["both", "both_global"].includes(d.provider) ? d.ghcn_pipeline_metrics : null
  if (d.provider !== "ghcn" && !["both", "both_global"].includes(d.provider)) return null
  const acquisition = ghcnFetch(m, context)
  if (acquisition?.noPayload) return { state: "ghcn_fetch_unavailable", detail: acquisition.detail, acquisitionDetail: acquisition.detail }
  const unavailable = { state: "ghcn_intake_unavailable", detail: "Saved GHCN intake details are unavailable or inconsistent."
    + (acquisition ? ` ${acquisition.detail}` : ""), acquisitionDetail: acquisition?.detail ?? null }
  const trace = m?.diff_intake, c = trace?.counts
  const names = ["parsed_temperature_rows", "inactive_station_rows", "too_old_rows", "future_rows",
    "usable_updates", "delete_updates", "unusable_updates", "final_values", "final_station_days"]
  const integer = n => Number.isSafeInteger(n) && n >= 0
  const day = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
  const timestamp = value => typeof value === "string" ? Date.parse(value) : NaN
  const start = timestamp(context?.started_at), end = timestamp(context?.ended_at)
  if (context?.current !== true || !Number.isFinite(start) || !Number.isFinite(end) || end < start
      || !m || m.threshold_verification !== "success" || !["success", "degraded"].includes(m.status)
      || !trace || trace.schema_version !== 1 || Object.keys(trace).sort().join() !== "counts,cutoff_day,schema_version,window_day"
      || !day(trace.window_day) || !day(trace.cutoff_day) || trace.cutoff_day > trace.window_day
      || trace.window_day < new Date(start).toISOString().slice(0, 10)
      || trace.window_day > new Date(end).toISOString().slice(0, 10)
      || !c || Array.isArray(c) || Object.keys(c).sort().join() !== [...names].sort().join()
      || !names.every(name => integer(c[name]))) return unavailable
  const partition = c.inactive_station_rows + c.too_old_rows + c.future_rows
    + c.usable_updates + c.delete_updates + c.unusable_updates
  if (!Number.isSafeInteger(partition) || partition !== c.parsed_temperature_rows
      || c.final_values > c.usable_updates || c.final_values < c.final_station_days
      || (c.usable_updates > 0 && c.delete_updates === 0 && c.unusable_updates === 0 && c.final_values === 0)
      || c.final_values > 2 * c.final_station_days
      || !integer(m.station_obs_pairs) || m.station_obs_pairs !== c.final_station_days
      || !integer(m.stations_with_obs) || m.stations_with_obs > c.final_station_days
      || (m.stations_with_obs === 0) !== (c.final_station_days === 0)
      || ![m.diff_dates_attempted, m.diff_dates_fetched, m.diff_dates_missing].every(integer)
      || m.diff_dates_fetched < 1 || m.diff_dates_fetched + m.diff_dates_missing !== m.diff_dates_attempted
      || (Object.hasOwn(m, "diff_fetch_failed") && m.diff_fetch_failed !== 0)) return unavailable
  const n = (value, noun) => `${value} ${noun}${value === 1 ? "" : "s"}`
  const detail = `Saved GHCN intake: ${n(c.parsed_temperature_rows, "temperature update")} parsed; `
    + `${n(c.inactive_station_rows, "inactive-station row")}; ${c.too_old_rows} older than the window; ${c.future_rows} future-dated; `
    + `${n(c.usable_updates, "usable update")}; ${n(c.delete_updates, "deletion")}; ${n(c.unusable_updates, "unusable update")}; `
    + `${n(c.final_values, "daily value")}; ${n(c.final_station_days, "station-day")} retained. `
    + `${m.diff_dates_fetched} of ${m.diff_dates_attempted} diffs fetched.`
  return { state: c.final_station_days === 0 ? "ghcn_intake_empty" : null,
    detail: detail + (acquisition ? ` ${acquisition.detail}` : "") }
}

function nwsAdmissionDetail(row) {
  if (row.source !== "nws_alerts" || row.status !== "success") return null
  const { response_features: received, adapter_selected: selected } = row.details?.nws_alert_admission ?? {}
  if (!Number.isSafeInteger(received) || !Number.isSafeInteger(selected)
      || selected < 0 || received < selected || selected !== row.observed) return null
  return `Saved NWS response contained ${received} alert entries. The adapter selected ${selected} under its warning criteria`
}

const RAINFALL_COUNTERS = Object.freeze([
  "input_rows", "untyped_rows", "identity_unavailable_rows", "identity_conflict_rows",
  "qualification_held_rows", "history_held_rows", "duplicate_qualified_rows",
  "qualified_events", "nominated_events", "nomination_cap_excluded",
])
const RAINFALL_HOLDS = Object.freeze({
  rainfall_time_invalid: "invalid source time",
  rainfall_reading_invalid: "invalid reading structure",
  rainfall_satellite_product_required: "required satellite product missing",
  rainfall_number_invalid: "invalid numeric reading",
  rainfall_point_invalid: "invalid registered point or day",
  rainfall_outside_automatic_range: "outside the automatic amount range",
  rainfall_reading_identity_changed: "reading identity changed",
  rainfall_evidence_invalid: "invalid evidence structure",
  rainfall_source_identity_changed: "source identity changed",
  rainfall_completed_window_expired: "completed window not current at nomination",
  rainfall_report_unqualified: "other qualification hold",
})
const RAINFALL_SETTINGS_HOLDS = Object.freeze({
  rainfall_observed_report_disabled: "observed report settings disabled",
  rainfall_report_publication_paused: "publication settings paused",
  rainfall_report_operation_limit_invalid: "operation limit invalid",
  rainfall_report_one_sample_required: "one-sample operation settings required",
})
const RAINFALL_SCOPE = "Input row dispositions and unique event nominations; not coverage or source-truth validation."
const RAINFALL_GRID_HOLDS = Object.freeze({
  rainfall_completed_window_expired: "completed source day outside its allowed age",
  rainfall_grid_attribute_invalid: "invalid or unsupported numeric metadata",
  rainfall_grid_axes_invalid: "invalid or unsupported coordinate axes",
  rainfall_grid_dataset_ambiguous: "ambiguous duplicate dataset layouts",
  rainfall_grid_dataset_invalid: "invalid or unsupported dataset structure",
  rainfall_grid_packed_data_unsupported: "unsupported packed or scaled data",
  rainfall_grid_product_invalid: "unsupported product or file size",
  rainfall_grid_time_invalid: "invalid or unsupported source time metadata",
  rainfall_grid_units_invalid: "invalid or unsupported precipitation units",
  rainfall_grid_clock_invalid: "invalid local scan clock",
  rainfall_grid_geography_unavailable: "required inland geography unavailable",
  rainfall_grid_geography_identity_changed: "inland geography identity changed",
  rainfall_grid_geography_invalid: "invalid inland geography",
})
function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && [Object.prototype, null].includes(Object.getPrototypeOf(value))
}
function exactKeys(value, keys) {
  return record(value) && Reflect.ownKeys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
}
function safeCount(value) { return Number.isSafeInteger(value) && value >= 0 }
function rainfallGridHold(row) {
  const value = row.details?.rainfall_grid_discovery
  if ((!exactKeys(value, ["schema", "status", "reason"])
      && !exactKeys(value, ["schema", "status", "reason", "hold_code"]))
      || value.schema !== "theheat.imerg-grid-discovery/v1" || value.status !== "held"
      || value.reason !== "rainfall_grid_frame_unqualified") return null
  const reason = typeof value.hold_code === "string" && Object.hasOwn(RAINFALL_GRID_HOLDS, value.hold_code)
    ? RAINFALL_GRID_HOLDS[value.hold_code] : "the specific cause was not retained"
  return `Saved inland rainfall scan held: ${reason}.`
}
function safeSum(values) {
  const total = values.reduce((sum, value) => sum + value, 0)
  return Number.isSafeInteger(total) ? total : null
}

const RAINFALL_GRID_SCOPE = "City row and discovered cell dispositions; joint unique cell nominations, not coverage or source truth."
const GRID_COUNTERS = Object.freeze(["input_rows", "identity_held_rows", "qualification_held_rows",
  "history_held_rows", "duplicate_qualified_rows", "qualified_events"])
const JOINT_COUNTERS = Object.freeze(["qualified_events", "nominated_events", "nomination_cap_excluded", "duplicate_cell_events"])

function rainfallGridNomination(row, outer, unavailable) {
  const n = outer.nomination, c = n.city, g = n.grid, j = n.joint
  const cityKeys = RAINFALL_COUNTERS.slice(0, 8)
  if (!exactKeys(n, ["schema", "city", "grid", "joint", "scope"]) || n.scope !== RAINFALL_GRID_SCOPE
      || !exactKeys(c, [...cityKeys, "qualification_holds"]) || !cityKeys.every(key => safeCount(c[key]))
      || !exactKeys(g, GRID_COUNTERS) || !GRID_COUNTERS.every(key => safeCount(g[key]))
      || !exactKeys(j, JOINT_COUNTERS) || !JOINT_COUNTERS.every(key => safeCount(j[key]))
      || !record(c.qualification_holds) || !safeCount(outer.nominated) || !safeCount(outer.queued)) return unavailable
  const codes = Reflect.ownKeys(c.qualification_holds)
  if (!codes.every(code => typeof code === "string" && Object.hasOwn(RAINFALL_HOLDS, code)
      && safeCount(c.qualification_holds[code]) && c.qualification_holds[code] > 0)) return unavailable
  const qualifiedInput = safeSum([c.qualified_events, g.qualified_events])
  if (c.input_rows !== row.observed || g.input_rows === 0
      || safeSum(cityKeys.slice(1).map(key => c[key])) !== c.input_rows
      || safeSum(GRID_COUNTERS.slice(1).map(key => g[key])) !== g.input_rows
      || safeSum(codes.map(code => c.qualification_holds[code])) !== c.qualification_held_rows
      || qualifiedInput === null || safeSum([j.qualified_events, j.duplicate_cell_events]) !== qualifiedInput
      || safeSum([j.nominated_events, j.nomination_cap_excluded]) !== j.qualified_events
      || j.nominated_events !== Math.min(3, j.qualified_events)
      || (c.duplicate_qualified_rows > 0 && c.qualified_events === 0)
      || (g.duplicate_qualified_rows > 0 && g.qualified_events === 0)
      || (j.duplicate_cell_events > 0 && j.qualified_events === 0)
      || outer.nominated !== j.nominated_events || outer.queued > outer.nominated || outer.queued > row.promoted
      || outer.status !== (outer.nominated > 0 ? "nominated" : "no_qualified_report")) return unavailable
  const reasons = [
    ["city rows with conflicting identities", c.identity_conflict_rows],
    ["city rows without a usable identity", c.identity_unavailable_rows], ["untyped city rows", c.untyped_rows],
    ...codes.sort().map(code => [RAINFALL_HOLDS[code], c.qualification_holds[code]]),
    ["city rows held by history", c.history_held_rows], ["duplicate city rows", c.duplicate_qualified_rows],
    ["grid inputs with unusable or conflicting identities", g.identity_held_rows],
    ["grid inputs held by qualification", g.qualification_held_rows], ["grid inputs held by history", g.history_held_rows],
    ["duplicate grid rows", g.duplicate_qualified_rows], ["same-cell events joined", j.duplicate_cell_events],
    ["excluded by the nomination cap", j.nomination_cap_excluded],
  ].filter(([, value]) => value > 0).map(([label, value]) => `${label}: ${value}`)
  return { state: "rainfall_nominations", detail:
    `Saved rainfall report nominations: ${c.input_rows} city input rows; ${g.input_rows} grid cell report inputs; `
    + `${j.qualified_events} qualified cells; ${outer.nominated} nominated; ${outer.queued} queued.`
    + (reasons.length ? ` Dispositions: ${reasons.join("; ")}.` : "")
    + " Retained decisions, not coverage, source truth, drafts or posts." }
}

// Read only the finite aggregate emitted by rainfall_observed.nominate and its
// real source caller. Never render a retained reason/scope as arbitrary prose.
function rainfallNomination(row, current) {
  if (row.source !== "gpm_imerg" || !["success", "degraded", "partial_failure"].includes(row.status)) return null
  const unavailable = { state: "rainfall_nominations_unavailable", detail: "Rainfall report nomination counts are unavailable for this saved source run." }
  if (!current || !safeCount(row.observed) || !safeCount(row.promoted)) return unavailable
  const outer = row.details?.rainfall_observed_report
  if (exactKeys(outer, ["status", "reason", "nominated", "queued"]) && outer.status === "held"
      && typeof outer.reason === "string" && Object.hasOwn(RAINFALL_SETTINGS_HOLDS, outer.reason)
      && outer.nominated === 0 && outer.queued === 0) {
    return { state: "rainfall_reports_held", detail: `Saved rainfall report nomination held: ${RAINFALL_SETTINGS_HOLDS[outer.reason]}. Nomination counts were not recorded.` }
  }
  if (!exactKeys(outer, ["status", "nomination", "nominated", "queued"])) return unavailable
  const n = outer.nomination
  if (record(n) && n.schema === "rainfall-nomination-counts-v2") return rainfallGridNomination(row, outer, unavailable)
  if (!exactKeys(n, ["schema", ...RAINFALL_COUNTERS, "qualification_holds", "scope"])
      || n.schema !== "rainfall-nomination-counts-v1" || n.scope !== RAINFALL_SCOPE
      || !RAINFALL_COUNTERS.every(key => safeCount(n[key]))
      || !record(n.qualification_holds) || !safeCount(outer.nominated) || !safeCount(outer.queued)) return unavailable
  const codes = Reflect.ownKeys(n.qualification_holds)
  if (!codes.every(code => typeof code === "string" && Object.hasOwn(RAINFALL_HOLDS, code)
      && safeCount(n.qualification_holds[code]) && n.qualification_holds[code] > 0)) return unavailable
  if (n.input_rows !== row.observed
      || safeSum(RAINFALL_COUNTERS.slice(1, 8).map(key => n[key])) !== n.input_rows
      || safeSum(codes.map(code => n.qualification_holds[code])) !== n.qualification_held_rows
      || safeSum([n.nominated_events, n.nomination_cap_excluded]) !== n.qualified_events
      || n.nominated_events !== Math.min(3, n.qualified_events)
      || (n.duplicate_qualified_rows > 0 && n.qualified_events === 0)
      || outer.nominated !== n.nominated_events || outer.queued > outer.nominated || outer.queued > row.promoted
      || outer.status !== (outer.nominated > 0 ? "nominated" : "no_qualified_report")) return unavailable
  const reasons = [
    ["untyped input rows", n.untyped_rows], ["rows without a usable identity", n.identity_unavailable_rows],
    ["rows with conflicting identities", n.identity_conflict_rows],
    ...codes.sort().map(code => [RAINFALL_HOLDS[code], n.qualification_holds[code]]),
    ["held by retained draft/publication history", n.history_held_rows],
    ["duplicate qualified rows", n.duplicate_qualified_rows], ["excluded by the nomination cap", n.nomination_cap_excluded],
  ].filter(([, value]) => value > 0).map(([label, value]) => `${label}: ${value}`)
  return { state: "rainfall_nominations", detail:
    `Saved rainfall report nominations: ${n.input_rows} input rows; ${n.qualified_events} qualified events; ${outer.nominated} nominated; ${outer.queued} queued.`
    + (reasons.length ? ` Dispositions: ${reasons.join("; ")}.` : "")
    + " Retained decisions, not coverage, source truth, drafts or posts." }
}

export function sourceOutcome(row, rejections = [], { rainfallNominationCurrent = true, ghcnIntakeContext = null, fireReportCurrent = false } = {}) {
  if (!row || typeof row !== "object") return outcome("unknown", row)
  if (row.source === "twitter_metrics") return twitterMetricsOutcome(row)
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
  if (incident?.product_state === "access_hold"
      && incident.failing.some(item => item.outcome === "access_refused" || item.outcome === "access_backoff")) {
    return outcome("access_refused", row, named)
  }
  if (incident?.product_state === "unavailable" && incident.failing.some(item => item.outcome === "endpoint_missing")) {
    return outcome("endpoint_missing", row, named)
  }
  if (incident?.product_state === "reachable_unqualified") return outcome("reachable_unqualified", row, named)
  const regional = details.regional_observed?.regions
  const held = regional && typeof regional === "object"
    ? Object.entries(regional).filter(([, r]) => r?.status !== "processed").map(([id, r]) => `${id}: ${text(r?.text) || text(r?.hold)}`)
    : []
  if (held.length && !((count(row.promoted) ?? 0) > 0)) return outcome("regional_hold", row, held.join("; "))
  if (row.status === "failed") {
    const acquisition = ghcnIntake(row, ghcnIntakeContext)?.acquisitionDetail
    return outcome("unavailable", row, [named, acquisition].filter(Boolean).join(" ") || null)
  }
  // Only the collector's exact zero-work marker explains this policy exclusion.
  // Keep explicit access/incident failures above it; old copy rejections below
  // do not turn this current no-work policy skip into a new check attempt.
  if (row.source === "air_quality" && row.status === "skipped" && row.error_class === "editorial_scope"
      && row.note === "Forecast AQ acquisition skipped in observed-only scheduled mode"
      && (row.error == null || row.error === "")
      && ["observed", "promoted", "triaged_in", "triaged_out", "writer_attempted", "drafted"].every(key => row[key] === 0)) {
    return outcome("policy_excluded", row)
  }
  const rainfall = rainfallNomination(row, rainfallNominationCurrent)
  // A scan explanation cannot borrow currency from a mismatched source interval
  // or bypass the strict city/grid nomination denominators above.
  const gridHold = rainfall?.state === "rainfall_nominations" ? rainfallGridHold(row) : null
  const intake = ghcnIntake(row, ghcnIntakeContext)
  const fire = fireReportStatus(row, fireReportCurrent)
  const admission = [nwsAdmissionDetail(row) ?? rainfall?.detail, gridHold, intake?.detail, fire?.detail].filter(Boolean).join(" ") || null
  if (rejections.some(r => r?.source === row.source && ["writer", "safety", "fact_check", "critic", "honesty_gate", "copy_gate"].includes(r?.stage))) {
    return outcome("writer_or_check_rejection", row, admission)
  }
  if (fire?.state === "fire_reports_unavailable") return outcome(fire.state, row, fire.detail)
  if ((count(row.promoted) ?? 0) > 0) {
    const drafted = Number.isSafeInteger(row.drafted) && row.drafted >= 0 ? row.drafted : null
    const action = drafted === null
      ? "Check whether these candidates reached writing and review; the saved-draft count was not recorded."
      : drafted === 0
      ? "Candidates were collected, but this run recorded no saved draft. Check selection and check results."
      : "Check the saved drafts from this run; they may need fresh review."
    return outcome("supplying", row, admission, action)
  }
  if (gridHold) {
    const alternate = incident?.product_state === "alternate_served"
      ? " City data was served by an alternate leg; primary recovery is unverified." : ""
    return outcome("rainfall_grid_held", row, admission + alternate)
  }
  if (incident?.product_state === "alternate_served") return outcome("alternate_served", row, named)
  if (rainfall) return outcome(rainfall.state, row, rainfall.detail)
  if (intake?.state) return outcome(intake.state, row, admission)
  if (fire) return outcome(fire.state, row, fire.detail)
  if (["success", "degraded", "partial_failure"].includes(row.status)) return outcome("no_event", row, admission)
  return outcome("unknown", row)
}

function outcome(state, row, detail = null, action = null) {
  const [label, next_action] = OUTCOMES[state]
  return { state, label, next_action: action ?? next_action, detail, source: row?.source ?? null, status: row?.status ?? null }
}

// Coverage denominators exactly as retained; sampled sources are never "global recall".
export function coverageRow(row) {
  const metrics = row?.source === "twitter_metrics" ? twitterMetricsOutcome(row) : null
  const lookup = ["metrics_returned", "metrics_partial"].includes(metrics?.state)
  const details = row?.details && typeof row.details === "object" ? row.details : {}
  const aq = details.aq_availability && typeof details.aq_availability === "object" ? details.aq_availability : null
  const regions = details.regional_observed?.regions && typeof details.regional_observed.regions === "object"
    ? Object.values(details.regional_observed.regions).filter(r => r?.status === "processed") : null
  const sum = key => regions.reduce((total, r) => total === null || count(r?.[key]) === null ? null : total + r[key], 0)
  const universe = metrics
    ? { checked: lookup ? row.observed : null, usable: lookup ? row.promoted : null, label: "requested X post metrics" }
    : regions?.length
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
    universe, scope: metrics
      ? "Retained post-metrics polling only; not weather observations, story candidates or event recall."
      : "Checked sample only; not global recall and not a count of posts.",
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
