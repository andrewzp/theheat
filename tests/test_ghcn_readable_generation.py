"""Actual writer/check request builders over complete readable invented evidence."""

from copy import deepcopy
import json

from freezegun import freeze_time
import pytest

from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from src.two_bot.ghcn_readable_warrant import decode_wire
from src.two_bot.json_utils import _iter_json_spans
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.test_observed_copy_guard_journey import _models


def _request_bundles(value):
    if isinstance(value, str):
        for start, end in _iter_json_spans(value):
            try:
                item = json.loads(value[start:end])
            except ValueError:
                continue
            if isinstance(item, dict) and "signal_kind" in item and "raw_signal_dump" in item:
                yield item
    elif isinstance(value, dict):
        for child in value.values():
            yield from _request_bundles(child)
    elif isinstance(value, list):
        for child in value:
            yield from _request_bundles(child)


@pytest.mark.parametrize(
    "direction,tier", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar")]
)
def test_complete_readable_warrant_reaches_actual_sdk_checks_and_pending_metadata(
    monkeypatch, direction, tier
):
    bundle = graphic_bundles(direction=direction, tier=tier)[-1]
    reading = "reached 42.2°C" if direction == "high" else "fell to -22.2°C"
    comparison = {
        "all_time": f"its archive {direction}",
        "monthly": "a September record",
        "calendar": "a record for 8 September",
    }[tier]
    text = (
        f"Graphic Fixture {reading} on 8 September, {comparison} "
        "in the available GHCN archive through 2026-09-07."
    )
    models = _models(monkeypatch, copy=text)
    outcome = {}
    with freeze_time("2026-09-09T12:00:00Z", tick=True):
        result = pipeline.generate_draft(bundle, deepcopy(DEFAULT_STATE), result_out=outcome)
    assert result is not None, outcome
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    assert result["text"] == text
    retained = result["two_bot_metadata"]["bundle"]
    assert retained["raw_signal_dump"]["evidence"]["baseline"]["calendar_table"]["rows"]
    expanded = decode_wire(retained)
    assert expanded["raw_signal_dump"]["evidence"]["station_id"] == "USC99000001"
    for stage, request in models.requests:
        if stage != "safety":
            actual = list(_request_bundles(request))
            expected = json.dumps(
                retained, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            assert actual and all(
                json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                == expected
                for item in actual
            ), stage
