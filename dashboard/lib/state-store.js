import { mergePublicationControl } from "./publication-control.js"
import { DatabaseSync } from "node:sqlite"
import { decisionRevision, draftIdentity, fingerprint } from "./draft-revisions.js"

const DEFAULT_STATE = {
  publication_control: {},
  last_hot10: { date: null, cities: [] },
  streaks: {},
  posted_events: [],
  daily_tweet_count: {},
  co2_annual_count: {},
  ch4_annual_count: {},
  ch4_last_milestone: null,
  nao_annual_count: {},
  ao_annual_count: {},
  pdo_annual_count: {},
  nao_last_phase: null,
  ao_last_phase: null,
  pdo_last_phase: null,
  ozone_hole_last_peak: {},
  ozone_hole_annual_count: {},
  pending_confirmations: [],
  drafts: [],
  run_history: [],
  errors: [],
  suppressions: [],
  memory: {
    ongoing_events: [],
    used_era_anchors: [],
    used_peer_comparisons: [],
    used_framings: [],
    shipped_tweets: [],
  },
  city_all_time_max: {},
  city_all_time_min: {},
  city_monthly_max: {},
  city_monthly_min: {},
  record_streaks: {},
  data_source_failures: {},
  source_health: {},
  publish_ledger: {},
  _state_rev: 0,
  ocean_sst_streak: {
    seeded: false,
    last_milestone_fired: null,
  },
  ice_mass_max_loss: {},
  ice_mass_last_milestone: {},
  ice_mass_last_seen: {},
  ice_annual_count: {},
  precip_daily_records: {},
  precip_recent_by_city: {},
  snow_daily_swe_gain_records: {},
  snow_recent_by_station: {},
  snow_annual_count: {},
  seasonal_snow_records: {},
  fire_complex_tiers: {},
  coral_dhw_last_tier: {},
  coral_dhw_annual_count: {},
  cyclone_tiers: {},
  cyclone_wind_history: {},
  cyclone_annual_count: {},
  flood_activation_tiers: {},
  flood_annual_count: {},
  fire_footprint_last_run: null,
  synthesis_components: {
    fires: {},
    heats: {},
    drought_snapshot: null,
  },
  synthesis_cooldown: {},
}

const SQLITE_SCHEMA = `
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posted_events (
  seq INTEGER PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS pending_confirmations (
  seq INTEGER PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE,
  detected TEXT,
  source TEXT,
  city TEXT,
  state_code TEXT,
  country TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_tweet_count (
  day TEXT PRIMARY KEY,
  count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS streaks (
  city TEXT PRIMARY KEY,
  consecutive_days INTEGER NOT NULL,
  last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL,
  event_id TEXT,
  type TEXT,
  status TEXT,
  created_at TEXT,
  approved_at TEXT,
  posted_at TEXT,
  auto_approve_at TEXT,
  approval_mode TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL,
  mode TEXT,
  status TEXT,
  started_at TEXT,
  ended_at TEXT,
  source_count INTEGER,
  failure_count INTEGER,
  drafted_count INTEGER,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_runs (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  source TEXT,
  status TEXT,
  duration_ms INTEGER,
  observed INTEGER,
  promoted INTEGER,
  drafted INTEGER,
  error TEXT,
  note TEXT,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (run_id, seq),
  FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS errors (
  seq INTEGER PRIMARY KEY,
  source TEXT,
  ts TEXT,
  msg TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppressions (
  supp_id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL,
  ts TEXT,
  source TEXT,
  run_id TEXT,
  event_id TEXT,
  category TEXT,
  score_total INTEGER,
  threshold INTEGER,
  payload_json TEXT NOT NULL
);
`

const METADATA_JSON_KEYS = [
  "publication_control",
  "co2_annual_count",
  "ch4_annual_count",
  "ch4_last_milestone",
  "nao_annual_count",
  "ao_annual_count",
  "pdo_annual_count",
  "nao_last_phase",
  "ao_last_phase",
  "pdo_last_phase",
  "ozone_hole_last_peak",
  "ozone_hole_annual_count",
  "city_all_time_max",
  "city_all_time_min",
  "city_monthly_max",
  "city_monthly_min",
  "record_streaks",
  "ocean_sst_streak",
  "ice_mass_max_loss",
  "ice_mass_last_milestone",
  "ice_mass_last_seen",
  "ice_annual_count",
  "precip_daily_records",
  "precip_recent_by_city",
  "snow_daily_swe_gain_records",
  "snow_recent_by_station",
  "snow_annual_count",
  "seasonal_snow_records",
  "fire_complex_tiers",
  "coral_dhw_last_tier",
  "coral_dhw_annual_count",
  "cyclone_tiers",
  "cyclone_wind_history",
  "cyclone_annual_count",
  "flood_activation_tiers",
  "flood_annual_count",
  "fire_footprint_last_run",
  "synthesis_components",
  "synthesis_cooldown",
  "suppressions",
  "memory",
  "data_source_failures",
  "source_health",
  "publish_ledger",
  "_state_rev",
]

const PYTHON_OWNED_METADATA_KEYS = METADATA_JSON_KEYS.filter((key) => key !== "suppressions")

function gistHeaders() {
  const headers = { Accept: "application/vnd.github.v3+json" }
  const githubToken = process.env.GITHUB_TOKEN || ""
  if (githubToken) headers.Authorization = `token ${githubToken}`
  return headers
}

function configuredDbPath() {
  return process.env.THEHEAT_DB_PATH || ""
}

function configuredStateBackend() {
  return (process.env.THEHEAT_STATE_BACKEND || "").toLowerCase()
}

function configuredGistId() {
  return process.env.GIST_ID || ""
}

function normalizeState(state) {
  return {
    ...structuredClone(DEFAULT_STATE),
    ...(state || {}),
  }
}

function configuredBackend() {
  const stateBackend = configuredStateBackend()
  if (stateBackend === "sqlite" || stateBackend === "gist") return stateBackend
  return configuredDbPath() ? "sqlite" : "gist"
}

function parseTimestamp(value) {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function mergeOrderedUnique(current = [], incoming = [], maxItems) {
  const merged = []
  const seen = new Set()
  ;[...current, ...incoming].forEach((item) => {
    if (seen.has(item)) return
    seen.add(item)
    merged.push(item)
  })
  return typeof maxItems === "number" && merged.length > maxItems
    ? merged.slice(-maxItems)
    : merged
}

function draftStatusRank(draft) {
  return {
    posted: 4,
    approved: 3,
    rejected: 2,
    pending: 1,
  }[draft?.status] || 0
}

function draftRecencyKey(draft) {
  return [
    parseTimestamp(draft?.updated_at || draft?.posted_at || draft?.approved_at || draft?.created_at),
    draftStatusRank(draft),
  ]
}

function compareTuple(a, b) {
  if (a[0] !== b[0]) return a[0] - b[0]
  return a[1] - b[1]
}

function draftAttemptProtected(draft) {
  return Boolean(draft.publish_intent_id || draft.revision_conflicts?.length || ["submitted", "unknown"].includes(draft.publish_outcome) || (
    (draft.autoship_attempted || draft.last_publish_attempt_at)
    && !["not_sent", "confirmed"].includes(draft.publish_outcome)
  ))
}

function uniqueSnapshots(rows) {
  const byFingerprint = new Map(rows.filter((row) => row && typeof row === "object" && !Array.isArray(row))
    .map((row) => [fingerprint(row), structuredClone(row)]))
  return [...byFingerprint.keys()].sort().map((key) => byFingerprint.get(key))
}

function revisionSnapshot(draft) {
  return structuredClone(Object.fromEntries(Object.entries(draft)
    .filter(([key]) => !["revision_history", "revision_conflicts"].includes(key))))
}

function mergeDraftPair(current, incoming) {
  const currentIdentity = draftIdentity(current)
  const incomingIdentity = draftIdentity(incoming)
  const recencyDelta = compareTuple(draftRecencyKey(incoming), draftRecencyKey(current))
  const decisionDelta = decisionRevision(incoming) - decisionRevision(current)
  const incomingWins = incomingIdentity.content_revision > currentIdentity.content_revision
    || (incomingIdentity.content_revision === currentIdentity.content_revision
      && (decisionDelta > 0 || (decisionDelta === 0
        && (recencyDelta > 0 || (recencyDelta === 0 && fingerprint(incomingIdentity) >= fingerprint(currentIdentity))))))
  const [winner, loser] = incomingWins ? [incoming, current] : [current, incoming]
  const out = structuredClone(winner)
  const sameIdentity = fingerprint(currentIdentity) === fingerprint(incomingIdentity)
  const histories = [...(current.revision_history || []), ...(incoming.revision_history || [])]
  if (!sameIdentity || fingerprint(current.review_binding ?? null) !== fingerprint(incoming.review_binding ?? null)
    || fingerprint(current.approval_binding ?? null) !== fingerprint(incoming.approval_binding ?? null)) {
    histories.push(revisionSnapshot(loser))
  }
  if (histories.length) out.revision_history = uniqueSnapshots(histories)
  const winningRevision = draftIdentity(winner).content_revision
  const conflicts = [current, incoming].filter((draft) => draftIdentity(draft).content_revision === winningRevision)
    .flatMap((draft) => draft.revision_conflicts || [])
  if (!sameIdentity && currentIdentity.content_revision === incomingIdentity.content_revision) {
    conflicts.push(revisionSnapshot(current), revisionSnapshot(incoming))
  }
  if (sameIdentity && decisionRevision(current) === decisionRevision(incoming)
    && fingerprint(current.approval_binding ?? null) !== fingerprint(incoming.approval_binding ?? null)) {
    conflicts.push(revisionSnapshot(current), revisionSnapshot(incoming))
  }
  if (conflicts.length) {
    out.revision_conflicts = uniqueSnapshots(conflicts)
    delete out.approval_binding
    delete out.auto_approve_at
    delete out.autoship_on_critic_pass
  }
  if (sameIdentity && loser.tweet_id) {
    for (const key of ["tweet_id", "posted_at", "last_publish_attempt_at"]) {
      if (loser[key]) out[key] = structuredClone(loser[key])
    }
    out.status = "posted"
    out.publish_outcome = "confirmed"
  } else if (!sameIdentity && (loser.tweet_id || draftAttemptProtected(loser))) {
    if (loser.tweet_id || loser.autoship_attempted || loser.last_publish_attempt_at || ["submitted", "unknown"].includes(loser.publish_outcome)) {
      out.autoship_attempted = true
      out.publish_outcome = "unknown"
      out.post_error = "Publication evidence exists for a different draft revision; reconciliation required."
      if (loser.last_publish_attempt_at) out.last_publish_attempt_at = loser.last_publish_attempt_at
    }
  } else if (sameIdentity && draftAttemptProtected(loser)) {
    const sameAttempt = loser.last_publish_attempt_at === out.last_publish_attempt_at
    if (!(sameAttempt && ["not_sent", "confirmed"].includes(out.publish_outcome))) {
      if (loser.autoship_attempted || loser.last_publish_attempt_at || ["submitted", "unknown"].includes(loser.publish_outcome)) {
        out.autoship_attempted = true
        out.publish_outcome = "unknown"
        if (loser.last_publish_attempt_at) out.last_publish_attempt_at = loser.last_publish_attempt_at
      }
    }
  }
  return out
}

function attemptRows(row) {
  if (!row || typeof row !== "object" || Array.isArray(row)) return []
  return [Object.fromEntries(Object.entries(row).filter(([key]) => key !== "attempt_conflicts")),
    ...(row.attempt_conflicts || []).filter((child) => child && typeof child === "object" && !Array.isArray(child))]
}

function attemptRank(row) {
  return row.tweet_id ? 4 : ({ confirmed: 4, not_sent: 3, unknown: 2, submitted: 1 }[row.phase] || 0)
}

export function mergePublishLedger(base = {}, next = {}) {
  const merged = {}
  for (const eventId of [...new Set([...Object.keys(base || {}), ...Object.keys(next || {})])].sort()) {
    const attempts = new Map()
    for (const row of [...attemptRows(base?.[eventId]), ...attemptRows(next?.[eventId])]) {
      const identity = Object.fromEntries(["intent_id", "at", "content_revision", "text_sha256", "evidence_sha256", "text"]
        .map((key) => [key, row[key] ?? null]))
      const key = fingerprint(identity)
      const existing = attempts.get(key)
      if (!existing) attempts.set(key, structuredClone(row))
      else if (existing.tweet_id && row.tweet_id && existing.tweet_id !== row.tweet_id) {
        attempts.set(fingerprint(row), structuredClone(row))
      } else {
        const [winner, loser] = attemptRank(row) >= attemptRank(existing) ? [row, existing] : [existing, row]
        attempts.set(key, structuredClone({ ...loser, ...winner }))
      }
    }
    const rows = [...attempts.values()].sort((a, b) => Number(Boolean(a.tweet_id)) - Number(Boolean(b.tweet_id))
      || parseTimestamp(a.at) - parseTimestamp(b.at) || attemptRank(a) - attemptRank(b)
      || (fingerprint(a) < fingerprint(b) ? -1 : fingerprint(a) > fingerprint(b) ? 1 : 0))
    const primary = rows.pop()
    if (!primary) continue
    if (rows.length) primary.attempt_conflicts = uniqueSnapshots(rows)
    merged[eventId] = primary
  }
  return merged
}

export function mergeDrafts(current = [], incoming = [], maxItems = 200) {
  const merged = new Map()
  const anonymous = []

  ;[...current, ...incoming].forEach((draft) => {
    const copy = structuredClone(draft)
    if (!copy.id) {
      anonymous.push(copy)
      return
    }
    const existing = merged.get(copy.id)
    merged.set(copy.id, existing ? mergeDraftPair(existing, copy) : copy)
  })

  const ordered = [...merged.values(), ...anonymous].sort((a, b) => {
    const createdDelta = parseTimestamp(a.created_at || a.updated_at) - parseTimestamp(b.created_at || b.updated_at)
    if (createdDelta !== 0) return createdDelta
    return parseTimestamp(a.updated_at || a.created_at) - parseTimestamp(b.updated_at || b.created_at)
  })

  if (ordered.length <= maxItems) return ordered
  const protectedDrafts = ordered.filter(draftAttemptProtected)
  const candidates = ordered.filter((draft) => !draftAttemptProtected(draft))
  const slots = Math.max(0, maxItems - protectedDrafts.length)
  const kept = new Set([...protectedDrafts, ...(slots ? candidates.slice(-slots) : [])])
  return ordered.filter((draft) => kept.has(draft))
}

function mergeRunHistory(current = [], incoming = [], maxItems = 20) {
  const merged = new Map()
  const anonymous = []

  ;[...current, ...incoming].forEach((run) => {
    const copy = structuredClone(run)
    if (!copy.id) {
      anonymous.push(copy)
      return
    }
    const existing = merged.get(copy.id)
    if (!existing) {
      merged.set(copy.id, copy)
      return
    }
    const existingKey = [
      parseTimestamp(existing.ended_at || existing.started_at),
      existing.sources?.length || 0,
    ]
    const candidateKey = [
      parseTimestamp(copy.ended_at || copy.started_at),
      copy.sources?.length || 0,
    ]
    if (compareTuple(candidateKey, existingKey) >= 0) {
      merged.set(copy.id, copy)
    }
  })

  return [...merged.values(), ...anonymous]
    .sort((a, b) => parseTimestamp(b.started_at || b.ended_at) - parseTimestamp(a.started_at || a.ended_at))
    .slice(0, maxItems)
}

function mergeErrors(current = [], incoming = [], maxItems = 50) {
  const merged = []
  const seen = new Set()
  ;[...current, ...incoming].forEach((error) => {
    const key = `${error?.source || ""}|${error?.ts || ""}|${error?.msg || ""}`
    if (seen.has(key)) return
    seen.add(key)
    merged.push(structuredClone(error))
  })
  merged.sort((a, b) => parseTimestamp(a.ts) - parseTimestamp(b.ts))
  return merged.slice(-maxItems)
}

function mergeSuppressions(current = [], incoming = [], maxItems = 200) {
  const merged = new Map()
  const anonymous = []
  ;[...current, ...incoming].forEach((supp) => {
    const copy = structuredClone(supp)
    if (!copy.id) {
      anonymous.push(copy)
      return
    }
    const existing = merged.get(copy.id)
    if (!existing || parseTimestamp(copy.ts) >= parseTimestamp(existing.ts)) {
      merged.set(copy.id, copy)
    }
  })
  const ordered = [...merged.values(), ...anonymous]
  ordered.sort((a, b) => parseTimestamp(a.ts) - parseTimestamp(b.ts))
  return ordered.length > maxItems ? ordered.slice(-maxItems) : ordered
}

function mergeState(current, incoming) {
  const base = normalizeState(current)
  const next = normalizeState(incoming)
  const rawIncoming = incoming || {}
  const incomingOrBase = (key, fallback) => structuredClone(
    Object.prototype.hasOwnProperty.call(rawIncoming, key)
      ? (rawIncoming[key] ?? fallback)
      : base[key]
  )
  const pythonOwnedMetadata = Object.fromEntries(
    PYTHON_OWNED_METADATA_KEYS.map((key) => [
      key,
      structuredClone(
        Object.prototype.hasOwnProperty.call(rawIncoming, key)
          ? rawIncoming[key]
          : base[key]
      ),
    ])
  )
  // Preserve Python-owned top-level state keys that the dashboard never
  // sets but must not overwrite. Without the spread, every dashboard
  // approve/reject/edit click was rewriting state.json with only this
  // dashboard-era subset, erasing memory / record_streaks /
  // data_source_failures / ocean_sst_streak / ice_mass_* /
  // fire_complex_tiers / synthesis_*. Found 2026-05-08 via codex review.
  return normalizeState({
    ...base,
    ...next,
    // Explicit merge logic for keys the dashboard does manage:
    last_hot10: incomingOrBase("last_hot10", DEFAULT_STATE.last_hot10),
    streaks: incomingOrBase("streaks", DEFAULT_STATE.streaks),
    posted_events: mergeOrderedUnique(base.posted_events, next.posted_events, 500),
    daily_tweet_count: {
      ...(base.daily_tweet_count || {}),
      ...(next.daily_tweet_count || {}),
    },
    pending_confirmations: incomingOrBase("pending_confirmations", DEFAULT_STATE.pending_confirmations),
    drafts: mergeDrafts(base.drafts, next.drafts),
    run_history: mergeRunHistory(base.run_history, next.run_history),
    errors: mergeErrors(base.errors, next.errors),
    suppressions: mergeSuppressions(base.suppressions, next.suppressions),
    ...pythonOwnedMetadata,
    publication_control: mergePublicationControl(base.publication_control, next.publication_control),
    publish_ledger: mergePublishLedger(base.publish_ledger, rawIncoming.publish_ledger),
  })
}

async function readGistState() {
  const gistId = configuredGistId()
  if (!gistId) return structuredClone(DEFAULT_STATE)
  const res = await fetch(`https://api.github.com/gists/${gistId}`, {
    headers: gistHeaders(),
    cache: "no-store",
  })
  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to read state: ${res.status} ${errorText}`)
  }
  const gist = await res.json()
  const stateFile = gist?.files?.["state.json"]
  let content = stateFile?.content
  if (stateFile?.truncated && stateFile?.raw_url) {
    const rawRes = await fetch(stateFile.raw_url, {
      headers: gistHeaders(),
      cache: "no-store",
    })
    if (!rawRes.ok) {
      const errorText = await rawRes.text()
      throw new Error(`Failed to read raw state: ${rawRes.status} ${errorText}`)
    }
    content = await rawRes.text()
  }
  if (!content) {
    throw new Error("state.json not found in Gist")
  }
  return normalizeState(JSON.parse(content))
}

async function writeGistState(state) {
  const gistId = configuredGistId()
  const res = await fetch(`https://api.github.com/gists/${gistId}`, {
    method: "PATCH",
    headers: { ...gistHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      files: { "state.json": { content: JSON.stringify(state, null, 2) } },
    }),
  })
  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to write state: ${res.status} ${errorText}`)
  }
}

function mergeDraftIntoState(state, draft) {
  const merged = mergeState(state, { drafts: [draft] })
  const index = merged.drafts.findIndex((candidate) => candidate.id === draft.id)
  const updated = structuredClone(draft)
  // This path runs only after the exact observed row and ledger are checked.
  // Honor intentional status/approval revocation even within one millisecond;
  // generic snapshot rank must not undo an authorized cancel or rollback.
  if (index >= 0) {
    if (merged.drafts[index].revision_history?.length) updated.revision_history = merged.drafts[index].revision_history
    merged.drafts[index] = updated
  } else merged.drafts.push(updated)
  return merged
}

function connectDb() {
  const db = new DatabaseSync(configuredDbPath())
  db.exec(SQLITE_SCHEMA)
  return db
}

function tableCount(db, table) {
  return db.prepare(`SELECT COUNT(*) AS count FROM ${table}`).get().count
}

function sqliteIsEmpty(db) {
  return [
    "metadata",
    "posted_events",
    "pending_confirmations",
    "daily_tweet_count",
    "streaks",
    "drafts",
    "runs",
    "errors",
    "suppressions",
  ].reduce((sum, table) => sum + tableCount(db, table), 0) === 0
}

function writeSqliteState(db, state) {
  const normalized = normalizeState(state)
  const insertPosted = db.prepare("INSERT INTO posted_events (seq, event_id) VALUES (?, ?)")
  const insertPending = db.prepare(`
    INSERT INTO pending_confirmations
    (seq, event_id, detected, source, city, state_code, country, payload_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `)
  const insertDaily = db.prepare("INSERT INTO daily_tweet_count (day, count) VALUES (?, ?)")
  const insertStreak = db.prepare("INSERT INTO streaks (city, consecutive_days, last_seen) VALUES (?, ?, ?)")
  const insertDraft = db.prepare(`
    INSERT INTO drafts
    (draft_id, seq, event_id, type, status, created_at, approved_at, posted_at, auto_approve_at, approval_mode, payload_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `)
  const insertRun = db.prepare(`
    INSERT INTO runs
    (run_id, seq, mode, status, started_at, ended_at, source_count, failure_count, drafted_count, payload_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `)
  const insertSourceRun = db.prepare(`
    INSERT INTO source_runs
    (run_id, seq, source, status, duration_ms, observed, promoted, drafted, error, note, payload_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `)
  const insertError = db.prepare("INSERT INTO errors (seq, source, ts, msg, payload_json) VALUES (?, ?, ?, ?, ?)")
  const insertSuppression = db.prepare(`
    INSERT INTO suppressions
    (supp_id, seq, ts, source, run_id, event_id, category, score_total, threshold, payload_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `)
  const insertMeta = db.prepare("INSERT INTO metadata (key, value_json) VALUES (?, ?)")

  db.exec("BEGIN")
  try {
    db.exec("DELETE FROM metadata")
    insertMeta.run("last_hot10", JSON.stringify(normalized.last_hot10 || DEFAULT_STATE.last_hot10))
    METADATA_JSON_KEYS.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(normalized, key)) {
        insertMeta.run(key, JSON.stringify(normalized[key]))
      }
    })

    db.exec("DELETE FROM posted_events")
    normalized.posted_events.forEach((eventId, index) => insertPosted.run(index, eventId))

    db.exec("DELETE FROM pending_confirmations")
    normalized.pending_confirmations.forEach((pending, index) => {
      insertPending.run(
        index,
        pending.event_id,
        pending.detected ?? null,
        pending.source ?? null,
        pending.city ?? null,
        pending.state_code ?? null,
        pending.country ?? null,
        JSON.stringify(pending)
      )
    })

    db.exec("DELETE FROM daily_tweet_count")
    Object.entries(normalized.daily_tweet_count || {}).forEach(([day, count]) => {
      insertDaily.run(day, count)
    })

    db.exec("DELETE FROM streaks")
    Object.entries(normalized.streaks || {}).forEach(([city, details]) => {
      insertStreak.run(city, details.consecutive_days ?? 0, details.last_seen ?? "")
    })

    db.exec("DELETE FROM drafts")
    normalized.drafts.forEach((draft, index) => {
      insertDraft.run(
        draft.id,
        index,
        draft.event_id ?? null,
        draft.type ?? null,
        draft.status ?? null,
        draft.created_at ?? null,
        draft.approved_at ?? null,
        draft.posted_at ?? null,
        draft.auto_approve_at ?? null,
        draft.approval_mode ?? null,
        JSON.stringify(draft)
      )
    })

    db.exec("DELETE FROM source_runs")
    db.exec("DELETE FROM runs")
    normalized.run_history.forEach((run, runIndex) => {
      insertRun.run(
        run.id,
        runIndex,
        run.mode ?? null,
        run.status ?? null,
        run.started_at ?? null,
        run.ended_at ?? null,
        run.source_count ?? (run.sources?.length || 0),
        run.failure_count ?? 0,
        run.drafted_count ?? 0,
        JSON.stringify({ ...run, sources: [] })
      )
      ;(run.sources || []).forEach((sourceRun, sourceIndex) => {
        insertSourceRun.run(
          run.id,
          sourceIndex,
          sourceRun.source ?? null,
          sourceRun.status ?? null,
          sourceRun.duration_ms ?? 0,
          sourceRun.observed ?? 0,
          sourceRun.promoted ?? 0,
          sourceRun.drafted ?? 0,
          sourceRun.error ?? null,
          sourceRun.note ?? null,
          JSON.stringify(sourceRun)
        )
      })
    })

    db.exec("DELETE FROM errors")
    normalized.errors.forEach((error, index) => {
      insertError.run(
        index,
        error.source ?? null,
        error.ts ?? null,
        error.msg ?? null,
        JSON.stringify(error)
      )
    })

    db.exec("DELETE FROM suppressions")
    normalized.suppressions.forEach((supp, index) => {
      insertSuppression.run(
        supp.id,
        index,
        supp.ts ?? null,
        supp.source ?? null,
        supp.run_id ?? null,
        supp.event_id ?? null,
        supp.category ?? null,
        Number.isFinite(supp.score_total) ? supp.score_total : null,
        Number.isFinite(supp.threshold) ? supp.threshold : null,
        JSON.stringify(supp)
      )
    })

    db.exec("COMMIT")
  } catch (error) {
    db.exec("ROLLBACK")
    throw error
  }
}

function readSqliteState(db) {
  const state = structuredClone(DEFAULT_STATE)
  const lastHot10 = db.prepare("SELECT value_json FROM metadata WHERE key = 'last_hot10'").get()
  if (lastHot10?.value_json) {
    state.last_hot10 = JSON.parse(lastHot10.value_json)
  }
  for (const key of METADATA_JSON_KEYS) {
    const row = db.prepare("SELECT value_json FROM metadata WHERE key = ?").get(key)
    if (row?.value_json) {
      state[key] = JSON.parse(row.value_json)
    }
  }

  state.posted_events = db.prepare("SELECT event_id FROM posted_events ORDER BY seq ASC").all().map((row) => row.event_id)
  state.pending_confirmations = db.prepare("SELECT payload_json FROM pending_confirmations ORDER BY seq ASC").all().map((row) => JSON.parse(row.payload_json))
  state.daily_tweet_count = Object.fromEntries(
    db.prepare("SELECT day, count FROM daily_tweet_count ORDER BY day ASC").all().map((row) => [row.day, row.count])
  )
  state.streaks = Object.fromEntries(
    db.prepare("SELECT city, consecutive_days, last_seen FROM streaks ORDER BY city ASC").all().map((row) => [
      row.city,
      { consecutive_days: row.consecutive_days, last_seen: row.last_seen },
    ])
  )
  state.drafts = db.prepare("SELECT payload_json FROM drafts ORDER BY seq ASC").all().map((row) => JSON.parse(row.payload_json))

  const runs = db.prepare("SELECT run_id, payload_json FROM runs ORDER BY seq ASC").all()
  const sourceRuns = db.prepare("SELECT run_id, payload_json FROM source_runs ORDER BY run_id ASC, seq ASC").all()
  const sourceMap = new Map()
  sourceRuns.forEach((row) => {
    const group = sourceMap.get(row.run_id) || []
    group.push(JSON.parse(row.payload_json))
    sourceMap.set(row.run_id, group)
  })
  state.run_history = runs.map((row) => {
    const payload = JSON.parse(row.payload_json)
    payload.sources = sourceMap.get(row.run_id) || payload.sources || []
    return payload
  })

  state.errors = db.prepare("SELECT payload_json FROM errors ORDER BY seq ASC").all().map((row) => JSON.parse(row.payload_json))
  const tableSuppressions = db.prepare("SELECT payload_json FROM suppressions ORDER BY seq ASC").all().map((row) => JSON.parse(row.payload_json))
  state.suppressions = mergeSuppressions(state.suppressions, tableSuppressions)
  return normalizeState(state)
}

function upsertSqliteDraft(db, draftId, draft, fallbackSeq) {
  const existing = db.prepare("SELECT seq FROM drafts WHERE draft_id = ?").get(draftId)
  const seq = existing?.seq ?? fallbackSeq
  db.prepare(`
    INSERT INTO drafts
    (draft_id, seq, event_id, type, status, created_at, approved_at, posted_at, auto_approve_at, approval_mode, payload_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(draft_id) DO UPDATE SET
      seq = excluded.seq,
      event_id = excluded.event_id,
      type = excluded.type,
      status = excluded.status,
      created_at = excluded.created_at,
      approved_at = excluded.approved_at,
      posted_at = excluded.posted_at,
      auto_approve_at = excluded.auto_approve_at,
      approval_mode = excluded.approval_mode,
      payload_json = excluded.payload_json
  `).run(
    draft.id,
    seq,
    draft.event_id ?? null,
    draft.type ?? null,
    draft.status ?? null,
    draft.created_at ?? null,
    draft.approved_at ?? null,
    draft.posted_at ?? null,
    draft.auto_approve_at ?? null,
    draft.approval_mode ?? null,
    JSON.stringify(draft)
  )
}

async function bootstrapSqliteFromGist(db) {
  if (!configuredGistId() || sqliteIsEmpty(db) === false) return
  try {
    const gistState = await readGistState()
    writeSqliteState(db, gistState)
  } catch {
    // Leave the DB empty if bootstrap fails; callers will still get defaults.
  }
}

export function getStateBackend() {
  return configuredBackend()
}

export async function readStateStore() {
  if (configuredBackend() === "sqlite") {
    const db = connectDb()
    try {
      await bootstrapSqliteFromGist(db)
      return readSqliteState(db)
    } finally {
      db.close()
    }
  }
  return readGistState()
}

export async function writeStateStore(state) {
  if (configuredBackend() === "sqlite") {
    const db = connectDb()
    try {
      await bootstrapSqliteFromGist(db)
      const merged = mergeState(readSqliteState(db), state)
      writeSqliteState(db, merged)
      return
    } finally {
      db.close()
    }
  }
  const merged = mergeState(await readGistState(), state)
  await writeGistState(merged)
}

function revisionConflict() {
  const error = new Error("This draft changed. Refresh it before applying this action.")
  error.status = 409
  error.statusCode = 409
  error.code = "revision_conflict"
  return error
}

function checkExpectedRevision(draft, expectedRevision) {
  if (expectedRevision && fingerprint({ ...draftIdentity(draft), decision_revision: decisionRevision(draft) })
    !== fingerprint({ decision_revision: 0, ...expectedRevision })) throw revisionConflict()
}

function draftMutationSnapshot(draft, state) {
  const eventId = draft.event_id || draft.id
  return fingerprint({ draft, publish_ledger: state.publish_ledger?.[eventId] ?? null })
}

export async function updateDraftStore(draftId, updater, { expectedRevision } = {}) {
  if (configuredBackend() === "sqlite") {
    const db = connectDb()
    try {
      await bootstrapSqliteFromGist(db)
      // Lock before the read so another SQLite writer cannot invalidate the
      // authorization check between loading the row and updating it.
      db.exec("BEGIN IMMEDIATE")
      try {
        const state = readSqliteState(db)
        const drafts = state.drafts || []
        const draftIndex = drafts.findIndex((draft) => draft.id === draftId)
        if (draftIndex === -1) {
          db.exec("COMMIT")
          return { state, draft: null }
        }
        const draft = structuredClone(drafts[draftIndex])
        checkExpectedRevision(draft, expectedRevision)
        const nextDraft = await updater(draft, state)
        if (!nextDraft) {
          db.exec("COMMIT")
          return { state, draft: null }
        }
        nextDraft.updated_at = new Date().toISOString()
        state.drafts[draftIndex] = nextDraft
        upsertSqliteDraft(db, draftId, nextDraft, draftIndex)
        db.exec("COMMIT")
        return { state, draft: nextDraft }
      } catch (error) {
        db.exec("ROLLBACK")
        throw error
      }
    } finally {
      db.close()
    }
  }

  const state = await readGistState()
  const drafts = state.drafts || []
  const draftIndex = drafts.findIndex((draft) => draft.id === draftId)
  if (draftIndex === -1) {
    return { state, draft: null }
  }

  const draft = structuredClone(drafts[draftIndex])
  checkExpectedRevision(draft, expectedRevision)
  const observedSnapshot = draftMutationSnapshot(draft, state)
  const nextDraft = await updater(draft, state)
  if (!nextDraft) {
    return { state, draft: null }
  }

  nextDraft.updated_at = new Date().toISOString()
  const latestState = await readGistState()
  const latestDraft = latestState.drafts?.find((candidate) => candidate.id === draftId)
  // Reject changes visible at the second read, including approval revocation or
  // a newly submitted platform attempt with an unchanged content revision.
  // Gist has no transaction here: the remaining GET-to-PATCH race is unchanged.
  if (!latestDraft || draftMutationSnapshot(latestDraft, latestState) !== observedSnapshot) throw revisionConflict()
  const mergedState = mergeDraftIntoState(latestState, nextDraft)
  await writeGistState(mergedState)
  const mergedDraft = (mergedState.drafts || []).find((candidate) => candidate.id === draftId) || nextDraft
  return { state: mergedState, draft: mergedDraft }
}
