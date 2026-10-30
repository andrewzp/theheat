"""Actual nhc_advisory runner/queue/pipeline/admission with labelled offline fakes.

The four paid stages are explicit offline fakes, but each one goes through the
real provider boundary (trial_budget.provider_call inside call_with_retries), so
every provider attempt, including a retry, meets the live current-source guard.
NHC HTTP is an invented transport. Nothing here evaluates real model quality.
"""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from unittest.mock import Mock

from src.data import nhc_advisory as source
from src.editorial.nhc_advisory_runtime import AdvisoryOwner, advisory_owner_scope
from src.orchestrator.sources.nhc_advisory import run_nhc_advisory
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.state import DEFAULT_STATE
from src.two_bot import pipeline, trial_budget
from src.two_bot.retry import call_with_retries
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests import nhc_advisory_helpers as h

COPY = "Up to 3 inches of rain could trigger flash flooding and mudslides in Example Province tonight, NHC forecasts."


class Transport:
    """Invented NHC responses by exact URL; records every request in order."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, url, *, limit):
        self.calls.append(url)
        value = self.responses.get(url)
        if callable(value):
            value = value()
        if value is None:
            value = (200, {}, h.index() if url == source.INDEX_URL else h.page())
        if isinstance(value, Exception):
            raise value
        return value


def stage_fakes(sent, *, copy=COPY, failures=None):
    """Each fake purchases through the real provider/retry boundary with an offline send."""
    failures = failures if failures is not None else {}

    def via(stage, provider, result):
        def send(**request):
            sent.append(stage)
            if failures.get(stage):
                failures[stage] -= 1
                raise TimeoutError("invented transient response loss")
            return object()

        def run(*args, **kwargs):
            call_with_retries("invented " + stage, lambda: trial_budget.provider_call(
                stage, provider, {"model": "invented-" + stage}, send), sleep_seconds=0)
            return result
        return Mock(side_effect=run)
    return (via("writer", "anthropic", WriterResult(copy, None, "warning_consequence", None, None,
                                                    "Explicit invented offline model response.")),
            via("safety", "google", (True, None)),
            via("fact_check", "google", FactCheckResult(True, [], "Explicit offline check fixture.")),
            via("critic", "google", CriticResult(True, None, "Explicit offline critic fixture.")))


def configure(patch, transport, *, nomination=None):
    """Offline provider presence, one-sample/no-revise profile and the explicit opt-in."""
    patch.setenv("ANTHROPIC_API_KEY", "invented-no-provider-access")
    patch.setenv("GEMINI_API_KEY", "invented-no-provider-access")
    patch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
    for name, value in (("THEHEAT_WRITER_SAMPLES", "1"), ("THEHEAT_CRITIC_REVISE_ENABLED", "0"),
                        ("THEHEAT_CRITIC_ENABLED", "1"), ("THEHEAT_TRIAGE_ENABLED", "0"),
                        ("THEHEAT_NHC_ADVISORY_ACQUISITION", "1"),
                        ("THEHEAT_NHC_ADVISORY_NOMINATION", json.dumps(nomination or h.nominated()))):
        patch.setenv(name, value)
    patch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    patch.setattr(source, "_http_get", transport)


def generate(patch, transport, *, now=h.NOW, state=None, copy=COPY, failures=None, request_limit=None):
    """Run the real runner then the real drain; returns (state, observation)."""
    configure(patch, transport)
    sent: list[str] = []
    writer, safety, fact, critic = stage_fakes(sent, copy=copy, failures=failures)
    patch.setattr(pipeline.writer, "write_tweet", writer)
    patch.setattr(pipeline, "run_safety_pipeline", safety)
    patch.setattr(pipeline.fact_check, "fact_check", fact)
    patch.setattr(pipeline.critic, "critic_review", critic)
    state = deepcopy(DEFAULT_STATE) if state is None else state
    run: dict = {"sources": []}
    with advisory_owner_scope(AdvisoryOwner(clock=lambda: now), request_limit=request_limit) as _owner, \
            redirect_stdout(io.StringIO()):
        budget = source.current_budget()
        result = run_nhc_advisory(state, run)
        drafted = _drain_and_write_triage_queue(state, run)
    return state, {"result": result, "drafted": drafted, "sent": sent, "requests": budget.used, "run": run,
                   "calls": [m.call_count for m in (writer, safety, fact, critic)]}
