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


def _nws_bundle(identifier, *, area="Ficta Coast", reference=None):
    from tests.remaining_campaign.test_w04_nws_cli_journey import feed, NOW
    from src.data import nws_alerts
    from src.two_bot.intern.disasters import build_severe_weather_bundle
    from src.media.published_radar import source_envelope
    feature = json.loads(feed())["features"][0]
    props = feature["properties"]
    props["id"], props["areaDesc"] = identifier, area
    props["references"] = [] if reference is None else [{"identifier": reference, "sender": "NWS", "sent": props["sent"]}]
    return build_severe_weather_bundle(nws_alerts.SevereWeatherAlert(
        event_type=props["event"], area=area, severity=props["severity"], description=props["description"], headline=props["headline"],
        sender_name=props["senderName"], event_id="nws_" + identifier,
        source_evidence=source_envelope(feature, NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))))


def test_nws_identity_uses_official_chain_and_preserves_unknown_delivery():
    from src.editorial import warning_automatic as wa
    def draft(bundle, id):
        return {"id": id, "type": "severe_weather", "event_id": bundle.event_id,
                "review_context": {"two_bot": {"bundle": bundle.to_dict()}}}
    old = _nws_bundle("urn:old")
    state = {"drafts": [draft(old, "old")], "publish_ledger": {old.event_id: {"phase": "submitted"}}}
    assert wa.episode_hold(draft(_nws_bundle("urn:independent"), "new"), state) is None
    assert wa.episode_hold(draft(_nws_bundle("urn:update", area="Expanded Ficta Coast", reference="urn:old"),
                                 "updated"), state) == "warning_prior_delivery_unknown"
    middle = _nws_bundle("urn:update", area="Expanded Ficta Coast", reference="urn:old")
    state["drafts"].append(draft(middle, "middle"))
    newest = _nws_bundle("urn:newest", area="Ficta Inland", reference="urn:update")
    assert wa.episode_hold(draft(newest, "newest"), state) == "warning_prior_delivery_unknown"
    assert wa.runner_fence("severe_weather", newest, state) == "warning_prior_delivery_unknown"
    state["drafts"] = [draft(middle, "middle")]
    assert wa.runner_fence("severe_weather", newest, state) == "warning_prior_delivery_unknown"


def test_warning_writer_view_is_derived_without_mutating_retained_bundle():
    from tests.remaining_campaign.test_w04_warning_automatic import _bundle
    from src.two_bot.types import StoryBundle, MemorySlice
    from src.two_bot.intern.nhc_advisory import RetainedAdvisory
    from src.two_bot.writer import build_writer_user_prompt
    bundle = StoryBundle(**_bundle())
    before = deepcopy(bundle.to_dict())
    prompt = build_writer_user_prompt(bundle, MemorySlice())
    assert "qualified_warning_consequence_view" in prompt and "forecast_threat" in prompt
    assert bundle.to_dict() == before
    RetainedAdvisory(bundle)
    bundle.raw_signal_dump["nhc_advisory"]["hazard"]["text"] = "invented consequence"
    with pytest.raises(Exception):
        build_writer_user_prompt(bundle, MemorySlice())


def test_actual_warning_builder_can_be_selected_without_observed_harm(monkeypatch):
    from src.orchestrator import portfolio_selection
    from tests.remaining_campaign.test_w08_portfolio_selection import candidate
    from tests.remaining_campaign.test_w04_warning_automatic import _bundle
    from src.two_bot.types import StoryBundle
    from dataclasses import replace
    bundle = StoryBundle(**_bundle())
    row = replace(candidate("warning"), bundle=bundle, event_id=bundle.event_id, review_context={})
    result = portfolio_selection.plan([row], allowance=1)
    assert len(result["selected"]) == 1
    evidence = portfolio_selection.evidence_for(row)
    vector = report_supply.importance_vector(evidence)
    assert evidence["evidence_type"] == "official_warning" and vector["impact"] is None
    assert vector["rarity"] is None
