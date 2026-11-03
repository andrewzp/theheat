"""ROUTE repair B.5 (+ B.1 retry) through REAL processes: independently started dashboard clients
(real handlers, sealing with an invented test key), the REAL Python admission CLI (no key), the REAL
inbox fetch and the REAL Node consumer CLI with a job summary. Private draft text and feedback notes
must appear in no dispatch input, admitted artifact, fetched inbox file, consumer stdout/stderr,
report, job summary or result file. Also Python/Node agreement on the sealed envelope bytes.

OFFLINE FIXTURES, explicitly (file-backed Gist, file dispatch queue, invented data).
Red baselines: receipts/red-b5-plaintext-artifacts-v2.txt, receipts/red-b1-unauthorized-domain-operations.txt.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from scripts import gist_command_inbox as inbox
from src.commands import gist_commands
from tests.real_closure import route_harness as h

ROOT = Path(__file__).resolve().parents[2]
TEXT = "PRIVATE unpublished edit: Invented City 1 reached 41 degrees."
NOTE = "PRIVATE operator note about the tone"


def _seed(root: Path) -> dict:
    seed = h.fixture_state(2)
    h.seed_gist(root, h.STATE_GIST, {"state.json": json.dumps(seed["state"]), "gist-write-route.json": h.route_record()})
    h.seed_gist(root, h.FEEDBACK_GIST, {})
    return seed


def _files_under(path: Path) -> dict[str, str]:
    return {str(p.relative_to(path)): p.read_text(errors="replace") for p in path.rglob("*") if p.is_file()}


def test_private_content_reaches_no_public_or_operator_surface_and_still_applies(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    state = h.gist_state(root)
    second = state["drafts"][1]
    edit = h.finish(h.start_client("app/api/drafts/route.js", {
        "action": "edit", "draftId": "draft_route_1", "expectedRevision": seed["identities"]["draft_route_1"], "editedText": TEXT},
        h.client_env(root, route="serialized")))
    target = {"draft_id": second["id"], "status": "pending", "tweet_id": None, "content_revision": seed["identities"][second["id"]]["content_revision"],
              "text_sha256": seed["identities"][second["id"]]["text_sha256"],
              "evidence_sha256": seed["identities"][second["id"]]["evidence_sha256"], "graphic_sha256": None}
    feedback = h.finish(h.start_client("app/api/post-feedback/route.js", {
        "request_id": "51111111-2222-4333-8444-555555555555", "target": target, "subject": "copy", "tags": ["useful"], "note": NOTE},
        h.client_env(root, route="serialized")))
    assert (edit["status"], feedback["status"]) == (202, 202), (edit, feedback)
    secrets = [TEXT, NOTE, "41 degrees", "the tone"]
    dispatched = json.dumps(h.dispatches(root))
    assert not any(secret in dispatched for secret in secrets), "workflow_dispatch inputs carry ciphertext only"
    # REAL admission CLI (it never holds the key), then the artifact store and the REAL inbox fetch.
    results = h.admit_all(root)
    assert [r["admitted"] for r in results] == [True, True]
    admitted = _files_under(root / "inbox")
    assert sorted(Path(name).name for name in admitted) == ["admission.json", "admission.json", "command.json", "command.json"]
    assert not any(secret in content for content in admitted.values() for secret in secrets)
    summary = root / "summary.md"
    env = h.consumer_env(root, run_id="4001", GITHUB_STEP_SUMMARY=str(summary))
    process = h.start_consumer(root, env, root / "report.json")
    out, err = process.communicate(timeout=120)
    assert process.returncode == 0, (out, err)
    report_text = (root / "report.json").read_text()
    report = json.loads(report_text)
    assert len(report["applied"]) == 2, report
    for surface in (out, err, report_text, summary.read_text(), json.dumps(h.gist_files(root).get("gist-command-results.json")),
                    json.dumps(h.gist_files(root, h.FEEDBACK_GIST).get("gist-command-results.json"))):
        assert not any(secret in surface for secret in secrets), surface[:300]
    assert next(d for d in h.gist_state(root)["drafts"] if d["id"] == "draft_route_1")["text"] == TEXT, "applied to the secret Gist only"
    stored = h.gist_files(root, h.FEEDBACK_GIST)
    assert any(NOTE in content for name, content in stored.items() if name.startswith("editorial-feedback-")), "the note lands only in its feedback record"


def test_python_admission_and_node_agree_on_sealed_bytes_and_refusals(tmp_path):
    script = ("import('./lib/gist-route-submit.js').then(m => { const route = {schema_version: 1, mode: 'serialized', generation: 1,"
              " changed_at: '2026-10-30T12:00:00Z', changed_by_run: '1:consume', command_id: process.argv[1]};"
              " const built = m.buildSealedCommand({action: 'post_feedback', operation: 'post_feedback', producerKind: 'post_feedback',"
              " actorSubject: 'dashboard-operator', route, payload: {input_json: JSON.stringify({note: 'ü'})}});"
              " process.stdout.write(JSON.stringify(built)) })")
    env = h.base_env() | {"THEHEAT_GIST_WRITE_ROUTE": "serialized", "THEHEAT_COMMAND_SEAL_KEY": h.TEST_SEAL_KEY}
    node = subprocess.run([h.NODE, "-e", script, h.ACTIVATION], cwd=h.DASHBOARD, env=env, capture_output=True, text=True, check=True)
    built = json.loads(node.stdout)
    raw = built["raw"]
    assert raw.isascii() and "ü" not in raw and "note" not in raw
    parsed = gist_commands.parse_command(raw, now=datetime.now(UTC), seal_kid="k-test")
    assert parsed["digest"] == built["digest"] == hashlib.sha256(raw.encode()).hexdigest()
    envelope = json.loads(raw)
    tampered = {**envelope, "seal": {**envelope["seal"], "iv": "AAAA"}}
    canonical = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    done = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "admit", "--out", str(tmp_path / "out")], cwd=ROOT,
                          env=h.base_env() | {"THEHEAT_COMMAND_INPUT": canonical}, capture_output=True, text=True, check=True)
    assert json.loads(done.stdout) == {"admitted": False, "code": "invalid_envelope", "command_id": envelope["command_id"]}
    check = subprocess.run([h.NODE, "-e", "import('./lib/gist-command-seal.js').then(m => { try { m.parseEnvelope(process.argv[1]); process.stdout.write('ok') }"
                            " catch (e) { process.stdout.write(e.code) } })", canonical], cwd=h.DASHBOARD, env=h.base_env(), capture_output=True, text=True, check=True)
    assert check.stdout == "invalid_envelope"


def test_inbox_extracts_only_the_envelope_and_receipt(tmp_path):
    command = json.dumps({"seal": {"ciphertext": "AAAA"}})
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("command.json", command)
        archive.writestr("admission.json", json.dumps({"command_id": "61111111-2222-4333-8444-555555555555"}))
    artifact = {"id": 5, "name": "theheat-command-61111111-2222-4333-8444-555555555555", "expired": False}
    target = inbox.extract(artifact, blob.getvalue(), tmp_path)
    assert sorted(p.name for p in target.iterdir()) == ["admission.json", "command.json"]
