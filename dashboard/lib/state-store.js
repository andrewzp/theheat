import { DatabaseSync } from "node:sqlite"

const DEFAULT_STATE = {
  last_hot10: { date: null, cities: [] },
  streaks: {},
  posted_events: [],
  daily_tweet_count: {},
  pending_confirmations: [],
  drafts: [],
  run_history: [],
  errors: [],
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
`

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

function mergeDrafts(current = [], incoming = [], maxItems = 200) {
  const merged = new Map()
  const anonymous = []

  ;[...current, ...incoming].forEach((draft) => {
    const copy = structuredClone(draft)
    if (!copy.id) {
      anonymous.push(copy)
      return
    }
    const existing = merged.get(copy.id)
    if (!existing || compareTuple(draftRecencyKey(copy), draftRecencyKey(existing)) >= 0) {
      merged.set(copy.id, copy)
    }
  })

  const ordered = [...merged.values(), ...anonymous].sort((a, b) => {
    const createdDelta = parseTimestamp(a.created_at || a.updated_at) - parseTimestamp(b.created_at || b.updated_at)
    if (createdDelta !== 0) return createdDelta
    return parseTimestamp(a.updated_at || a.created_at) - parseTimestamp(b.updated_at || b.created_at)
  })

  return ordered.length > maxItems ? ordered.slice(-maxItems) : ordered
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

function mergeState(current, incoming) {
  const base = normalizeState(current)
  const next = normalizeState(incoming)
  return normalizeState({
    last_hot10: structuredClone(next.last_hot10 || base.last_hot10),
    streaks: structuredClone(next.streaks || base.streaks),
    posted_events: mergeOrderedUnique(base.posted_events, next.posted_events, 500),
    daily_tweet_count: {
      ...(base.daily_tweet_count || {}),
      ...(next.daily_tweet_count || {}),
    },
    pending_confirmations: structuredClone(next.pending_confirmations || []),
    drafts: mergeDrafts(base.drafts, next.drafts),
    run_history: mergeRunHistory(base.run_history, next.run_history),
    errors: mergeErrors(base.errors, next.errors),
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
  const content = gist?.files?.["state.json"]?.content
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
  return mergeState(state, { drafts: [draft] })
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
  const insertMeta = db.prepare("INSERT INTO metadata (key, value_json) VALUES (?, ?)")

  db.exec("BEGIN")
  try {
    db.exec("DELETE FROM metadata")
    insertMeta.run("last_hot10", JSON.stringify(normalized.last_hot10 || DEFAULT_STATE.last_hot10))

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
  const normalized = normalizeState(state)
  if (configuredBackend() === "sqlite") {
    const db = connectDb()
    try {
      await bootstrapSqliteFromGist(db)
      const merged = mergeState(readSqliteState(db), normalized)
      writeSqliteState(db, merged)
      return
    } finally {
      db.close()
    }
  }
  const merged = mergeState(await readGistState(), normalized)
  await writeGistState(merged)
}

export async function updateDraftStore(draftId, updater) {
  if (configuredBackend() === "sqlite") {
    const db = connectDb()
    try {
      await bootstrapSqliteFromGist(db)
      const state = readSqliteState(db)
      const drafts = state.drafts || []
      const draftIndex = drafts.findIndex((draft) => draft.id === draftId)
      if (draftIndex === -1) {
        return { state, draft: null }
      }

      const draft = structuredClone(drafts[draftIndex])
      const nextDraft = await updater(draft, state)
      if (!nextDraft) {
        return { state, draft: null }
      }

      nextDraft.updated_at = new Date().toISOString()
      state.drafts[draftIndex] = nextDraft
      db.exec("BEGIN")
      try {
        upsertSqliteDraft(db, draftId, nextDraft, draftIndex)
        db.exec("COMMIT")
      } catch (error) {
        db.exec("ROLLBACK")
        throw error
      }
      return { state, draft: nextDraft }
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
  const nextDraft = await updater(draft, state)
  if (!nextDraft) {
    return { state, draft: null }
  }

  nextDraft.updated_at = new Date().toISOString()
  const latestState = await readGistState()
  const mergedState = mergeDraftIntoState(latestState, nextDraft)
  await writeGistState(mergedState)
  const mergedDraft = (mergedState.drafts || []).find((candidate) => candidate.id === draftId) || nextDraft
  return { state: mergedState, draft: mergedDraft }
}
