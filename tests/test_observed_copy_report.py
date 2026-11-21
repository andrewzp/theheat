"""Offline observed-copy report on invented exports: identity, stages, measures and file boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from itertools import permutations

import pytest

from scripts import observed_copy_report as cli
from src.evaluation import observed_copy as oc

OBSERVED_BUNDLE = {"raw_signal_dump": {"evidence": {"evidence_type": "observed"}},
                   "current_facts": [{"label": "observed_high_c", "value": 40.2},
                                     {"label": "source_station", "value": "Invented Station"}]}


def draft(identifier, text, **extra):
    row = {"id": identifier, "type": "observed_metar_contrast", "status": "pending", "text": text,
           "review_context": {"two_bot": {"bundle": OBSERVED_BUNDLE,
                                          "fact_check": {"passed": True}, "critic": {"verdict": "PASS"}}}}
    row.update(extra)
    return row


def export(tmp_path, name, drafts, suppressions=()):
    path = tmp_path / name
    path.write_text(json.dumps({"drafts": list(drafts), "suppressions": list(suppressions)}))
    return path


GOOD = "Invented Station reached 40.2°C on 3 September, its highest in the available GHCN archive through 2026-09-02."


# --- identity --------------------------------------------------------------------------------------

def test_identical_exports_count_once_and_conflicting_ones_are_held_and_excluded(tmp_path):
    one = draft("invented-1", GOOD)
    a = oc.parse_export("a.json", json.dumps({"drafts": [one, draft("invented-2", GOOD)]}).encode())
    b = oc.parse_export("b.json", json.dumps({"drafts": [one, draft("invented-2", GOOD + " Changed.")]}).encode())
    summary, _md, sheet = oc.build_report([a, b])
    assert summary["identities"] == {"supplied_records": 4, "distinct_ids": 2, "included": 1,
                                     "conflicting_held_and_excluded": 1}
    [conflict] = summary["conflicts"]
    assert conflict["variants"] == 2 and [p["input"] for p in conflict["pointers"]] == ["a.json", "b.json"]
    assert "Changed." not in sheet  # the conflicting variant is not picked


@pytest.mark.parametrize("raw,code", [
    (b"not json", "input_not_json"), (b'{"drafts": [{"id": "x", "text": NaN}]}', "input_non_finite_number"),
    (b'{"no": []}', "input_has_no_draft_list"), (b'{"drafts": [{"text": "x"}]}', "draft_without_identity"),
    (b'{"drafts": [{"id": "x"}]}', "draft_without_text"), (b'{"drafts": ["x"]}', "draft_without_identity"),
])
def test_unusable_supplied_evidence_fails_visibly(raw, code):
    with pytest.raises(oc.ReportError) as caught:
        oc.parse_export("bad.json", raw)
    assert caught.value.code == code


# --- recorded stages --------------------------------------------------------------------------------

def test_stages_are_reported_as_recorded_never_upgraded():
    sha = hashlib.sha256(GOOD.encode()).hexdigest()
    observation = {"schema_version": 1, "basis": "accepted_writer_result", "event_id": "invented-event",
                   "angle_chosen": "observed", "bundle_sha256": "1" * 64, "text_sha256": sha}
    rows = [
        draft("joined", GOOD, review_context={"two_bot": {"accepted_writer_observation": observation,
                                                          "fact_check": {"passed": True}}}),
        draft("edited", GOOD, review_context={"two_bot": {"accepted_writer_observation": {**observation, "text_sha256": "0" * 64}}}),
        draft("posted", GOOD, status="posted", tweet_id="123456"),
        draft("posted-no-receipt", GOOD, status="posted"),
        {"id": "bare", "text": GOOD},
    ]
    summary, _md, _sheet = oc.build_report([oc.parse_export("s.json", json.dumps(
        {"drafts": rows, "suppressions": [{"stage": "fact_check"}, {"stage": "fact_check"}, {}]}).encode())])
    stages = summary["stages"]
    assert stages["writer_to_saved"] == {"final_differs_from_accepted_writer_output": 1,
                                         "final_equals_accepted_writer_output": 1, "unjoined": 3}
    # Nonposted status describes the retained record, not actual X visibility.
    assert stages["publication"] == {"no_publication_recorded": 2, "recorded_receipt": 1, "status_posted_without_receipt": 1,
                                     "unknown": 1}
    assert stages["fact_check"] == {"passed": 3, "unknown": 2}
    assert stages["generation"] == {"recorded": 2, "unknown": 3}
    assert summary["retained_suppressions"]["stage_counts"] == {"fact_check": 2, "unknown": 1}
    assert summary["retained_suppressions"]["unique_failed_generations"] is None


# --- deterministic text measures --------------------------------------------------------------------

@pytest.mark.parametrize("text,count", [
    (GOOD, 1),
    ("Invented Town hit 39.9°C at 3 p.m. in the U.S. Midwest on Nov. 16, a station high.", 1),
    ("Invented Town hit 39.9°C on 16 November. That beat its old high by 1.2°C.", 2),
    ("Invented Town hit -12°C. It was the coldest. Nobody expected it.", 3),
    ("Invented Town hit 39.9°C on 16 November.\nhttps://example.invalid/a.b/obs?x=1.5", 1),
    ("Invented Town hit 39.9°C on 16 November", 1),
])
def test_sentence_counter_respects_decimals_abbreviations_dates_and_urls(text, count):
    assert oc.sentence_count(text) == count


@pytest.mark.parametrize("text,observed,codes", [
    (GOOD, True, []),
    ("GHCN data show Invented Station reached 40.2°C on 3 September.", True, ["source_or_acronym_lead"]),
    ("Invented Station reached 40.2°C on 3 September; on 3 September it also set a low.", True, ["repeated_date"]),
    ("Invented Station hit 40.2°C, 104°F, 12 mm of rain and 55 mph gusts on 3 September.", True,
     ["many_competing_numbers"]),
    ("Preliminary, provisional and available readings show Invented Station at 40.2°C on 3 September.", True,
     ["stacked_qualifiers"]),
    ("Invented 40°C on 3 Sep.\nhttps://example.invalid/a/very/long/source/path/that/dominates/the/post", True,
     ["source_url_dominates_text"]),
    ("Invented Station reached 40.2°C, its highest in the available archive.", True, ["no_explicit_observation_date"]),
    ("Invented Station reached 40.2°C, its highest in the available archive.", None, []),
])
def test_each_warning_is_a_specific_lexical_prompt(text, observed, codes):
    assert oc.warnings_for(text, observed=observed) == codes


# --- command and file boundary ------------------------------------------------------------------------

def test_command_writes_a_new_private_directory_and_prints_no_draft_text(tmp_path, capsys):
    source = export(tmp_path, "state.json", [draft("invented-1", GOOD)])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    out = tmp_path / "report"
    assert cli.main(["--input", str(source), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert GOOD not in printed and "Invented Station" not in printed
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o700
    assert sorted(os.listdir(out)) == ["report.json", "report.md", "review-sheet.md"]
    assert all(stat.S_IMODE(os.stat(out / name).st_mode) == 0o600 for name in os.listdir(out))
    report = json.loads((out / "report.json").read_text())
    assert report["advisory_only"] is True and GOOD not in json.dumps(report)
    assert GOOD in (out / "review-sheet.md").read_text()  # exact text only in the private sheet
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert cli.main(["--input", str(source), "--out", str(out)]) == 2  # never overwritten
    assert json.loads(capsys.readouterr().out) == {"error": "output_exists"}


def test_symlinked_or_special_inputs_are_refused(tmp_path, capsys):
    real = export(tmp_path, "state.json", [draft("invented-1", GOOD)])
    link = tmp_path / "link.json"
    link.symlink_to(real)
    assert cli.main(["--input", str(link), "--out", str(tmp_path / "r1")]) == 2
    fifo = tmp_path / "pipe.json"
    os.mkfifo(fifo)
    assert cli.main(["--input", str(fifo), "--out", str(tmp_path / "r2")]) == 2
    assert not (tmp_path / "r1").exists() and not (tmp_path / "r2").exists()
    assert all("error" in json.loads(line) for line in capsys.readouterr().out.splitlines())


def test_no_network_or_provider_is_touched(tmp_path, monkeypatch):
    import socket

    def refuse(*_args, **_kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    source = export(tmp_path, "state.json", [draft("invented-1", GOOD)])
    assert cli.main(["--input", str(source), "--out", str(tmp_path / "report")]) == 0


def test_public_documentation_uses_only_invented_examples():
    doc = Path(__file__).resolve().parents[1] / "docs" / "observed-copy-report.md"
    text = doc.read_text()
    assert "Invented" in text and "advisory" in text.lower()


# Root O3 integration repairs: retained rows are not paid/model denominators.
def report_export(label, suppressions, *, capture="one", include_history=True):
    payload = {"drafts": [draft("invented-one", GOOD)], "capture_label": capture}
    if include_history:
        payload["suppressions"] = suppressions
    return oc.parse_export(label, json.dumps(payload).encode())


def test_repeated_export_and_exact_copy_do_not_inflate_suppression_counts():
    one = report_export("one.json", [{"id": "invented-kill", "stage": "fact_check"}])
    copy = report_export("copy.json", [{"id": "invented-kill", "stage": "fact_check"}])
    original = oc.build_report([one])[0]
    repeated, markdown, _ = oc.build_report([one, one, copy])
    assert original["retained_suppressions"]["stage_counts"] == {"fact_check": 1}
    assert repeated["retained_suppressions"]["stage_counts"] == {"fact_check": 1}
    assert len(repeated["inputs"]) == 3
    [row] = repeated["retained_suppressions"]["rows"]
    assert [p["argument_index"] for p in row["pointers"]] == [0, 1, 2]
    assert [p["input"] for p in row["pointers"]] == ["one.json", "one.json", "copy.json"]
    assert "generation_failures_recorded" not in repeated
    assert "not unique failed generations or paid attempts" in markdown


def test_anonymous_rows_keep_row_and_capture_scope_without_fake_uniqueness():
    rows = [{"stage": "fact_check"}, {"stage": "fact_check"}]
    first = report_export("first.json", rows, capture="one")
    second = report_export("second.json", rows, capture="two")
    summary, _, _ = oc.build_report([first, first, second])
    retained = summary["retained_suppressions"]
    assert retained["stage_counts"] == {"fact_check": 4}
    assert retained["anonymous_rows_included"] == 4
    assert retained["unique_failed_generations"] is None
    assert retained["paid_attempts"] is None


@pytest.mark.parametrize("reverse", [False, True])
def test_identified_repeated_row_across_distinct_captures_counts_once(reverse):
    row = {"id": "invented-stable-row", "stage": "score_gate"}
    inputs = [report_export("one.json", [row], capture="one"),
              report_export("two.json", [row], capture="two")]
    if reverse:
        inputs.reverse()
    summary, _, _ = oc.build_report(inputs)
    assert summary["retained_suppressions"]["stage_counts"] == {"score_gate": 1}
    assert summary["retained_suppressions"]["identified_rows_included"] == 1


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_conflicting_suppression_ids_are_held_in_every_input_order(order):
    inputs = [report_export("one.json", [{"id": "invented-conflict", "stage": "fact_check"}], capture="one"),
              report_export("two.json", [{"id": "invented-conflict", "stage": "score_gate"}], capture="two"),
              report_export("three.json", [{"id": "invented-independent", "stage": "critic"}], capture="three")]
    summary, _, _ = oc.build_report([inputs[i] for i in order])
    retained = summary["retained_suppressions"]
    assert retained["stage_counts"] == {"critic": 1}
    assert retained["conflicting_ids_held"] == 1
    assert retained["identified_rows_included"] == 1
    assert len(retained["conflicts"]) == 1
    assert retained["conflicts"][0]["variants"] == 2
    assert {p["input"] for p in retained["conflicts"][0]["pointers"]} == {"one.json", "two.json"}


def test_missing_suppression_history_is_unknown_not_an_empty_observation():
    missing = report_export("missing.json", None, include_history=False)
    empty = report_export("empty.json", [])
    summary, markdown, _ = oc.build_report([missing, empty])
    retained = summary["retained_suppressions"]
    assert retained["exports_without_history"] == 1
    assert retained["exports_with_retained_list"] == 1
    assert retained["stage_counts"] == {}
    assert retained["availability"] == "partial_or_unavailable"
    assert "unavailable" in markdown.lower()


@pytest.mark.parametrize("raw,code", [
    (b'{"drafts":[],"drafts":[]}', "input_duplicate_key"),
    (b'{"drafts":[{"id":"a","text":"Invented","text":"Other"}]}', "input_duplicate_key"),
    (b'{"drafts":[],"extra":1e309}', "input_non_finite_number"),
    (b'{"drafts":[],"extra":-1e309}', "input_non_finite_number"),
    (b'{"drafts":[],"suppressions":"unknown"}', "suppression_history_invalid"),
    (b'{"drafts":[],"suppressions":[null]}', "suppression_without_object"),
    (b'{"drafts":[],"suppressions":[{"stage":{}}]}', "suppression_invalid_stage"),
    (b'{"drafts":[],"suppressions":[{"id":true}]}', "suppression_invalid_identity"),
    (b'{"drafts":[{"id":"a","text":"\\ud800"}]}', "input_invalid_string"),
])
def test_ambiguous_or_malformed_export_is_a_bounded_refusal(raw, code):
    with pytest.raises(oc.ReportError) as caught:
        oc.parse_export("invented.json", raw)
    assert caught.value.code == code


def test_bare_list_pointer_addresses_the_actual_input_array():
    export = oc.parse_export("list.json", json.dumps([draft("invented-list", GOOD)]).encode())
    summary, _, _ = oc.build_report([export])
    assert summary["drafts"][0]["pointers"][0]["pointer"] == "/0"


@pytest.mark.parametrize("outcome", ["unknown", "submitted", "confirmed"])
def test_pending_status_never_erases_unresolved_or_contradictory_delivery(outcome):
    row = draft("invented-delivery", GOOD, publish_outcome=outcome)
    summary, _, _ = oc.build_report([oc.parse_export("s.json", json.dumps([row]).encode())])
    assert summary["stages"]["publication"] == {"unknown": 1}


def test_cli_never_echoes_copy_in_untrusted_stage_labels(tmp_path, capsys):
    private = "Invented private copy must never be printed"
    row = draft("invented-label", GOOD, status=private,
                review_context={"two_bot": {"critic": {"verdict": private}}})
    source = export(tmp_path, "state.json", [row], suppressions=[{"stage": private}])
    assert cli.main(["--input", str(source), "--out", str(tmp_path / "report")]) == 0
    stdout = capsys.readouterr().out
    assert private not in stdout and GOOD not in stdout
    result = json.loads(stdout)
    assert result["stages"]["status"] == {"unknown": 1}
    assert result["stages"]["critic"] == {"unknown": 1}
    assert result["retained_suppression_rows_by_stage"] == {"unknown": 1}


def test_malformed_optional_stage_and_fact_fields_stay_unknown():
    row = draft("invented-malformed", GOOD, status={},
                review_context={"two_bot": {"bundle": {"current_facts": 7}}})
    summary, _, sheet = oc.build_report([oc.parse_export("s.json", json.dumps([row]).encode())])
    assert summary["stages"]["status"] == {"unknown": 1}
    assert summary["stages"]["publication"] == {"unknown": 1}
    assert "no retained source facts" in sheet


def test_cli_count_summary_agrees_without_printing_private_text(tmp_path, capsys):
    path = tmp_path / "invented.json"
    path.write_text(json.dumps({"drafts": [draft("invented-one", GOOD)],
                                "suppressions": [{"id": "invented-row", "stage": "fact_check"}]}))
    out = tmp_path / "result"
    assert cli.main(["--input", str(path), "--input", str(path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert GOOD not in printed
    value = json.loads(printed)
    saved = json.loads((out / "report.json").read_bytes())
    assert value["retained_suppression_rows_by_stage"] == saved["retained_suppressions"]["stage_counts"] == {"fact_check": 1}


@pytest.mark.parametrize("numbers", [("9007199254740992.0", "9007199254740993.0"), ("1e-1000", "0.0")])
def test_distinct_numeric_claims_are_conflicts_not_rounded_duplicates(numbers):
    inputs = [oc.parse_export(f"{i}.json", ('{"drafts":[{"id":"same","text":"Invented",'
        '"value":'+number+'}],"suppressions":[{"id":"same-row","stage":"critic","value":'+number+'}]}').encode())
        for i, number in enumerate(numbers)]
    for ordered in (inputs, inputs[::-1]):
        result = oc.build_report(ordered)[0]
        assert result["identities"]["conflicting_held_and_excluded"] == 1
        assert result["retained_suppressions"]["conflicting_ids_held"] == 1
        assert result["retained_suppressions"]["stage_counts"] == {}


def test_equal_exact_numeric_values_and_user_numeric_lookalikes_remain_distinct():
    equal = [oc.parse_export(str(i), ('{"drafts":[],"suppressions":[{"id":"n","value":'+n+'}]}').encode())
             for i, n in enumerate(("1000", "1e3", "1000.0"))]
    result = oc.build_report(equal)[0]["retained_suppressions"]
    assert result["identified_rows_included"] == 1 and result["conflicting_ids_held"] == 0
    numeric = oc.parse_export("n", b'{"drafts":[],"suppressions":[{"id":"n","value":1.2}]}')
    lookalike = oc.parse_export("fake", b'{"drafts":[],"suppressions":[{"id":"n","value":["number",0,"12",-1]}]}')
    assert oc.build_report([numeric, lookalike])[0]["retained_suppressions"]["conflicting_ids_held"] == 1


@pytest.mark.parametrize("outcome,tweet_id", [("not_sent", "123456"), ("invented-bad", "123456"),
                                             ("confirmed", "placeholder"), (None, True)])
def test_invalid_or_contradictory_posted_receipts_stay_unknown(outcome, tweet_id):
    row = draft("invented-posted", GOOD, status="posted", tweet_id=tweet_id, publish_outcome=outcome)
    assert oc.stages(row)["publication"] == "unknown"


def test_private_text_cannot_enter_summary_json_through_untrusted_labels():
    row = draft("invented-labels", GOOD, type=GOOD,
                review_context={"two_bot": {"bundle": {"raw_signal_dump": {
                    "evidence": {"evidence_type": GOOD}}}}})
    summary, md, sheet = oc.build_report([oc.parse_export("s.json", json.dumps([row]).encode())])
    assert GOOD not in json.dumps(summary) and GOOD not in md and GOOD in sheet
    assert summary["drafts"][0]["kind"] == "unknown"
    assert summary["drafts"][0]["evidence_type"] == "unknown"


@pytest.mark.parametrize("fields", [{"candidates": "malformed"}, {"writer_observations": "bad"},
    {"review_context": {"two_bot": {"accepted_writer_observation": {"text_sha256": "bad"}}}}])
def test_malformed_writer_records_do_not_establish_generation_or_comparison(fields):
    result = oc.stages(draft("invented-writer", GOOD, **fields))
    assert result["generation"] == "unknown"
    assert result["writer_to_saved"] == "unjoined"


def test_stdout_distinguishes_missing_suppression_history_from_empty(tmp_path, capsys):
    results = []
    for i, payload in enumerate(({"drafts": []}, {"drafts": [], "suppressions": []})):
        path = tmp_path / f"{i}.json"
        path.write_text(json.dumps(payload))
        assert cli.main(["--input", str(path), "--out", str(tmp_path / f"out-{i}")]) == 0
        results.append(json.loads(capsys.readouterr().out))
    assert results[0] != results[1]
    assert results[0]["suppression_history"]["exports_without_history"] == 1
    assert results[1]["suppression_history"]["exports_without_history"] == 0


@pytest.mark.parametrize("text", ["", "https://example.invalid/only-link"])
def test_zero_body_sentences_have_their_own_histogram_bin(text):
    result = oc.build_report([oc.parse_export("s.json", json.dumps([draft("empty", text)]).encode())])[0]
    assert result["sentences"] == {"0": 1}


@pytest.mark.parametrize("exponent", ["99999999999999999999999", "-99999999999999999999999"])
def test_decimal_exponent_outside_runtime_range_is_a_bounded_cli_refusal(tmp_path, capsys, exponent):
    source = tmp_path / "huge-exponent.json"
    source.write_text('{"drafts":[],"value":1e'+exponent+'}')
    out = tmp_path / "output"
    assert cli.main(["--input", str(source), "--out", str(out)]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "input_non_finite_number"}
    assert not out.exists()
