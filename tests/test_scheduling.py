from copy import deepcopy
from datetime import UTC, datetime

from src.state import DEFAULT_STATE


def test_dead_zone_deferred_to_1230utc():
    from src.editorial.scheduling import defer_to_engagement_window

    original = datetime(2026, 6, 12, 6, 15, tzinfo=UTC)

    assert defer_to_engagement_window(original) == datetime(2026, 6, 12, 12, 30, tzinfo=UTC)


def test_outside_window_unchanged():
    from src.editorial.scheduling import defer_to_engagement_window

    original = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)

    assert defer_to_engagement_window(original) == original


def test_flag_off_no_change(monkeypatch):
    from src.editorial.scoring import score_hot10
    from src.orchestrator import draft_save

    monkeypatch.delenv("THEHEAT_ENGAGEMENT_WINDOW_ENABLED", raising=False)
    monkeypatch.setattr(
        draft_save,
        "_utc_after_minutes_iso",
        lambda minutes: "2026-06-12T06:15:00Z",
    )
    state = deepcopy(DEFAULT_STATE)

    saved = draft_save.save_draft(
        "Hot 10 draft",
        state,
        "hot10",
        "hot10_evt",
        score=score_hot10(9.2, 10, 3),
        candidate_score={"total": 81},
    )

    assert saved is True
    assert state["drafts"][0]["auto_approve_at"] == "2026-06-12T06:15:00Z"


def test_flag_on_deferred_at_draft_save(monkeypatch):
    from src.editorial.scoring import score_hot10
    from src.orchestrator import draft_save

    monkeypatch.setenv("THEHEAT_ENGAGEMENT_WINDOW_ENABLED", "1")
    monkeypatch.setattr(
        draft_save,
        "_utc_after_minutes_iso",
        lambda minutes: "2026-06-12T06:15:00Z",
    )
    state = deepcopy(DEFAULT_STATE)

    saved = draft_save.save_draft(
        "Hot 10 draft",
        state,
        "hot10",
        "hot10_evt",
        score=score_hot10(9.2, 10, 3),
        candidate_score={"total": 81},
    )

    assert saved is True
    assert state["drafts"][0]["auto_approve_at"] == "2026-06-12T12:30:00Z"


def test_boundary_0459_and_1100():
    from src.editorial.scheduling import defer_to_engagement_window

    before = datetime(2026, 6, 12, 4, 59, tzinfo=UTC)
    start = datetime(2026, 6, 12, 5, 0, tzinfo=UTC)
    end = datetime(2026, 6, 12, 11, 0, tzinfo=UTC)

    assert defer_to_engagement_window(before) == before
    assert defer_to_engagement_window(start) == datetime(2026, 6, 12, 12, 30, tzinfo=UTC)
    assert defer_to_engagement_window(end) == end
