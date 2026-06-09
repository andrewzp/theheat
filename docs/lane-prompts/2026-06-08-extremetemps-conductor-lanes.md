# @extremetemps — Conductor lane dispatch (2026-06-08)

Paste-ready prompts for building the 4 ENG-CLEARED @extremetemps plans in isolated
Conductor worktrees. Pre-build gates were run inline 2026-06-08 (see Appendix); each
prompt states its gate result so the build agent does NOT re-block.

## Dispatch schedule

- **Wave 1 (parallel — near-term editorial supply):**
  - **Lane A** = absolute-extreme → wet-bulb, **SEQUENTIAL inside ONE worktree** (they
    edit the same `src/data/open_meteo.py` lines — `ExtremeSignalBundle` field + the
    `any([...])` inclusion gate at line 641 — so they cannot be parallel worktrees).
  - **Lane B** = air-quality (new module, independent).
- **Wave 2:** **Lane C** = SST (new module; **build LAST** per Andrew, 2026-06-08 — it
  earns ~zero supply until NH late summer).
- **Merge (Claude-main, after each PR's `test` check passes):** merge whichever lands
  first; the next rebases/resolves the trivial registry-file additions (`thresholds.py`,
  `approval.py` manual_only set, `common.py` `__all__`, `scoring/__init__.py`,
  `two_bot/intern/__init__.py`, `state.py` `DEFAULT_STATE`) — adjacent additions, easy
  3-way merges. Retarget any downstream PR to main before merging its upstream.
- **Review:** at the PR stage (the in-worktree `codex`/`/code-review` is blocked by the
  broken global `~/.codex/config.toml`). Claude-main runs `/code-review` per PR via the
  throwaway-`CODEX_HOME` workaround, or Andrew runs `/code-review ultra <PR#>`.

---

## Lane A — absolute-extreme → wet-bulb (SEQUENTIAL, one worktree)

```
Resume @theheat to BUILD two related signals in THIS isolated Conductor worktree.
Repo root: /Users/andrewpuschel/Documents/Claude/theheat

Build these TWO plans, IN THIS ORDER, in this single worktree — they edit the SAME
lines of src/data/open_meteo.py (the ExtremeSignalBundle field block + the any([...])
inclusion gate at line 641), so they CANNOT be separate parallel worktrees:

  1. FIRST: /Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-08-absolute-extreme.md
  2. THEN:  /Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-08-wetbulb-extremes.md

Read each plan IN FULL before coding it. Each is self-contained with verified path:line
anchors, a TDD test list, and a GSTACK REVIEW REPORT (both ENG CLEARED).

Pre-build gates (already cleared 2026-06-08 — do NOT re-block on them):
- absolute-extreme: NO gate (rides detect_extreme_signals; no new data). Honor the plan's
  OPEN QUESTION recommendation to also support the GHCN confirmed-observation path.
- wet-bulb Step 0: the Open-Meteo ARCHIVE endpoint ACCEPTS wet_bulb_temperature_2m_max
  alongside temperature_2m_max/min — verified HTTP 200 with all three fields present and
  real floats. WIRE THE VAR INTO BOTH the forecast AND archive daily params (Step 1c).
  Do NOT take the forecast-only fallback.

Build discipline:
- TDD: write the plan's failing tests FIRST, then implement to green.
- Build absolute-extreme COMPLETELY (its tests + full suite green) and COMMIT before
  starting wet-bulb. Sequencing them in one worktree avoids the line-641 conflict.
- Both launch manual_only — keep that posture; do NOT change approval mode beyond spec.
- Gate before PR (source .venv/bin/activate first): `python -m mypy src/` clean;
  `python -m ruff check` clean on changed files; `python -m pytest tests/ -q -m "not
  voice_replay"` all green; plus each plan's targeted tests.

When green:
- `git push` this worktree's branch and open a PR with `gh pr create` (base: main).
  One combined PR is simplest; two stacked PRs (absolute-extreme, then wet-bulb on top)
  is also fine.
- Do NOT merge — Claude-main merges after the `test` check passes.
- Do NOT run codex or /code-review in this worktree (global ~/.codex/config.toml is
  broken; review happens at the PR stage).

Constraints: no push to main; posting stays manual_only; absolute paths in file links.
```

---

## Lane B — air-quality (new module, parallel-safe)

```
Resume @theheat to BUILD the air-quality signal in THIS isolated Conductor worktree.
Repo root: /Users/andrewpuschel/Documents/Claude/theheat

Build: /Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-08-air-quality-pm-dust.md
Read it IN FULL before coding. Self-contained, verified anchors, ENG CLEARED (Revision 2).
NEW source module — independent of the open_meteo lanes; safe to run in parallel.

Pre-build gate (Step 0 — already cleared 2026-06-08, do NOT re-run/re-block):
- CAMS tiers validated against live data. SHIP THE TIER CONSTANTS AS-PLANNED:
  PM2.5 24h-mean 150/250/350 µg/m³; dust daily-max 500/2000/5000 µg/m³.
- Calibration evidence: clean cities (Reykjavik 2, Auckland 12) sit far below the floors;
  a real Delhi pre-monsoon dust event (1503 µg/m³) fired dust tier-1; baseline Sahel dust
  (Khartoum 292, Niamey 230) stays correctly under the 500 floor. Keep the PROVISIONAL
  label in code comments per the plan, but no tier change is needed.

Build discipline:
- TDD: write the plan's failing tests FIRST (batched-fetch list-response parse, 24h-mean
  vs daily-max, tier boundaries, event_id schemes), then implement to green.
- PM2.5 uses the 24h-MEAN; dust uses the daily-MAX (Revision 2 fix — do not regress).
- Tier-dedup state writes via the on_draft_success callback, NOT at detection time
  (Step 5 / Codex P1). Mirror an existing source's callback pattern exactly.
- Batched fetch (CHUNK_SIZE=50) — ~13 calls for 638 cities, not 638 calls.
- Launches manual_only — keep that posture.
- Gate before PR (source .venv/bin/activate): mypy src/ clean; ruff clean on changed
  files; `pytest tests/ -q -m "not voice_replay"` green + the plan's targeted tests.

When green: `git push` the worktree branch, `gh pr create` (base: main). Do NOT merge.
Do NOT run codex or /code-review here (global ~/.codex/config.toml broken — review at PR stage).
Constraints: no push to main; manual_only; absolute paths in file links.
```

---

## Lane C — SST regional anomaly (new module, parallel-safe, BUILD LAST)

```
Resume @theheat to BUILD the regional SST anomaly signal in THIS isolated Conductor worktree.
Repo root: /Users/andrewpuschel/Documents/Claude/theheat
PRIORITY: build this LAST of the four @extremetemps lanes (Andrew's call 2026-06-08) —
dispatch after the absolute-extreme/wet-bulb and air-quality lanes.

Build: /Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-08-sst-anomaly-marine-heatwave.md
Read it IN FULL before coding. Self-contained, Rev 4, ENG CLEARED, 2 Codex passes.
NEW source module (NOAA Coral Reef Watch gridded anomaly via CoastWatch ERDDAP) —
independent of the other lanes; safe to run in parallel but sequenced last per above.

Pre-build gates (both already run 2026-06-08 — do NOT re-block):
- (1) ERDDAP re-probe: noaacrwsstanomalyDaily is LIVE — HTTP 200, text/csv, NO auth,
  2-day lag (within the 5-day window). The 13-region burst (ThreadPool max_workers=4)
  finished in 2.4s with no rate-limiting. Build against it.
- (2) Tier/box calibration: SHIP THE THRESHOLDS AS-PLANNED — absolute area-weighted
  basin-mean +2.5 (t1) / +3.5 (t2) / +4.5 (t3) °C, the 13 generous boxes, manual_only.
  Calibration result: 0/13 basins fire in June (highest = Med +1.97°C) — the astounding-
  bar working correctly; SST is a NH-late-summer signal (Aug–Sep peak). Keep the
  thresholds PROVISIONAL in comments per the plan.
- DOCUMENTED FAST-FOLLOW (NOT v1): the basin-wide boxes dilute (north_atlantic averages
  a +9.6°C hot patch down to +0.46°C). Leave a code comment flagging box-tightening to
  anomaly cores as a post-NH-summer refinement, but do NOT change the boxes in this build.

Build discipline:
- TDD per the plan (registry=13, cos-lat area-weighted mean, griddap CSV parse incl.
  fill/valid filter, tier boundaries, dateline fail-fast, annual tier-key rotation,
  runner tests).
- Honor the folded P1 fixes: [P1-1] add BOTH new state keys to _merge_state() (else they
  vanish on merge — highest priority); [P1-2] derive the year from the READING date, not
  date.today(); [P1-3] fetch_all_regions defaults strict=False (per-region degradation;
  the runner does NOT use _fetch_strict).
- Launches manual_only — keep that posture.
- Gate before PR (source .venv/bin/activate): mypy src/ clean; ruff clean on changed
  files; `pytest tests/ -q -m "not voice_replay"` green + the plan's targeted tests.

When green: `git push` the worktree branch, `gh pr create` (base: main). Do NOT merge.
Do NOT run codex or /code-review here (global ~/.codex/config.toml broken — review at PR stage).
Constraints: no push to main; manual_only; absolute paths in file links.
```

---

## Appendix — pre-build gate evidence (run 2026-06-08, probe at /tmp/theheat_prebuild_probes.py)

### Wet-bulb (PASS)
- Forecast `wet_bulb_temperature_2m_max`: HTTP 200, returns `[28.5]`.
- **Archive (the blocking one):** HTTP 200, `daily` fields = `[time, temperature_2m_max,
  temperature_2m_min, wet_bulb_temperature_2m_max]`. `temperature_2m_max=[37.8, 34.8, 35.2]`
  still present; `wet_bulb=[28.9, 27.8, 28.5]` real floats. Core air-temp regression OK —
  the "could break all air-temp records" risk is cleared. Wire the var into both requests.

### Air-quality (PASS, tiers validated)
| city | expect | pm25_24h_mean | pm25_tier | dust_daily_max | dust_tier |
|---|---|---|---|---|---|
| Lahore | dirty | 39.2 | — | 69 | — |
| Delhi | dirty | 124.0 | — | **1503** | **1** |
| Reykjavik | clean | 2.1 | — | 0 | — |
| Auckland | clean | 11.6 | — | 0 | — |
| Khartoum | dusty | 37.1 | — | 292 | — |
| Niamey | dusty | 15.1 | — | 230 | — |

Clean cities ≪50; Delhi (off-season) at 124 confirms the 150 PM2.5 floor is conservative-
but-reachable in-season; Delhi dust 1503 fired a real tier-1 event; baseline Sahel dust
(230–292) stays under the 500 floor. Ship 150/250/350 + 500/2000/5000 as-is.

### SST (endpoint PASS; calibration = seasonal, ship as-planned)
Re-probe: HTTP 200, text/csv, no auth, 2-day lag; 13-box ThreadPool(4) burst in 2.4s, no
rate-limiting. 13-region calibration (stride 20, cos-lat area-weighted mean), grid 2026-06-06:

| region | cells | awm °C | min | max | tier |
|---|---|---|---|---|---|
| north_atlantic | 3736 | 0.46 | −7.5 | **9.6** | — |
| subpolar_n_atlantic | 416 | −0.20 | −5.8 | 1.8 | — |
| ne_pacific_blob | 388 | 0.63 | −2.1 | 3.0 | — |
| mediterranean | 310 | **1.97** | −0.3 | 4.2 | — |
| tasman_sea | 383 | 1.23 | −0.7 | 4.2 | — |
| gulf_of_mexico | 191 | 0.93 | −0.5 | 2.1 | — |
| caribbean | 327 | 0.84 | −1.1 | 2.8 | — |
| western_indian_ocean | 615 | 0.68 | −2.8 | 2.4 | — |
| bay_of_bengal | 230 | 0.84 | −0.4 | 2.8 | — |
| coral_triangle | 557 | 0.62 | −0.5 | 1.4 | — |
| great_barrier_reef | 125 | 0.66 | −0.2 | 1.5 | — |
| california_current | 89 | 0.28 | −2.1 | 1.7 | — |
| nino34 | 561 | 1.64 | 0.6 | 2.7 | — |

0/13 fire vs the +2.5 floor (highest = Med +1.97). Correct astounding-bar behavior for
June; SST fires in NH late summer. north_atlantic shows the box-dilution issue (+9.6 patch
→ +0.46 mean) — documented fast-follow, not a v1 change.
