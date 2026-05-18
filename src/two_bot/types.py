"""Type definitions for the two-bot pipeline."""

from dataclasses import dataclass, field
from typing import Any


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

    def to_dict(self) -> dict:
        return {
            "signal_kind": self.signal_kind,
            "where": self.where,
            "when": self.when,
            "event_id": self.event_id,
            "headline_metric": self.headline_metric,
            "current_facts": self.current_facts,
            "historical_context": self.historical_context,
            "raw_signal_dump": self.raw_signal_dump,
        }


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


@dataclass
class CriticResult:
    """Second-pass editorial critic verdict.

    The critic runs after fact_check passes and acts as the final
    editorial gate before a draft enters the human-approval queue.
    PASS/KILL only — no rewrite loop in v1.
    """

    passed: bool
    kill_reason: str | None
    raw_response: str

    def __post_init__(self) -> None:
        if self.passed and self.kill_reason is not None:
            raise ValueError(
                "CriticResult invariant violated: kill_reason must be None when passed=True"
            )
        if not self.passed and not self.kill_reason:
            raise ValueError(
                "CriticResult invariant violated: kill_reason required when passed=False"
            )

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "kill_reason": self.kill_reason,
            "raw_response": self.raw_response,
        }
