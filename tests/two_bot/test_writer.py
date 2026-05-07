import importlib

import pytest

from src.two_bot.writer import write_fire_tweet

from tests.two_bot.conftest import (
    _bundle,
    _fake_writer_response,
    _fake_writer_response_raw,
    _memory,
)


def test_write_fire_tweet_returns_tweet(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": "Mali fire test",
            "kill_reason": None,
            "angle_chosen": "rarity",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "test",
        }
    )

    result = write_fire_tweet(_bundle(), _memory())

    assert result.tweet == "Mali fire test"
    assert result.kill_reason is None
    assert mock_anthropic.called


def test_write_fire_tweet_returns_kill(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": None,
            "kill_reason": "no historical_context available",
            "angle_chosen": "",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "test",
        }
    )

    result = write_fire_tweet(_bundle(), _memory())

    assert result.tweet is None
    assert result.kill_reason


def test_write_fire_tweet_raises_on_both_tweet_and_kill_set(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": "x",
            "kill_reason": "y",
            "angle_chosen": "x",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "x",
        }
    )

    with pytest.raises(ValueError):
        write_fire_tweet(_bundle(), _memory())


def test_write_fire_tweet_raises_on_invalid_json(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response_raw("not json")

    with pytest.raises(ValueError):
        write_fire_tweet(_bundle(), _memory())


def test_write_fire_tweet_raises_on_missing_api_key(monkeypatch):
    from src.two_bot import writer

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(writer, "_call_anthropic", writer._call_anthropic)

    with pytest.raises(RuntimeError):
        write_fire_tweet(_bundle(), _memory())


def test_writer_provider_resolved_at_import(monkeypatch):
    import src.two_bot.writer as writer_module

    monkeypatch.setenv("THEHEAT_WRITER_MODEL", "totally-fake-model")
    with pytest.raises(RuntimeError):
        importlib.reload(writer_module)

    monkeypatch.delenv("THEHEAT_WRITER_MODEL", raising=False)
    importlib.reload(writer_module)


class TestStripMarkdownFences:
    """Regression: Sonnet 4.6 wraps writer output in ```json fences despite
    the prompt explicitly forbidding them. Observed in run 25525862349
    (2026-05-07 22:58Z): every monthly_low + fire writer call returned
    fenced JSON, ``json.loads()`` raised, the catch-all swallowed the
    error, all drafts silently died.
    """

    def test_strips_fences_with_json_lang_tag(self):
        from src.two_bot.writer import _strip_markdown_fences
        raw = '```json\n{"tweet": "x", "kill_reason": null}\n```'
        assert _strip_markdown_fences(raw) == '{"tweet": "x", "kill_reason": null}'

    def test_strips_fences_without_lang_tag(self):
        from src.two_bot.writer import _strip_markdown_fences
        raw = '```\n{"tweet": "x"}\n```'
        assert _strip_markdown_fences(raw) == '{"tweet": "x"}'

    def test_strips_uppercase_lang_tag(self):
        from src.two_bot.writer import _strip_markdown_fences
        raw = '```JSON\n{"a": 1}\n```'
        assert _strip_markdown_fences(raw) == '{"a": 1}'

    def test_handles_leading_trailing_whitespace(self):
        from src.two_bot.writer import _strip_markdown_fences
        raw = '   \n\n  ```json\n{"a": 1}\n```  \n  '
        assert _strip_markdown_fences(raw) == '{"a": 1}'

    def test_passthrough_when_no_fences(self):
        from src.two_bot.writer import _strip_markdown_fences
        raw = '{"tweet": "already raw json"}'
        assert _strip_markdown_fences(raw) == '{"tweet": "already raw json"}'

    def test_parse_writer_json_accepts_fenced_response(self):
        from src.two_bot.writer import _parse_writer_json
        raw = """```json
{
  "tweet": "Sissonville hit -2.2C overnight, the coldest May reading since 1995.",
  "kill_reason": null,
  "angle_chosen": "monthly_record_rarity",
  "era_anchor_used": null,
  "peer_comparison_used": null,
  "reasoning": "monthly_low rarity in 30y archive"
}
```"""
        result = _parse_writer_json(raw)
        assert result.tweet is not None
        assert result.tweet.startswith("Sissonville")
        assert result.kill_reason is None

    def test_parse_writer_json_rejects_truly_invalid_json(self):
        import pytest
        from src.two_bot.writer import _parse_writer_json
        with pytest.raises(ValueError, match="invalid JSON"):
            _parse_writer_json("```json\nnot actually json\n```")


class TestBundleJsonHandlesDates:
    """Regression: GHCN bundles carry signal_date (date) inside raw_signal_dump.

    Before the _json_default hook landed, json.dumps raised
    ``TypeError: Object of type date is not JSON serializable`` and
    the entire two-bot pipeline aborted via the catch-all in
    pipeline.py — silently killing every GHCN draft. See run
    25512609762 (2026-05-07 17:48Z), where 2 monthly_low bundles died
    this way after passing the editorial score gate.
    """

    def _bundle_with_date(self):
        import datetime
        from src.two_bot.types import StoryBundle

        return StoryBundle(
            signal_kind="monthly_low",
            where="SISSONVILLE 1SW, United States",
            when="on May 4",
            event_id="monthly_low_USC00468191_05_2026-05-04",
            headline_metric={"label": "today_min_c", "value": -2.2, "unit": "C"},
            current_facts=[{"label": "city", "value": "SISSONVILLE 1SW"}],
            historical_context={"prior_record_c": 1.0, "prior_record_year": 1995},
            raw_signal_dump={
                "city": "SISSONVILLE 1SW",
                "country": "United States",
                "signal_date": datetime.date(2026, 5, 4),
                "kind": "low",
                "today_min_c": -2.2,
            },
        )

    def test_bundle_json_serializes_date_as_iso_string(self):
        import json
        from src.two_bot.writer import _bundle_json

        bundle = self._bundle_with_date()
        result = _bundle_json(bundle)
        parsed = json.loads(result)
        assert parsed["raw_signal_dump"]["signal_date"] == "2026-05-04"

    def test_bundle_json_serializes_datetime_as_iso_string(self):
        import datetime
        import json
        from src.two_bot.writer import _bundle_json
        from src.two_bot.types import StoryBundle

        bundle = StoryBundle(
            signal_kind="test",
            where="here",
            when="now",
            event_id="ev1",
            headline_metric={},
            current_facts=[],
            raw_signal_dump={"ts": datetime.datetime(2026, 5, 7, 12, 0, 0)},
        )
        result = _bundle_json(bundle)
        parsed = json.loads(result)
        assert parsed["raw_signal_dump"]["ts"].startswith("2026-05-07T12:00:00")

    def test_bundle_json_raises_on_unknown_type(self):
        from src.two_bot.writer import _bundle_json
        from src.two_bot.types import StoryBundle

        class Surprise:
            pass

        bundle = StoryBundle(
            signal_kind="test",
            where="here",
            when="now",
            event_id="ev2",
            headline_metric={},
            current_facts=[],
            raw_signal_dump={"x": Surprise()},
        )
        # Loud failure — we don't want to silently coerce surprise types via str().
        with pytest.raises(TypeError, match="not JSON serializable"):
            _bundle_json(bundle)

    def test_fact_check_bundle_json_handles_date(self, monkeypatch):
        """Same fix in fact_check.py — uses the shared _json_default."""
        import datetime
        import json

        # Stub _call_gemini so we can capture the bundle_json string it builds.
        captured = {}

        def fake_call(tweet, bundle):
            from src.two_bot.fact_check import _json_default
            from src.two_bot.prompts.fact_check_prompt import FACT_CHECK_USER_PROMPT_TEMPLATE
            user_prompt = FACT_CHECK_USER_PROMPT_TEMPLATE.format(
                tweet=tweet,
                bundle_json=json.dumps(
                    bundle.to_dict(), sort_keys=True, default=_json_default
                ),
            )
            captured["prompt"] = user_prompt
            return '{"passed": true, "failures": []}'

        from src.two_bot import fact_check
        monkeypatch.setattr(fact_check, "_call_gemini", fake_call)

        bundle = self._bundle_with_date()
        result = fact_check.fact_check("test tweet", [], bundle, {})
        assert result.passed is True
        assert "2026-05-04" in captured["prompt"]

