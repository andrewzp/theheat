# Resume @theheat — fresh session prompt (written 2026-05-08, ~11 PM PT)

**Paste this into a new Claude Code session in the `theheat` repo when you're ready to pick back up.** It's self-contained — no prior conversation needed.

---

## What this project is

@theheat is an automated climate data bot for X (@theheat). It monitors 14 free public data sources, scores extreme signals editorially, generates a tweet via a two-bot pipeline (Sonnet 4.6 writer → Gemini Flash fact-checker), and queues the result for human review on a dashboard. **Posting has been paused since 2026-04-26** until the corpus reaches "majority A-grade per cycle." This isn't an outage — it's a deliberate quality bar.

**Core principle:** astounding data + clean presentation. The DATA is the product.

## Where things stand at session start

- **Repo:** `~/Documents/Claude/theheat` (github.com/andrewzp/theheat). Always `cd` into it before running `git`/`gh`/`pytest` — git fails at the parent.
- **Branch:** `main`. Latest commit at session end: **`d9c84ff`** (PR #47 codex review high-severity batch).
- **Tests:** ~813 passing. Run with `source .venv/bin/activate && python -m pytest -x -q` (~5 min).
- **State backend:** GitHub Gist. Pull with `gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/heat_state.json`.
- **Dashboard:** https://dashboard-phi-beryl-65.vercel.app (auth-protected). Local dev usually on `:3001` via the preview tools, sometimes `:3030`.
- **Pipeline status:** ✅ working end-to-end as of 2026-05-08 23:00 PT. Was broken for 4 days (2026-05-03 → 2026-05-08) due to a Gemini SDK ms-vs-s timeout bug.
- **Drafts in queue:** 2 pending (Sissonville WV + Dayton WY monthly_lows).
- **Posting:** still paused.

## Read these in order

1. **`BRIEFING.md`** — top-level project briefing. Updated 2026-05-08. Status section + architecture + voice rules + state schema + known issues. **Start here.**
2. **`docs/SESSION_BRIEF.md`** — top entry (2026-05-08) is the 13-hour debugging marathon. Reads like a thriller; it'll tell you exactly which bugs were fixed and why each layer surfaced.
3. **`CHANGELOG.md`** — 11 releases on 2026-05-08 alone (0.3.0.0 through 0.3.10.0). Each entry is the "what + why" for one PR.
4. **`PIPELINE.md`** — mermaid diagram (updated 2026-05-08). Now shows the suppression ledger as a state-write target at every kill stage.
5. **`docs/codex-review-findings-2026-05-08.md`** — Codex's review of today's batch. 3 highs (already fixed in #47), 6 mediums, 2 lows. The mediums + lows are still open.

## What was shipped 2026-05-08 (compressed timeline)

Ten PRs landed in a 13-hour debugging marathon. Each fixed the bug surfaced by the previous PR's diagnostic improvements. The actual root cause was found at PR #43:

- **#38** Suppression ledger v1 + dashboard health-calc fix (`success` + `skipped` count as healthy)
- **#39** `signal_date` (date object) was choking `json.dumps()` in writer/fact-check via the bundle's `raw_signal_dump`. Fixed via `_json_default` ISO coercion. Plus downstream suppression capture (`stage` field discriminator).
- **#40** Sonnet wraps JSON in ```` ```json ```` fences despite the prompt forbidding them. `_strip_markdown_fences` handles it.
- **#41** Sonnet emits chain-of-thought preamble ("Let me think about this carefully.") before the JSON. `_extract_json_payload` finds first `{` to last `}`. Anthropic timeout 90s → 180s.
- **#42** Codex bug-hunt sweep. Three new shared modules: `json_utils.py` (default + balanced extraction + comment/comma fallback), `retry.py` (`call_with_retries` exp-backoff), `source_status.py` (typed errors). Wired into all LLM parsers + state.py + sqlite_store + FIRMS + fire_footprint.
- **#43** **Root cause: `google-genai` `HttpOptions.timeout` is MILLISECONDS, not seconds.** Three sites passing bare `90` (= 90ms) and `180` (= 180ms) bumped to `90000` / `180000`. Every Gemini fact-check had been timing out in <300ms for 4 days.
- **#44** `normalize_station_name()` in ghcn.py — strips CoCoRaHS suffixes (`SISSONVILLE 1SW` → `Sissonville`), airport suffixes (`MIAMI INTL AP` → `Miami`), WFO prefixes (`WFO SAN JUAN` → `San Juan`).
- **#45** Bundle enrichment: `state` field on event dataclasses, `expand_us_state()` for US codes, `_format_where()` includes state, `_ghcn_observation_facts()` adds `observation_kind` (`"overnight low"` / `"afternoon high"`). **First run with this PR produced 2 pending drafts** — pipeline finally working end-to-end.
- **#46** Fahrenheit-first audience-aware temperature formatting. `_c_to_f()` integer conversion. `_audience_unit_facts()` adds `"fahrenheit_first"` for US, `"celsius_first"` elsewhere. Writer prompt's new `TEMPERATURE FORMATTING` section.
- **#47** Codex review of #38–#46 caught 3 high-severity bugs I missed: dashboard `mergeState()` was erasing Python-owned state on every save (data loss), SQLite `_METADATA_JSON_KEYS` was dropping `memory` + `data_source_failures` (state loss), claim_extractor had no Gemini timeout (unbounded hang risk). All fixed.

## Invariants — DO NOT BREAK without explicit user permission

- **Cheap model never writes audience-facing prose.** Sonnet 4.6 writes; Gemini Flash fact-checks + extracts claims.
- **Voice generator (`src/voice/generator.py`) is dead code.** Not reached on any live signal path. Slated for deletion. If you find a code change reaching it, that's a regression.
- **`THEHEAT_SIGNALS_PROVIDER=ghcn`** stays in production. Open-Meteo extreme-signals path is dormant rollback only.
- **Hot 10 leaderboard stays on Open-Meteo.** Don't migrate.
- **Brand identity is LOCKED** at R3 v4 — thermometer-bulb mark + Inter SemiBold + paper/ink + `#C2410C` accent on headline numbers. Canonical handoff at `brand/handoff/`. Don't reopen unless something is genuinely broken.
- **Posting paused** since 2026-04-26 until majority A-grade per cycle. Drafts go to dashboard for human review, NOT auto-posted.
- **Default to opening a PR.** Don't push to main without confirming. The user ran 10 PRs in one day; they explicitly authorize merges with "ship it" / "land it" type messages.
- **Always `cd /Users/andrewpuschel/Documents/Claude/theheat &&`** before any git/python/gh command. The bash session's cwd is the parent (Claude root) by default and git fails there.
- **Don't pin model IDs to `*-latest` aliases** — they silently roll to preview tiers. Use specific dated snapshots or known stable strings.
- **WebFetch live source of truth** before pinning a model ID, API version, or any "what's current?" fact. The Gemini ms-vs-s bug today proved this — a unit changed across SDK versions and the value didn't.

## Open priorities (in order)

### A. Verify the pipeline is still healthy (5 min)

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/heat_state.json
jq '{
  drafts_pending_count: (.drafts | map(select(.status == "pending")) | length),
  latest_run: (.run_history | sort_by(.started_at) | last | {id, drafted_count, ended_at, failure_count}),
  recent_pipeline_kills: ((.suppressions // []) | map(select(.stage == "pipeline_error")) | sort_by(.ts) | .[-3:] | map({ts, reasons, summary})),
  recent_score_gate: ((.suppressions // []) | map(select(.stage == "score_gate")) | sort_by(.ts) | .[-3:] | map({ts, category, reasons}))
}' /tmp/heat_state.json
```

Expected: 2+ pending drafts (or more if new signals fired overnight). 0 new `pipeline_error` records since `2026-05-08T05:30:00Z`. If `pipeline_error` records are appearing, read the kill_reason — that's the new bug.

### B. Decide on the 2 pending drafts

Both pre-date #46 so they're stuck in `°C`-only format. Per yesterday's grading:
- **Sissonville WV** (B-grade) — voice good, signal borderline. Approve, edit, or reject.
- **Dayton WY** (C+) — flat voice, no hook. Recommend reject.

Pull the full text:
```bash
jq '.drafts | map(select(.status == "pending")) | map({event_id, score: .score.total, text})' /tmp/heat_state.json
```

### C. Address the Codex review medium/low findings

`docs/codex-review-findings-2026-05-08.md` — 6 mediums, 2 lows. In rough priority order:

1. **Suppression `stage` UI rendering** (medium / certain) — the `stage` field discriminator was added to state in #42 but `dashboard/app/page.js::SuppressedView` still groups by `source` only. The card copy says "editorial gate kills" but actually covers writer / fact_check / pipeline_error / score_gate now. Render `stage` as the primary pill. ~30 min PR.
2. **GHCN observed records labeled `forecast_*_c`** (medium / likely) — same event dataclasses serve both Open-Meteo (forecast) and GHCN (observed) but the bundle's `headline_metric.label` says "forecast" for both. Should split into `observed_*_c` for GHCN, keep `forecast_*_c` for Open-Meteo. ~30 min PR.
3. **`observation_kind` accuracy** (medium / possible) — currently hardcoded "overnight low" / "afternoon high" but TMIN/TMAX are 24-hour extrema. Could relabel to `daily_minimum` / `24h_low` for accuracy, or add an `observation_kind_caveat` fact noting it's the daily extreme. ~20 min PR.
4. **Writer prompt tightening** for speculative claims ("flowers are already up", "the ground froze") — these are pure hallucinations the writer should be told not to add. Add an explicit bullet to HARD RULES. ~15 min PR.
5. **`loads_model_json` trailing-comma fallback isn't string-aware** (low / edge) — replace regex with a string-aware character walker. ~30 min PR.
6. **`text.title()` mangles `JFK INTL AP` → `Jfk`** (low / possible) — preserve all-caps tokens of length 2-4 OR special-case known IATA codes. ~15 min PR.

### D. If new bugs surface

The diagnostic loop is now structural. If drafts stop flowing again:

1. **Pull state, look at `bot_state.suppressions`.** Most recent records will tell you what's killing them and at which `stage`.
2. **Grep run logs for `[two_bot.retry]` and `[two_bot.pipeline]`** — these surface every retry attempt and every catch-all exception with type + message.
3. **Check the dashboard's `Suppressed` tab** — same data via UI.
4. **Iterate on the same pattern as today**: fix the surface bug, run a verification cycle (`gh workflow run bot.yml -f mode=alerts`), wait ~12 min for test + alerts jobs, check state, repeat.

### E. If the user says "ship it"

The pattern from yesterday: branch (`fix/...` or `feat/...`), commit with co-author trailer, push, open PR with title + body, squash-merge with `gh pr merge N --squash --delete-branch`, sync local main, trigger verification. The user ran 10 PRs in one day — they're comfortable with this cadence.

## Common commands

```bash
# Always start with cd
cd /Users/andrewpuschel/Documents/Claude/theheat
source .venv/bin/activate

# Tests
python -m pytest -x -q              # full suite, ~5 min
python -m pytest tests/test_ghcn.py tests/test_main.py tests/test_state.py tests/two_bot/ -q  # targeted, ~5 min

# State
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/heat_state.json

# Trigger an alerts cycle manually
gh workflow run bot.yml -f mode=alerts
gh run list --workflow=bot.yml --limit 3 --json databaseId,status,createdAt,event,headSha

# Check production dashboard health
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://dashboard-phi-beryl-65.vercel.app/

# Manual Vercel deploy (auto-deploy is broken — see Known Issues)
cd dashboard && vercel --prod --yes

# Recent PRs landed
gh pr list --state merged --limit 12 --json number,title,mergedAt
```

## Pinned context (from MEMORY)

- User is unemployed. Cost matters. Default to cheaper paths (e.g. `gemini-2.5-flash` not `gemini-flash-latest`).
- **Auto mode pattern**: when user shows clear intent ("ship it", "land it", "do it"), execute and course-correct mid-flight. Don't ask permission for low-risk work.
- **Verify subagent file claims** with `ls`/`find`/`grep` before relaying to user.
- **Don't pin** to `*-latest` aliases.
- **`Bash` cwd default is parent** — always `cd .../theheat &&` first.
- **WebFetch primary source** before quoting financials, model IDs, API versions.
- **Versioned doc filenames** — never overwrite a regenerated doc with the same name; add date or `-v2` suffix.

## Final state at handoff (2026-05-08 23:00 PT)

```
Tests:                  813 passing
PRs landed today:       10 (#38–#47)
CHANGELOG releases:     0.3.0.0 → 0.3.10.0 (eleven entries)
Pipeline status:        ✅ end-to-end working
Pending drafts:         2
Posting:                paused (resumption-bar invariant)
Last cron run:          25538897186 (commit 6a068dc, drafted_count: 0,
                        no pipeline_error since 2026-05-08T05:30Z)
Visibility loop:        suppression ledger surfaces every kill stage,
                        retry helper logs every LLM attempt, dashboard
                        Suppressed tab queries via /api/suppressions
```

The 4-day production outage is over. The diagnostic infrastructure shipped today is the durable win — the next bug surfaces in minutes, not days.

If you're picking up tomorrow morning and the 04:00Z and 08:00Z scheduled crons fired cleanly overnight, the pipeline is genuinely stable. If they didn't, the suppression ledger will tell you why before you've finished your coffee.
