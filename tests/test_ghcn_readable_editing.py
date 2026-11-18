"""Actual Python/JS bindings and lossless Gist edits, with invented source trees."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.editorial import revisions
from src.editorial.policy import current_editorial_policy
from src.two_bot.ghcn_readable_warrant import decode_wire, encode_full
from tests.test_ghcn_publication_observation_set import paired_variants as paired_variants

JS = r"""
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { parseGistDocument, stringifyGistDocument, assertGistEvidenceUnchanged } from "./dashboard/lib/lossless-gist.js"
import { draftIdentity, recordHumanReview, authorizeDraft, approvalIsCurrent, reviewIsCurrent, invalidateText } from "./dashboard/lib/draft-revisions.js"
const { draft, policy, mutations } = JSON.parse(readFileSync(0, "utf8"))
const original = structuredClone(draft)
assert.deepEqual(draftIdentity(draft), original.expected_identity)
delete draft.expected_identity
recordHumanReview(draft, policy)
authorizeDraft(draft, "manual", "invented-js-intent", null, policy)
assert.ok(approvalIsCurrent(draft, "manual", policy))
for (const altered of mutations) {
  const bad = structuredClone(draft)
  bad.review_context.two_bot.bundle = altered
  assert.equal(reviewIsCurrent(bad, policy), false)
  assert.equal(approvalIsCurrent(bad, "manual", policy), false)
}
// Every float lexeme in the actual Python warrant must survive the real
// lossless store serializer, including baseline cells committed by its SHA.
const raw = readFileSync(process.argv[1], "utf8")
const document = parseGistDocument(raw), state = structuredClone(document.value)
invalidateText(state.drafts[0], "An invented text edit needing fresh checks.")
assertGistEvidenceUnchanged(document, state.drafts)
const saved = stringifyGistDocument(state, document)
process.stdout.write(saved)
"""


@pytest.mark.parametrize(
    "key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar_date")]
)
def test_real_text_edit_preserves_python_wire_and_all_float_lexemes(tmp_path, paired_variants, key):
    node = shutil.which("node")
    assert node, "The documented Node path is required; do not silently skip edit acceptance"
    draft = deepcopy(paired_variants[key])
    wire = encode_full(draft["review_context"]["two_bot"]["bundle"])
    draft["review_context"]["two_bot"]["bundle"] = wire
    revisions.initialize_revision(draft)
    revisions.record_human_review(draft)
    revisions.authorize_draft(draft, "manual", "invented-python-intent")
    assert revisions.approval_is_current(draft, "manual")
    mutations = []
    for kind in ("years", "samples", "date", "value", "alias", "revision", "observation"):
        altered = deepcopy(wire)
        baseline = altered["raw_signal_dump"]["evidence"]["baseline"]
        row = baseline["calendar_table"]["rows"][0]
        if kind == "years":
            row[1] += 1
        elif kind == "samples":
            row[2] += 1
        elif kind == "date":
            row[3] = str(int(row[3][:4]) + 1) + row[3][4:]
        elif kind == "value":
            row[4] += 1
        elif kind == "alias":
            altered["historical_context"]["baseline"]["full_baseline_sha256"] = "0" * 64
        elif kind == "revision":
            baseline["revision_id"] = "0" * 64
        else:
            altered["raw_signal_dump"]["evidence"]["variables"]["TMIN"]["value_c"] -= 1
        bad = deepcopy(draft)
        bad["review_context"]["two_bot"]["bundle"] = altered
        assert revisions.fingerprint(altered) != revisions.fingerprint(wire), kind
        assert not revisions.review_is_current(bad) and not revisions.approval_is_current(bad), kind
        mutations.append(altered)
    raw = json.dumps({"drafts": [draft]}, ensure_ascii=False)
    path = tmp_path / "invented-state.json"
    path.write_text(raw)
    message = dict(
        draft={**draft, "expected_identity": revisions.draft_identity(draft)},
        policy=current_editorial_policy(),
        mutations=mutations,
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", JS, str(path)],
        cwd=Path(__file__).resolve().parents[1],
        input=json.dumps(message),
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    edited = json.loads(result.stdout)["drafts"][0]
    saved = edited["review_context"]["two_bot"]["bundle"]
    assert json.dumps(saved, sort_keys=True, separators=(",", ":")) == json.dumps(
        wire, sort_keys=True, separators=(",", ":")
    )
    assert decode_wire(saved) == decode_wire(wire)
    assert not revisions.review_is_current(edited) and not revisions.approval_is_current(edited)
    assert edited["text"] != draft["text"]
