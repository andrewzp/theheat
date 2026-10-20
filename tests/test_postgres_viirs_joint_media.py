"""Invented NOAA-20/NOAA-21 VIIRS stories through the local editor workflow.

Source-selected brief -> real offline generation/admission -> native prepare ->
explicit joint review and attach -> fresh required checks -> parked decision ->
restart and dump/restore. Offline fixtures only: no hosted, provider, source or
X request; Gist stays production and publishing stays paused. Invented data
proves workflow bindings, never scientific truth or hosted acceptance.
"""

from datetime import timedelta
import hashlib
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import pytest

from src.commands import postgres_editor_media as domain
from src.commands.preview_media_worker import consume_media_once
from src.commands.reducer import _identity
from src.commands.schema import CommandError, utc_text
from src.dashboard_preview.preview import qualified_spec
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import approval_is_current, fingerprint, review_is_current
from src.media.joint_review import CONFIRMATIONS
from tests import test_postgres_candidate_admission as candidate
from tests import test_postgres_sourced_generation as sourced
from tests.test_postgres_editor_media import (
    AT, action, admitted as admitted, offline_connections as offline_connections,
    park_dump_restore_journey, view,
)
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies

ADAPTER = Path(__file__).resolve().parents[1] / "src/media/viirs_map_graphic_adapter.py"
FILES = {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}
NS = "{http://www.w3.org/2000/svg}"
# Extent, damage, harm and percentage wording this graphic must never add. The
# alt text's explicit negations ("not ... severity", "common incident") stay.
UNSUPPORTED = ("hectare", "acre", "km²", "damage", "destroy", "evacuat", "casualt", "fatalit", "%")


def draft(case):
    return next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])


def retained(case, proposal):
    store = case["store"]
    with store.projections._connection() as c:
        store._validate(c)
        return domain.retained_package(store, c, case["draft_id"], proposal)


def revoked(principal):
    return lambda subject: None if subject == principal.subject else candidate.resolve(subject)


def packages(core):
    return admin(core[3], "SELECT count(*) FROM theheat_media.packages")[0][0]


def review(prepared, reason="Invented VIIRS source, text, labels and full alt reviewed together."):
    return dict(proposal_sha256=prepared["preparation"]["proposal_sha256"],
                expected_policy_sha256=prepared["expected_policy_sha256"],
                expected_packet_sha256=prepared["packet"]["packet_sha256"],
                review=dict(decision="accept", confirmations={k: True for k in CONFIRMATIONS}, reason=reason))


def assert_viirs_package(case, prepared, png, *, platform):
    """Exact native five-asset retention, current identities and scientific labels."""
    proposal = prepared["preparation"]["proposal_sha256"]
    package = retained(case, proposal)
    assets = package["assets"]
    assert set(assets) == FILES and assets["preview.png"] == png
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (1200, 1500)
    stored = package["capture"]["inputs"]
    manifest, spec = stored["renderer_manifest"], stored["graphic_spec"]
    assert {name: hashlib.sha256(assets[name]).hexdigest() for name in FILES} == manifest["files"]
    binding = manifest["binding"]
    assert (binding["template"], binding["template_version"]) == ("viirs_thermal_detection_map", "p31-viirs-locator-1")
    assert manifest["synthetic"] is True and manifest["publication_approved"] is False
    # Current renderer/policy identity: recomputed now, never copied from the package.
    current, label, context = qualified_spec(case["bundle"].to_dict(), synthetic=True, include_viirs=True)
    digest, renderer = domain.profile(case["store"], current)
    assert binding["renderer"] == renderer and spec == current
    assert renderer["adapter_sha256"] == hashlib.sha256(ADAPTER.read_bytes()).hexdigest()
    assert prepared["preparation"]["renderer_profile_sha256"] == digest
    assert prepared["expected_policy_sha256"] == fingerprint(current_editorial_policy())
    assert (label, context) == ("NASA FIRMS · VIIRS", {"kind": "viirs_acquisition", "acquired_at": "2032-02-29T23:59:00Z"})
    evidence = spec["evidence"]
    product = case["bundle"].raw_signal_dump["source_product"]
    assert (evidence["source_product"], evidence["instrument"], evidence["satellite"]) == (product, "VIIRS", platform)
    assert (evidence["acquired_at"], evidence["acquisition_precision"]) == ("2032-02-29T23:59:00Z", "minute")
    assert (evidence["unit"], evidence["variable"], evidence["confidence_kind"]) == ("MW", "pixel_frp", "categorical")
    categories = [point["confidence_category"] for point in evidence["points"]]
    assert categories == ["high", "nominal", "low"]
    root = ET.fromstring(assets["preview.svg"])
    texts = ["".join(node.itertext()) for node in root.iter(NS + "text")]
    for row in ("SYNTHETIC DATA", "500.1234 MW", "Pixel A radiative power", f"NASA FIRMS · {platform} VIIRS",
                "2032-02-29 23:59 UTC", "Source detection confidence", "A high · B nominal · C low",
                "Pixel radiative power (MW)", "Pixel centers, not fire boundaries."):
        assert row in texts, row
    # Equal locator markers: one 14 px marker per source row, no size encoding.
    assert sum(circle.attrib.get("r") == "14" for circle in root.iter(NS + "circle")) == len(evidence["points"])
    alt = assets["alt.txt"].decode("utf-8")
    assert alt.startswith("SYNTHETIC DEMONSTRATION") and alt.strip() == prepared["packet"]["media"]["alt_text"]
    for phrase in ("categorical low, nominal or high class", "pixel-integrated fire radiative power in megawatts",
                   "never combined into a total", "Equal-size markers", "do not establish simultaneity"):
        assert phrase in alt, phrase
    visible = " ".join(texts)
    for text in (visible, alt, root.find(NS + "title").text):
        assert "MODIS" not in text
    for word in UNSUPPORTED:
        assert word not in visible.lower() and word not in alt.lower(), word
    packet = prepared["packet"]
    assert packet["graphic_binding"]["template"] == "viirs_thermal_detection_map"
    assert packet["synthetic"] is True and packet["publication_approved"] is False
    assert packet["claim_agreement_status"] == "unreviewed"
    return package


@pytest.mark.parametrize("admitted", ["viirs_n20"], indirect=True)
def test_noaa20_native_review_checks_park_restore_and_graphic_invalidation(admitted, monkeypatch, core, cluster):
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options

    case = admitted
    admitted_draft = draft(case)
    # The real admission engine left a checked text-only revision.
    assert "review_binding" in admitted_draft and set(admitted_draft["review_context"]["two_bot"]) > {"bundle", "signal_kind"}
    ready = view(case)
    assert ready["status"] == "ready" and ready["source_label"] == "NASA FIRMS · VIIRS"
    assert ready["source_context"] == {"kind": "viirs_acquisition", "acquired_at": "2032-02-29T23:59:00Z"}

    journey = park_dump_restore_journey(case, monkeypatch, core, cluster)
    prepared, png = journey["prepared"], journey["png"]
    assert_viirs_package(case, prepared, png, platform="NOAA-20")
    media = case["attached"]["media"]
    assert media["publication_approved"] is False and media["production_attachment_authorized"] is False
    approval = journey["park"]["media_approval"]
    assert approval["parked"] is True and approval["publication_approved"] is False
    assert len(case["provider_requests"]) == 3

    # Attaching created the next pending revision: the admitted text checks and
    # review do not carry over to it; the old revision remains in history.
    current = draft(case)
    assert current["content_revision"] == admitted_draft["content_revision"] + 1 and current["status"] == "pending"
    assert "review_binding" not in current and set(current["review_context"]["two_bot"]) <= {"bundle", "signal_kind"}
    assert any(row.get("review_binding") == admitted_draft["review_binding"]
               and row["content_revision"] == admitted_draft["content_revision"] for row in current["revision_history"])
    assert not review_is_current(current) and not approval_is_current(current)
    assert not set(current) & {"approved_at", "publish_requested_at", "auto_approve_at"}

    # Restart on the same database: exact projection, bytes and one idempotent receipt.
    restarted = PostgresCommandAuthority(**options(core[3]))
    restarted.configure_sourced_generation(lambda: case["config"])
    restarted.configure_editor_media(**case["store"].editor_media_configuration)
    again = dict(case, store=restarted)
    assert view(again) == journey["projected"] and view(again)["parked"]
    assert view(again, png=prepared["preparation"]["proposal_sha256"]) == png
    assert restarted.consume(candidate.resolve, command_id=journey["park_command"].command_id, now=AT) == journey["park"]

    # Removing the graphic invalidates the parked decision; old checks are not
    # resurrected and the historical bytes stay readable.
    held = view(case)
    _, removed = action(case, "remove_media_revision", dict(
        expected_policy_sha256=held["expected_policy_sha256"],
        expected_proposal_sha256=held["removal"]["expected_proposal_sha256"],
        confirmed=True, reason="Remove the invented VIIRS graphic"))
    assert removed["status"] == "applied", removed
    after = view(case)
    assert not after["parked"] and not after["review_current"] and after["preparation"] is None
    assert after["checks_status"] == "not_requested" and after["expected_check_completion_sha256"] is None
    gone = draft(case)
    assert not set(gone) & {"media_attachment", "media_review_binding", "approval_binding"}
    assert view(case, png=prepared["preparation"]["proposal_sha256"]) == png


@pytest.mark.parametrize("admitted", ["viirs_n21"], indirect=True)
def test_noaa21_prepare_and_attach_hold_every_stale_or_unauthorized_request(admitted, monkeypatch, core):
    case = admitted
    store = case["store"]
    ready = view(case)
    assert ready["status"] == "ready" and ready["source_label"] == "NASA FIRMS · VIIRS"
    good = {k: ready[k] for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")}
    before = store.read()
    target = _identity(draft(case))
    stale_target = dict(target, content_revision=target["content_revision"] + 1)
    for payload, options, code in (
        (dict(good, expected_policy_sha256="0" * 64), {}, "editorial_policy_changed"),
        (dict(good, expected_renderer_profile_sha256="0" * 64), {}, "native_renderer_changed"),
        (good, dict(resolve=revoked(candidate.EDITOR)), "forbidden"),
        (good, dict(target=stale_target), "revision_conflict"),
    ):
        command, result = action(case, "prepare_media_revision", payload, **options)
        assert result["status"] == "rejected" and result["code"] == code, result
        # Each refusal is a durable result, so it never blocks later commands.
        assert store.consume(candidate.resolve, command_id=command.command_id, now=AT) == result
    assert store.read() == before and packages(core) == 0

    _, result = action(case, "prepare_media_revision", good)
    assert result["status"] == "unchanged", result
    prepared = view(case)
    assert prepared["status"] == "prepared" and prepared["packet"]["graphic_binding"]["template"] == "viirs_thermal_detection_map"
    png = view(case, png=prepared["preparation"]["proposal_sha256"])
    package = assert_viirs_package(case, prepared, png, platform="NOAA-21")
    assert package["capture"]["inputs"]["graphic_spec"]["evidence"]["satellite_code"] == "N21"
    state = store.read()
    payload = review(prepared)

    def refuse(code, **options):
        _, result = action(case, "attach_media_revision", payload, **options)
        assert result["status"] == "rejected" and result["code"] == code, result
        assert store.read() == state

    refuse("forbidden", resolve=revoked(candidate.EDITOR))
    refuse("revision_conflict", target=stale_target)
    with monkeypatch.context() as patch:
        patch.setenv("THEHEAT_WRITER_SAMPLES", "3")
        refuse("editorial_policy_changed")
    with monkeypatch.context() as patch:
        original = domain.profile
        patch.setattr(domain, "profile", lambda *args: ("e" * 64, original(*args)[1]))
        refuse("native_renderer_changed")
    # A newer retained revision of the same source event makes the selection ambiguous.
    newer = store.retain_generation_input(dict(case["value"], source_revision="invented-qualified-two"))
    case["config"]["current_inputs"].append(newer["brief_id"])
    refuse("media_source_revision_ambiguous")
    case["config"]["current_inputs"][:] = [case["refs"]["brief_id"]]
    saved = list(case["config"]["current_inputs"])
    case["config"]["current_inputs"].clear()
    refuse("media_source_not_allowlisted")
    case["config"]["current_inputs"][:] = saved

    _, attached = action(case, "attach_media_revision", payload)
    assert attached["status"] == "applied", attached
    media = attached["media"]
    assert media["publication_approved"] is False and media["production_attachment_authorized"] is False
    current = view(case)
    assert current["status"] == "attached" and current["review_current"] is True
    assert current["packet"]["media"]["png_sha256"] == hashlib.sha256(png).hexdigest()


@pytest.mark.parametrize("admitted", ["viirs_snpp", "hms", "viirs_mixed_product", "viirs_mixed_instrument",
                                      "viirs_mixed_minute"], indirect=True)
def test_unsupported_saved_source_is_a_recorded_typed_refusal(admitted, core):
    case = admitted
    store = case["store"]
    before = store.read()
    held = view(case)
    assert held["status"] == "unavailable" and held["code"] == "graphic_source_unqualified", held
    assert held["preparation"] is None and not held["parked"] and not held["review_current"]
    command, result = action(case, "prepare_media_revision", dict(
        expected_policy_sha256=fingerprint(current_editorial_policy()), expected_renderer_profile_sha256="f" * 64))
    assert result["status"] == "rejected" and result["code"] == "graphic_source_unqualified", result
    assert consume_media_once(store, candidate.resolve, command_id=command.command_id, now=AT) == result
    assert store.read() == before and packages(core) == 0
    # The refusal is recorded, so the next accepted command is not stuck behind it.
    _, edited = action(case, "edit_revision", {"text": "An edited invented statement after a held graphic."})
    assert edited["status"] == "applied", edited
    assert len(case["provider_requests"]) == 3


@pytest.mark.parametrize("admitted", ["viirs_long_frp"], indirect=True)
def test_unreadable_exact_value_is_held_before_native_preparation(admitted, monkeypatch, core):
    from src.commands import preview_media_worker as worker
    from src.media import evidence_graphic_render as renderer

    case = admitted
    spec, _, _ = qualified_spec(case["bundle"].to_dict(), synthetic=True, include_viirs=True)
    assert spec["template"] == "viirs_thermal_detection_map"
    digest, _ = domain.profile(case["store"], spec)
    before = case["store"].read()

    def forbidden(*args, **kwargs):
        raise AssertionError("Unreadable preflight attempted native/drawing work")

    monkeypatch.setattr(worker, "run_native", forbidden)
    monkeypatch.setattr(renderer, "_drawing", forbidden)
    held = view(case)
    assert held["status"] == "unavailable" and held["code"] == "graphic_map_labels_exceed_space"
    assert held["preparation"] is None and not held["parked"] and not held["review_current"]
    _, result = action(case, "prepare_media_revision", dict(
        expected_policy_sha256=fingerprint(current_editorial_policy()), expected_renderer_profile_sha256=digest))
    assert result["status"] == "rejected" and result["code"] == "graphic_map_labels_exceed_space"
    assert case["store"].read() == before and packages(core) == 0


@pytest.mark.parametrize("missing", ["primary", "related"])
def test_missing_receipt_cannot_become_an_editor_source(store, missing):
    from tests.viirs_graphic_helpers import viirs_bundle

    bundle = viirs_bundle().to_dict()
    if missing == "primary":
        bundle["raw_signal_dump"]["acquisition_provenance"] = None
    else:
        bundle["related_signals"][0]["acquisition_evidence"] = None
    save = dict(legacy_type="fire", event_id=bundle["event_id"], score=None, city="", tweet_date="",
                cooldown_exempt=False, review_context=None, evaluator_metadata=None)
    value = dict(schema_version=1, source_key="firms", source_revision="invented-missing-receipt",
                 captured_at=utc_text(sourced.NOW), useful_until=utc_text(sourced.NOW + timedelta(hours=8)),
                 urgent=False, bundle=bundle, save=save)
    with pytest.raises(CommandError) as error:
        store.retain_generation_input(value)
    assert error.value.code == "generation_evidence_not_ready"
