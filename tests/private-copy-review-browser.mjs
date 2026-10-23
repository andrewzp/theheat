// Background-only browser journey for the private copy-review form.
//
// D1 archives (actual pipeline, INVENTED offline transports) -> qualified INVENTED
// selection -> CLI-built private pack -> fresh headless Chromium on an owned
// 127.0.0.1 server -> keyboard/form interaction -> downloaded SYNTHETIC ballots ->
// fresh-process CLI import -> existing comparison summary.
// These SYNTHETIC opinions add zero real human ratings and prove no preference.
//
// Run explicitly (no discovery assumptions):
//   node tests/private-copy-review-browser.mjs --python <locked python> --result-dir <abs 0700 dir>
//     --playwright <absolute index.mjs> --chromium <absolute executable>
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = realpathSync(fileURLToPath(new URL("..", import.meta.url)));
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => {
  if (value.startsWith("--")) pairs.push([value.slice(2), all[index + 1]]);
  return pairs;
}, []));
const PYTHON = args.python;
const RESULT_DIR = args["result-dir"];
assert.ok(PYTHON && RESULT_DIR, "--python and --result-dir are required");
assert.ok(args.playwright && args.chromium, "--playwright and --chromium are required explicit installed paths");
assert.ok([PYTHON, RESULT_DIR, args.playwright, args.chromium].every(isAbsolute), "all paths must be absolute");
mkdirSync(RESULT_DIR, { recursive: true, mode: 0o700 });
chmodSync(RESULT_DIR, 0o700);
const ASSET_NAMES = ["index.html", "app.js", "styles.css", "pack-data.js"];
const proof = { notice: "SYNTHETIC fixture journey; zero real human ratings; no model preference proven.", steps: [] };
const sha = (data) => createHash("sha256").update(data).digest("hex");
const ENV = { PATH: "/usr/bin:/bin", HOME: "/nonexistent-invented-home", LC_ALL: "C", LANG: "C", NO_PROXY: "*",
  no_proxy: "*", NETRC: "/dev/null", PYTHON_DOTENV_DISABLED: "1" };

function python(argv) {
  const result = spawnSync(PYTHON, ["-I", ...argv], { cwd: ROOT, env: ENV, encoding: "utf8", timeout: 180000 });
  return { code: result.status, stdout: result.stdout, stderr: result.stderr };
}

// 1. Invented archives + selection, then the actual CLI build.
const work = realpathSync(mkdtempSync(join(realpathSync(tmpdir()), "copy-review-")));
chmodSync(work, 0o700);
const setup = python(["-c", [
  "import json, sys",
  `sys.path.insert(0, ${JSON.stringify(ROOT)})`,
  "from pathlib import Path",
  "from tests.test_private_copy_pack import configure_offline_environment, make_review_workspace",
  "configure_offline_environment()",
  `w = make_review_workspace(Path(${JSON.stringify(work)}))`,
  "print(json.dumps({'archives': [str(a) for a in w['archives']], 'selection': str(w['selection'])}))",
].join("\n")]);
assert.equal(setup.code, 0, setup.stderr);
const workspace = JSON.parse(setup.stdout.trim().split("\n").pop());
const privateDir = join(work, "private");
mkdirSync(privateDir, { mode: 0o700 });
const packDir = join(work, "pack");
const created = new Date(Date.now() - 3600_000).toISOString().replace("Z", "+00:00");
const build = python([join(ROOT, "scripts/private_copy_review.py"), "build", "--selection", workspace.selection,
  "--created-at", created, "--pack-dir", packDir, "--private-dir", privateDir,
  ...workspace.archives.flatMap((a) => ["--archive", a])]);
const built = JSON.parse(build.stdout);
assert.equal(build.code, 1, build.stdout + build.stderr); // One invented unqualified pair is held.
assert.equal(built.status, "pack_built_with_held_pairs");
assert.equal(built.origin_leak_scan, "clean");
const privateRecord = JSON.parse(readFileSync(join(privateDir, built.private_record), "utf8"));
proof.steps.push({ step: "cli_build", pack_id: built.pack_id, pairs: built.pairs, held_pairs: built.held_pairs });

// Strings that would reveal origin/provenance/translation if they reached the page.
const needles = new Set(["private_mapping", "pairs_input", "side_assignments", "edited_from", "author_assertion",
  "provenance", "invented-operator", "claude", "gemini"]);
for (const [candidateId, record] of Object.entries(privateRecord.provenance)) {
  needles.add(candidateId);
  needles.add(record.scope_id);
  needles.add(record.manifest_sha256);
}
for (const pair of privateRecord.pairs_input) for (const candidate of pair.candidates) needles.add(candidate.origin);
for (const archive of workspace.archives) needles.add(archive);

// 2. Owned loopback server: four fixed files from the pack only.
const server = createServer((request, response) => {
  const name = new URL(request.url, "http://127.0.0.1").pathname.replace(/^\//, "") || "index.html";
  if (!ASSET_NAMES.includes(name) || request.method !== "GET") {
    response.writeHead(404, { "content-type": "text/plain" });
    response.end("not found");
    return;
  }
  const type = { html: "text/html", js: "text/javascript", css: "text/css" }[name.split(".").pop()];
  response.writeHead(200, { "content-type": `${type}; charset=utf-8`, "cache-control": "no-store" });
  response.end(readFileSync(join(packDir, name)));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const ORIGIN = `http://127.0.0.1:${server.address().port}`;
proof.loopback_origin_port_os_assigned = true;

const { chromium } = await import(pathToFileURL(args.playwright).href);
const browser = await chromium.launch({ headless: true, executablePath: args.chromium });
const consoleErrors = [];
const blocked = [];
const requested = [];

async function session(viewport, extra = {}) {
  const context = await browser.newContext({ viewport, acceptDownloads: true, ...extra });
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin === ORIGIN) return route.continue();
    blocked.push(url.href);
    return route.abort();
  });
  const page = await context.newPage();
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
  page.on("request", (request) => requested.push(request.url()));
  await page.goto(`${ORIGIN}/index.html`);
  await page.waitForSelector("#pairs section.pair");
  return { context, page };
}

async function noLeaks(page, label) {
  const html = await page.content();
  const leaks = [...needles].filter((needle) => needle && html.includes(needle));
  assert.deepEqual(leaks, [], `${label}: origin metadata leaked into the page`);
}

async function save(download, name) {
  const target = join(RESULT_DIR, name);
  await download.saveAs(target);
  chmodSync(target, 0o600);
  return target;
}

// 3. Desktop: keyboard, invalid form, synthetic ballot 1 (pair 1 prefer A, pair 2 tie).
const desktop = await session({ width: 1280, height: 900 });
let page = desktop.page;
await noLeaks(page, "desktop");
await page.keyboard.press("Tab");
assert.equal(await page.evaluate(() => document.activeElement.className), "skip");
await page.keyboard.press("Enter");
assert.equal(await page.evaluate(() => document.activeElement.id), "ballot");
await page.keyboard.press("Tab");
assert.equal(await page.evaluate(() => document.activeElement.id), "rater-id");
await page.keyboard.type("synthetic-rater-1");
await page.keyboard.press("Tab");
assert.equal(await page.evaluate(() => document.activeElement.value), "human_assertion");
await page.keyboard.press("ArrowDown"); // Moves to and selects "Synthetic test fixture".
assert.equal(await page.evaluate(() => document.activeElement.value), "synthetic_fixture");
await page.keyboard.press("Tab");
assert.equal(await page.evaluate(() => document.activeElement.id), "rater-assertion");
await page.keyboard.press("Space");
assert.equal(await page.isChecked("#rater-assertion"), true);
proof.steps.push({ step: "keyboard_rater_fields", result: "skip_link_focus_typed_id_arrow_radio_space_checkbox" });

await page.click("#export");
let errorText = await page.textContent("#errors");
assert.match(errorText, /Rate at least one pair/);
assert.equal(await page.evaluate(() => document.activeElement.id), "errors");
await page.check("#preference-0-A");
await page.click("#export");
errorText = await page.textContent("#errors");
assert.match(errorText, /Fix 6 problems/);
await page.focus("#errors li:first-child button");
await page.keyboard.press("Enter");
assert.equal(await page.evaluate(() => document.activeElement.id), "score-0-A-punch-1");
proof.steps.push({ step: "invalid_form", errors_shown: ["Rate at least one pair", "Fix 6 problems"],
  error_link_moves_focus_to: "score-0-A-punch-1", download_attempted_while_invalid: false });

for (const [side, values] of [["A", [4, 4, 2]], ["B", [3, 4, 3]]]) {
  for (const [index, metric] of ["punch", "clarity", "unnecessary_words"].entries()) {
    await page.check(`#score-0-${side}-${metric}-${values[index]}`);
  }
}
await page.check("#preference-1-tie");
for (const side of ["A", "B"]) for (const metric of ["punch", "clarity", "unnecessary_words"]) {
  await page.check(`#score-1-${side}-${metric}-3`);
}
await page.fill("#notes-1", "SYNTHETIC fixture note </script><img src=x onerror=alert(1)>");
const [download1] = await Promise.all([page.waitForEvent("download"), page.click("#export")]);
const ballot1 = await save(download1, "ballot-synthetic-rater-1.json");
assert.match(await page.textContent("#status"), /Downloaded ballot-pack-.*synthetic-rater-1\.json with 2 rated pairs/);
assert.equal(await page.evaluate(() => document.querySelectorAll("img").length), 0); // Notes stayed text.
const desktopShot = join(RESULT_DIR, "desktop.png");
await page.screenshot({ path: desktopShot, fullPage: true });
chmodSync(desktopShot, 0o600);
await noLeaks(page, "desktop after input");
await desktop.context.close();

// 4. Phone width: layout and synthetic ballot 2 (pair 1 abstain, pair 2 left unrated).
const mobile = await session({ width: 390, height: 844 }, { isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
page = mobile.page;
await noLeaks(page, "mobile");
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
assert.ok(overflow <= 0, `horizontal overflow ${overflow}px at phone width`);
const stacked = await page.evaluate(() => {
  const [a, b] = document.querySelectorAll(".pair .side");
  return b.getBoundingClientRect().top > a.getBoundingClientRect().bottom - 1;
});
assert.equal(stacked, true);
await page.fill("#rater-id", "synthetic-rater-2");
await page.check("input[name=rater-kind][value=synthetic_fixture]");
await page.check("#rater-assertion");
await page.check("#preference-0-abstain");
const [download2] = await Promise.all([page.waitForEvent("download"), page.click("#export")]);
const ballot2 = await save(download2, "ballot-synthetic-rater-2.json");
const mobileShot = join(RESULT_DIR, "mobile.png");
await page.screenshot({ path: mobileShot, fullPage: true });
chmodSync(mobileShot, 0o600);
const scoreRows = await page.evaluate(() => [...document.querySelectorAll(".pair .side .choices")].slice(0, 3)
  .map((set) => new Set([...set.querySelectorAll(".pill")].map((pill) => Math.round(pill.getBoundingClientRect().top))).size));
assert.deepEqual(scoreRows, [1, 1, 1], "score choices should fit one row at phone width");
const tapHeights = await page.evaluate(() => Math.min(...[...document.querySelectorAll(".pill")].map((p) => p.getBoundingClientRect().height)));
assert.ok(tapHeights >= 44, `tap targets ${tapHeights}px`);
await mobile.context.close();
proof.steps.push({ step: "phone_width", viewport: "390x844", horizontal_overflow_px: overflow, sides_stacked: stacked,
  score_choice_rows: scoreRows, min_tap_height_px: tapHeights });

// 5. Direct file:// open of a copied pack (operators may open it without a server).
const fileCopy = join(work, "file-pack");
mkdirSync(fileCopy, { mode: 0o700 });
for (const name of ASSET_NAMES) copyFileSync(join(packDir, name), join(fileCopy, name));
const fileContext = await browser.newContext();
await fileContext.route("**/*", (route) => {
  const url = new URL(route.request().url());
  if (url.protocol === "file:" && url.pathname.startsWith(fileCopy)) return route.continue();
  blocked.push(url.href);
  return route.abort();
});
const filePage = await fileContext.newPage();
filePage.on("pageerror", (error) => consoleErrors.push(String(error)));
await filePage.goto(pathToFileURL(join(fileCopy, "index.html")).href);
const fileRendered = await filePage.locator("#pairs section.pair").count();
await fileContext.close();
proof.steps.push({ step: "file_url_open", rendered_pairs: fileRendered });
assert.equal(fileRendered, built.pairs);
await browser.close();
server.close();

assert.deepEqual(consoleErrors, [], "console errors");
assert.deepEqual(blocked, [], "only the owned loopback origin and local files were requested");
assert.ok(requested.every((url) => url.startsWith(ORIGIN)), "non-loopback request");

// 6. Fresh-process CLI import of the downloaded ballots (ballot 1 twice = identical retry).
for (const ballot of [ballot1, ballot2]) {
  const parsed = JSON.parse(readFileSync(ballot, "utf8"));
  assert.equal(parsed.rater_kind, "synthetic_fixture");
  assert.equal(parsed.pack_sha256, privateRecord.pack_sha256);
}
const importDir = join(RESULT_DIR, "imports");
mkdirSync(importDir, { recursive: true, mode: 0o700 });
chmodSync(importDir, 0o700);
const asOf = new Date(Date.now() + 60_000).toISOString().replace("Z", "+00:00");
const imported = python([join(ROOT, "scripts/private_copy_review.py"), "import", "--private",
  join(privateDir, built.private_record), "--ballot", ballot1, "--ballot", ballot1, "--ballot", ballot2,
  "--as-of", asOf, "--output-dir", importDir]);
const summary = JSON.parse(imported.stdout);
assert.equal(imported.code, 0, imported.stdout + imported.stderr);
assert.equal(summary.real_human_ratings_added, 0);
assert.deepEqual(summary.synthetic_fixture_preferences, { A: 1, B: 0, tie: 1, abstain: 1 });
assert.equal(summary.identical_retries_collapsed, 2);
assert.equal(summary.publication_approved, false);
proof.steps.push({ step: "cli_import", summary });

proof.ballots = { "synthetic-rater-1": sha(readFileSync(ballot1)), "synthetic-rater-2": sha(readFileSync(ballot2)) };
proof.screenshots = { desktop: sha(readFileSync(desktopShot)), mobile: sha(readFileSync(mobileShot)) };
proof.console_errors = consoleErrors.length;
proof.blocked_requests = blocked.length;
proof.requests = requested.length;
proof.browser = { headless: true, executable: "explicit pinned Chromium (Chrome for Testing 1234)", fresh_contexts: 3 };
writeFileSync(join(RESULT_DIR, "browser-proof.json"), JSON.stringify(proof, null, 1) + "\n", { mode: 0o600 });
console.log(JSON.stringify({ status: "passed", steps: proof.steps.map((s) => s.step), console_errors: 0,
  blocked_requests: 0, real_human_ratings_added: 0 }));
