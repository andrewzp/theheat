"""Pending-only NHC import operator against invented Gist and NHC transports; no actual write."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from scripts import nhc_advisory_import as m, nhc_advisory_trial as trial
from src.data import nhc_advisory as source
from src.editorial.nhc_advisory import validate_capture
from src.editorial.revisions import approval_is_current, review_is_current
from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle
from tests import nhc_advisory_helpers as h
from tests.nhc_advisory_pipeline_helpers import COPY, Transport

TRIAL_ID = "0123456789abcdef0123456789abcdef"
CODE = "a" * 40
SOURCE = "b" * 64
PAIR = [source.INDEX_URL, h.URL]
# Lexical forms, Unicode and spacing must survive the insertion exactly.
STATE = (b' {"drafts": [ {"id":"old","event_id":"other","text":"retained", "number":1.2000e+0,"negative":-0.0} ],'
         b' "publish_ledger":{},"posted_events":[],"opaque":{"x":3.14000},"unicode":"\\u03b1"}\n')
FLAGS = {"THEHEAT_PRODUCTION_PAUSED": "1", "THEHEAT_WRITER_SAMPLES": "1",
         **{k: "0" for k in ("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS",
                             "THEHEAT_CRITIC_REVISE_ENABLED", "THEHEAT_SELFHEAL_REPAIR_ENABLED")}}


def report(captured=h.NOW, code=CODE):
    policy = {"schema_version": 1, "execution_sha256": "c" * 64, "source_sha256": SOURCE,
              "models": {"critic": "critic-model", "fact_check": "fact-model", "safety": "safety-model",
                         "writer": "writer-model", "writer_provider": "anthropic"},
              "flags": {"writer_samples": 1, "critic_enabled": True, "critic_revise_enabled": False,
                        "safety_llm_enabled": True}}
    return json.dumps({"schema_version": 1, "kind": "configuration_only", "collection_paused": True,
                       "runtime_inventory": {"mode": "runtime_report", "git_sha": code,
                                             "captured_at": captured.isoformat(), "editorial_policy": policy,
                                             "flags": {"automatic_publication_enabled": False, "writer_samples": 1,
                                                       "critic_enabled": True, "critic_revise_enabled": False},
                                             "credentials_present": {"safety_gemini": True}}}).encode()


def proposal(**draft_changes):
    evidence = validate_capture(h.capture(), h.selected(), now=h.NOW)
    bundle = build_nhc_advisory_bundle(evidence).to_dict()
    plan = {"trial_id": TRIAL_ID, "nomination": h.nominated(),
            "operator_recheck_deadline": evidence.deadline.strftime("%Y-%m-%dT%H:%M:%SZ")}
    made = trial.proposal(plan, bundle, COPY, h.NOW)
    made["plan_sha256"] = "d" * 64
    made["draft"].update(draft_changes)
    return made


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode()


class Gist:
    """Invented Gist/variables transport: snapshots, at most the PATCHes the operator sends."""

    def __init__(self, *, state=STATE, flags=None, files=None, patch="apply", readback="ok"):
        self.files = {"state.json": state, "runtime-inventory.json": report(),
                      "world_threshold_cache.json": b'{"kept":1.000}', **(files or {})}
        self.flags = dict(FLAGS if flags is None else flags)
        self.mode, self.readback, self.reads, self.patches = patch, readback, 0, []
        self.before_read = None

    def read(self):
        self.reads += 1
        if self.before_read is not None:
            self.before_read(self)
        if self.readback == "fail" and self.patches:
            raise TimeoutError("invented lost readback")
        return dict(self.files), dict(self.flags)

    def patch(self, content):
        self.patches.append(content)
        if self.mode in ("apply", "apply_then_lose"):
            self.files["state.json"] = content
        if self.mode in ("lose", "apply_then_lose"):
            raise TimeoutError("invented lost acknowledgement")
        if self.mode == "conflict":
            self.files["state.json"] = STATE.replace(b'"old"', b'"other-writer"')


@pytest.fixture
def nhc(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(source, "_http_get", transport)
    return transport


def run(gist, raw=None, *, journal, clock=lambda: h.NOW, expected=None):
    raw = encode(proposal()) if raw is None else raw
    return m.execute(raw, m.sha(raw), expected_state_sha256=expected or m.sha(gist.files["state.json"]),
                     read=gist.read, patch=gist.patch, journal=journal, clock=clock, code_sha=CODE, source_sha=SOURCE)


def test_check_is_a_dry_run_with_one_bounded_source_read(nhc):
    gist, raw = Gist(), encode(proposal())
    result = m.check(raw, m.sha(raw), read=gist.read, clock=lambda: h.NOW, code_sha=CODE, source_sha=SOURCE)
    assert result["state_sha256"] == m.sha(STATE) and result["writes"] == 0 and gist.patches == []
    assert result["race_window"] == "unfenced_gist_read_write" and nhc.calls == PAIR


def test_lossless_insertion_preserves_every_original_byte_and_grants_no_authority():
    made = proposal()
    raw = encode(made)
    gist = Gist()
    content, _, draft, _ = m.plan(raw, m.sha(raw), gist.files, FLAGS, h.NOW, CODE, SOURCE)
    old = STATE.decode()
    _, end = m.member(old, "drafts")
    assert content.startswith(old[:end - 1].encode()) and content.endswith(old[end - 1:].encode())
    assert all(token in content for token in (b"1.2000e+0", b"3.14000", b"-0.0", b"\\u03b1"))
    got = m.document(content)[0]
    assert got["drafts"][0] == m.document(STATE)[0]["drafts"][0] and got["drafts"][1] == made["draft"]
    assert draft["status"] == "pending" and draft["approval_policy"]["mode"] == "manual_only"
    assert not review_is_current(draft) and not approval_is_current(draft, "manual")
    for absent in ("review_binding", "approval_binding", "publish_intent_id", "scheduled_for", "human_reviewed"):
        assert absent not in draft
    assert "expir" not in json.dumps(draft["review_context"]["two_bot"]["bundle"]["current_facts"]).lower()


def test_empty_drafts_list_insertion(nhc):
    state = b'{"drafts":[],"publish_ledger":{},"posted_events":[]}'
    raw = encode(proposal())
    content, *_ = m.plan(raw, m.sha(raw), Gist(state=state).files, FLAGS, h.NOW, CODE, SOURCE)
    assert content.startswith(b'{"drafts":[{') and content.endswith(b'}],"publish_ledger":{},"posted_events":[]}')


def test_apply_is_one_patch_one_readback_and_confirmed_pending(nhc, tmp_path):
    gist = Gist()
    result = run(gist, journal=tmp_path)
    assert result["outcome"] == "confirmed_pending" and result["write_acknowledged"] is True
    assert len(gist.patches) == 1 and gist.reads == 3 and nhc.calls == PAIR
    assert (result["reviews"], result["approvals"], result["posts"], result["provider_calls"]) == (0, 0, 0, 0)
    (marker,) = tmp_path.glob("*.attempt.json")
    claim = marker.name.removesuffix(".attempt.json")
    assert json.loads(marker.read_text())["no_automatic_resend"] is True
    assert (tmp_path / claim / "before-1.bin").read_bytes() == STATE  # Sorted: runtime-inventory, state, cache.
    assert (tmp_path / claim / "after" / "inventory.json").exists()
    assert (marker.stat().st_mode & 0o777) == 0o600
    # The applied draft is now a duplicate; a later attempt cannot get past the plan.
    with pytest.raises(m.ImportRefused, match="duplicate_draft"):
        run(Gist(state=gist.files["state.json"]), journal=tmp_path)


def test_the_durable_attempt_marker_blocks_a_second_write_even_if_the_draft_vanished(nhc, tmp_path):
    run(Gist(), journal=tmp_path)
    second = Gist()  # Someone else removed the imported draft; the operator still never re-sends.
    with pytest.raises(m.ImportRefused, match="attempt_already_consumed"):
        run(second, journal=tmp_path)
    assert second.patches == []


def test_lost_acknowledgement_is_reconciled_by_the_one_readback(nhc, tmp_path):
    gist = Gist(patch="apply_then_lose")
    result = run(gist, journal=tmp_path)
    assert result["outcome"] == "confirmed_pending_after_uncertain_response" and len(gist.patches) == 1


@pytest.mark.parametrize("mode", ["lose", "conflict"])
def test_unconfirmed_or_conflicting_readback_holds_without_resend_or_rollback(nhc, tmp_path, mode):
    gist = Gist(patch=mode)
    result = run(gist, journal=tmp_path)
    assert result["outcome"] == "readback_conflict_hold_no_resend" and len(gist.patches) == 1
    assert gist.reads == 3
    with pytest.raises(m.ImportRefused, match="attempt_already_consumed"):
        run(Gist(), journal=tmp_path)


def test_lost_readback_stays_unknown(nhc, tmp_path):
    gist = Gist(readback="fail")
    result = run(gist, journal=tmp_path)
    assert result["outcome"] == "unknown" and result["after_snapshot_retained"] is False
    assert len(gist.patches) == 1
    assert json.loads(next(tmp_path.glob("*.result.json")).read_text())["outcome"] == "unknown"


def _approved(p):
    p["approved"] = True


def _review_binding(p):
    p["draft"]["review_binding"] = {"kind": "human"}


def _intent(p):
    p["draft"]["publish_intent_id"] = "invented-intent"


def _source_hold(p):
    p["draft"]["review_context"]["nhc_advisory_source_hold"] = "nhc_advisory_current_source_changed"


def _place(p):
    p["draft"]["text"] = "Up to 3 inches of rain could trigger flash flooding tonight, NHC forecasts."


def _not_pending(p):
    p["draft"]["status"] = "approved"


def _deadline(p):
    p["operator_recheck_deadline"] = "2026-10-29T21:50:00Z"


def _identity(p):
    p["draft"]["id"] = "nhc_trial_" + "f" * 32 + "_ep492026"


@pytest.mark.parametrize("edit,code", [
    (_approved, "proposal_already_applied_or_authorized"), (_review_binding, "unexpected_draft_authority"),
    (_intent, "unexpected_draft_authority"), (_source_hold, "obsolete_checks_or_context"),
    (_place, "nhc_advisory_copy_place_missing"), (_not_pending, "draft_not_pending_manual"),
    (_deadline, "proposal_deadline_mismatch"), (_identity, "unsupported_draft_identity"),
], ids=["approved", "review", "intent", "source-hold", "place", "not-pending", "deadline", "identity"])
def test_invalid_proposal_refuses_before_any_read_or_write(nhc, tmp_path, edit, code):
    made = proposal()
    edit(made)
    gist = Gist()
    with pytest.raises(m.ImportRefused, match=code):
        run(gist, encode(made), journal=tmp_path)
    assert gist.reads == 0 and gist.patches == [] and nhc.calls == [] and not list(tmp_path.iterdir())


def test_changed_proposal_bytes_refuse(nhc, tmp_path):
    raw = encode(proposal())
    with pytest.raises(m.ImportRefused, match="proposal_changed"):
        m.execute(raw + b" ", m.sha(raw), expected_state_sha256=m.sha(STATE), read=Gist().read, patch=None,
                  journal=tmp_path, clock=lambda: h.NOW, code_sha=CODE, source_sha=SOURCE)


def _gist(**kwargs):
    return lambda: Gist(**kwargs)


def _with_files(**files):
    return lambda: Gist(files=files)


def _flags(**changes):
    return lambda: Gist(flags={**FLAGS, **changes})


@pytest.mark.parametrize("make,code", [
    (_flags(THEHEAT_AUTOMATIC_PUBLICATION_ENABLED="1"), "controls_changed:theheat_automatic_publication_enabled"),
    (_flags(THEHEAT_PRODUCTION_PAUSED="0"), "controls_changed:theheat_production_paused"),
    (_flags(THEHEAT_WRITER_SAMPLES="3"), "controls_changed:theheat_writer_samples"),
    (_flags(THEHEAT_PAID_PR_REPLAY_ENABLED="1"), "paid_background_enabled"),
    (_with_files(**{"runtime-inventory.json": report(captured=h.NOW - timedelta(hours=7))}), "policy_stale"),
    (_with_files(**{"runtime-inventory.json": report(code="e" * 40)}), "policy_unverified"),
    (_gist(state=STATE.replace(b'"event_id":"other"', b'"event_id":"nhc_advisory:ep492026:34:rainfall"')),
     "duplicate_draft"),
    (_gist(state=STATE.replace(b'"posted_events":[]', b'"posted_events":["nhc_advisory:ep492026:34:rainfall"]')),
     "publication_history_exists"),
    (_gist(state=STATE.replace(b'"id":"old"', b'"id":"nhc_trial_0123456789abcdef0123456789abcdef_al012026"')),
     "trial_import_limit"),
    (_gist(state=b'{"drafts": {}}'), "state_drafts_shape"),
    (_gist(state=b'{"drafts": [], "drafts": []}'), "duplicate_json_key"),
    (_gist(state=b'{"drafts": [], "x": NaN}'), "nonfinite_number"),
], ids=["automatic", "unpaused", "samples", "paid-replay", "policy-stale", "code-changed", "duplicate",
        "history", "trial-limit", "drafts-shape", "duplicate-key", "nan"])
def test_changed_controls_policy_or_state_refuse_before_any_claim_or_write(nhc, tmp_path, make, code):
    gist = make()
    with pytest.raises(m.ImportRefused, match=code):
        run(gist, journal=tmp_path)
    assert gist.patches == [] and not list(tmp_path.glob("*.attempt.json"))


def test_state_changed_since_the_reviewed_check_refuses(nhc, tmp_path):
    gist = Gist()
    with pytest.raises(m.ImportRefused, match="state_changed_since_review"):
        run(gist, journal=tmp_path, expected="0" * 64)
    assert gist.patches == [] and nhc.calls == []


def test_a_concurrent_write_between_the_two_reads_refuses(nhc, tmp_path):
    gist = Gist()

    def race(g):
        if g.reads == 2:
            g.files["state.json"] = STATE.replace(b'"retained"', b'"edited elsewhere"')
    gist.before_read = race
    with pytest.raises(m.ImportRefused, match="snapshot_changed_before_write"):
        run(gist, journal=tmp_path)
    assert gist.patches == [] and nhc.calls == []


@pytest.mark.parametrize("change,code", [
    ({h.URL: (200, {}, h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4"))))},
     "nhc_advisory_current_source_changed"),
    ({source.INDEX_URL: (200, {}, h.index(advisory="35"))}, "nhc_advisory_superseded"),
    ({source.INDEX_URL: (200, {}, h.index(storms=[]))}, "nhc_advisory_storm_not_current"),
    ({h.URL: (301, {"location": "https://www.nhc.noaa.gov.example.test/"}, b"")}, "nhc_advisory_redirect_refused"),
    ({h.URL: (200, {}, h.page()[:300])}, "nhc_advisory_format_drift"),
], ids=["corrected", "superseded", "removed", "redirect", "partial"])
def test_a_changed_or_unreadable_current_source_refuses_before_the_claim(monkeypatch, tmp_path, change, code):
    transport = Transport(change)
    monkeypatch.setattr(source, "_http_get", transport)
    gist = Gist()
    with pytest.raises(m.ImportRefused, match=code):
        run(gist, journal=tmp_path)
    assert gist.patches == [] and not list(tmp_path.glob("*.attempt.json")) and len(transport.calls) <= 2


@pytest.mark.parametrize("minutes,code", [(26, "nhc_advisory_operator_deadline_passed"),
                                          (-5, "nhc_advisory_time_incoherent")], ids=["deadline", "before-capture"])
def test_clock_boundaries_refuse_before_network(nhc, tmp_path, minutes, code):
    gist = Gist()
    with pytest.raises(m.ImportRefused, match=code):
        run(gist, journal=tmp_path, clock=lambda: h.NOW + timedelta(minutes=minutes))
    assert gist.reads == 0 and nhc.calls == []


def test_deadline_passing_during_the_source_check_refuses_before_the_claim(nhc, tmp_path):
    ticks = iter([h.NOW] * 3)
    gist = Gist()
    with pytest.raises(m.ImportRefused, match="nhc_advisory_operator_deadline_passed"):
        run(gist, journal=tmp_path, clock=lambda: next(ticks, h.NOW + timedelta(minutes=27)))
    assert gist.patches == [] and not list(tmp_path.glob("*.attempt.json"))


class Completed:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout, self.returncode = stdout, returncode


def test_github_client_uses_only_the_fixed_routes_and_patches_at_most_once(monkeypatch):
    calls = []
    gist_id = "0" * 32

    def fake(args, **kwargs):
        calls.append((args, kwargs.get("input")))
        if args[-1] == f"gists/{gist_id}":
            return Completed(json.dumps({"files": {
                "state.json": {"content": STATE.decode(), "truncated": False},
                "runtime-inventory.json": {"content": report().decode(), "truncated": False}}}).encode())
        if "variables" in args[-1]:
            return Completed(json.dumps({"variables": [{"name": "THEHEAT_PRODUCTION_PAUSED", "value": "1"}]}).encode())
        return Completed()
    monkeypatch.setattr(m.subprocess, "run", fake)
    client = m.GitHub(gist_id, "invented-owner/invented-repo")
    files, flags = client.read()
    assert files["state.json"] == STATE and flags == {"THEHEAT_PRODUCTION_PAUSED": "1"}
    client.patch(b'{"drafts":[]}')
    args, body = calls[-1]
    assert args == ["gh", "api", "--method", "PATCH", f"gists/{gist_id}", "--input", "-"]
    assert json.loads(body) == {"files": {"state.json": {"content": '{"drafts":[]}'}}}
    with pytest.raises(m.ImportRefused, match="second_patch_forbidden"):
        client.patch(b'{"drafts":[]}')
    assert len(calls) == 3 and all(a[:2] == ["gh", "api"] for a, _ in calls)


def test_github_client_refuses_truncated_files_and_unusual_identifiers(monkeypatch):
    monkeypatch.setattr(m.subprocess, "run", lambda args, **k: Completed(json.dumps({"files": {
        "state.json": {"content": "{}", "truncated": True}}}).encode()))
    with pytest.raises(m.ImportRefused, match="gist_file_inventory_changed"):
        m.GitHub("0" * 32, "o/r").read()
    for gist_id, repository in (("../../etc", "o/r"), ("0" * 32, "https://evil.example.test/o/r")):
        with pytest.raises(m.ImportRefused, match="invalid_gist_or_repository"):
            m.GitHub(gist_id, repository)


def test_cli_prints_only_fixed_refusal_codes(monkeypatch, tmp_path, capsys):
    raw = encode(proposal())
    (tmp_path / "proposal.json").write_bytes(raw)
    monkeypatch.setattr("sys.argv", ["nhc_advisory_import.py", "check", "--proposal", str(tmp_path / "proposal.json"),
                                     "--proposal-sha256", m.sha(raw), "--gist-id", "not-a-gist",
                                     "--repository", "o/r"])
    assert m.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused", "reason": "invalid_gist_or_repository",
                                                   "writes": 0}


def test_deep_copy_of_the_proposal_is_unchanged_by_planning():
    made = proposal()
    before = deepcopy(made)
    raw = encode(made)
    m.plan(raw, m.sha(raw), Gist().files, FLAGS, h.NOW, CODE, SOURCE)
    assert made == before
