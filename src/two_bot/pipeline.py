"""Stage orchestration for the two-bot pipeline."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import os
from typing import Any

from src import config
from src.data.firms import FireEvent
from src.state_schema import BotState
from src.two_bot import critic, fact_check, memory, writer
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern import build_fire_bundle
from src.two_bot.retry import BudgetExhaustedError
from src.two_bot.types import FactCheckResult, MemorySlice, StoryBundle, WriterResult
from src.voice.safety import run_safety_pipeline


_FORBIDDEN_CLAIM_SIGNAL_KINDS = ("regional_anomaly", "heat_records_cluster")


def _forbidden_claim_violation(tweet: str, bundle: StoryBundle) -> str | None:
    """§F deterministic honesty gate (Layer 0) for bundles carrying a curated
    ``historical_context.forbidden_claims`` denylist.

    For ``regional_anomaly`` this catches bare-region / national / area-weighted
    framings (see build_regional_anomaly_bundle). For ``heat_records_cluster`` (#414)
    it blocks single-cause synoptic attributions ("heat dome", blocking ridge, …) —
    the bundle proves clustered records, not their cause. Rejects any draft whose
    text contains a forbidden substring (case-insensitive). This is the LOAD-BEARING
    honesty layer; the writer prompt + fact-check + safety regex are backstops.
    Returns the matched phrase, or None when clean / not a guarded signal_kind.
    """
    if bundle.signal_kind not in _FORBIDDEN_CLAIM_SIGNAL_KINDS:
        return None
    # Normalize Unicode curly apostrophes to straight before matching: the writer
    # is Gemini, which routinely emits U+2019, and the possessive forbidden_claims
    # ("{region}'s average") use a straight apostrophe — so a curly-apostrophe
    # draft would otherwise EVADE this load-bearing gate. (safety.py:137 learned
    # the same lesson for date phrasing.)
    low = tweet.lower().replace("’", "'").replace("‘", "'")
    for phrase in bundle.historical_context.get("forbidden_claims", []):
        if phrase and phrase.lower() in low:
            return phrase
    return None


# Phase D deterministic cross-signal honesty gate (Layer 0). related_signals carry
# only verified FACTS, never a verifiable RELATION — so a draft that was handed
# them may enumerate ("the same week, X and Y") but must not assert causation, a
# shared cause/system, a trend, or that they're two expressions of one thing. The
# fact-checker is deliberately permissive ("when in doubt, ACCEPT"), so this CODE
# gate is the load-bearing FIRST layer of the protection (codex must-fix #1),
# backstopped at activation by the F3 critic ("default to KILL") and the
# voice-regression gate (see the activation runbook). The list is intentionally
# broad — causal/synthesis word STEMS, substring-matched — because a false kill of
# a multi-signal draft is the safe direction vs an unverifiable claim shipping, and
# the only allowed cross-signal form (bare enumeration) uses none of these. A
# substring denylist can never be paraphrase-complete; that residual is what the
# critic + voice-regression cover. ``co2``/``ch4``/global kinds never reach this
# gate (they're excluded from windowing), so stems like "fuel" won't false-kill a
# "fossil fuel" emissions tweet.
_CROSS_SIGNAL_BANNED_PHRASES: tuple[str, ...] = (
    # explicit pattern / causation framing
    "global pattern", "broader pattern", "larger pattern", "pattern of",
    "fingerprint", "signature of",
    "driven by", "driving", "driver", "driven", "drives",
    "fuel", "feeding", "feeds the", "feed the",
    "caused by", "causing", "the cause", "common cause", "root cause",
    "because of", "due to", "result of", "resulting from", "stems from",
    "stem from", "leads to", "leading to", "behind the", "behind both",
    "behind these", "trigger", "stok",
    # connection / correlation
    "linked", "link between", "connected", "connection between", "tied to",
    "tied together", "tie to", "correlat", "relationship between", "in common",
    "share a", "shares a", "share the same", "common thread", "common root",
    "interconnect", "all connected", "no coincidence", "not a coincidence",
    "not coincidental", "no accident", "not by chance",
    # amplification / compounding / worsening
    "amplif", "intensif", "exacerbat", "worsen", "worse", "compound",
    "accelerat", "magnif", "supercharg", "turbocharg",
    # systemic / trend / shared-expression framing
    "trend", "systemic", "same system", "same conditions", "same forces",
    "same story", "same root", "same driver", "feedback", "cascade",
    "ripple effect", "knock-on", "expression of", "expressions of",
    "manifestation", "symptom of", "symptoms of", "two sides of", "two faces of",
    "shared cause", "converg", "part of a", "part of the same",
)


def _cross_signal_violation(tweet: str, bundle: StoryBundle) -> str | None:
    """Reject a causal / shared-system / "global pattern" framing in a draft that
    was handed ``related_signals``. Only fires when related_signals are present, so
    single-event drafts are never affected (flag OFF == today). Bare enumeration of
    the related facts is allowed. Returns the matched phrase, or None when clean /
    no related signals. Curly apostrophes normalized (cf. _forbidden_claim_violation).
    """
    if not getattr(bundle, "related_signals", None):
        return None
    low = tweet.lower().replace("’", "'").replace("‘", "'")
    for phrase in _CROSS_SIGNAL_BANNED_PHRASES:
        if phrase in low:
            return phrase
    return None


def _critic_enabled() -> bool:
    """Operations kill-switch for the critic stage.

    Defaults to enabled. Set ``THEHEAT_CRITIC_ENABLED=0`` (or
    ``false``/``off``/``no``) to skip the critic without touching the
    code path — useful if the critic ever starts over-killing drafts
    in production and we need to triage without a deploy.
    """

    raw = os.environ.get("THEHEAT_CRITIC_ENABLED", "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _writer_samples() -> int:
    try:
        return max(1, int(os.environ.get("THEHEAT_WRITER_SAMPLES", str(config.WRITER_SAMPLES))))
    except ValueError:
        return config.WRITER_SAMPLES


def _critic_revise_enabled() -> bool:
    raw = os.environ.get("THEHEAT_CRITIC_REVISE_ENABLED")
    if raw is None:
        return config.CRITIC_REVISE_ENABLED
    return raw.strip().lower() in {"1", "true", "on", "yes"}


def _revision_constraint(previous_tweet: str, revise_instruction: str) -> str:
    return (
        f"Previous draft: {previous_tweet}\n"
        f"The critic requires: {revise_instruction}"
    )


def _audit_bundle_for_generation(
    bundle: StoryBundle,
    *,
    record_kill: Callable[[str, str], None] | None = None,
    prefix: str = "",
) -> bool:
    audit = audit_story_bundle(bundle)
    warning_codes = [issue.code for issue in audit.issues if issue.severity == "warning"]
    if warning_codes:
        print(
            f"[two_bot.pipeline] {prefix}Evidence warnings "
            f"({bundle.signal_kind}): {', '.join(warning_codes)}"
        )

    if audit.prompt_ready:
        return True

    error_codes = [issue.code for issue in audit.issues if issue.severity == "error"]
    reason = ", ".join(error_codes) or "unknown"
    print(
        f"[two_bot.pipeline] {prefix}Evidence contract rejected "
        f"{bundle.signal_kind} draft: {reason}"
    )
    if record_kill is not None:
        record_kill("evidence_contract", reason)
    return False


def _writer_sample_slate(
    bundle: StoryBundle,
    memory_slice: MemorySlice,
    samples: int,
) -> list[WriterResult]:
    if samples <= 1:
        return [writer.write_tweet(bundle, memory_slice)]
    with ThreadPoolExecutor(max_workers=samples) as executor:
        futures = [
            executor.submit(writer.write_tweet, bundle, memory_slice)
            for _ in range(samples)
        ]
        return [future.result() for future in futures]


def _check_safety_honesty_fact(
    tweet: str,
    bundle: StoryBundle,
    state: BotState,
    *,
    record_kill: Callable[[str, str], None],
    mark_stage: Callable[[str, str], None] | None = None,
) -> FactCheckResult | None:
    safety_passed, safety_reason = run_safety_pipeline(tweet)
    if not safety_passed:
        print(
            f"[two_bot.pipeline] Safety rejected {bundle.signal_kind} "
            f"draft: {safety_reason}"
        )
        record_kill("safety", safety_reason or "unknown")
        return None

    forbidden_hit = _forbidden_claim_violation(tweet, bundle)
    if forbidden_hit is not None:
        print(
            f"[two_bot.pipeline] Honesty gate rejected {bundle.signal_kind} "
            f"draft: forbidden claim {forbidden_hit!r}"
        )
        record_kill("honesty_gate", f"forbidden claim: {forbidden_hit!r}")
        return None

    cross_signal_hit = _cross_signal_violation(tweet, bundle)
    if cross_signal_hit is not None:
        print(
            f"[two_bot.pipeline] Cross-signal honesty gate rejected "
            f"{bundle.signal_kind} draft: {cross_signal_hit!r}"
        )
        record_kill("cross_signal", f"unverifiable cross-signal claim: {cross_signal_hit!r}")
        return None

    fact_result = fact_check.fact_check(tweet, [], bundle, state)
    if not fact_result.passed:
        failures_str = "; ".join(fact_result.failures)
        print(
            f"[two_bot.pipeline] Fact-check rejected {bundle.signal_kind} "
            f"draft: {failures_str}"
        )
        if mark_stage is not None:
            mark_stage("fact_check", "kill")
        record_kill("fact_check", failures_str or "unknown")
        return None
    if mark_stage is not None:
        mark_stage("fact_check", "pass")
    return fact_result


def generate_draft(
    bundle: StoryBundle,
    state: BotState,
    *,
    result_out: dict | None = None,
) -> dict | None:
    """Run the full pipeline (writer → claim extract → fact-check) and
    return a save_draft-ready dict. Publish memory is recorded only after
    successful posting. Returns a save_draft-ready dict, or
    ``None`` if the writer kills, fact-check rejects, or anything raises.

    Signal-agnostic. The bundle's ``signal_kind`` carries the type
    forward so the writer can dispatch on it. Used by every live signal
    type that has a bundle builder; raw signal types still go through
    the voice generator until they get builders.

    Returns:
        ``{"text": str, "event_id": str, "type": str, "two_bot_metadata": dict}``
        on success. None otherwise.

    If ``result_out`` is provided, on every None-return path it will be
    populated with ``{"kill_stage": str, "kill_reason": str}`` so callers
    can record a suppression with the actual cause. Without this hook
    pipeline errors are visible only in stdout — invisible to the
    dashboard. (Found 2026-05-07: GHCN bundles dying with
    ``Object of type date is not JSON serializable`` for ~13 hours
    before anyone noticed, because the catch-all swallowed the stack.)

    Never raises.
    """

    # Phase A funnel telemetry: per-candidate terminal pass|kill per stage.
    # REVISE re-runs overwrite a stage's outcome (terminal wins), so each
    # stage counts a candidate once. Mirrored into result_out for the drain.
    stage_outcomes: dict[str, str] = {}

    def _record_kill(stage: str, reason: str) -> None:
        if result_out is not None:
            result_out["kill_stage"] = stage
            result_out["kill_reason"] = reason

    def _mark_stage(stage: str, outcome: str) -> None:
        stage_outcomes[stage] = outcome
        if result_out is not None:
            result_out["stage_outcomes"] = stage_outcomes

    try:
        if not _audit_bundle_for_generation(bundle, record_kill=_record_kill):
            return None

        memory_slice = memory.build_memory_slice(state, bundle)
        samples = _writer_samples()
        writer_results = _writer_sample_slate(bundle, memory_slice, samples)
        viable_results = [result for result in writer_results if result.tweet is not None]
        if not viable_results:
            kill_reasons = [
                result.kill_reason or "unknown"
                for result in writer_results
            ]
            reason = "all writer samples killed: " + "; ".join(kill_reasons)
            print(f"[two_bot.pipeline] Writer killed {bundle.signal_kind} draft: {reason}")
            _mark_stage("writer", "kill")
            _record_kill("writer", reason)
            return None
        _mark_stage("writer", "pass")

        writer_result = viable_results[0]
        slate_critic_result = None
        if samples > 1 and _critic_enabled():
            candidate_texts = [result.tweet for result in viable_results if result.tweet is not None]
            slate_critic_result = critic.critic_select_slate(
                candidate_texts,
                bundle,
                state,
                shipped_recent=memory_slice.shipped_tweet_texts[:10],
            )
            if not slate_critic_result.passed:
                print(
                    f"[two_bot.pipeline] Critic rejected {bundle.signal_kind} "
                    f"slate: {slate_critic_result.kill_reason}"
                )
                _mark_stage("critic", "kill")
                _record_kill("critic", slate_critic_result.kill_reason or "unknown")
                return None
            _mark_stage("critic", "pass")
            selected_index = slate_critic_result.selected_index or 0
            writer_result = viable_results[selected_index]

        assert writer_result.tweet is not None
        fact_result = _check_safety_honesty_fact(
            writer_result.tweet,
            bundle,
            state,
            record_kill=_record_kill,
            mark_stage=_mark_stage,
        )
        if fact_result is None:
            return None

        # Stage 5: editorial critic — final gate before the draft reaches
        # the human-approval queue. In multi-sample mode the slate critic
        # already selected the strongest candidate before safety/fact-check.
        critic_result = None
        if _critic_enabled() and slate_critic_result is None:
            shipped_recent = memory_slice.shipped_tweet_texts[:10]
            revise_enabled = _critic_revise_enabled()
            critic_result = critic.critic_review(
                writer_result.tweet,
                bundle,
                state,
                shipped_recent=shipped_recent,
                allow_revise=revise_enabled,
            )
            if critic_result.verdict == "REVISE":
                if not revise_enabled:
                    _record_kill("critic", "critic returned REVISE while revise is disabled")
                    return None
                assert critic_result.revise_instruction is not None
                revised = writer.write_tweet(
                    bundle,
                    memory_slice,
                    revision_constraint=_revision_constraint(
                        writer_result.tweet,
                        critic_result.revise_instruction,
                    ),
                )
                if revised.tweet is None:
                    print(
                        f"[two_bot.pipeline] Revision writer killed "
                        f"{bundle.signal_kind} draft: {revised.kill_reason}"
                    )
                    # Terminal outcome is a writer kill — overwrite the earlier
                    # writer pass so the candidate isn't double-counted.
                    _mark_stage("writer", "kill")
                    _record_kill("writer", revised.kill_reason or "unknown")
                    return None
                revised_tweet = revised.tweet
                writer_result = revised
                fact_result = _check_safety_honesty_fact(
                    revised_tweet,
                    bundle,
                    state,
                    record_kill=_record_kill,
                    mark_stage=_mark_stage,
                )
                if fact_result is None:
                    return None
                critic_result = critic.critic_review(
                    revised_tweet,
                    bundle,
                    state,
                    shipped_recent=shipped_recent,
                    allow_revise=False,
                )
            if not critic_result.passed:
                print(
                    f"[two_bot.pipeline] Critic rejected {bundle.signal_kind} "
                    f"draft: {critic_result.kill_reason}"
                )
                _mark_stage("critic", "kill")
                _record_kill("critic", critic_result.kill_reason or "unknown")
                return None
            _mark_stage("critic", "pass")

        metadata: dict[str, Any] = {
            "signal_kind": bundle.signal_kind,
            "angle_chosen": writer_result.angle_chosen,
            "era_anchor_used": writer_result.era_anchor_used,
            "peer_comparison_used": writer_result.peer_comparison_used,
            "reasoning": writer_result.reasoning,
            "fact_check": fact_result.to_dict(),
            "bundle": memory.bundle_memory_snapshot(bundle),
            "writer_model": writer.WRITER_MODEL,
            "fact_checker_model": fact_check.FACT_CHECKER_MODEL,
        }
        # Bet A (A1): carry the offered impact facts + the writer's citation
        # self-report into review_context, where save_draft's decision-4 gate
        # (forced manual_only) and the dashboard reviewer read them.
        human_impact = getattr(bundle, "human_impact", None)
        if human_impact:
            metadata["human_impact"] = human_impact
            metadata["cited_impact"] = writer_result.cited_impact
        if critic_result is not None:
            metadata["critic"] = critic_result.to_dict()
            metadata["critic_model"] = critic.CRITIC_MODEL
        elif slate_critic_result is not None:
            metadata["critic"] = slate_critic_result.to_dict()
            metadata["critic_model"] = critic.CRITIC_MODEL
        return {
            "type": bundle.signal_kind,
            "text": writer_result.tweet,
            "event_id": bundle.event_id,
            "two_bot_metadata": metadata,
        }
    except BudgetExhaustedError as exc:
        print(
            f"[two_bot.pipeline] Budget exhausted ({bundle.signal_kind}): {exc}"
        )
        _record_kill("budget_exhausted", str(exc))
        return None
    except Exception as exc:
        print(
            f"[two_bot.pipeline] Pipeline error ({bundle.signal_kind}): {exc}"
        )
        _record_kill("pipeline_error", f"{type(exc).__name__}: {exc}")
        return None


def generate_fire_draft(
    fire: FireEvent,
    state: BotState,
    *,
    result_out: dict | None = None,
) -> dict | None:
    """Convenience wrapper: build a fire bundle and run the live pipeline.

    Kept for backwards-compat with main.py's existing fire integration.
    The ``"type"`` field is forced to ``"fire"`` for compatibility with
    the dashboard and existing draft-saving logic.
    """

    bundle = build_fire_bundle(fire)
    draft = generate_draft(bundle, state, result_out=result_out)
    if draft is not None:
        # Preserve the legacy "fire" type tag instead of "fire" coming
        # from bundle.signal_kind (which is already "fire", but be
        # explicit for any future bundle.signal_kind divergence).
        draft["type"] = "fire"
    return draft


def generate_shadow_draft(bundle: StoryBundle, state: BotState) -> dict | None:
    """Run the writer + fact-check stages WITHOUT recording memory.

    Used for the shadow A/B experiment: the live tweet is still produced by
    the voice generator and posted; this output is stored alongside it for
    side-by-side review.

    Returns ``{"text": str, "two_bot_metadata": dict}`` on success, or
    ``None`` if the writer kills, fact-check rejects, or any error occurs.
    Never raises.

    Critically, this does NOT call ``memory.record_shipped`` — the shadow
    tweet is not actually shipped, so writing it into the memory layer
    would corrupt the banned-reuse list with text the audience never saw.
    Memory is read (so the writer sees the real banned list) but not
    written.
    """

    try:
        if not _audit_bundle_for_generation(bundle, prefix="Shadow "):
            return None

        memory_slice = memory.build_memory_slice(state, bundle)
        writer_result = writer.write_tweet(bundle, memory_slice)
        if writer_result.tweet is None:
            print(
                f"[two_bot.pipeline] Shadow writer killed "
                f"{bundle.signal_kind} draft: {writer_result.kill_reason}"
            )
            return None

        safety_passed, safety_reason = run_safety_pipeline(writer_result.tweet)
        if not safety_passed:
            print(
                f"[two_bot.pipeline] Shadow safety rejected "
                f"{bundle.signal_kind} draft: {safety_reason}"
            )
            return None

        forbidden_hit = _forbidden_claim_violation(writer_result.tweet, bundle)
        if forbidden_hit is not None:
            print(
                f"[two_bot.pipeline] Shadow honesty gate rejected "
                f"{bundle.signal_kind} draft: forbidden claim {forbidden_hit!r}"
            )
            return None

        fact_result = fact_check.fact_check(
            writer_result.tweet, [], bundle, state
        )
        if not fact_result.passed:
            print(
                f"[two_bot.pipeline] Shadow fact-check rejected "
                f"{bundle.signal_kind} draft: " + "; ".join(fact_result.failures)
            )
            return None

        return {
            "text": writer_result.tweet,
            "two_bot_metadata": {
                "signal_kind": bundle.signal_kind,
                "angle_chosen": writer_result.angle_chosen,
                "era_anchor_used": writer_result.era_anchor_used,
                "peer_comparison_used": writer_result.peer_comparison_used,
                "reasoning": writer_result.reasoning,
                "fact_check": fact_result.to_dict(),
                "writer_model": writer.WRITER_MODEL,
                "fact_checker_model": fact_check.FACT_CHECKER_MODEL,
            },
        }
    except Exception as exc:
        print(
            f"[two_bot.pipeline] Shadow pipeline error "
            f"({bundle.signal_kind}): {exc}"
        )
        return None
