"""Local editor/media join over the existing commands, packages and check engine.

Native work is detached from SQL. Every current operation resolves provenance
and permission independently; historical raw retention grants no new work.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import math
import threading
from time import monotonic as _passive_monotonic
from typing import Any
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
from src.editorial.policy import current_editorial_policy
from src.media.attachment import build_media_attachment_proposal, build_media_removal_proposal
from src.media.joint_review import joint_media_review_status
from src.media.review_packet import build_media_review_packet
from src.media import platform_description as descriptions
from src.storage import postgres_projection as p
from src.two_bot.candidate_derivation import has_ghcn_reference

PREPARATION = "editor-media-preparation-v1"
SCOPE = "local_joint_media"

_PASSIVE_TOKEN = object()


def _open_passive_inspection(authority, now):
    return _PassiveInspection(_PASSIVE_TOKEN, authority, now)


class _PassiveInspection:
    """One lexical passive GET, never command, dispatch or readiness authority."""

    def __init__(self, token, authority, now):
        refuse(token is _PASSIVE_TOKEN, "passive_inspection_required")
        self._identity = id(self)
        self._environment = authority.environment
        self._authority = authority
        self._thread = threading.get_ident()
        self._closed = False
        self._used = False
        self._snapshot_ready = False
        self._capture_started = False
        self._projected = self._delivered = False
        self._start = utc_datetime(utc_text(now))
        self._anchor = _passive_monotonic()
        self._elapsed = 0.0
        self._c: Any = None
        self._pair: Any = None
        self._context: bytes | None = None
        self._proof: Any = None
        self._failure: str | None = None
        self._intent_bytes: bytes | None = None

    def _check(self, authority, c):
        refuse(self._identity == id(self) and not self._closed and authority is self._authority
               and authority.environment == self._environment
               and threading.get_ident() == self._thread and c is self._c,
               "passive_inspection_context_changed")

    def now(self):
        self._check(self._authority, self._c)
        elapsed = _passive_monotonic() - self._anchor
        refuse(math.isfinite(elapsed) and elapsed >= self._elapsed and elapsed >= 0,
               "invalid_time")
        self._elapsed = elapsed
        return self._start + timedelta(seconds=elapsed)

    def bind(self, c, state, version, policy, claim):
        self._check(self._authority, None)
        refuse(self._c is None and c is not None and type(version) is int, "passive_inspection_context_changed")
        self._c, self._state, self._version = c, state, version
        self._policy, self._claim = policy, claim
        self._state_bytes = p._canonical(state)
        self._policy_bytes = p._canonical(policy)

    def project(self, draft_id, resolve_principal):
        self._check(self._authority, self._c)
        refuse(not self._projected, "passive_inspection_context_changed")
        self._projected = True
        return _projection(self._authority, self._c, draft_id, state=self._state, version=self._version,
            policy=self._policy, now=self._start, resolve_principal=resolve_principal,
            claim=self._claim, _inspection=self)

    def delivery(self, draft_id, resolve_principal):
        from src.commands import postgres_delivery as delivery
        self._check(self._authority, self._c)
        refuse(not self._delivered, "passive_inspection_context_changed")
        self._delivered = True
        if not self._snapshot_ready:
            return delivery.projection(self._authority, self._c, draft_id, resolve_principal,
                self._start, claim=self._claim)
        return delivery._projection(self._authority, self._c, draft_id, resolve_principal,
            self._start, claim=self._claim, _inspection=self)

    def _binding(self, draft, value, policy):
        return p._canonical(dict(draft=draft, inputs=value, policy=policy))

    def start_inputs(self):
        self._check(self._authority, self._c)
        if self._capture_started:
            return self._snapshot_ready
        self._capture_started = True
        from src.commands import postgres_delivery as delivery
        # This extra capture must never become an earlier outward validation gate.
        # On failure, let the original full paths determine their own order/fields.
        try:
            source_loader = getattr(self._authority, "generation_configuration", None)
            delivery_loader = getattr(self._authority, "delivery_configuration", None)
            source_config = p._canonical(generation.configuration(self._authority))
            delivery_config = p._canonical(delivery.configuration(self._authority)) if hasattr(self._authority, "delivery_configuration") else None
            native_config = p._canonical(getattr(self._authority, "editor_media_configuration", None))
        except Exception:
            self._snapshot_ready = False
            return False
        self._source_loader, self._delivery_loader = source_loader, delivery_loader
        self._source_config, self._delivery_config = source_config, delivery_config
        self._native_config = native_config
        self._snapshot_ready = True
        return True

    def review(self, authority, c, draft, value, policy, resolve_principal):
        self._check(authority, c)
        binding = self._binding(draft, value, policy)
        refuse(self._snapshot_ready and self._pair is None and self._context is None,
               "passive_inspection_context_changed")
        package, record = _reviewed(authority, c, draft, value, policy, resolve_principal)
        refuse(binding == self._binding(draft, value, policy), "passive_inspection_context_changed")
        self._pair = deepcopy((package, record))
        self._context = binding
        self._draft, self._inputs = deepcopy(draft), deepcopy(value)
        return package, record

    def parked_review(self, authority, c, draft, value, policy):
        self._check(authority, c)
        refuse(self._pair is not None and self._context == self._binding(draft, value, policy),
               "passive_inspection_context_changed")
        return self._pair[0]

    def verified(self, packet, deadline, *, day_bound=True):
        self._check(self._authority, self._c)
        refuse(self._pair is not None and self._proof is None, "passive_inspection_context_changed")
        self._proof = deepcopy(packet), deadline, day_bound

    def matches(self, authority, c, value):
        self._check(authority, c)
        return (self._snapshot_ready and self._proof is not None and value["draft_id"] == self._draft["id"]
            and p._canonical(value["approval_binding"]) == p._canonical(self._draft.get("approval_binding"))
            and value["intent_id"] == self._draft.get("publish_intent_id"))

    def consume(self, authority, c, draft, state, version, value, policy, claim, intent, resolve_principal):
        self._check(authority, c)
        refuse(not self._used and self.matches(authority, c, intent), "passive_inspection_context_changed")
        self._used = True
        refuse(type(version) is int and version == self._version and p._canonical(state) == self._state_bytes
               and claim is self._claim, "passive_inspection_context_changed")
        package, record = self._pair
        _package_current(authority, c, draft, draft["media_review_binding"]["proposal_sha256"], value, package)
        refuse(p._canonical(policy) == self._policy_bytes, "joint_media_review_obsolete")
        refuse(self._context == self._binding(draft, value, policy), "media_source_or_renderer_changed")
        resolve(resolve_principal, record["reviewer"]["subject"])
        self._intent_bytes = p._canonical(intent)
        return deepcopy(package), deepcopy(record)

    def refused(self, authority, c, intent, code):
        if self.matches(authority, c, intent):
            self._failure = code

    def finish(self, view, resolve_principal):
        self._check(self._authority, self._c)
        if not self._snapshot_ready or self._proof is None:
            return
        try:
            _, record = self._pair
            refuse(p._canonical(generation.configuration(self._authority)) == self._source_config,
                   "media_source_not_allowlisted")
            from src.commands import postgres_delivery as delivery
            config = p._canonical(delivery.configuration(self._authority)) if hasattr(self._authority, "delivery_configuration") else None
            refuse(config == self._delivery_config, "delivery_configuration_changed")
            binding = self._draft["approval_binding"]

            def final_roles():
                try:
                    resolve(resolve_principal, record["reviewer"]["subject"])
                except CommandError:
                    view["review_current"] = False
                    raise
                resolve(resolve_principal, binding["publisher_subject"], publisher=True)
                resolve(resolve_principal, binding["requesting_actor"])

            final_roles()
            # One bounded content reread catches same-loader/file changes in roles.
            # Compare ORIGINAL snapshots; never stabilize or accept a new baseline.
            refuse(p._canonical(generation.configuration(self._authority)) == self._source_config,
                   "media_source_not_allowlisted")
            config = p._canonical(delivery.configuration(self._authority)) if hasattr(self._authority, "delivery_configuration") else None
            refuse(config == self._delivery_config, "delivery_configuration_changed")
            final_roles()  # Configuration callbacks may themselves revoke a role.
            if self._failure is not None:
                raise CommandError(self._failure, "The parked projection is no longer current")
            # Cheap bindings follow role callbacks; no claim of external-state atomicity.
            refuse(getattr(self._authority, "generation_configuration", None) is self._source_loader,
                   "media_source_not_allowlisted")
            refuse(getattr(self._authority, "delivery_configuration", None) is self._delivery_loader,
                   "delivery_configuration_changed")
            if self._intent_bytes is not None:
                refuse(p._canonical(delivery.read(self._c, self._draft["publish_intent_id"])) == self._intent_bytes,
                       "delivery_approval_changed")
            version, state = self._authority._state(self._c, lock=True)
            refuse(type(version) is int and version == self._version and p._canonical(state) == self._state_bytes,
                   "parked_media_state_changed")
            refuse(p._canonical(current_editorial_policy()) == self._policy_bytes,
                   "editorial_policy_changed")
            refuse(p._canonical(getattr(self._authority, "editor_media_configuration", None)) == self._native_config,
                   "native_renderer_changed")
            packet, deadline, day_bound = self._proof
            now = self.now()  # Includes claim reconstruction, proofs, second inputs and description work.
            refuse(utc_text(now) < deadline, "parked_media_lease_expired")
            refuse(utc_text(now) < packet["useful_until"] and (not day_bound or utc_text(now)[:10] == packet["check_date"]),
                   "parked_media_obsolete")
            source = self._inputs["source"]
            refuse(now < min(utc_datetime(source["source_useful_until"]), utc_datetime(source["provenance_useful_until"])),
                   "media_source_expired")
            if self._inputs["spec"].get("schema_version") == 6:
                refuse(now < utc_datetime(self._inputs["spec"]["evidence"]["useful_until"]), "media_source_expired")
        except CommandError as exc:
            view.update(parked=False, parked_status=exc.code, checks_status=exc.code)
            for item in view.get("delivery", {}).get("intents", []):
                if item["intent_id"] == self._draft.get("publish_intent_id"):
                    item.update(current=False, reason=exc.code)

    def __copy__(self):
        raise CommandError("passive_inspection_context_changed", "An inspection cannot be copied")

    def __deepcopy__(self, memo):
        raise CommandError("passive_inspection_context_changed", "An inspection cannot be copied")

    def close(self):
        self._closed = True
        self._snapshot_ready = False
        self._pair = self._context = self._proof = self._intent_bytes = None
        self._c = None


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


def qualified(bundle):
    """One saved non-radar source; this editor explicitly adopts VIIRS and GHCN temperature."""
    from src.dashboard_preview.errors import PreviewError
    from src.dashboard_preview.preview import qualified_spec
    from src.media.fire_map_graphic_adapter import MapQualificationError
    try:
        return qualified_spec(bundle, synthetic=True, include_viirs=True, include_temperature=True)
    except MapQualificationError:
        raise
    except (PreviewError, ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError,
            OverflowError):
        # The source adapters refuse unsupported products, mixed sets, unbound
        # receipts and unqualified station warrants deterministically. The
        # authority re-raises ValueError for editor actions, so an unconverted
        # refusal would leave a prepare intent pending ahead of every later command.
        raise CommandError("graphic_source_unqualified",
                           "This saved source does not qualify for a graphic") from None


def qualified_claim(view, source, claim, policy):
    """One saved compact GHCN claim, drawn from its freshly resolved full evidence.

    Only a ResolvedClaim that the caller resolved from operator-retained evidence
    before this connection carries the comparator tables; the draft never does.
    """
    from src.media.temperature_graphic_adapter import temperature_claim_graphic_spec
    from src.storage.cyclone_supply import CycloneSupplyError, digest
    from src.two_bot.ghcn_claim_view import ResolvedClaim
    refuse(type(claim) is ResolvedClaim, getattr(claim, "code", None) or "ghcn_baseline_unavailable")
    try:
        claim.verify_saved(view)
    except CycloneSupplyError as exc:
        raise CommandError(str(exc), "The saved GHCN claim differs from its retained evidence") from None
    refuse(source["schema_version"] == 2 and source["source_key"] == "ghcn" and source["bundle"] == view
           and source["source_revision"] == fingerprint(dict(reference=claim.reference, view_sha256=claim.view_sha256,
                                                             policy_sha256=digest(policy))), "ghcn_claim_source_changed")
    try:
        spec = temperature_claim_graphic_spec(view, claim.full, expected_full_sha256=claim.full_sha256, synthetic=True)
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError, OverflowError):
        raise CommandError("graphic_source_unqualified", "This saved source does not qualify for a graphic") from None
    evidence = spec["evidence"]
    return spec, "NOAA GHCN-Daily · station observations", {
        "kind": "ghcn_station_day", "station_id": evidence["station_id"], "valid_date": evidence["points"][0]["valid_date"],
        "retrieved_at": evidence["evidence_as_of"], "reporting_interval_known": False, "timezone": None}


def view_claim(authority, draft_id):
    """Resolve a compact claim for the read-only view, before its connection.

    This rebuilds the evidence without the dispatch replay or state checkpoint
    that commands require, so it can serve a GET and grants no command authority.
    """
    if not hasattr(authority, "ghcn_baseline"):
        return None
    with authority.projections._connection() as c:
        authority._validate(c)
        _, state = authority._state(c)
    drafts = [d for d in state["drafts"] if isinstance(d, dict) and d.get("id") == draft_id]
    bundle = drafts[0].get("review_context", {}).get("two_bot", {}).get("bundle") if len(drafts) == 1 else None
    if not has_ghcn_reference(bundle):
        return None
    from src.commands.postgres_sourced_generation import GhcnPreparationFailure
    from src.storage.cyclone_supply import CycloneSupplyError
    from src.two_bot.ghcn_claim_view import resolve, structural_view
    try:
        reference = structural_view(bundle)
        return resolve(authority, reference["source_run_id"], reference["selection"])
    except CycloneSupplyError as exc:
        return GhcnPreparationFailure(str(exc))
    except OSError:
        return GhcnPreparationFailure("ghcn_baseline_unavailable")


def inputs(authority, c, draft, policy, now, *, claim=None):
    """A saved source origin is immutable; its present allowlist is not.

    A compact GHCN draft also needs ``claim``, resolved before this connection.
    """
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
    from src.media.evidence_graphic import MAP_TEMPLATES
    from src.media.fire_map_graphic_adapter import MapQualificationError
    try:
        if captured["bundle"].get("signal_kind") == "severe_weather":
            from src.commands.postgres_published_media import current as radar_current
            spec = radar_current(authority, c, origin["brief_id"], captured["bundle"], ref, now)
            label, context = "Published NWS radar · human label review required", spec["evidence"]["scope"]
        elif has_ghcn_reference(captured["bundle"]):
            spec, label, context = qualified_claim(captured["bundle"], source, claim, policy)
        else:
            spec, label, context = qualified(captured["bundle"])
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


def command_inputs(authority, c, state, command, actor, policy, now, *, ghcn=None, version=None):
    """``ghcn`` is a compact claim's context, resolved before this connection.

    It is rechecked against the locked state only after identity, role and time.
    """
    refuse(actor.subject == command.actor_subject, "forbidden")
    authorize(actor, command.action)
    refuse(now < utc_datetime(command.expires_at), "command_expired")
    refuse(utc_datetime(command.requested_at) <= now + timedelta(minutes=5), "invalid_time")
    draft = _target_drafts(state, command)[0]
    claim = ghcn.current(authority, c, state, version) if ghcn is not None else None
    value = inputs(authority, c, draft, policy, now, claim=claim)
    refuse(command.payload["expected_policy_sha256"] == value["policy_sha256"], "editorial_policy_changed")
    if "expected_renderer_profile_sha256" in command.payload:
        refuse(command.payload["expected_renderer_profile_sha256"] == value["profile_sha256"], "native_renderer_changed")
    return draft, value


def package_current(authority, c, draft, proposal, value, policy):
    package = media.read(c, proposal, authority.environment)
    return _package_current(authority, c, draft, proposal, value, package)


def _package_current(authority, c, draft, proposal, value, package):
    """Check current bindings against a package freshly verified on this read."""
    capture = package["capture"]
    refuse(capture["proposal"]["proposal_sha256"] == proposal, "media_preparation_not_retained")
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
    return _reviewed(authority, c, draft, value, policy, resolve_principal)[0]


def _reviewed(authority, c, draft, value, policy, resolve_principal):
    """Verify the exact pair once; retain its record for this same operation."""
    binding = draft.get("media_review_binding")
    refuse(type(binding) is dict and "media_attachment" in draft, "joint_media_review_required")
    intent = authority._intent(c, binding["command_id"])
    # One full retained-media verification: the explicit read below, not also inside _result.
    result = authority._result(c, binding["command_id"], media=False)
    refuse(intent is not None and result is not None, "joint_media_review_not_retained")
    retained, package = media_commands.read_with_package(c, intent[0], result, authority.environment)
    _package_current(authority, c, draft, binding["proposal_sha256"], value, package)
    record = retained["review"]
    refuse(retained["review"]["review_sha256"] == binding["review_sha256"]
           and record["packet"]["packet_sha256"] == binding["packet_sha256"], "joint_media_review_changed")
    reviewer = resolve(resolve_principal, record["reviewer"]["subject"])
    stored = package["capture"]["inputs"]
    platform_inputs = {}
    status = None
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
        if draft["decision_revision"] == reviewed_revision:
            status = media_commands._current_review_status(record, draft, package, policy,
                description_profiles(authority), expected_review_sha256=binding["review_sha256"],
                current_principal=reviewer)
        else:
            platform_inputs["platform_description"] = media_commands.description_for(
                checked_draft, package, policy, description_profiles(authority))
    if status is None:
        status = joint_media_review_status(record, draft, expected_review_sha256=binding["review_sha256"],
            current_principal=reviewer, expected_draft_identity=draft_identity(draft), editorial_policy=policy,
            graphic_spec=stored["graphic_spec"], renderer_manifest=stored["renderer_manifest"], png_bytes=package["assets"]["preview.png"], **platform_inputs)
    refuse(status["current"] is True and status["accepted"] is True, "joint_media_review_obsolete")
    return package, record


def boundary(authority, c, state, version, command, actor, policy, now, resolve_principal, prepared=None, ghcn=None):
    """Called in the command savepoint. All writes roll back with any refusal."""
    draft, value = command_inputs(authority, c, state, command, actor, policy, now, ghcn=ghcn, version=version)
    # command_inputs just verified this same context against the locked state.
    claim = ghcn.claim if ghcn is not None else None
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
    completion = completed(c, identity, packet, now, authority.environment, resolved=claim)
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


def completed(c, identity, packet, now, environment, *, resolved=None):
    from src.commands import postgres_stage_revision_checks as stages
    if stages.protocol(c, identity) == 2:
        cap = stages.lease(c, identity)
        refuse(cap is not None, "revision_check_lease_required")
        try:
            checks._current(c, packet, dict(owner=cap["owner"], fence=cap["fence"], current_context=packet["current_context"],
                checker_state_sha256=packet["checker_state_sha256"]), utc_text(now), environment)
            return stages.completion(c, identity, packet, now, environment, resolved=resolved)
        except checks.checks.CheckJournalError as exc:
            if str(exc) not in {"changed_revision_check_state", "revision_check_expired", "stale_revision_check_owner"}:
                raise
            raise CommandError(str(exc), "The retained check authority is stale; refresh the current revision") from None
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
    proofs, _ = checks.verified_stage_receipts(c, identity, packet, owner=owner, fence=fence, environment=environment,
                                               resolved=resolved)
    body = dict(schema_version=1, origin_kind=packet["origin_kind"], enrollment_id=packet["enrollment_id"],
                check_set_id=identity, packet_sha256=p._sha(p._canonical(packet)), stages=proofs)
    return {**body, "completion_sha256": fingerprint(body)}


def runner_context(authority, c, command_id, resolve_principal, state, version, policy, now, *, claim=None):
    intent = authority._intent(c, command_id)
    result = authority._result(c, command_id)
    refuse(intent is not None and intent[0].action == "request_revision_checks"
           and result is not None and result["status"] == "unchanged", "revision_check_request_required")
    command = intent[0]
    actor = resolve(resolve_principal, command.actor_subject)
    # The accepted request's short lifetime bounds intake, not a retained grant.
    draft = _target_drafts(state, command)[0]
    value = inputs(authority, c, draft, policy, now, claim=claim)
    reviewed(authority, c, draft, value, policy, resolve_principal)
    identity = result["revision_checks"]["check_set_id"]
    packet, _ = checks._packet(c, identity, authority.environment)
    refuse(packet["state_version"] == version and packet["state_sha256"] == p._sha(p._canonical(state))
           and packet["renderer_profile_sha256"] == value["profile_sha256"] and packet["source_origin"] == value["source_origin"]
           and packet["current_context"]["policy_sha256"] == fingerprint(policy)
           and utc_text(now) < packet["useful_until"] and utc_text(now)[:10] == packet["check_date"], "revision_checks_obsolete")
    return command, identity, packet, actor


def parked(authority, c, draft, state, version, value, policy, now, resolve_principal, *, claim=None):
    return _parked(authority, c, draft, state, version, value, policy, now, resolve_principal, claim=claim)


def _parked(authority, c, draft, state, version, value, policy, now, resolve_principal, *, claim=None, _inspection=None):
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
    if _inspection is None:
        reviewed(authority, c, draft, value, policy, resolve_principal)
    else:
        _inspection.parked_review(authority, c, draft, value, policy)
    packet, _ = checks._packet(c, binding["completion"]["check_set_id"], authority.environment)
    refuse(packet["state_version"] == binding["consumed_state_version"]
           and packet["state_sha256"] == binding["consumed_state_sha256"]
           and packet["current_context"]["policy_sha256"] == value["policy_sha256"] == binding["policy_sha256"]
           and packet["renderer_profile_sha256"] == value["profile_sha256"] == binding["renderer_profile_sha256"]
           and packet["source_origin"] == value["source_origin"] and utc_text(now) < packet["useful_until"] == binding["useful_until"],
           "parked_media_obsolete")
    # The consumed predecessor remains the check origin; subsequent authority
    # writes invalidate this parked decision, even when their prose is unchanged.
    from src.commands import postgres_stage_revision_checks as stages
    if stages.protocol(c, binding["completion"]["check_set_id"]) == 2:
        refuse(utc_text(now) < stages.final_deadline(c, binding["completion"]["check_set_id"], packet), "parked_media_lease_expired")
        proof = stages.completion(c, binding["completion"]["check_set_id"], packet, now, authority.environment, resolved=claim)
        refuse(p._canonical(proof) == p._canonical(binding["completion"]), "parked_media_proof_changed")
        if _inspection is not None:
            _inspection.verified(packet, stages.final_deadline(c, binding["completion"]["check_set_id"], packet))
        return True
    lease = c.execute("SELECT fence,owner,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1",
                      (binding["completion"]["check_set_id"],)).fetchone()
    refuse(lease is not None and lease[1] == "revision-checks:" + packet["enrollment_id"]
           and utc_text(now) < lease[2], "parked_media_lease_expired")
    proofs, _ = checks.verified_stage_receipts(c, binding["completion"]["check_set_id"], packet,
        owner=lease[1], fence=lease[0], environment=authority.environment, resolved=claim)
    proof = dict(schema_version=1, origin_kind=packet["origin_kind"], enrollment_id=packet["enrollment_id"],
                 check_set_id=binding["completion"]["check_set_id"], packet_sha256=p._sha(p._canonical(packet)), stages=proofs)
    refuse(p._canonical({**proof, "completion_sha256":fingerprint(proof)}) == p._canonical(binding["completion"]), "parked_media_proof_changed")
    if _inspection is not None:
        _inspection.verified(packet, lease[2], day_bound=False)
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


def projection(authority, c, draft_id, *, state, version, policy, now, resolve_principal, png_proposal=None, original=False,
               claim=None):
    return _projection(authority, c, draft_id, state=state, version=version, policy=policy, now=now,
        resolve_principal=resolve_principal, png_proposal=png_proposal, original=original, claim=claim)


def _projection(authority, c, draft_id, *, state, version, policy, now, resolve_principal, png_proposal=None, original=False,
                claim=None, _inspection=None):
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
        if _inspection is not None and not _inspection.start_inputs():
            _inspection = None
        value = inputs(authority, c, draft, policy, now, claim=claim)
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
                        expected_profiles=description_profiles(authority), graphic_spec=package["capture"]["inputs"]["graphic_spec"])
                except descriptions.DescriptionError as exc:
                    fit = exc.code
                view["platform_description"] = dict(record=description,
                    wire_text=description.get("wire_text", package["assets"]["alt.txt"].decode("utf-8")), status=fit,
                    qualification="offline_fixture_only" if description["profiles"]["profile"] == descriptions.FIXTURE_PROFILE else "unqualified")
                break
            except (CommandError, ValueError):
                continue
        if "media_attachment" in draft:
            try:
                reviewed_package, reviewed_record = (_reviewed(authority, c, draft, value, policy, resolve_principal)
                    if _inspection is None else _inspection.review(authority, c, draft, value, policy, resolve_principal))
                view["review_current"] = True
                view["expected_review_sha256"] = draft["media_review_binding"]["review_sha256"]
                if draft["media_review_binding"].get("schema_version") == 2:
                    retained_description = reviewed_record["platform_description"]
                    view["platform_description"].update(record=retained_description,
                        wire_text=retained_description.get("wire_text", reviewed_package["assets"]["alt.txt"].decode("utf-8")))
                try:
                    view["parked"] = (parked(authority, c, draft, state, version, value, policy, now, resolve_principal, claim=claim)
                        if _inspection is None else _parked(authority, c, draft, state, version, value, policy, now,
                            resolve_principal, claim=claim, _inspection=_inspection))
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
                    proof = completed(c, identity, packet, now, authority.environment, resolved=claim)
                    view.update(checks_status="passed", expected_check_completion_sha256=proof["completion_sha256"])
                elif any(s not in {"pending", "passed"} for s in stages.values()):
                    view["checks_status"] = "needs_attention"
            except CommandError as exc:
                view["checks_status"] = exc.code
    except CommandError as exc:
        view.update(status="unavailable", code=exc.code)
    refuse(len(p._canonical(view)) <= 128*1024, "media_view_bound")
    return view
