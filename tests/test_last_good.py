from __future__ import annotations

from datetime import date

import pytest

from src.data.last_good import LastGoodReading, read, write
from src.state import _fresh_state


def test_last_good_payload_size_cap():
    bot_state = _fresh_state()

    with pytest.raises(ValueError, match="last-good payload"):
        write(
            bot_state,
            "co2",
            "2026-06-10",
            {"blob": "x" * 2100},
            captured_at="2026-06-11T00:00:00Z",
        )

    assert bot_state["last_good_readings"] == {}


def test_last_good_read_returns_fresh_cached_reading_with_provenance():
    bot_state = _fresh_state()
    write(
        bot_state,
        "co2",
        "2026-06-10",
        {"date": "2026-06-10", "ppm": 429.8},
        captured_at="2026-06-11T00:00:00Z",
    )

    cached = read(bot_state, "co2", max_age_days=3, now=date(2026, 6, 12))

    assert cached == LastGoodReading(
        source_key="co2",
        data_date="2026-06-10",
        captured_at="2026-06-11T00:00:00Z",
        payload={"date": "2026-06-10", "ppm": 429.8},
        from_cache=True,
    )


def test_last_good_read_rejects_stale_cached_reading():
    bot_state = _fresh_state()
    write(
        bot_state,
        "co2",
        "2026-06-10",
        {"date": "2026-06-10", "ppm": 429.8},
        captured_at="2026-06-11T00:00:00Z",
    )

    assert read(bot_state, "co2", max_age_days=1, now=date(2026, 6, 12)) is None
