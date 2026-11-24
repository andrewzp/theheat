"""Invented observed gusts; no live source, provider or platform calls."""
from copy import deepcopy
from datetime import timedelta
import gzip
import json
from urllib.parse import parse_qs, urlsplit

from freezegun import freeze_time
import pytest

from src.data import awc_gust as gust, awc_observed as awc
from src.orchestrator.metar_report import run_metar_report
from src.two_bot import pipeline, writer
from src.voice import safety
from tests import live_content_harness as h
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_awc_observed import NOW, TARGET, HEADER, catalog, csv_bytes, reports
from tests.test_awc_observed_automatic import sender

REAL_WRITER = writer.write_tweet
BODY = "North Test airport, Norway, reported gusts of 120 km/h (75 mph) at 12:00 UTC on 15 Nov."
GUST_HEADER = HEADER + ["wind_speed_kt", "wind_gust_kt"]


def rows():
    values = reports()
    values[0][0] = values[0][0].replace("00000KT", "27040G65KT")
    return [values[0] + ["40", "65"], values[1] + ["0", ""]]


def metadata():
    return awc.parse_stations(json.dumps(catalog()).encode())


def evidence():
    raw = csv_bytes(rows(), header=GUST_HEADER)
    compressed = (gzip.compress(json.dumps(catalog()).encode(), mtime=0), gzip.compress(raw, mtime=0))
    return gust.nominate(now=NOW, capture=compressed)[0]


def xml(values):
    from xml.etree.ElementTree import Element, SubElement, tostring
    root = Element("response")
    data = SubElement(root, "data", {"num_results": "1"})
    metar = SubElement(data, "METAR")
    row = dict(zip(GUST_HEADER, values[0]))
    for key in ("raw_text", "station_id", "observation_time", "latitude", "longitude",
                "temp_c", "metar_type", "wind_speed_kt", "wind_gust_kt"):
        SubElement(metar, key).text = row[key]
    SubElement(metar, "quality_control_flags")
    return tostring(root)


class Transport(h.Transport):
    def __init__(self):
        super().__init__()
        self.rows = rows()
        self.awc_calls = []
        self.before_reply = None
        self.failure = None

    def send(self, adapter, request, **options):
        parts = urlsplit(request.url)
        url = f"{parts.scheme}://{parts.netloc}{parts.path}"
        if url not in (awc.METARS_URL, awc.STATIONS_URL, awc.HISTORY_URL):
            return super().send(adapter, request, **options)
        assert request.method == "GET" and options["stream"] is True
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if url == awc.HISTORY_URL:
            assert query == {"ids": "TAAA", "format": "xml", "taf": "false", "hours": "2", "date": TARGET}
        else:
            assert query == {}
        self.awc_calls.append((url, query))
        if self.before_reply:
            self.before_reply()
        if self.failure:
            return h._reply(request, self.failure, b"invented source failure")
        body = (gzip.compress(csv_bytes(self.rows, header=GUST_HEADER), mtime=0) if url == awc.METARS_URL else
                gzip.compress(json.dumps(catalog()).encode(), mtime=0) if url == awc.STATIONS_URL else xml(self.rows))
        return h._reply(request, 200, body)


@pytest.fixture
def world(monkeypatch, fresh_state):
    for key, value in {
        "ANTHROPIC_API_KEY": "invented-no-access", "GEMINI_API_KEY": "invented-no-access",
        "THEHEAT_OBSERVED_WEATHER_ONLY": "1", gust.ENABLE_FLAG: "1", awc.ENABLE_FLAG: "0",
        "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
        "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_TRIAGE_ENABLED": "0", "THEHEAT_REFILL_ENABLED": "0",
        "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1", "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-gust-epoch", "THEHEAT_PRODUCTION_PAUSED": "0",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-no-access")
    transport = Transport()
    transport.install(monkeypatch.setattr)
    called = []
    stages = stage_fakes(called, copy=BODY)
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety.run_safety_pipeline)
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    return transport, fresh_state, {"id": "invented-gust-run", "mode": "metar_report", "sources": []}, called, stages


def generate(world):
    with freeze_time(NOW, tick=True):
        run_metar_report(world[1], world[2])


@pytest.mark.parametrize("triage", ["0", "1"])
def test_gust_real_transport_collector_checks_and_sender_once(world, monkeypatch, triage):
    transport, state, run, called, _ = world
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", triage)
    generate(world)
    assert called == ["writer", "safety", "fact_check", "critic"], state.get("suppressions")
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    assert draft["type"] == gust.KIND and draft["event_id"] == "metar_gust_TAAA_2026-11-15"
    assert draft["text"] == BODY + "\n" + gust.citation(evidence()["points"][0])
    assert len(draft["text"]) <= 200
    assert len(transport.awc_calls) == 6
    assert run["sources"][0]["promoted"] == 1
    sender(monkeypatch, world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    sender(monkeypatch, world)
    generate(world)
    assert transport.x_posts == [draft["text"]] and len(state["drafts"]) == 1
    assert called == ["writer", "safety", "fact_check", "critic", "safety"]


@pytest.mark.parametrize("key,value", [
    ("wind_gust_kt", ""), ("wind_gust_kt", "NaN"), ("wind_gust_kt", "49"), ("wind_gust_kt", "101"),
    ("wind_gust_kt", "64"), ("wind_speed_kt", "41"), ("wind_speed_kt", "-1"),
    ("metar_type", "TAF"), ("observation_time", "2026-11-15T12:11:00Z"),
    ("observation_time", "2026-11-15T10:00:00Z"), ("maintenance_indicator_on", "TRUE"),
    ("latitude", "61"), ("temp_c", "-21"),
])
def test_bad_decoded_gust_cannot_nominate(key, value):
    values = rows()
    values[0][GUST_HEADER.index(key)] = value
    assert gust.parse_metars(csv_bytes(values, header=GUST_HEADER), metadata(), now=NOW) == {}


@pytest.mark.parametrize("wind", [
    "00000KT TEMPO 27040G65KT", "00000KT RMK 27040G65KT", "00000KT BECMG 27040G65KT",
    "00000KT NOSIG 27040G65KT", "27040G65MPS", "27040G65KMH", "27040KT", "27040G66KT",
    "27040G65KT 27040G65KT", "99940G65KT", "27040G65KT FM151300 27040G90KT",
])
def test_only_primary_observed_kt_wind_agrees(wind):
    values = rows()
    if wind.startswith("27040G65KT FM"):
        values[0][0] += " FM151300 27040G90KT"
    else:
        values[0][0] = values[0][0].replace("27040G65KT", wind)
    result = gust.parse_metars(csv_bytes(values, header=GUST_HEADER), metadata(), now=NOW)
    # A later TREND does not alter the primary observed gust.
    assert bool(result) == wind.startswith("27040G65KT FM")


def test_duplicate_report_identity_and_columns_are_never_winners():
    values = rows()
    values.append(deepcopy(values[0]))
    for supplied in (values, list(reversed(values))):
        assert gust.parse_metars(csv_bytes(supplied, header=GUST_HEADER), metadata(), now=NOW) == {}
    with pytest.raises(awc.ObservedHeld, match="columns"):
        gust.parse_metars(csv_bytes([rows()[0] + ["65"]], header=GUST_HEADER + ["wind_gust_kt"]), metadata(), now=NOW)


@pytest.mark.parametrize("change", ["type", "schema", "event", "value", "source", "where", "extra", "point-count"])
def test_shared_url_does_not_allow_cross_profile_or_changed_bundle(monkeypatch, change):
    monkeypatch.setenv(gust.ENABLE_FLAG, "1")
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    bundle = gust.build_bundle(evidence(), now=NOW).to_dict()
    if change == "type":
        bundle["signal_kind"] = awc.KIND
    elif change == "schema":
        bundle["raw_signal_dump"]["report_schema"] = awc.SCHEMA
    elif change == "event":
        bundle["event_id"] = "metar_pair_TAAA_TBBB_2026-11-15"
    elif change == "value":
        bundle["headline_metric"]["value"] = 66
    elif change == "source":
        bundle["raw_signal_dump"]["evidence"]["source_url"] += "&taf=true"
    elif change == "where":
        bundle["where"] = "nearby invented city"
    elif change == "extra":
        bundle["raw_signal_dump"]["physical_episode"] = {"id": "invented"}
    else:
        bundle["raw_signal_dump"]["evidence"]["points"].append(deepcopy(bundle["raw_signal_dump"]["evidence"]["points"][0]))
    assert awc.current_bundle_hold(bundle, now=NOW)


@pytest.mark.parametrize("change", ["forecast", "sustained", "record", "impact", "time", "units", "airport", "citation"])
def test_local_claim_refusals_preserve_scope(monkeypatch, change):
    bundle = gust.build_bundle(evidence(), now=NOW)
    body = BODY
    if change == "forecast":
        body += " More is expected."
    elif change == "sustained":
        body = body.replace("gusts", "sustained winds")
    elif change == "record":
        body += " A record."
    elif change == "impact":
        body += " Flights closed."
    elif change == "time":
        body = body.replace("12:00", "13:00")
    elif change == "units":
        body = body.replace("120 km/h (75 mph)", "120 mph")
    elif change == "airport":
        body = body.replace(" airport", "")
    text = body + "\n" + ("https://example.invalid" if change == "citation" else evidence()["source_url"])
    assert gust.claim_failures(text, bundle, now=NOW)


@pytest.mark.parametrize("boundary", ["before-writer", "after-checks", "before-sender"])
def test_source_correction_never_promotes_or_sends(world, monkeypatch, boundary):
    transport, state, _, called, stages = world
    def change():
        transport.rows[0][0] = transport.rows[0][0].replace("G65KT", "G66KT")
        transport.rows[0][-1] = "66"
    if boundary == "before-writer":
        transport.before_reply = lambda: change() if len(transport.awc_calls) == 3 else None
    elif boundary == "after-checks":
        def critic(*args, **kwargs):
            result = stages[3](*args, **kwargs)
            change()
            return result
        monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    generate(world)
    if boundary == "before-sender":
        assert len(state["drafts"]) == 1
        change()
        sender(monkeypatch, world)
        assert state["drafts"][0]["status"] != "posted"
    else:
        assert state["drafts"] == []
    assert called == ([] if boundary == "before-writer" else ["writer", "safety", "fact_check", "critic"])
    assert transport.x_posts == []


@pytest.mark.parametrize("key,value", [
    (gust.ENABLE_FLAG, "0"), ("THEHEAT_OBSERVED_WEATHER_ONLY", "0"),
    ("THEHEAT_CRITIC_ENABLED", "0"), ("THEHEAT_PRODUCTION_PAUSED", "1"),
    ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2"), ("THEHEAT_WRITER_SAMPLES", "3"),
    ("THEHEAT_REFILL_ENABLED", "1"), ("THEHEAT_CRITIC_REVISE_ENABLED", "1"),
    ("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0"), ("GITHUB_REF", "refs/tags/main"),
])
def test_invalid_operation_settings_spend_nothing(world, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    generate(world)
    assert world[0].awc_calls == [] and world[3] == [] and world[1]["drafts"] == []


def test_real_writer_request_contains_only_compact_observed_gust_facts(world, monkeypatch):
    stages = world[4]
    requests = []
    def reply(prompt):
        requests.append(writer.anthropic_writer_request(prompt))
        stages[0]()
        assert '"label": "gust_kmh", "value": 120' in prompt and '"label": "gust_mph", "value": 75' in prompt
        assert '"gust_kt": 65' in prompt and '"airport": "North Test Arpt"' in prompt
        assert "27040G65KT" not in prompt and "NOSIG" not in prompt
        assert "never sustained wind" in prompt
        return json.dumps({"tweet": BODY, "kill_reason": None, "angle_chosen": "observed_gust",
            "era_anchor_used": None, "peer_comparison_used": None, "reasoning": "Invented offline response."})
    monkeypatch.setattr(writer, "_call_writer_provider", reply)
    monkeypatch.setattr(writer, "write_tweet", REAL_WRITER)
    generate(world)
    assert len(requests) == 1 and world[3] == ["writer", "safety", "fact_check", "critic"]
    sender(monkeypatch, world)
    assert len(world[0].x_posts) == 1


def test_retained_station_and_unknown_attempt_are_not_refilled(world):
    transport, state, _, called, _ = world
    state["publish_ledger"]["metar_gust_TAAA_2026-11-14"] = {"phase": "unknown", "at": (NOW - timedelta(days=2)).isoformat()}
    generate(world)
    assert called == [] and state["drafts"] == [] and transport.x_posts == []


def test_both_profiles_share_one_cache_acquisition(world, monkeypatch):
    monkeypatch.setenv(awc.ENABLE_FLAG, "1")
    transport, state, run, called, _ = world
    with freeze_time(NOW):
        from src.orchestrator.sources.awc_observed import run_awc_observed
        run_awc_observed(state, run)
    assert len(transport.awc_calls) == 2 and called == []
    assert run["sources"][0]["details"]["gust_nominated"] == 1
    assert run["sources"][0]["details"]["contrast_nominated"] == 1
    assert {candidate.legacy_type for candidate in state["_triage_queue"]} == {gust.KIND, awc.KIND}


@pytest.mark.parametrize("stage", ["safety", "fact_check", "critic"])
def test_any_required_check_refusal_prevents_a_gust_draft(world, monkeypatch, stage):
    from src.two_bot.types import FactCheckResult, CriticResult
    stages = world[4]
    index = {"safety": 1, "fact_check": 2, "critic": 3}[stage]
    def refuse(*args, **kwargs):
        stages[index](*args, **kwargs)
        return ((False, "invented refusal") if stage == "safety" else
                FactCheckResult(False, ["invented unsupported claim"], "offline refusal") if stage == "fact_check" else
                CriticResult(False, "weak_signal", "offline refusal"))
    owner, name = ((safety, "check_llm") if stage == "safety" else
                   (pipeline.fact_check, "fact_check") if stage == "fact_check" else (pipeline.critic, "critic_review"))
    monkeypatch.setattr(owner, name, refuse)
    generate(world)
    assert stage in world[3] and world[1]["drafts"] == [] and world[0].x_posts == []


@pytest.mark.parametrize("change", ["flag", "text", "kind", "checks", "expired", "unknown"])
def test_changed_review_authority_source_or_delivery_cannot_send(world, monkeypatch, change):
    generate(world)
    state = world[1]
    draft = state["drafts"][0]
    at = NOW + timedelta(minutes=2)
    if change == "flag":
        monkeypatch.setenv(gust.ENABLE_FLAG, "0")
    elif change == "text":
        draft["text"] = draft["text"].replace("120", "140")
    elif change == "kind":
        draft["type"] = awc.KIND
    elif change == "checks":
        draft["review_context"]["two_bot"]["fact_check"]["passed"] = False
    elif change == "expired":
        at = NOW + timedelta(hours=3)
    else:
        state["publish_ledger"][draft["event_id"]] = {"phase": "unknown", "at": NOW.isoformat()}
    sender(monkeypatch, world, at)
    assert world[0].x_posts == [] and draft["status"] != "posted"
    if change == "unknown":
        assert state["publish_ledger"][draft["event_id"]]["phase"] == "unknown"


def test_both_profiles_compete_for_one_paid_slot(world, monkeypatch):
    monkeypatch.setenv(awc.ENABLE_FLAG, "1")
    generate(world)
    assert world[3] == ["writer", "safety", "fact_check", "critic"]
    assert len(world[1]["drafts"]) == 1 and world[1]["drafts"][0]["type"] == gust.KIND


@pytest.mark.parametrize("hours,held", [(23, True), (24, False), (25, False)])
def test_station_spacing_is_rolling_and_not_a_physical_episode(hours, held):
    packet = evidence()
    previous = deepcopy(packet)
    previous["points"][0]["valid_time"] = (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    state = {"drafts": [{"type": gust.KIND, "event_id": "metar_gust_TAAA_previous", "review_context": {
        "two_bot": {"bundle": {"raw_signal_dump": {"evidence": previous}}}}}], "publish_ledger": {}}
    assert bool(gust.retained_station_hold(state, packet, now=NOW)) is held


def test_gust_packet_is_readable_but_cannot_enter_the_temperature_graphic():
    from src.editorial.revisions import fingerprint
    from src.media.awc_graphic_adapter import awc_graphic_spec, AWCGraphicRefused
    bundle = gust.build_bundle(evidence(), now=NOW).to_dict()
    assert all(isinstance(row["value"], (str, int, float)) for row in bundle["current_facts"])
    with pytest.raises(AWCGraphicRefused, match="temperature pair"):
        awc_graphic_spec(bundle, expected_bundle_sha256=fingerprint(bundle))
