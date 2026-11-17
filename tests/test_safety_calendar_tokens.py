"""Real ISO calendar dates and signed temperatures are not prose event suffixes.

GHCN/ERA5 record wording must name the verified source cutoff literally (for example
"through 2026-11-15"), so the lexical event-suffix rule cannot refuse a real date token.
Everything else stays: malformed or impossible dates, hyphen-joined ranges, event-ID
suffixes and every other ban keep their exact refusal, and a lexical pass is never a
factual, source, review or publication pass: the required model check still decides.
All examples are invented.
"""
import pytest

from src.voice import safety
from src.voice.safety import check_regex

ROOT_REPRODUCTION = ("Invented Station 0 reached 39.9°C on November 16, above its available "
                     "GHCN archive high through 2026-11-15.")


@pytest.mark.parametrize("text", [
    ROOT_REPRODUCTION,
    "Invented Station 0 fell to -31.4°C, its lowest in the available GHCN archive through 2026-11-15.",
    "Invented Station 0 reached 41.2°C on 16 November (GHCN archive through 2026-11-15).",
    "Through 2026-11-15, Invented Station 0 had never logged a November reading above 36°C.",
    "Invented Station 0 hit 104°F, above its accepted-sample archive high through 2026-11-15; 2026-11-16 was hotter.",
    "Invented Station 0 reached 39.9°C, an ERA5 reanalysis high through 2024-02-29.",
    "Invented Station 0 reached 39.9°C from 2026-11-14 to 2026-11-15.",
    "Invented Station 0 reached 39.9°C over 2026-11-14–2026-11-15.",
    "Invented Station 0 reached 39.9°C (cutoff: '2026-11-15').",
])
def test_real_calendar_date_tokens_pass_the_lexical_layer(text):
    assert check_regex(text) == (True, None)
    assert safety.check_truncated_temperature(text) == (True, None)
    assert safety.check_month_repetition(text) == (True, None)


@pytest.mark.parametrize("text,reason", [
    ("Invented Station 0 topped its archive high through 2026-13-45.", "Banned pattern: '-13'"),
    ("Invented Station 0 topped its archive high through 2026-02-30.", "Banned pattern: '-02'"),
    ("Invented Station 0 topped its archive high through 2026-11-31.", "Banned pattern: '-11'"),
    ("Invented Station 0 topped its archive high through 2025-02-29.", "Banned pattern: '-02'"),
    ("Invented Station 0 topped its archive high through 0026-11-15.", "Banned pattern: '-11'"),
    ("Invented Station 0 topped its archive high through 2026-11.", "Banned pattern: '-11'"),
    ("Invented Station 0 topped its archive high through 2026-1-15.", "Banned pattern: '-15'"),
    ("Invented Station 0 topped its archive high through 2026-11-15-03.", "Banned pattern: '-11'"),
    ("Invented Station 0 topped its archive high through x2026-11-15.", "Banned pattern: '-11'"),
    ("Invented Station 0 topped its archive high through 2026-11-15x.", "Banned pattern: '-11'"),
    ("Invented Station 0 topped its archive high through 2026-11-15.5 today.", "Banned pattern: '-11'"),
    ("Invented Station 0 topped its archive high through obs/2026-11-15.", "Banned pattern: '-11'"),
])
def test_malformed_impossible_or_glued_dates_gain_no_exemption(text, reason):
    assert check_regex(text) == (False, reason)


@pytest.mark.parametrize("text,reason", [
    # A hyphen joining two real dates is a range separator; neither glued date is exempt.
    ("Invented Station 0 was hot 2026-11-14-2026-11-15.", "Banned pattern: '-11'"),
    # Year ranges are not calendar dates; unchanged (an en dash already passes).
    ("The 1991-2020 November normal at Invented Town is 3°C.", "Banned pattern: '-2020'"),
    # Event-ID suffixes stay refused next to a real date (mixed tokens).
    ("Tropical Storm Invented-25 made landfall on 2026-11-15.", "Banned pattern: '-25'"),
    ("On 2026-11-15 Typhoon Invented-2026 made landfall.", "Banned pattern: '-2026'"),
    ("Invented Station-12 logged 40°C through 2026-11-15.", "Banned pattern: '-12'"),
])
def test_ranges_and_event_suffixes_keep_their_exact_refusal(text, reason):
    assert check_regex(text) == (False, reason)


@pytest.mark.parametrize("text,reason", [
    ("Invented Station 0 reached 39.9°C through 2026-11-15!", "Banned pattern: '!'"),
    ("Invented Station 0 reached 39.9°C through 2026-11-15 #heat", "Banned pattern: '#heat'"),
    ("BREAKING: Invented Station 0 reached 39.9°C through 2026-11-15.", "Banned pattern: 'BREAKING:'"),
    ("A national average of 39.9°C through 2026-11-15.", "Banned pattern: 'national average'"),
    ("Invented Station 0 reached 39.9°C through 2026-11-15. Wake up.", "Banned pattern: 'Wake up'"),
])
def test_a_date_cannot_hide_any_other_ban(text, reason):
    assert check_regex(text) == (False, reason)


def test_only_the_suffix_rule_is_exempt_inside_a_cited_url():
    # The URL/date exemption covers the event-suffix rule alone; a hashtag in a URL fragment still refuses.
    text = "Invented Station 0 reached 39.9°C through 2026-11-15. https://example.invalid/obs/2026-11-15#heat"
    assert check_regex(text) == (False, "Banned pattern: '#heat'")


def test_length_bound_still_applies_with_a_date():
    text = ROOT_REPRODUCTION + " " + "Invented context." * 20
    assert len(text) > 280
    assert check_regex(text) == (False, f"Too long: {len(text)} chars (max 280)")


@pytest.mark.parametrize("sign", ["-", "−"], ids=["ascii", "unicode"])
@pytest.mark.parametrize("text", [
    "Invented Town fell to {sign}12°C, its lowest November reading through 2026-11-15.",
    "Invented Town fell to {sign}4°F, its lowest November reading through 2026-11-15.",
    "Invented Town fell to {sign}12.5°C on 2026-11-16.",
    "Invented Town fell to {sign}12°C/{sign}10°F through 2026-11-15.",
    "Invented Town peaked at 3°C after a {sign}12°C low on 2026-11-16.",
    "Invented Town ({sign}40°F) set a low through 2026-11-15.",
])
def test_signed_temperatures_high_and_low_pass_alongside_a_date(sign, text):
    assert check_regex(text.format(sign=sign)) == (True, None)


def test_truncated_fahrenheit_guard_still_runs_with_a_date():
    text = "Invented Town reached 9F through 2026-11-15."
    assert check_regex(text) == (True, None)
    assert safety.check_truncated_temperature(text)[0] is False


def test_lexical_pass_still_requires_the_model_verdict(monkeypatch):
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    assert safety.run_safety_pipeline(ROOT_REPRODUCTION) == (False, "safety_unavailable: missing credential")
    calls: list[str] = []

    def refuse(text: str) -> tuple[bool, str]:
        calls.append(text)
        return False, "invented model refusal"
    monkeypatch.setattr(safety, "check_llm", refuse)
    assert safety.run_safety_pipeline(ROOT_REPRODUCTION) == (False, "invented model refusal")
    assert calls == [ROOT_REPRODUCTION]


def test_lexical_refusal_still_comes_before_any_model_call(monkeypatch):
    calls: list[str] = []

    def allow(text: str) -> tuple[bool, None]:
        calls.append(text)
        return True, None
    monkeypatch.setattr(safety, "check_llm", allow)
    assert safety.run_safety_pipeline("Invented Station 0 topped its high through 2026-13-45.")[0] is False
    assert calls == []
