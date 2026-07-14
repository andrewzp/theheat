# The economics master plan (v3) — reconciled

> **Supersedes** [PLAN-25-PERCENT.md](PLAN-25-PERCENT.md) (proposal A, 2026-07-13) and the external
> cross-model audit pasted 2026-07-13 (proposal B). Every load-bearing claim from both was verified
> against the repo, the GitHub Actions logs, and live Anthropic/Google docs on **2026-07-13**; this
> document records what survived, what was corrected, and the one merged plan.
>
> **Mandate (Andrew):** Claude stays the writer. Everything else can move. Quality same or better.
> Cost ≤ 25% of today. **This plan budgets 20% with a 5% reserve** (B's governance framing, adopted):
> today ≈ **$50–70/month** (corrected ledger) → operational budget **≤ $10–14/month**, hard ceiling
> $13–18.
>
> **Context that orders the work:** the Anthropic balance hit $0 on 2026-07-11 and drafting silently
> stopped. P0 lands **with** the top-up so the refilled balance isn't burned by the old architecture
> — and P0 item 2 exists because the 2026-07-13T21:02Z cycle fired **six** paid attempts (six
> distinct `request_id`s) *after* the first "credit balance is too low" error.

## 1. The corrected ledger — what actually burns credits

All Anthropic-billed unless noted. Writer = `claude-sonnet-4-6` ($3/$15 per MTok; 5-min cache write
$3.75/M, read $0.30/M — verified live 2026-07-13). Writer system prompt measured at **60,404 chars ≈
15.1k tokens** (the in-code "~5,700 tokens" comment is 2.6× stale).

| # | Consumer | Mechanics (verified) | Ceiling | Typical | ≈ $/month |
|---|---|---|---|---|---|
| 1 | voice-regression nightly 09:00 UTC | 39 paid replays/run against the full 15.1k-token prompt (18 safe-or-kill + 18 no-fabrication + fixtures); header comment says "$6/month" — 5× stale | 39 calls/day | 39 | **~$30** |
| 2 | bot writer, 6 cycles/day (cron 0,4,8,16,20 + 12 UTC) | `THEHEAT_WRITER_SAMPLES=2` (repo var since Jun 13) × refill target 3 × attempts ≤ 6; both concurrent samples miss a fresh cache (documented API behavior); ~$0.057 cache re-warm burned every cycle (5-min TTL vs 4-h cycle gaps ⇒ ~$10/mo of pure re-warming) | 72 calls/day | ~10–20 | **~$15–25** |
| 3 | workflow-self-heal daily 13:00 UTC | `claude-code-action@v1`, **no model pin** (an observed run selected Opus-class, $0.39), `--max-turns 40`, runs even when all workflows are green | 1 agent session/day | 1 | **~$5–15** |
| 4 | ~~virality evaluator~~ | **dead code** — `evaluate_and_polish` has exactly one caller (`src/voice/generator.py:807`) and the legacy generator has zero live importers | 0 | 0 | **$0** |
| 5 | Gemini: fact-check (Flash), safety Layer-2 (Flash), F3 critic (Pro), grounded news (Flash) | bills to Google; presumed free tier (**unconfirmed — Andrew check §9**). Real risk is quota, not dollars: Pro free tier ≈ 50 req/day vs up to ~18–36 critic calls/day | — | — | $0 (quota risk) |
| 6 | daily-plan / grading routine | claude.ai RemoteTrigger routine on the **Max 20x subscription** — $0 marginal API. Struck from the ledger; do **not** pause it | — | — | $0 |

**Today ≈ $50–70/month.** Two structural facts stand from proposal A: the test suite outspends the
product ~2:1, and cache re-warms dominate writer cost at our volume. One stands from proposal B: the
retry stack is four layers deep (SDK default `max_retries=2` × `call_with_retries` 3 attempts ×
JSON-parse 2 × length 3 — up to 6 provider calls per writer sample before transport retries).

## 2. Reconciliation record

### Corrections to proposal A (the prior 25% plan)

1. **Evaluator line was fiction.** It charged $3/mo and planned "instrument → delete" for a
   component with no live callers. Replaced by P1's dead-code quarantine (a hygiene/risk win, $0).
2. **Its P0 flag flip was unsafe alone.** `THEHEAT_WRITER_SAMPLES` 2→1 silently **activates** the
   critic-REVISE rewrite lane (`pipeline.py:340-399` — the per-candidate critic with
   `allow_revise` only runs when `slate_critic_result is None`, i.e. samples=1), and
   `THEHEAT_CRITIC_REVISE_ENABLED=1` is live. The two flags must flip together (P0 item 1). B's
   flag set had this pairing right, without stating why.
3. **PR-gating alone would have lost the outage canary.** The nightly suite is the de-facto
   billing/key tripwire (it was the only loud signal in the 07-11 outage; `bot.yml` stays green
   through writer failures). The synthesis keeps a 3-fixture daily canary (P0 item 4).
4. Its slicing rejection survives, but for updated reasons (see conflict 1 below).

### Corrections to proposal B (the external audit)

1. **"Compile a per-signal prompt under 15,000 chars" is impossible.** Measured anatomy of
   `WRITER_SYSTEM_PROMPT`: universal sections (voice, gates, signature move, bundle contract,
   memory slice, WHAT-NEVER-SHIPS, exemplars, kill discipline, output) ≈ **27k chars**; per-signal
   sections ≈ 33.5k total, ~4.2k each. A compiled prompt floors at ~31k chars ≈ 7.9k tokens — a
   ~48% input cut, not 75%, worth ~$1–2/mo under the P2 batch architecture. Parked (conflict 1).
2. **The "daily grading routine" costs $0.** It is a claude.ai scheduled routine on the Max plan,
   not API spend. Not paused; struck from the ledger.
3. **"72 calls/day" is the ceiling, not the run-rate** (typical ~10–20 at current success rates).
   Both numbers now appear in the ledger.
4. **Structured outputs can't eliminate the length-retry lane.** Verified live: `output_config.format`
   is GA on `claude-sonnet-4-6`, but `maxLength` is not supported server-side — the 280-char cap
   stays a retry loop. Structured outputs only retires the JSON-parse retry lane (P2 item 3).
5. Its per-candidate call counts, the July-13 continuation-after-billing-failure claim, the nested
   retry stack, the refill-flag semantics, the fail-open Gemini safety question, the "when in
   doubt, ACCEPT" fact-checker posture, and the Sonnet 5 pricing/tokenizer facts **all verified
   exactly**.

### Adjudicated conflicts

1. **Per-signal prompt slicing** — A: reject (cache fragmentation); B: adopt (<15k chars, adherence
   + cost). **Verdict: not a cost lever at all** (B's size target impossible; under live cycles
   fragmentation can cost more — A right; under P2 batch it saves ~$1–2/mo — immaterial). Its one
   real promise is *adherence* (less instruction dilution from ~26k chars of irrelevant signal
   rules per call). Parked as a **P3+ experiment**, runnable only against the frozen replay corpus
   with blind preference ≥ baseline. It adds an assembly seam to the most taste-sensitive file in
   the repo; nobody buys that seam for $2.
2. **Voice-regression cadence** — A: PR-gated + weekly canary; B: kill nightly, 3 daily canaries +
   weekly batch. **Verdict: both, merged** — auto PR gate on prompt/writer paths (quality UP:
   blocks the offending merge), 3-fixture daily canary that **fails red on billing/auth errors**
   (preserves the outage-tripwire role), weekly full suite (batched in P2).
3. **Batch scope** — A: batch the whole writer path; B: batch only non-urgent. **Verdict: batch all
   standard cycles** — nearly all drafts wait for Andrew anyway, and the autoship lane
   (`AUTOSHIP_ALLOWLIST` kinds, critic-pass, 36-h freshness ceiling) tolerates the typical <1 h
   batch latency; a freshness guard (P2) hands stale batch results to manual review instead of
   autoshipping. Sync path retained for dryruns and any future live-alert lane.
4. **Critic consolidation** — B: one Pro slate call per cycle; A: keep Pro per candidate. **Verdict:
   keep per-candidate for now** (it is a blocking honesty/taste gate; don't change gate semantics
   for $0), **consolidate only if** Andrew's Gemini-tier check shows quota pressure (free Pro ≈ 50
   req/day; we run ~6–18/day typical). Never Flash for the critic (taste rule).
5. **Grading routine** — B: pause until delta-check. **Verdict: leave it alone** ($0, and it's the
   daily editorial planning input).
6. **Fact-checker posture** — B frames "when in doubt, ACCEPT" as the defect behind the false
   records. Partially right, but the permissiveness is deliberate editorial policy (the writer's
   world knowledge is the product); the systemic fix both proposals converge on is the
   **claim/warrant model** ([design](../../../plans/2026-06-16-claim-warrant-model.md), PR #324 —
   Andrew-gated), not a stricter LLM checker.

### Converged independently (highest confidence)

Samples → 1 · self-heal → deterministic keyless red-gate + cheap pinned model only on red · nightly
suite off cron · usage ledger + caps + alerts · Claude keeps the pen; no Flash in taste roles ·
Batch API as the structural saver · claim/warrant as the false-record fix.

## 3. The plan

### P0 — stop-loss (config + 2 small diffs, ~1 session, no quality surface)

1. **Paired flag flip** (one change, never split):
   `gh variable set THEHEAT_WRITER_SAMPLES --body 1` **and**
   `gh variable set THEHEAT_CRITIC_REVISE_ENABLED --body 0`.
   Keep `THEHEAT_REFILL_ENABLED=1` (the refill loop owns the $0 pre-writer dedup/cooldown
   predicates and SUCCESS-aware caps); defaults already give target 3 / attempts 6.
   *Watch:* approved drafts/day and `critic` kill counts in funnel telemetry. *Re-enable trigger:*
   if approved drafts/day drops >20% for a week, flip REVISE back on before touching anything else.
2. **Cycle-level billing circuit breaker** (small diff in `_refill_drain` + the non-refill path):
   first `kill_stage == "budget_exhausted"` aborts the remaining slate for the cycle and records
   one suppression. (The per-call breaker has existed since May — `BudgetExhaustedError` skips
   retries; the gap is per-cycle, proven by the six post-failure request_ids on 07-13.)
3. **One retry owner:** `max_retries=0` on the Anthropic client in `writer.py` —
   `call_with_retries` (3 attempts, billing-aware) is the single transport-retry layer.
4. **voice-regression.yml:** delete the nightly cron. Add automatic `pull_request` trigger on
   `src/two_bot/prompts/**` + `src/two_bot/writer.py` (keep the `voice-check` label for everything
   else). Add a **daily 3-fixture canary job**: high-signal fixtures, asserts API reachable
   (billing error → **red** — the outage tripwire) and ≥2/3 produce a safety-passing tweet. Weekly
   full 39-fixture run (cron; moves to Batch in P2). Fix the stale "$6/month" header with a real
   `cost/run × cadence` line.
5. **workflow-self-heal.yml:** new keyless preflight job (gh api red-count over the five scheduled
   workflows; **writes SELFHEAL_BEACON itself** via `gh variable set` so green days cost $0 and
   the heartbeat survives); agent job runs only on red, pinned `--model claude-haiku-4-5`
   (mechanical triage; JUDGMENT items already PR-and-stop).
6. **Ledger MVP:** append per-call `usage` (stage, model, in/cached/out tokens, est $) to state;
   dashboard/sentinel surface lands in P1.
7. **Andrew (Console, ~5 min):** top-up + auto-reload + monthly cap + spend alerts.

### P1 — measurement + hygiene (small code)

1. Ledger dashboard line + weekly sentinel `$ est./month` + in-code per-cycle writer-call cap with
   alerts at 70%/90% of budget.
2. **Delete the dead legacy pipeline** (`src/voice/generator.py` generation path,
   `src/editorial/evaluator.py`, orchestrator vestiges): zero live callers, but a
   virality-rubric rewriter with kill power ("scroll-stopping opener", "REPLY BAIT: imply, don't
   state" — the banned wink, one import away from the publication path) plus a
   contradiction (`EVALUATOR_ENABLED` env-defaults to *true* while the comment claims disabled).
   Pure deletion PR; no behavior change; tests updated.
3. Optional, data-gated: cross-cycle negative cache (skip re-attempting a killed bundle unless its
   material facts changed) — only if week-1 funnel shows repeated same-event writer kills.

### P2 — the dollar mover (one focused session)

1. **Batch API writer lane:** submit at cycle time (custom_id = event_id, pending-batch state in
   the gist), collect in the existing hourly :30 cron, then run today's gates unchanged
   (safety → honesty → fact-check → critic) on collection. Batch = 50% off input *and* output and
   **stacks with caching** (verified live). Autoship freshness guard: batch results older than a
   threshold go to manual review, never autoship. Sync path stays for dryruns/live-alert lane.
   *Measure batch cache-hit rate in the ledger for week 1 — it decides where in the $7–12 writer
   range we land.*
2. **Structured outputs** for the writer response (`output_config.format` json_schema — GA on
   sonnet-4-6): retires the JSON-parse retry lane and that failure mode. Length-retry loop stays
   (280 is semantic; `maxLength` unsupported server-side).
3. Critic slate-consolidation: **hold** unless the Gemini tier check shows pressure (conflict 4).
4. **Claim/warrant implementation start** (Andrew-gated on the two #324 tunables): the actual fix
   for false records; deterministic claim-to-text validation gradually displaces LLM checking.

### P3 — evaluation harness (before any taste-bearing experiment)

Frozen replay corpus: approved + rejected drafts, human edits + rejection reasons, every signal
family, the false-precipitation-record incident, forecast-tense and evidence-grade cases, known
template/voice failures. Cutover gates for any future experiment (prompt compilation, Haiku
tiering, Sonnet 5 challenger): zero severe factual defects; blind human preference ≥ baseline;
approval rate, drafts/day, edit distance, template similarity no worse; cost ≤ budget two
consecutive weeks. Any false record or evidence-grade/tense breach ⇒ immediate rollback.

**Held levers (not in the plan, documented for the day they're wanted):** Haiku-for-routine
tiering via the pre-writer editorial score (→ ~$5–7/mo; taste-gated dryrun A/B). Sonnet 5 writer
challenger — intro $2/$10 ends **2026-08-31** and its tokenizer is ~30% heavier, so post-intro it's
*more* expensive per request than 4.6 at equal text: a quality challenger only, evaluated on the
P3 corpus if at all. Per-signal prompt compilation (adherence experiment, P3-gated). Local/Ollama:
rejected for prod (self-hosted runner on a public repo = fork-PR RCE per GitHub's own docs; Ollama
ships no auth; shelf knowledge in PLAN-25-PERCENT.md appendix).

## 4. Arithmetic (verified constants; honest ranges)

Constants: 15.1k-token cached system prompt; Sonnet 4.6 $3/$15, write $3.75/M, read $0.30/M,
batch ×0.5 on everything; Haiku 4.5 $1/$5.

| Stage | Writer | Regression | Self-heal | **Total/mo** | vs today |
|---|---|---|---|---|---|
| Today (corrected) | $15–25 | ~$30 | $5–15 | **$50–70** | 100% |
| After P0 | $13–16 | $4–6 (canary + weekly + PR runs) | <$1 | **~$18–23** | ~30–35% |
| After P0+P1 | $13–16 | $4–6 | <$1 | **~$18–22** | ~30% (P1 is hygiene, not dollars) |
| **After P2 (batch)** | **$7–12** | $3–4 (weekly batched) | <$1 | **~$11–17** | **~17–25%** ✅ |
| + held tiering lever | $3–5 | $3–4 | <$1 | ~$7–9 | ~11–13% |

The P2 writer range is wide honestly: batch **with** healthy cache hits ≈ $7–9/mo; batch with poor
in-batch cache locality ≈ $11–12/mo (uncached-batched 15.1k × $1.50/M ≈ $0.023/call). Mid-case
lands **~$11–14/mo ≈ 18–22%** — inside the 20%+5% budget; worst case ~25% still meets the mandate,
and the ledger (P0/P1) measures which case we're in before anyone reaches for the held levers.

## 5. Quality — same or better, argued

The published voice is untouched: same model, same prompt, same honesty gates, and the
manual-review relationship unchanged. Four things get *better*: (1) the regression suite stops
firing blind at 9am and starts **blocking the exact PRs** that can break the voice; (2) the
billing-outage failure mode gets a loud daily tripwire instead of silence; (3) a dead
foreign-register rewriter with kill power is removed from the codebase; (4) cost becomes a
dashboard metric with alerts, ending the stale-comment era ("$6/month", "~5,700 tokens",
"$25–45/mo" — all measured wrong this session). The one watched risk: REVISE verdicts become kills
at samples=1 — funnel telemetry watches drafts/day with an explicit re-enable trigger (P0.1).

## 6. Risks & rollbacks

| Change | Risk | Rollback |
|---|---|---|
| samples 1 + revise 0 | fewer approved drafts/day (supply is the known bottleneck) | two `gh variable set` calls; re-enable revise first |
| PR-gated suite | prompt regression slips via an unexpected path | canary + weekly full run still sweep; add paths |
| Self-heal gate | preflight misses a red class | `workflow_dispatch` unchanged; revert yml |
| Batch lane | latency tail (≤24 h worst case), in-batch cache misses | freshness guard; sync path retained; flag to revert |
| Breaker | false-positive abort on transient 400 | matches only the observed billing string (same pattern list as `retry.py`) |

## 7. Andrew-gated (nothing here starts without explicit words)

1. Credits top-up + auto-reload + cap (**the urgent thing**, unchanged).
2. Console usage-by-key: confirm the measured ledger and whether **Vital bills this account**.
3. **aistudio.google.com**: Gemini tier for the bot's key (decides conflict 4; free Pro ≈ 50/day).
4. PR #324 claim/warrant tunables (unlocks P2.4).
5. Held levers (tiering, Sonnet 5 challenger, prompt compilation) stay OFF.

## 8. Paste-ready kickoff (green-lights P0 + P1)

> Pick up @theheat. Execute the economics master plan —
> `docs/superpowers/plans/economics/PLAN-ECONOMICS-MASTER-v3.md` — P0 then P1, under the standing
> rules in `docs/handoffs/2026-07-13-next-session.md`. P0.1's two flags flip together in one step.
> Show me the funnel/drafts-per-day readout after 48h of P0 before starting P2.
