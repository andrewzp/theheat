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
