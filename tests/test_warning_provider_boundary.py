"""Actual logical provider/retry boundary; send is an explicit offline stub."""
from src.two_bot import trial_budget
from src.two_bot.retry import call_with_retries
from tests.test_retained_warning_pipeline import case as case, draft
from tests.two_bot.conftest import configured_pipeline_providers as configured_pipeline_providers
from src.editorial.warning_runtime import warning_final_safety_scope, warning_source_scope
from datetime import timedelta
import pytest

pytestmark = pytest.mark.usefixtures("configured_pipeline_providers")


def test_expired_warning_is_not_dispatched_again_after_a_transient_provider_failure(case):
    attempts = []
    output = case["writer"].return_value
    def send(**request):
        attempts.append(request)
        if len(attempts) == 1:
            case["selected"]["now"] += timedelta(days=1)
            raise TimeoutError("invented response lost")
        return object()
    def writer(*args, **kwargs):
        call_with_retries("invented writer", lambda: trial_budget.provider_call(
            "writer", "anthropic", {"model": "invented", "messages": []}, send), sleep_seconds=0)
        return output
    case["writer"].side_effect = writer
    with warning_source_scope(case["source"]):
        saved, result = draft(case)
    assert not saved and case["state"]["drafts"] == []
    assert len(attempts) == 1
    assert result["kill_reason"] == "warning_expired"


def test_unchanged_current_source_keeps_existing_bounded_transport_retry(case):
    attempts = []
    output = case["writer"].return_value
    def send(**request):
        attempts.append(request)
        if len(attempts) == 1:
            raise TimeoutError("invented transport failure")
        return object()
    def writer(*args, **kwargs):
        call_with_retries("invented writer", lambda: trial_budget.provider_call(
            "writer", "anthropic", {"model": "invented", "messages": []}, send), sleep_seconds=0)
        return output
    case["writer"].side_effect = writer
    with warning_source_scope(case["source"]):
        assert draft(case)[0]
    assert len(attempts) == 2 and case["writer"].call_count == 1


@pytest.mark.parametrize("context", [None, {}, {"two_bot": None}, {"two_bot": {}}])
def test_unrelated_manual_sources_keep_their_existing_provider_behavior(context):
    sent = []
    with warning_final_safety_scope({"type": "fixture_text", "review_context": context}):
        trial_budget.provider_call("safety", "google", {"model": "invented"}, lambda **request: sent.append(request))
    assert sent == [{"model": "invented"}]
