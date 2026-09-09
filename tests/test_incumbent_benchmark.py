"""Evidence classification and immutable baseline integrity, with synthetic copy."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from src.evaluation import incumbent


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    source = {"drafts": [], "publish_ledger": {}, "memory": {"shipped_tweets": []}}
    rows = []
    for index, evidence in enumerate(sorted(incumbent.PUBLICATION_CLASSES), 1):
        receipt = evidence == "x_receipt"
        rows.append({
            "audit_id": f"T{index:02d}", "text": f"Synthetic copy {index}: 35°C.\n",
            "event_id": f"event_{index}", "posted_at": "2026-07-01T12:00:00Z",
            "publication_evidence": evidence, "tweet_id": "123456" if receipt else None,
            "url": "https://x.com/i/status/123456" if receipt else "",
            "live_x_check": "individual_post" if receipt else "not_checked",
            "public_views_2026_09_08": 12 if receipt else None,
        })
        if evidence == "generation_memory_only_publication_unverified":
            source["memory"]["shipped_tweets"].append({
                "event_id": f"event_{index}", "tweet_text": rows[-1]["text"],
                "shipped_at": rows[-1]["posted_at"],
            })
            rows[-1]["posted_at"] = None
        else:
            source["drafts"].append({"event_id": f"event_{index}", "text": rows[-1]["text"],
                                     "status": "posted", "posted_at": rows[-1]["posted_at"]})
        if receipt:
            source["publish_ledger"][f"event_{index}"] = {"tweet_id": "123456"}
    snapshot = encoded(source)
    for row in rows:
        row["source_snapshot_sha256"] = hashlib.sha256(snapshot).hexdigest()
    labels = {"schema_version": 1, "cases": [{
        "case_id": "synthetic_forecast", "audit_ids": ["T01"],
        "verdict": "confirmed_specific_defect", "finding": "Wrong evidence class.",
        "evidence_limit": "No observed maximum recovered.",
        "expected_rejection": "Forecast does not prove observation.",
        "permitted_claim": "Attributed forecast.",
    }]}
    paths = {}
    for name, data in {"corpus": encoded(rows), "snapshot": snapshot, "cases": encoded(labels)}.items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_bytes(data)
    monkeypatch.setattr(incumbent, "_source_files", lambda *_: {
        "incumbent/src/prompt.py": b'PROMPT = "Original, not current"\n',
    })
    return {"repository": tmp_path, "revision": "a" * 40, **paths,
            "evidence": {}, "output": tmp_path / "frozen"}


def test_freeze_preserves_exact_bytes_and_evidence_denominators(inputs):
    result = incumbent.freeze(**inputs)
    summary = result["corpus_summary"]
    assert summary["texts"] == 3
    assert summary["publication_classes"] == {name: 1 for name in incumbent.PUBLICATION_CLASSES}
    assert summary["live_corroborated"] == summary["selected_public_view_samples"] == 1
    assert (inputs["output"] / "corpus.json").read_bytes() == inputs["corpus"].read_bytes()
    assert incumbent.verify(inputs["output"], result["manifest_sha256"])["verified"] is True
    manifest = json.loads((inputs["output"] / "manifest.json").read_text())
    assert manifest["readiness"]["editor_ranked_slate"] == "not_yet_reviewed_by_editor"
    assert manifest["readiness"]["independent_reference_events"] == "not_yet_assembled"
    assert (inputs["output"].stat().st_mode & 0o777) == 0o700


def test_existing_baseline_is_never_overwritten(inputs):
    result = incumbent.freeze(**inputs)
    inputs["corpus"].write_text("changed")
    with pytest.raises(FileExistsError):
        incumbent.freeze(**inputs)
    assert incumbent.verify(inputs["output"], result["manifest_sha256"])["verified"]


@pytest.mark.parametrize("mutation", ["file", "manifest", "missing", "extra", "symlink"])
def test_verifier_detects_tampering_and_incomplete_packages(inputs, mutation):
    result = incumbent.freeze(**inputs)
    output = inputs["output"]
    if mutation == "file":
        (output / "corpus.json").write_text("[]")
    elif mutation == "manifest":
        (output / "manifest.json").write_text("{}")
    elif mutation == "missing":
        (output / "scientific-cases.json").unlink()
    elif mutation == "extra":
        (output / "not-in-manifest").write_text("extra")
    else:
        (output / "link").symlink_to(inputs["corpus"])
    with pytest.raises(ValueError):
        incumbent.verify(output, result["manifest_sha256"])


@pytest.mark.parametrize("change", [
    {"tweet_id": "123"}, {"url": "https://x.com/i/status/123"},
    {"publication_evidence": "published"}, {"source_snapshot_sha256": "b" * 64},
    {"live_x_check": "profile_timeline"}, {"public_views_2026_09_08": 0},
])
def test_generation_memory_cannot_gain_publication_or_metrics(inputs, change):
    rows = json.loads(inputs["corpus"].read_text())
    rows[0].update(change)
    with pytest.raises(ValueError):
        incumbent.validate_corpus(encoded(rows), inputs["snapshot"].read_bytes())


@pytest.mark.parametrize("bad_id", [None, 123, "not-a-receipt", ""])
def test_receipt_class_requires_real_retained_id(inputs, bad_id):
    rows = json.loads(inputs["corpus"].read_text())
    rows[-1]["tweet_id"] = bad_id
    with pytest.raises(ValueError):
        incumbent.validate_corpus(encoded(rows), inputs["snapshot"].read_bytes())


@pytest.mark.parametrize("mutation", ["duplicate_id", "duplicate_text", "nan", "duplicate_key"])
def test_ambiguous_corpus_fails_before_any_artifact_creation(inputs, mutation):
    rows = json.loads(inputs["corpus"].read_text())
    if mutation == "duplicate_id":
        rows[1]["audit_id"] = rows[0]["audit_id"]
    elif mutation == "duplicate_text":
        rows[1]["text"] = rows[0]["text"]
    data = encoded(rows)
    if mutation == "nan":
        data = data.replace(b'"public_views_2026_09_08": null', b'"public_views_2026_09_08": NaN')
    elif mutation == "duplicate_key":
        data = data.replace(b'"audit_id": "T01"', b'"audit_id": "T01", "audit_id": "T04"')
    inputs["corpus"].write_bytes(data)
    with pytest.raises(ValueError):
        incumbent.freeze(**inputs)
    assert not inputs["output"].exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "x/../../escape", "x\\escape", "x//y"])
def test_evidence_paths_cannot_escape_the_package(inputs, name):
    inputs["evidence"] = {name: inputs["corpus"]}
    with pytest.raises(ValueError):
        incumbent.freeze(**inputs)
    assert not inputs["output"].exists()


def test_case_must_join_original_text_and_retain_uncertainty(inputs):
    labels = json.loads(inputs["cases"].read_text())
    for change in ({"audit_ids": ["T99"]}, {"evidence_limit": ""}, {"verdict": "probably_true"}):
        changed = deepcopy(labels)
        changed["cases"][0].update(change)
        with pytest.raises(ValueError):
            incumbent.validate_cases(encoded(changed), inputs["corpus"].read_bytes())


def test_receipt_url_cannot_point_to_a_different_post(inputs):
    rows = json.loads(inputs["corpus"].read_text())
    rows[-1]["url"] = "https://x.com/i/status/999999"
    with pytest.raises(ValueError, match="URL"):
        incumbent.validate_corpus(encoded(rows), inputs["snapshot"].read_bytes())


@pytest.mark.parametrize("change", [
    {"text": "Invented exact text"}, {"event_id": "unrelated_event"},
    {"tweet_id": "999999", "url": "https://x.com/i/status/999999"},
    {"posted_at": "2026-07-02T12:00:00Z"},
])
def test_hash_match_cannot_legitimize_invented_source_claims(inputs, change):
    rows = json.loads(inputs["corpus"].read_text())
    rows[-1].update(change)
    with pytest.raises(ValueError, match="join original source"):
        incumbent.validate_corpus(encoded(rows), inputs["snapshot"].read_bytes())


@pytest.mark.parametrize("change", ["empty", "approved", "receipt_removed"])
def test_original_source_must_establish_publication(inputs, change):
    rows = json.loads(inputs["corpus"].read_text())
    source = json.loads(inputs["snapshot"].read_text())
    if change == "empty":
        source = {"drafts": [], "publish_ledger": {}, "memory": {"shipped_tweets": []}}
    elif change == "approved":
        source["drafts"][-1]["status"] = "approved"
    else:
        source["publish_ledger"] = {}
    snapshot = encoded(source)
    for row in rows:
        row["source_snapshot_sha256"] = hashlib.sha256(snapshot).hexdigest()
    with pytest.raises(ValueError, match="join original source"):
        incumbent.validate_corpus(encoded(rows), snapshot)


@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("document", ["corpus", "snapshot", "cases"])
def test_nonfinite_values_fail_in_every_input_document(inputs, number, document):
    data = inputs[document].read_bytes()
    # Add an otherwise unused measurement; validation must inspect all JSON.
    data = data.replace(b"{", b'{"unused_measurement":' + number.encode() + b",", 1)
    inputs[document].write_bytes(data)
    with pytest.raises(ValueError, match="Non-finite"):
        incumbent.freeze(**inputs)


def test_generation_time_cannot_become_publication_time(inputs):
    rows = json.loads(inputs["corpus"].read_text())
    rows[0]["posted_at"] = "2026-07-01T12:00:00Z"
    with pytest.raises(ValueError, match="Timestamp"):
        incumbent.validate_corpus(encoded(rows), inputs["snapshot"].read_bytes())


def test_git_snapshot_uses_named_commit_not_dirty_worktree(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True).stdout

    git("init", "--quiet")
    (tmp_path / "src").mkdir()
    prompt = tmp_path / "src" / "prompt.py"
    prompt.write_bytes(b"original prompt\n")
    git("add", "src")
    git("-c", "user.name=Offline fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "incumbent")
    revision = git("rev-parse", "HEAD").decode().strip()
    prompt.write_bytes(b"uncommitted improvement\n")
    assert incumbent._source_files(tmp_path, revision) == {"incumbent/src/prompt.py": b"original prompt\n"}
    with pytest.raises(ValueError):
        incumbent._source_files(tmp_path, "HEAD")
