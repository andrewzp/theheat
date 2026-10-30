"""Source checkpoint regressions. Invented packets/transports; no external access."""
from copy import deepcopy
from datetime import UTC, datetime, date
import json
import time

import pytest

from src.data import regional_observations as regional, gpm_imerg, normals_acquisition, threshold_rebuild
from src.editorial import report_supply
from src.orchestrator.sources import gpm_imerg as scan_runner
from tests.remaining_campaign.test_w05_regional_observed import aemet_packet
from tests.remaining_campaign.test_w06_gpm_regional_scan import CITIES
from tests.remaining_campaign.test_w08_report_portfolio import report
from tests.live_content_harness import trap_network


def test_regional_retained_packet_expires_at_real_builder():
    observation = regional.parse_packet(aemet_packet())["observations"][0]
    assert regional.build_candidate(observation, now=datetime(2026, 10, 30, tzinfo=UTC))[0] is not None
    bundle, reason = regional.build_candidate(observation, now=datetime(2026, 11, 30, tzinfo=UTC))
    assert bundle is None and reason == "time_support_stale"
    assert regional.build_candidate(observation, now=datetime(2026, 10, 28, tzinfo=UTC))[1] == "time_support_future_capture"


def test_scanner_passes_explicit_block_through_real_selector(monkeypatch):
    trap_network(monkeypatch.setattr)
    selected = []
    def fetch(*, cities, max_cities, network_selection=None, **kwargs):
        selected.append(gpm_imerg._network_watchlist(cities, max_cities, scan_date=date(2026, 10, 30),
                                                     selection=network_selection))
        return []
    monkeypatch.setattr(scan_runner.gpm_imerg, "fetch_daily_precip", fetch)
    state = {"run_history": []}
    for i in range(3):
        scan = {}
        scan_runner._scanned_fetch(state, CITIES, max_cities=2, max_workers=1, trace=None, scan=scan)
        state["run_history"].append({"started_at": f"2026-10-30T0{i}:00:00Z", "sources": [
            {"source": "gpm_imerg", "details": {"rainfall_scan": scan}}]})
    assert [[row["city"] for row in rows] for rows in selected] == [
        ["Ficta 0", "Ficta 1"], ["Ficta 2", "Ficta 3"], ["Ficta 4"]]


def test_default_normals_provider_refuses_before_library_import(monkeypatch):
    trap_network(monkeypatch.setattr)
    with pytest.raises(normals_acquisition.NormalsError, match="normals_bounded_transport_unavailable"):
        normals_acquisition.MeteostatProvider()


class SlowResponse:
    status_code = 200
    headers = {}
    def iter_content(self, chunk_size):
        time.sleep(3)
        yield b"invented"
    def close(self):
        self.closed = True


class SlowSession:
    def __init__(self, headers=False):
        self.headers = headers
        self.response = SlowResponse()
    def get(self, *args, **kwargs):
        if self.headers:
            time.sleep(3)
        return self.response


@pytest.mark.parametrize("headers", [True, False])
def test_threshold_deadline_interrupts_delayed_headers_and_body(tmp_path, monkeypatch, headers):
    trap_network(monkeypatch.setattr)
    start = time.monotonic()
    result = threshold_rebuild.fetch_archive(tmp_path / "archive", session=SlowSession(headers),
        max_bytes=1024, deadline_seconds=1, max_retries=0)
    assert result["status"] == "incomplete" and "deadline" in result["reasons"]
    assert time.monotonic() - start < 2
    assert not (tmp_path / "archive").exists()


@pytest.mark.parametrize("value", [None, "", [], 7])
def test_report_full_text_requires_actual_retained_text(value):
    result = report_supply.brief_items(report(retained_text=value))
    assert result["human_impact"] == []
    assert all("full_article_unavailable" in row["reasons"] for row in result["held_claims"])
