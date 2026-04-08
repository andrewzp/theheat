"""Tests for US Drought Monitor data."""

import responses

from src.data.drought import DroughtUpdate, fetch_drought_data

SAMPLE_RESPONSE = [
    {"Name": "Texas", "D0": 10, "D1": 8, "D2": 5, "D3": 15, "D4": 10},
    {"Name": "Oklahoma", "D0": 12, "D1": 6, "D2": 4, "D3": 12, "D4": 8},
    {"Name": "Kansas", "D0": 5, "D1": 3, "D2": 2, "D3": 8, "D4": 5},
    {"Name": "Florida", "D0": 2, "D1": 1, "D2": 0, "D3": 0, "D4": 0},  # Below 10% threshold
    {"Name": "Overall", "D0": 10, "D1": 5, "D2": 3, "D3": 8, "D4": 5},  # Skipped
]


class TestFetchDroughtData:
    @responses.activate
    def test_happy_path_filters_and_sorts(self):
        responses.add(
            responses.GET,
            "https://usdmdataservices.unl.edu/api/StateStatistics/GetDroughtSeverityStatisticsByAreaPercent",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        updates = fetch_drought_data()
        assert len(updates) == 3
        assert all(isinstance(u, DroughtUpdate) for u in updates)
        # Sorted by d3+d4 descending
        assert updates[0].state == "Texas"
        assert updates[0].d3_pct == 15
        assert updates[0].d4_pct == 10
        # Florida excluded (d3+d4 < 10)
        assert all(u.state != "Florida" for u in updates)
        # Overall excluded
        assert all(u.state != "Overall" for u in updates)

    @responses.activate
    def test_api_error_returns_empty(self):
        responses.add(
            responses.GET,
            "https://usdmdataservices.unl.edu/api/StateStatistics/GetDroughtSeverityStatisticsByAreaPercent",
            status=500,
        )
        assert fetch_drought_data() == []

    @responses.activate
    def test_event_id_format(self):
        responses.add(
            responses.GET,
            "https://usdmdataservices.unl.edu/api/StateStatistics/GetDroughtSeverityStatisticsByAreaPercent",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        updates = fetch_drought_data()
        assert updates[0].event_id.startswith("drought_Texas_")

    @responses.activate
    def test_handles_null_drought_values(self):
        data = [
            {"Name": "Nevada", "D0": None, "D1": None, "D2": None, "D3": 20, "D4": None},
        ]
        responses.add(
            responses.GET,
            "https://usdmdataservices.unl.edu/api/StateStatistics/GetDroughtSeverityStatisticsByAreaPercent",
            json=data,
            status=200,
        )
        updates = fetch_drought_data()
        assert len(updates) == 1
        assert updates[0].d3_pct == 20
        assert updates[0].d4_pct == 0
