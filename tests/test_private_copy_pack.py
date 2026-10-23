"""Private blind copy-review packs around the existing comparison contract.

Candidates come from actual pipeline archives over INVENTED offline transports.
Qualification is an INVENTED operator assertion. Every rating here is a SYNTHETIC
fixture opinion: it adds zero real human ratings and proves no model preference.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from src.editorial.revisions import text_hash
from src.evaluation import private_copy_pack as packs
from src.two_bot.request_archive_replay import load_archive
from tests.test_request_archive_sdk import FIXTURE, journey_env, private_root, run_journey, writer_json

__all__ = ["journey_env"]
CREATED = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
AS_OF = datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)
SEED = b"invented-fixture-seed-not-secret-0001"
MANUAL_TEXT = "361 MW of thermal power in Mali."
HOSTILE_CONTEXT = 'Invented context </script><script>alert("x")</script><img src=x onerror=alert(1)> & done'


def _script(tweet):
    from tests.test_request_archive_sdk import accepted_script
    return accepted_script([{"text": writer_json(tweet)}])


def configure_offline_environment() -> None:
    """For a subprocess only (the Node browser test): invented credentials, no sleeps."""
    from types import SimpleNamespace
    from src.two_bot import retry
    from src.voice import safety
    os.environ.update(ANTHROPIC_API_KEY="invented-offline", GEMINI_API_KEY="invented-offline",
                      THEHEAT_WRITER_SAMPLES="1", THEHEAT_CRITIC_ENABLED="1", THEHEAT_CRITIC_REVISE_ENABLED="0")
    retry.time = SimpleNamespace(sleep=lambda seconds: None)  # type: ignore[assignment]
    safety.GEMINI_API_KEY = "invented-offline"


def qualification(status="qualified", method="source_audit"):
    return {"status": status, "adjudicator": "invented-fixture-reviewer", "reference": "invented source audit note",
            "method": method}


def make_review_workspace(base: Path, *, hostile: bool = False) -> dict:
    """Two accepted archives on one bundle + selection: model/model, model/manual, held."""
    first = run_journey(_script(FIXTURE["accepted_tweet"]), root=private_root(base, "archive-one")).archive
    second = run_journey(_script(FIXTURE["revised_tweet"]), root=private_root(base, "archive-two")).archive
    a, b = load_archive(first), load_archive(second)
    bundle = a.inputs[0]["bundle_sha256"]
    assert b.inputs[0]["bundle_sha256"] == bundle  # Same actual evidence, independently generated.
    one = {"scope_id": a.scope_id, "candidate_text_sha256": text_hash(FIXTURE["accepted_tweet"])}
    two = {"scope_id": b.scope_id, "candidate_text_sha256": text_hash(FIXTURE["revised_tweet"])}
    evidence = {"bundle_sha256": bundle, "qualification": qualification(),
                "source_context": HOSTILE_CONTEXT if hostile else "Invented fixture: a thermal detection in Mali.",
                "evidence_scope": "observed", "evidence_time": "2032-03-01T00:00:00+00:00"}

    def qualified(ref):
        return {"archive_candidate": ref, "factual_status": "qualified", "rejection_reasons": [],
                "material_claims": ["invented thermal power value"]}
    manual = {"manual_edit": {"text": MANUAL_TEXT if not hostile else '<b onmouseover="x">361 MW</b> </script>',
                              "edited_from": one, "author_assertion": "invented-operator"},
              "factual_status": "qualified", "rejection_reasons": [], "material_claims": ["invented value"]}
    selection = {"schema": packs.SELECTION_SCHEMA, "pairs": [
        {"label": "invented model vs model", "evidence": evidence, "candidates": [qualified(one), qualified(two)]},
        {"label": "invented model vs manual edit", "evidence": deepcopy(evidence),
         "candidates": [qualified(one), manual]},
        {"label": "invented unqualified evidence", "evidence": {**deepcopy(evidence),
                                                                "qualification": qualification("unverified", "not_reviewed")},
         "candidates": [qualified(one), qualified(two)]},
    ]}
    inputs = private_root(base, "inputs")
    selection_path = inputs / "selection.json"
    selection_path.write_text(json.dumps(selection))
    os.chmod(selection_path, 0o600)
    return {"archives": [first, second], "selection": selection_path, "selection_value": selection,
            "inputs": inputs, "bundle": bundle, "refs": (one, two)}


def built(workspace, **overrides):
    selection = packs.parse_selection(workspace["selection"].read_bytes())
    archives = [load_archive(path) for path in workspace["archives"]]
    return packs.build_pack(selection, archives, created_at=overrides.get("created_at", CREATED),
                            seed=overrides.get("seed", SEED))


def ballot(public, ratings, *, rater="synthetic-rater-1", kind="synthetic_fixture", rated_at="2026-10-23T12:30:00Z",
           **changes):
    value = {"schema": packs.BALLOT_SCHEMA, "form_version": "1", "pack_id": public["pack_id"],
             "pack_sha256": public["pack_sha256"], "rubric_id": public["rubric"]["id"],
             "rubric_sha256": public["rubric_sha256"], "rater_id": rater, "rater_kind": kind,
             "rater_assertion": True, "rated_at": rated_at, "ratings": ratings}
    value.update(changes)
    return json.dumps(value).encode()


def rating(pair, preference="A", score=4, notes="SYNTHETIC fixture note"):
    scores = None if preference == "abstain" else {"punch": score, "clarity": score, "unnecessary_words": 2}
    return {"pair_id": pair["pair_id"], "pair_sha256": pair["pair_sha256"], "preference": preference,
            "scores": {"A": scores, "B": scores}, "notes": notes}


@pytest.fixture
def workspace(journey_env, tmp_path):
    return make_review_workspace(tmp_path)


def test_pack_pairs_only_exact_qualified_evidence_and_holds_the_rest(workspace):
    public, private, held = built(workspace)
    assert public is not None and len(public["pairs"]) == 2
    assert held["held_pairs"] == [{"selection_index": 2, "label_sha256": held["held_pairs"][0]["label_sha256"],
                                   "reasons": ["evidence_not_qualified_by_explicit_review"]}]
    assert sorted(private["pair_kinds"].values()) == ["model_vs_manual_edit", "model_vs_model"]
    kinds = {record["kind"] for record in private["provenance"].values()}
    assert kinds == {"archive_candidate", "manual_edit"}
    archived = [r for r in private["provenance"].values() if r["kind"] == "archive_candidate"]
    assert all(r["bundle_sha256"] == workspace["bundle"] and r["model_check_outcomes"] for r in archived)
    for pair in public["pairs"]:
        assert pair["evidence_sha256"] == workspace["bundle"]
        assert "Evidence scope: observed. Evidence time: 2032-03-01T00:00:00+00:00." in pair["source_context"]
        assert pair["qualification"]["method"] == "source_audit"  # Not stripped to hide anything.
    assert built(workspace)[0] == public  # Fixed seed + clock: deterministic identities.
    other = built(workspace, seed=b"another-invented-seed-0000000002")[0]
    assert other["pack_id"] != public["pack_id"]


def test_public_pack_is_detached_from_origins_provenance_and_translation(workspace, tmp_path):
    public, private, _ = built(workspace)
    data = packs.pack_data_script(public).decode()
    for secret in [*private["provenance"], *[c["origin"] for p in private["pairs_input"] for c in p["candidates"]],
                   *[str(r["scope_id"]) for r in private["provenance"].values()], "invented-operator",
                   "claude", "gemini", "manual_edit", "edited_from", "archive:"]:
        assert secret not in data
    assert set(public) == {"schema", "created_at", "rubric", "rubric_sha256", "clock_policy", "pairs", "notice",
                           "pack_id", "pack_sha256"}
    assert all(set(pair["sides"]["A"]) == {"text", "text_sha256", "characters", "words"} for pair in public["pairs"])
    assert private["authority"] == "private_origin_mapping_never_display"


@pytest.mark.parametrize("case", ["identical_text", "newer_evidence", "unqualified_candidate", "missing_archive",
                                  "not_reviewed"])
def test_held_cases_buy_nothing_and_never_fabricate_alternatives(workspace, case):
    selection = deepcopy(workspace["selection_value"])
    pair = selection["pairs"][0]
    if case == "identical_text":
        pair["candidates"][1] = {"manual_edit": {"text": FIXTURE["accepted_tweet"], "edited_from": workspace["refs"][0],
                                                 "author_assertion": "invented-operator"},
                                 "factual_status": "qualified", "rejection_reasons": [], "material_claims": []}
        expected = "identical_text_is_not_a_comparison"
    elif case == "newer_evidence":
        pair["evidence"]["bundle_sha256"] = "f" * 64
        expected = "candidates_not_on_the_exact_selected_evidence"
    elif case == "unqualified_candidate":
        pair["candidates"][0]["factual_status"] = "unverified"
        expected = "candidate_0_not_qualified"
    elif case == "missing_archive":
        pair["candidates"][1]["archive_candidate"] = {"scope_id": "scope-" + "0" * 32,
                                                      "candidate_text_sha256": "1" * 64}
        expected = "candidate_1_not_in_verified_archives"
    else:
        pair["evidence"]["qualification"] = qualification("qualified", "not_reviewed")
        expected = "evidence_not_qualified_by_explicit_review"
    selection["pairs"] = [pair]
    parsed = packs.parse_selection(json.dumps(selection).encode())
    public, private, held = packs.build_pack(parsed, [load_archive(p) for p in workspace["archives"]],
                                             created_at=CREATED, seed=SEED)
    assert public is None and private["pack_id"] is None and held["result"] == "held_no_pair"
    assert expected in held["held_pairs"][0]["reasons"]


@pytest.mark.parametrize("change", ["path_field", "archive_path_ref", "float", "duplicate_key", "missing_qualification"])
def test_selection_is_strict_and_never_takes_paths(workspace, change):
    selection = deepcopy(workspace["selection_value"])
    if change == "path_field":
        selection["pairs"][0]["candidates"][0]["path"] = "/etc/passwd"
        data = json.dumps(selection).encode()
    elif change == "archive_path_ref":
        selection["pairs"][0]["candidates"][0]["archive_candidate"]["scope_id"] = "/abs/scope-dir"
        data = json.dumps(selection).encode()
    elif change == "float":
        data = json.dumps(selection).encode().replace(b'"schema"', b'"x": 1.5, "schema"', 1)
    elif change == "duplicate_key":
        data = json.dumps(selection).encode().replace(b'"schema"', b'"schema": "x", "schema"', 1)
    else:
        del selection["pairs"][0]["evidence"]["qualification"]
        data = json.dumps(selection).encode()
    with pytest.raises(packs.CopyReviewError):
        packs.parse_selection(data)


def test_hostile_text_is_escaped_in_page_data(journey_env, tmp_path):
    hostile = make_review_workspace(tmp_path, hostile=True)
    public, _, _ = built(hostile)
    data = packs.pack_data_script(public).decode()
    assert "</script" not in data.lower() and "<img" not in data and "<b " not in data
    assert "\\u003c/script\\u003e" in data and "\\u0026" in data
    assert public["pairs"][0]["source_context"].startswith(HOSTILE_CONTEXT)  # Text preserved exactly.


def test_import_restores_bindings_and_keeps_every_outcome_separate(workspace):
    public, private, _ = built(workspace)
    p1, p2 = public["pairs"]
    good = ballot(public, [rating(p1, "A"), rating(p2, "tie")])
    second = ballot(public, [rating(p1, "abstain")], rater="synthetic-rater-2")
    human = ballot(public, [rating(p1, "B")], rater="invented-human-1", kind="human_assertion")
    conflicting_first = ballot(public, [rating(p2, "A")], rater="synthetic-rater-3")
    conflicting_second = ballot(public, [rating(p2, "B")], rater="synthetic-rater-3")
    stale = ballot(public, [{**rating(p1), "pair_sha256": "0" * 64}], rater="synthetic-rater-4")
    forged = [ballot(public, [rating(p1, score=value)], rater=f"synthetic-forged-{i}")
              for i, value in enumerate([True, "4", 6, 0])]
    clocks = [ballot(public, [rating(p1)], rater="synthetic-clock-1", rated_at="2026-10-23T12:30:00"),
              ballot(public, [rating(p1)], rater="synthetic-clock-2", rated_at="2027-01-01T00:00:00Z"),
              ballot(public, [rating(p1)], rater="synthetic-clock-3", rated_at="2026-10-22T00:00:00Z"),
              ballot(public, [rating(p1)], rater="synthetic-clock-4", rated_at="not a time")]
    wrong = [ballot(public, [rating(p1)], pack_id="pack-0000000000000000"),
             ballot(public, [rating(p1)], rubric_sha256="0" * 64),
             ballot(public, [rating(p1)], rater_assertion=False),
             ballot(public, [rating(p1)], rater_kind="model"),
             ballot(public, [{**rating(p1), "extra": 1}], rater="synthetic-extra"),
             ballot(public, [{k: v for k, v in rating(p1).items() if k != "pair_sha256"}], rater="synthetic-missing"),
             ballot(public, [], rater="synthetic-empty"),
             ballot(public, [rating(p1)] * 3, rater="synthetic-too-many"),
             b'{"schema": NaN}']
    report = packs.import_ballots(private, [good, good, second, human, conflicting_first, conflicting_second, stale,
                                            *forged, *clocks, *wrong], as_of=AS_OF)
    synthetic, real = report["synthetic_fixture_summary"], report["human_asserted_summary"]
    assert report["identical_retries_collapsed"] == 2  # The whole good ballot retried once.
    assert report["conflicts"] == [{"pair_id": p2["pair_id"], "rater_id": "synthetic-rater-3", "ratings": 2,
                                    "outcome": "conflicting_ratings_quarantined"}]
    assert synthetic["eligible_preferences_by_display_side"] == {"A": 1, "B": 0, "tie": 1, "abstain": 1}
    assert real["eligible_preferences_by_display_side"] == {"A": 0, "B": 1, "tie": 0, "abstain": 0}
    assert report["real_human_ratings_added"] == 1  # Only the typed human assertion; never authenticated.
    reasons = sorted(b.get("reason") for b in report["ballots"] if b["outcome"] != "ballot_read")
    assert reasons == sorted([
        "rating_stale_pair_binding", *["rating_rejected_by_existing_contract"] * 4,
        "ballot_clock_invalid_or_naive", "ballot_clock_outside_policy", "ballot_clock_outside_policy",
        "ballot_clock_invalid_or_naive", "ballot_for_another_or_changed_pack", "ballot_rubric_mismatch",
        "ballot_rater_assertion", "ballot_rater_assertion", "rating_shape", "rating_shape",
        "ballot_ratings_shape", "ballot_json_invalid"])
    empty = [b for b in report["ballots"] if b.get("ratings_offered") == 0]
    assert len(empty) == 1 and empty[0]["ratings_valid"] == 0
    assert report["interpretation"]["synthetic_fixture_summary"] == "synthetic_fixture_ballots_are_not_human_preference"
    assert report["interpretation"]["model_vs_manual_edit"] == "a_manual_edit_preference_is_not_a_model_A_B_result"
    assert report["interpretation"]["publication_approved"] is False


@pytest.mark.parametrize("edit", ["text", "evidence", "qualification", "sides", "context"])
def test_any_edit_to_pack_inputs_invalidates_every_old_rating(workspace, edit):
    public, private, _ = built(workspace)
    good = ballot(public, [rating(public["pairs"][0])])
    changed = deepcopy(private)
    pair = changed["pairs_input"][0]
    if edit == "text":
        pair["candidates"][0]["text"] = "Invented revised text."
        pair["candidates"][0]["text_sha256"] = text_hash("Invented revised text.")
    elif edit == "evidence":
        pair["evidence_sha256"] = "e" * 64
    elif edit == "qualification":
        pair["qualification"]["reference"] = "invented changed reference"
    elif edit == "sides":
        sides = changed["side_assignments"][pair["pair_id"]]
        sides["A"], sides["B"] = sides["B"], sides["A"]
    else:
        pair["source_context"] += " Changed."
    with pytest.raises(packs.CopyReviewError, match="pack_changed_since_export"):
        packs.import_ballots(changed, [good], as_of=AS_OF)


def test_unrated_pairs_and_clock_policy_are_explicit(workspace):
    public, private, _ = built(workspace)
    report = packs.import_ballots(private, [ballot(public, [rating(public["pairs"][0])])], as_of=AS_OF)
    assert report["synthetic_fixture_summary"]["unrated_pair_count"] == 1
    assert report["human_asserted_summary"]["unrated_pair_count"] == 2
    assert "5 minutes" in report["clock_policy"]
    with pytest.raises(packs.CopyReviewError, match="as_of_not_aware"):
        packs.import_ballots(private, [], as_of=AS_OF.replace(tzinfo=None))
    late = packs.import_ballots(private, [ballot(public, [rating(public["pairs"][0])],
                                                 rated_at=(AS_OF + timedelta(minutes=4)).isoformat())], as_of=AS_OF)
    assert late["ballots"][0]["outcome"] == "ballot_read"


@pytest.mark.parametrize("field", ["archives", "provenance", "pair_kinds", "private_mapping", "selection_sha256"])
def test_retained_private_fields_are_bound_even_when_display_does_not_change(workspace, field):
    public, private, _ = built(workspace)
    good = ballot(public, [rating(public["pairs"][0])])
    changed = deepcopy(private)
    if field == "archives":
        changed[field] = []
    elif field == "provenance":
        next(iter(changed[field].values()))["manifest_sha256"] = "0" * 64
    elif field == "pair_kinds":
        manual = next(pair for pair, kind in changed[field].items() if kind == "model_vs_manual_edit")
        changed[field][manual] = "model_vs_model"
    elif field == "private_mapping":
        next(iter(changed[field].values()))["rating_binding"]["evidence_sha256"] = "0" * 64
    else:
        changed[field] = "0" * 64
    with pytest.raises(packs.CopyReviewError, match="private_record_identity_mismatch"):
        packs.import_ballots(changed, [good], as_of=AS_OF)


@pytest.mark.parametrize("field", ["archives", "provenance", "pair_kinds", "private_mapping"])
def test_resigned_private_metadata_must_still_agree_with_origin_and_display_inputs(workspace, field):
    _, private, _ = built(workspace)
    changed = deepcopy(private)
    if field == "archives":
        changed[field] = []
    elif field == "provenance":
        next(iter(changed[field].values()))["bundle_sha256"] = "0" * 64
    elif field == "pair_kinds":
        manual = next(pair for pair, kind in changed[field].items() if kind == "model_vs_manual_edit")
        changed[field][manual] = "model_vs_model"
    else:
        next(iter(changed[field].values()))["rating_binding"]["evidence_sha256"] = "0" * 64
    changed["private_sha256"] = packs._identity(changed, "private_sha256")
    with pytest.raises(packs.CopyReviewError):
        packs.verify_private_record(changed)


def test_import_report_reconstructs_summaries_counts_clocks_and_exact_private_identity(workspace):
    public, private, _ = built(workspace)
    synthetic = ballot(public, [rating(public["pairs"][0])])
    human = ballot(public, [rating(public["pairs"][1], "tie")], rater="invented-human", kind="human_assertion")
    report = packs.import_ballots(private, [synthetic, synthetic, human], as_of=AS_OF)
    assert packs.verify_import_report(report, private, as_of=AS_OF) == report
    assert report["identical_retries_collapsed"] == 1
    assert report["real_human_ratings_added"] == 1
    assert report["synthetic_fixture_summary"]["unique_rating_count"] == 1
    for field in ("private_sha256", "real_human_ratings_added", "identical_retries_collapsed", "conflicts",
                  "human_asserted_summary", "synthetic_fixture_summary", "offered_ratings"):
        changed = deepcopy(report)
        if field == "private_sha256":
            changed[field] = "0" * 64
        elif field in ("real_human_ratings_added", "identical_retries_collapsed"):
            changed[field] += 1
        elif field == "conflicts":
            changed[field] = [{"pair_id": "forged"}]
        elif field == "offered_ratings":
            changed[field][0]["rating"]["binding"]["evidence_sha256"] = "0" * 64
        else:
            changed[field]["unique_rating_count"] += 1
        with pytest.raises(packs.CopyReviewError, match="import_report_identity_mismatch"):
            packs.verify_import_report(changed, private, as_of=AS_OF)
        changed["report_sha256"] = packs._identity(changed, "report_sha256")
        with pytest.raises(packs.CopyReviewError):
            packs.verify_import_report(changed, private, as_of=AS_OF)
    with pytest.raises(packs.CopyReviewError, match="import_report_clock_or_rubric"):
        packs.verify_import_report(report, private, as_of=AS_OF - timedelta(seconds=1))
    changed = deepcopy(report)
    changed["offered_ratings"][0]["rating"]["rated_at"] = "2030-01-01T00:00:00Z"
    changed["report_sha256"] = packs._identity(changed, "report_sha256")
    with pytest.raises(packs.CopyReviewError, match="import_rating_clock_outside_policy"):
        packs.verify_import_report(changed, private, as_of=AS_OF)


def test_malformed_pair_identifier_and_unknown_form_version_are_bounded_refusals(workspace):
    public, private, _ = built(workspace)
    malformed = {**rating(public["pairs"][0]), "pair_id": []}
    report = packs.import_ballots(private, [ballot(public, [malformed]),
                                            ballot(public, [], form_version="future")], as_of=AS_OF)
    assert [item.get("reason") for item in report["ballots"]] == ["rating_unknown_pair", None, "ballot_form_version"]


def test_unused_invalid_archive_remains_invalid_in_bound_private_inputs(workspace, tmp_path):
    invalid = load_archive(private_root(tmp_path, "scope-" + "0" * 32))
    assert invalid.status == "invalid"
    public, private, _ = packs.build_pack(packs.parse_selection(workspace["selection"].read_bytes()),
                                          [*[load_archive(path) for path in workspace["archives"]], invalid],
                                          created_at=CREATED, seed=SEED)
    assert packs.verify_private_record(private) == public
    assert any(item["status"] == "invalid" for item in private["archives"])
