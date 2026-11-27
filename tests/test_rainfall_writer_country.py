"""Invented provider answers through the actual point writer/check/save path."""
import json

import pytest

from src.data import gpm_imerg as gpm
from src.two_bot import critic, fact_check, writer
from src.voice import safety
from tests import live_content_harness as h
from tests.test_rainfall_observed_automatic import collect, world  # noqa: F401
from tests.test_rainfall_observed_report import TEXT

REAL_WRITER = writer.write_tweet
REAL_FACT_CHECK = fact_check.fact_check
REAL_CRITIC = critic.critic_review
REAL_SAFETY = safety.check_llm


@pytest.mark.parametrize("country_named,factual_pass", [(False, True), (True, False), (True, True)])
def test_required_country_instruction_reaches_writer_without_bypassing_checks(
    monkeypatch, world, country_named, factual_pass,  # noqa: F811
):
    transport, state, _run, _old_calls, _old_stages, _module = world
    transport.rows = [next(row for row in gpm.load_cities()
                           if row["city"] == "Seattle" and row["country"] == "US")]
    place = "Seattle, US" if country_named else "Seattle, WA"
    body = TEXT.split("\n")[0].replace("Paris, France", place)
    monkeypatch.setattr(writer, "write_tweet", REAL_WRITER)
    monkeypatch.setattr(fact_check, "fact_check", REAL_FACT_CHECK)
    monkeypatch.setattr(critic, "critic_review", REAL_CRITIC)
    monkeypatch.setattr(safety, "check_llm", REAL_SAFETY)
    monkeypatch.setattr(safety, "_SAFETY_CACHE", type(safety._SAFETY_CACHE)())
    models = h.ModelScript(copy=body, fact_passed=factual_pass)
    models.install(monkeypatch.setattr)
    collect(world)
    [request] = [request for stage, request in models.requests if stage == "writer"]
    prompt = json.dumps(request["messages"])
    assert "explicitly include the source country from bundle.country beside the place" in prompt
    assert "A US state or region cannot replace that country" in prompt
    assert "Do not infer or add an unsupplied state or country" in prompt
    if not country_named:
        assert models.stages() == ["writer"]
        assert state["drafts"] == []
        assert any("rainfall_country_required" in row.get("reasons", [])
                   for row in state["suppressions"])
    elif not factual_pass:
        assert models.stages() == ["writer", "safety", "fact_check"]
        assert state["drafts"] == []
    else:
        assert models.stages() == ["writer", "safety", "fact_check", "critic"]
        [draft] = state["drafts"]
        assert draft["text"] == body + "\n" + gpm_public_url()
        assert draft["approval_binding"]["mode"] == "auto"
        assert draft["review_binding"]["kind"] == "model"
    assert transport.x_posts == []


def gpm_public_url():
    from src.data.rainfall_observed import SOURCE_URL
    return SOURCE_URL
