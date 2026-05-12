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


class TestLengthRetry:
    """Writer-side defense: if the model returns a tweet > 280 chars, retry
    with explicit length feedback. After LENGTH_RETRY_BUDGET retries, return
    KILL so Twitter never sees an over-length string.

    Production failure mode this prevents: voice-regression nightly failures
    on cold-record fixtures (Sissonville, Verkhoyansk) where Sonnet's
    system-explainer occasionally overshoots 280 chars on a given sampling.
    Without retry, every such overshoot fails the test AND ships a
    truncated draft. With retry, the second/third call usually fits.
    """

    def _overlong(self, n: int = 320) -> str:
        return "x" * n

    def _short(self) -> str:
        return "Sissonville hit 28°F overnight on May 4; coldest May low in 16 years."

    def test_retries_when_first_attempt_is_overlong(self, mock_anthropic):
        """First call > 280, second call fits — second result returned."""
        mock_anthropic.side_effect = [
            _fake_writer_response({
                "tweet": self._overlong(290),
                "kill_reason": None,
                "angle_chosen": "x",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": "first",
            }),
            _fake_writer_response({
                "tweet": self._short(),
                "kill_reason": None,
                "angle_chosen": "x",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": "second",
            }),
        ]

        result = write_fire_tweet(_bundle(), _memory())

        assert result.tweet == self._short()
        assert result.kill_reason is None
        assert mock_anthropic.call_count == 2

    def test_kills_after_retry_budget_exhausted(self, mock_anthropic):
        """All 3 attempts > 280 — return KILL with explicit reason."""
        from src.two_bot.writer import LENGTH_RETRY_BUDGET

        mock_anthropic.side_effect = [
            _fake_writer_response({
                "tweet": self._overlong(290 + i),
                "kill_reason": None,
                "angle_chosen": "x",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": f"attempt {i}",
            })
            for i in range(LENGTH_RETRY_BUDGET + 1)
        ]

        result = write_fire_tweet(_bundle(), _memory())

        assert result.tweet is None
        assert result.kill_reason is not None
        assert "over-280-char" in result.kill_reason
        assert "attempts" in result.kill_reason
        assert mock_anthropic.call_count == LENGTH_RETRY_BUDGET + 1

    def test_no_retry_when_first_attempt_fits(self, mock_anthropic):
        """Happy path: first call ≤ 280, no retry."""
        mock_anthropic.return_value = _fake_writer_response({
            "tweet": self._short(),
            "kill_reason": None,
            "angle_chosen": "x",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "first",
        })

        result = write_fire_tweet(_bundle(), _memory())

        assert result.tweet == self._short()
        assert mock_anthropic.call_count == 1

    def test_no_retry_when_first_attempt_is_kill(self, mock_anthropic):
        """If writer kills (tweet=None), no length-retry needed."""
        mock_anthropic.return_value = _fake_writer_response({
            "tweet": None,
            "kill_reason": "no historical_context available",
            "angle_chosen": "",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "first",
        })

        result = write_fire_tweet(_bundle(), _memory())

        assert result.tweet is None
        assert result.kill_reason == "no historical_context available"
        assert mock_anthropic.call_count == 1

    def test_retry_user_prompt_carries_length_feedback(self, mock_anthropic):
        """The retry user prompt must include the previous draft's char count
        so the model knows what to shorten."""
        mock_anthropic.side_effect = [
            _fake_writer_response({
                "tweet": self._overlong(297),
                "kill_reason": None,
                "angle_chosen": "x",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": "first",
            }),
            _fake_writer_response({
                "tweet": self._short(),
                "kill_reason": None,
                "angle_chosen": "x",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": "second",
            }),
        ]

        write_fire_tweet(_bundle(), _memory())

        # First call has no retry feedback; second call must.
        first_prompt = mock_anthropic.call_args_list[0].args[0]
        second_prompt = mock_anthropic.call_args_list[1].args[0]
        assert "Length retry" not in first_prompt
        assert "Length retry" in second_prompt
        assert "297 characters" in second_prompt
        assert "280-character cap" in second_prompt

    def test_boundary_exactly_280_chars_passes(self, mock_anthropic):
        """Tweet at exactly 280 chars is valid, no retry."""
        text_280 = "x" * 280
        mock_anthropic.return_value = _fake_writer_response({
            "tweet": text_280,
            "kill_reason": None,
            "angle_chosen": "x",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "boundary",
        })

        result = write_fire_tweet(_bundle(), _memory())

        assert result.tweet == text_280
        assert mock_anthropic.call_count == 1

    def test_boundary_281_chars_triggers_retry(self, mock_anthropic):
        """Tweet at 281 chars is over — retry triggers."""
        text_281 = "x" * 281
        mock_anthropic.side_effect = [
            _fake_writer_response({
                "tweet": text_281,
                "kill_reason": None,
                "angle_chosen": "x",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": "first",
            }),
            _fake_writer_response({
                "tweet": self._short(),
                "kill_reason": None,
                "angle_chosen": "x",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": "second",
            }),
        ]

        result = write_fire_tweet(_bundle(), _memory())

        assert result.tweet == self._short()
        assert mock_anthropic.call_count == 2


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


class TestExtractJsonPayload:
    """Regression: Sonnet 4.6 emits a chain-of-thought preamble before
    the JSON ('Let me think about this carefully.') in run 25526974586,
    even though the prompt says 'No prose outside the JSON.' The fence
    stripper alone doesn't catch this — there's no fence. Solution:
    extract the substring between the first '{' and the last '}'.
    """

    def test_strips_chain_of_thought_preamble(self):
        from src.two_bot.writer import _extract_json_payload
        raw = 'Let me think about this carefully.\n\n{"tweet": "x", "kill_reason": null}'
        assert _extract_json_payload(raw) == '{"tweet": "x", "kill_reason": null}'

    def test_strips_postamble_explanation(self):
        from src.two_bot.writer import _extract_json_payload
        raw = '{"tweet": "x"}\n\nThe reasoning behind this choice is...'
        assert _extract_json_payload(raw) == '{"tweet": "x"}'

    def test_strips_preamble_and_fences_combined(self):
        from src.two_bot.writer import _extract_json_payload
        raw = '```json\nLet me reason about this signal.\n{"a": 1}\n```'
        assert _extract_json_payload(raw) == '{"a": 1}'

    def test_handles_nested_raw_signal_dump_object(self):
        """Bundle response has nested dicts inside raw_signal_dump.
        rfind('}') should still find the OUTER closing brace."""
        from src.two_bot.writer import _extract_json_payload
        raw = 'Here is the response: {"tweet": "x", "raw_signal_dump": {"city": "Sissonville", "nested": {"a": 1}}}'
        result = _extract_json_payload(raw)
        import json
        parsed = json.loads(result)
        assert parsed["raw_signal_dump"]["nested"]["a"] == 1

    def test_passthrough_clean_response(self):
        from src.two_bot.writer import _extract_json_payload
        raw = '{"tweet": "clean response"}'
        assert _extract_json_payload(raw) == '{"tweet": "clean response"}'

    def test_no_braces_at_all_returns_cleaned_text(self):
        """Genuine garbage from the model — let json.loads fail loudly
        with the raw text in the error log, not silently swallow."""
        from src.two_bot.writer import _extract_json_payload
        raw = "I cannot help with this signal."
        # Returned as-is (no extraction possible). json.loads() in the
        # caller will raise ValueError, which gets logged.
        assert _extract_json_payload(raw) == "I cannot help with this signal."

    def test_parse_writer_json_accepts_preamble_response(self):
        """End-to-end: a Sonnet response with chain-of-thought
        preamble parses correctly through the full _parse_writer_json
        path — exactly the failure mode in run 25526974586."""
        from src.two_bot.writer import _parse_writer_json
        raw = """Let me think about this signal carefully.

The bundle shows a monthly_low for Sissonville at -2.2C. The prior
record was 1.0C in 1995. That's a significant 3-degree margin.

{
  "tweet": "Sissonville WV hit -2.2C overnight, three degrees below the previous May low set in 1995.",
  "kill_reason": null,
  "angle_chosen": "monthly_record_margin",
  "era_anchor_used": null,
  "peer_comparison_used": null,
  "reasoning": "monthly low with strong margin against archive"
}"""
        result = _parse_writer_json(raw)
        assert result.tweet is not None
        assert result.tweet.startswith("Sissonville WV")
        assert result.kill_reason is None
        assert result.angle_chosen == "monthly_record_margin"


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


class TestWriterPromptAntiSpeculation:
    """Regression: writer was inventing temporal and seasonal framing not in the
    bundle, causing fact-check kills. Two confirmed kills on 2026-05-08 (Dayton WY):
    - 'January reading' — invented seasonal framing
    - 'three weeks into meteorological spring' — invented + factually wrong

    The HARD RULES now carry an explicit anti-fabricated-context bullet. These
    tests assert the prompt contains the guard and does NOT contain blanket
    anti-voice phrases that would kill legitimate editorial flourish like
    'Fruit trees in the Kanawha Valley were not consulted.'
    """

    def _get_system_prompt(self):
        from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT
        return WRITER_SYSTEM_PROMPT

    def test_anti_speculation_bullet_present(self):
        """The HARD RULES section must contain the fabricated-context guard."""
        prompt = self._get_system_prompt()
        assert "NO FABRICATED CONTEXT" in prompt

    def test_bullet_names_temporal_framing_examples(self):
        """Bullet must call out specific temporal-framing failure patterns."""
        prompt = self._get_system_prompt()
        assert "three weeks into meteorological spring" in prompt
        assert "January reading" in prompt

    def test_bullet_names_seasonal_biological_examples(self):
        """Bullet must call out seasonal/biological invented context."""
        prompt = self._get_system_prompt()
        assert "flowers are already up" in prompt
        assert "the ground froze" in prompt

    def test_bullet_explicitly_permits_anthropomorphic_flourish(self):
        """The Sissonville regression guard: anthropomorphic voice must be
        explicitly exempted so the model doesn't over-correct and kill
        editorial lines like 'Fruit trees...were not consulted.'"""
        prompt = self._get_system_prompt()
        assert "Anthropomorphic flourish" in prompt
        assert "not consulted" in prompt  # the canonical example is in the prompt

    def test_prompt_does_not_contain_blanket_anti_voice_ban(self):
        """Confirm no blunt 'no anthropomorphism' rule was accidentally added."""
        prompt = self._get_system_prompt()
        assert "no anthropomorphism" not in prompt.lower()
        assert "no anthropomorphic" not in prompt.lower()


class TestWriterPromptHardRules:
    """Each HARD RULE bullet in WRITER_SYSTEM_PROMPT is load-bearing.

    These tests fail if a bullet is accidentally deleted or weakened during
    a prompt edit. They check for canonical concept anchors per rule, not
    exact wording, so minor rephrasing doesn't break them. The intent is
    "did the rule get dropped from the prompt?", not "is the wording
    pixel-perfect?"
    """

    def _get_system_prompt(self):
        from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT
        return WRITER_SYSTEM_PROMPT

    def test_length_cap_present(self):
        prompt = self._get_system_prompt()
        assert "280" in prompt

    def test_no_first_person_rule(self):
        """Rule must enumerate the specific banned pronouns so the model
        can't paraphrase its way around 'no first person.'"""
        prompt = self._get_system_prompt()
        assert "No first person" in prompt
        assert '"we"' in prompt
        assert '"I"' in prompt
        assert '"us"' in prompt

    def test_no_hedging_rule(self):
        prompt = self._get_system_prompt()
        assert "No hedging" in prompt
        # At least one canonical hedging example must remain
        assert '"seems"' in prompt or '"may"' in prompt or '"appears to be"' in prompt

    def test_no_restate_padding_rule(self):
        prompt = self._get_system_prompt()
        assert "restate-padding" in prompt or "restate padding" in prompt

    def test_no_poetry_closers_rule(self):
        """The named example anchors the shape — model needs to see what's banned."""
        prompt = self._get_system_prompt()
        assert "poetry" in prompt.lower()
        # The canonical "doesn't know" example must remain
        assert "doesn't know" in prompt or "doesn’t know" in prompt

    def test_no_named_power_plant_formula_rule(self):
        """The single most-violated stock-formula ban — must enumerate the
        adjectives so the model can't slip in 'mid-sized commercial reactor.'"""
        prompt = self._get_system_prompt()
        assert "power plant" in prompt
        assert "SPECIFIC" in prompt or "NAMED" in prompt

    def test_no_throat_clearing_openers_rule(self):
        prompt = self._get_system_prompt()
        assert "throat-clearing" in prompt or "throat clearing" in prompt

    def test_concrete_claim_traceability_rule(self):
        """Every concrete claim must trace to bundle or general knowledge."""
        prompt = self._get_system_prompt()
        assert "traceable to the bundle" in prompt or "trace to" in prompt
        assert "bundle" in prompt

    def test_geographic_orientation_rule(self):
        """Must remain with named-city examples; this rule was a recurring
        regression target — readers need 'Conakry, Guinea' not just 'Conakry.'"""
        prompt = self._get_system_prompt()
        assert "ORIENT THE READER GEOGRAPHICALLY" in prompt
        # Specific anchor cities that motivated the rule
        assert "Conakry" in prompt
        assert "Yakutsk" in prompt

    def test_temperature_formatting_rules_present(self):
        """audience_unit / Fahrenheit-first routing — added in PR #46."""
        prompt = self._get_system_prompt()
        assert "audience_unit" in prompt
        assert "fahrenheit_first" in prompt
        assert "celsius_first" in prompt

    def test_archive_window_only_rule_present(self):
        """When historical_context.archive_window_only is true, model must
        NOT call it 'all-time' / 'ever' / 'in recorded history.'"""
        prompt = self._get_system_prompt()
        assert "archive_window_only" in prompt
        # The substitute phrasing must be enumerated so the model has a path
        assert "in N years" in prompt or "in the N-year" in prompt or "since" in prompt

