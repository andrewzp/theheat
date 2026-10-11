"""Real dashboard edits retain Python source identity across the Gist boundary."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from src.dashboard_preview.errors import PreviewError
from src.editorial.revisions import decision_revision, draft_identity
from tests.dashboard_graphic_helpers import POLICY, RUNTIME, saved_pm25_preview, saved_preview
from tests.test_dashboard_graphic_preview import preview


@pytest.mark.parametrize("invalid_source", [False, True], ids=["qualified", "already-invalid"])
def test_actual_dashboard_save_keeps_source_hashes_and_untouched_hazard(tmp_path, invalid_source):
    root = Path(__file__).resolve().parents[1]
    state, _ = saved_pm25_preview()
    fire, _ = saved_preview()
    state["drafts"].extend(fire["drafts"])
    aq = state["drafts"][0]
    if invalid_source:
        aq["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["forecast_window"]["series"]["dust"]["values"][0] += 1
    aq["review_context"]["two_bot"]["fact_check"] = {"passed": True}
    aq["review_context"]["two_bot"]["critic"] = {"passed": True}
    aq["approval_binding"] = {"retained": "invented obsolete approval"}
    before = deepcopy(state)
    (tmp_path / "state.json").write_text(json.dumps(state, ensure_ascii=False, allow_nan=False))
    code = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import {pathToFileURL} from 'node:url';
net.Socket.prototype.connect = () => { throw new Error('No sockets in invented save fixture') };
const [root, temp] = process.argv.slice(1);
const {POST} = await import(pathToFileURL(root + '/dashboard/app/api/drafts/route.js'));
const {writeStateStore} = await import(pathToFileURL(root + '/dashboard/lib/state-store.js'));
const {draftIdentity,decisionRevision} = await import(pathToFileURL(root + '/dashboard/lib/draft-revisions.js'));
const {runtimeRun} = await import(pathToFileURL(root + '/dashboard/tests/helpers/review-policy.js'));
let content = fs.readFileSync(temp + '/state.json', 'utf8');
content = content.slice(0,-1) + ',\"run_history\":' + JSON.stringify([runtimeRun(new Date().toISOString())]) + '}';
let writes = 0;
globalThis.fetch = async (url, options={}) => {
  assert.equal(url,'https://api.github.com/gists/invented-source-roundtrip');
  if (!options.method || options.method === 'GET') return Response.json({files:{'state.json':{content}}});
  assert.equal(options.method,'PATCH');
  content = JSON.parse(options.body).files['state.json'].content;
  writes++;
  return Response.json({});
};
for (const editedText of ['Invented forecast edited once.', 'Invented forecast edited twice.']) {
  const row = JSON.parse(content).drafts.find(d => d.id === 'invented-pm25');
  const response = await POST(new Request('http://localhost/api/drafts',{
    method:'POST',headers:{'Content-Type':'application/json',Authorization:'Basic '+Buffer.from('invented:fixture').toString('base64')},
    body:JSON.stringify({action:'edit',draftId:row.id,editedText,expectedRevision:{...draftIdentity(row),decision_revision:decisionRevision(row)}})
  }));
  const payload = await response.json();
  assert.equal(response.status,200,JSON.stringify(payload));
  assert.equal(payload.draft.review_status,'needs_revalidation');
  assert.equal(payload.draft.approval_binding,undefined);
  assert.equal(payload.draft.review_context.two_bot.fact_check,undefined);
  assert.equal(payload.draft.review_context.two_bot.critic,undefined);
  assert.equal(payload.draft.text,editedText);
}
await writeStateStore({errors:[{msg:'Invented unrelated save'}]});
assert.equal(writes,3);
fs.writeFileSync(temp+'/saved.json',content);
'''
    env = {"PATH": os.environ["PATH"], "THEHEAT_STATE_BACKEND": "gist",
           "GIST_ID": "invented-source-roundtrip", "NODE_ENV": "production",
           "DASHBOARD_USERNAME": "invented", "DASHBOARD_PASSWORD": "fixture"}
    process = subprocess.run(["node", "--input-type=module", "-e", code, str(root), str(tmp_path)],
                   env=env, check=False, capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr
    saved = json.loads((tmp_path / "saved.json").read_text())
    def canonical(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    for original in before["drafts"]:
        row = next(d for d in saved["drafts"] if d["id"] == original["id"])
        bundle = row["review_context"]["two_bot"]["bundle"]
        assert canonical(bundle) == canonical(original["review_context"]["two_bot"]["bundle"])
        request = {"draft_id": row["id"],
                   "expected_revision": {**draft_identity(row), "decision_revision": decision_revision(row)},
                   "expected_policy_source_sha256": POLICY, "expected_preview_runtime_sha256": RUNTIME}
        if original["id"] == "invented-fire":
            assert canonical(row) == canonical(original)
            assert json.loads(preview(saved, request))["source_context"]["kind"] == "modis_acquisition"
        else:
            assert row["content_revision"] == 2 and row["decision_revision"] == 2
            for history in row["revision_history"]:
                assert canonical(history["review_context"]["two_bot"]["bundle"]) == canonical(bundle)
            if invalid_source:
                with pytest.raises(PreviewError) as error:
                    preview(saved, request)
                assert error.value.code == "graphic_unavailable"
            else:
                response = json.loads(preview(saved, request))
                assert response["source_context"]["kind"] == "pm25_forecast_day"
                assert response["attachment"] is False and response["publication_approved"] is False
