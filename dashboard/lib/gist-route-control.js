// P00c route control authentication (ROUTE-CONTRACT-v2, dated note 2026-11-02 b). activate_route /
// deactivate_route carry no private content, but they change who may write: they are signed by
// root with HMAC-SHA256 under THEHEAT_ROUTE_CONTROL_KEY (`<kid>:<base64 32 bytes>`), a key held only
// by root (src/commands/gist_commands.py route-command) and the consume/drain jobs (verification)
// — never by the dashboard. Every field is bound: the MAC covers the canonical command with
// `auth` reduced to {alg, kid}. Python admission checks only the shape and the configured kid.
import { createHmac, timingSafeEqual } from "node:crypto"
import { canonical } from "./local-command-recovery.js"
import { parseKeySetting } from "./gist-command-seal.js"

export const CONTROL_KEY_ENV = "THEHEAT_ROUTE_CONTROL_KEY"
export const CONTROL_ALG = "HS256"

class ControlError extends Error {
  constructor(code, status = 403) { super(code); this.code = code; this.status = status; this.statusCode = status }
}

export function controlKey(env = process.env) { return parseKeySetting(env[CONTROL_KEY_ENV] ?? "", "route_control_key_invalid") }

export function controlMac(command, kid, key) {
  const { auth: _auth, ...fields } = command
  return createHmac("sha256", key).update(canonical({ ...fields, auth: { alg: CONTROL_ALG, kid } }), "utf8").digest("base64")
}

export function signRouteControl(command, key) {
  const { auth: _auth, ...fields } = command
  return { ...fields, auth: { alg: CONTROL_ALG, kid: key.kid, mac: controlMac(fields, key.kid, key.key) } }
}

// kid differs: route_control_key_unknown (not terminal); MAC differs: route_control_invalid.
export function verifyRouteControl(command, key) {
  if (command.auth?.kid !== key.kid) throw new ControlError("route_control_key_unknown", 409)
  const expected = Buffer.from(controlMac(command, key.kid, key.key), "base64")
  const supplied = Buffer.from(String(command.auth?.mac ?? ""), "base64")
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) throw new ControlError("route_control_invalid", 403)
  return true
}
