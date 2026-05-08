from datetime import date


def test_threshold_watermark_refuses_to_advance_past_missing_diff():
    from scripts.update_thresholds_incremental import _resolve_new_watermark

    dates_to_fetch = [
        date(2026, 5, 1),
        date(2026, 5, 2),
        date(2026, 5, 3),
    ]
    successful_dates = [date(2026, 5, 1), date(2026, 5, 3)]

    assert _resolve_new_watermark(
        dates_to_fetch=dates_to_fetch,
        successful_dates=successful_dates,
        current_watermark=date(2026, 4, 30),
    ) == date(2026, 5, 1)


def test_threshold_watermark_advances_when_successes_are_contiguous():
    from scripts.update_thresholds_incremental import _resolve_new_watermark

    assert _resolve_new_watermark(
        dates_to_fetch=[date(2026, 5, 1), date(2026, 5, 2)],
        successful_dates=[date(2026, 5, 1), date(2026, 5, 2)],
        current_watermark=date(2026, 4, 30),
    ) == date(2026, 5, 2)
