# Handoffs

Dated end-of-session brief documents. Each file captures the state of @theheat
at end-of-session and orients the next session.

**Most recent first:**

- [2026-06-09-v2.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-09-v2.md) — **CURRENT.** 0.9.20.0. @extremetemps lane COMPLETE (Part B landed #203). 8 PRs: Part B + 3 state-correctness fixes (#200/#204/#206 + the merge-handler contract test) + 3 tech-stack-review wins (#208 gist minify −621 KB, #209 tests 26s→4s + workflow timeouts, #210 −240 dead lines). reganom landed but **DORMANT** (`THEHEAT_REGANOM_ENABLED` unset — one-command flip). Tech-stack review + architectural backlog (MERGE_SPEC next) inside. Carries the paste-ready resume prompt.
- [2026-06-09.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-09.md) — mid-session brief (Part B landed, activation). Superseded by v2.
- [2026-06-08-v3.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-08-v3.md) — Wave 1 + SST landed; Part B Rev-3 build-ready. Superseded by 2026-06-09-v2.
- [2026-06-08-v2.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-08-v2.md) — Landed 0.9.16.1 (#191); planned + reviewed the full @extremetemps lane (#192) — 5 build-ready plans in docs/plans/ (4 ENG CLEARED, 1 deferred). Build order + Conductor parallelization caveat inside. Superseded.
- [2026-06-08.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-08.md) — grading routine restored (root cause: unbound repo), gpm datapool live (0.9.15.0), per-type pending TTL (0.9.16.0). (Superseded by v2.)
- [2026-06-06.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-06.md) — 0.9.11.1–0.9.14.0: daily source-health sentinel (per-source auto-closing GitHub issues, `ours` vs `external`) + dashboard external/idle tier; gpm_imerg fan-out cap + codex review-follow-up hardening; gpm AWS alternate-feed plan written (build deferred — gpm 0-value). ⚠️ daily-plan grading routine STILL DOWN since 05-26 (operator-gated) — the #1 open thread.
- [2026-06-02.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-02.md) — 0.9.9.0–0.9.11.0: source-health dashboard panel fixed + deployed; source-fetch reliability sweep (gpm_imerg 404 walk-back, IPv4 force, retry routing). (Superseded by 2026-06-06.)
- [2026-06-01.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-01.md) — 0.9.4.0–0.9.8.0 auto-fix sweep; bot re-enabled after a 12-day pause. (Superseded — it claimed the routine was healthy and C5 was unbuilt; both wrong, corrected in 2026-06-02.)
- [2026-05-22-v2.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-05-22-v2.md) — 0.9.1.0–0.9.3.0 dashboard automation indicators + beacon migration.
- [2026-05-19.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-05-19.md) — 0.9.0.0 all-sources triage migration + evidence contract.
- [2026-05-15.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-05-15.md) — overnight wave (Plans A-F + F2 + threshold registry + monolith decomposition). 23 PRs merged. 1151 tests.
- [2026-05-14-v2.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-05-14-v2.md) — Plan A pre-wave handoff; brand-kit correction captured. Anomaly threshold PR #96 staged.
- [2026-05-14.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-05-14.md) - initial 2026-05-14 sweep, superseded by v2
- [2026-05-12-v2.md](2026-05-12-v2.md) - late-evening cleanup wave and production fixes, supersedes 2026-05-12
- [2026-05-12.md](2026-05-12.md) - end-of-day PR #78 and #80 handoff, superseded by v2
- [2026-05-11.md](2026-05-11.md) - 2026-05-10 session handoff
- [2026-05-09.md](2026-05-09.md) - 2026-05-08 late-session handoff

## Convention Going Forward

- Filename format: `YYYY-MM-DD.md` or `YYYY-MM-DD-v2.md` / `YYYY-MM-DD-v3.md` for same-day iterations.
- Always link the new file from the top of this README.
- The current next-session handoff is whichever file sits at the top.
