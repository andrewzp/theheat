"""Actual warning queue/pipeline/admission with labelled offline provider fakes."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
from unittest.mock import Mock

import pytest

from src.editorial.warning_runtime import SuppliedWarning, WarningSource, warning_source_scope
from src.editorial.scoring import EditorialScore
from src.orchestrator.sources.official_warning import run_official_warning
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests.warning_helpers import NOW, encode, nomination, packet

COPY = "Invented Warning Agency warns: dangerous winds are possible tonight on Example Island."


def source():
    metadata, raw = packet()
    encoded = encode(metadata)
    selected = SuppliedWarning(encoded, raw, nomination(encoded, raw))
    return WarningSource(lambda: selected, clock=lambda: NOW)


def generated_state(runtime=None):
    """Return a genuinely generated pending draft, never fabricated model proof."""
    from src.editorial.policy import current_editorial_policy
    state = deepcopy(DEFAULT_STATE)
    writer = Mock(return_value=WriterResult(COPY, None, "warning_consequence", None, None,
                                           "Explicit invented offline model response."))
    safety = Mock(return_value=(True, None))
    fact = Mock(return_value=FactCheckResult(True, [], "Explicit offline check fixture."))
    critic = Mock(return_value=CriticResult(True, None, "Explicit offline critic fixture."))
    score = EditorialScore("official_warning", 80, 80, 80, 80, 80, 0, 80, 60,
                           ["Explicit invented editorial nomination."])
    with pytest.MonkeyPatch.context() as patch, redirect_stdout(io.StringIO()):
        patch.setenv("ANTHROPIC_API_KEY", "invented-no-provider-access")
        patch.setenv("GEMINI_API_KEY", "invented-no-provider-access")
        patch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
        patch.setenv("THEHEAT_WRITER_SAMPLES", "1")
        patch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
        patch.setenv("THEHEAT_CRITIC_ENABLED", "1")
        patch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
        patch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
        patch.setattr(pipeline.writer, "write_tweet", writer)
        patch.setattr(pipeline, "run_safety_pipeline", safety)
        patch.setattr(pipeline.fact_check, "fact_check", fact)
        patch.setattr(pipeline.critic, "critic_review", critic)
        selected = source()
        assert run_official_warning(state, None, source=selected, score=score)["promoted"] == 1
        with warning_source_scope(selected):
            assert _drain_and_write_triage_queue(state, None) == 1
        policy = current_editorial_policy()
    assert [item.call_count for item in (writer, safety, fact, critic)] == [1, 1, 1, 1]
    assert state["drafts"][0]["status"] == "pending"
    state["drafts"][0]["id"] = "invented-official-warning"
    if runtime is not None:
        row = deepcopy(runtime)
        row["runtime_inventory"]["editorial_policy"] = policy
        state["run_history"] = [row]
    return state, policy
