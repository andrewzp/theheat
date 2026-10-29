// The actual trial proposal inserted by the actual import plan, served to the
// actual draft handlers through the invented Gist harness. No NHC/model/X request.
import { pythonJSON, withWarningGist } from "./warning-gist-harness.js"
import { runtimeRun } from "./review-policy.js"

export const NHC_NOW = "2026-10-29T21:30:00.000Z"
const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external request trapped'))\n"
const seedCode = trap + `
from tests.nhc_advisory_import_helpers import imported_state
value=json.load(sys.stdin)
state,policy=imported_state(value.get('runtime'))
print(json.dumps(dict(raw_state=json.dumps(state,ensure_ascii=False),policy=policy)))
`
export function importedAdvisory() {
  return pythonJSON(seedCode, { runtime: runtimeRun("2026-10-29T21:29:00.000Z") })
}

export async function withNhcGist(run, { seed = importedAdvisory() } = {}) {
  await withWarningGist(async t => { t.at(NHC_NOW); await run(t) }, { seed })
}
