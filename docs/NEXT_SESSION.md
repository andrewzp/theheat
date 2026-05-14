# Start-of-Session Brief

> **STALE — use [`NEXT_SESSION_PROMPT_2026-05-14-v2.md`](NEXT_SESSION_PROMPT_2026-05-14-v2.md) instead.**
>
> The current re-entry doc is the dated prompt above (written mid-session 2026-05-14 after the brand-kit-correction work). This file's body below is a snapshot from 2026-04-29 — preserved for historical context only, not for actual re-entry.
>
> Order of reads on a new session:
> 1. `docs/NEXT_SESSION_PROMPT_2026-05-14-v2.md` — current pointer with First-5-minutes orient block
> 2. `BRIEFING.md` (root) — full state of the project
> 3. `docs/SESSION_BRIEF.md` — recent sessions, newest at top

---

## Historical snapshot (2026-04-29)

**Written:** 2026-04-29 after voice engine v3 ship (era-anchor parking + addendum-mismatch fix + SYSTEM_PROMPT vehicle-agnostic rewrite).

**Status going in (at the time):** 566 tests green on `main`. Posting paused (Apr 12 was last post, deliberate quality pause). Pending queue: ask first — bulk-rejected after Apr 29 grading.

The historical content below is from before the two-bot writer + suppression ledger + Attenborough/Economist voice + writer guardrails landed. Do not treat as current state.

---

## 60-second state of the world

**Posting status:** PAUSED. Resumption bar (set 2026-04-26): majority A-grade rate per corpus cycle. Currently 0% (Apr 29, 0 of 3). Track in `docs/QUALITY_TREND.md`.

**Voice engine version:** v3, shipped 2026-04-29. Active changes:
- Era anchors PARKED at 1-in-10 via `_era_anchor_should_fire` deterministic gate. 90% of record drafts get explicit "parked, use other vehicles" steer-away message; 10% get curated content framed as "your 1-in-10 turn."
- Addendum-mismatch bug fixed (`all_time_record`/`monthly_record` categories now match `all_time_high/low` and `monthly_high/low` addendum keys, which had been dormant since they were written). Added missing `monthly_low`, `country_low`, `record_low` addenda.
- 5 record-type per-category addenda rewritten to use a shared 6-vehicle specificity menu (`_RECORD_SPECIFICITY_VEHICLES`). Era anchor is option 6, marked PARKED.
- SYSTEM_PROMPT #1 ("HISTORICAL WEIGHT") rewritten — was era-anchor-evangelizing, now lists all 6 specificity vehicles equally.
- 3 new bad-examples: explicit-gap math ("That gap is 4.5 degrees"), restate-padding, era-anchor-then-restate template.

**Data:** 613 cities × 179 countries with elevation. `data/era_anchors.json` curated 2026-04-26 to remove 43 political/US-centric/mass-tragedy entries (Trump, Brexit, Capitol riot, Hurricane Sandy, etc).

**Cost:** ~$30–55/mo total stack (Sonnet evaluator $25–45 + Gemini $5–10). The Gemini "free tier" claim was outdated; `gemini-flash-latest` aliases to a paid preview model. Pin `GEMINI_MODEL=gemini-2.5-flash` to return to free.

**Daily routine:** the recurring grader (`trig_016PGeHZgEYWmeQhx1xGmYg6`) fires every day at 15:00 UTC = 8 AM Pacific. Grades pending drafts, refines `docs/IMPROVEMENT_PLAN.md`, opens a PR. Plan-refinement-only — does NOT implement code/prompts. Human reviews, we implement together.

---

## First moves on a new session

### 1. Pull pending drafts (5 minutes)

```bash
curl -s https://api.github.com/gists/06c02c97ffc0d11458687f1ed998d9e5 \
  | python3 -c "
import json, sys
state = json.loads(json.load(sys.stdin)['files']['state.json']['content'])
for d in [d for d in state.get('drafts', []) if d.get('status') == 'pending']:
    print('---', d.get('type'), '---')
    print(d.get('text', ''))
    print()
"
```

The voice engine v3 changes will start showing in cycles after the Apr 29 commit pushed. Look for:
- **Era-anchor rate dropping.** Apr 25/27/29 corpora had 100% era-anchor deployment on records. v3 should drop that to ~10%. Empirical signal of whether the gate works.
- **Other specificity vehicles emerging.** Accelerating-warming framing, past-tense personification, place-as-punchline, absolute scale, ecosystem context. Variety is the goal.
- **Wodehouse violations holding or returning.** "That gap is X degrees" appeared in Apr 27 + Apr 29. New bad-example targets it; check whether it returns.

If new corpus needs grading: append to `docs/DRAFT_CORPUS.md` (newest at top).

### 2. Read the daily plan-refinement PR (if one's waiting)

The recurring agent fires at 15:00 UTC daily. Check open PRs on `github.com/andrewzp/theheat`. Refined `docs/IMPROVEMENT_PLAN.md` is the artifact.

### 3. Pick a direction

Open menu:

#### A. Implement next active proposal from IMPROVEMENT_PLAN.md
P1 (era anchors) is shipped, awaiting empirical confirmation. Next priorities by leverage:
- **P4** Wodehouse rule top-of-prompt — most predictive failure mode, observed across all corpus cycles. ~30 min.
- **P5** Stranded-mechanic warning in fire prompt — 3 drafts on Apr 27 had real moves stranded inside throat-clearing. ~15 min.
- **P6** Name humor moves as available tools (mostly done in v3 record addenda; could replicate for fire / anomaly / synthesis).
- **P2** / **P3** Widen plant-comparison + opener-formula regex — tactical. ~30 min total.

#### B. Two-bot architecture redesign (BIG, in flight)
User raised 2026-04-29: separate Data Organizer (gathers + structures signals into "story bundles") from Writer (takes bundles, writes voice). Cleaner than current Gemini-generates-then-Sonnet-rewrites. Started exploring; ready for full brainstorm + spec → plan → implement. See SESSION_BRIEF.md for context. This is bigger than P1-P6 — architectural.

#### C. Prompts inventory file
User asked for a single doc that lists all the bot's prompts (system + per-category + helpers + safety + evaluator) with content + locations. Half-built; abandoned mid-stride when the architectural conversation opened. Could finish for handoff before architecture redesign.

#### D. Cost optimization
Pin `GEMINI_MODEL=gemini-2.5-flash` in GitHub Actions secrets to drop ~$5–10/mo Gemini cost. ~5 min.

#### E. Fix `evaluator_pass=null` issue
Apr 29 drafts all had `evaluator_pass: null`. Either the evaluator isn't writing its verdict to draft state, or `EVALUATOR_ENABLED` got set false somewhere. Investigation, ~30 min.

---

## Invariants (do not break)

- **Utility, not business.** No follower / engagement optimization.
- **Set-and-forget.** No new human-in-the-loop layers.
- **Resumption bar.** Posting resumes when majority A-grade per cycle, sustained.
- **Honest framing.** Open-Meteo = 30 yrs, OISST = 44 yrs, GRACE = 24 yrs.
- **Extreme only.** Routine data isn't tweetable.
- **No press-release openers, no boilerplate, no meta-commentary.** Banned by safety pipeline + bad-examples.
- **Earned editorial heat allowed for elite signals only** (all-time, country, ≥18°C anomaly, ≥5-day streak). Mid-tier records get the quiet voice.
- **Sonnet evaluator stays on.** User said no Opus, no Haiku for now. `EVALUATOR_ENABLED=true`.
- **Sonnet-rewrite-bypass-of-_detect_stock_formula is intentional.** User confirmed 2026-04-27. Don't add the bypass.
- **Era anchors parked at 1-in-10.** Don't reach for them as the default. The gate enforces structurally.
- **Daily agent doesn't implement.** It refines `docs/IMPROVEMENT_PLAN.md` and opens PRs. Human + Claude implement together.

## Common commands

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
source .venv/bin/activate

python -m pytest tests/

gh run list --limit 5 --workflow=bot.yml

# Recent draft activity
curl -s https://api.github.com/gists/06c02c97ffc0d11458687f1ed998d9e5 | python3 -c "..."

# Override Gemini model
gh secret set GEMINI_MODEL  # paste e.g. gemini-2.5-flash to drop to free tier

# Kill the evaluator (drops Anthropic cost)
gh secret set EVALUATOR_ENABLED  # paste: false
```

## Open thread snapshots

- **Voice engine v3 just shipped.** Empirical verdict comes from next 3 cycles. Daily grader will track.
- **Two-bot architecture conversation pending.** Started 2026-04-29; brainstorm not yet held.
- **Prompts inventory file** half-built (the user asked for it; pivoted to architecture mid-stride).
- **`evaluator_pass=null` mystery** — all 3 Apr 29 drafts had no evaluator verdict. Worth investigating.
- **Cost docs reflect reality now** ($30–55/mo, not "$25–45/mo with Gemini free tier").
