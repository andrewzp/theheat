"""Phase D — cross-signal writer context (THEHEAT_MULTISIGNAL_CONTEXT, default OFF).

Windowing, the bundle serialization (cache-safe when empty), and the drain gate.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from datetime import UTC, datetime

import pytest

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
    bundle = _bundle(signal_kind=signal_kind, event_id=event_id, when=when, country=country, facts=facts)
    if signal_kind == "fire":
        from tests.fire_source_fixtures import fire_event
        from src.two_bot.intern.fire import build_fire_bundle
        bundle = build_fire_bundle(fire_event(when=datetime.fromisoformat(when).replace(tzinfo=UTC), country=country))
        event_id = bundle.event_id
    return TriageCandidateBundle(
        bundle=bundle,
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
        assert [r.event_id for r in q[0].bundle.related_signals] == [q[1].event_id]
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


@pytest.mark.parametrize("field,value", [
    ("headline_metric", {"label": "x", "value": 2}),
    ("where", "Another place"), ("when", "2026-05-01"),
    ("signal_kind", "country_high"), ("country", "US"),
])
def test_conflicts_withhold_whole_identity_before_window_ranking_and_cap(field, value, caplog):
    from src.two_bot.multisignal import attach_related_signals
    host = _cand(event_id="host", country="ML")
    high = _cand(event_id="ambiguous", country="ML", total=99)
    conflicting = replace(deepcopy(high), score=replace(high.score, total=1))
    setattr(conflicting.bundle, field, value)
    alternate = _cand(event_id="valid", country="ML", total=60)
    queue = [host, high, alternate, conflicting]
    before = deepcopy(queue)
    with caplog.at_level("INFO", logger="src.two_bot.multisignal"):
        attach_related_signals(queue, max_related=1)
    assert [r.event_id for r in host.bundle.related_signals] == ["valid"]
    assert "conflicting_identities=1" in caplog.text
    for actual, original in zip(queue, before, strict=True):
        detached = deepcopy(actual)
        detached.bundle.related_signals = []
        assert detached == original  # All primary observations and scores survive.


def test_identical_summaries_deduplicate_at_best_score_and_keep_stable_ties():
    from src.two_bot.multisignal import attach_related_signals
    host = _cand(event_id="host", country="ML")
    low = _cand(event_id="same", country="ML", total=1)
    high = replace(deepcopy(low), score=replace(low.score, total=95))
    tie = _cand(event_id="tie", country="ML", total=95)
    lower = _cand(event_id="lower", country="ML", total=80)
    # Key order and existing Decimal serialization are not evidence differences.
    high.bundle.headline_metric = {"value": Decimal("1"), "label": "x"}
    low.bundle.headline_metric["value"] = 1.0
    attach_related_signals([host, low, tie, lower, high])
    assert [r.event_id for r in host.bundle.related_signals] == ["same", "tie"]


@pytest.mark.parametrize("bad", [None, "", " ", " alias ", 4, ["alias"]])
def test_missing_or_malformed_identity_clears_host_and_quarantines_valid_alias(bad):
    from src.two_bot.multisignal import attach_related_signals
    host = _cand(event_id="host", country="ML")
    invalid = replace(_cand(event_id="alias", country="ML"), event_id=bad)
    stale = RelatedSignal("old", "fire", "Place", "2026-06-16", {"value": 1})
    invalid.bundle.related_signals = [stale]
    alias = _cand(event_id="alias", country="ML")
    attach_related_signals([host, invalid, alias])
    assert not host.bundle.related_signals
    assert not invalid.bundle.related_signals


def test_mismatched_candidate_and_bundle_ids_quarantine_both_aliases():
    from src.two_bot.multisignal import attach_related_signals
    host = _cand(event_id="host", country="ML")
    mismatch = _cand(event_id="left", country="ML")
    mismatch.bundle.event_id = "right"
    queue = [host, mismatch, _cand(event_id="left", country="ML"),
             _cand(event_id="right", country="ML")]
    attach_related_signals(queue)
    assert not host.bundle.related_signals
    assert not mismatch.bundle.related_signals


@pytest.mark.parametrize("value", [float("nan"), float("inf"), b"bytes", object(), "\ud800"])
def test_malformed_summary_cannot_hide_behind_valid_sibling(value):
    from src.two_bot.multisignal import attach_related_signals
    host = _cand(event_id="host", country="ML")
    valid = _cand(event_id="alias", country="ML")
    malformed = deepcopy(valid)
    malformed.bundle.headline_metric["value"] = value
    attach_related_signals([host, valid, malformed])
    assert not host.bundle.related_signals


@pytest.mark.parametrize("change", ["removed", "country", "date", "global", "identity", "zero"])
def test_recompute_clears_old_context_even_for_ineligible_hosts(change):
    from src.two_bot.multisignal import attach_related_signals
    host, other = [_cand(event_id=e, country="ML") for e in ("host", "other")]
    attach_related_signals([host, other])
    assert host.bundle.related_signals
    queue = [host, other]
    if change == "removed":
        queue.remove(other)
    elif change == "country":
        host.bundle.country = ""
    elif change == "date":
        host.bundle.when = "invalid"
    elif change == "global":
        host.bundle.signal_kind = "enso"
    elif change == "identity":
        host.bundle.event_id = "different"
    attach_related_signals(queue, max_related=0 if change == "zero" else 2)
    assert not host.bundle.related_signals


def test_attached_nested_metrics_are_detached_between_candidates_and_hosts():
    from src.two_bot.multisignal import attach_related_signals
    a, b, other = [_cand(event_id=e, country="ML") for e in ("a", "b", "other")]
    other.bundle.headline_metric["qualifier"] = {"window": ["day"]}
    attach_related_signals([a, b, other])
    a_other = next(r for r in a.bundle.related_signals if r.event_id == "other")
    b_other = next(r for r in b.bundle.related_signals if r.event_id == "other")
    other.bundle.headline_metric["qualifier"]["window"].append("changed source")
    a_other.headline_metric["qualifier"]["window"].append("changed host")
    assert b_other.headline_metric["qualifier"] == {"window": ["day"]}


@pytest.mark.parametrize("limit,expected", [(-1, 0), (0, 0), (1, 1), (99, 2)])
def test_related_context_stays_bounded(limit, expected):
    from src.two_bot.multisignal import attach_related_signals
    queue = [_cand(event_id=str(i), country="ML") for i in range(5)]
    attach_related_signals(queue, max_related=limit)
    assert len(queue[0].bundle.related_signals) == expected


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
    related_id = bot_state["_triage_queue"][1].event_id
    captured = {}

    def fake_try(bundle, st, score, **kwargs):
        captured[kwargs.get("event_id")] = list(getattr(bundle, "related_signals", []))
        return False

    monkeypatch.setenv("THEHEAT_MULTISIGNAL_CONTEXT", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    common._drain_and_write_triage_queue(bot_state, {"id": "r", "sources": []})
    assert [r.event_id for r in captured["a"]] == [related_id]


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
