# Copy-Paste Prompt for Starting the Next Session

Paste this verbatim into a new chat with a clean context window.

Last refresh: 2026-05-07 — after GHCN-Daily migration shipped (PRs #30 → #31 → #32 → #33 → #35 → #36) and the brand identity layer locked at R3 v4. Refresh again whenever the architecture or current focus changes meaningfully.

---

## PROMPT TO PASTE

```
New session on @theheat. Get up to speed fast — read in this order:

1. BRIEFING.md  (project overview, current cost, posting status)
2. CHANGELOG.md (read the [0.3.0.0] and [0.2.0.0] entries — the
                  May 2026 changes are the architecture you need
                  to understand: GHCN-Daily migration on the data
                  side, two-bot pipeline on the writing side)
3. PIPELINE.md  (mermaid diagram — slightly stale on the writer
                  stage, accurate on the data sources)

Repo: github.com/andrewzp/theheat
Cwd:  /Users/andrewpuschel/Documents/Claude/theheat
State backend: GitHub Gist (GIST_ID env var; dashboard reads via /api/state)
Dashboard:    Vercel-deployed Next.js. Local dev on :3030.
Threshold DB: GitHub Release asset `thresholds-latest`
              (913 MB SQLite, 11,907 active stations, 9.28M threshold rows).
              CI downloads it on every alert run; local dev expects it
              at theheat/data/station_thresholds.sqlite.

CURRENT ARCHITECTURE (post-2026-05-07, post PRs #30–#36):

  Cron (GH Actions) → src/main.py run_alerts/run_leaderboard
       │
       ├── Extreme-signals lane (THEHEAT_SIGNALS_PROVIDER=ghcn):
       │   src/data/ghcn.py → check_extreme_signals_for_stations()
       │       ├── Loads 11,907 active stations from SQLite
       │       │   (downloaded as a GH Release asset at job start;
       │       │   sanity-checked for active>=1000 + thresholds>=1000
       │       │   before the bot is allowed to run).
       │       ├── Fetches superghcnd_diff tarballs for last 3 days
       │       │   in parallel (ThreadPoolExecutor). Each tarball has
       │       │   insert.csv, update.csv, delete.csv.
       │       ├── Drops late-arriving backfill (obs_date older than
       │       │   today − MAX_OBS_AGE_DAYS, default 4). Without this
       │       │   filter the bot reports week-old weather as today's.
       │       ├── Detects all-time / monthly / calendar-date /
       │       │   anomaly signals per station against precomputed
       │       │   thresholds. MIN_ARCHIVE_YEARS=15 guard.
       │       └── Dedups to top-2 per country by score.
       │   Returns (bundles, country_records, optional metrics_out
       │   funnel for dashboard drill-down).
       │
       ├── Hot 10 leaderboard (always Open-Meteo, untouched by the
       │   GHCN migration). Polls 638 curated cities for daily
       │   anomaly ranking.
       │
       ├── Other lanes (FIRMS, NIFC, NOAA GML, NWS, GDACS, NSIDC,
       │   GRACE-FO, drought, ENSO, ocean waves, water levels, river
       │   gauges, sea ice). Unchanged by this migration.
       │
       ├── Editorial scoring (src/editorial/) decides which signals
       │   pass the threshold. Most signals die here for not being
       │   extraordinary enough.
       │
       └── Two-bot pipeline (src/two_bot/, unchanged from PR #25):
              ├── intern.py        — pure Python; 22 build_*_bundle.
              │                       _resolve_when helper threads
              │                       signal_date through the GHCN
              │                       path so the writer's "when" is
              │                       the actual obs date (24-48 hr
              │                       lag), not date.today().
              ├── writer.py        — Claude Sonnet 4.6 (env override:
              │                       THEHEAT_WRITER_MODEL).
              ├── claim_extractor  — Gemini 2.5 Flash.
              ├── fact_check.py    — Gemini 2.5 Flash.
              └── memory.py        — pure Python; record_streaks
                                      keyed by station_id on GHCN
                                      path, city name on Open-Meteo.

INVARIANTS — do not break these without explicit user permission:
- Cheap model (Gemini Flash) NEVER writes audience-facing prose.
- THEHEAT_WRITER_MODEL is Sonnet (or higher). Editorial judgment
  lives there; the cheap stages do tactical structured-output work.
- Voice generator (src/voice/generator.py) is NOT reached on any
  live signal path. Don't add new call sites.
- Don't pin to *-latest aliases for any model — they silently roll
  to preview tiers.
- Don't reintroduce human-in-the-loop editorial. Set-and-forget is
  the invariant.
- Don't push to main without confirming. Default to opening a PR.
- THEHEAT_SIGNALS_PROVIDER stays at "ghcn" in production. Rollback
  to "open_meteo" is one env-var flip in bot.yml — don't switch
  back without a reason.
- Hot 10 leaderboard stays on Open-Meteo. Don't migrate it.
- Brand identity (R3 v4 — thermometer-bulb mark + Inter SemiBold
  wordmark + paper/ink palette + single accent #C2410C on headline
  numbers) is LOCKED. Don't iterate on the visual system. The
  canonical handoff is at brand/handoff/.

CURRENT STATE (May 7, 2026):
- Tests: 709 passing.
- Production cost: ~$13/mo Sonnet writer + <$2/mo Gemini Flash
  cheap stages. GHCN-Daily is free, no auth, no rate limit.
- Posting still paused (since 2026-04-26) until quality clears the
  bar. Two-bot writing + 19× station-coverage expansion is the
  combined bet that closes the gap.
- Twitter profile NOT yet updated with the new brand assets. Avatar
  is at brand/handoff/png/avatar-400.png; banner at
  brand/handoff/png/banner-light-1500x500.png. User will upload
  manually when ready.

OPEN FOLLOW-UPS (in priority order):

1. Watch first ~10 alert cycles on the new pipeline. Look for:
   - Lag framing reads cleanly ("on May 4," not "today")
   - At least one previously-missed event class fires (high-latitude
     cold record, mountain-station record, polar station, etc.)
   - data_source_failures["ghcn"] stays at 0 in dashboard
   - Pipeline funnel in the dashboard drill-down shows stations_active
     ≈ 11,907, stations_with_obs in the thousands, raw_signals firing,
     and the editorial gate filtering most out

2. Run a manual workflow_dispatch alerts cycle if no scheduled run
   has happened in 24h: `gh workflow run bot.yml --repo
   andrewzp/theheat --ref main -f mode=alerts`. Note that requires
   user consent (it's a production deploy action — the sandbox blocks
   it without explicit approval).

3. The brand assets need to actually be uploaded to Twitter:
   - Profile picture: brand/handoff/png/avatar-400.png
   - Header banner: brand/handoff/png/banner-light-1500x500.png
   - Bio + pinned tweet: copy in brand/handoff/Brand Book.html

4. Disable Sonnet evaluator pass (still pending from the previous
   release): `EVALUATOR_ENABLED=false` in .github/workflows/bot.yml
   env block. Saves $25-45/mo. Redundant with fact_check.py.

5. Delete src/voice/generator.py (1,730 lines, no live call sites).

6. Hybrid feeds for Japan / Cyprus / small-island gaps. GHCN-Daily
   covers most @extremetemps records but not Tokashiki/Okinawa or
   Troodos/Cyprus. Closing those gaps requires JMA AMeDAS, Cyprus
   DoMS, etc. Separate PR if/when a missed station-level event
   surfaces.

7. Weekly threshold-refresh workflow (.github/workflows/refresh-
   thresholds.yml) runs Sundays at 02:00 UTC. After it runs the
   first time, verify the asset got re-uploaded and the new station
   count is reasonable.

PINNED CONTEXT YOU SHOULD KNOW:
- The user is unemployed; cost matters. Default to cheaper paths.
- Claude Max 20x covers all CC sessions but NOT production API
  spend. Production billed separately.
- Auto mode pattern: when the user says "do it" or shows clear
  intent, execute and course-correct mid-flight. Don't ask
  permission for low-risk changes; do them.
- Verify subagent file claims with ls/find/grep before relaying.
  Spot-check what an agent says it built.
- A stale worktree at /private/tmp/theheat-main-auth-fix.* sometimes
  holds the local main branch. PRs merge fine on GitHub; local
  checkout may need `git worktree prune` if it acts up.
- Brand was painful: 4 rounds of designer work + my overcorrections
  ("visceral fever," melting wordmarks, station-pin, then back to
  thermometer). Don't reopen the visual identity unless something
  is genuinely broken. Lock is real.

FIRST MOVE — pick whichever the user asks for, or default to:
  Pull the production state via the dashboard
  (curl http://localhost:3030/api/state if dashboard is running, or
  via Gist API directly). Inspect the latest run's source telemetry —
  click "▶ details" on the open_meteo_extreme_signals row to see the
  GHCN pipeline funnel + per-bundle event log. Look for the failure
  modes in OPEN FOLLOW-UPS #1.

Be brief. Show diffs before committing. Test before pushing.
```

---

## What's NOT in this prompt (intentionally)

- Old voice-engine v1/v2/v3 history. CHANGELOG keeps it for archaeology.
- Pre-port architecture details. Read CHANGELOG [0.2.0.0] only if
  you need to understand a pre-port decision.
- The brand iteration history (R1/R2/R3 v1/v2/v3 → R3 v4 lock).
  The lock is what matters; the path here is interesting only if
  someone wants to understand why "fever" / "station-pin" / "horizon-
  rule" decisions were retired.
- Specific commit SHAs older than May 2026. `git log` covers it.
- The old `docs/SESSION_BRIEF.md` archive of pre-port sessions.

## When to refresh this prompt

Replace this file whenever:
- A major architectural change lands (GHCN migration, two-bot port).
- An invariant from the "do not break these" list flips.
- A new env var or model becomes load-bearing.
- A high-priority follow-up ships and gets superseded.

The goal: a fresh chat reading just BRIEFING + CHANGELOG + this
prompt should be productive within 5 minutes.
