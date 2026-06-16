# Phase D — Multi-Signal Writer Context

**Status:** Plan (light) · drafted 2026-06-16 · outside review pending
**Sequence:** A → B → C → D. This is **D** (last; biggest build, highest ceiling).
**Depends on:** A (measure A-rate proxy lift), B (ship the better drafts), C
(synthesis across a real slate).
**Process:** full `/brainstorm → /write-plan → /plan-eng-review + codex` before
code. Highest regression risk of the four.

## Problem

The critic demands Attenborough/Economist system-framing — *"take a precise data
point, place it inside the larger system that makes it matter"*
(`src/two_bot/prompts/critic_prompt.py:34`) — but the writer is handed a
**single-event** `StoryBundle` (`src/two_bot/types.py:9`). `synthesis.py` exists
but is narrow (fire×drought×heat, threshold 82, rarely fires). The "outstanding"
tweets in the thesis come from **connecting signals** (this heat + that Med SST
anomaly + that drought, same region/week). The input contract and the quality bar
are in direct tension: we ask for system-level framing and feed single data
points. This caps the A-rate at the source.

## Goal / Non-goals

**Goal:** give the writer **optional, verifiable** cross-signal context drawn from
the same cycle's other high-scoring events, so it can write synthesis-grade tweets
without unverifiable claims — raising the rate at which drafts clear the critic.

**Non-goals:** free-form "connect anything" (must stay fact-checkable); replacing
per-event drafts (this augments); loosening the fact-checker.

## Approach

1. **`related_signals: list[RelatedSignal]` (optional) on `StoryBundle`**
   (`src/two_bot/types.py`). Each `RelatedSignal` is itself bundle-grade fact —
   `event_id`, `type`, `where`, `headline_metric`, `when` — i.e. verifiable, not
   prose.

2. **Populate at drain time.** When assembling a candidate's bundle, attach the
   cycle's other top-scoring events within a spatial/temporal window (same
   country / radius, same N-day window) as `related_signals`. We already hold the
   whole triage queue at drain (`_drain_and_write_triage_queue`), so this is cheap
   and deterministic — no extra fetch.

3. **Writer prompt** (`src/two_bot/prompts/writer_prompt.py`): a section
   permitting the writer to reference the broader pattern using **only**
   `related_signals` facts ("the same week, X and Y" where X/Y are bundle-grade),
   never invented correlations. Headline metric stays bundle-sourced as today.

4. **Fact-check guard** (`src/two_bot/prompts/fact_check_prompt.py`):
   `related_signals` are bundle facts, so the exact-match contract already covers
   them. Add a rule: any cross-signal claim must map to a `related_signals` entry
   — no ungrounded "part of a global pattern."

5. **Evidence contract** (`src/two_bot/evidence_contract.py`): `related_signals`
   optional; absence is not an error (single-event drafts remain valid).

## Files touched

- `src/two_bot/types.py` — `StoryBundle.related_signals` + `RelatedSignal`.
- `src/two_bot/intern/_shared.py` — helper to assemble related signals.
- drain step / `two_bot_dispatch` — attach related signals from the cycle queue
  within window.
- `src/two_bot/prompts/writer_prompt.py` — synthesis section.
- `src/two_bot/prompts/fact_check_prompt.py` — cross-signal grounding guard.
- `src/two_bot/evidence_contract.py` — `related_signals` optional.
- tests + `tests/voice_regression/`.

## Test plan

- Unit: related signals attached only within the spatial/temporal window; writer
  can cite a related signal; fact-check **rejects** a cross-signal claim with no
  matching `related_signals` entry; absence leaves single-event behavior
  unchanged; evidence contract passes with empty `related_signals`.
- Voice-regression: replay the corpus to confirm no new template/voice failures;
  on a held-out set, Phase A's `critic_pass_rate` goes **up, not down**.

## Risks & rollback

**Highest of the four** — touches writer prompt + fact-check + evidence contract,
the machinery most likely to regress quality or admit unverifiable claims.
Mitigations: (1) flag `THEHEAT_MULTISIGNAL_CONTEXT` default OFF; (2)
`related_signals` strictly bundle-grade facts; (3) fact-check grounding guard;
(4) voice-regression gate before ship; (5) ship to a fraction of categories
first. **Rollback:** flag off → single-event behavior, **byte-identical writer
system prompt** (the cache prefix is preserved — related_signals ride in the user
prompt, not the cached system block — confirm during build).

## Open decisions (for reviewer + Andrew)

1. Window definition: same country? same ~500km? same 7 days? Needs a taste pass.
2. Max related signals per draft: 2–3 (avoid prompt bloat + cache churn).
3. Confirm `related_signals` in the user prompt does not break writer prompt-cache
   byte-stability (`tests/two_bot/test_writer_caching.py` asserts it).
4. Should the critic prompt explicitly *reward* earned synthesis, or just stop
   killing it? (Smaller, safer to start with the latter.)

## Hand-off / dependencies

Last in sequence. By the end, the system is the generate-many-then-select-best,
synthesis-capable engine the thesis describes: A measures, B ships, C generates
many, D makes them outstanding.

---

## Outside review — codex gpt-5.5 (2026-06-16): SHIP WITH CHANGES

"Relies too much on prompt-only grounding for the highest-risk part."

**Must-fix before building:**
1. **Add a DETERMINISTIC cross-signal honesty gate (code, not prompt).** The
   fact-checker is deliberately permissive ("When in doubt, ACCEPT",
   `fact_check_prompt.py:68`), so a prompt rule "must map to related_signals" won't
   hold. Mirror the existing regional-anomaly honesty gate (`pipeline.py:20`): allow
   bare enumeration ("same week, X and Y"); REJECT causal / trend / "global pattern"
   / "fingerprint" / shared-system claims unless a structured relation fact supports
   them.
2. **Define `RelatedSignal` + the window concretely.** Core bundle fields lack
   canonical country/lat/lon (`types.py:17`), so "same country / radius" needs geo
   fields added first. Pin the date source (`bundle.when` vs `tweet_date` vs
   `created_at`), radius fallback, max count, and exclusions for global /
   missing-coordinate signals.
3. **Cache/rollback caveat.** `related_signals` in `bundle.to_dict()` rides the USER
   prompt (fine, `writer.py:197`), but the plan also adds a synthesis section to
   `WRITER_SYSTEM_PROMPT` (`writer.py:118`) — that DOES change the cached prefix and
   the byte-identity test (`test_writer_caching.py:117`). Decide: keep all new
   guidance in the user prompt (cache preserved) or accept a one-time cache reset.

**What codex affirmed:** StoryBundle is the right surface (writer/fact-check/critic
all serialize it); optional `default_factory=list` keeps single-event behavior
intact; the flag posture is right — but only after the grounding gate + window are
structural.
