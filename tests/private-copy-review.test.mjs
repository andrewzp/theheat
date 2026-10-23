// Private copy-review form logic and static safety; INVENTED pack data only.
// Run explicitly: node --test tests/private-copy-review.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const assets = new URL("../tools/private-copy-review/", import.meta.url);
const appSource = readFileSync(new URL("app.js", assets), "utf8");
const html = readFileSync(new URL("index.html", assets), "utf8");
const css = readFileSync(new URL("styles.css", assets), "utf8");

function load() {
  const sandbox = {};
  vm.runInNewContext(appSource, sandbox, { filename: "app.js" });
  return sandbox.PrivateCopyReview;
}

const pack = {
  pack_id: "pack-0123456789abcdef", pack_sha256: "a".repeat(64),
  rubric: { id: "theheat.copy-rubric/v1", scores: {}, preference: "", length: "" }, rubric_sha256: "b".repeat(64),
  pairs: [
    { pair_id: "pair-one", pair_sha256: "c".repeat(64), sides: { A: { text: "Invented A" }, B: { text: "Invented B" } } },
    { pair_id: "pair-two", pair_sha256: "d".repeat(64), sides: { A: { text: "Invented C" }, B: { text: "Invented D" } } },
  ],
};

// Values created inside the vm context come from another realm; compare plain JSON.
const plain = (value) => JSON.parse(JSON.stringify(value));

function ready(app) {
  const state = app.emptyState(pack);
  state.raterId = "synthetic-rater-1";
  state.raterKind = "synthetic_fixture";
  state.assertion = true;
  return state;
}

function scoreAll(entry, value) {
  for (const side of ["A", "B"]) for (const metric of ["punch", "clarity", "unnecessary_words"]) entry.scores[side][metric] = value;
}

test("nothing is preselected and an empty ballot cannot be exported", () => {
  const app = load();
  const state = app.emptyState(pack);
  assert.equal(state.raterKind, null);
  assert.equal(state.assertion, false);
  for (const entry of Object.values(state.pairs)) {
    assert.equal(entry.preference, null);
    assert.deepEqual(JSON.parse(JSON.stringify(entry.scores)), { A: {}, B: {} });
  }
  const result = app.validate(ready(app), pack);
  assert.equal(result.ratings.length, 0);
  assert.match(result.errors[0].message, /Rate at least one pair/);
});

test("rater identity, kind and assertion are required and bounded", () => {
  const app = load();
  const state = ready(app);
  state.raterId = "bad id with spaces";
  state.raterKind = "model";
  state.assertion = false;
  scoreAll(state.pairs["pair-one"], 3);
  state.pairs["pair-one"].preference = "A";
  const targets = plain(app.validate(state, pack).errors).map((e) => e.target);
  assert.deepEqual(targets.slice(0, 3), ["rater-id", "rater-kind-0", "rater-assertion"]);
});

test("a preference needs all six integer scores unless it abstains", () => {
  const app = load();
  const state = ready(app);
  const entry = state.pairs["pair-one"];
  entry.preference = "B";
  entry.scores.A.punch = 4;
  entry.scores.B.clarity = "4"; // A numeric string is not a score.
  const missing = app.validate(state, pack).errors;
  assert.equal(missing.length, 5); // A.punch is the only valid integer score.
  assert.ok(missing.every((e) => e.message.includes("from 1 to 5")));
  scoreAll(entry, 6);
  assert.equal(app.validate(state, pack).errors.length, 6);
  scoreAll(entry, 4);
  const ok = app.validate(state, pack);
  assert.equal(ok.errors.length, 0);
  assert.equal(ok.ratings[0].scores.A.punch, 4);
  entry.preference = "abstain";
  scoreAll(entry, undefined);
  const abstained = app.validate(state, pack).ratings[0];
  assert.deepEqual(JSON.parse(JSON.stringify(abstained.scores)), { A: null, B: null });
});

test("unrated pairs stay unrated, but stray scores or notes must be resolved", () => {
  const app = load();
  const state = ready(app);
  state.pairs["pair-one"].preference = "tie";
  scoreAll(state.pairs["pair-one"], 2);
  assert.equal(app.validate(state, pack).ratings.length, 1);
  state.pairs["pair-two"].notes = "SYNTHETIC stray note";
  const errors = app.validate(state, pack).errors;
  assert.equal(errors.length, 1);
  assert.match(errors[0].message, /Pair 2: choose a preference/);
});

test("notes are bounded and the ballot binds pack, rubric and pair identities", () => {
  const app = load();
  const state = ready(app);
  const entry = state.pairs["pair-two"];
  entry.preference = "A";
  scoreAll(entry, 5);
  entry.notes = "x".repeat(2001);
  assert.match(app.validate(state, pack).errors[0].message, /limited to 2000/);
  entry.notes = "</script><img src=x onerror=alert(1)>";
  const result = app.validate(state, pack);
  const ballot = app.buildBallot(state, pack, result.ratings, "2026-10-23T12:30:00.000Z");
  assert.deepEqual(Object.keys(plain(ballot)).sort(), ["form_version", "pack_id", "pack_sha256", "rated_at", "rater_assertion",
    "rater_id", "rater_kind", "ratings", "rubric_id", "rubric_sha256", "schema"]);
  assert.equal(ballot.ratings[0].pair_sha256, "d".repeat(64));
  assert.equal(ballot.ratings[0].notes, "</script><img src=x onerror=alert(1)>"); // Data, never markup.
  assert.equal(app.ballotFilename(pack, { raterId: "synthetic:rater/1" }), "ballot-pack-0123456789abcdef-synthetic_rater_1.json");
});

test("assets never parse HTML, execute strings, store data or reach the network", () => {
  for (const forbidden of [/innerHTML/, /outerHTML/, /insertAdjacentHTML/, /document\.write/, /\beval\s*\(/,
    /new Function/, /\bfetch\s*\(/, /XMLHttpRequest/, /sendBeacon/, /WebSocket/, /localStorage/, /sessionStorage/,
    /indexedDB/, /document\.cookie/, /\bimport\s*\(/, /https?:\/\//]) {
    assert.doesNotMatch(appSource, forbidden, String(forbidden));
  }
  assert.match(html, /Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'/);
  assert.match(html, /connect-src 'none'/);
  assert.doesNotMatch(html, /<script>|<style|\sstyle=|\son[a-z]+\s*=|https?:\/\/|\/\/[a-z]/i);
  assert.deepEqual([...html.matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]), ["pack-data.js", "app.js"]);
  assert.doesNotMatch(css, /@import|url\(|https?:/);
});
