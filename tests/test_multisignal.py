"""Phase D — cross-signal writer context (THEHEAT_MULTISIGNAL_CONTEXT, default OFF).

Windowing, the bundle serialization (cache-safe when empty), and the drain gate.
"""

from __future__ import annotations

from copy import deepcopy

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE
from src.two_bot.types import RelatedSignal, StoryBundle, TriageCandidateBundle


def _bundle(*, signal_kind="drought", event_id="e", where="Place", when="2026-06-16",
            country="", facts=None):
    return StoryBundle(
        signal_kind=signal_kind, where=where, when=when, event_id=event_id,
        headline_metric={"label": "x", "value": 1}, current_facts=facts or [],
        country=country,
    )


def _cand(*, event_id, total=80, signal_kind="drought", country="", when="2026-06-16",
          facts=None, source="s"):
    return TriageCandidateBundle(
        bundle=_bundle(signal_kind=signal_kind, event_id=event_id, when=when,
                       country=country, facts=facts),
        score=EditorialScore(category=signal_kind, severity=80, novelty=80, timeliness=80,
                             confidence=80, shareability=80, sensitivity=0, total=total,
                             threshold=60, reasons=[]),
        event_id=event_id, source=source, review_context={}, city="", tweet_date="",
        cooldown_exempt=False, legacy_type=signal_kind, created_at="2026-06-16T12:00:00Z",
    )


# ---------------------------------------------------------------------------
# serialization (cache-safety)
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_omits_empty_country_and_related(self):
        d = _bundle().to_dict()
        assert "country" not in d
        assert "related_signals" not in d  # byte-identical to pre-Phase-D

    def test_to_dict_includes_related_when_present(self):
        b = _bundle(country="ML")
        b.related_signals = [RelatedSignal(
            event_id="r1", signal_kind="fire", where="Mali", when="2026-06-15",
            headline_metric={"label": "FRP", "value": 9}, country="ML")]
        d = b.to_dict()
        assert d["country"] == "ML"
        assert d["related_signals"][0]["event_id"] == "r1"
        assert d["related_signals"][0]["signal_kind"] == "fire"


# ---------------------------------------------------------------------------
# flag
# ---------------------------------------------------------------------------

class TestFlag:
    def test_default_off(self, monkeypatch):
        from src.two_bot.multisignal import multisignal_context_enabled
        monkeypatch.delenv("THEHEAT_MULTISIGNAL_CONTEXT", raising=False)
        assert multisignal_context_enabled() is False

    def test_truthy_on(self, monkeypatch):
        from src.two_bot.multisignal import multisignal_context_enabled
        monkeypatch.setenv("THEHEAT_MULTISIGNAL_CONTEXT", "1")
        assert multisignal_context_enabled() is True


# ---------------------------------------------------------------------------
# windowing
# ---------------------------------------------------------------------------

class TestWindowing:
    def test_same_country_same_window_attaches(self):
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="a", country="ML", when="2026-06-16", signal_kind="drought"),
            _cand(event_id="b", country="ML", when="2026-06-14", signal_kind="fire"),
        ]
        attach_related_signals(q)
        assert [r.event_id for r in q[0].bundle.related_signals] == ["b"]
        assert [r.event_id for r in q[1].bundle.related_signals] == ["a"]

    def test_different_country_excluded(self):
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="a", country="ML", when="2026-06-16"),
            _cand(event_id="b", country="US", when="2026-06-16"),
        ]
        attach_related_signals(q)
        assert q[0].bundle.related_signals == []
        assert q[1].bundle.related_signals == []

    def test_out_of_window_excluded(self):
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="a", country="ML", when="2026-06-16"),
            _cand(event_id="b", country="ML", when="2026-06-01"),  # > 7 days
        ]
        attach_related_signals(q)
        assert q[0].bundle.related_signals == []

    def test_missing_country_excluded_both_directions(self):
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="a", country="ML", when="2026-06-16"),
            _cand(event_id="b", country="", when="2026-06-16"),  # no country
        ]
        attach_related_signals(q)
        assert q[0].bundle.related_signals == []  # b not a valid relation
        assert q[1].bundle.related_signals == []  # b can't host

    def test_country_from_current_facts_fallback(self):
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="a", when="2026-06-16", facts=[{"label": "country", "value": "ML"}]),
            _cand(event_id="b", when="2026-06-16", facts=[{"label": "country", "value": "ML"}]),
        ]
        attach_related_signals(q)
        assert [r.event_id for r in q[0].bundle.related_signals] == ["b"]

    def test_caps_at_max_and_ranks_by_score(self):
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="host", country="ML", total=99),
            _cand(event_id="hi", country="ML", total=95),
            _cand(event_id="mid", country="ML", total=80),
            _cand(event_id="lo", country="ML", total=61),
        ]
        attach_related_signals(q, max_related=2)
        host_related = [r.event_id for r in q[0].bundle.related_signals]
        assert host_related == ["hi", "mid"]  # top 2 by score, distinct

    def test_distinct_event_ids_only(self):
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="same", country="ML", when="2026-06-16"),
            _cand(event_id="same", country="ML", when="2026-06-16"),  # duplicate id
        ]
        attach_related_signals(q)
        assert q[0].bundle.related_signals == []  # same event_id never relates

    def test_global_and_coarse_kinds_excluded(self):
        """codex must-fix #2: global / whole-country kinds participate in neither
        direction (no meaningful regional locus)."""
        from src.two_bot.multisignal import attach_related_signals
        q = [
            _cand(event_id="fire", country="ML", when="2026-06-16", signal_kind="fire"),
            _cand(event_id="glob", country="ML", when="2026-06-16", signal_kind="global_disaster"),
            _cand(event_id="ctry", country="ML", when="2026-06-16", signal_kind="country_high"),
        ]
        attach_related_signals(q)
        # the regional fire gets no related signal (the others are excluded)
        assert q[0].bundle.related_signals == []
        # the global / country-record candidates host nothing either
        assert q[1].bundle.related_signals == []
        assert q[2].bundle.related_signals == []


# ---------------------------------------------------------------------------
# drain gate
# ---------------------------------------------------------------------------

def test_drain_attaches_when_flag_on(monkeypatch):
    from src.orchestrator import common
    bot_state = deepcopy(DEFAULT_STATE)
    bot_state["drafts"] = []
    bot_state["_triage_queue"] = [
        _cand(event_id="a", country="ML", source="s1"),
        _cand(event_id="b", country="ML", signal_kind="fire", source="s2"),
    ]
    captured = {}

    def fake_try(bundle, st, score, **kwargs):
        captured[kwargs.get("event_id")] = list(getattr(bundle, "related_signals", []))
        return False

    monkeypatch.setenv("THEHEAT_MULTISIGNAL_CONTEXT", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    common._drain_and_write_triage_queue(bot_state, {"id": "r", "sources": []})
    assert [r.event_id for r in captured["a"]] == ["b"]


def test_drain_does_not_attach_when_flag_off(monkeypatch):
    from src.orchestrator import common
    bot_state = deepcopy(DEFAULT_STATE)
    bot_state["drafts"] = []
    bot_state["_triage_queue"] = [
        _cand(event_id="a", country="ML", source="s1"),
        _cand(event_id="b", country="ML", signal_kind="fire", source="s2"),
    ]
    captured = {}

    def fake_try(bundle, st, score, **kwargs):
        captured[kwargs.get("event_id")] = list(getattr(bundle, "related_signals", []))
        return False

    monkeypatch.delenv("THEHEAT_MULTISIGNAL_CONTEXT", raising=False)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    common._drain_and_write_triage_queue(bot_state, {"id": "r", "sources": []})
    assert captured["a"] == []  # no related signals attached
