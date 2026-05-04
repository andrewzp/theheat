# Copy-Paste Prompt for Starting the Next Session

Paste this verbatim into a new chat with a clean context window.

Last refresh: 2026-05-04 — after PRs #21, #22, #23, #25 landed (full
voice→two-bot port). Refresh again whenever the architecture or
current focus changes meaningfully.

---

## PROMPT TO PASTE

```
New session on @theheat. Get up to speed fast — read in this order:

1. BRIEFING.md  (project overview, current cost, posting status)
2. CHANGELOG.md (start at the top; everything from May 2026 is the
                 architectural change you need to understand)
3. PIPELINE.md  (mermaid flowchart — slightly stale on the writer
                 stage, but the data-source side and editorial gate
                 are still accurate)

Repo: github.com/andrewzp/theheat
Cwd:  /Users/andrewpuschel/Documents/Claude/theheat
State backend: GitHub Gist (GIST_ID env var, prod uses gist;
              dashboard reads via /api/state)
Dashboard:    Vercel-deployed Next.js. Local dev on :3030.

CURRENT ARCHITECTURE (post-2026-05-04, post PR #25):

  Cron (GH Actions) → src/main.py run_alerts/run_leaderboard
       │
       ├── 14 free public data sources (FIRMS, Open-Meteo, NIFC,
       │   NOAA, NSIDC, GRACE-FO, GDACS, USGS, etc.)
       │
       ├── Editorial scoring (src/editorial/) decides which signals
       │   pass the threshold. This is where most signals are killed
       │   for not being extraordinary enough.
       │
       └── Two-bot pipeline (src/two_bot/):
              ├── intern.py        — pure Python: builds StoryBundle
              │                       from raw dataclass. 22 builders,
              │                       one per signal type. Source of
              │                       truth for what the writer sees.
              ├── writer.py        — Claude Sonnet 4.6 (env override:
              │                       THEHEAT_WRITER_MODEL). Drafts
              │                       the tweet OR kills the draft
              │                       with kill_reason.
              ├── claim_extractor  — Gemini 2.5 Flash (env override:
              │                       THEHEAT_CHEAP_MODEL or
              │                       THEHEAT_CLAIM_EXTRACT_MODEL).
              │                       Extracts factual claims from
              │                       writer's tweet as JSON.
              ├── fact_check.py    — Gemini 2.5 Flash. Verifies each
              │                       claim against the bundle's
              │                       headline_metric / current_facts /
              │                       historical_context.
              └── memory.py        — Pure Python. Writes used_framings,
                                      used_era_anchors, used_peer_
                                      comparisons, shipped_tweet_texts,
                                      recent_tweets_same_event so the
                                      writer doesn't repeat itself.

INVARIANTS — do not break these without explicit user permission:
- The cheap model (Gemini Flash / any model in THEHEAT_CHEAP_MODEL)
  NEVER writes audience-facing prose. Only structured-output stages.
- THEHEAT_WRITER_MODEL is Sonnet (or higher). It has the editorial
  judgment; the cheap stages do tactical work.
- Voice generator (src/voice/generator.py) is NOT reached on any
  live signal path. Don't add new call sites.
- Don't pin to `*-latest` aliases for any model — they silently roll
  to preview tiers. Both CHEAP_MODEL and WRITER_MODEL defaults are
  explicit version snapshots.
- Don't reintroduce human-in-the-loop editorial. Set-and-forget is
  the invariant. Auto-approval policies live in src/editorial/.
- Don't push to main without confirming the change is what was
  wanted. Default to opening a PR.

CURRENT STATE (May 4, 2026):
- Tests: 637 passing
- Production cost: ~$13/mo Sonnet writer + <$2/mo Gemini Flash
  (cheap stages) + ~$25-45/mo Sonnet evaluator pass (REDUNDANT,
  candidate for deletion).
- Posting still paused (since 2026-04-26) until quality clears the
  bar. The port to Sonnet-only writing is the bet that closes the
  gap. Watch the next few cycles in the dashboard.

OPEN FOLLOW-UPS (in priority order):
1. Watch first ~10 alerts cycles on the new architecture. Look for:
   - Geographic orientation present on non-iconic cities ("Riga,
     Latvia", not bare "Riga")
   - Trivial signals being killed by the writer with a kill_reason
     instead of shipping ("not extraordinary" / "no historical
     context available")
   - No near-identical drafts in the same NWS/GDACS event series
     (recent_tweets_same_event window should suppress this)

2. Disable Sonnet evaluator pass:
   `EVALUATOR_ENABLED=false` in .github/workflows/bot.yml env block.
   Saves $25-45/mo. Redundant with fact_check.py — only safe to do
   AFTER step 1 confirms the new path is working.

3. Delete src/voice/generator.py (1,730 lines, no live call sites).
   Includes downstream removal of unused templates and tests.
   Cleanup PR; no behavior change.

4. Category-tune writer_prompt.py addenda for the ~16 newly-ported
   signal types (ice_mass_record, marine_heatwave, river_flood,
   storm_surge, extreme_wave, sea_ice_record, global_disaster,
   record_streak, simultaneous_records, drought, enso, co2_milestone,
   synthesis, hot10, anomaly_*, all_time_*). Look at first production
   drafts in the dashboard to find which categories need help.

PINNED CONTEXT YOU SHOULD KNOW:
- The user is unemployed; cost matters. They explicitly said
  "we're not rich." Default to cheaper paths when unambiguous.
- Claude Max 20x covers all CC sessions but NOT production API
  spend. Production costs are billed separately to Anthropic +
  Google API keys.
- The user prefers action over explanation. Don't ask permission
  for low-risk changes; do them.
- "Auto mode" pattern: when the user says "do it" or shows clear
  intent, execute and course-correct mid-flight rather than
  planning + asking.
- A stale worktree at /private/tmp/theheat-main-auth-fix.1xmlvi
  holds the local `main` branch and blocks `gh pr merge` from
  doing the local checkout. PRs still merge on GitHub via the API
  fine — just can't sync local main automatically. Don't `git
  worktree remove` it without checking that user's WIP first.

FIRST MOVE — pick whichever the user asks for, or default to:
  Pull the production state via the dashboard (curl
  http://localhost:3030/api/state if dashboard is running, or via
  Gist API directly). Inspect any drafts in the queue. Look for
  the failure modes in OPEN FOLLOW-UPS #1.

Be brief. Show diffs before committing. Test before pushing.
```

---

## What's NOT in this prompt (intentionally)

- Old voice-engine v1/v2/v3 history. Pre-port architecture is no
  longer relevant. CHANGELOG keeps the old entries for archaeology.
- Specific commit SHAs older than May 2026 PRs. Future-me can `git log`.
- The dozens of older `docs/SESSION_BRIEF.md` / `docs/NEXT_SESSION.md`
  entries. Those describe the world before the port — read only if
  you need to understand a pre-port decision.
- The 35-draft Apr 24 corpus grading saga. Closed; the port supersedes.

## When to refresh this prompt

Replace this file whenever:
- A major architectural change lands (like the May 2026 port).
- An invariant from the "do not break these" list flips.
- A new env var or model becomes load-bearing.
- A follow-up from the priority list ships and gets superseded.

The goal is: a fresh chat reading just BRIEFING + CHANGELOG + this
prompt should be productive within 5 minutes. If it's not, this
prompt is stale.
