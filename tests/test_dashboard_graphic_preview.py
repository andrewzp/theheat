from copy import deepcopy
import hashlib
import json

import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from tests.dashboard_graphic_helpers import POLICY, RUNTIME, saved_preview


def test_actual_python_binding_is_accepted_by_browser_contract(tmp_path):
    """Catch cross-language identity drift that an invented JSON response misses."""
    from pathlib import Path
    import subprocess
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "dashboard/lib/graphic-runtime-manifest.json").read_text())
    state, request = saved_preview()
    policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
    request.update(expected_policy_source_sha256=policy, expected_preview_runtime_sha256=runtime)
    body = preview(state, request, policy_sha=policy, runtime_sha=runtime)
    (tmp_path / "response.json").write_bytes(body)
    (tmp_path / "request.json").write_text(json.dumps(request))
    code = '''
import fs from 'node:fs'; import {pathToFileURL} from 'node:url';
const [root, temp] = process.argv.slice(1);
const {validateGraphicResponse} = await import(pathToFileURL(root + '/dashboard/lib/graphic-preview.js'));
const read = path => JSON.parse(fs.readFileSync(path));
await validateGraphicResponse(read(temp + '/response.json'), read(temp + '/request.json'),
 read(root + '/dashboard/lib/graphic-runtime-manifest.json'));
'''
    subprocess.run(["node", "--input-type=module", "-e", code, str(root), str(tmp_path)],
                   check=True, timeout=15, capture_output=True, text=True)


def preview(state, request, **changes):
    return build_preview(request, **{"policy_sha": POLICY, "runtime_sha": RUNTIME,
                                    "read_state": lambda: state, "budget": Budget(),
                                    "synthetic": True, **changes})


def test_real_graphic_preserves_complete_state_and_binds_exact_saved_revision():
    state, request = saved_preview()
    before = deepcopy(state)
    reads = []
    def read():
        reads.append(True)
        return state
    body = preview(state, request, read_state=read)
    result = json.loads(body)
    assert state == before and len(reads) == 2
    assert result["revision_identity"] == request["expected_revision"]
    assert result["svg_sha256"] == hashlib.sha256(result["svg_utf8"].encode()).hexdigest()
    assert result["publication_approved"] is False and result["attachment"] is False
    assert result["preview_runtime_sha256"] == RUNTIME
    assert "SYNTHETIC" in result["alt_text"] and "simultaneity" in result["alt_text"]
    assert result["source_time"] == "2032-02-29T23:59:00Z" and len(body) <= 1024 * 1024
    assert "raw_signal_dump" not in result and "drafts" not in result


@pytest.mark.parametrize("field", ["text", "decision_revision", "status", "revision_conflicts"])
def test_change_during_render_discards_asset(field):
    state, request = saved_preview()
    changed = deepcopy(state)
    changed["drafts"][0][field] = {"text": "Changed", "decision_revision": 1,
                                  "status": "approved", "revision_conflicts": ["conflict"]}[field]
    reads = iter([state, changed])
    with pytest.raises(PreviewError) as error:
        preview(state, request, read_state=lambda: next(reads))
    assert error.value.code in {"stale_preview", "conflicted_draft"}


@pytest.mark.parametrize("change,code", [
    ("duplicate", "draft_unavailable"), ("posted", "draft_unavailable"),
    ("missing", "draft_unavailable"), ("conflict", "conflicted_draft"),
    ("source", "graphic_unavailable"), ("related", "graphic_unavailable"),
    ("bundle_size", "graphic_unavailable"),
])
def test_saved_state_failure_never_renders(monkeypatch, change, code):
    state, request = saved_preview()
    draft = state["drafts"][0]
    if change == "duplicate":
        state["drafts"].append(deepcopy(draft))
    elif change == "missing":
        state["drafts"] = []
    elif change == "posted":
        draft["status"] = "posted"
    elif change == "conflict":
        draft["revision_conflicts"] = ["conflict"]
    else:
        bundle = draft["review_context"]["two_bot"]["bundle"]
        if change == "source":
            del bundle["raw_signal_dump"]["acquisition_provenance"]
        elif change == "related":
            bundle["related_signals"][0]["acquisition_evidence"] = None
        else:
            bundle["oversize"] = "x" * 1_000_001
        from src.editorial.revisions import draft_identity
        request["expected_revision"].update(draft_identity(draft))
    monkeypatch.setattr("src.dashboard_preview.preview.render_svg", lambda **_: pytest.fail("ineligible render"))
    with pytest.raises(PreviewError) as error:
        preview(state, request)
    assert error.value.code == code


@pytest.mark.parametrize("field,value", [
    ("draft_id", ""), ("expected_revision", {}), ("extra", "supplied source"),
    ("expected_policy_source_sha256", "c" * 64), ("expected_preview_runtime_sha256", "c" * 64),
])
def test_bad_or_stale_request_never_reads_state(field, value):
    state, request = saved_preview()
    request[field] = value
    with pytest.raises(PreviewError):
        preview(state, request, read_state=lambda: pytest.fail("unexpected read"))


def test_boolean_revision_is_not_an_integer():
    state, request = saved_preview()
    request["expected_revision"]["decision_revision"] = False
    with pytest.raises(PreviewError):
        preview(state, request, read_state=lambda: pytest.fail("unexpected read"))
