"""Local editor/media join over the existing commands, packages and check engine.

Native work is detached from SQL. Every current operation resolves provenance
and permission independently; historical raw retention grants no new work.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import os
import stat
from uuid import NAMESPACE_URL, uuid5

from src.commands import hosted_fixture
from src.commands import postgres_revision_checks as revisions
from src.commands import postgres_checks as checks
from src.commands import postgres_media as media, postgres_media_commands as media_commands
from src.commands import postgres_sourced_generation as generation
from src.commands.postgres_candidate_admission import refuse
from src.commands.reducer import Reduction, _identity, _target_drafts
from src.commands.schema import CommandError, Principal, authorize, utc_datetime, utc_text
from src.editorial.revisions import draft_identity, fingerprint, revoke_approval
from src.media.attachment import build_media_attachment_proposal, build_media_removal_proposal
from src.media.joint_review import joint_media_review_status
from src.media.review_packet import build_media_review_packet
from src.media import platform_description as descriptions
from src.storage import postgres_projection as p

PREPARATION = "editor-media-preparation-v1"
SCOPE = "local_joint_media"


def configure(authority, *, rasterizer, scratch, dependency_manifest):
    refuse(hosted_fixture.allowed(authority), "editor_media_local_only")
    binary, folder = Path(rasterizer), Path(scratch)
    refuse(binary.is_absolute() and folder.is_absolute() and not binary.is_symlink()
           and binary.is_file() and os.access(binary, os.X_OK), "native_renderer_unavailable")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    meta = folder.stat()
    refuse(not folder.is_symlink() and stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid()
           and stat.S_IMODE(meta.st_mode) == 0o700, "private_media_scratch_required")
    from src.media.native_profile import load
    load(dependency_manifest, rasterizer=str(binary))
    authority.editor_media_configuration = dict(rasterizer=str(binary.resolve()), scratch=str(folder.resolve()),
        dependency_manifest=str(Path(dependency_manifest).absolute()))


def profile(authority, spec):
    """Actual native closure, independent of the dashboard SVG manifest."""
    from src.media.evidence_graphic_render import _renderer_identity
    config = getattr(authority, "editor_media_configuration", None)
    refuse(hosted_fixture.allowed(authority) and type(config) is dict, "editor_media_unavailable")
    assert isinstance(config, dict)
    from src.media.native_profile import load
    try:
        _, dependencies_sha256 = load(config["dependency_manifest"], rasterizer=config["rasterizer"])
    except (OSError, ValueError, KeyError, TypeError):
        raise CommandError("native_renderer_unavailable", "The declared local renderer dependencies changed") from None
    binary = Path(config["rasterizer"])
    refuse(binary.is_absolute() and binary.is_file() and not binary.is_symlink()
           and os.access(binary, os.X_OK), "native_renderer_unavailable")
    if spec["template"] == "published_nws_radar":
        from importlib.metadata import version
        from src.media import published_radar
        renderer = dict(library="Pillow", version=version("pillow"), width=600, height=550,
            implementation_sha256=p._sha(Path(published_radar.__file__).read_bytes()), dependencies_sha256=dependencies_sha256)
    else:
        renderer = {**_renderer_identity(spec["template"], spec["evidence"]), "rasterizer_sha256": p._sha(binary.read_bytes())}
    root = Path(__file__).parents[1]
    sources: tuple[str, ...] = ("commands/preview_media_worker.py", "commands/postgres_editor_media.py", "dashboard_preview/preview.py")
    if spec["template"] == "published_nws_radar":
        sources += ("media/published_radar.py", "commands/postgres_published_media.py")
    identity = dict(schema_version=1, renderer=renderer, dependencies_sha256=dependencies_sha256,
                    sources={name:p._sha((root/name).read_bytes()) for name in sources})
    if spec["template"] == "published_nws_radar":
        identity["selection_sha256"] = spec["evidence"]["selection_sha256"]
    return fingerprint(identity), renderer


def inputs(authority, c, draft, policy, now):
    """A saved source origin is immutable; its present allowlist is not."""
    from src.two_bot.check_origin import SOURCE_NAMESPACE
    refuse(generation.exists(c, SOURCE_NAMESPACE, fingerprint({"draft_id":draft["id"]})), "saved_source_origin_unavailable")
    ref, origin, captured = revisions.source(c, draft)
    config = generation.configuration(authority)
    refuse(origin["brief_id"] in config["current_inputs"], "media_source_not_allowlisted")
    source = generation.document(generation.read(c, generation.INPUT, origin["brief_id"]))
    current = [generation.document(generation.read(c, generation.INPUT, i)) for i in config["current_inputs"]]
    refuse(sum((row["source_key"], row["save"]["event_id"]) == (source["source_key"], source["save"]["event_id"])
               for row in current) == 1, "media_source_revision_ambiguous")
    refuse(now < min(utc_datetime(origin["source_useful_until"]), utc_datetime(origin["provenance_useful_until"])),
           "media_source_expired")
    from src.dashboard_preview.errors import PreviewError
    from src.dashboard_preview.preview import qualified_spec
    from src.media.evidence_graphic import MAP_TEMPLATES
    from src.media.fire_map_graphic_adapter import MapQualificationError
    try:
        if captured["bundle"].get("signal_kind") == "severe_weather":
            from src.commands.postgres_published_media import current as radar_current
            spec = radar_current(authority, c, origin["brief_id"], captured["bundle"], ref, now)
            label, context = "Published NWS radar · human label review required", spec["evidence"]["scope"]
        else:
            try:
                spec, label, context = qualified_spec(captured["bundle"], synthetic=True, include_viirs=True)
            except MapQualificationError:
                raise
            except (PreviewError, ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError,
                    OverflowError):
                # The source adapters refuse unsupported products, mixed sets and
                # unbound receipts deterministically. The authority re-raises
                # ValueError for editor actions, so an unconverted refusal would
                # leave a prepare intent pending ahead of every later command.
                raise CommandError("graphic_source_unqualified",
                                   "This saved source does not qualify for a graphic") from None
        if spec["template"] in MAP_TEMPLATES:
            from src.media.evidence_graphic_render import map_text_layout
            map_text_layout(spec["evidence"])
    except MapQualificationError as exc:
        raise CommandError(exc.code, "This source cannot be shown within the qualified map display limits") from None
    digest, renderer = profile(authority, spec)
    return dict(source_origin=ref, source=origin, spec=spec, profile_sha256=digest, renderer=renderer,
                policy_sha256=fingerprint(policy), source_label=label, source_context=context)


def resolve(resolve_principal, subject, *, publisher=False):
    try:
        actor = resolve_principal(subject)
    except Exception:
        raise CommandError("authorization_unavailable", "Current operator authorization is unavailable") from None
    refuse(isinstance(actor, Principal) and actor.subject == subject
           and actor.role in ({"publisher"} if publisher else {"editor", "publisher"}), "forbidden")
    return actor


def command_inputs(authority, c, state, command, actor, policy, now):
    refuse(actor.subject == command.actor_subject, "forbidden")
    authorize(actor, command.action)
    refuse(now < utc_datetime(command.expires_at), "command_expired")
    refuse(utc_datetime(command.requested_at) <= now + timedelta(minutes=5), "invalid_time")
    draft = _target_drafts(state, command)[0]
    value = inputs(authority, c, draft, policy, now)
    refuse(command.payload["expected_policy_sha256"] == value["policy_sha256"], "editorial_policy_changed")
    if "expected_renderer_profile_sha256" in command.payload:
        refuse(command.payload["expected_renderer_profile_sha256"] == value["profile_sha256"], "native_renderer_changed")
    return draft, value


def package_current(authority, c, draft, proposal, value, policy):
    package = media.read(c, proposal, authority.environment)
    capture = package["capture"]
    refuse(capture["predecessor_state"]["drafts"][0]["id"] == draft["id"], "media_draft_mismatch")
    retained = generation.read(c, PREPARATION, proposal)
    refuse(retained["draft_id"] == draft["id"] and retained["proposal_sha256"] == proposal
           and retained["renderer_profile_sha256"] == value["profile_sha256"], "native_renderer_changed")
    intent = authority._intent(c, retained["command_id"])
    result = authority._result(c, retained["command_id"])
    refuse(intent is not None and intent[0].action == "prepare_media_revision" and result is not None
           and result["status"] == "unchanged" and result["media_preparation"] == retained,
           "media_preparation_not_retained")
    refuse(p._canonical(capture["inputs"]["graphic_spec"]) == p._canonical(value["spec"])
           and p._canonical(capture["inputs"]["renderer_manifest"]["binding"]["renderer"]) == p._canonical(value["renderer"]),
           "media_source_or_renderer_changed")
    return package


def packet_for(draft, package, policy):
    stored = package["capture"]["inputs"]
    return build_media_review_packet(draft, expected_draft_identity=draft_identity(draft), editorial_policy=policy,
        graphic_spec=stored["graphic_spec"], renderer_manifest=stored["renderer_manifest"], png_bytes=package["assets"]["preview.png"])


def reviewed(authority, c, draft, value, policy, resolve_principal):
    binding = draft.get("media_review_binding")
    refuse(type(binding) is dict and "media_attachment" in draft, "joint_media_review_required")
    package = package_current(authority, c, draft, binding["proposal_sha256"], value, policy)
    intent = authority._intent(c, binding["command_id"])
    result = authority._result(c, binding["command_id"])
    refuse(intent is not None and result is not None, "joint_media_review_not_retained")
    retained = media_commands.read(c, intent[0], result, authority.environment)
    record = retained["review"]
    refuse(retained["review"]["review_sha256"] == binding["review_sha256"]
           and record["packet"]["packet_sha256"] == binding["packet_sha256"], "joint_media_review_changed")
    reviewer = resolve(resolve_principal, record["reviewer"]["subject"])
    stored = package["capture"]["inputs"]
    platform_inputs = {}
    if record.get("schema_version") == 3:
        from src.commands.postgres_delivery import description_profiles
        retained_description = record["platform_description"]
        refuse(binding.get("schema_version") == 2 and binding.get("platform_description_sha256") == retained_description["description_sha256"],
               "platform_description_changed")
        checked_draft = deepcopy(draft)
        # Parking advances the decision counter once without changing content.
        # Only the exact retained approval transition may preserve this review.
        reviewed_revision = retained_description["target"]["decision_revision"]
        if draft["decision_revision"] != reviewed_revision:
            approval = draft.get("approval_binding", {})
            refuse(approval.get("schema_version") == 2 and approval.get("media") == binding
                and draft["decision_revision"] == reviewed_revision + 1
                and approval.get("decision_revision") == draft["decision_revision"], "joint_media_review_obsolete")
            approval_intent = authority._intent(c, approval["command_id"])
            approval_result = authority._result(c, approval["command_id"])
            refuse(approval_intent is not None and approval_result is not None
                and approval_intent[0].action == "approve_media_revision"
                and approval_intent[0].targets[0].decision_revision == reviewed_revision
                and approval_result["status"] == "applied"
                and approval_result["publish_intent_id"] == approval["publish_intent_id"], "joint_media_review_obsolete")
            checked_draft["decision_revision"] = reviewed_revision
        platform_inputs["platform_description"] = media_commands.description_for(
            checked_draft, package, policy, description_profiles(authority))
    status = joint_media_review_status(record, draft, expected_review_sha256=binding["review_sha256"],
        current_principal=reviewer, expected_draft_identity=draft_identity(draft), editorial_policy=policy,
        graphic_spec=stored["graphic_spec"], renderer_manifest=stored["renderer_manifest"], png_bytes=package["assets"]["preview.png"], **platform_inputs)
    refuse(status["current"] is True and status["accepted"] is True, "joint_media_review_obsolete")
    return package


def boundary(authority, c, state, version, command, actor, policy, now, resolve_principal, prepared=None):
    """Called in the command savepoint. All writes roll back with any refusal."""
    draft, value = command_inputs(authority, c, state, command, actor, policy, now)
    payload = command.payload
    unchanged = Reduction(state, (), ())
    if command.action == "prepare_media_revision":
        refuse(type(prepared) is dict and prepared.get("command_id") == command.command_id,
               "native_preparation_required")
        refuse(prepared["checkpoint"] == fingerprint(dict(target=_identity(draft), inputs=value)), "media_preparation_obsolete")
        if value["spec"]["template"] == "published_nws_radar":
            refuse(now >= utc_datetime(prepared["started_at"]), "media_completion_clock_regressed")
        if prepared.get("failure"):
            refuse(False, prepared["failure"])
        manifest, assets = prepared["manifest"], prepared["assets"]
        refuse(p._canonical(manifest["binding"]["renderer"]) == p._canonical(value["renderer"]), "native_renderer_changed")
        # The command retains its original ISO spelling; the older package
        # contract requires the canonical UTC spelling at this boundary.
        proposal_at = utc_text(utc_datetime(command.requested_at))
        proposal = build_media_attachment_proposal(state, draft["id"], expected_revision=_identity(draft),
            editorial_policy=policy, graphic_spec=value["spec"], renderer_manifest=manifest,
            png_bytes=assets["preview.png"], at=proposal_at)
        request = dict(expected_revision=_identity(draft), expected_policy_sha256=fingerprint(policy), graphic_spec=value["spec"],
            renderer_manifest=manifest, proposal_at=proposal_at, expected_proposal_sha256=proposal["proposal_sha256"])
        request, assets = media.prepare(request, assets)
        media.stage(c, draft["id"], request, assets=assets, principal=actor, state=state, authority_version=version,
                    policy=policy, now=now, environment=authority.environment)
        refs = dict(status="staged", command_id=command.command_id, draft_id=draft["id"], proposal_sha256=proposal["proposal_sha256"],
            packet_sha256=proposal["packet"]["packet_sha256"], renderer_profile_sha256=value["profile_sha256"],
            publication_approved=False)
        generation.record(c, PREPARATION, proposal["proposal_sha256"], refs)
        return unchanged, "media_preparation", refs
    reviewed(authority, c, draft, value, policy, resolve_principal)
    binding = draft["media_review_binding"]
    refuse(binding["packet_sha256"] == payload["expected_packet_sha256"]
           and binding["review_sha256"] == payload["expected_review_sha256"], "joint_media_review_changed")
    if command.action == "request_revision_checks":
        identity = revisions.enroll(c, state, version, draft, now=now, policy=policy,
            profile=value["profile_sha256"], environment=authority.environment)
        return unchanged, "revision_checks", dict(check_set_id=identity, publication_approved=False)
    refuse(command.action == "approve_media_revision", "editor_media_action_refused")
    original, identity, packet = requested(authority, c, draft, version, state, value, now)
    resolve(resolve_principal, original.actor_subject)
    completion = completed(c, identity, packet, now, authority.environment)
    refuse(completion["completion_sha256"] == payload["expected_check_completion_sha256"], "check_completion_changed")
    proposed = deepcopy(draft)
    revoke_approval(proposed)
    intent_id = str(uuid5(NAMESPACE_URL, "theheat:local-joint-media:" + command.command_id))
    proposed["approval_binding"] = dict(schema_version=2 if binding.get("schema_version") == 2 else 1, scope=SCOPE, **draft_identity(proposed),
        decision_revision=proposed["decision_revision"], command_id=command.command_id,
        publish_intent_id=intent_id, policy_sha256=fingerprint(policy), renderer_profile_sha256=value["profile_sha256"],
        media=deepcopy(binding), completion=completion, consumed_state_version=version,
        consumed_state_sha256=p._sha(p._canonical(state)), resulting_state_version=version + 1,
        requesting_actor=original.actor_subject, publisher_subject=actor.subject, useful_until=packet["useful_until"])
    proposed.update(status="pending", publish_intent_id=intent_id, updated_at=command.requested_at)
    updated = deepcopy(state)
    updated["drafts"] = [proposed if isinstance(d, dict) and d.get("id") == draft["id"] else d for d in updated["drafts"]]
    return Reduction(updated, (draft["id"],), (_identity(proposed),), intent_id), "media_approval", dict(
        scope=SCOPE, parked=True, publication_approved=False, check_set_id=identity,
        completion_sha256=completion["completion_sha256"], consumed_state_version=version, resulting_state_version=version + 1)


def requested(authority, c, draft, version, state, value, now):
    """Find one exact current enrollment, never choose an older passing proof."""
    rows = c.execute("SELECT i.command_id FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) ORDER BY i.sequence DESC LIMIT 1024").fetchall()
    for (command_id,) in rows:
        command, _ = authority._intent(c, command_id)
        if command.action != "request_revision_checks" or command.targets[0].draft_id != draft["id"]:
            continue
        result = authority._result(c, command_id)
        if result["status"] == "rejected":
            continue
        identity = result["revision_checks"]["check_set_id"]
        packet, _ = checks._packet(c, identity, authority.environment)
        if packet["draft_target"] != _identity(draft):
            continue
        refuse(packet["state_version"] == version and packet["state_sha256"] == p._sha(p._canonical(state))
               and packet["renderer_profile_sha256"] == value["profile_sha256"]
               and packet["source_origin"] == value["source_origin"] and utc_text(now) < packet["useful_until"],
               "revision_checks_obsolete")
        return command, identity, packet
    raise CommandError("revision_checks_required", "Run checks for the current text and graphic")


def completed(c, identity, packet, now, environment):
    owner, fence = "revision-checks:" + packet["enrollment_id"], None
    lease = c.execute("SELECT fence,owner FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (identity,)).fetchone()
    refuse(lease is not None and lease[1] == owner, "revision_check_lease_required")
    fence = lease[0]
    try:
        checks._current(c, packet, dict(owner=owner, fence=fence, current_context=packet["current_context"],
            checker_state_sha256=packet["checker_state_sha256"]), utc_text(now), environment)
    except checks.checks.CheckJournalError as exc:
        if str(exc) not in {"changed_revision_check_state", "revision_check_expired", "stale_revision_check_owner"}:
            raise
        raise CommandError(str(exc), "The retained check authority is stale; refresh the current revision") from None
    proofs, _ = checks.verified_stage_receipts(c, identity, packet, owner=owner, fence=fence, environment=environment)
    body = dict(schema_version=1, origin_kind=packet["origin_kind"], enrollment_id=packet["enrollment_id"],
                check_set_id=identity, packet_sha256=p._sha(p._canonical(packet)), stages=proofs)
    return {**body, "completion_sha256": fingerprint(body)}


def runner_context(authority, c, command_id, resolve_principal, state, version, policy, now):
    intent = authority._intent(c, command_id)
    result = authority._result(c, command_id)
    refuse(intent is not None and intent[0].action == "request_revision_checks"
           and result is not None and result["status"] == "unchanged", "revision_check_request_required")
    command = intent[0]
    actor = resolve(resolve_principal, command.actor_subject)
    # The accepted request's short lifetime bounds intake, not a retained grant.
    draft = _target_drafts(state, command)[0]
    value = inputs(authority, c, draft, policy, now)
    reviewed(authority, c, draft, value, policy, resolve_principal)
    identity = result["revision_checks"]["check_set_id"]
    packet, _ = checks._packet(c, identity, authority.environment)
    refuse(packet["state_version"] == version and packet["state_sha256"] == p._sha(p._canonical(state))
           and packet["renderer_profile_sha256"] == value["profile_sha256"] and packet["source_origin"] == value["source_origin"]
           and packet["current_context"]["policy_sha256"] == fingerprint(policy)
           and utc_text(now) < packet["useful_until"] and utc_text(now)[:10] == packet["check_date"], "revision_checks_obsolete")
    return command, identity, packet, actor


def parked(authority, c, draft, state, version, value, policy, now, resolve_principal):
    binding = draft.get("approval_binding")
    if not isinstance(binding, dict) or binding.get("scope") != SCOPE:
        return False
    refuse(draft.get("status") == "pending" and binding["resulting_state_version"] == version
           and draft.get("publish_intent_id") == binding["publish_intent_id"]
           and all(binding[k] == v for k,v in draft_identity(draft).items())
           and binding["decision_revision"] == draft["decision_revision"], "parked_media_obsolete")
    command, _ = authority._intent(c, binding["command_id"])
    result = authority._result(c, binding["command_id"])
    refuse(command.action == "approve_media_revision" and result is not None and result["status"] == "applied"
           and result["state_version"] == version and result["publish_intent_id"] == binding["publish_intent_id"]
           and result["media_approval"]["completion_sha256"] == binding["completion"]["completion_sha256"], "parked_media_not_retained")
    _, retained = authority.projections._read(c, "command-core-v1", str(version))
    refuse(p._canonical(retained) == p._canonical(state), "parked_media_state_changed")
    resolve(resolve_principal, command.actor_subject, publisher=True)
    resolve(resolve_principal, binding["requesting_actor"])
    reviewed(authority, c, draft, value, policy, resolve_principal)
    packet, _ = checks._packet(c, binding["completion"]["check_set_id"], authority.environment)
    refuse(packet["state_version"] == binding["consumed_state_version"]
           and packet["state_sha256"] == binding["consumed_state_sha256"]
           and packet["current_context"]["policy_sha256"] == value["policy_sha256"] == binding["policy_sha256"]
           and packet["renderer_profile_sha256"] == value["profile_sha256"] == binding["renderer_profile_sha256"]
           and packet["source_origin"] == value["source_origin"] and utc_text(now) < packet["useful_until"] == binding["useful_until"],
           "parked_media_obsolete")
    # The consumed predecessor remains the check origin; subsequent authority
    # writes invalidate this parked decision, even when their prose is unchanged.
    lease = c.execute("SELECT fence,owner,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1",
                      (binding["completion"]["check_set_id"],)).fetchone()
    refuse(lease is not None and lease[1] == "revision-checks:" + packet["enrollment_id"]
           and utc_text(now) < lease[2], "parked_media_lease_expired")
    proofs, _ = checks.verified_stage_receipts(c, binding["completion"]["check_set_id"], packet,
        owner=lease[1], fence=lease[0], environment=authority.environment)
    proof = dict(schema_version=1, origin_kind=packet["origin_kind"], enrollment_id=packet["enrollment_id"],
                 check_set_id=binding["completion"]["check_set_id"], packet_sha256=p._sha(p._canonical(packet)), stages=proofs)
    refuse(p._canonical({**proof, "completion_sha256":fingerprint(proof)}) == p._canonical(binding["completion"]), "parked_media_proof_changed")
    return True


def retained_package(authority, c, draft_id, png_proposal, *, original=False):
    # Passive historical evidence has an exact retained key. It must not
    # depend on the current mutation eligibility or a recent-list window.
    media._sha(png_proposal)
    refuse(generation.exists(c, PREPARATION, png_proposal), "media_preparation_not_retained")
    reference = generation.read(c, PREPARATION, png_proposal)
    intent = authority._intent(c, reference["command_id"])
    refuse(intent is not None, "media_preparation_not_retained")
    command, _ = intent
    result = authority._result(c, reference["command_id"])
    refuse(command.action == "prepare_media_revision" and len(command.targets) == 1
           and command.targets[0].draft_id == reference["draft_id"] == draft_id
           and command.command_id == reference["command_id"] and result is not None
           and reference["proposal_sha256"] == png_proposal and reference["status"] == "staged"
           and reference["publication_approved"] is False and result["status"] == "unchanged"
           and p._canonical(result["media_preparation"]) == p._canonical(reference),
           "media_preparation_not_retained")
    return media.read_retained_package(c, expected_proposal_sha256=reference["proposal_sha256"],
        expected_packet_sha256=reference["packet_sha256"], expected_predecessor=command.targets[0].as_dict(),
        expected_subject=command.actor_subject, expected_at=utc_text(utc_datetime(command.requested_at)),
        environment=authority.environment, original_bytes=original)


def projection(authority, c, draft_id, *, state, version, policy, now, resolve_principal, png_proposal=None, original=False):
    matches = [d for d in state["drafts"] if isinstance(d, dict) and d.get("id") == draft_id]
    refuse(len(matches) == 1, "draft_not_found")
    draft = matches[0]
    if png_proposal is not None:
        package = retained_package(authority, c, draft_id, png_proposal, original=original)
        return package["assets"]["original.gif" if original else "preview.png"]
    view = dict(draft_id=draft_id, target=_identity(draft), status="unavailable", text=draft["text"],
        publication_approved=False, local_preview=True, parked=False, review_current=False, checks_status="not_requested",
        expected_check_completion_sha256=None, preparation=None, packet=None)
    # Removing content is an invalidation operation, not new source/renderer
    # authority. An outage must never strand an attached graphic.
    if "media_attachment" in draft:
        removal = build_media_removal_proposal(state, draft_id, expected_revision=_identity(draft), at=utc_text(now))
        view.update(expected_policy_sha256=fingerprint(policy), removal=dict(expected_proposal_sha256=removal["proposal_sha256"],
            requested_at=utc_text(now), expires_at=utc_text(now + timedelta(minutes=5))))
    # Relationship authorization comes from immutable successful preparations,
    # never from a caller-supplied digest or copied draft media fields.
    refs = []
    rows = c.execute("SELECT i.command_id FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) ORDER BY i.sequence DESC LIMIT 1024").fetchall()
    for (command_id,) in rows:
        command, _ = authority._intent(c, command_id)
        if command.action != "prepare_media_revision" or command.targets[0].draft_id != draft_id:
            continue
        result = authority._result(c, command_id)
        if result["status"] == "unchanged":
            refs.append(result["media_preparation"])
        if len(refs) == 64:
            break
    try:
        value = inputs(authority, c, draft, policy, now)
        if value["spec"]["template"] == "published_nws_radar":
            evidence = value["spec"]["evidence"]
            view["published"] = dict(station="KTLX", frame_minute_utc=evidence["input"]["metadata"]["frame_minute_utc"],
                units="dBZ", context="Radar context at Oklahoma City; not the full warning footprint or evidence of surface impacts.",
                useful_until=evidence["useful_until"], synthetic=evidence["synthetic"], source_credit="NATIONAL WEATHER SERVICE")
        view.update(status="ready", expected_policy_sha256=value["policy_sha256"],
            expected_renderer_profile_sha256=value["profile_sha256"], source_label=value["source_label"], source_context=value["source_context"])
        for reference in refs:
            try:
                package = package_current(authority, c, draft, reference["proposal_sha256"], value, policy)
                if "media_attachment" in draft:
                    packet = packet_for(draft, package, policy)
                    mode = "attached"
                else:
                    capture = package["capture"]
                    if capture["proposal"]["predecessor"] != _identity(draft):
                        continue
                    packet = capture["proposal"]["packet"]
                    mode = "prepared"
                view.update(status=mode, preparation=reference, packet=packet)
                from src.commands.postgres_delivery import description_profiles
                prospective = deepcopy(draft) if mode == "attached" else deepcopy(package["capture"]["proposal"]["proposed_draft"])
                if mode == "attached":
                    revoke_approval(prospective)
                description = media_commands.description_for(prospective, package, policy, description_profiles(authority))
                fit = "fits_local_limits"
                try:
                    descriptions.preflight(description, raw_alt=package["assets"]["alt.txt"], png=package["assets"]["preview.png"],
                        expected_profiles=description_profiles(authority))
                except descriptions.DescriptionError as exc:
                    fit = exc.code
                view["platform_description"] = dict(record=description,
                    wire_text=package["assets"]["alt.txt"].decode("utf-8"), status=fit,
                    qualification="offline_fixture_only" if description["profiles"]["profile"] == descriptions.FIXTURE_PROFILE else "unqualified")
                break
            except (CommandError, ValueError):
                continue
        if "media_attachment" in draft:
            try:
                reviewed(authority, c, draft, value, policy, resolve_principal)
                view["review_current"] = True
                view["expected_review_sha256"] = draft["media_review_binding"]["review_sha256"]
                try:
                    view["parked"] = parked(authority, c, draft, state, version, value, policy, now, resolve_principal)
                    if view["parked"]:
                        view["checks_status"] = "passed"
                        return view
                except CommandError as exc:
                    view["parked_status"] = exc.code
                original, identity, packet = requested(authority, c, draft, version, state, value, now)
                resolve(resolve_principal, original.actor_subject)
                view.update(check_set_id=identity, check_command_id=original.command_id, checks_status="pending")
                stages, _ = checks._stages(c, identity, packet, packet["captured_at"])
                view["checks"] = stages
                if all(s == "passed" for s in stages.values()):
                    proof = completed(c, identity, packet, now, authority.environment)
                    view.update(checks_status="passed", expected_check_completion_sha256=proof["completion_sha256"])
                elif any(s not in {"pending", "passed"} for s in stages.values()):
                    view["checks_status"] = "needs_attention"
            except CommandError as exc:
                view["checks_status"] = exc.code
    except CommandError as exc:
        view.update(status="unavailable", code=exc.code)
    refuse(len(p._canonical(view)) <= 128*1024, "media_view_bound")
    return view
