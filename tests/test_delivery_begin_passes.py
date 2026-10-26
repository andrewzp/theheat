"""begin()'s two context passes over invented primitives; no PostgreSQL proof.

The retained approval/review/check verifiers are explicit counting fixtures that
keep their real call structure: approval roles, the review pair, its package
binding and the reviewer. They prove the private reuse fences and the refusal
order of the second (acquire) pass, never qualification, a grant or a send.
"""
from copy import copy, deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.commands import postgres_delivery as delivery, postgres_editor_media as editor
from src.commands import postgres_stage_revision_checks as stages
from src.commands.schema import CommandError, Principal, utc_text
from src.editorial.revisions import fingerprint
from src.posting import delivery_receipts
from src.storage import postgres_projection as p
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
def test_acquire_pass_rereads_live_inputs_but_not_its_own_first_pass_retained_proof(case, ghcn):
    if not ghcn:
        case.ghcn = None
    with pytest.raises(Stop):
        begin(case)
    # The first pass verified the retained approval, review and check proof on
    # this connection. The acquire pass rereads every live input, both approval
    # roles, the package binding and each reviewer, but replays that proof once.
    assert counts(case, RETAINED) == dict(parked=1, completion=1, review=2, description_replay=1)
    assert counts(case, LIVE) == dict(configuration=4, policy=2, claim=2 if ghcn else 0, inputs=2, description=2)
    assert case.control["calls"].count("package_current") == 3
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


def recorded(monkeypatch):
    scopes = []

    class Recorded(delivery._OwnDispatchPass):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            scopes.append(self)

    monkeypatch.setattr(delivery, "_OwnDispatchPass", Recorded)
    return scopes


def own(case, *, c=None):
    return delivery._OwnDispatchPass(delivery._DISPATCH_TOKEN, case.authority, case.sql if c is None else c,
                                     case.value, case.resolve, NOW, case.ghcn)


def test_dispatch_pass_is_private_single_and_never_copied(case):
    for token in (None, True, object(), {}):
        with pytest.raises(CommandError):
            delivery._OwnDispatchPass(token, case.authority, case.sql, case.value, case.resolve, NOW, case.ghcn)
    scope = own(case)
    for copier in (copy, deepcopy):
        with pytest.raises(CommandError):
            copier(scope)
    supplied = {"_dispatch": scope}
    with pytest.raises(TypeError):
        delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, **supplied)
    with pytest.raises(TypeError):
        delivery.acquire(case.authority, case.sql, case.value, "x", "upload", "worker", case.resolve, NOW,
                         **supplied)


@pytest.mark.parametrize("outcome", ["stopped", "refused", "prior_send"])
def test_begin_closes_its_pass_on_every_exit(case, monkeypatch, outcome):
    scopes = recorded(monkeypatch)
    if outcome == "refused":
        at_acquire_pass(case, lambda: case.control["revoked"].add("publisher"))
    elif outcome == "prior_send":
        case.control["existing"] = dict(attempt_id="invented-prior")
    if outcome == "prior_send":
        assert begin(case) == dict(dispatch_granted=False)
    else:
        with pytest.raises(Stop if outcome == "stopped" else CommandError):
            begin(case)
    assert len(scopes) == 1 and scopes[0]._stage == "closed" and scopes[0]._pair is None
    case.control.update(hook=None)
    case.control["revoked"].clear()
    # A closed pass cannot resolve a claim, so no later transaction can borrow it.
    with pytest.raises(CommandError) as held:
        delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=scopes[0])
    assert held.value.code == "delivery_dispatch_context_changed"


def test_each_begin_transaction_verifies_its_own_retained_proof_again(case):
    # No proof outlives its begin(): a later transaction (including one after an
    # uncertain COMMIT acknowledgement) replays the complete first pass itself.
    for _ in range(2):
        with pytest.raises(Stop):
            begin(case)
    assert counts(case, RETAINED) == dict(parked=2, completion=2, review=4, description_replay=2)


def test_foreign_connection_authority_or_byte_equal_pass_never_borrows_a_proof(case):
    first = own(case)
    delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=first)
    assert counts(case, RETAINED) == dict(parked=1, completion=1, review=2, description_replay=1)
    for c, authority in ((Sql(case.control), case.authority), (case.sql, SimpleNamespace(**vars(case.authority)))):
        with pytest.raises(CommandError) as held:
            delivery.context(authority, c, case.value, case.resolve, NOW, ghcn=first)
        assert held.value.code == "delivery_dispatch_context_changed"
    # A separately minted pass with identical bytes performs its own full proof.
    delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=own(case))
    assert counts(case, RETAINED) == dict(parked=2, completion=2, review=4, description_replay=2)
    # The first pass's own successor still reuses exactly once, then never again.
    for _ in range(2):
        delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=first)
    assert counts(case, RETAINED) == dict(parked=3, completion=3, review=6, description_replay=3)


@pytest.mark.parametrize("change", ["now", "resolver"])
def test_changed_clock_or_role_resolver_is_not_the_same_operation(case, change):
    scope = own(case)
    delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=scope)
    now = NOW + timedelta(microseconds=1) if change == "now" else NOW
    resolve = case.resolve if change == "now" else (lambda subject: case.resolve(subject))
    delivery.context(case.authority, case.sql, case.value, resolve, now, ghcn=scope)
    assert counts(case, RETAINED) == FULL_TWICE


def test_reentrant_callbacks_cannot_record_or_reuse_twice(case, monkeypatch):
    scopes = recorded(monkeypatch)
    inner = []

    def reenter():
        inner.append(len(case.control["calls"]))
        delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=scopes[0])

    # During the first pass's parked role: the nested pass neither records nor reuses.
    case.control.update(hook=reenter, hook_at=3)
    with pytest.raises(Stop):
        begin(case)
    assert inner and counts(case, RETAINED) == dict(parked=2, completion=2, review=4, description_replay=2)
    # During the acquire pass: one reuse at most, then the outer pass replays fully.
    case.control["calls"].clear()
    case.control["roles"].clear()
    case.control.update(hook=reenter, hook_at=len(PASS_ROLES) + 1)
    scopes.clear()
    with pytest.raises(Stop):
        begin(case)
    assert counts(case, RETAINED) == dict(parked=2, completion=2, review=4, description_replay=2)


def test_returned_pair_is_a_copy_of_the_first_pass_record(case):
    scope = own(case)
    first, _ = delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=scope)
    first["assets"]["preview.png"] += b"invented caller mutation"
    second, _ = delivery.context(case.authority, case.sql, case.value, case.resolve, NOW, ghcn=scope)
    assert second == case.control["package"]
    assert counts(case, RETAINED) == dict(parked=1, completion=1, review=2, description_replay=1)
