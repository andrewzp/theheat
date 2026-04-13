"""Virality evaluator — second inference pass via Claude Sonnet 4.6.

Takes the top-ranked tweet candidate, scores it on 5 virality dimensions
(awe, concrete comparison, social currency, scroll-stopping opener,
show-not-tell), and rewrites if it fails. Based on Berger & Milkman's
research: awe is 30% more likely to be shared; high-arousal emotion
drives sharing; concrete comparisons make numbers visceral.

Graceful degradation: any failure (API, parse, rate limit) returns the
original candidate unchanged.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from src.editorial.candidates import (
    CandidateBundle,
    CandidateScore,
    DraftCandidate,
    score_candidate_text,
)
from src.voice.safety import run_safety_pipeline

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EVALUATOR_MODEL = "claude-sonnet-4-6"

EVALUATOR_PROMPT = """\
You are a virality editor for @theheat, a climate data Twitter account.
You receive a tweet candidate and the raw data it was generated from.
Your job: evaluate whether this tweet will make someone stop scrolling and share it.

Score each dimension 0-10:

1. AWE (physical activation)
   Does this tweet create a gut reaction — not just "huh, interesting" but "wait, WHAT?"
   10 = jaw drop. 5 = mildly interesting. 0 = boring information dump.

2. CONCRETE COMPARISON
   Does the tweet anchor the number to something visceral the reader already understands?
   10 = "Category 5 starts at 157" (makes 178 mph land). "A power plant is 1,000 MW. \
Except it's a forest." 5 = number stated but no anchor. 0 = abstract statistic.

3. SOCIAL CURRENCY
   Would sharing this make someone look smart and informed, not preachy?
   10 = "Wait till you hear this" energy. 5 = informative but forgettable. 0 = lecturing.

4. SCROLL-STOPPING OPENER
   Do the first 5-7 words create surprise or pattern interruption?
   10 = "Anchorage recorded 82F today." (wait — Anchorage?). 5 = factual but expected \
opener. 0 = starts with agency name or boilerplate.

5. SHOW NOT TELL
   Does the tweet let the data speak, or does it add meta-commentary?
   10 = pure data + framing, no commentary. 0 = "THIS IS SERIOUS", "this is rare", \
"pay attention", "you should be worried".

RULES:
- A tweet PASSES if it scores 7+ on at least 4 of the 5 dimensions.
- A tweet FAILS if it scores below 5 on ANY dimension, or below 7 on 2+ dimensions.
- If the tweet FAILS, you MUST provide a rewrite that fixes the weak dimensions \
while keeping all facts accurate to the data provided.
- The rewrite MUST be under 280 characters.
- The rewrite MUST NOT contain emojis, hashtags, or exclamation points.
- The rewrite MUST NOT open with an agency name (NWS, NOAA, GDACS, etc.).
- The rewrite MUST NOT contain meta-commentary ("this is serious", "this is rare", etc.).

Respond in JSON only, no markdown fences:
{"passed": true/false, "scores": {"awe": N, "comparison": N, "social_currency": N, \
"opener": N, "show_not_tell": N}, "total": N, "failures": ["dimension_name", ...], \
"reasoning": "one sentence explaining the verdict", "rewrite": "improved tweet" or null}
"""


@dataclass(frozen=True)
class EvaluatorVerdict:
    passed: bool
    scores: dict[str, int]
    total: int
    failures: list[str]
    reasoning: str
    rewrite: str | None

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "scores": self.scores,
            "total": self.total,
            "failures": self.failures,
            "reasoning": self.reasoning,
            "rewrite": self.rewrite,
        }


def _passing_verdict() -> EvaluatorVerdict:
    """Default pass — used when the evaluator can't run."""
    return EvaluatorVerdict(
        passed=True,
        scores={},
        total=0,
        failures=[],
        reasoning="evaluator skipped",
        rewrite=None,
    )


def _verify_pass(scores: dict[str, int], model_said_passed: bool) -> bool:
    """Cross-check the model's verdict against its own scores.

    The model might hallucinate "passed: true" with scores of 3/2/4.
    Trust the numbers, not the label.
    """
    values = [v for v in scores.values() if isinstance(v, (int, float))]
    if not values:
        return model_said_passed  # no scores to verify

    # Fail if any dimension < 5
    if any(v < 5 for v in values):
        return False
    # Fail if fewer than 4 dimensions score 7+
    above_7 = sum(1 for v in values if v >= 7)
    if above_7 < 4:
        return False
    return True


def _parse_evaluator_response(raw_text: str) -> EvaluatorVerdict:
    """Parse JSON response from the evaluator model."""
    text = (raw_text or "").strip()

    # Strip markdown fences if the model wraps in ```json
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    parsed = json.loads(text)

    scores = parsed.get("scores", {})
    model_said_passed = bool(parsed.get("passed", True))
    # Cross-check: trust the scores, not the model's self-assessment
    passed = _verify_pass(scores, model_said_passed)

    total = int(parsed.get("total", 0))
    failures = list(parsed.get("failures", []))
    reasoning = str(parsed.get("reasoning", ""))
    rewrite = parsed.get("rewrite")
    if rewrite is not None:
        rewrite = str(rewrite).strip()
        if not rewrite:
            rewrite = None

    if not passed and model_said_passed:
        print(f"[evaluator] Overrode model verdict: scores {scores} don't meet pass criteria")

    return EvaluatorVerdict(
        passed=passed,
        scores=scores,
        total=total,
        failures=failures,
        reasoning=reasoning,
        rewrite=rewrite,
    )


def _get_anthropic_client():
    """Lazy-load the Anthropic client. Returns None if unavailable."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic

        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as e:
        print(f"[evaluator] Anthropic client init failed: {e}")
        return None


def evaluate_candidate(
    candidate_text: str,
    data_description: str,
    category: str,
) -> EvaluatorVerdict:
    """Run the virality evaluator on a single candidate.

    Uses Claude Sonnet 4.6 via the Anthropic API. On any failure,
    returns a passing verdict so the original candidate goes through unchanged.
    """
    client = _get_anthropic_client()
    if client is None:
        return _passing_verdict()

    try:
        user_content = (
            f"CATEGORY: {category}\n\n"
            f"DATA CONTEXT:\n{data_description}\n\n"
            f'TWEET TO EVALUATE:\n"{candidate_text}"'
        )

        response = client.messages.create(
            model=EVALUATOR_MODEL,
            max_tokens=1024,
            system=EVALUATOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = response.content[0].text
        verdict = _parse_evaluator_response(raw_text)
        action = "PASS" if verdict.passed else "FAIL"
        print(f"[evaluator] {action} (total={verdict.total}): {candidate_text[:60]}...")
        if not verdict.passed and verdict.failures:
            print(f"[evaluator] Failures: {', '.join(verdict.failures)}")
        return verdict

    except Exception as e:
        print(f"[evaluator] Evaluator failed, passing through original: {e}")
        return _passing_verdict()


def evaluate_and_polish(
    bundle: CandidateBundle,
    data_description: str,
) -> CandidateBundle:
    """Evaluate top candidate and return improved bundle.

    If the top candidate passes, returns bundle unchanged.
    If it fails and a rewrite is provided, the rewrite replaces the
    top candidate (after safety check). Falls back to original bundle
    on any failure.
    """
    if not bundle.candidates:
        return bundle

    top = bundle.candidates[0]
    verdict = evaluate_candidate(top.text, data_description, bundle.category)

    if verdict.passed or not verdict.rewrite:
        return bundle

    # Run the rewrite through safety pipeline
    safe, reason = run_safety_pipeline(verdict.rewrite)
    if not safe:
        print(f"[evaluator] Rewrite failed safety ({reason}), keeping original")
        return bundle

    # Build new candidate from the rewrite
    rewrite_score = score_candidate_text(verdict.rewrite, bundle.category)

    # Score-regression guard: don't accept a rewrite that scores worse
    if rewrite_score.total < top.score.total:
        print(f"[evaluator] Rewrite scored lower ({rewrite_score.total} < {top.score.total}), keeping original")
        return bundle

    rewrite_candidate = DraftCandidate(
        rank=1,
        text=verdict.rewrite,
        source="evaluator_rewrite",
        score=rewrite_score,
    )

    # Re-rank: rewrite at top, shift others down
    rest = [
        DraftCandidate(rank=c.rank + 1, text=c.text, source=c.source, score=c.score)
        for c in bundle.candidates
    ]

    print(f"[evaluator] Rewrite accepted: {verdict.rewrite[:60]}...")
    return CandidateBundle(
        category=bundle.category,
        candidates=[rewrite_candidate] + rest,
    )
