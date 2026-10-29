import assert from "node:assert/strict"
import test from "node:test"
import { pythonJSON } from "./helpers/warning-gist-harness.js"
import { runtimeRun } from "./helpers/review-policy.js"
import { nhcAdvisoryForDisplay } from "../lib/nhc-advisory-evidence.js"
import { nhcAdvisoryValidation } from "../lib/nhc-advisory-validation.js"

test("Python-qualified CRLF advisory keeps its exact bytes and remains reviewable", () => {
  const value = pythonJSON(`
import json,sys,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external request trapped'))
from tests import nhc_advisory_helpers as h
from tests.nhc_advisory_import_helpers import imported_state
from src.editorial.nhc_advisory import validate_capture
from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle,RetainedAdvisory
seed=json.load(sys.stdin)
state,policy=imported_state(seed['runtime'])
page=h.page(h.bulletin().replace('\\n','\\r\\n'))
e=validate_capture(h.capture(page_bytes=page),h.selected(),now=h.NOW)
b=build_nhc_advisory_bundle(e)
assert RetainedAdvisory(b).identity()==e.identity()
state['drafts'][0]['review_context']['two_bot']['bundle']=b.to_dict()
print(json.dumps(state['drafts'][0]))
`, { runtime: runtimeRun("2026-10-29T21:29:00.000Z") })
  const before = structuredClone(value)
  const record = value.review_context.two_bot.bundle.raw_signal_dump.nhc_advisory
  assert.ok(record.bulletin_utf8.includes("\r\n"))
  assert.equal(nhcAdvisoryForDisplay(value).status, "present")
  assert.deepEqual(nhcAdvisoryValidation(value, Date.parse("2026-10-29T21:30:00Z")), { blocked: false })
  assert.deepEqual(value, before)
})
