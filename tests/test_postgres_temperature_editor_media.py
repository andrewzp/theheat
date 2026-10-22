"""Invented GHCN station comparators at the local editor's media boundary.

The editor explicitly adopts the existing qualified temperature adapter. Positive
fixtures are synthetic GHCN observed-evidence bytes; forecast, compact-reference
and mutated warrants are negative only. No source, provider, hosted or X request;
Gist stays production and publishing stays paused. An available-sample comparison
is never presented as a certified record.

The schema-1 source-selected engine cannot retain a full station bundle (see the
retention limits below). Saved drafts instead carry the compact schema-2 claim
view; the editor and its saved checks resolve the full evidence locally from
operator-retained GHCN inputs. Those journeys use the actual engine, native
worker, check executor and authenticated local HTTP with invented model fixtures.
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
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
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
from tests.workflow_clock import positive_workflow_clock as positive_workflow_clock

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
    """Why a saved draft carries the compact claim: the two retention guards hold."""
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


def test_schema1_retention_refuses_every_station_shape_before_any_draft(store):
    """Schema-1 retention limits at the actual command boundary, never bypassed.

    A full qualified station bundle, a compact claim reference and a dated forecast
    all refuse before any brief, job, candidate or draft exists. Compact claims
    enter only through the operator-owned schema-2 resolver (journeys below).
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


# --- Compact saved GHCN claims resolved from local operator-retained evidence ---

CLAIM_FIELDS = {("high", "all_time"): "all_time_high", ("high", "monthly"): "monthly_high",
                ("high", "calendar"): "calendar_date_high", ("low", "all_time"): "all_time_low",
                ("low", "monthly"): "monthly_low", ("low", "calendar"): "calendar_date_low"}


def claim_reference(full, field):
    """The schema-2 reference shape with invented source pins; a full-story hash binds it."""
    from src.storage import ghcn_runtime_inputs as runtime
    from src.storage.scientific_supply import NAMESPACE
    from src.two_bot.ghcn_claim_view import json_tree
    run = "00000000-0000-4000-8000-000000000001"
    evidence = full.raw_signal_dump["evidence"]

    def pin(name):
        return hashlib.sha256(("invented-" + name).encode()).hexdigest()

    return dict(schema_version=1, kind="ghcn_claim_view_v1", scope="selected_claim_warrants", source_run_id=run,
        source_result=dict(namespace=runtime.RESULT, snapshot_id="run:" + run, sha256=pin("result")),
        runtime_input=dict(namespace=runtime.INPUT, snapshot_id="run:" + run, sha256=pin("input")),
        scientific_supply=dict(namespace=NAMESPACE, snapshot_id="run:" + run, sha256=pin("supply")),
        selection=dict(station_id=evidence["station_id"], signal_date=full.when, signal_field=field),
        member_sha256=pin("member"),
        full_story=dict(codec="revision-fingerprint-v1-json-default", sha256=fingerprint(json_tree(full.to_dict()))),
        observation_revision=evidence["revision_id"], baseline_revision=evidence["baseline"]["revision_id"],
        baseline_artifact=dict(database_sha256=pin("database"), manifest_sha256=pin("manifest")),
        original_archives=[dict(kind="station_archive", key=evidence["station_id"], retrieved_at=evidence["retrieved_at"],
                                status="success", raw_sha256=evidence["baseline"]["source_payload_sha256"], failure_code=None)])


def claim_pair(full, field):
    """A saved compact view built by the actual schema-2 projection of ``full``."""
    from src.two_bot.ghcn_claim_view import json_tree, project
    reference = claim_reference(full, field)
    return json_tree(project(full, reference, reference["selection"]).to_dict()), json_tree(full.to_dict())


def claim_spec(view, full, full_json):
    from src.media.temperature_graphic_adapter import temperature_claim_graphic_spec
    return temperature_claim_graphic_spec(view, full, expected_full_sha256=fingerprint(full_json), synthetic=True)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_compact_claim_binds_saved_view_full_evidence_and_source_reference(variant):
    from src.media.evidence_graphic import validate_graphic
    from src.two_bot.ghcn_claim_view import project_tree
    direction, tier = VARIANTS[variant]
    full = station(direction, tier)
    view, full_json = claim_pair(full, CLAIM_FIELDS[(direction, tier)])
    reference = view["raw_signal_dump"]["ghcn_claim_view"]
    # The JSON twin replays the saved view without the mutating StoryBundle constructor.
    assert project_tree(full_json, reference, reference["selection"]) == view
    assert full_json == story_bundle_snapshot(full)
    assert "calendar_samples" not in json.dumps(view) and len(p._canonical(view)) <= 32768 < len(p._canonical(full_json))
    spec = claim_spec(view, full, full_json)
    binding = spec["evidence"]["input_binding"]
    assert binding["claim_view"] == dict(view_sha256=fingerprint(view), reference=reference)
    assert binding["bundles"][0]["bundle_sha256"] == reference["full_story"]["sha256"] == fingerprint(full_json)
    # The comparator itself is the unchanged full-evidence qualification.
    plain, _, _ = domain.qualified(story_bundle_snapshot(full))
    assert {k: v for k, v in spec["evidence"].items() if k != "input_binding"} == {
        k: v for k, v in plain["evidence"].items() if k != "input_binding"}
    assert validate_graphic(spec["template"], spec["evidence"], expected_evidence_sha256=spec["expected_evidence_sha256"])
    # The pair binding is closed: an altered view hash, source selection or extra
    # field fails the replay even with a recomputed evidence fingerprint.
    other = CLAIM_FIELDS[(direction, "monthly" if tier == "calendar" else "calendar")]
    selection = {**reference["selection"], "signal_field": other}
    for altered in ({**binding, "claim_view": {**binding["claim_view"], "view_sha256": "0" * 64}},
                    {**binding, "claim_view": {**binding["claim_view"], "reference": {**reference, "selection": selection}}},
                    {**binding, "claim_view": {**binding["claim_view"], "full_story_sha256": fingerprint(full_json)}}):
        evidence = {**spec["evidence"], "input_binding": altered}
        with pytest.raises(ValueError):
            validate_graphic(spec["template"], evidence, expected_evidence_sha256=fingerprint(evidence))


@pytest.mark.parametrize("change", [
    "view_value", "view_table_count", "view_reference", "other_full", "other_day", "selection_field",
    "selection_station", "selection_date", "malformed_reference", "expected_full",
    "forecast", "qflag", "unit", "cutoff", "date", "station",
])
def test_compact_claim_pair_tampering_or_unqualified_evidence_is_refused(change):
    from tests.ghcn_graphic_helpers import graphic_bundles
    from tests.test_temperature_graphic_adapter import reseal as reseal_bundle
    full = station()
    view, full_json = claim_pair(full, "all_time_high")
    reference = view["raw_signal_dump"]["ghcn_claim_view"]
    evidence = full.raw_signal_dump["evidence"]
    if change == "view_value":
        view["headline_metric"]["value"] += 1
    elif change == "view_table_count":
        view["raw_signal_dump"]["evidence"]["baseline"]["variables"]["temperature_2m_max"]["sample_count"] += 1
    elif change == "view_reference":
        reference["observation_revision"] = "0" * 64
    elif change in {"other_full", "other_day"}:
        # Genuine full evidence for a different comparator or source day.
        full = station("high", "monthly") if change == "other_full" else graphic_bundles()[-2]
        full_json = story_bundle_snapshot(full)
    elif change == "selection_field":
        reference["selection"]["signal_field"] = "monthly_high"
    elif change == "selection_station":
        reference["selection"]["station_id"] = "USC99000002"
    elif change == "selection_date":
        reference["selection"]["signal_date"] = "2026-09-07"
    elif change == "malformed_reference":
        reference["kind"] = "ghcn_claim_view_v0"
    elif change == "expected_full":
        full_json = {**full_json, "where": "Another resolver result"}
    else:
        # A consistent forged pair around unqualified full evidence still reaches
        # the unchanged scientific qualification, which refuses it.
        if change == "forecast":
            evidence["evidence_type"] = "forecast"
        elif change == "qflag":
            evidence["variables"]["TMAX"]["qflag"] = "S"
        elif change == "unit":
            evidence["unit"] = "F"
        elif change == "cutoff":
            evidence["baseline"]["requested_comparison_cutoff"] = "2026-09-08"
        elif change == "date":
            full.raw_signal_dump["signal_date"] = "2026-09-07"
        else:
            evidence["station_id"] = "USC99000002"
        reseal_bundle(full)
        try:
            view, full_json = claim_pair(full, "all_time_high")
        except ValueError:
            return  # The actual schema-2 projection already refuses this source.
    with pytest.raises(ValueError):
        claim_spec(view, full, full_json)


def test_compact_claim_requires_a_typed_resolver_result():
    from types import SimpleNamespace
    from src.commands.postgres_sourced_generation import GhcnPreparationFailure
    full = station()
    view, _ = claim_pair(full, "all_time_high")
    policy = current_editorial_policy()
    for claim, code in ((None, "ghcn_baseline_unavailable"),
                        (dict(full=full, view=view), "ghcn_baseline_unavailable"),
                        (SimpleNamespace(full=full, verify_saved=lambda saved: saved), "ghcn_baseline_unavailable"),
                        (GhcnPreparationFailure("ghcn_baseline_changed"), "ghcn_baseline_changed")):
        with pytest.raises(CommandError) as error:
            domain.qualified_claim(view, {}, claim, policy)
        assert error.value.code == code


def test_native_compact_claim_package_and_review_require_the_exact_pair(native_dependencies, tmp_path):
    full = station("low", "calendar")
    view, full_json = claim_pair(full, "calendar_date_low")
    spec = claim_spec(view, full, full_json)
    manifest_path = native_package(spec, tmp_path / "native", native_dependencies["rasterizer"])
    manifest = json.loads(manifest_path.read_bytes())
    png = (manifest_path.parent / "preview.png").read_bytes()
    assert manifest["binding"]["template"] == "temperature_comparator" and manifest["publication_approved"] is False
    stored = json.loads((manifest_path.parent / "input.json").read_bytes())
    assert stored["evidence"]["input_binding"]["claim_view"]["view_sha256"] == fingerprint(view)

    def draft(bundle):
        return dict(id="invented-compact-media", event_id=view["event_id"], type=view["signal_kind"], text=TEXT,
                    content_revision=1, decision_revision=1, status="pending", review_context={"two_bot": {"bundle": bundle}})

    def review(bundle, graphic=spec):
        row = draft(bundle)
        return dict(draft=row, expected_draft_identity=draft_identity(row), editorial_policy=current_editorial_policy(),
                    graphic_spec=graphic, renderer_manifest=manifest, png_bytes=png)

    accepted = review(view)
    packet = build_media_review_packet(**accepted)
    assert status(make(accepted), accepted)["accepted"]
    assert media_review_packet_is_current(packet, accepted["draft"], **{k: v for k, v in accepted.items() if k != "draft"})
    other_view, _ = claim_pair(station("low", "monthly"), "monthly_low")
    for bundle in (full_json, other_view, {**view, "where": "Another place"}):
        with pytest.raises(ValueError, match="different retained bundles"):
            build_media_review_packet(**review(bundle))
    # A full-bundle graphic never stands in for a compact draft's saved claim.
    plain, _, _ = domain.qualified(full_json)
    with pytest.raises(ValueError):
        build_media_review_packet(**review(view, plain))
    # The native renderer replays the pair and refuses a substituted claim view.
    forged = deepcopy(spec)
    forged["evidence"]["input_binding"]["claim_view"]["view_sha256"] = fingerprint(other_view)
    forged["expected_evidence_sha256"] = fingerprint(forged["evidence"])
    with pytest.raises(subprocess.CalledProcessError) as refused:
        native_package(forged, tmp_path / "forged", native_dependencies["rasterizer"])
    assert b"saved claim view is not the projection of this full evidence" in refused.value.stderr


# The existing invented GHCN engine journeys: real source capture, operator
# resolver, one invented writer response, four required checks and admission.
TRACKED = "USW00000999"
PREPARE_KEYS = ("expected_policy_sha256", "expected_renderer_profile_sha256")


def variant_text(field, day):
    """Invented writer output that passes the actual deterministic checks."""
    from tests.ghcn_variant_sources import VARIANTS as STATIONS
    month = day.strftime("%B")
    value, verb, extreme = {
        "all_time_high": ("45.5", "reached", "highest reading"), "monthly_high": ("40.0", "reached", f"highest {month} reading"),
        "calendar_date_high": ("33.0", "reached", "highest reading for the date"),
        # A Unicode minus: the existing safety pattern holds hyphenated digit runs.
        "all_time_low": ("−25.5", "fell to", "lowest reading"), "monthly_low": ("−15.0", "fell to", f"lowest {month} reading"),
        "calendar_date_low": ("−5.0", "fell to", "lowest reading for the date")}[field]
    return f"INVENTED STATION {STATIONS[field]} {verb} {value}°C, its {extreme} in the 25-year station archive."


@pytest.fixture
def compact_case(request, database, tmp_path, monkeypatch, positive_workflow_clock, native_dependencies):
    from datetime import UTC, datetime
    from src.commands.postgres_sourced_generation import private_configuration
    from src.voice import safety
    from tests import test_postgres_ghcn_source_results as ghcn_source
    from tests.ghcn_variant_sources import VARIANTS as STATIONS, station_id, variant_source
    from tests.test_postgres_command_authority import options
    from tests.test_postgres_preview_command_ingress import clean_environment
    from tests.test_postgres_sourced_generation import allowance_document
    from tests.test_spend_journal import LIMITS
    fields = request.param
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-offline-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    original_draft = ghcn_source.draft
    # The fixture's existing claim belongs to a quiet station outside every variant.
    monkeypatch.setattr(ghcn_source, "draft", lambda **kw: original_draft(**dict(kw, sid=TRACKED)))
    folder = tmp_path / "invented-source"
    folder.mkdir()
    supply = variant_source(folder, fields, tracked=(TRACKED,))
    generator = ghcn_source.configured.__wrapped__(database, supply, tmp_path, monkeypatch)
    case = next(generator)
    case["environment"] = {**clean_environment(), "THEHEAT_CRITIC_ENABLED": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    run = ghcn_source.retained(case)
    child = subprocess.run([sys.executable, "-c", 'import json,sys; from tests.workflow_clock import start_child_clock; '
        'fixture_clock=start_child_clock(json.loads(sys.argv.pop(1))); from src.voice import safety; '
        'safety.GEMINI_API_KEY="invented-offline-key"; from src.commands.preview_worker import main; raise SystemExit(main())',
        json.dumps(positive_workflow_clock), *case["args"], "--command-id", ghcn_source.enroll(case, run)],
        env=case["environment"], capture_output=True, text=True, timeout=60)
    assert child.returncode == 0 and json.loads(child.stdout)["result"]["status"] == "applied", child.stdout + child.stderr
    now = datetime.now(UTC)
    owner = case["owner"]
    for method in ("initialize_spending", "initialize_batches", "initialize_batch_workers", "initialize_batch_results",
                   "initialize_candidate_checks", "initialize_check_executions", "initialize_media_staging",
                   "initialize_media_commands"):
        getattr(owner, method)()
    owner.initialize_synchronous_checks(now=now)
    owner.initialize_revision_checks(now=now)
    # Invented local allowance scaled for up to six admissions plus editor checks;
    # every model call still needs its own reservation and grant.
    case["authority"].spending("configure", dict(LIMITS, daily_micro_usd=400, monthly_micro_usd=600), now=utc_text(now))
    case["authority"].configure_editor_media(**native_dependencies, scratch=tmp_path / "native")
    base = dict(authority=options(case["params"]), baseline={k: str(v) for k, v in vars(supply["baseline"]).items()},
        operators=str(tmp_path / "operators.json"), generation=str(tmp_path / "generation.json"), run_id=run,
        policy_sha256=fingerprint(current_editorial_policy()), trace=str(tmp_path / "trace.jsonl"),
        test_clock=positive_workflow_clock, native=case["authority"].editor_media_configuration)
    case["variants"] = {}
    for field in fields:
        config = dict(base, text=variant_text(field, supply["day"]),
                      selection=dict(station_id=station_id(STATIONS[field]), signal_date=str(supply["day"]), signal_field=field))
        path = tmp_path / f"worker-{field}.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        case["variants"][field] = dict(config=config, config_path=path)
    case.update(case["variants"][fields[0]], supply=supply)
    briefs = {field: ghcn_worker(variant(case, field), "enroll")["brief_id"] for field in fields}
    reserve = case["authority"].retain_generation_reservation(allowance_document(briefs[fields[0]], now=now, schema_version=2,
        execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180, brief_ids=list(briefs.values())))
    path = Path(base["generation"])
    path.write_text(json.dumps(dict(schema_version=2, current_inputs=list(briefs.values()),
                                    reservations=dict(batch=None, synchronous=reserve))))
    path.chmod(0o600)
    case["authority"].configure_sourced_generation(private_configuration(path))
    case["briefs"] = briefs
    yield case
    try:
        next(generator)
    except StopIteration:
        pass


def variant(case, field):
    return dict(case, **case["variants"][field])


def ghcn_worker(case, operation, identity="", fault=""):
    from tests.test_postgres_ghcn_generation import worker
    return worker(case, operation, identity, fault)


def submit_command(case, body, role="editor", fault=""):
    from tests.test_postgres_preview_command_ingress import http
    status_code, accepted, _ = http(case["port"], "/commands", method="POST", value=body, role=role)
    assert status_code == 202, accepted
    return ghcn_worker(case, "consume", body["command_id"], fault)


def generation_command(action, refs, *, minutes=60):
    from datetime import UTC, datetime
    from uuid import uuid4
    now = datetime.now(UTC)
    return dict(command_id=str(uuid4()), action=action, requested_at=utc_text(now),
                expires_at=utc_text(now + timedelta(minutes=minutes)), targets=[], payload=refs)


def admit_compact(case, field):
    """Actual operator-selected source -> one invented writer -> four checks -> draft."""
    from tests.test_postgres_preview_command_ingress import http
    case = variant(case, field)
    _, listing, _ = http(case["port"], "/generation")
    brief = next(b for b in listing["briefs"] if b["brief_id"] == case["briefs"][field])
    body = generation_command("request_sourced_generation",
        {k: brief[k] for k in ("brief_id", "brief_sha256", "expected_state_version", "expected_policy_sha256")})
    assert submit_command(case, body)["status"] == "applied"
    assert ghcn_worker(case, "write", body["command_id"])["outcome"] == "response_retained"
    captured = ghcn_worker(case, "capture", body["command_id"])
    assert captured["outcome"] == "candidate_ready", captured
    check = generation_command("request_candidate_checks", captured["candidate"], minutes=10)
    requested = submit_command(case, check, role="publisher")
    assert requested["status"] == "unchanged", requested
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        completed = ghcn_worker(case, stage, check["command_id"])
        assert completed["outcome"] == "completed" and completed["checks"]["stages"][stage] == "passed", (
            field, stage, json.dumps(completed, sort_keys=True))
    projected = next(row for row in ghcn_worker(case, "projection")
                     if row["check_set_id"] == requested["candidate"]["check_set_id"])
    refs = dict(captured["candidate"], **{k: projected[k] for k in ("check_set_id", "expected_completion_sha256")})
    admitted = submit_command(case, generation_command("admit_checked_candidate", refs))
    assert admitted["status"] == "applied", admitted
    return admitted["candidate"]["draft_id"]


def saved_draft(case, draft_id):
    return next(d for d in case["authority"].read()[1]["drafts"] if d["id"] == draft_id)


def media_view(case, draft_id, role="editor"):
    from tests.test_postgres_preview_command_ingress import http
    status_code, body, headers = http(case["port"], f"/drafts/{draft_id}/media", role=role)
    assert status_code == 200 and headers["Cache-Control"] == "private, no-store", body
    return body


def editor_command(case, draft_id, action, payload, *, target=None):
    from datetime import UTC, datetime
    from uuid import uuid4
    from src.commands.reducer import _identity
    now = datetime.now(UTC)
    return dict(command_id=str(uuid4()), action=action, requested_at=utc_text(now),
                expires_at=utc_text(now + timedelta(minutes=5)),
                targets=[target or _identity(saved_draft(case, draft_id))], payload=payload)


def trace_rows(case, start=0):
    lines = Path(case["config"]["trace"]).read_text().splitlines() if Path(case["config"]["trace"]).exists() else []
    return [json.loads(line) for line in lines[start:]]


def assert_compact_saved_claim(case, draft_id, field):
    from src.two_bot.candidate_derivation import has_ghcn_reference
    bundle = saved_draft(case, draft_id)["review_context"]["two_bot"]["bundle"]
    encoded = p._canonical(bundle)
    assert has_ghcn_reference(bundle) and b"calendar_samples" not in encoded and b"monthly_samples" not in encoded
    assert len(encoded) <= 32768
    assert bundle["raw_signal_dump"]["ghcn_claim_view"]["selection"]["signal_field"] == field
    return bundle


@pytest.mark.parametrize("compact_case", [tuple(CLAIM_FIELDS.values())], indirect=True, ids=["six_variants"])
def test_six_compact_claims_reach_actual_native_editor_preparation(compact_case):
    case = compact_case
    from tests.ghcn_variant_sources import VARIANTS as STATIONS, station_id
    native = {"all_time_high", "all_time_low"}
    for field in CLAIM_FIELDS.values():
        start = len(trace_rows(case))
        draft_id = admit_compact(case, field)
        bundle = assert_compact_saved_claim(case, draft_id, field)
        # Writer and model-check arguments stay compact; only the local
        # deterministic fact gate reads the full resolved evidence.
        evidence = [row for row in trace_rows(case, start) if row["kind"] == "evidence_argument"]
        assert {row["stage"] for row in evidence} == {"writer_view", "fact_view", "critic_view", "local_fact_full"}
        assert all(row["compact"] is (row["stage"] != "local_fact_full") for row in evidence)
        assert max(row["byte_count"] for row in evidence if row["compact"]) <= 32768
        assert min(row["byte_count"] for row in evidence if not row["compact"]) > 2 * 32768
        ready = media_view(case, draft_id)
        assert ready["status"] == "ready", ready
        assert ready["source_label"] == "NOAA GHCN-Daily · station observations"
        assert ready["source_context"] == dict(kind="ghcn_station_day", station_id=station_id(STATIONS[field]),
            valid_date=str(case["supply"]["day"]), retrieved_at=case["supply"]["now"],
            reporting_interval_known=False, timezone=None)
        prepare = editor_command(case, draft_id, "prepare_media_revision", {k: ready[k] for k in PREPARE_KEYS})
        result = submit_command(case, prepare)
        assert result["status"] == "unchanged" and result["media_preparation"]["publication_approved"] is False, result
        assert ghcn_worker(case, "consume", prepare["command_id"]) == result
        prepared = media_view(case, draft_id)
        assert prepared["status"] == "prepared" and prepared["packet"]["graphic_binding"]["template"] == "temperature_comparator"
        package = case["authority"].read_media_proposal(prepared["preparation"]["proposal_sha256"])
        spec = package["capture"]["inputs"]["graphic_spec"]
        binding = spec["evidence"]["input_binding"]
        assert binding["claim_view"] == dict(view_sha256=fingerprint(bundle),
                                             reference=bundle["raw_signal_dump"]["ghcn_claim_view"])
        assert binding["bundles"][0]["bundle_sha256"] == bundle["raw_signal_dump"]["ghcn_claim_view"]["full_story"]["sha256"]
        assert package["capture"]["predecessor_state"]["drafts"][0]["review_context"]["two_bot"]["bundle"] == bundle
        if field in native:
            assets = package["assets"]
            assert set(assets) == FILES and assets["preview.png"][:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", assets["preview.png"][16:24]) == (1200, 1500)
            alt = assets["alt.txt"].decode("utf-8")
            for qualifier in ("SYNTHETIC DEMONSTRATION", "Station " + station_id(STATIONS[field]), str(case["supply"]["day"]),
                              "observed", "Evidence as of " + case["supply"]["now"],
                              "reporting interval and timezone are unknown", "no implied UTC observation time",
                              "does not establish an official or unrestricted record"):
                assert qualifier in alt
            case.setdefault("native_packages", {})[field] = {name: len(data) for name, data in assets.items()}
    assert set(case["native_packages"]) == native


def attach_payload(prepared, reason):
    from tests.test_postgres_editor_media import CONFIRMATIONS, EXTRA_CONFIRMATIONS
    confirmations = CONFIRMATIONS | (EXTRA_CONFIRMATIONS if prepared["packet"]["schema_version"] == 2 else set())
    return dict(proposal_sha256=prepared["preparation"]["proposal_sha256"],
                expected_policy_sha256=prepared["expected_policy_sha256"],
                expected_packet_sha256=prepared["packet"]["packet_sha256"],
                review=dict(decision="accept", confirmations={k: True for k in confirmations}, reason=reason))


def checked_payload(current, **extra):
    return dict(expected_policy_sha256=current["expected_policy_sha256"],
                expected_renderer_profile_sha256=current["expected_renderer_profile_sha256"],
                expected_packet_sha256=current["packet"]["packet_sha256"],
                expected_review_sha256=current["expected_review_sha256"], **extra)


def without_clock(view):
    """A projection's removal offer is stamped with the read time."""
    return {k: v for k, v in view.items() if k != "removal"}


def png_bytes(authority, draft_id, proposal, operators):
    from datetime import UTC, datetime
    return authority.editor_media_projection(draft_id, operators.resolve, now=datetime.now(UTC), png_proposal=proposal)


@pytest.mark.parametrize("compact_case", [("all_time_low",)], indirect=True, ids=["all_time_low"])
def test_compact_claim_native_review_checks_park_restore_and_invalidation(compact_case, cluster, tmp_path):
    import psycopg
    from datetime import UTC, datetime
    from src.commands.postgres_authority import PostgresCommandAuthority
    from src.commands.postgres_sourced_generation import private_configuration
    from src.commands.schema import Command
    from tests.test_postgres_command_authority import options
    from tests.test_postgres_editor_media import all_application_rows
    from tests.test_postgres_preview_command_ingress import http
    from tests.test_postgres_projection import admin
    case = compact_case
    draft_id = admit_compact(case, "all_time_low")
    bundle = assert_compact_saved_claim(case, draft_id, "all_time_low")
    ready = media_view(case, draft_id)
    assert ready["status"] == "ready", ready
    # A stale renderer identity is a durable refusal that never holds the queue.
    before = case["authority"].read()
    stale = editor_command(case, draft_id, "prepare_media_revision", {**{k: ready[k] for k in PREPARE_KEYS},
                                                                     "expected_renderer_profile_sha256": "f" * 64})
    refused = submit_command(case, stale)
    assert refused["status"] == "rejected" and refused["code"] == "native_renderer_changed", refused
    assert ghcn_worker(case, "consume", stale["command_id"]) == refused and case["authority"].read() == before
    prepare = editor_command(case, draft_id, "prepare_media_revision", {k: ready[k] for k in PREPARE_KEYS})
    assert submit_command(case, prepare)["status"] == "unchanged"
    prepared = media_view(case, draft_id)
    proposal = prepared["preparation"]["proposal_sha256"]
    png = png_bytes(case["authority"], draft_id, proposal, case["operators"])
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 1000
    attached = submit_command(case, editor_command(case, draft_id, "attach_media_revision",
                                                   attach_payload(prepared, "Invented station claim, PNG and full alt reviewed.")))
    assert attached["status"] == "applied", attached
    current = media_view(case, draft_id)
    assert current["status"] == "attached" and current["review_current"] is True, current
    # Fresh required checks over the saved compact claim, each with its own
    # locally resolved scientific context; prompts never carry the full tables.
    request = editor_command(case, draft_id, "request_revision_checks", checked_payload(current))
    requested = submit_command(case, request)
    assert requested["status"] == "unchanged", requested
    packet = case["authority"].check_execution("read", {"check_set_id": requested["revision_checks"]["check_set_id"]},
                                               now=utc_text(datetime.now(UTC)))["packet"]
    assert packet["bundle"] == bundle and b"calendar_samples" not in p._canonical(packet)
    start = len(trace_rows(case))
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        completed = ghcn_worker(case, stage, request["command_id"])
        assert completed["outcome"] == "completed" and completed["checks"]["stages"][stage] == "passed", completed
    rows = trace_rows(case, start)
    stages = [row for row in rows if row["kind"] == "revision_stage"]
    assert [row["stage"] for row in stages] == ["deterministic", "safety", "fact_check", "critic"]
    assert all(row["packet_bundle_sha256"] == row["view_sha256"] == fingerprint(bundle)
               and not row["request_full_tables"] for row in stages)
    posts = [row for row in rows if row["kind"] == "model_post"]
    assert [row["stage"] for row in posts] == ["revision_safety", "revision_fact_check", "revision_critic"]
    assert not any(row["full_tables"] for row in posts)
    evidence = [row for row in rows if row["kind"] == "evidence_argument"]
    assert {row["stage"] for row in evidence} == {"fact_view", "critic_view", "local_fact_full"}
    assert all(row["compact"] is (row["stage"] != "local_fact_full") for row in evidence)
    current = media_view(case, draft_id)
    assert current["checks_status"] == "passed" and current["expected_check_completion_sha256"], current
    wrong = submit_command(case, editor_command(case, draft_id, "approve_media_revision",
        checked_payload(current, expected_check_completion_sha256="0" * 64, reason="Invented stale proof")), role="publisher")
    assert wrong["status"] == "rejected" and wrong["code"] == "check_completion_changed", wrong
    editor_approval = editor_command(case, draft_id, "approve_media_revision", checked_payload(
        current, expected_check_completion_sha256=current["expected_check_completion_sha256"], reason="Editor cannot park"))
    assert http(case["port"], "/commands", method="POST", value=editor_approval)[0] == 403
    approve = editor_command(case, draft_id, "approve_media_revision", checked_payload(
        current, expected_check_completion_sha256=current["expected_check_completion_sha256"],
        reason="Park this invented local review only."))
    park = submit_command(case, approve, role="publisher")
    assert park["status"] == "applied" and park["media_approval"]["parked"] is True, park
    assert park["media_approval"]["publication_approved"] is False and "delivery" not in park
    assert ghcn_worker(case, "consume", approve["command_id"]) == park
    parked = media_view(case, draft_id)
    assert parked["parked"] is True and parked["checks_status"] == "passed"
    draft = saved_draft(case, draft_id)
    assert draft["status"] == "pending" and draft["approval_binding"]["scope"] == "local_joint_media"
    assert not set(draft) & {"approved_at", "publish_requested_at", "auto_approve_at", "tweet_id"}

    # Owned dump/restore into a new database, then resumption from that copy.
    params, run, _ = cluster
    rows_before = all_application_rows(case["params"])
    state = case["authority"].read()
    dump = tmp_path / "compact-claim.dump"
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), case["params"]["dbname"])
    name = "restore_compact_" + hashlib.sha256(str(dump).encode()).hexdigest()[:16]
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = dict(case["params"], dbname=name)
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = PostgresCommandAuthority(**options(restored_params))
        restored.configure_ghcn_source_results(case["supply"]["baseline"])
        restored.configure_sourced_generation(private_configuration(case["config"]["generation"]))
        restored.configure_editor_media(**case["authority"].editor_media_configuration)
        assert restored.read() == state and all_application_rows(restored_params) == rows_before
        resolve = case["operators"].resolve
        restored_view = restored.editor_media_projection(draft_id, resolve, now=datetime.now(UTC))
        assert without_clock(restored_view) == without_clock(parked) and restored_view["parked"]
        assert png_bytes(restored, draft_id, proposal, case["operators"]) == png
        config = dict(case["config"], authority=options(restored_params))
        path = tmp_path / "restored-worker.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        copy = dict(case, config=config, config_path=path)
        assert ghcn_worker(copy, "consume", approve["command_id"]) == park
        assert all_application_rows(restored_params) == rows_before
        actor = resolve("local-editor")
        body = editor_command(case, draft_id, "edit_revision",
                              {"text": draft["text"].replace("lowest reading", "lowest accepted reading")})
        restored.accept(Command.from_request(body, actor, environment="local", now=datetime.now(UTC)), actor,
                        now=datetime.now(UTC))
        assert ghcn_worker(copy, "consume", body["command_id"])["status"] == "applied"
        edited = restored.editor_media_projection(draft_id, resolve, now=datetime.now(UTC))
        assert not edited["parked"] and not edited["review_current"]
        # Passive historical bytes need neither the current source nor its resolver.
        del restored.ghcn_baseline
        held = restored.editor_media_projection(draft_id, resolve, now=datetime.now(UTC))
        assert held["status"] == "unavailable" and held["code"] == "ghcn_baseline_unavailable", held
        assert not held["parked"] and not held["review_current"]
        assert png_bytes(restored, draft_id, proposal, case["operators"]) == png
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))

    # The original keeps its parked decision until a saved edit, then a fresh
    # re-review neither resurrects the approval nor reuses the old checks.
    edit = submit_command(case, editor_command(case, draft_id, "edit_revision",
                                               {"text": draft["text"].replace("lowest reading", "lowest archive reading")}))
    assert edit["status"] == "applied", edit
    stale_view = media_view(case, draft_id)
    assert not stale_view["parked"] and not stale_view["review_current"] and "approval_binding" not in saved_draft(case, draft_id)
    review = attach_payload(stale_view, "Reviewed the edited statement and unchanged qualified graphic.")
    reviewed = submit_command(case, editor_command(case, draft_id, "review_media_revision", review))
    assert reviewed["status"] == "applied", reviewed
    rereviewed = media_view(case, draft_id)
    assert rereviewed["review_current"] and not rereviewed["parked"]
    assert rereviewed["checks_status"] == "revision_checks_required", rereviewed
    removal = rereviewed["removal"]
    remove = editor_command(case, draft_id, "remove_media_revision", dict(
        expected_policy_sha256=rereviewed["expected_policy_sha256"], expected_proposal_sha256=removal["expected_proposal_sha256"],
        confirmed=True, reason="Remove the invented graphic"))
    remove.update(requested_at=removal["requested_at"], expires_at=removal["expires_at"])
    removed = submit_command(case, remove)
    assert removed["status"] == "applied", removed
    final = saved_draft(case, draft_id)
    assert not set(final) & {"media_attachment", "media_review_binding", "approval_binding"}
    assert png_bytes(case["authority"], draft_id, proposal, case["operators"]) == png


@pytest.mark.parametrize("compact_case", [("calendar_date_low",)], indirect=True, ids=["calendar_date_low"])
def test_actual_authenticated_http_compact_claim_editor_journey(compact_case, tmp_path):
    """Next handlers -> authenticated HTTP -> real authority -> native/check workers."""
    import os
    import socket
    import threading
    from datetime import UTC, datetime
    from src.commands.preview_ingress import PreviewServer
    case = compact_case
    draft_id = admit_compact(case, "calendar_date_low")
    bundle = assert_compact_saved_claim(case, draft_id, "calendar_date_low")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        origin = "http://127.0.0.1:" + str(probe.getsockname()[1])
    server = PreviewServer(case["authority"], case["operators"], port=0, origin=origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # One file configures both the Node journey and the invented GHCN worker.
    config = dict(case["config"], endpoint=f"http://127.0.0.1:{server.server_port}", origin=origin, root=str(ROOT),
                  python=sys.executable, child=str(ROOT / "tests/fixtures/ghcn_generation_worker.py"),
                  draft_id=draft_id, at=utc_text(datetime.now(UTC)))
    path = tmp_path / "http.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    start = len(trace_rows(case))
    try:
        result = subprocess.run([os.environ.get("THEHEAT_NODE24", "node"), "--test", "tests/editor-media-http.test.js"],
                                cwd=ROOT / "dashboard", env={**case["environment"], "THEHEAT_MEDIA_HTTP_CONFIG": str(path)},
                                capture_output=True, text=True, timeout=300)
        # The Node journey skips without its config; require one actual pass.
        assert result.returncode == 0 and "\u2139 pass 1" in result.stdout and "\u2139 skipped 0" in result.stdout, (
            result.stdout + result.stderr)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    rows = trace_rows(case, start)
    assert [row["stage"] for row in rows if row["kind"] == "model_post"] == [
        "revision_safety", "revision_fact_check", "revision_critic"]
    assert not any(row.get("full_tables") or row.get("request_full_tables") for row in rows)
    assert {row["view_sha256"] for row in rows if row["kind"] == "revision_stage"} == {fingerprint(bundle)}
    final = saved_draft(case, draft_id)
    assert final["text"] == "An edited invented weather statement." and "approval_binding" not in final
    assert final["review_context"]["two_bot"]["bundle"] == bundle


@pytest.mark.parametrize("compact_case", [("monthly_high",)], indirect=True, ids=["monthly_high"])
def test_compact_claim_refusals_are_durable_typed_and_never_promote_after_drift(compact_case, tmp_path):
    from datetime import UTC, datetime
    from src.commands.postgres_authority import PostgresCommandAuthority
    from src.commands.postgres_sourced_generation import private_configuration
    from src.commands.preview_media_worker import consume_media_once
    from tests.test_postgres_command_authority import options
    case = compact_case
    draft_id = admit_compact(case, "monthly_high")
    bundle = assert_compact_saved_claim(case, draft_id, "monthly_high")
    ready = media_view(case, draft_id)
    expected = {k: ready[k] for k in PREPARE_KEYS}
    resolve = case["operators"].resolve

    def unchanged(refused, code, before):
        assert refused["status"] == "rejected" and (refused["code"] == code if code else refused["code"].startswith("ghcn_")), refused
        assert case["authority"].read() == before
        current = media_view(case, draft_id)
        assert current["preparation"] is None and current["status"] in {"ready", "unavailable"}, current

    # Missing resolver: an authority without the operator GHCN baseline refuses
    # durably instead of qualifying the saved compact view by itself.
    before = case["authority"].read()
    body = editor_command(case, draft_id, "prepare_media_revision", expected)
    from tests.test_postgres_preview_command_ingress import http
    assert http(case["port"], "/commands", method="POST", value=body)[0] == 202
    bare = PostgresCommandAuthority(**options(case["params"]))
    bare.configure_sourced_generation(private_configuration(case["config"]["generation"]))
    bare.configure_editor_media(**case["authority"].editor_media_configuration)
    refused = consume_media_once(bare, resolve, command_id=body["command_id"], now=datetime.now(UTC))
    unchanged(refused, "ghcn_baseline_unavailable", before)
    assert ghcn_worker(case, "consume", body["command_id"]) == refused
    # ...and the refusal never holds the queue: the next valid edit applies.
    edit = submit_command(case, editor_command(case, draft_id, "edit_revision",
        {"text": saved_draft(case, draft_id)["text"].replace("station archive", "station's archive")}))
    assert edit["status"] == "applied", edit
    # A command aimed at the pre-edit revision is refused, not re-targeted.
    before = case["authority"].read()
    stale = submit_command(case, editor_command(case, draft_id, "prepare_media_revision", expected, target=body["targets"][0]))
    assert stale["status"] == "rejected" and case["authority"].read() == before, stale

    # Changed operator resources and identities refuse before any staged asset.
    manifest = case["supply"]["baseline"].manifest
    original = manifest.read_bytes()
    manifest.write_bytes(original + b"\n")
    try:
        before = case["authority"].read()
        unchanged(submit_command(case, editor_command(case, draft_id, "prepare_media_revision", expected)), None, before)
    finally:
        manifest.write_bytes(original)
    for changes, code in ((dict(expected_policy_sha256="0" * 64), "editorial_policy_changed"),
                          (dict(expected_renderer_profile_sha256="0" * 64), "native_renderer_changed")):
        before = case["authority"].read()
        unchanged(submit_command(case, editor_command(case, draft_id, "prepare_media_revision", {**expected, **changes})),
                  code, before)
    operators = Path(case["config"]["operators"])
    saved_operators = operators.read_bytes()
    body = editor_command(case, draft_id, "prepare_media_revision", expected)
    assert http(case["port"], "/commands", method="POST", value=body)[0] == 202
    rows = json.loads(saved_operators)
    operators.write_text(json.dumps(dict(rows, operators=[r for r in rows["operators"] if r["role"] != "editor"])))
    try:
        before = case["authority"].read()
        revoked = ghcn_worker(case, "consume", body["command_id"])
    finally:
        operators.write_bytes(saved_operators)
    unchanged(revoked, "forbidden", before)
    before = case["authority"].read()
    unchanged(submit_command(case, editor_command(case, draft_id, "prepare_media_revision", expected),
                             fault="native_failure"), "native_render_failed", before)

    # The same saved claim still prepares, attaches and enrolls fresh checks.
    assert submit_command(case, editor_command(case, draft_id, "prepare_media_revision", expected))["status"] == "unchanged"
    prepared = media_view(case, draft_id)
    assert submit_command(case, editor_command(case, draft_id, "attach_media_revision",
        attach_payload(prepared, "Invented compact claim reviewed with its PNG and alt.")))["status"] == "applied"
    current = media_view(case, draft_id)
    request = editor_command(case, draft_id, "request_revision_checks", checked_payload(current))
    assert submit_command(case, request)["status"] == "unchanged"
    for stage in ("deterministic", "safety", "fact_check"):
        completed = ghcn_worker(case, stage, request["command_id"])
        assert completed["outcome"] == "completed" and completed["checks"]["stages"][stage] == "passed", (
            stage, json.dumps(completed, sort_keys=True))
    # A baseline change after the final provider grant retains the raw response
    # but promotes nothing; the restored, freshly resolved context reconciles it.
    check_set = case["authority"].result(request["command_id"])["revision_checks"]["check_set_id"]
    try:
        retained = ghcn_worker(case, "critic", request["command_id"], "postgrant_baseline")
        assert retained["outcome"] == "reconciliation_required", retained
        passive = case["authority"].check_execution("read", dict(check_set_id=check_set), now=utc_text(datetime.now(UTC)))
        assert passive["attempts"]["critic"]["observation"]["complete"] is True
        assert not passive["attempts"]["critic"].get("terminal")
        held = media_view(case, draft_id)  # The view cannot resolve the drifted source either.
        assert held["status"] == "unavailable" and held["code"].startswith("ghcn_") and held["checks_status"] != "passed"
    finally:
        manifest.write_bytes(original)
    # The retained, unpromoted observation now awaits reconciliation, not a new call.
    assert media_view(case, draft_id)["checks_status"] == "needs_attention"
    completed = ghcn_worker(case, "critic", request["command_id"])
    assert completed["outcome"] == "completed" and completed["checks"]["stages"]["critic"] == "passed", completed
    assert media_view(case, draft_id)["checks_status"] == "passed"
    assert saved_draft(case, draft_id)["review_context"]["two_bot"]["bundle"] == bundle
