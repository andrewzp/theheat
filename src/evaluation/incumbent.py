"""Freeze incumbent evidence without promoting generation memory to publications.

Packages are private local artifacts, separate from the public repository. Their
manifest digest must be retained outside the package to detect manifest tampering.
Reading source at a Git commit does not execute that source or reproduce a run.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile


PUBLICATION_CLASSES = frozenset({
    "x_receipt", "posted_state_no_receipt", "generation_memory_only_publication_unverified",
})
SOURCE_PATHS = (
    "src", "tests/voice_regression", ".github/workflows/bot.yml", "VERSION",
    "requirements.txt", "requirements-dev.txt", "pyproject.toml",
)
READINESS = {
    "incumbent_texts": "frozen_with_original_publication_classes",
    "incumbent_source": "frozen_git_source_not_a_reproduced_runtime",
    "historical_scientific_cases": "audit_labels_with_explicit_evidence_limits",
    "independent_reference_events": "not_yet_assembled",
    "editor_ranked_slate": "not_yet_reviewed_by_editor",
    "blind_writing_comparison": "not_yet_run",
    "prospective_post_age_metrics": "not_yet_captured",
}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON value: {value}")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_keys)


def _encode(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n").encode("utf-8")


def _safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or "\\" in name or ".." in path.parts
            or str(path) != name or name == "."):
        raise ValueError(f"Unsafe package path: {name!r}")
    return name


def validate_corpus(data: bytes, snapshot: bytes) -> dict:
    """Validate archive evidence classes, preserving the original bytes separately."""
    rows = _json(data)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Corpus must be a nonempty list")
    if not isinstance(_json(snapshot), dict):
        raise ValueError("Source state snapshot must be an object")
    snapshot_hash = _hash(snapshot)
    ids, receipt_ids, texts = set(), set(), set()
    counts: Counter = Counter()
    corroborated = 0
    public_view_samples = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Corpus rows must be objects")
        audit_id = row.get("audit_id")
        if not isinstance(audit_id, str) or not re.fullmatch(r"T[0-9]+", audit_id):
            raise ValueError("Invalid audit ID")
        if audit_id in ids:
            raise ValueError(f"Duplicate audit ID: {audit_id}")
        ids.add(audit_id)
        text = row.get("text")
        if not isinstance(text, str) or not text.strip() or text in texts:
            raise ValueError(f"Missing or duplicate exact text: {audit_id}")
        texts.add(text)
        evidence = row.get("publication_evidence")
        if evidence not in PUBLICATION_CLASSES:
            raise ValueError(f"Unknown publication evidence: {audit_id}")
        receipt = row.get("tweet_id")
        if evidence == "x_receipt":
            if not isinstance(receipt, str) or not re.fullmatch(r"[0-9]+", receipt):
                raise ValueError(f"Receipt-backed text has no valid ID: {audit_id}")
            if receipt in receipt_ids:
                raise ValueError(f"Duplicate receipt: {audit_id}")
            url = row.get("url")
            if not isinstance(url, str) or not re.fullmatch(
                rf"https://(?:x\.com|twitter\.com)/[A-Za-z0-9_]+/status/{receipt}", url,
            ):
                raise ValueError(f"Status URL does not match retained receipt: {audit_id}")
            receipt_ids.add(receipt)
        elif receipt not in (None, "") or row.get("url") not in (None, ""):
            raise ValueError(f"Unreceipted class contains a receipt or status URL: {audit_id}")
        if row.get("source_snapshot_sha256") != snapshot_hash:
            raise ValueError(f"Corpus snapshot hash mismatch: {audit_id}")
        check = row.get("live_x_check")
        if check not in {"not_checked", "individual_post", "profile_timeline"}:
            raise ValueError(f"Unknown public corroboration class: {audit_id}")
        if check != "not_checked":
            if evidence != "x_receipt":
                raise ValueError(f"Public corroboration needs a receipt: {audit_id}")
            corroborated += 1
        views = row.get("public_views_2026_09_08")
        if views is not None:
            if type(views) is not int or views < 0 or check != "individual_post":
                raise ValueError(f"Invalid selected public-view observation: {audit_id}")
            public_view_samples += 1
        counts[evidence] += 1
    return {
        "texts": len(rows), "publication_classes": dict(sorted(counts.items())),
        "live_corroborated": corroborated, "selected_public_view_samples": public_view_samples,
        "source_snapshot_sha256": snapshot_hash,
        "scope": "retained_texts_not_complete_account_history",
        "performance_limit": "selected_lifetime_views_not_fixed_age_or_causal_lift",
    }


def validate_cases(data: bytes, corpus: bytes) -> None:
    labels = _json(data)
    rows = {row["audit_id"]: row for row in _json(corpus)}
    if not isinstance(labels, dict) or labels.get("schema_version") != 1:
        raise ValueError("Unsupported scientific-case schema")
    cases = labels.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Scientific cases are missing")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Scientific cases must be objects")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("Missing or duplicate scientific case ID")
        seen.add(case_id)
        references = case.get("audit_ids")
        if not isinstance(references, list) or not references:
            raise ValueError(f"Case has no original text references: {case_id}")
        if any(not isinstance(ref, str) or ref not in rows for ref in references):
            raise ValueError(f"Unknown original text reference: {case_id}")
        for field in ("finding", "evidence_limit", "expected_rejection", "permitted_claim"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f"Missing {field}: {case_id}")
        if case.get("verdict") not in {
            "confirmed_specific_defect", "strong_suspicion", "unreconciled_discrepancy",
        }:
            raise ValueError(f"Unknown adjudication: {case_id}")


def _source_files(repository: Path, revision: str) -> dict[str, bytes]:
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("An immutable full Git commit ID is required")
    subprocess.run(["git", "cat-file", "-e", f"{revision}^{{commit}}"],
                   cwd=repository, check=True, capture_output=True)
    tree = subprocess.run(
        ["git", "ls-tree", "-rz", revision, "--", *SOURCE_PATHS],
        cwd=repository, check=True, capture_output=True,
    ).stdout
    files = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split()
        path = _safe_path(encoded_path.decode("utf-8"))
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Nonregular incumbent source: {path}")
        files[f"incumbent/{path}"] = subprocess.run(
            ["git", "cat-file", "blob", blob], cwd=repository,
            check=True, capture_output=True,
        ).stdout
    if not files:
        raise ValueError("No incumbent source files found")
    return files


def freeze(
    *, repository: Path, revision: str, corpus: Path, snapshot: Path, cases: Path,
    evidence: dict[str, Path], output: Path,
) -> dict:
    """Create a new package; existing packages are never updated or overwritten."""
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Already frozen; verify instead: {output}")
    corpus_data, snapshot_data, case_data = corpus.read_bytes(), snapshot.read_bytes(), cases.read_bytes()
    summary = validate_corpus(corpus_data, snapshot_data)
    validate_cases(case_data, corpus_data)
    files = _source_files(repository, revision)
    files.update({"corpus.json": corpus_data, "source-state.json": snapshot_data,
                  "scientific-cases.json": case_data})
    for name, source in evidence.items():
        files[f"evidence/{_safe_path(name)}"] = source.read_bytes()
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "incumbent_git_sha": revision,
        "corpus_summary": summary,
        "readiness": READINESS,
        "runtime_limit": "Git defaults do not prove effective historical runtime overrides.",
        "replay_limit": "Raw provider payloads and baseline products are incomplete; source is not a full replay.",
        "files": {name: {"sha256": _hash(data), "bytes": len(data)}
                  for name, data in sorted(files.items())},
    }
    manifest_data = _encode(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Lock only package creation, not bot state. This is not a Gist writer lock.
    lock = output.with_name(f".{output.name}.freeze-lock")
    with lock.open("x"):
        try:
            if output.exists() or output.is_symlink():
                raise FileExistsError(f"Already frozen: {output}")
            with tempfile.TemporaryDirectory(prefix=".freeze-", dir=output.parent) as temporary:
                staging = Path(temporary) / "package"
                staging.mkdir(mode=0o700)
                for name, data in {**files, "manifest.json": manifest_data}.items():
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    target.chmod(0o600)
                staging.rename(output)
        finally:
            lock.unlink()
    return {"manifest_sha256": _hash(manifest_data), "corpus_summary": summary,
            "files": len(files), "output": str(output.resolve())}


def verify(package: Path, manifest_sha256: str) -> dict:
    """Require an independently retained digest, and reject extra/missing files."""
    if package.is_symlink() or not package.is_dir():
        raise ValueError("Package must be a regular directory")
    paths = list(package.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Package contains a symlink")
    if any(not path.is_file() and not path.is_dir() for path in paths):
        raise ValueError("Package contains a nonregular entry")
    manifest_data = (package / "manifest.json").read_bytes()
    if _hash(manifest_data) != manifest_sha256:
        raise ValueError("Manifest digest mismatch")
    manifest = _json(manifest_data)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported manifest schema")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Manifest file index missing")
    expected = {_safe_path(name) for name in files} | {"manifest.json"}
    if expected != {path.relative_to(package).as_posix() for path in paths if path.is_file()}:
        raise ValueError("Missing or extra package files")
    for name, descriptor in files.items():
        data = (package / name).read_bytes()
        if descriptor != {"sha256": _hash(data), "bytes": len(data)}:
            raise ValueError(f"File digest or length mismatch: {name}")
    corpus = (package / "corpus.json").read_bytes()
    summary = validate_corpus(corpus, (package / "source-state.json").read_bytes())
    validate_cases((package / "scientific-cases.json").read_bytes(), corpus)
    if summary != manifest.get("corpus_summary"):
        raise ValueError("Corpus summary mismatch")
    return {"manifest_sha256": manifest_sha256, "corpus_summary": summary,
            "files": len(files), "verified": True}
