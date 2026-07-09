# Handoff — 2026-07-08 (evening) · #414 heat records-cluster: DESIGN PIVOT to tier-aware standalone

**`main` @ `51d633b`, version `0.9.98.0`.** PR-B lives UNMERGED on
`origin/feat/records-cluster-detection` @ `ccc99f7` (version 0.9.99.0 on the branch).
Supersedes [docs/handoffs/2026-07-08.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-07-08.md) for everything #414.

> **★ The one thing to know:** #414 is being **reworked to be TIER-AWARE and STANDALONE**
> (daily **+ monthly + all-time** record members, gated on record *significance*, **NO
> reganom fusion**). The committed PR-B is a daily-count-only mechanism that codex proved
> is **US-only in production** and marginal on the editorial bar. The rework is the next
> step. Full spec + paste-ready kickoff at the bottom.

## TL;DR of the journey (so a fresh session has the arc)

1. **Spike → plan → codex design review.** The [#414 spike](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-07-08-heat-records-cluster-spike.md) (GO) → an executable [row-414 plan](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-414-heat-records-cluster.md) → a **codex-xhigh DESIGN review** (BLOCK → 4 P0s fixed: geography country-purity, transcontinental-continent omission, "heat dome" forbidden, suppression-ordering prepass). Docs PR [#421](https://github.com/andrewzp/theheat/pull/421) merged.
2. **PR-A — merged.** `src/editorial/records_cluster.py`: single-linkage spatial clustering + the **honest namer** (documented reganom zone iff country-pure + geographically contained, else "N cities across K countries[ in {continent}]", continent omitted for transcontinental/US-territory). **3 codex-xhigh rounds** each caught real honesty bugs (blank-country → false "Iberia"; US-alias double-count; `inf` crash; dup-key nondeterminism; US-territory continent; `USA` alias) → all fixed → APPROVE → PR [#422](https://github.com/andrewzp/theheat/pull/422) merged. 31 tests.
3. **PR-B — built, committed, NOT merged** (`origin/feat/records-cluster-detection`). The daily-count-only mechanism: detection prepass (reads `bundle.calendar_date_high` only), `heat_records_cluster` bundle/scoring/threshold, `heat_records_cluster_fired` dedup key (sqlite contract + merge + TTL), deterministic honesty gate, manual-approval, full registration. codex-xhigh review → **CHANGES-REQUESTED** (0 P0; 3 P1 + 1 P2): 3 contained fixes applied on the branch (bot.yml flag passthrough, honesty-gate breadth + continent-overclaim guard, signature collision); the **4th P1 (global reach) folds into the rework**.
4. **Andrew's pivot: "how would a human newsroom do this?"** That reframed everything → I proposed fusing the cluster with **reganom** (regional_anomaly) for "cause + effect."
5. **codex stress-tested the reasoning → killed the fusion, confirmed the rework.** Verdict below.

## The codex reasoning stress-test (the decision)

codex, as skeptic-meteorologist + wire-desk editor + anti-scope-creep engineer, graded the five claims:

| Claim | Verdict |
|---|---|
| **1. Can't say "heat dome" (no synoptic map)** | **HOLDS** — and stronger: clustered records aren't even a *unique* heat-dome fingerprint (advection, downslope winds, dry air, station quirks all cluster). Forbid cause words. |
| **2. reganom = the air-mass/dome detector we're missing** | **MOSTLY WRONG** — reganom fetches ERA5 *surface* `temperature_2m_max` anomaly over sampled points, **not** 500 mb heights/ridges/blocking. It's another *effect* sensor, not the cause. |
| **3. Gate on record TIER, not daily count** | **PARTIALLY HOLDS** — editorially right (repo already ranks all-time>monthly>daily); the committed cluster is count-of-daily only. Including all-time/monthly **also restores world reach** in `provider=both`. But "zero cost" was hand-waving (tier semantics, scoring, copy, dedup all get harder). |
| **4. reganom zones = the newsroom's vernacular region names** | **PARTIALLY WRONG** — some are (Iberia, Sahel); the list isn't a full vernacular map. And the "N countries in continent" fallback is **the honesty mechanism**, not a symptom of a missing map. |
| **5. records-led-but-fused** | **PARTIALLY HOLDS but not as built** — records-led is right for #414; anomaly-led would just be reganom-with-garnish. But fusion is real engineering (reganom is a *separate* source runner, runs *later* in sequential alerts, **no co-fire matcher exists**) — AND the cadence kills it: records use today's forecast / obs ≤4d old; **reganom is intentionally several complete days behind** (ERA5 lag), so same-window co-firing is unreliable. |

**codex bottom line:** ship **lean, standalone, records-led, tier-aware** — **NOT** anomaly-led, **NOT** causal fusion. Framing: *"Daily heat records fell in N cities across [honest geography], with all-time/monthly records noted separately when present."* **Biggest risk in the pre-pivot direction:** *using reganom as permission to say more than either sensor proves → a brittle implied-attribution product.*

Andrew + codex + I converged: **tier-aware standalone records cluster, no reganom entanglement.**

## Current git / prod state

- **`main` @ `51d633b`, v0.9.98.0.** PR-A merged; `src/editorial/records_cluster.py` lives here (namer + clustering + signature helpers, all codex-APPROVED). `CHANGELOG [Unreleased]` has the PR-A entry.
- **`origin/feat/records-cluster-detection` @ `ccc99f7`, v0.9.99.0 (branch only).** PR-B daily-only mechanism + the 3 codex-fix commit. **No open PR.** 2499 tests green on the branch. **Do NOT merge as-is** — rework first.
- **Flag `THEHEAT_RECORDS_CLUSTER_ENABLED` = default OFF**, wired into `bot.yml` (on the branch). The class is **manual-approval** even when ON.
- Unrelated: source-health issue [#420](https://github.com/andrewzp/theheat/issues/420) (`_pipeline_liveness` stale) **auto-filed 12:59Z, auto-closed 15:40Z** — self-healed, not from this work. Bot healthy.
- **Bash safety-classifier had an Anthropic-side outage** during the session (blocked test-runs/merges intermittently); recovered.

## ★ THE REWORK — tier-aware standalone records cluster

**Goal:** the class fires on a spatially-coherent burst of *significant* heat records (all-time / monthly / national-scale >> daily), names the region honestly (PR-A namer, unchanged), leads the copy with the significant records, and is **global in production** — with **no reganom fusion and no cause attribution**.

**What CHANGES from committed PR-B:**
1. **Prepass collects TIERED members** (`src/orchestrator/sources/open_meteo.py` prepass, ~line 295). Today it reads only `bundle.calendar_date_high`. Rework: for each bundle collect `all_time_high` (tier `all_time`), `monthly_high` (tier `monthly`), `calendar_date_high` (tier `daily`) — each carries `lat`/`lon`. Dedup a city to its **strongest** tier (all_time > monthly > daily). This is what makes it **global**: `evaluate_city()` (the `provider=both` world path, `src/data/world_thresholds.py:126`) emits all_time/monthly but **not** calendar_date_high, so world cities only enter the cluster via their monthly/all-time members.
2. **Scoring gates on SIGNIFICANCE, not daily count** (`src/editorial/scoring/temperature.py:score_heat_records_cluster`). Weight all_time ≫ monthly ≫ daily; a daily-only cluster should score low / not fire, a cluster with several monthly/all-time fires. **The exact gate is a taste call for Andrew** (e.g. "≥1 all-time OR ≥3 monthly OR a weighted-significance threshold").
3. **Bundle carries the tier breakdown** (`build_heat_records_cluster_bundle`): counts by tier (e.g. "3 all-time, 5 monthly, 8 daily"), sample cities *with their tier*, plus the existing honest geography facts.
4. **Copy leads with the significant records** (PR-C writer section): *"Heat records fell in N cities across [region] — including X all-time and Y monthly highs."* No "heat dome"/cause words (deterministic gate already enforces).
5. **Suppression / double-coverage** — a genuine **taste call**: today PR-B suppresses only the constituent *daily* drafts (all-time/monthly cities keep their own bigger individual draft). With tier members in the cluster, decide: does a city's all-time record post BOTH individually AND inside the cluster (a newsroom might run both), or does the cluster suppress those too? Surface to Andrew.
6. **NO reganom fusion.** Drop the idea. (Optional far-future: a *non-causal* corroboration note — but the cadence problem makes it low-value; don't build it now.)

**What SURVIVES from PR-B (keep):** the PR-A namer; the `heat_records_cluster_fired` state dedup key (sqlite contract + merge + TTL + recorder); registration (threshold/scoring shims/memory/finalize maps); **manual-approval**; the deterministic honesty gate (`_forbidden_claim_violation` + the broadened denylist + continent-overclaim guard); the flag + bot.yml passthrough; the cluster signature; the suppression/supersede *structure* (extend it to tiers).

**Still open (taste calls for Andrew, don't block on — pick sensible defaults + surface):**
- The **significance gate** (#2 above) — his editorial bar.
- **Double-coverage** (#5) — cluster-vs-individual for all-time/monthly cities.
- **Tuning**: `LINK_KM=350` / `MIN_CLUSTER_SIZE=6` / `ZONE_CONTAINMENT_FRACTION=0.80`. (Note: at L=350 a sparse real Desert-SW fragments — El Paso ~418 km from its neighbour; dense real data fills the gap, but L may want to rise.)
- **Writer voice** (PR-C) — show a dryrun sample before flip.

**Process (binds — INDEX §Standing rules):** `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH` on EVERY command (incl. codex + git). TDD throughout. Before every push: `.venv/bin/ruff check src/ tests/` + `.venv/bin/mypy src/` + `THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q` all green. **codex-xhigh** on every editorial/detection/state diff, looped to clean APPROVE, LAST round after LAST edit. Merge = checks green → squash → verify `git log origin/main`. Claude merges. VERSION + CHANGELOG ride code PRs; docs their own PR. **Never weaken an honesty gate. US-only is off-brand — the whole point of the tier rework is that monthly/all-time members make it global.**

---

## Paste-ready kickoff prompt for the rework session

> Pick up @theheat #414. `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH`
> — that exact prefix on EVERY Bash command INCLUDING codex and git (fresh shells lose cwd;
> codex fails "Not inside a trusted directory", git exits 128 — retry with the prefix).
> Python `.venv/bin/python` (ruff/mypy are `.venv/bin/ruff` / `.venv/bin/mypy`); repo
> `andrewzp/theheat`. `main` is `51d633b`, v0.9.98.0.
>
> **READ FIRST, in order:** (1) `docs/handoffs/2026-07-08-records-cluster.md` — THIS doc: the
> full arc, the codex reasoning stress-test that killed the reganom-fusion idea, and the
> tier-aware rework spec. (2) `docs/superpowers/plans/front-page-parity/row-414-heat-records-cluster.md`
> — the plan (now carrying the pivot banner). (3) `docs/superpowers/plans/front-page-parity/INDEX.md`
> §Standing rules.
>
> **STATE:** PR-A is MERGED (`src/editorial/records_cluster.py` — the honest namer +
> clustering, codex-APPROVED, on `main`). PR-B (the daily-count-only mechanism) is committed
> UNMERGED on `origin/feat/records-cluster-detection` @ `ccc99f7` — **do NOT merge it as-is.**
> `git checkout feat/records-cluster-detection` and build the rework on it (most of PR-B
> survives; see the handoff's "What SURVIVES" list).
>
> **DECISION (settled by Andrew + two codex passes — do not relitigate):** the class is a
> **tier-aware, STANDALONE records cluster. NO reganom fusion** (reganom is another surface-
> anomaly *effect* sensor, not a synoptic cause; and its ERA5 lag makes co-firing unreliable —
> fusing invites implied-attribution, the exact failure the bot guards against). The copy
> **never** asserts "heat dome" or any cause.
>
> **YOUR TASK — the tier-aware rework** (spec in the handoff's "★ THE REWORK" section):
> (1) prepass collects **tiered** members — `all_time_high` + `monthly_high` + `calendar_date_high`,
> each with lat/lon, a city deduped to its strongest tier; this is ALSO what makes it global in
> `provider=both` (world cities emit only monthly/all-time via `evaluate_city`, `world_thresholds.py:126`).
> (2) score/gate on record **significance** (all_time ≫ monthly ≫ daily), not daily count —
> a daily-only cluster shouldn't fire. (3) bundle carries the tier breakdown. (4) copy leads with
> the significant records. (5) keep suppression of constituent *daily* drafts; the all-time/monthly
> double-coverage question is a **taste call for Andrew**. (6) keep everything in "What SURVIVES"
> (namer, state key, honesty gate, manual-approval, flag, registration).
>
> **HOW:** TDD throughout. codex-xhigh on every editorial/detection/state diff, looped to clean
> APPROVE, LAST round after LAST edit. Before every push: ruff + mypy + 90-day pytest green.
> When the rework is APPROVE + green, open ONE PR from the branch, verify checks, squash-merge,
> confirm `git log origin/main` shows it. Then **PR-C** = the writer's voice for the class
> (writer_prompt section + fact_check rule) with a **dryrun voice sample surfaced to Andrew**.
>
> **SURFACE to Andrew as taste calls (don't block — pick defaults + flag):** the significance
> gate (what makes a cluster fire), the all-time/monthly double-coverage decision, L/N/containment
> tuning, and the PR-C writer sample. Work autonomously; stop only for a real fork or a prod flag
> flip (his explicit words required). The flag stays OFF until the rework is global + verified.
