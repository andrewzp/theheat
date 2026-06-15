import test from "node:test"
import assert from "node:assert/strict"

import {
  sourceDiagnosticClass,
  sourceDiagnosticLabel,
} from "../lib/source-diagnostic.js"

test("source diagnostics reserve red treatment for unhealthy source errors", () => {
  assert.equal(sourceDiagnosticClass("unhealthy"), "source-diagnostic-unhealthy")
  assert.equal(sourceDiagnosticClass("external"), "source-diagnostic-external")
  assert.equal(sourceDiagnosticClass("degraded"), "source-diagnostic-degraded")
  assert.equal(sourceDiagnosticClass("healthy"), "source-diagnostic-degraded")

  assert.equal(sourceDiagnosticLabel("unhealthy"), "last error")
  assert.equal(sourceDiagnosticLabel("external"), "external issue")
  assert.equal(sourceDiagnosticLabel("degraded"), "diagnostic")
})
