# The 25% plan — theheat API-cost redesign

> **Mandate (Andrew, 2026-07-13):** Claude stays the writer. Everything else can move. Quality same
> or better. Cost ≤ 25% of today. Today ≈ **$53–73/month** (measured); target ≤ **$13–18/month**;
> this plan lands at **~$9–12/month (~15–18%)**.
> Context: the Anthropic balance hit $0 on 2026-07-11 and production drafting silently stopped
> (bot.yml stays green on writer failures — see the `reference_theheat_drafting_health` memory).
> Full research (market pricing, local/Ollama landscape) was live-sourced 2026-07-13; decision-
> relevant subset inlined below.

## 1. The measured ledger (what actually burns credits)

All Anthropic-billed. Writer/evaluator = `claude-sonnet-4-6` ($3/$15 per MTok); writer caches its
15.1k-token system prompt (write $3.75/M per warm-up, read $0.30/M, 5-min TTL). Fact-check
(`gemini-2.5-flash`) + critic (`gemini-2.5-pro`) bill to Google — presumed free tier (unconfirmed).

| # | Consumer | Cadence | Volume | ≈ $/month |
|---|---|---|---|---|
| 1 | voice-regression: 40 live writer replays (`tests/voice_regression/`) | nightly 09:00 UTC since #61 (May 9) | 40 calls/day | **~$30** |
| 2 | bot writer (`src/two_bot/writer.py`) | ~5–6 full cycles/day | ~5 successes/day + kills, ×2 (`THEHEAT_WRITER_SAMPLES=2` since Jun 13) | **~$15–25** |
| 3 | workflow-self-heal: full Claude Code agent (`claude-code-action@v1`, model unpinned, `--max-turns 40`) | daily 13:00 UTC, runs even when all green | 1 session/day | **~$5–15** |
| 4 | virality evaluator (`src/editorial/evaluator.py`, Sonnet, uncached) | per draft | ~5 calls/day | **~$3** |
| 5 | dryrun harnesses | manual only | ~0 | ~0 |

Two structural facts: **the test suite outspends the product ~2:1** (production is ~5 drafts/day;
the nightly suite is 40 — its own header costed it at "$6/month", a 5× stale underestimate), and
**cache re-warms dominate writer cost at our volume** (~6 × $0.057/day ≈ $10/month just re-writing
the prompt into the 5-minute cache each cycle, because cycles are hours apart).

## 2. Ideas considered — verdicts

- ✅ **Event-driven voice-regression** — the nightly `schedule:` is a category error; the suite's
  purpose is catching prompt/model changes, and `workflow_dispatch` + the `voice-check` PR label
  already exist. Gate PRs touching `src/two_bot/prompts/**` + `writer.py`; add a weekly 10-bundle
  canary for environmental drift. Quality UP (blocks the offending PR instead of reporting the
  morning after). Saves ~$26–29/mo.
- ✅ **Gate + pin self-heal** — keyless bash pre-check job (`gh run list` red-count) gates the
  agent job; pin `--model claude-haiku-4-5` (it triages workflows; never writes voice). ~$5–14/mo.
- ✅ **Samples 2→1** — best-of-2 doubles spend to discard half; selection already exists downstream
  (F3 critic + manual review). Upgrade path if quality dips: adaptive re-roll (second sample only
  when the critic scores marginal). ~$8–12/mo.
- ✅ **Batch API for the writer** — drafts wait hours for human review; batches are 50% off and
  kill the cache-rewarm floor. Submit in the draft step; the existing hourly cron collects, then
  fact-check/critic run as today. The one real plumbing item (~1 session). Halves remaining writer
  cost.
- ✅ **Token-usage ledger** — writer/evaluator responses already return exact `usage`; accumulate
  per-day tokens in state, show `$ est. this month` on the dashboard + weekly sentinel line. Cost
  drift becomes visible forever.
- ✅ **Billing guardrails** — Console auto-reload + monthly cap + alerts (Andrew).
- ✅ **Delete (or demote) the evaluator** — a second Sonnet pass rewriting the writer's tweet
  against a *virality* rubric ("scroll-stopping opener, awe"); predates the F3 critic and the
  one-house-voice program and is in tension with it. Instrument one week (rewrite rate + diffs),
  then delete unless the data defends it. Removes the last non-house rewriter from the publication
  path — likely a quality WIN. ~$3/mo.
- 🧪 **Haiku-for-routine tiering** (option, Andrew-gated, not in core plan) — route routine signals
  to Haiku 4.5, keep Sonnet for high-significance (the pre-writer editorial score is the router).
  Only if <$5/mo is ever wanted; dryrun A/B + Andrew's read required.
- ❌ **Writer to Gemini/local** — mandate: Claude writes. Also: critic is already Gemini Pro;
  same-family writer+critic would weaken the independent-check design.
- ❌ **Per-signal prompt slicing** — looks like a 2× input win; cache math says otherwise at our
  volume (fragments one 15k warm-up into several per-kind 8k warm-ups; can cost MORE), and it adds
  an assembly seam to the most taste-sensitive file in the repo. Revisit only if the prompt doubles.
- ❌ **Local Ollama in prod** — GitHub's own docs: self-hosted runners on public repos are a
  fork-PR RCE path; tunnels couple prod to home uptime and Ollama has no built-in auth. With the
  writer staying Claude, local chases ~$3/mo. Shelf knowledge preserved below.
- ❌ **Fewer bot cycles** — saves re-warms but trades timeliness on a real-time account whose known
  bottleneck is editorial supply. Batches fix the same dollars without the coverage loss.

## 3. The plan

**P0 — no quality surface (config/workflow, ~1 session):**
1. voice-regression → PR-gated (`on: pull_request paths:` prompts/writer) + weekly 10-bundle canary; delete nightly cron.
2. self-heal → keyless red-check gate job + `--model claude-haiku-4-5` pin.
3. `gh variable set THEHEAT_WRITER_SAMPLES --body 1`.
4. Usage ledger in state + dashboard/sentinel cost line.
5. Console auto-reload + cap + alerts (**Andrew**).

**P1 — small code, quality-positive:** 6. evaluator: instrument → delete (keep the instrumentation PR separate from the delete PR).

**P2 — one focused session:** 7. Batch API for the writer path (pending-batch state + collect step in the hourly cron).

**Optional (Andrew-gated):** Haiku-for-routine tiering.

## 4. Arithmetic

| Stage | Writer | Regression | Self-heal | Evaluator | **Total/mo** | vs today |
|---|---|---|---|---|---|---|
| Today | $15–25 | $30 | $5–15 | $3 | **$53–73** | 100% |
| After P0 | $15–17 | ~$2 | <$1 | $3 | **~$20–23** | ~33% |
| After P0+P1 | $15–17 | ~$1–2 | <$1 | $0 | **~$17–19** | ~28% |
| **After P0+P1+P2** | **$7–9** | ~$1–2 | <$1 | $0 | **~$9–12** | **~15–18%** ✅ |
| + optional tiering | $3–5 | ~$1 | <$1 | $0 | ~$5–7 | ~9% |

## 5. Quality — same or better, argued

Published voice untouched (same model, prompt, gates). Regression protection strengthens (merge
gate instead of morning-after report). Evaluator removal deletes a conflicting register with
rewrite power over published copy. Honesty gates (§F, fact-check, critic) untouched. Cost becomes
a dashboard metric; every new scheduled workflow's PR must carry a `cost/run × cadence = $/month`
line (the stale "$6/month" header comment in voice-regression is how the drift went unseen).

## 6. Account checks (Andrew, ~5 min)

1. **platform.claude.com/settings/usage** — confirm the ledger above by key/day, and whether
   **Vital bills the same account** (if yes, its share is additional and untouched by this plan).
2. **aistudio.google.com** (rate-limit page for the bot's key) — Gemini free-tier limits are no
   longer published publicly; the F3 critic runs on Gemini **Pro** (free tier ≈ 50 req/day —
   fits today's ~5–10/day, little headroom; Google cut free quotas without notice in Dec 2025).

## Appendix — live-sourced research highlights (2026-07-13)

- Anthropic Batch API: 50% off, stacks with prompt caching (verified live) — P2's mechanics.
- Gemini 2.0 line hard-shutdown 2026-06-01; our roles are on 2.5 (unaffected; pin + watch).
- Contingency writer candidates if Claude were ever forced out (NOT the plan): DeepSeek v4-flash
  w/ caching ~$3/mo (China-hosted, ambiguous training policy), Gemini 2.5 Flash-Lite ~$5/mo,
  Groq paid ~$2/mo (8B quality risk). Traps: Cerebras free tier caps context at 8k (can't fit our
  prompt); OpenRouter free = evaluation tier; DeepSeek retires model names on ~3-month cycles.
- Local shelf (future hard-$0 card): Gemma 4 31B / Gemma 3 27B (cleanest JSON, no thinking-mode
  conflict), gpt-oss-20b (`reasoning_effort` dial), Qwen3.5-27B (top open IFEval). Ollama gotchas
  that would bite this workload: default `num_ctx` silently truncates a 15–20k system prompt from
  the front; JSON-schema `format` mode disables thinking tokens.
