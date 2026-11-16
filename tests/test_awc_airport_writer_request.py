"""Invented observations and model replies, never live copy-quality proof."""
import json

from freezegun import freeze_time
import pytest

from src.two_bot import writer
from tests.test_awc_observed import NOW
from tests.test_awc_observed_automatic import generate, sender, world as world

REAL_WRITER = writer.write_tweet
BODY = ("65°C airport gap: North Test/Island, Norway −20°C; "
        "South Test/Bay, Chile 45°C at 12:00 UTC, 15 Nov.")


@pytest.mark.parametrize("omission", [None, "slash", "airport"])
def test_real_writer_request_preserves_full_airport_scope_without_rewriting(world, monkeypatch, omission):
    transport, state, _, called, stages = world
    transport.stations[0]["site"] = "North Test/Island Arpt"
    transport.stations[1]["site"] = "South Test/Bay Arpt"
    body = BODY
    if omission == "slash":
        body = body.replace("North Test/Island", "North Test")
    elif omission == "airport":
        body = body.replace("airport ", "")
    requests = []

    def reply(prompt):
        request = writer.anthropic_writer_request(prompt)
        requests.append(request)
        # Same physical-attempt boundary as the existing offline integration fixture.
        stages[0]()
        assert "including slash-separated name parts" in prompt
        assert "Use the word airport or airports explicitly" in prompt
        assert "Never replace an airport name with a nearby city" in prompt
        assert '"airport": "North Test/Island Arpt"' in prompt
        assert '"airport": "South Test/Bay Arpt"' in prompt
        assert '"body_max_scalars": 109' in prompt
        return json.dumps({"tweet": body, "kill_reason": None, "angle_chosen": "observed_contrast",
                           "era_anchor_used": None, "peer_comparison_used": None,
                           "reasoning": "Explicit invented model reply, not a model-quality evaluation."})

    monkeypatch.setattr(writer, "_call_writer_provider", reply)
    monkeypatch.setattr(writer, "write_tweet", REAL_WRITER)
    generate(world)
    assert len(requests) == 1
    assert requests[0]["model"] == writer.WRITER_MODEL
    if omission is not None:
        assert called == ["writer"]
        assert state["drafts"] == []
        assert "awc_airport_scope_missing" in state["suppressions"][-1]["reasons"]
        sender(monkeypatch, world)
        assert transport.x_posts == []
        return
    assert called == ["writer", "safety", "fact_check", "critic"]
    draft = state["drafts"][0]
    assert draft["text"].split("\n")[0] == body
    assert len(draft["text"]) <= 200
    with freeze_time(NOW):
        assert writer.automatic_copy_budget(draft_bundle(draft))["body_max_scalars"] == 109
    sender(monkeypatch, world)
    assert transport.x_posts == [draft["text"]]
    sender(monkeypatch, world)
    assert transport.x_posts == [draft["text"]]


def draft_bundle(draft):
    from src.two_bot.types import StoryBundle
    return StoryBundle(**draft["review_context"]["two_bot"]["bundle"])
