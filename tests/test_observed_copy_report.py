"""Offline observed-copy report on invented exports: identity, stages, measures and file boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

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
    rows = [
        draft("joined", GOOD, review_context={"two_bot": {"accepted_writer_observation": {"text_sha256": sha},
                                                          "fact_check": {"passed": True}}}),
        draft("edited", GOOD, review_context={"two_bot": {"accepted_writer_observation": {"text_sha256": "0" * 64}}}),
        draft("posted", GOOD, status="posted", tweet_id="invented-1"),
        draft("posted-no-receipt", GOOD, status="posted"),
        {"id": "bare", "text": GOOD},
    ]
    summary, _md, _sheet = oc.build_report([oc.parse_export("s.json", json.dumps(
        {"drafts": rows, "suppressions": [{"stage": "fact_check"}, {"stage": "fact_check"}, {}]}).encode())])
    stages = summary["stages"]
    assert stages["writer_to_saved"] == {"final_differs_from_accepted_writer_output": 1,
                                         "final_equals_accepted_writer_output": 1, "unjoined": 3}
    # A draft with no recorded status is unknown, not "not published".
    assert stages["publication"] == {"not_published": 2, "recorded_receipt": 1, "status_posted_without_receipt": 1,
                                     "unknown": 1}
    assert stages["fact_check"] == {"passed": 3, "unknown": 2}
    assert stages["generation"] == {"recorded": 2, "unknown": 3}
    assert summary["generation_failures_recorded"] == {"fact_check": 2, "unknown": 1}


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
