# Handoff — 2026-07-09 · #414 records-cluster SHIPPED; writer-voice realignment is the open thread

> Wraps the 2026-07-08 evening session (the #414 tier-aware rework) + a dashboard-auth fix.
> **`main` @ `dd4e525`, v`0.9.99.0`, tree clean.** Everything below is MERGED unless marked **OPEN**.
> Detailed #414 journey (design pivot + codex stress-test): [docs/handoffs/2026-07-08-records-cluster.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-07-08-records-cluster.md) (marked SHIPPED).

## ★ THE ONE THING TO DO NEXT — realign the `heat_records_cluster` writer voice (OPEN)

**Andrew's directive:** *the voice across the whole project must be the same.* My PR-C writer
section — `## Heat records cluster bundles` in
[src/two_bot/prompts/writer_prompt.py](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/prompts/writer_prompt.py) —
**drifted into a "scoreboard" register.** It invents a parallel "four moves take this from
scoreboard to story" framework whose four moves are all *data-handling* (which records to lead
with, tense, geography, subject), and its example enumerates records with **no house SYSTEM
CLAUSE**:

- ✗ (shipped) *"Records are falling across Iberia. Madrid and Toledo are on pace… four more…
  six others… twelve cities in a single afternoon."* — all data point, no beat-2. Run the
  file's own "delete the system clause" test and there's nothing to delete.

The house voice is defined ONCE at the top of that file (`# THE VOICE`, `# THE SIGNATURE MOVE`):
every tweet is **data point → system clause (name the larger system that makes it matter) →
stop, no wink.** Per-signal sections are meant to add only that signal's *specifics*, then ride
the one voice.

**The fix:** subordinate the section to the signature move. The system clause for a records
CLUSTER is **the shift, not the cause** — record heat has stopped arriving one city at a time;
a region's worth in one afternoon is the *climate arc* (a warming baseline), which is honest
world-knowledge framing — NOT a "heat dome" / blocking ridge (a synoptic cause the bundle can't
prove and that is already on the `forbidden_claims` denylist).

- ✓ (target) *"Madrid and Toledo are on pace for their hottest readings on record, four more
  Spanish cities for their hottest July — a dozen records across Iberia in one afternoon. Heat
  records like these used to arrive one city at a time; a whole region's worth in a day is what
  a warmer baseline looks like."*

**Task:** rewrite the section so it (a) rides the signature move (system clause = the shift);
(b) keeps only genuinely signal-SPECIFIC rules — the fields to cite (`tier_counts`,
`records_provenance`, `significant_cities`, the carried geography), the tense-by-provenance
contract, the no-cause honesty; (c) trims the bits that just restate global principles
(don't-personify-the-region is already global, in the regional_anomaly section); (d) fixes the
example. Touch fact-check rule `r)` only if geography/tense wording must match. Dryrun-verify
with the harness (needs keys). codex-xhigh the editorial diff to clean APPROVE. **Voice is
Andrew's taste domain — show him the before/after section + example before merging.**

**Also log the standing rule** (feedback memory): *per-signal writer sections carry signal-
SPECIFICS only; the house voice (signature move) is defined once and every class rides it —
never invent a parallel register or an example that skips the system clause.*

## What shipped this session (all MERGED to `main`)

- **[#424](https://github.com/andrewzp/theheat/pull/424)** — #414 tier-aware standalone records-cluster **mechanism**: global via monthly/all-time tiers (world cities enter through them), significance-gated (`is_significant_cluster` = ≥1 all-time OR ≥3 monthly), tier-agnostic `place_key` dedup, suppress only constituent daily drafts, `records_provenance` tense honesty, **no reganom fusion, no cause attribution.** codex-xhigh APPROVED (2 rounds — round 1 caught 3 real P1 + 1 P2: the **world-monthly US-only trap** [`world_cache` stamps `old_record_year=_year(today)`], tier-agnostic dedup, a daily-draft leak, forecast-as-set provenance — all fixed TDD).
- **[#425](https://github.com/andrewzp/theheat/pull/425)** — **PR-C**: the writer-voice section (being realigned above) + fact-check rule `r)` + [scripts/records_cluster_writer_dryrun.py](/Users/andrewpuschel/Documents/Claude/theheat/scripts/records_cluster_writer_dryrun.py) harness. codex-xhigh APPROVED (2 rounds; the editorial prose had zero findings — only harness nits, now fixed).
- **[#426](https://github.com/andrewzp/theheat/pull/426)** — docs: marked #414 SHIPPED in the handoff + INDEX.
- **[#427](https://github.com/andrewzp/theheat/pull/427)** — dashboard auth (unrelated; see below).

## #414 state + taste calls (flag OFF)

- `THEHEAT_RECORDS_CLUSTER_ENABLED` = **OFF** + **manual-approval even when ON**. Flag-off ⇒ same-day path byte-identical.
- Flip (Andrew's explicit call only): `gh variable set THEHEAT_RECORDS_CLUSTER_ENABLED --body 1 --repo andrewzp/theheat`; rollback `--body 0`.
- **Live voice sample** (no keys in the build sessions): `ANTHROPIC_API_KEY=… GEMINI_API_KEY=… .venv/bin/python scripts/records_cluster_writer_dryrun.py --samples 3` — the way to see real tweets before flipping.
- Taste calls (defaults chosen, all in the code): significance gate (≥1 all-time OR ≥3 monthly), double-coverage (all-time/monthly cities post individually AND in the cluster), tuning (`LINK_KM=350` / `MIN_CLUSTER_SIZE=6` / containment `0.80`), writer voice (being realigned).

## Dashboard auth (DONE — FYI, no action)

`dashboard-andrew-puschels-projects.vercel.app` had TWO stacked logins (Vercel Authentication +
app HTTP Basic auth, the latter set to unrecoverable Sensitive env vars). Now a **single gate =
Vercel Authentication** (Andrew's Google/Vercel account). #427 added `DASHBOARD_AUTH_DISABLED=1`
(set in Vercel prod) to turn off the app's redundant Basic auth; deployed via `vercel --prod`
(deployment `dpl_BTqn5q3…`). Fails **closed** if that flag were ever removed. Verified: the URL
now 302s to `vercel.com/sso-api` (Vercel Auth), no app Basic challenge.

## Standing rules (bind every session — verbatim)

- `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH` on EVERY Bash command **including codex and git** (fresh shells lose cwd — git exits 128, codex "not a trusted directory"; retry with the prefix). Python `.venv/bin/python`; ruff/mypy `.venv/bin/ruff` / `.venv/bin/mypy`.
- Before every push: `ruff check src/ tests/` AND `mypy src/` AND `THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q` — all green (currently 2512). Fixtures today-relative.
- codex-xhigh on any diff touching editorial gates / posting / state / storage, looped to clean APPROVE (zero P0/P1/P2), the LAST round STARTING after the LAST edit. `codex exec -c model_reasoning_effort='"xhigh"' "<prompt>" < /dev/null` (the `< /dev/null` prevents a background stdin hang).
- Merge: `gh pr checks <N> --repo andrewzp/theheat --watch` → verify the required `test` check actually **passed** (not just the watch exit code) → `gh pr merge <N> --squash --delete-branch` → confirm `git log origin/main` shows the squash. **Claude merges.**
- One PR per unit; VERSION bump + CHANGELOG `[Unreleased]` ride code PRs; docs are their own PR. Never weaken an honesty gate. **US-only is off-brand.**

---

## Paste-ready kickoff prompt for the next session

> Pick up @theheat. `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH`
> — that exact prefix on EVERY Bash command INCLUDING codex and git (fresh shells lose cwd; git
> exits 128, codex "not a trusted directory" — retry with the prefix). Python `.venv/bin/python`
> (ruff/mypy = `.venv/bin/ruff` / `.venv/bin/mypy`); repo `andrewzp/theheat`; `main` is `dd4e525`,
> v0.9.99.0, tree clean.
>
> **READ FIRST, in order:** (1) `docs/handoffs/2026-07-09-next-session.md` — THIS doc: the open
> thread + full state. (2) The memory `project_theheat_414_records_cluster`. (3)
> `docs/superpowers/plans/front-page-parity/INDEX.md` §Standing rules.
>
> **STATE:** #414 tier-aware heat records-cluster is SHIPPED (#424 mechanism + #425 PR-C + #426
> docs), flag `THEHEAT_RECORDS_CLUSTER_ENABLED` **OFF** + manual-approval. Dashboard auth fixed
> (#427; single gate = Vercel Auth). All merged; tree clean on `main`.
>
> **THE OPEN THREAD — realign the `heat_records_cluster` writer voice.** Andrew's directive: "the
> voice across the whole project must be the same." The `## Heat records cluster bundles` section
> in `src/two_bot/prompts/writer_prompt.py` drifted into a **scoreboard** register that skips the
> house SIGNATURE MOVE (data point → system clause → stop; defined at the top of that file).
> Rewrite it to ride the one house voice: the system clause for a records cluster is **the shift,
> not the cause** — record heat has stopped arriving one city at a time; a region's worth in a day
> is the climate arc / a warming baseline, NEVER a "heat dome" (a synoptic cause on the
> `forbidden_claims` denylist). Keep only signal-SPECIFIC rules (fields to cite:
> tier_counts/records_provenance/significant_cities/geography; tense-by-provenance; no-cause
> honesty); trim the bits that restate global principles; fix the example (target ✓ example is in
> the handoff). Update fact-check rule `r)` only if wording must match. Dryrun-verify with
> `scripts/records_cluster_writer_dryrun.py` (needs ANTHROPIC_API_KEY + GEMINI_API_KEY). codex-xhigh
> the editorial diff to clean APPROVE. **Voice is Andrew's taste domain — show him the before/after
> section + example before merging.** Then **log the standing rule**: per-signal writer sections
> carry signal-SPECIFICS only; the house voice is defined once and every class rides it.
>
> **THEN, only if Andrew asks:** run the dryrun harness for a live voice sample, and/or flip
> `THEHEAT_RECORDS_CLUSTER_ENABLED=1` (his explicit words required — it's a prod flag flip). The
> other #414 taste calls (significance gate, double-coverage, L/N/containment tuning) are all
> defaulted and flagged in the handoff.
>
> **HOW (binds — INDEX §Standing rules):** the `cd … && PATH=…` prefix on every command; before
> every push ruff + mypy + `THEHEAT_TIME_TRAVEL_DAYS=90` pytest green; codex-xhigh on editorial
> diffs looped to clean APPROVE, LAST round after LAST edit; Claude merges (checks green → squash
> → verify `git log origin/main`); docs are their own PR; never weaken an honesty gate; US-only is
> off-brand. Work autonomously; stop only for a real fork or a prod flag flip (his explicit words).
