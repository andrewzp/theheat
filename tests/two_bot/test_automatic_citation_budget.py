"""Writer preparation fits the existing cap; it never rewrites or grants a check."""

from copy import deepcopy
import json

import pytest

from src.editorial.automatic_text import automatic_text_hold, scalar_count, OVER_CAP
from src.two_bot import writer
from src.two_bot.source_links import source_citation, format_source_link
from src.two_bot.types import StoryBundle, MemorySlice


def bundle(url="https://example.invalid/report-october-2026", kind="monthly_climate_report"):
    return StoryBundle(
        kind,
        "Invented global report",
        "2026-10-31",
        "invented-report",
        {"label": "published_monthly_anomaly", "value": 1.6},
        [{"label": "public_source_url", "value": url}],
        raw_signal_dump={},
    )


def test_exact_citation_and_newline_are_reserved_before_the_writer(monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    b = bundle()
    before = deepcopy(b.to_dict())
    budget = writer.automatic_copy_budget(b)
    assert budget == {
        "final_max_scalars": 200,
        "citation": source_citation(b),
        "citation_reserve_scalars": len(source_citation(b)) + 1,
        "body_max_scalars": 199 - len(source_citation(b)),
    }
    prompt = writer.build_writer_user_prompt(b, MemorySlice())
    assert json.dumps(budget, sort_keys=True, ensure_ascii=False) in prompt
    assert "Preserve required units, period, geographic scope, baseline and attribution" in prompt
    assert "preserve correctness for manual review" in prompt
    assert b.to_dict() == before


def test_no_citation_uses_existing_final_cap_without_inventing_one(monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    b = bundle(kind="monthly_high")
    assert source_citation(b) is None
    assert writer.automatic_copy_budget(b) == {
        "final_max_scalars": 200,
        "citation": None,
        "citation_reserve_scalars": 0,
        "body_max_scalars": 200,
    }


@pytest.mark.parametrize("kind", ["hot10", "fire", "official_warning"])
def test_manual_or_forecast_kinds_get_no_new_automatic_instruction(monkeypatch, kind):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    assert writer.automatic_copy_budget(bundle(kind=kind)) is None


def test_legacy_off_prompt_and_cached_system_remain_exact(monkeypatch):
    monkeypatch.delenv("THEHEAT_OBSERVED_WEATHER_ONLY", raising=False)
    b = bundle(kind="monthly_high")
    m = MemorySlice()
    expected = writer.WRITER_USER_PROMPT_TEMPLATE.format(
        bundle_json=writer._bundle_json(b), memory_json=writer._memory_json(m)
    )
    assert writer.build_writer_user_prompt(b, m) == expected
    system = writer.anthropic_writer_request(expected)["system"]
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    request = writer.anthropic_writer_request(writer.build_writer_user_prompt(b, m))
    assert request["system"] == system
    assert writer.automatic_copy_budget(b)["body_max_scalars"] == 200


def test_scalar_budget_not_utf8_bytes_and_formatter_unchanged(monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    b = bundle("https://example.invalid/café-2026")
    budget = writer.automatic_copy_budget(b)
    body = "é" * budget["body_max_scalars"]
    final = format_source_link(body, b)
    assert scalar_count(final) == 200 and automatic_text_hold(final) is None
    assert len(final.encode("utf8")) > 200
    longer = format_source_link(body + "é", b)
    assert longer == body + "é\n" + source_citation(b)
    assert automatic_text_hold(longer) == OVER_CAP
    assert format_source_link(final, b) == final


def test_impossible_citation_budget_cannot_authorize_truncation(monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    b = bundle("https://example.invalid/" + "a" * 200)
    budget = writer.automatic_copy_budget(b)
    assert budget["body_max_scalars"] == 0 and budget["citation"] == source_citation(b)
    prompt = writer.build_writer_user_prompt(b, MemorySlice())
    assert "Never drop a necessary qualifier, invent a short URL or truncate a claim" in prompt
    text = format_source_link("A complete invented fact.", b)
    assert text.startswith("A complete invented fact.") and automatic_text_hold(text) == OVER_CAP


@pytest.mark.parametrize(
    "url", ["not a URL", "https://example.invalid/%zz", "https://name:secret@example.invalid/x"]
)
def test_malformed_citation_stays_unqualified_and_is_never_formatted(monkeypatch, url):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    b = bundle(url)
    assert source_citation(b) is None
    assert writer.automatic_copy_budget(b)["citation"] is None
    assert format_source_link("Complete invented fact.", b) == "Complete invented fact."
