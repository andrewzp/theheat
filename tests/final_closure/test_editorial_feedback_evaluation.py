"""Final closure B4: correction-candidate joins, copy review packs, copy comparisons.

Invented station, posts and copy only. The GHCN finding comes from the real
revision producer (``ghcn._retain_changed_point``) on an invented row. Nothing is
fetched, posted, corrected or deleted; outputs are review-only and descriptive.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.data import ghcn
from src.data.ghcn_format import DiffRecord
from src.editorial.revisions import draft_identity, text_hash
from src.evaluation import copy_review, correction_candidates

ROOT = Path(__file__).resolve().parents[2]
STATION = "ZZ000000001"  # Invented identifier.
RETRIEVED = "2026-10-20T06:00:00Z"
POST_TEXT = "Sample Town reached 39.9°C on June 25, its hottest June day in the available GHCN archive since 1951."


def _posted_state(text=POST_TEXT, *, tweet_id="1999999999999999999"):
    draft = {"id": "invented-post", "event_id": "ghcn_alltime_high_ZZ000000001_2026-06-25", "type": "temperature",
             "status": "posted", "text": text, "tweet_id": tweet_id, "posted_at": "2026-06-26T12:00:00Z",
             "content_revision": 1}
    ledger = {draft["event_id"]: {"phase": "confirmed", "tweet_id": tweet_id, "text": text,
                                  "text_sha256": text_hash(text), "confirmed_at": "2026-06-26T12:00:05Z"}}
    return {"drafts": [draft], "publish_ledger": ledger}


def _claim(state, value=39.9):
    draft = state["drafts"][0]
    return {"station_id": STATION, "valid_date": "2026-06-25", "element": "TMAX", "draft_id": draft["id"],
            "event_id": draft["event_id"], "text_sha256": text_hash(draft["text"]), "tweet_id": draft["tweet_id"],
            "status": "posted", "reported_value_c": value, "reported_previous_c": 39.1,
            "publication_time_qflag": None, "baseline": {}}


def _qc_flagged(state, *, value=39.9, qflag="S"):
    row = DiffRecord("update", STATION, date(2026, 6, 25), "TMAX", value, qflag=qflag)
    before = deepcopy(state["drafts"])
    added, findings = ghcn._retain_changed_point(state, row, RETRIEVED, "a" * 64, [_claim(state, value)])
    assert findings == 1 and state["drafts"] == before  # A posted claim is never rewritten.
    return state


def test_a_later_qc_flag_on_a_confirmed_post_becomes_a_review_only_candidate():
    state = _qc_flagged(_posted_state())
    result = correction_candidates.prepare_from_state(state)
    assert result["source_findings"]["derived"] == 1 and not result["incomplete"]
    [candidate] = result["candidates"]
    assert candidate["claim"] == POST_TEXT and candidate["claim"] in state["publish_ledger"][
        "ghcn_alltime_high_ZZ000000001_2026-06-25"]["text"]
    assert candidate["kind"] == "value" and candidate["action"] == "editor_review_only"
    assert candidate["automatic_correction"] is False and candidate["deletion"] is False
    assert "QFLAG 'S'" in candidate["source_evidence"]["statement"]
    assert candidate["source_evidence"]["retrieved_at"] == RETRIEVED
    assert "Publication-time QC status is unknown" in candidate["uncertainty"]
    assert "does not establish that the post was wrong when published" in candidate["uncertainty"]


def test_fahrenheit_copy_still_quotes_the_one_matching_sentence():
    text = "Sample Town reached 103.8°F on June 25 in the available GHCN archive."
    result = correction_candidates.prepare_from_state(_qc_flagged(_posted_state(text)))
    assert [c["claim"] for c in result["candidates"]] == [text]


def test_an_ambiguous_or_missing_quote_is_named_evidence_needed_never_guessed():
    text = "Sample Town reached 39.9°C. A second site also hit 39.9°C."
    result = correction_candidates.prepare_from_state(_qc_flagged(_posted_state(text)))
    assert not result["candidates"]
    assert result["incomplete"][0]["needed"] == ["exact_claim_quoted_from_delivered_text"]


def test_coverage_gaps_and_unconfirmed_posts_are_not_contradictions():
    state = _posted_state()
    row = DiffRecord("update", STATION, date(2026, 6, 25), "TMAX", None)
    ghcn._retain_changed_point(state, row, RETRIEVED, "a" * 64, [_claim(state)])
    result = correction_candidates.prepare_from_state(state)
    assert not result["candidates"]
    assert result["source_findings"]["review_only"][0]["status"] == "review_only_not_a_contradiction"
    unposted = _posted_state()
    unposted["publish_ledger"] = {}
    _qc_flagged(unposted)
    assert correction_candidates.prepare_from_state(unposted)["candidates"] == []


def test_supplied_discrepancies_and_reader_flags_keep_their_existing_rules():
    state = _qc_flagged(_posted_state())
    partial = {"tweet_id": "1999999999999999999", "claim": "not in the post", "kind": "value"}
    result = correction_candidates.prepare_from_state(state, [partial],
                                                      reader_flags=[{"tweet_id": "1999999999999999999"}])
    assert len(result["candidates"]) == 1 and len(result["incomplete"]) == 1
    assert result["reader_flags"] == []  # A source-complete candidate already exists.


def _cli(*args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/tmp", "LC_ALL": "C"}
    return subprocess.run([sys.executable, str(ROOT / "scripts/theheat_evaluation.py"), *args],
                          capture_output=True, text=True, env=env, check=False)


def test_cli_derives_candidates_from_a_private_state_file(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(_qc_flagged(_posted_state())))
    out = tmp_path / "corrections.json"
    run = _cli("correction-candidates", "--state", str(state_path), "--from-source-findings", "--output", str(out))
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(out.read_text())["candidates"][0]["action"] == "editor_review_only"
    assert POST_TEXT not in run.stdout
    refused = _cli("correction-candidates", "--state", str(state_path), "--output", str(tmp_path / "x.json"))
    assert refused.returncode == 2 and "discrepancies_or_source_findings_required" in refused.stdout


def _desk_state():
    rows = [
        ("posted-1", "posted", "Port Example hit 47°C Thursday, 8°C above its July normal.", "2026-10-20T10:00:00Z"),
        ("posted-2", "posted", "A model forecast puts Sample City at 44°C, a stark reminder of a warming world.",
         "2026-10-21T10:00:00Z"),
        ("rejected-1", "rejected", "Sample Bay reached 31°C. That beat 1998. It was hot.", "2026-10-22T10:00:00Z"),
        ("pending-1", "pending", "Sample Coast is forecast to reach 45°C Friday.", "2026-10-23T10:00:00Z"),
        ("held-1", "pending", "Invented held draft text.", "2026-10-23T11:00:00Z"),
    ]
    drafts = []
    for draft_id, status, text, at in rows:
        d = {"id": draft_id, "status": status, "text": text, "type": "temperature", "updated_at": at,
             "content_revision": 1}
        if status == "posted":
            d.update(tweet_id=str(10**18 + len(drafts)), posted_at=at)
        drafts.append(d)
    drafts[0]["review_context"] = {"two_bot": {"reviewed_policy_sha256": "c" * 64}}
    return {"drafts": drafts}


T0, T1 = datetime(2026, 10, 19, tzinfo=UTC), datetime(2026, 10, 26, tzinfo=UTC)


def test_review_pack_lists_recent_copy_with_notes_and_exact_feedback_targets():
    state = _desk_state()
    pack = copy_review.review_pack(state, since=T0, until=T1)
    assert [item["draft_id"] for item in pack["items"]] == ["rejected-1", "posted-2", "posted-1"]
    by_id = {item["draft_id"]: item for item in pack["items"]}
    assert [n["code"] for n in by_id["posted-2"]["copy_notes"]] == ["source_led_opener", "generic_explanatory_ending"]
    assert [n["code"] for n in by_id["rejected-1"]["copy_notes"]] == ["too_many_sentences"]
    assert by_id["posted-1"]["copy_notes"] == [] and by_id["posted-1"]["reviewed_policy_sha256"] == "c" * 64
    target = by_id["posted-1"]["feedback_target"]
    assert {k: target[k] for k in ("content_revision", "text_sha256", "evidence_sha256")} == draft_identity(state["drafts"][0])
    assert by_id["posted-1"]["feedback"]["tags"] == []  # Blank: absence is never a negative score.


def test_pending_drafts_need_opt_in_and_named_ids_stay_out():
    state = _desk_state()
    with_pending = copy_review.review_pack(state, since=T0, until=T1, statuses=("posted", "rejected", "pending"),
                                           exclude_ids=["held-1"])
    ids = [item["draft_id"] for item in with_pending["items"]]
    assert "pending-1" in ids and "held-1" not in ids and with_pending["skipped"] == {"excluded_by_id": 1}
    with pytest.raises(ValueError):
        copy_review.review_pack(state, since=T1, until=T0)


def test_comparison_is_descriptive_and_never_echoes_incumbent_text():
    incumbent = ["Invented incumbent copy one. With a second sentence. And a third.",
                 "According to the agency, Port Example hit 47°C."]
    result = copy_review.compare(_desk_state(), since=T0, until=T1, policy_sha256="c" * 64, incumbent_texts=incumbent)
    groups = result["groups"]
    assert groups["incumbent_supplied"]["count"] == 2
    assert groups["incumbent_supplied"]["note_counts"]["source_led_opener"] == 1
    assert groups["incumbent_supplied"]["note_counts"]["too_many_sentences"] == 1
    assert groups["drafts_current_policy"]["count"] == 1 and groups["drafts_current_policy"]["with_blocking_note"] == 0
    assert groups["drafts_other_or_unbound"]["count"] == 4
    assert result["quality_result"] is None and result["preference_result"] is None
    assert not any(text in json.dumps(result) for text in incumbent)
    assert copy_review.compare(_desk_state(), since=T0, until=T1)["groups"]["incumbent_supplied"]["status"] == "not_supplied"


def test_cli_pack_is_owner_only_and_prints_no_copy(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(_desk_state()))
    out = tmp_path / "pack.json"
    run = _cli("copy-review-pack", "--state", str(state_path), "--since", T0.isoformat(), "--until", T1.isoformat(),
               "--output", str(out))
    assert run.returncode == 0, run.stdout + run.stderr
    assert os.stat(out).st_mode & 0o777 == 0o600
    assert json.loads(run.stdout)["items"] == 3 and "Port Example" not in run.stdout
    again = _cli("copy-review-pack", "--state", str(state_path), "--since", T0.isoformat(), "--until", T1.isoformat(),
                 "--output", str(out))
    assert again.returncode == 2 and "output_exists" in again.stdout
