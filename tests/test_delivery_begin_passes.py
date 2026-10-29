"""begin()'s two context passes over invented primitives; no PostgreSQL proof.

The first fixture's retained verifiers are explicit counting models that keep
their real call structure (approval roles, review pair, package binding,
reviewer). The second runs the actual schema3 review, profile/status and
description readers over invented retained rows; only its approval/check
completion is modeled. Neither proves protocol2 qualification, a grant or a send.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import io
import json
from types import SimpleNamespace
from typing import Any

from PIL import Image
import pytest

from src.commands import postgres_delivery as delivery, postgres_editor_media as editor
from src.commands import postgres_stage_revision_checks as stages
from src.commands import postgres_media as media, postgres_media_commands as commands
from src.commands.media_journal import MediaJournalError
from src.commands.schema import CommandError, Principal, canonical_json, utc_text
from src.editorial.revisions import fingerprint
from src.media import platform_description as descriptions
from src.posting import delivery_receipts
from src.posting.local_delivery import FixtureConfiguration
from src.storage import postgres_projection as p
from tests import test_media_journal as journal, test_media_replay_reuse as reuse
from tests import test_media_review_packet as packets, test_media_review_pair as pair
from tests.test_joint_media_review import ACTOR
from tests.test_media_replay_reuse import Rows

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
ROLES = dict(publisher="publisher", editor="editor", reviewer="editor")
# One pass: both approval roles, both parked approval roles, each review read's reviewer.
PASS_ROLES = ["publisher", "editor", "publisher", "editor", "reviewer", "reviewer"]
RETAINED = ("parked", "completion", "review", "description_replay")
LIVE = ("configuration", "policy", "claim", "inputs", "description")
FULL_TWICE = dict(parked=2, completion=2, review=4, description_replay=2)


class Stop(Exception):
    """Request verification follows both passes; this harness never grants."""


class Sql:
    """Only acquire's lease rows and the legacy check-lease deadline."""

    def __init__(self, control):
        self.control = control
        self.leases = []

    def execute(self, query, args=()):
        sql = " ".join(query.split())
        if sql.startswith("SELECT expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s"):
            return Rows([(self.control["check_expires"],)])
        if sql.startswith("SELECT fence,owner,recorded_at,expires_at FROM theheat_delivery.leases"):
            return Rows(deepcopy(self.control["lease_rows"]))
        if sql.startswith("INSERT INTO theheat_delivery.leases VALUES"):
            self.leases.append(args)
            return Rows([])
        raise AssertionError(f"Unexpected SQL boundary: {sql}")


class Claim:
    """An invented claim context; each current() is one live source reread."""

    def __init__(self, control):
        self.control = control

    def current(self, authority, c, state, version):
        self.control["calls"].append("claim")
        if self.control["claim_fault"] and self.control["calls"].count("claim") > 1:
            raise CommandError(self.control["claim_fault"], "Invented later source change")
        return self.control["claim"]


def invented_claim():
    return SimpleNamespace(reference=dict(source_run_id="run", selection=dict(station_id="USW00000000")),
                           full_sha256="e" * 64, view_sha256="f" * 64)


@pytest.fixture
def case(monkeypatch):
    png, alt = b"invented png bytes", b"Invented alt text.\n"
    binding = dict(publisher_subject="publisher", requesting_actor="editor", command_id="approval",
                   useful_until="2026-10-25T13:00:00Z", completion=dict(check_set_id="checks"))
    description = dict(description_sha256="d" * 64, wire_text="Invented alt text.\n")
    value = dict(schema_version=2, intent_id="intent", draft_id="draft", event_id="event",
                 text="Invented approved statement.", fixture=dict(instance_id="fixture"),
                 configuration_sha256="b" * 64, approval_binding=binding, platform_description=description,
                 package=dict(receipt="invented"), png_sha256=p._sha(png), alt_sha256=p._sha(alt))
    draft = dict(id="draft", event_id="event", text=value["text"], approval_binding=deepcopy(binding),
                 media_review_binding=dict(schema_version=2, command_id="review", proposal_sha256="a" * 64,
                                           platform_description_sha256=description["description_sha256"]))
    policy = dict(version=1)
    control = dict(
        calls=[], roles=[], revoked=set(), hook=None, hook_at=len(PASS_ROLES) + 1,
        state=dict(drafts=[draft]), version=3, approved_version=3, digest="b" * 64,
        fixture=dict(instance_id="fixture"), policy=policy, approved_policy=fingerprint(policy),
        inputs=dict(profile_sha256="c" * 64, spec=dict(template="invented"), source_label="Invented"),
        retained_profile="c" * 64, allowlisted=True, claim=invented_claim(), claim_fault=None,
        check_expires="2026-10-25T13:00:00Z", lease_rows=[], existing=None,
        package=dict(receipt=dict(receipt="invented"), assets={"preview.png": png, "alt.txt": alt},
                     capture=dict(inputs=dict(graphic_spec=dict(template="invented")))),
        record=dict(reviewer=dict(subject="reviewer"), platform_description=deepcopy(description)))
    calls = control["calls"]

    def resolve(subject):
        control["roles"].append(subject)
        if control["hook"] is not None and len(control["roles"]) == control["hook_at"]:
            control["hook"]()
        return None if subject in control["revoked"] else Principal(subject, ROLES[subject], "invented")

    def configuration(authority):
        calls.append("configuration")
        return deepcopy(control["fixture"]), control["digest"]

    def current_policy():
        calls.append("policy")
        return deepcopy(control["policy"])

    def inputs(authority, c, draft, policy, now, *, claim=None):
        calls.append("inputs")
        delivery.refuse(control["allowlisted"], "media_source_not_allowlisted")
        return dict(deepcopy(control["inputs"]), policy_sha256=fingerprint(policy))

    def parked(authority, c, draft, state, version, value, policy, now, resolve_principal, *, claim=None):
        calls.append("parked")
        delivery.refuse(version == control["approved_version"]
                        and value["policy_sha256"] == control["approved_policy"], "parked_media_obsolete")
        editor.resolve(resolve_principal, "publisher", publisher=True)
        editor.resolve(resolve_principal, draft["approval_binding"]["requesting_actor"])
        editor.reviewed(authority, c, draft, value, policy, resolve_principal)
        calls.append("completion")
        return True

    def reviewed(authority, c, draft, value, policy, resolve_principal):
        calls.append("review")
        editor._package_current(authority, c, draft, draft["media_review_binding"]["proposal_sha256"],
                                value, control["package"])
        editor.resolve(resolve_principal, control["record"]["reviewer"]["subject"])
        return deepcopy(control["package"]), deepcopy(control["record"])

    def package_current(authority, c, draft, proposal, value, package):
        calls.append("package_current")
        delivery.refuse(value["profile_sha256"] == control["retained_profile"], "native_renderer_changed")
        return package

    def media_commands_review(authority, c, command):
        calls.append("description_replay")
        return dict(review=deepcopy(control["record"]))

    def described(authority, draft, package, record):
        calls.append("description")
        delivery.configuration(authority)  # Live profiles, as the real preflight reads them.
        return record

    def attempt(c, value, platform, stage):
        return deepcopy(control["existing"]) if stage == "upload" else None

    def verify(*args, **kwargs):
        raise Stop

    authority = SimpleNamespace(environment="local")
    authority._state = lambda c, lock=False: (control["version"], deepcopy(control["state"]))
    authority._intent = lambda c, command_id: (SimpleNamespace(actor_subject="publisher"), None)
    for owner, name, replacement in (
        (delivery, "configuration", configuration), (delivery, "current_editorial_policy", current_policy),
        (delivery, "media_commands_review", media_commands_review), (delivery, "_description_preflight", described),
        (delivery, "attempt", attempt), (delivery, "outcome", lambda c, saved: dict(status="unknown", result=None)),
        (editor, "inputs", inputs), (editor, "parked", parked),
        (editor, "_reviewed", reviewed), (editor, "_package_current", package_current),
        (stages, "protocol", lambda c, identity: 1), (delivery_receipts, "verify_request", verify),
        (delivery.descriptions, "validate", lambda *args, **kwargs: "Invented alt text.\n"),
    ):
        monkeypatch.setattr(owner, name, replacement)
    control["sql"] = Sql(control)
    return SimpleNamespace(authority=authority, value=value, resolve=resolve, control=control,
                           sql=control["sql"], ghcn=Claim(control))


def begin(case, *, stage="upload"):
    lease = dict(owner="worker", fence=1, expires_at=utc_text(NOW + timedelta(seconds=delivery.LEASE_SECONDS)))
    return delivery.begin(case.authority, case.sql, case.value, "x", stage, lease, {}, b"",
                          case.resolve, NOW, ghcn=case.ghcn)


def counts(case, names):
    return {name: case.control["calls"].count(name) for name in names}


def at_acquire_pass(case, change):
    """Run ``change`` inside the acquire pass's first role callback."""
    case.control["hook"] = change


@pytest.mark.parametrize("ghcn", [True, False], ids=["ghcn_claim", "no_claim"])
def test_acquire_pass_replays_its_complete_retained_proof_after_its_role_callbacks(case, ghcn):
    if not ghcn:
        case.ghcn = None
    with pytest.raises(Stop):
        begin(case)
    # Role callbacks can change live and retained inputs, so the acquire pass
    # repeats the full approval/review/check proof at its original positions.
    assert counts(case, RETAINED) == FULL_TWICE
    assert counts(case, LIVE) == dict(configuration=4, policy=2, claim=2 if ghcn else 0, inputs=2, description=2)
    assert case.control["calls"].count("package_current") == 4
    assert case.control["roles"] == PASS_ROLES * 2
    assert len(case.sql.leases) == 1


@pytest.mark.parametrize("fault,code,roles", [
    ("publisher", "forbidden", 7),
    ("requester", "forbidden", 8),
    ("reviewer", "forbidden", 11),
    ("second_reviewer", "forbidden", 12),
    ("configuration", "delivery_configuration_changed", 8),
    ("draft", "delivery_approval_changed", 8),
    ("version", "parked_media_obsolete", 8),
    ("policy", "parked_media_obsolete", 8),
    ("renderer", "native_renderer_changed", 10),
    ("allowlist", "media_source_not_allowlisted", 8),
    ("source", "ghcn_execution_context_changed", 8),
    ("baseline", "ghcn_baseline_changed", 8),
    ("expired", "ghcn_preparation_expired", 8),
])
def test_late_change_before_acquire_pass_keeps_original_refusal_and_position(case, fault, code, roles):
    control = case.control

    def change():
        if fault in {"publisher", "reviewer", "second_reviewer"}:
            control["revoked"].add(fault.removeprefix("second_"))
        elif fault == "requester":
            control["revoked"].add("editor")
        elif fault == "configuration":
            control["digest"] = "0" * 64
        elif fault == "draft":
            control["state"]["drafts"][0]["text"] += " Invented later revision."
        elif fault == "version":
            control["version"] += 1
        elif fault == "policy":
            control["policy"] = dict(version=2)
        elif fault == "renderer":
            control["inputs"]["profile_sha256"] = "9" * 64
        elif fault == "allowlist":
            control["allowlisted"] = False
        else:
            control["claim_fault"] = dict(source="ghcn_execution_context_changed", baseline="ghcn_baseline_changed",
                                          expired="ghcn_preparation_expired")[fault]

    at_acquire_pass(case, change)
    if fault == "second_reviewer":
        control["hook_at"] = roles  # Only the second skipped review read's reviewer callback.
    with pytest.raises(CommandError) as held:
        begin(case)
    assert held.value.code == code
    assert len(control["roles"]) == roles
    assert case.sql.leases == []


@pytest.mark.parametrize("change", ["state", "draft", "inputs", "claim_object", "claim_reference", "value"])
def test_any_other_changed_input_replays_the_complete_original_proof(case, change):
    control = case.control

    def changed():
        if change == "state":
            control["state"]["invented_unrelated"] = True
        elif change == "draft":
            control["state"]["drafts"][0]["invented_unchecked"] = 1
        elif change == "inputs":
            control["inputs"]["source_label"] = "Invented later label"
        elif change == "claim_object":
            control["claim"] = invented_claim()  # Equal bytes, different resolved object.
        elif change == "claim_reference":
            control["claim"].reference["selection"]["station_id"] = "USW00000001"
        else:
            case.value["invented_unchecked"] = 1

    at_acquire_pass(case, changed)
    with pytest.raises(Stop):
        begin(case)
    assert counts(case, RETAINED) == FULL_TWICE
    assert case.control["roles"] == PASS_ROLES * 2


def test_unknown_prior_send_and_lease_fences_keep_their_original_results(case):
    case.control["existing"] = dict(attempt_id="invented-prior")
    assert begin(case) == dict(dispatch_granted=False)
    assert case.sql.leases == []
    for rows, code in (([(1, "other-worker", "2026-10-25T11:59:50Z", "2026-10-25T12:00:20Z")], "delivery_lease_busy"),
                       ([(1, "worker", "2026-10-25T12:00:05Z", "2026-10-25T12:00:35Z")], "delivery_clock_regressed")):
        case.control.update(existing=None, lease_rows=rows)
        with pytest.raises(CommandError) as held:
            begin(case)
        assert held.value.code == code
    case.control["lease_rows"] = []
    with pytest.raises(CommandError) as held:
        delivery.begin(case.authority, case.sql, case.value, "x", "upload",
                       dict(owner="worker", fence=2, expires_at="2026-10-25T12:00:30Z"), {}, b"",
                       case.resolve, NOW, ghcn=case.ghcn)
    assert held.value.code == "delivery_stale_fence"


# Actual schema3 review, profile/status and description readers over invented
# retained rows. The approval/check completion step is the only modeled part.
REPLAY_NOW = reuse.NOW


@pytest.fixture
def reviewed(monkeypatch, tmp_path):
    folder = tmp_path / "invented-private-delivery"
    folder.mkdir(mode=0o700)

    def fixture(name, port):
        path = folder / name
        path.write_text(json.dumps(dict(schema_version=2, scope="local_http_fixture_v1", invented=True,
            instance_id="11111111-2222-4333-8444-555555555555", origin=f"http://127.0.0.1:{port}",
            routes_version=1, actor="did:plc:aaaaaaaaaaaaaaaaaaaaaaaa", platform_profile="credentialless-loopback-v1")))
        path.chmod(0o600)
        return FixtureConfiguration.load(path)

    first, second = fixture("a.json", 39131), fixture("b.json", 39132)
    inputs = pair.family_inputs("temperature")
    image = io.BytesIO()
    Image.new("RGB", (packets.WIDTH, packets.HEIGHT), (246, 241, 232)).save(image, format="PNG")  # Invented, decodable.
    inputs = dict(inputs, png_bytes=image.getvalue(), renderer_manifest=packets.manifest_for(inputs["graphic_spec"], image.getvalue()))
    retained = getattr(reuse.replay, "__wrapped__")(getattr(journal.package, "__wrapped__")(inputs))
    retained["profiles"] = descriptions.profiles(first.read())
    staged = media.read(retained["sql"], retained["command"].payload["proposal_sha256"], "local")
    proposed = commands.description_for(retained["capture"]["proposal"]["proposed_draft"], staged,
                                        retained["inputs"]["editorial_policy"], retained["profiles"])
    payload = deepcopy(retained["command"].payload)
    payload["review"]["confirmations"][descriptions.CONFIRMATION] = True
    payload["review"]["expected_platform_description_sha256"] = proposed["description_sha256"]
    retained["command"] = replace(retained["command"], payload_json=canonical_json(payload))
    pair.retain(retained, pair.prepare(retained))
    reuse.preparation(retained)
    draft = pair.parked_draft(retained)
    later = utc_text(REPLAY_NOW + timedelta(hours=1))
    draft["approval_binding"].update(publisher_subject=ACTOR.subject, requesting_actor=ACTOR.subject,
                                     useful_until=later, completion=dict(check_set_id="invented-checks"))
    state = deepcopy(retained["after"])
    state["drafts"] = [draft]
    authority, sql = retained["authority"], retained["sql"]
    authority.delivery_configuration = first
    package, record = editor._reviewed(authority, sql, draft, reuse.current_inputs(retained),
                                       retained["inputs"]["editorial_policy"], lambda subject: Principal(subject, "publisher", "invented"))
    value = dict(schema_version=2, intent_id=draft["approval_binding"]["publish_intent_id"],
                 command_id=draft["approval_binding"]["command_id"], draft_id=draft["id"], event_id=draft["event_id"],
                 text=draft["text"], fixture=first.read(), configuration_sha256=first.sha256,
                 approval_binding=deepcopy(draft["approval_binding"]), platform_description=record["platform_description"],
                 package=package["receipt"], png_sha256=p._sha(package["assets"]["preview.png"]),
                 alt_sha256=p._sha(package["assets"]["alt.txt"]))
    control: dict[str, Any] = dict(calls=[], roles=[], hooks={}, seal=True, leases=[])
    original = sql.execute

    def execute(query, args=()):
        text = " ".join(query.split())
        if text.startswith("SELECT expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s"):
            return Rows([(later,)])
        if text.startswith("SELECT fence,owner,recorded_at,expires_at FROM theheat_delivery.leases"):
            return Rows([])
        if text.startswith("INSERT INTO theheat_delivery.leases VALUES"):
            control["leases"].append(args)
            return Rows([])
        return original(query, args)

    def resolve(subject):
        control["roles"].append(subject)
        hook = control["hooks"].get(len(control["roles"]))
        if hook is not None:
            hook()
        return Principal(subject, "publisher", "invented-session")

    def parked(authority, c, draft, state, version, value, policy, now, resolve_principal, *, claim=None):
        control["calls"].append("parked")
        delivery.refuse(version == 2, "parked_media_obsolete")
        editor.resolve(resolve_principal, draft["approval_binding"]["publisher_subject"], publisher=True)
        editor.resolve(resolve_principal, draft["approval_binding"]["requesting_actor"])
        editor.reviewed(authority, c, draft, value, policy, resolve_principal)  # Actual schema3 review read.
        control["calls"].append("completion")
        delivery.refuse(control["seal"], "stage_seal_required")  # Modeled protocol2 deterministic seal.
        return True

    def inputs_current(authority, c, draft, policy, now, *, claim=None):
        control["calls"].append("inputs")
        return reuse.current_inputs(retained)

    def verify(*args, **kwargs):
        raise Stop

    for owner, name, replacement in (
        (sql, "execute", execute), (authority, "_state", lambda c, lock=False: (2, deepcopy(state))),
        (editor, "inputs", inputs_current), (editor, "parked", parked), (stages, "protocol", lambda c, identity: 1),
        (delivery, "attempt", lambda c, value, platform, stage: None), (delivery_receipts, "verify_request", verify),
    ):
        monkeypatch.setattr(owner, name, replacement)
    sql.package_reads = 0
    return SimpleNamespace(authority=authority, sql=sql, value=value, resolve=resolve, control=control,
                           first=first, second=second, draft=draft, package=package)


def begin_reviewed(r):
    lease = dict(owner="worker", fence=1, expires_at=utc_text(REPLAY_NOW + timedelta(seconds=delivery.LEASE_SECONDS)))
    return delivery.begin(r.authority, r.sql, r.value, "x", "upload", lease, {}, b"", r.resolve, REPLAY_NOW)


def test_actual_review_profiles_run_in_both_passes_and_description_reads_its_review_once(reviewed):
    with pytest.raises(Stop):
        begin_reviewed(reviewed)
    assert reviewed.control["roles"] == [ACTOR.subject] * 12 and len(reviewed.control["leases"]) == 1
    assert reviewed.control["calls"].count("parked") == 2 and reviewed.control["calls"].count("completion") == 2
    # Per pass: parked's review, the reviewed read and one description read.
    assert reviewed.sql.package_reads == 6


@pytest.mark.parametrize("restore", [True, False], ids=["A_B_A", "A_B"])
def test_configuration_changed_by_first_acquire_reviewer_refuses_before_the_second(reviewed, restore):
    r = reviewed
    r.control["hooks"][11] = lambda: setattr(r.authority, "delivery_configuration", r.second)
    if restore:
        r.control["hooks"][12] = lambda: setattr(r.authority, "delivery_configuration", r.first)
    with pytest.raises(CommandError) as held:
        begin_reviewed(r)
    assert held.value.code == "joint_media_review_obsolete"
    assert len(r.control["roles"]) == 11 and r.control["leases"] == []


def test_retained_stage_seal_removed_before_acquire_refuses_inside_begin_then_eligibility_returns(reviewed):
    r = reviewed
    r.control["hooks"][7] = lambda: r.control.update(seal=False)
    with pytest.raises(CommandError) as held:
        begin_reviewed(r)
    assert held.value.code == "stage_seal_required"
    assert len(r.control["roles"]) == 11 and r.control["leases"] == []
    r.control.update(seal=True, hooks={}, roles=[])
    with pytest.raises(Stop):
        begin_reviewed(r)
    assert len(r.control["leases"]) == 1


def test_description_review_is_read_once_and_still_refuses_changed_retained_bytes(reviewed):
    r = reviewed
    assert delivery.description_preflight(r.authority, r.sql, r.draft, r.package) == r.value["platform_description"]
    assert r.sql.package_reads == 1
    digest = p._sha(r.package["assets"]["preview.png"])
    r.sql.artifacts[digest] += b"invented retained corruption"
    r.sql.package_reads = 0
    with pytest.raises(MediaJournalError, match="changed_media_staging_bytes"):
        delivery.description_preflight(r.authority, r.sql, r.draft, r.package)
    assert r.sql.package_reads == 1
