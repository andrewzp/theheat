"""Exact CRW packet capture at the existing collector fetch (explicit, default-off).

Every scenario records the collector's exact HTTP request URLs in order (one fetch
worker, so submission order is the request order) and compares retention off with
retention on: capture must add, repeat or reorder no request and must leave every
health/report projection identical. Retained packets are the served bytes verbatim
and render through the real store-backed CRW preview. Invented bytes; no network.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from typing import Any, cast

from freezegun import freeze_time
import pytest
import requests

from src.data import crw_contract as contract, ocean_sst_anomaly as sst
from src.data.crw_regions import REGION_REGISTRY, _build_url
from src.editorial.revisions import fingerprint
from src.media import crw_capture, gist_assets, gist_assets_postgres as pg, gist_crw_media
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.state import DEFAULT_STATE
from src.two_bot.bundle_capture import MAX_BUNDLE_BYTES
from src.two_bot.intern.marine_crw import build_regional_sst_anomaly_bundle
from tests import gist_pg_protocol_fixture as fx
from tests.crw_fixtures import DAY, csv_body, metadata_body, response

NOW = "2026-06-16T12:00:00Z"
HOT = {"caribbean": 3.6, "mediterranean": 2.6}  # Tier 2 and tier 1 invented anomalies.


def scripted(monkeypatch, *, csv=None, metadata=None):
    """Serve invented bytes by exact URL; record every request in order."""
    log: list[str] = []
    served: dict[str, bytes] = {}
    csv = csv or {}

    def fetch(url, **_options):
        log.append(url)
        if url == contract.METADATA_URL:
            if isinstance(metadata, Exception):
                raise metadata
            served["metadata"] = metadata if isinstance(metadata, bytes) else metadata_body()
            return response(served["metadata"])
        region = next((r for r in REGION_REGISTRY if _build_url(r) == url), None)
        if region is None:  # The native fallback leg: an invented outage, still logged in order.
            raise requests.ConnectionError("invented native outage")
        body = csv.get(region.slug, csv_body(region, value=HOT.get(region.slug, 0.4)))
        if isinstance(body, Exception):
            raise body
        served[region.slug] = body
        return response(body)

    monkeypatch.setattr(sst, "fetch_with_retry", fetch)
    monkeypatch.setattr(sst, "_FETCH_WORKERS", 1)
    return log, served


def collect(monkeypatch, capture, **script):
    log, served = scripted(monkeypatch, **script)
    with freeze_time(NOW):
        collection = sst.collect_all_regions(strict=False, **({"capture_packets": True} if capture else {}))
    return log, served, collection


def compare_base_head(monkeypatch, **script):
    base_log, _, base = collect(monkeypatch, False, **script)
    head_log, served, head = collect(monkeypatch, True, **script)
    assert head_log == base_log  # Exact URLs, order and count.
    assert head.details() == base.details() and head.readings == base.readings
    assert base.captured is None and "csv_utf8" not in json.dumps(head.details())
    return head_log, served, head


def events(collection):
    return sst.detect_regional_sst_anomaly_events(collection.readings, {})


def test_retention_is_explicit_and_default_off():
    assert not crw_capture.enabled({}) and not crw_capture.enabled({crw_capture.ENV: "true"})
    assert not crw_capture.enabled({crw_capture.ENV: "0"}) and crw_capture.enabled({crw_capture.ENV: "1"})
    assert crw_capture.writer({}) == (None, "store_unavailable")
    # The reader selection never yields an insert capability.
    assert crw_capture.writer({gist_assets.ENV: "sqlite:/tmp/x.sqlite3"}) == (None, "store_unavailable")


def test_primary_capture_adds_no_request_and_retains_the_served_bytes(monkeypatch, tmp_path):
    log, served, collection = compare_base_head(monkeypatch)
    assert log == [contract.METADATA_URL, *(_build_url(r) for r in REGION_REGISTRY)]
    assert set(collection.captured.csv) == set(HOT)  # Candidates only; quiet regions keep nothing.
    store = gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3")
    found = {e.region_slug: e for e in events(collection)}
    assert set(found) == set(HOT)
    for slug, event in found.items():
        retained, outcome = crw_capture.retain_for_event(event, collection.captured, store)
        assert outcome == "retained" and retained.retained_packet["schema_version"] == 1
        packet = gist_assets.get_document(store, retained.retained_packet["artifact_sha256"])
        assert packet["csv_utf8"].encode() == served[slug] and packet["metadata_utf8"].encode() == served["metadata"]
        assert packet["csv_retrieved_at"] == event.provenance["retrieved_at"] == NOW
        assert packet["metadata_retrieved_at"] == event.provenance["primary_metadata"]["retrieved_at"] == NOW
        assert retained.retained_packet["packet_sha256"] == fingerprint(packet)
        bundle = story_bundle_snapshot(build_regional_sst_anomaly_bundle(retained))
        assert bundle["raw_signal_dump"]["retained_packet"] == retained.retained_packet
        assert "csv_utf8" not in json.dumps(bundle) and len(json.dumps(bundle).encode()) <= MAX_BUNDLE_BYTES
        reader = gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3", writable=False)
        prepared = gist_crw_media.prepare_media(bundle, reader, retained.retained_packet["artifact_sha256"])
        assert prepared["descriptor"]["source"]["packet_artifact_sha256"] == retained.retained_packet["artifact_sha256"]
        # Idempotent: an identical retry retains the same identity.
        assert crw_capture.retain_for_event(event, collection.captured, store) == (retained, "retained")
    # An unretained event's bundle is byte-identical to the pre-capture bundle.
    plain = found["caribbean"]
    assert "retained_packet" not in story_bundle_snapshot(build_regional_sst_anomaly_bundle(plain))["raw_signal_dump"]


def test_fallback_leg_is_never_relabelled_as_a_primary_packet(monkeypatch):
    timeout = requests.Timeout("invented primary timeout")
    region = next(r for r in REGION_REGISTRY if r.slug == "caribbean")
    native = []

    def fallback(*, regions, min_valid_cells, today):
        native.append([r.slug for r in regions])
        reading = sst.RegionalSSTReading(region.slug, region.display_name, DAY, 3.6, 2, 300,
                                         source_leg=sst.NOAA_STAR_SSTA_LEG)
        return [sst.RegionalSSTSample(region.slug, "candidate", sst.NOAA_STAR_SSTA_LEG, product_date=DAY,
                                      total_cells=300, valid_cells=300, excluded_cells=0, reading=reading)]
    monkeypatch.setattr(sst, "_fetch_noaa_star_ssta_samples_strict", fallback)
    log, _served, collection = compare_base_head(monkeypatch, csv={r.slug: timeout for r in REGION_REGISTRY})
    assert len(log) == 1 + len(REGION_REGISTRY) and len(native) == 2  # Base and head each ran it once.
    assert collection.captured.csv == {}
    store = Recording()
    (event,) = events(collection)
    assert crw_capture.retain_for_event(event, collection.captured, store) == (event, "unsupported_source_leg")
    relabelled = replace(event, source_leg=None)
    assert crw_capture.retain_for_event(relabelled, collection.captured, store)[1] == "source_unqualified"
    assert store.writes == []


class Recording:
    """A writer that records any attempted write (none is expected)."""

    def __init__(self):
        self.writes = []

    def put_many(self, blobs):
        self.writes.append(blobs)
        raise AssertionError("no write expected")


@pytest.mark.parametrize("case", ["insufficient", "stale", "metadata_outage"])
def test_unqualified_samples_capture_nothing(monkeypatch, case):
    caribbean = next(r for r in REGION_REGISTRY if r.slug == "caribbean")
    scripts: dict[str, dict[str, Any]] = {
              "insufficient": {"csv": {"caribbean": csv_body(caribbean, selected={(10.0, -80.0): 3.6})}},
              "stale": {"csv": {"caribbean": csv_body(caribbean, day="2026-06-01")}},
              "metadata_outage": {"metadata": requests.ConnectionError("invented metadata outage")}}
    script = scripts[case]
    log, _served, collection = compare_base_head(monkeypatch, **script)
    assert "caribbean" not in (collection.captured.csv if collection.captured else {})
    if case == "metadata_outage":
        assert log[0] == contract.METADATA_URL and collection.captured is None
        # Only the existing native leg's own index walk follows (pinned base == head above).
        assert len(log) > 1 and all(url.startswith(sst.NOAA_STAR_SSTA_BASE_URL) for url in log[1:])


def test_non_utf8_or_oversized_packets_hold_without_writing(monkeypatch, tmp_path):
    _log, _served, collection = compare_base_head(monkeypatch)
    (event,) = [e for e in events(collection) if e.region_slug == "caribbean"]
    body, at = collection.captured.csv["caribbean"]
    store = gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3")
    swapped = replace(collection.captured, csv={"caribbean": (body + b"\n", at)})
    assert crw_capture.retain_for_event(event, swapped, store)[1] == "packet_unavailable"
    big = replace(collection.captured, metadata_body=b" " * 100_001)
    monkeypatch.setitem(event.provenance["primary_metadata"], "response_bytes", 100_001)
    assert crw_capture.packet_for(event, big) == (None, "packet_too_large")
    assert crw_capture.retain_for_event(event, None, store)[1] == "packet_unavailable"


@pytest.mark.parametrize("fault,outcome", [("unavailable", "store_unavailable"), ("timeout", "store_unavailable"),
                                           ("commit_failure", "retention_unknown"),
                                           ("lost_commit_ack", "retention_unknown"), (None, "retained")])
def test_store_outcomes_through_the_insert_only_postgres_writer(monkeypatch, tmp_path, fault, outcome):
    for name in [n for n in __import__("os").environ if n.startswith("PG")]:
        monkeypatch.delenv(name)
    _log, _served, collection = compare_base_head(monkeypatch)
    (event,) = [e for e in events(collection) if e.region_slug == "caribbean"]
    backing = fx.create(tmp_path / "protocol.sqlite3")
    writer = pg.PostgresMediaStore(pg.parse_dsn(fx.WRITER_DSN), role="writer", driver=fx.module(backing))
    fx.set_fault(backing, fault or "")
    retained, got = crw_capture.retain_for_event(event, collection.captured, writer)
    assert got == outcome
    assert (retained.retained_packet is not None) is (outcome == "retained")  # Unknown is never success.
    reader = pg.PostgresMediaStore(pg.parse_dsn(fx.READER_DSN), role="reader", driver=fx.module(backing))
    with pytest.raises(gist_assets.MediaStoreError):
        reader.put_many([b"x"])  # The preview/sender capability has no write path.


def _runner(monkeypatch, tmp_path, env, **script):
    from src.orchestrator.sources import ocean_sst_anomaly as runner
    for name in (crw_capture.ENV, gist_assets.WRITER_ENV, gist_assets.WRITER_DSN_ENV, gist_assets.ENV):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    log, _served = scripted(monkeypatch, **script)
    monkeypatch.setattr(runner, "_should_draft", lambda *_a: True)
    bot_state, run = deepcopy(DEFAULT_STATE), cast(dict[str, Any], {"sources": []})
    with freeze_time(NOW):
        runner.run_ocean_sst_anomaly(bot_state, run)
    (source,) = [s for s in run["sources"] if s.get("source") == "ocean_sst_anomaly" or s.get("name") == "ocean_sst_anomaly"]
    return log, bot_state, source


def _dumps(bot_state):
    return {c.event_id: c.bundle.raw_signal_dump if hasattr(c.bundle, "raw_signal_dump") else c.bundle["raw_signal_dump"]
            for c in bot_state["_triage_queue"]}


def test_runner_attaches_only_the_reference_and_holds_on_store_failure(monkeypatch, tmp_path):
    off_log, off_state, off = _runner(monkeypatch, tmp_path, {})
    store = tmp_path / "media.sqlite3"
    on_log, on_state, on = _runner(monkeypatch, tmp_path, {crw_capture.ENV: "1", gist_assets.WRITER_ENV: f"sqlite:{store}"})
    held_log, held_state, held = _runner(monkeypatch, tmp_path, {crw_capture.ENV: "1"})  # Enabled, no writer.
    assert off_log == on_log == held_log
    assert "media_retention" not in off["details"]
    strip = {k: v for k, v in on["details"].items() if k != "media_retention"}
    assert strip == off["details"] == {k: v for k, v in held["details"].items() if k != "media_retention"}
    assert on["details"]["media_retention"] == {**crw_capture.summary(Counter()), "retained": 2}
    assert held["details"]["media_retention"] == {**crw_capture.summary(Counter()), "store_unavailable": 2}
    off_dumps, on_dumps, held_dumps = _dumps(off_state), _dumps(on_state), _dumps(held_state)
    assert off_dumps == held_dumps and set(on_dumps) == set(off_dumps) and len(on_dumps) == 2
    for event_id, dump in on_dumps.items():
        reference = dump["retained_packet"]
        assert set(reference) == crw_capture.REFERENCE_KEYS
        assert {k: v for k, v in dump.items() if k != "retained_packet"} == off_dumps[event_id]
        assert gist_assets.SQLiteMediaStore(store, writable=False).get(reference["artifact_sha256"], limit=600_000)
    assert "csv_utf8" not in json.dumps(on_state, default=str)
