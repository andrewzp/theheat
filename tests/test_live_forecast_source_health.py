"""Milestone E: the Open-Meteo threshold/baseline hold, forecast coverage isolation and
discovery that is never truncated to the publication cap.

E1 replays the retained first-run outcome through the real consumer: on 2026-10-30
the job restored no cache, then `scripts.threshold_artifacts ensure` printed
`threshold_baseline_asset_unavailable` with `cache_validation: missing` in under a
second (retained JOB123830059450.log), and a read-only release lookup on 2026-10-29
showed `thresholds-latest` with zero assets. No source, release or credential is
touched here: the GitHub client and every response are invented.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import requests

from scripts import threshold_artifacts as artifacts
from src.data import open_meteo, places
from src.state import DEFAULT_STATE
from tests import live_content_harness as h

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


class InventedRelease:
    """The release-metadata seam of artifacts.GitHub; records calls, never downloads real bytes."""

    def __init__(self, assets):
        self.asset_rows, self.calls = assets, []

    def assets(self, tag):
        self.calls.append(("assets", tag))
        return self.asset_rows

    def download(self, tag, name, directory):
        self.calls.append(("download", tag, name))
        (Path(directory) / name).write_bytes(b"invented bytes, not the pinned database")


def manifest():
    return artifacts.read_manifest(ROOT / "data/station_thresholds.version")


def test_pinned_manifest_is_the_legacy_single_sqlite_asset():
    pinned = manifest()
    assert pinned["release"] == "thresholds-latest" and "format" not in pinned
    assert artifacts._asset(pinned) == ("station_thresholds.sqlite", pinned["sha256"], 957_243_392)


def test_retained_outcome_is_a_missing_release_asset_not_a_consumer_fault(tmp_path):
    release, diagnostics = InventedRelease([]), cast(dict[str, str], {})
    with pytest.raises(artifacts.ArtifactError, match="threshold_baseline_asset_unavailable"):
        artifacts.ensure_database(tmp_path / "station_thresholds.sqlite", manifest(), cast(Any, release),
                                  diagnostics=diagnostics)
    assert diagnostics == {"cache_validation": "missing"} and release.calls == [("assets", "thresholds-latest")]


@pytest.mark.parametrize("asset", [
    {"name": "station_thresholds.sqlite", "state": "uploaded", "size": 1},
    {"name": "station_thresholds.sqlite", "state": "starter", "size": 957_243_392},
    {"name": "station_thresholds-other.sqlite.gz", "state": "uploaded", "size": 957_243_392},
], ids=["wrong-size", "not-uploaded", "other-name"])
def test_any_mismatched_asset_is_withheld_before_download(tmp_path, asset):
    release = InventedRelease([asset])
    with pytest.raises(artifacts.ArtifactError, match="threshold_baseline_asset_unavailable"):
        artifacts.ensure_database(tmp_path / "station_thresholds.sqlite", manifest(), cast(Any, release))
    assert ("download", "thresholds-latest", "station_thresholds.sqlite") not in release.calls


def test_a_matching_asset_is_downloaded_and_still_checksum_bound(tmp_path):
    release = InventedRelease([{"name": "station_thresholds.sqlite", "state": "uploaded", "size": 957_243_392}])
    with pytest.raises(artifacts.ArtifactError, match="threshold_download_digest_mismatch"):
        artifacts.ensure_database(tmp_path / "station_thresholds.sqlite", manifest(), cast(Any, release))
    assert release.calls[-1] == ("download", "thresholds-latest", "station_thresholds.sqlite")
    assert not (tmp_path / "station_thresholds.sqlite").exists()  # Never a fabricated baseline.


@pytest.mark.parametrize("outcome", ["failure", "skipped", "cancelled", "unknown", "anything"])
def test_unverified_thresholds_withhold_only_the_ghcn_leg(monkeypatch, outcome):
    from src.orchestrator.sources import open_meteo as runner

    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", outcome)
    monkeypatch.setattr(runner.ghcn, "check_extreme_signals_for_stations",
                        lambda **_k: pytest.fail("no station fetch without a verified baseline"))
    metrics: dict = {}
    assert runner._verified_ghcn_signals(deepcopy(DEFAULT_STATE), metrics) == ([], [])
    assert metrics["status"] == "failed" and metrics["error"] == "threshold_baseline_unavailable"


# ---------------------------------------------------------------- E2: forecast coverage isolation


def block(name: str, zone: str, max_c: float) -> tuple[dict, dict]:
    row = h.catalogue_rows([name])[0]
    place = places.place_for_row(row)
    payload = h.forecast_payload(place["lat"], place["lon"], zone=zone, max_c=max_c, now=T0)
    payload["daily"].update(temperature_2m_min=[max_c - 12], wet_bulb_temperature_2m_max=[max_c - 15])
    return {**row, **place}, payload


def batch_with(monkeypatch, responses):
    calls = []

    def fake_fetch(url, **options):
        calls.append(options["params"]["latitude"])
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(json=lambda: value)
    monkeypatch.setattr(open_meteo, "fetch_with_retry", fake_fetch)
    return calls


def test_one_unusable_block_never_erases_the_other_cities(monkeypatch):
    (riyadh, a), (cairo, b), (delhi, c) = (block("Riyadh", "Asia/Riyadh", 39.2), block("Cairo", "Africa/Cairo", 37.4),
                                          block("Delhi", "Asia/Kolkata", 36.9))
    b.pop("timezone")  # A partial provider block: no valid local day.
    batch_with(monkeypatch, [[a, b, c]])
    out = open_meteo.fetch_forecasts_batch([riyadh, cairo, delhi])
    assert set(out) == {places.cache_key("Riyadh", riyadh["country"], riyadh["lat"], riyadh["lon"]),
                        places.cache_key("Delhi", delhi["country"], delhi["lat"], delhi["lon"])}
    assert all(v["evidence"]["evidence_type"] == "forecast" for v in out.values())


def test_a_misaligned_or_failed_batch_is_withheld_alone(monkeypatch):
    (riyadh, a), (cairo, b) = block("Riyadh", "Asia/Riyadh", 39.2), block("Cairo", "Africa/Cairo", 37.4)
    batch_with(monkeypatch, [[a], requests.ConnectionError("invented outage"), [a, b]])
    assert open_meteo.fetch_forecasts_batch([riyadh, cairo]) == {}  # One block for two places never aligns.
    assert open_meteo.fetch_forecasts_batch([riyadh, cairo]) == {}  # This region's outage only.
    assert len(open_meteo.fetch_forecasts_batch([riyadh, cairo])) == 2  # The next batch is unaffected.


def test_rate_limit_is_saturation_not_an_empty_world(monkeypatch):
    riyadh, _payload = block("Riyadh", "Asia/Riyadh", 39.2)
    limited = requests.HTTPError(response=cast(Any, SimpleNamespace(status_code=429)))
    batch_with(monkeypatch, [limited])
    with pytest.raises(open_meteo.OpenMeteoSaturated):
        open_meteo.fetch_forecasts_batch([riyadh])


def test_discovery_keeps_every_qualified_candidate_and_the_cap_applies_later(monkeypatch):
    from freezegun import freeze_time
    from src.orchestrator.sources.air_quality import run_air_quality

    lahore, delhi = ({**row, **places.place_for_row(row)} for row in h.catalogue_rows(["Lahore", "Delhi"]))
    hazard = {"pm25": 250.0, "dust": 100.0, "pm10": 90.0}
    transport = h.Transport(air_quality={h.coordinate_key(c["lat"], c["lon"]): dict(hazard) for c in (lahore, delhi)})
    transport.install(monkeypatch.setattr)
    monkeypatch.setattr("src.data.air_quality._pacing_sleep", lambda _s: None)
    monkeypatch.setenv("THEHEAT_AQ_DUST_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    state: Any = deepcopy(DEFAULT_STATE)
    run: Any = {"id": "run-e2", "sources": []}
    with freeze_time("2026-10-29T13:00:00Z"):
        run_air_quality(state, run, [lahore, delhi])
    row = next(r for r in run["sources"] if r["source"] == "air_quality")
    assert row["promoted"] == 2 and len(state["_triage_queue"]) == 2  # Both enter; the cap is a later, visible cut.
    assert row["details"]["aq_availability"]["observed_cities"] == 2


def test_retained_source_rows_carry_the_fields_the_health_outcomes_read():
    retained = ROOT.parents[2] / ".gstack/deploy-reports/2026-10-29-one-post-restart/automatic-activation/startup-confirmation/JOB123830059450.log"
    if not retained.exists():
        pytest.skip("Root's retained startup job log is outside this checkout")
    log = retained.read_text(errors="replace")
    assert '"error": "threshold_baseline_asset_unavailable", "cache_validation": "missing"' in log
    assert "THEHEAT_GHCN_THRESHOLD_VERIFICATION: failure" in log
    assert json.dumps({"status": "blocked"})[1:-1] in log
