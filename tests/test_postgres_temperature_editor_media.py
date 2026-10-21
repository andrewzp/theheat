"""Invented GHCN station comparators at the local editor's media boundary.

The editor explicitly adopts the existing qualified temperature adapter. Positive
fixtures are synthetic GHCN observed-evidence bytes; forecast, compact-reference
and mutated warrants are negative only. No source, provider, hosted or X request;
Gist stays production and publishing stays paused. An available-sample comparison
is never presented as a certified record.

The current local source-selected engine cannot retain a full station bundle (see
the retention test below), so no PostgreSQL draft carries one yet. The native
package and joint-review checks here use the worker's own child and packet code.
"""

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from src.commands import postgres_editor_media as domain
from src.commands import postgres_sourced_generation as generation
from src.commands.media_journal import asset_limits
from src.commands.postgres_candidate_admission import TYPE_ALIASES
from src.commands.preview_media_worker import run_native
from src.commands.schema import CommandError, utc_text
from src.data.temperature_evidence import fingerprint as source_fingerprint
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import draft_identity, invalidate_text
from src.media.evidence_graphic import build_alt_text
from src.media.review_packet import build_media_review_packet, media_review_packet_is_current
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.storage import postgres_projection as p
from tests import test_postgres_sourced_generation as sourced
from tests.test_joint_media_review import make, status
from tests.test_postgres_editor_media import offline_connections as offline_connections
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies

ROOT = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"
FILES = {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}
TEXT = "An invented station reading exceeds its available archive comparator."
# (direction, comparator tier) for the six existing qualified comparator variants.
VARIANTS = {f"{direction}_{tier}": (direction, tier)
            for direction in ("high", "low") for tier in ("all_time", "monthly", "calendar")}
CONTEXT = dict(kind="ghcn_station_day", station_id="USC99000001", valid_date="2026-09-08",
               retrieved_at="2026-09-09T12:00:00Z", reporting_interval_known=False, timezone=None)


def station(direction="high", tier="all_time"):
    from tests.ghcn_graphic_helpers import graphic_bundles
    return graphic_bundles(direction=direction, tier=tier)[-1]


def compact_view(bundle):
    """The actual schema-2 claim projection: selected warrants, tables by reference."""
    from src.two_bot.ghcn_claim_view import json_tree, project
    field = {"high": "all_time_high", "low": "all_time_low"}[bundle.raw_signal_dump["kind"]]
    selection = dict(station_id="USC99000001", signal_date=bundle.when, signal_field=field)
    reference = dict(source_run_id="00000000-0000-4000-8000-000000000001", selection=selection)
    return json_tree(project(bundle, reference, selection).to_dict())


def forecast_snapshot():
    """A dated gridded forecast with its own archive; negative fixture only."""
    from datetime import date
    from src.data.temperature_evidence import forecast_day
    from src.data.world_thresholds import evaluate_city
    from src.two_bot.intern.temperature import build_monthly_high_bundle
    from tests.temperature_helpers import provider_payload
    from tests.test_temperature_time_integrity import baseline
    point, cached = baseline()
    forecast = forecast_day(provider_payload({"daily": {"temperature_2m_max": [40.3]}}, "2026-07-04",
                                             "Asia/Kolkata", 19800), retrieved_at="2026-07-03T23:30:00Z")
    result = evaluate_city("Chennai", "India", forecast, cached, lat=point["lat"], lon=point["lon"],
                           today=date(2026, 7, 3))
    return story_bundle_snapshot(build_monthly_high_bundle(result.monthly_high))


def generation_input(snapshot):
    kind = snapshot["signal_kind"]
    save = dict(legacy_type=TYPE_ALIASES.get(kind, kind), event_id=snapshot["event_id"], score=None, city="",
                tweet_date="", cooldown_exempt=False, review_context=None, evaluator_metadata=None)
    return dict(schema_version=1, source_key="open_meteo", source_revision="invented-station-one",
                captured_at=utc_text(sourced.NOW), useful_until=utc_text(sourced.NOW + timedelta(hours=8)),
                urgent=False, bundle=snapshot, save=save)


def reseal(snapshot):
    """Recompute the source revision so a mutation reaches the deeper warrant guards."""
    evidence = snapshot["raw_signal_dump"]["evidence"]
    evidence["revision_id"] = source_fingerprint(
        {key: value for key, value in evidence.items() if key not in {"retrieved_at", "revision_id"}})
    snapshot["historical_context"]["baseline"] = deepcopy(evidence["baseline"])


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_editor_qualification_adopts_each_station_comparator(variant):
    direction, _ = VARIANTS[variant]
    snapshot = story_bundle_snapshot(station(*VARIANTS[variant]))
    before = deepcopy(snapshot)
    spec, label, context = domain.qualified(snapshot)
    assert snapshot == before
    assert spec["template"] == "temperature_comparator"
    assert (label, context) == ("NOAA GHCN-Daily · station observations", CONTEXT)
    evidence = spec["evidence"]
    assert evidence["synthetic"] is True and evidence["input_binding"]["adapter_version"] == "p31-ghcn-observed-1"
    assert evidence["variable"] == {"high": "daily_maximum_temperature", "low": "daily_minimum_temperature"}[direction]
    assert (evidence["station_id"], evidence["time_basis"], evidence["reporting_interval_known"], evidence["timezone"]) == (
        "USC99000001", "source_calendar_date", False, None)
    assert [point["evidence_type"] for point in evidence["points"]] == ["observed"]
    assert evidence["baseline"]["coverage_kind"] == "available_accepted_source_samples"
    assert "no official record" in evidence["baseline"]["scope"]
    alt = build_alt_text(spec["template"], evidence)
    for qualifier in ("SYNTHETIC DEMONSTRATION", "Station USC99000001", "2026-09-08", "observed",
                      "Evidence as of 2026-09-09T12:00:00Z", "reporting interval and timezone are unknown",
                      "no implied UTC observation time", "does not establish an official or unrestricted record"):
        assert qualifier in alt


@pytest.mark.parametrize("change", [
    "missing", "compact", "forecast", "product", "station", "date", "unit", "qflag", "interval",
    "cutoff", "oversized", "kind", "headline",
])
def test_unqualified_station_source_is_a_typed_editor_refusal(change):
    bundle = station()
    snapshot = story_bundle_snapshot(bundle)
    raw = snapshot["raw_signal_dump"]
    evidence = raw["evidence"]
    if change == "missing":
        del raw["evidence"]
    elif change == "compact":
        snapshot = compact_view(bundle)
    elif change == "forecast":
        evidence["evidence_type"] = "forecast"
    elif change == "product":
        evidence["source_product"] = "openmeteo-era5-daily-v2"
    elif change == "station":
        evidence["station_id"] = "USC99000002"
    elif change == "date":
        evidence["valid_date"] = "2026-09-09"
    elif change == "unit":
        evidence["unit"] = "F"
    elif change == "qflag":
        evidence["variables"]["TMAX"]["qflag"] = "S"
    elif change == "interval":
        evidence["reporting_interval_known"] = True
    elif change == "cutoff":
        evidence["baseline"]["requested_comparison_cutoff"] = "2026-09-08"
    elif change == "oversized":
        # One consistent but unrepresentable display value; never a truncated label.
        raw["new_temp_c"] = snapshot["headline_metric"]["value"] = 1.2345678901234567e100
        evidence["variables"]["TMAX"]["value_c"] = 1.2345678901234567e100
    elif change == "kind":
        snapshot["signal_kind"] = "record_streak"
    else:
        snapshot["headline_metric"]["value"] += 1
    if change in {"forecast", "product", "station", "date", "unit", "qflag", "interval", "cutoff", "oversized"}:
        reseal(snapshot)
    with pytest.raises(CommandError) as error:
        domain.qualified(snapshot)
    assert error.value.code == "graphic_source_unqualified"


def native_package(spec, folder, rasterizer):
    """The editor worker's fixed native child and environment, given invented data only."""
    folder.mkdir(mode=0o700)
    request = dict(spec=spec, output_dir=str(folder), rasterizer=rasterizer)
    run = run_native([sys.executable, "-m", "src.commands.preview_media_worker", "--native-child"],
                     input=p._canonical(request), timeout=45, cwd=ROOT,
                     env={"PATH": "/usr/bin:/bin", "HOME": str(folder), "LANG": "en_US.UTF-8",
                          "PYTHONPYCACHEPREFIX": str(folder / "bytecode")})
    assert run.returncode == 0, run.stderr.decode("utf-8", errors="replace")
    assert len(run.stdout) <= 4096
    manifest_path = Path(json.loads(run.stdout)["manifest"])
    assert manifest_path.is_relative_to(folder) and not manifest_path.is_symlink()
    return manifest_path


@pytest.mark.parametrize("variant", ["high_all_time", "low_calendar"])
def test_native_station_package_and_joint_review_bind_the_comparator(variant, native_dependencies, tmp_path):
    snapshot = story_bundle_snapshot(station(*VARIANTS[variant]))
    spec, _, _ = domain.qualified(deepcopy(snapshot))
    manifest_path = native_package(spec, tmp_path / "native", native_dependencies["rasterizer"])
    manifest = json.loads(manifest_path.read_bytes())
    folder = manifest_path.parent
    limits = asset_limits(manifest)
    assets = {name: (folder / name).read_bytes() for name in limits}
    assert set(manifest["files"]) == set(assets) == FILES
    assert all(0 < len(assets[name]) <= limits[name] for name in limits)
    png = assets["preview.png"]
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (1200, 1500)
    binding = manifest["binding"]
    assert binding["template"] == "temperature_comparator"
    assert binding["renderer"]["adapter_sha256"] == hashlib.sha256(
        (ROOT / "src/media/temperature_graphic_adapter.py").read_bytes()).hexdigest()
    assert manifest["publication_approved"] is False and manifest["synthetic"] is True
    alt = assets["alt.txt"].decode("utf-8")
    assert alt == manifest["alt_text"] + "\n" and manifest["alt_text"] == build_alt_text(spec["template"], spec["evidence"])
    assert "reporting interval and timezone are unknown" in alt and "Station USC99000001" in alt
    svg = " ".join("".join(node.itertext()) for node in ET.fromstring(assets["preview.svg"]).iter(NS + "text"))
    # The PNG is pdftoppm's raster of this PDF; read the PDF's drawn text, not OCR.
    pdf = subprocess.run([str(Path(native_dependencies["rasterizer"]).with_name("pdftotext")), "-enc", "UTF-8",
                          str(folder / "preview.pdf"), "-"], check=True, capture_output=True, encoding="utf-8", timeout=15)
    for drawn in (" ".join(svg.split()), " ".join(pdf.stdout.split())):
        for qualifier in ("SYNTHETIC DATA", "Station USC99000001; interval/timezone unknown", "Current: 2026-09-08",
                          "As of 2026-09-09 12:00Z", "Observed comparator:", "no official record",
                          "Dates are source-calendar labels; reporting interval and timezone unknown."):
            assert qualifier in drawn
        assert "forecast" not in drawn.lower() and "UTC" not in drawn

    draft = dict(id="invented-station-media", event_id=snapshot["event_id"], type=snapshot["signal_kind"],
                 text=TEXT, content_revision=1, decision_revision=1, status="pending",
                 review_context={"two_bot": {"bundle": snapshot}})
    review = dict(draft=draft, expected_draft_identity=draft_identity(draft), editorial_policy=current_editorial_policy(),
                  graphic_spec=spec, renderer_manifest=manifest, png_bytes=png)
    packet = build_media_review_packet(**review)
    assert packet["graphic_binding"]["template"] == "temperature_comparator"
    assert packet["publication_approved"] is False and packet["claim_agreement_status"] == "unreviewed"
    assert media_review_packet_is_current(packet, draft, **{k: v for k, v in review.items() if k != "draft"})
    record = make(review)
    assert status(record, review)["accepted"]
    for change in ("png", "text", "template", "source"):
        altered = deepcopy(review)
        if change == "png":
            altered["png_bytes"] = png + b"changed"
        elif change == "text":
            invalidate_text(altered["draft"], "A different invented station claim.")
            altered["expected_draft_identity"] = draft_identity(altered["draft"])
        elif change == "template":
            altered["renderer_manifest"]["binding"]["template_version"] = "p31-temperature-changed"
        else:
            altered["draft"]["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["station_id"] = (
                "USC99000002")
        assert not media_review_packet_is_current(packet, altered["draft"],
                                                  **{k: v for k, v in altered.items() if k != "draft"})
        assert not status(record, altered)["accepted"]


def test_full_station_bundle_exceeds_current_source_capture_contracts():
    """Why no editor draft can carry one yet: the two existing retention guards."""
    from src.two_bot.bundle_capture import MAX_BUNDLE_BYTES, capture_bundle
    from src.two_bot.candidate_derivation import retained_bundle
    for variant in VARIANTS.values():
        bundle = station(*variant)
        snapshot = story_bundle_snapshot(bundle)
        assert len(p._canonical(snapshot)) > 2 * MAX_BUNDLE_BYTES
        with pytest.raises(ValueError, match="bundle_capture_too_large"):
            capture_bundle(bundle)
        # StoryBundle construction re-projects temperature evidence facts.
        with pytest.raises(ValueError, match="retained_check_input_roundtrip_changed"):
            retained_bundle(snapshot)


def test_current_source_retention_refuses_every_station_shape_before_any_draft(store):
    """P31-T2 contract conflict at the actual command boundary, recorded not bypassed.

    A full qualified station bundle, a compact schema-2 claim reference and a dated
    forecast all refuse before any brief, job, candidate or draft exists. Replace
    this with the positive editor journey once a source contract admits the bundle.
    """
    def refused(snapshot):
        with pytest.raises(CommandError) as error:
            store.retain_generation_input(generation_input(snapshot))
        return error.value.code

    def briefs():
        with store.projections._connection() as c:
            return c.execute("SELECT count(*) FROM theheat_projection.fields WHERE namespace=%s",
                             (generation.INPUT,)).fetchone()[0]

    before = briefs()
    codes = {name: refused(story_bundle_snapshot(station(*variant))) for name, variant in VARIANTS.items()}
    assert codes == dict.fromkeys(VARIANTS, "generation_evidence_not_ready")
    assert refused(compact_view(station())) == "generation_input_invalid"
    assert refused(forecast_snapshot()) == "generation_evidence_not_ready"
    assert briefs() == before
