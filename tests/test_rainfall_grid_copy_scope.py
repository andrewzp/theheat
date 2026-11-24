"""Invented IMERG reports: optional resolution cannot erase single-cell scope.

SDK answers, source bytes and X responses are explicit offline fixtures. This
exercises consumers, not model judgment, actual weather or platform delivery.
"""
# ruff: noqa: F811 -- pytest registers imported fixtures under their argument names.
import json

import pytest

from src.data import rainfall_grid as grid, rainfall_observed as report
from tests.test_rainfall_grid_contract import evidence  # noqa: F401 -- register fixture
from tests.test_rainfall_grid_pipeline import (
    COPY, collect, enabled, gpm_public_url, grid_world, ordinary_grid_world, send,
)  # noqa: F401 -- existing isolated transport and SDK fixtures
from tests.test_rainfall_observed_report import NOW


@pytest.mark.parametrize("scope", ["one grid cell", "a satellite grid cell", "1 grid cell",
    "one 0.1° grid cell", "a 0.1-degree grid cell", "one 0.1 degree grid cell",
    "one satellite 0.1° grid cell"])
def test_source_supported_resolution_preserves_the_same_single_cell(evidence, enabled, scope):
    bundle = grid.build_bundle(evidence, now=NOW)
    text = COPY.replace("one grid cell", scope) + "\n" + gpm_public_url()
    assert report.claim_failures(text, bundle, now=NOW) == []


@pytest.mark.parametrize("scope", ["two 0.1° grid cells", "one 1° grid cell", "one 0.01° grid cell",
    "one 0.1-radian grid cell", "one 0.1° grid cells", "one 0.1° region", "the country"])
def test_other_resolution_plural_or_region_scope_is_still_held(evidence, enabled, scope):
    bundle = grid.build_bundle(evidence, now=NOW)
    assert report.claim_failures(COPY.replace("one grid cell", scope) + "\n" + gpm_public_url(),
        bundle, now=NOW) == ["rainfall_point_scope_required"]


@pytest.mark.parametrize("scope", ["more than one 0.1° grid cell", "half of a 0.1-degree grid cell",
    "at least one 0.1° grid cell", "up to one 0.1° grid cell", "part of one grid cell",
    "less than a satellite grid cell", "not only one 0.1° grid cell", "-1 0.1° grid cell"])
def test_single_cell_words_cannot_hide_partial_plural_or_uncertain_coverage(evidence, enabled, scope):
    bundle = grid.build_bundle(evidence, now=NOW)
    assert report.claim_failures(COPY.replace("one grid cell", scope) + "\n" + gpm_public_url(),
        bundle, now=NOW) == ["rainfall_point_scope_required"]


@pytest.mark.parametrize("scope", ["exactly one 0.1° grid cell", "only one 0.1-degree grid cell"])
def test_explicit_single_whole_cell_still_qualifies(evidence, enabled, scope):
    bundle = grid.build_bundle(evidence, now=NOW)
    assert report.claim_failures(COPY.replace("one grid cell", scope) + "\n" + gpm_public_url(),
        bundle, now=NOW) == []


@pytest.mark.parametrize("verb", ["recorded", "measured", "flooding", "record"])
def test_resolution_qualification_never_clears_an_independent_unsupported_claim(evidence, enabled, verb):
    bundle = grid.build_bundle(evidence, now=NOW)
    text = COPY.replace("one grid cell", "one 0.1° grid cell").replace("estimate.", "estimate " + verb + ".")
    assert report.claim_failures(text + "\n" + gpm_public_url(), bundle, now=NOW) == ["rainfall_unsupported_claim"]


@pytest.mark.parametrize("old,new,reason", [("190.5 mm", "200 mm", "rainfall_amount_changed"),
    ("15 Nov", "14 Nov", "rainfall_date_required"), ("24 hours", "three days", "rainfall_daily_window_required"),
    ("Brazil", "France", "rainfall_country_required"), ("water-equivalent precipitation", "precipitation", "rainfall_quantity_label_required")])
def test_the_new_scope_spelling_keeps_all_original_quantity_and_time_checks(evidence, enabled, old, new, reason):
    bundle = grid.build_bundle(evidence, now=NOW)
    text = COPY.replace("one grid cell", "one 0.1° grid cell").replace(old, new) + "\n" + gpm_public_url()
    assert report.claim_failures(text, bundle, now=NOW) == [reason]


@pytest.mark.parametrize("scope", ["one 0.1° grid cell", "a 0.1-degree grid cell"])
def test_actual_collector_writer_checks_save_and_fixture_sender_keep_resolution(
    monkeypatch, ordinary_grid_world, scope,
):
    transport, state, _run, models, _module = ordinary_grid_world
    models.copy = COPY.replace("one grid cell", scope)
    assert collect(ordinary_grid_world) is state
    assert models.stages() == ["writer", "safety", "fact_check", "critic"], state.get("suppressions")
    [draft] = state["drafts"]
    assert draft["text"] == models.copy + "\n" + gpm_public_url()
    assert draft["approval_binding"]["mode"] == "auto"
    assert len(transport.nasa_calls) == 3
    writer_request = next(request for stage, request in models.requests if stage == "writer")
    prompt = json.dumps(writer_request["messages"])
    assert "Use estimate or estimates; never say recorded or measured." in prompt
    send(monkeypatch, ordinary_grid_world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert transport.x_posts == [draft["text"]]


def test_a_qualified_scope_with_recorded_stops_before_paid_fact_checker_or_critic(ordinary_grid_world):
    transport, state, _run, models, _module = ordinary_grid_world
    models.copy = COPY.replace("one grid cell", "one 0.1° grid cell").replace("estimate.", "estimate recorded.")
    assert collect(ordinary_grid_world) is state
    assert state["drafts"] == []
    assert models.stages() == ["writer"]  # local refusal precedes every paid checker
    rejection = next(row for row in state["suppressions"] if row.get("stage") == "fact_check")
    assert rejection["reasons"] == ["rainfall_unsupported_claim"]
    assert transport.x_posts == []


@pytest.mark.parametrize("scope", ["more than one 0.1° grid cell", "half of a 0.1-degree grid cell"])
def test_actual_collection_refuses_multi_or_partial_cell_before_paid_checks(ordinary_grid_world, scope):
    transport, state, _run, models, _module = ordinary_grid_world
    models.copy = COPY.replace("one grid cell", scope)
    assert collect(ordinary_grid_world) is state
    assert state["drafts"] == [] and models.stages() == ["writer"]
    rejection = next(row for row in state["suppressions"] if row.get("stage") == "fact_check")
    assert rejection["reasons"] == ["rainfall_point_scope_required"]
    assert transport.x_posts == []
