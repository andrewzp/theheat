"""Tests for global ocean SST fetch + marine-heatwave-streak detection."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests


def test_module_exports_public_api():
    from src.data import ocean_sst
    assert hasattr(ocean_sst, "GlobalSSTObservation")
    assert hasattr(ocean_sst, "MarineHeatwaveStreakEvent")
    assert hasattr(ocean_sst, "MILESTONES")
    assert hasattr(ocean_sst, "fetch_global_sst")
    assert hasattr(ocean_sst, "detect_streak_milestone")


def test_milestones_ladder_values():
    from src.data.ocean_sst import MILESTONES
    assert MILESTONES == (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)


def test_milestones_up_to_under_400():
    from src.data.ocean_sst import _milestones_up_to
    assert _milestones_up_to(4) == ()
    assert _milestones_up_to(5) == (5,)
    assert _milestones_up_to(47) == (5, 10, 25)
    assert _milestones_up_to(400) == (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)


def test_milestones_up_to_past_400():
    from src.data.ocean_sst import _milestones_up_to
    assert _milestones_up_to(450) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400, 450,
    )
    assert _milestones_up_to(500) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400, 450, 500,
    )
    assert _milestones_up_to(449) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400,
    )
