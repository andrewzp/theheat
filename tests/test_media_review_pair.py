"""Invented pure media/SQL rows; no PostgreSQL, renderer, provider or human proof."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import sys

import pytest

from src.commands import postgres_media as media, postgres_media_commands as commands
from src.commands.schema import Principal, canonical_json
from src.editorial.revisions import draft_identity
from src.media import joint_review as joint, platform_description as descriptions
from src.media.review_packet import build_media_review_packet, MediaReviewError
from src.storage import postgres_projection as p
from tests.test_joint_media_review import ACTOR
from tests.test_media_journal import package as package_fixture
from tests.test_media_replay_reuse import (
    replay as replay_fixture, preparation, current_inputs, outcome, NOW, AT,
)
from tests.test_media_review_packet import seed as seed_fixture, structural_png, manifest_for


def family_inputs(family):
    if family == "temperature":
        return getattr(seed_fixture, "__wrapped__")()
    if family == "pm25":
        from tests.air_quality_graphic_helpers import graphic_bundle as pm25_bundle
        from tests.test_air_quality_graphic_adapter import adapt as pm25_spec
        spec = pm25_spec(pm25_bundle())
    else:
        from tests.fire_graphic_helpers import graphic_bundle as fire_bundle
        from tests.test_fire_map_graphic_adapter import adapt as fire_spec
        spec = fire_spec(fire_bundle())
    bundle = spec["evidence"]["input_binding"]["bundles"][0]["bundle"]
    draft = dict(id="synthetic-" + family, event_id=bundle["event_id"], type=bundle["signal_kind"],
                 text="An invented statement for a pure local review fixture.", content_revision=1,
                 status="pending", review_context={"two_bot": {"bundle": deepcopy(bundle)}})
    png = structural_png()
    from src.editorial.policy import current_editorial_policy
    return dict(draft=draft, expected_draft_identity=draft_identity(draft),
                editorial_policy=current_editorial_policy(), graphic_spec=spec,
                renderer_manifest=manifest_for(spec, png), png_bytes=png)


def make_case(family, *, extended=True):
    # Reuse the public pure reader fixture, then create a separate command with
    # the exact extended payload. Its historical result is retained only below.
    case = getattr(replay_fixture, "__wrapped__")(getattr(package_fixture, "__wrapped__")(family_inputs(family)))
    case["profiles"] = descriptions.profiles()
    if extended:
        staged = media.read(case["sql"], case["command"].payload["proposal_sha256"], "local")
        description = commands.description_for(case["capture"]["proposal"]["proposed_draft"], staged,
                                                case["inputs"]["editorial_policy"], case["profiles"])
        payload = deepcopy(case["command"].payload)
        payload["review"]["confirmations"][descriptions.CONFIRMATION] = True
        payload["review"]["expected_platform_description_sha256"] = description["description_sha256"]
        case["command"] = replace(case["command"], payload_json=canonical_json(payload))
    return case


def arguments(case):
    inputs, assets = case["capture"]["inputs"], case["assets"]
    draft = case["capture"]["proposal"]["proposed_draft"]
    return dict(draft=deepcopy(draft), payload=deepcopy(case["command"].payload["review"]),
                principal=ACTOR, reviewed_at=AT,
                expected_packet_sha256=case["command"].payload["expected_packet_sha256"],
                editorial_policy=deepcopy(inputs["editorial_policy"]),
                graphic_spec=deepcopy(inputs["graphic_spec"]), renderer_manifest=deepcopy(inputs["renderer_manifest"]),
                png_bytes=assets["preview.png"], proposal_sha256=case["command"].payload["proposal_sha256"],
                raw_alt=assets["alt.txt"], platform_profiles=deepcopy(case["profiles"]), derivation=None)


def unpaired(args):
    """The prior two independently validating public calls, without a stub."""
    args = dict(args)
    draft = args.pop("draft")
    description_package = dict(capture=dict(
        inputs={key: args[key] for key in ("graphic_spec", "renderer_manifest")},
        proposal={"proposal_sha256": args.pop("proposal_sha256")}),
        assets={"alt.txt": args.pop("raw_alt"), "preview.png": args["png_bytes"]})
    description = commands.description_for(draft, description_package, args["editorial_policy"],
                                           args.pop("platform_profiles"), derivation=args.pop("derivation"))
    return joint.record_joint_media_review(draft, expected_draft_identity=draft_identity(draft),
                                           platform_description=description, **args)


@contextmanager
def packet_calls():
    count = [0]
    previous = sys.getprofile()
    def observe(frame, event, arg):
        if event == "call" and frame.f_code is build_media_review_packet.__code__:
            count[0] += 1
    sys.setprofile(observe)
    try:
        yield count
    finally:
        sys.setprofile(previous)


def prepare(case):
    return commands.prepare(case["sql"], case["before"], case["command"], ACTOR, now=NOW,
                            editorial_policy=case["inputs"]["editorial_policy"], environment="local",
                            platform_profiles=case["profiles"])


def retain(case, transition):
    case.update(transition=transition, after=transition.reduction.state,
                result=outcome(case["command"], transition, 1))
    commands.retain(case["sql"], case["command"], transition)
    case["sql"].snapshot("command-core-v1", "1", case["after"])
    case["sql"].command(case["command"], case["result"])


@pytest.mark.parametrize("family", ["temperature", "pm25", "modis"])
def test_pair_matches_both_public_calls_exactly_with_one_fresh_packet(family):
    args = arguments(make_case(family))
    before = deepcopy(args)
    with packet_calls() as old_count:
        expected = unpaired(args)
    with packet_calls() as new_count:
        actual = joint._record_joint_media_review_with_description(**args)
    assert p._canonical(actual) == p._canonical(expected)
    assert old_count == [2] and new_count == [1] and args == before
    assert actual["schema_version"] == 3 and actual["publication_approved"] is False
    assert actual["production_attachment_authorized"] is False
    if family == "modis":
        assert actual["platform_description"]["derivation"] == descriptions.MODIS_DERIVATION
    # No returned packet, retained proof or previous call can authorize a new one.
    actual["packet"]["media"]["alt_text"] = "Mutated returned packet"
    with packet_calls() as repeated:
        assert joint._record_joint_media_review_with_description(**args) == expected
    assert repeated == [1] and args == before


@pytest.mark.parametrize("family", ["temperature", "pm25", "modis"])
@pytest.mark.parametrize("extended", [False, True], ids=["legacy", "extended"])
def test_real_fresh_historical_and_current_reader_counts_preserve_legacy_and_outputs(family, extended):
    case = make_case(family, extended=extended)
    before = deepcopy((case["before"], case["inputs"], case["assets"], case["capture"]))
    with packet_calls() as fresh_count:
        transition = prepare(case)
    assert fresh_count == [5]  # Legacy5 unchanged; extended6 ->5.
    if extended:
        assert p._canonical(transition.review) == p._canonical(unpaired(arguments(case)))
    retain(case, transition)
    with packet_calls() as historical_count:
        retained, package = commands.read_with_package(case["sql"], case["command"], case["result"], "local")
    assert historical_count == [5] and retained["review"] == transition.review
    assert package["capture"] == case["capture"] and package["assets"] == case["assets"]
    preparation(case)
    from src.commands import postgres_editor_media as editor
    with packet_calls() as current_count:
        verified, record = editor._reviewed(case["authority"], case["sql"], case["after"]["drafts"][0],
                                            current_inputs(case), case["inputs"]["editorial_policy"], lambda subject: ACTOR)
    assert current_count == ([7] if extended else [6])  # Extended8 ->7; currentness itself is unchanged.
    assert record == transition.review and verified == package
    assert (case["before"], case["inputs"], case["assets"], case["capture"]) == before


@pytest.mark.parametrize("change", [
    "source", "bundle", "png", "policy", "identity", "packet", "malformed_packet", "confirmation",
    "missing_confirmation", "description", "raw_alt", "profile", "principal", "role", "payload", "time",
])
def test_pair_preserves_exact_old_failure_class_and_message(change):
    args = arguments(make_case("pm25"))
    if change == "source":
        args["graphic_spec"]["evidence"]["event_id"] += "-changed"
    elif change == "bundle":
        args["draft"]["review_context"]["two_bot"]["bundle"]["where"] += " changed"
    elif change == "png":
        args["png_bytes"] += b"changed"
    elif change == "policy":
        args["editorial_policy"]["execution_sha256"] = "f" * 64
    elif change == "identity":
        args["draft"]["content_revision"] += 1
    elif change in {"packet", "malformed_packet"}:
        args["expected_packet_sha256"] = "0" * 64 if change == "packet" else True
    elif change == "confirmation":
        args["payload"]["confirmations"]["text_matches_data"] = False
    elif change == "missing_confirmation":
        del args["payload"]["confirmations"][descriptions.CONFIRMATION]
    elif change == "description":
        args["payload"]["expected_platform_description_sha256"] = "0" * 64
    elif change == "raw_alt":
        args["raw_alt"] = b"Substituted description.\n"
    elif change == "profile":
        args["platform_profiles"]["profile"] = "changed"
    elif change == "principal":
        args["principal"] = {"subject": "untrusted", "role": "editor"}
    elif change == "role":
        args["principal"] = Principal(ACTOR.subject, "viewer", "revoked")
    elif change == "payload":
        args["payload"]["invented_extra"] = True
    else:
        args["reviewed_at"] = "not-a-date"
    before = deepcopy(args)
    with pytest.raises(Exception) as old:
        unpaired(args)
    assert type(old.value) in (MediaReviewError, descriptions.DescriptionError)
    with pytest.raises(type(old.value)) as new:
        joint._record_joint_media_review_with_description(**args)
    assert str(new.value) == str(old.value) and args == before


def test_pair_and_public_entrypoints_cannot_accept_a_supplied_packet():
    args = arguments(make_case("pm25"))
    record = unpaired(args)
    with pytest.raises(TypeError, match="packet"):
        joint._record_joint_media_review_with_description(**dict(args, packet=record["packet"]))
    with pytest.raises(TypeError, match="platform_description"):
        joint._record_joint_media_review_with_description(**dict(args, platform_description=record["platform_description"]))
    public = {key: args[key] for key in ("draft", "payload", "principal", "reviewed_at", "expected_packet_sha256",
              "editorial_policy", "graphic_spec", "renderer_manifest", "png_bytes")}
    public["expected_draft_identity"] = draft_identity(args["draft"])
    with pytest.raises(MediaReviewError, match="Malformed joint-review input"):
        joint.record_joint_media_review(**public, packet=record["packet"])
    public["expected_draft_identity"]["text_sha256"] = "0" * 64
    with pytest.raises(MediaReviewError, match="Draft differs from the independent requested identity"):
        joint.record_joint_media_review(**public)
