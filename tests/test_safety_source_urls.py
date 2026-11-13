"""Source-year URLs are citations; prose event suffixes and all safety checks remain."""
import pytest

from src.voice import safety


@pytest.mark.parametrize("url", ["https://example.invalid/report-october-2026",
    "https://example.invalid/events/ABC-1234", "http://example.invalid/archive-2026?part=2"])
def test_source_url_year_is_not_an_event_name(url):
    assert safety.check_regex("An invented monthly finding, attributed to its publisher.\n" + url) == (True, None)


@pytest.mark.parametrize("text", [
    "Storm-2026 affected an invented coast. https://example.invalid/report-2026",
    "https://example.invalid/report-2026 Storm-2026 affected an invented coast.",
    "Storm-123 is not a reader-facing name.",
])
def test_any_event_suffix_outside_urls_still_refuses(text):
    assert safety.check_regex(text)[0] is False


@pytest.mark.parametrize("text", [
    "BREAKING: A finding. https://example.invalid/report-2026",
    "A finding! https://example.invalid/report-2026",
    "A finding. https://example.invalid/report-2026 #climate",
])
def test_a_citation_cannot_hide_other_banned_patterns(text):
    assert safety.check_regex(text)[0] is False


def test_real_safety_pipeline_still_requires_model_verdict_after_url_check(monkeypatch):
    calls = []
    monkeypatch.setattr(safety, "check_llm", lambda text: (calls.append(text) or False, "invented model refusal"))
    text = "An invented completed-month finding. https://example.invalid/report-2026"
    assert safety.run_safety_pipeline(text) == (False, "invented model refusal")
    assert calls == [text]



def test_month_in_a_source_path_does_not_become_prose_padding():
    text = "October was the warmest October, above the historical October average."
    assert safety.check_month_repetition(text + "\nhttps://example.invalid/october-2026") == (True, None)
    assert safety.check_month_repetition(text + " October.")[0] is False
