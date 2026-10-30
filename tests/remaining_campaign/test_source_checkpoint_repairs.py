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


def test_retained_report_producer_reaches_ordinary_drain_writer_and_removal_holds(tmp_path, monkeypatch):
    import hashlib
    from src.editorial import newsworthiness, hazard_episodes
    from src.orchestrator import common
    from src.state import DEFAULT_STATE
    from src.two_bot.bundle_capture import capture_bundle
    from src.two_bot.writer import build_writer_user_prompt
    from src.two_bot.types import MemorySlice
    from tests.remaining_campaign.test_w08_portfolio_selection import candidate
    trap_network(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_RETAINED_REPORT_PACKETS", str(tmp_path))
    from dataclasses import replace
    from src.two_bot.intern.disasters import build_global_flood_bundle
    from tests.remaining_campaign.test_w07_episode_admission import _activation
    event = _activation("Red", 100.0)
    row = replace(candidate(event.event_id), bundle=build_global_flood_bundle(event), source="copernicus_ems",
                  review_context={})
    monkeypatch.setenv(hazard_episodes.FLAG, "1")
    assertion = hazard_episodes.copernicus_assertion(event)
    admission = hazard_episodes.admit({}, assertion, source=row.source, event_id=row.event_id,
                                      score=row.score, summary="Invented retained activation")
    hazard_episodes.bind(row.review_context, admission)
    again = deepcopy(row)
    doc = report()
    doc["retained_text_sha256"] = hashlib.sha256(doc["retained_text"].encode()).hexdigest()
    claim = {"claim_id": "c1", "claim_kind": "flood_occurring", "place_id": "pl-ficta", "window": ["2026-10-28", "2026-10-29"],
             "text": "120 households were evacuated", "attribution": "Ficta Civil Protection"}
    ledger = hazard_episodes.empty_ledger()
    ep = hazard_episodes.assign(ledger, assertion)
    joined = hazard_episodes.join_report(ledger, report_sha256=doc["report_sha256"], claim=claim,
        observation={"place_id": "pl-ficta", "window": claim["window"], "evidence_type": "official_flood_report"},
        episode_id=ep["episode_id"], actor="invented-editor")
    packet = {"target_event_id": row.event_id,
        "bundle_sha256": hashlib.sha256(capture_bundle(row.bundle).serialized.encode()).hexdigest(),
        "report": doc, "selected_claim_ids": ["c1"], "episode_ledger": ledger, "join_ids": [joined["join_id"]]}
    (tmp_path / "report.json").write_text(json.dumps(packet))
    prompts = []
    def writer(bundle, state, score, **kwargs):
        prompts.append(build_writer_user_prompt(bundle, MemorySlice()))
        return True
    monkeypatch.setattr(common, "_try_two_bot_draft", writer)
    state = deepcopy(DEFAULT_STATE)
    state["_triage_queue"] = [row]
    common._drain_and_write_triage_queue(state, {"id": "report-test", "sources": []})
    assert len(prompts) == 1 and "attributed_report_statement" in prompts[0]
    item = row.bundle.human_impact[0]
    assert item["value"] == claim["text"] and item["attribution"] == claim["attribution"]
    assert item["report_sha256"] == doc["report_sha256"] and item["claim_id"] == "c1"
    assert item["physical_join_id"] == joined["join_id"]
    # Same physical input, removed join: no later writer can inherit the statement.
    hazard_episodes.remove_join(ledger, joined["join_id"], actor="invented-editor")
    (tmp_path / "report.json").write_text(json.dumps(packet))
    newsworthiness.attach_human_impact([row], [])
    assert not row.bundle.human_impact
    newsworthiness.attach_human_impact([again], [])
    assert not again.bundle.human_impact
    assert "report_join_unavailable" in again.review_context["retained_report_holds"]


@pytest.mark.parametrize("change,reason", [
    ("changed_text", "report_retained_text_identity"),
    ("missing_text", "report_retained_text_identity"),
    ("changed_target", "report_candidate_changed"),
    ("translation", "report_selected_claim_held"),
    ("unsupported_summary", None),
    ("wrong_claim", "report_claim_join_mismatch"),
    ("wrong_reference", "report_join_unavailable"),
    ("removed", "report_join_unavailable"),
])
def test_actual_report_consumer_keeps_claim_identity_and_holds(tmp_path, monkeypatch, change, reason):
    import hashlib
    from src.editorial import newsworthiness, hazard_episodes
    from src.two_bot.bundle_capture import capture_bundle
    from tests.remaining_campaign.test_w08_portfolio_selection import candidate
    trap_network(monkeypatch.setattr)
    monkeypatch.setenv(report_supply.PACKET_DIRECTORY_ENV, str(tmp_path))
    row = candidate("target")
    row.bundle.human_impact = []
    doc = report()
    doc["retained_text_sha256"] = hashlib.sha256(doc["retained_text"].encode()).hexdigest()
    ledger = hazard_episodes.empty_ledger()
    episode = hazard_episodes.assign(ledger, {"hazard": "flood", "issuer": "gdacs", "source_event_id": "target"})
    claim = {"claim_id": "c1", "text": doc["claims"][0]["quote"], "attribution": "Ficta Civil Protection",
             "claim_kind": "flood_occurring", "place_id": "pl-ficta", "window": ["2026-10-28", "2026-10-29"]}
    join = hazard_episodes.join_report(ledger, report_sha256=doc["report_sha256"], claim=claim,
        observation={"place_id": "pl-ficta", "window": claim["window"], "evidence_type": "official_flood_report"},
        episode_id=episode["episode_id"], actor="invented-editor")
    packet = {"target_event_id": row.event_id, "bundle_sha256": hashlib.sha256(
        capture_bundle(row.bundle).serialized.encode()).hexdigest(), "report": doc,
        "selected_claim_ids": ["c1"], "episode_ledger": ledger, "join_ids": [join["join_id"]]}
    if change == "changed_text":
        doc["retained_text"] += " Changed bytes."
    elif change == "missing_text":
        doc.pop("retained_text")
    elif change == "changed_target":
        row.bundle.headline_metric["value"] = 999
    elif change == "translation":
        doc["claims"][0]["original_language"] = "pt"
    elif change == "unsupported_summary":
        doc["claims"][0]["summary"] = "Invented deaths everywhere"
    elif change == "wrong_claim":
        join["claim"]["claim_id"] = "different-claim"
    elif change == "wrong_reference":
        join["report_sha256"] = "d" * 64
    else:
        hazard_episodes.remove_join(ledger, join["join_id"], actor="invented-editor")
    (tmp_path / "report.json").write_text(json.dumps(packet))
    newsworthiness.attach_human_impact([row], [])
    if reason:
        assert row.bundle.human_impact == []
        assert reason in row.review_context["retained_report_holds"]
    else:
        assert row.bundle.human_impact[0]["claim"] == claim["text"]
        assert "Invented deaths" not in json.dumps(row.bundle.human_impact)



def test_supplied_warning_prompt_keeps_selected_attribution_and_original_bytes():
    from tests import warning_helpers as wh
    from src.two_bot.intern.warnings import build_warning_bundle
    from src.two_bot.writer import build_writer_user_prompt
    from src.two_bot.types import MemorySlice
    metadata, original = wh.packet()
    encoded = wh.encode(metadata)
    bundle = build_warning_bundle(encoded, original, nomination=wh.nomination(encoded, original), now=wh.NOW)
    before = deepcopy(bundle.to_dict())
    prompt = build_writer_user_prompt(bundle, MemorySlice())
    assert "qualified_warning_consequence_view" in prompt and wh.WARNING in prompt
    assert bundle.to_dict() == before
    bundle.raw_signal_dump["source_name"] = "Different authority"
    with pytest.raises(ValueError, match="warning_retained_attribution_changed"):
        build_writer_user_prompt(bundle, MemorySlice())
