# Lane 10 — Docs cleanup (NEXT_SESSION_PROMPT chaos)

**Branch:** `chore/docs-cleanup`
**Scope:** Consolidate the proliferating NEXT_SESSION_PROMPT_*.md files into one canonical handoff location
**Estimated time:** 30-45 minutes CC, single PR
**Parallel-safety:** **Fully parallel-safe.** Touches `docs/` only. Zero conflict with any source/orchestrator/state work. Can spawn alongside Phase 3, Lane 08, Lane 09, Lane 11 — anything.

## Why this lane exists

`docs/` currently contains 8 differently-named "next session" files. The most recent handoff (NEXT_SESSION_PROMPT_2026-05-14-v2.md) explicitly notes that its predecessor was misdated. Naming chaos is real overhead — every new session starts by sorting out which doc is current.

Current state in [/Users/andrewpuschel/Documents/Claude/theheat/docs/](/Users/andrewpuschel/Documents/Claude/theheat/docs/):

```
NEXT_SESSION.md
NEXT_SESSION_PROMPT_2026-05-09.md
NEXT_SESSION_PROMPT_2026-05-11.md
NEXT_SESSION_PROMPT_2026-05-12.md
NEXT_SESSION_PROMPT_2026-05-12-v2.md
NEXT_SESSION_PROMPT_2026-05-14.md
NEXT_SESSION_PROMPT_2026-05-14-v2.md
START_NEXT_SESSION_PROMPT.md
```

Plus other accumulated docs: BUILD_BRIEF.md, CLAUDE_DESIGN_BRIEF.md, DESIGN.md, DRAFT_CORPUS.md, FUTURE_STATE.md, IDEAS.md, IMPROVEMENT_PLAN.md, LEVEL_UP_PLAN.md, QUALITY_TREND.md, SESSION_BRIEF.md, VOICE_FAILURE_ANALYSIS.md, codex-bug-hunt-*, codex-review-*, plus subdirectories `claude-design-handoff/`, `codex-reviews/`, `conductor-lanes/`, `mockups/`, `superpowers/`.

This lane only touches the NEXT_SESSION* files. Don't audit the other docs in scope here — that's a separate cleanup.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/NEXT_SESSION_PROMPT_2026-05-14-v2.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/NEXT_SESSION_PROMPT_2026-05-14-v2.md) — the most recent handoff. This is the source of truth for the current state.
2. All other NEXT_SESSION* files — read titles + first 20 lines to confirm they are superseded by v2 of 2026-05-14.

## The cleanup

### Step 1 — Move historical handoffs into an archive directory

Create [/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/) and move:

```
NEXT_SESSION_PROMPT_2026-05-09.md     → docs/handoffs/2026-05-09.md
NEXT_SESSION_PROMPT_2026-05-11.md     → docs/handoffs/2026-05-11.md
NEXT_SESSION_PROMPT_2026-05-12.md     → docs/handoffs/2026-05-12.md
NEXT_SESSION_PROMPT_2026-05-12-v2.md  → docs/handoffs/2026-05-12-v2.md
NEXT_SESSION_PROMPT_2026-05-14.md     → docs/handoffs/2026-05-14.md
NEXT_SESSION_PROMPT_2026-05-14-v2.md  → docs/handoffs/2026-05-14-v2.md
```

Use `git mv` so history is preserved.

### Step 2 — Delete redundant pointers

- `NEXT_SESSION.md` — if it's a generic "look at the dated handoffs" pointer, delete. If it has unique content, surface it back to Andrew rather than deleting blind.
- `START_NEXT_SESSION_PROMPT.md` — same call. If superseded, delete with `git rm`.

### Step 3 — Add a README to the new handoffs directory

Create [/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/README.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/README.md):

```markdown
# Handoffs

Dated end-of-session brief documents. Each file captures the state of @theheat
at end-of-session and orients the next session.

**Most recent first:**

- [2026-05-14-v2.md](2026-05-14-v2.md) — Plan A wave landed (most recent)
- [2026-05-14.md](2026-05-14.md) — initial 2026-05-14 sweep (superseded by v2)
- [2026-05-12-v2.md](2026-05-12-v2.md) — ...
- (etc., newest-first)

## Convention going forward

- Filename format: `YYYY-MM-DD.md` (or `-v2`, `-v3` for same-day iterations)
- Always link the new file from the top of this README
- The current "next session" is whichever file sits at the top
```

### Step 4 — Update CLAUDE.md / BRIEFING.md if they reference the old paths

Search the repo for references to `NEXT_SESSION_PROMPT_*` and update any stale path references. Likely candidates: BRIEFING.md, README files, any onboarding text.

```bash
grep -rn "NEXT_SESSION_PROMPT\|START_NEXT_SESSION" --include="*.md" /Users/andrewpuschel/Documents/Claude/theheat/
```

## Constraints

- **Preserve history.** Use `git mv` not `git rm` + `git add`. Old filename history must be reachable.
- **Don't audit other docs.** Only NEXT_SESSION* files in scope here.
- **Don't lose unique content.** If `NEXT_SESSION.md` or `START_NEXT_SESSION_PROMPT.md` have unique content (not just a pointer), surface to Andrew before deleting.
- **No code changes.** This is a `docs/` only cleanup.

## Acceptance

- `ls /Users/andrewpuschel/Documents/Claude/theheat/docs/NEXT_SESSION_PROMPT_*.md` returns nothing.
- `ls /Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/` shows 6 dated handoff files + README.md.
- `git log --follow docs/handoffs/2026-05-14-v2.md` shows the original commit history (proves git mv worked).
- No broken references to old paths anywhere in the repo.

## Branch / PR sequence

1. Branch `chore/docs-cleanup` from `main`.
2. `git mv` all 6 NEXT_SESSION_PROMPT_* files into `docs/handoffs/`.
3. Add README.md.
4. Update any stale path references (grep above).
5. PR → CI green (docs-only, should be fast) → Claude merges per the standing rule.

Done. ~30-45 minutes CC end-to-end.
