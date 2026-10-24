"""Invented pure media/SQL rows; no PostgreSQL, renderer, provider or human proof."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import sys

import pytest

from src.commands import postgres_media as media, postgres_media_commands as commands
from src.commands.schema import Command, CommandError, Principal, canonical_json
from src.editorial.revisions import draft_identity, fingerprint, revoke_approval
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
    assert current_count == [6]  # Extended current7 ->6; legacy6 unchanged.
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


def status_arguments(family="pm25"):
    args = arguments(make_case(family))
    record = unpaired(args)
    return {key: value for key, value in args.items() if key not in
            {"payload", "principal", "reviewed_at", "expected_packet_sha256", "derivation"}} | dict(
        record=record, expected_review_sha256=record["review_sha256"], current_principal=ACTOR)


def unpaired_status(args):
    """The prior description then public status path, with independent rebuilds."""
    values = dict(args)
    draft = values.pop("draft")
    package = dict(capture=dict(inputs={key: values[key] for key in ("graphic_spec", "renderer_manifest")},
        proposal={"proposal_sha256": values.pop("proposal_sha256")}),
        assets={"alt.txt": values.pop("raw_alt"), "preview.png": values["png_bytes"]})
    description = commands.description_for(draft, package, values["editorial_policy"], values.pop("platform_profiles"))
    return joint.joint_media_review_status(draft=draft, expected_draft_identity=draft_identity(draft),
        platform_description=description, **values)


@pytest.mark.parametrize("family", ["temperature", "pm25", "modis"])
def test_current_pair_matches_independent_public_calls_and_builds_fresh_each_time(family):
    args = status_arguments(family)
    before = deepcopy(args)
    with packet_calls() as old_count:
        expected = unpaired_status(args)
    with packet_calls() as new_count:
        actual = joint._joint_media_review_status_with_description(**args)
    assert actual == expected and actual["status"] == "accepted"
    assert p._canonical(actual) == p._canonical(expected)
    assert old_count == [2] and new_count == [1] and args == before
    actual["accepted"] = False
    with packet_calls() as again:
        assert joint._joint_media_review_status_with_description(**args) == expected
    assert again == [1] and args == before


@pytest.mark.parametrize("change", [
    "source", "bundle", "png", "policy", "identity", "record", "record_fields", "confirmation",
    "expected_review", "principal", "role", "subject", "profile", "raw_alt", "source_and_record",
    "png_and_role", "raw_alt_and_record",
])
def test_current_pair_preserves_status_and_exact_refusal_precedence(change):
    args = status_arguments()
    if change in {"source", "source_and_record"}:
        args["graphic_spec"]["evidence"]["event_id"] += "-changed"
    elif change == "bundle":
        args["draft"]["review_context"]["two_bot"]["bundle"]["where"] += " changed"
    elif change in {"png", "png_and_role"}:
        args["png_bytes"] += b"changed"
    elif change == "policy":
        args["editorial_policy"]["execution_sha256"] = "f" * 64
    elif change == "identity":
        args["draft"]["content_revision"] += 1
    elif change == "record_fields":
        args["record"]["unexpected"] = True
    elif change == "confirmation":
        args["record"]["confirmations"]["text_matches_data"] = False
    elif change == "expected_review":
        args["expected_review_sha256"] = True
    elif change == "principal":
        args["current_principal"] = {"subject": ACTOR.subject, "role": "editor"}
    elif change == "subject":
        args["current_principal"] = Principal("another-invented-editor", "editor", "fixture")
    elif change == "profile":
        args["platform_profiles"]["profile"] = "changed"
    if change in {"raw_alt", "raw_alt_and_record"}:
        args["raw_alt"] = b"Substituted text.\n"
    if change in {"record", "source_and_record", "raw_alt_and_record"}:
        args["record"]["review_sha256"] = "0" * 64
    if change in {"role", "png_and_role"}:
        args["current_principal"] = Principal(ACTOR.subject, "viewer", "revoked")
    before = deepcopy(args)
    try:
        expected = unpaired_status(args)
    except (MediaReviewError, descriptions.DescriptionError) as old:
        with pytest.raises(type(old)) as new:
            joint._joint_media_review_status_with_description(**args)
        assert str(new.value) == str(old)
    else:
        actual = joint._joint_media_review_status_with_description(**args)
        assert actual == expected and actual["accepted"] is False
        assert p._canonical(actual) == p._canonical(expected)
    assert args == before


def parked_draft(case):
    """Invented retained approval SQL rows exercise only review currentness.

    This does not run or certify checks/approval. Real command/result readers
    verify these rows; no domain validator or status is stubbed.
    """
    from src.commands import postgres_editor_media as editor
    from tests.test_media_attachment import revision
    from uuid import UUID
    draft = deepcopy(case["after"]["drafts"][0])
    binding = draft["media_review_binding"]
    command = Command.from_request(dict(command_id=str(UUID(int=91)), action="approve_media_revision",
        requested_at=AT, expires_at=case["command"].expires_at, targets=[revision(draft)], payload=dict(
            expected_policy_sha256=fingerprint(case["inputs"]["editorial_policy"]),
            expected_renderer_profile_sha256="c" * 64, expected_packet_sha256=binding["packet_sha256"],
            expected_review_sha256=binding["review_sha256"], expected_check_completion_sha256="f" * 64,
            reason="Invented retained approval boundary")), Principal(ACTOR.subject, "publisher", "fixture"),
        environment="local", now=NOW)
    revoke_approval(draft)
    draft["approval_binding"] = dict(schema_version=2, media=deepcopy(binding),
        decision_revision=draft["decision_revision"], command_id=command.command_id,
        publish_intent_id=str(UUID(int=92)))
    state = deepcopy(case["after"])
    state["drafts"] = [draft]
    case["sql"].snapshot("command-core-v1", "2", state)
    result = dict(status="applied", command_id=command.command_id, digest=command.digest,
        actor_subject=command.actor_subject, completed_at=AT, state_version=2,
        publish_intent_id=draft["approval_binding"]["publish_intent_id"])
    case["sql"].command(command, result)
    assert command.action == "approve_media_revision" and editor.SCOPE == "local_joint_media"
    return draft


@pytest.mark.parametrize("family", ["temperature", "pm25", "modis"])
@pytest.mark.parametrize("change", [None, "counter", "binding", "intent"], ids=["current", "counter", "binding", "intent"])
def test_parked_current_review_keeps_independent_builds_and_exact_transition_guards(family, change):
    from src.commands import postgres_editor_media as editor
    case = make_case(family)
    retain(case, prepare(case))
    preparation(case)
    draft = parked_draft(case)
    if change == "counter":
        draft["decision_revision"] += 1
    elif change == "binding":
        draft["approval_binding"]["media"]["review_sha256"] = "0" * 64
    elif change == "intent":
        draft["approval_binding"]["publish_intent_id"] = "changed"
    before = deepcopy(draft)
    def current():
        return editor._reviewed(case["authority"], case["sql"], draft, current_inputs(case),
            case["inputs"]["editorial_policy"], lambda subject: ACTOR)
    with packet_calls() as count:
        if change is None:
            package, record = current()
            assert record == case["transition"].review and package["capture"] == case["capture"]
            assert count == [7]  # Different decision counters keep both builds.
        else:
            with pytest.raises(CommandError) as caught:
                current()
            assert caught.value.code == "joint_media_review_obsolete" and count == [5]
    assert draft == before


@pytest.mark.parametrize("name", ["packet", "status", "platform_description", "expected_draft_identity"])
def test_current_pair_accepts_no_supplied_proof(name):
    args = status_arguments()
    with pytest.raises(TypeError, match=name):
        joint._joint_media_review_status_with_description(**dict(args, **{name: args["record"]["packet"]}))
