"""Type definitions for the two-bot pipeline."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RelatedSignal:
    """A bundle-grade fact about ANOTHER same-cycle event (Phase D).

    Attached to a StoryBundle so the writer can reference a *verifiable*
    cross-signal pattern. Carries only facts that already cleared the editorial
    gate for their own event — never prose, correlation, or causation.
    """

    event_id: str
    signal_kind: str
    where: str
    when: str
    headline_metric: dict[str, Any]
    country: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "signal_kind": self.signal_kind,
            "where": self.where,
            "when": self.when,
            "headline_metric": self.headline_metric,
            "country": self.country,
        }


@dataclass
class StoryBundle:
    """The intern's output. Pure facts; no editorial angles.

    First-build note (A1): ``historical_context`` is an empty dict in the
    first build. The full schema will be filled once real FIRMS distributions
    are computed in a follow-up PR.
    """

    signal_kind: str
    where: str
    when: str
    event_id: str
    headline_metric: dict[str, Any]
    current_facts: list[dict[str, Any]]
    historical_context: dict[str, Any] = field(default_factory=dict)
    raw_signal_dump: dict[str, Any] = field(default_factory=dict)
    # Phase D geo + cross-signal context. ``country`` is the canonical 2-letter
    # code used to window related signals (falls back to a current_facts entry
    # when a builder hasn't set it). ``related_signals`` rides in the USER prompt
    # via to_dict — never the cached WRITER_SYSTEM_PROMPT — so the prompt cache
    # is preserved and single-event behavior is byte-identical when empty.
    country: str = ""
    related_signals: list["RelatedSignal"] = field(default_factory=list)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "signal_kind": self.signal_kind,
            "where": self.where,
            "when": self.when,
            "event_id": self.event_id,
            "headline_metric": self.headline_metric,
            "current_facts": self.current_facts,
            "historical_context": self.historical_context,
            "raw_signal_dump": self.raw_signal_dump,
        }
        # Omit when empty so single-event bundles serialize byte-identically
        # (flag OFF / no related signals == today's user prompt).
        if self.country:
            data["country"] = self.country
        if self.related_signals:
            data["related_signals"] = [r.to_dict() for r in self.related_signals]
        return data


@dataclass
class MemorySlice:
    """The memory layer's contribution to the writer's context."""

    recent_tweets_same_country: list[str] = field(default_factory=list)
    recent_tweets_same_event: list[str] = field(default_factory=list)
    ongoing_event: dict | None = None
    used_era_anchors: list[str] = field(default_factory=list)
    used_peer_comparisons: list[str] = field(default_factory=list)
    used_framings: list[str] = field(default_factory=list)
    shipped_tweet_texts: list[str] = field(default_factory=list)
    recent_categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "recent_tweets_same_country": self.recent_tweets_same_country,
            "recent_tweets_same_event": self.recent_tweets_same_event,
            "ongoing_event": self.ongoing_event,
            "used_era_anchors": self.used_era_anchors,
            "used_peer_comparisons": self.used_peer_comparisons,
            "used_framings": self.used_framings,
            "shipped_tweet_texts": self.shipped_tweet_texts,
            "recent_categories": self.recent_categories,
        }


@dataclass
class WriterResult:
    """The writer's output."""

    tweet: str | None
    kill_reason: str | None
    angle_chosen: str
    era_anchor_used: str | None
    peer_comparison_used: str | None
    reasoning: str

    def __post_init__(self):
        if (self.tweet is None) == (self.kill_reason is None):
            raise ValueError(
                "WriterResult invariant violated: exactly one of tweet/kill_reason "
                "must be non-None"
            )

    def to_dict(self) -> dict:
        return {
            "tweet": self.tweet,
            "kill_reason": self.kill_reason,
            "angle_chosen": self.angle_chosen,
            "era_anchor_used": self.era_anchor_used,
            "peer_comparison_used": self.peer_comparison_used,
            "reasoning": self.reasoning,
        }


@dataclass
class ExtractedClaim:
    """One concrete claim extracted from tweet text by Stage 3.5."""

    text: str
    kind: str

    def to_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind}


@dataclass
class FactCheckResult:
    passed: bool
    failures: list[str]
    raw_response: str
    extracted_claims: list[ExtractedClaim] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failures": self.failures,
            "raw_response": self.raw_response,
            "extracted_claims": [c.to_dict() for c in self.extracted_claims],
        }


@dataclass(frozen=True)
class TriageCandidateBundle:
    """A scored bundle queued for the triage stage. Source runners build
    these and append to bot_state['_triage_queue']; the triage stage
    ranks/caps them and the survivors enter the writer pipeline.

    Carries all the arguments _try_two_bot_draft() needs so the writer
    call site stays unchanged.

    NOTE: This is distinct from src.editorial.candidates.CandidateBundle
    which is the voice-generator's multi-candidate evaluator type. This
    type is for the pre-LLM triage queue.
    """
    bundle: Any  # StoryBundle — use Any to avoid circular import
    score: Any   # EditorialScore — use Any to avoid circular import
    event_id: str
    source: str                 # source_key for telemetry
    review_context: dict        # for save_draft
    city: str                   # for city cooldown
    tweet_date: str             # for same-day dedup
    cooldown_exempt: bool       # for elite-signal bypass
    legacy_type: str            # for save_draft type field
    created_at: str             # iso8601 — used as triage tiebreaker
    draft_metadata: dict | None = None  # extra persisted draft fields
    # Optional zero-argument callable invoked by the drain step on successful
    # draft. Use for source-specific side effects that must only fire when a
    # draft actually ships (e.g. incrementing an annual count, updating a
    # last-seen tier). Defaults to None = no-op. NOT persisted (queue is
    # transient and never written to sqlite).
    on_draft_success: Callable[[], None] | None = None
    # Optional zero-argument predicate returning True when this candidate's annual
    # cap is already reached, re-evaluated against LIVE bot_state. The Phase C
    # refill loop calls it at admit time (after firing prior successes' callbacks
    # inline) so reaching deeper near a cap can't overshoot in-cycle — and it keys
    # the cap by the source's own logic (event-date year, per-index counter), which
    # a static legacy_type map can't. Defaults to None = uncapped.
    annual_cap_check: Callable[[], bool] | None = None


@dataclass
class CriticResult:
    """Second-pass editorial critic verdict.

    The critic runs after fact_check passes and acts as the final
    editorial gate before a draft enters the human-approval queue.
    Legacy construction stays PASS/KILL; S-22 adds optional REVISE and
    slate-selection metadata behind dark flags.
    """

    passed: bool
    kill_reason: str | None
    raw_response: str
    verdict: str = ""
    revise_instruction: str | None = None
    selected_index: int | None = None

    def __post_init__(self) -> None:
        if not self.verdict:
            self.verdict = "PASS" if self.passed else "KILL"
        self.verdict = self.verdict.upper()
        if self.verdict == "PASS":
            if not self.passed:
                raise ValueError(
                    "CriticResult invariant violated: PASS verdict requires passed=True"
                )
            if self.kill_reason is not None:
                raise ValueError(
                    "CriticResult invariant violated: kill_reason must be None when passed=True"
                )
            if self.revise_instruction is not None:
                raise ValueError(
                    "CriticResult invariant violated: revise_instruction must be None for PASS"
                )
            return
        if self.verdict == "KILL":
            if self.passed:
                raise ValueError(
                    "CriticResult invariant violated: KILL verdict requires passed=False"
                )
            if not self.kill_reason:
                raise ValueError(
                    "CriticResult invariant violated: kill_reason required when passed=False"
                )
            if self.revise_instruction is not None:
                raise ValueError(
                    "CriticResult invariant violated: revise_instruction must be None for KILL"
                )
            return
        if self.verdict == "REVISE":
            if self.passed:
                raise ValueError(
                    "CriticResult invariant violated: REVISE verdict requires passed=False"
                )
            if self.kill_reason is not None:
                raise ValueError(
                    "CriticResult invariant violated: kill_reason must be None for REVISE"
                )
            if not self.revise_instruction:
                raise ValueError(
                    "CriticResult invariant violated: revise_instruction required for REVISE"
                )
            if len(self.revise_instruction) > 200:
                raise ValueError(
                    "CriticResult invariant violated: revise_instruction exceeds 200 chars"
                )
            return
        raise ValueError(f"CriticResult invariant violated: unknown verdict {self.verdict!r}")

    def to_dict(self) -> dict:
        payload: dict[str, Any] = {
            "passed": self.passed,
            "kill_reason": self.kill_reason,
            "raw_response": self.raw_response,
            "verdict": self.verdict,
            "revise_instruction": self.revise_instruction,
        }
        if self.selected_index is not None:
            payload["selected_index"] = self.selected_index
        return payload
