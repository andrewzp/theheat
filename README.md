# The Heat

The Heat is an extreme-weather publication built for Twitter/X. Bluesky rollout
is deferred. It polls public climate,
weather, ocean, fire, air-quality, and disaster sources; scores genuinely unusual
signals; writes draft posts through the two-bot editorial pipeline; and stores
state in a GitHub Gist-backed approval queue reviewed from the Next.js dashboard.

## Local development

Use Python 3.12 and Node.js 24, matching the required CI profiles. Start in a
local environment without production credentials or a copied production state.
The ordinary tests use fixtures; database, native graphics and paid model
workflows have separate requirements.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest tests/test_editorial_revisions.py tests/test_draft_save_retention.py -q
cd dashboard
npm ci
npm test
```

This is a development smoke check, not the complete release gate. Follow the
[local development guide](docs/local-development.md) for the full checks,
optional native/database profiles and their limits. No provider key, Gist token,
platform login or production database is needed for this smoke check.

`python -m pytest` excludes `voice_replay` tests by default. Those tests call paid
APIs; ordinary development does not select them. Do not run a scheduled bot or
writer entry point to test installation.

## Workflows

- `theheat-bot`: hourly auto-publish at `30 * * * *`, daily leaderboard at
  `0 12 * * *`, and alert polling at `0 0,4,8,16,20 * * *`.
- `refresh-thresholds`: weekly station-threshold refresh at `0 2 * * 0`.
- `voice-regression`: daily 3-fixture billing/voice canary at `17 9 * * 1-6`,
  weekly full replay Sundays at `0 9 * * 0`, automatic PR gate on writer-path
  changes (`src/two_bot/prompts/**`, `writer.py`), and opt-in PR checks via
  the `voice-check` label (economics P0.4).
- `source-health-sentinel`: source-health issue reconciliation at
  `30 * * * *`.

## State

Production uses a GitHub Gist `state.json`; the SQLite backend remains a dormant
escape hatch and test target. The same gist also holds `world_threshold_cache.json`
— the non-US world temperature half's cached 30-year thresholds (derived/regenerable,
kept out of `state.json` so core state stays lean). Do not edit the production gist by
hand. State changes should flow through bot code and the normal merge/write path.

Pending, approved and posted drafts, unresolved publication attempts, and
revision conflicts survive the nominal 200-draft cap in both runtimes. Only
unprotected records are capped; rejected drafts expire after 30 days, with the
newest ten retained if expiry would otherwise empty the queue.

The dashboard's defaults, SQLite metadata fields and retention constants are
generated from Python. After intentionally changing those contracts, run
`python scripts/gen_state_contract.py`; CI checks the generated file and actual
Python/dashboard SQLite round trips. SQLite rejects unknown metadata and a
configured Gist bootstrap failure rather than returning a plausible empty
history. This parity coverage does not make SQLite a production migration or
make Gist writes transactional.

## Publication containment

Automatic publication defaults paused through `THEHEAT_AUTOMATIC_PUBLICATION_ENABLED=0`.
The older autoship flag alone does not pause every automatic lane. Collection and
draft generation have a separate pause, `THEHEAT_PRODUCTION_PAUSED=1`; reviewing
retained drafts remains available. Raw ad-hoc text cannot publish. Release authorization
uses a new epoch, exact current approval and a verified persisted pause before
re-enabling. See [the P00b configuration and release protocol](docs/handoffs/2026-09-09-p00b-publication-containment.md).
Gist mutations are still non-atomic; [P00c](docs/plans/2026-09-09-p00c-single-mutation-authority.md)
tracks the single-consumer and credential-isolation work.

## Dashboard access

The production dashboard uses Vercel Authentication. On the current Hobby plan,
Standard Protection protects generated deployment URLs but leaves production
aliases public. When `DASHBOARD_AUTH_DISABLED=1`, the application therefore
redirects alias page reads to its generated `VERCEL_URL` and refuses alias API
mutations. Both middleware and API handlers enforce this boundary. Production
fails closed if the generated address is unavailable.

Keep Vercel Standard Protection and automatic system environment variables
enabled. The application does not validate a Vercel login itself; Vercel must
authenticate requests before they reach the generated deployment address. After
each deployment, verify that anonymous requests to the aliases redirect and that
the generated address requires sign-in. Existing alias bookmarks still work;
the resulting dashboard address changes with each deployment. See
[Vercel's protection scopes](https://vercel.com/docs/deployment-protection).

Collection controls require a recent successful dashboard and automation read,
with both collection and dashboard generation explicitly unpaused. A refresh,
failed or expired observation, local preview or a pause keeps the controls disabled.
This is a client request fence; the server independently checks every request.

For a manual CLI deployment, pass the verified merged commit as a non-secret,
per-deployment value from the linked `dashboard/` directory:

```sh
vercel --prod --yes --env THEHEAT_DASHBOARD_GIT_SHA=EXACT_MERGED_SHA
```

Verify this declaration against the deployment's actual Git metadata after release.
It supplies the dashboard's own revision when the platform Git variable is absent;
it never borrows a bot report's revision. Missing, malformed or conflicting metadata
remains unknown. This value changes no authentication or publication setting.

## Project Map

- `PIPELINE.md`: current source-to-draft flow and stage glossary.
- `BRIEFING.md`: operator-level status and context.
- `docs/upgrade-progress.md`: original upgrade packages and acceptance limits.
- `docs/local-development.md`: fixture-based setup and validation profiles.
- `docs/handoffs/README.md`: dated session history and its reading convention.
- `docs/runbooks/source-redundancy.md`: how backup-served sources, `served_via`,
  evidence grades, and remaining unbacked sources work.
- `docs/source-to-writer-evidence-contract.md`: what facts the writer can see
  and what every source bundle must preserve.
- `docs/handoffs/`: dated handoffs and halt notes.
- `dashboard/`: Next.js operator dashboard.
- `src/orchestrator/`: scheduled modes, source runners, triage, draft saving,
  posting, and finalize hooks.
- `src/two_bot/`: writer, fact-check, critic, prompts, and bundle builders.
- `docs/plans/`: dated implementation plans. The
  [product priorities](docs/plans/2026-09-09-product-priorities.md) and
  [upgrade acceptance ledger](docs/upgrade-progress.md) describe the upgrade.
  The June throughput initiative is historical context; a dated plan or handoff
  does not authorize enabling a source, paid lane or publisher.

## Operating behavior and dated background

The notes below describe implemented behavior and dated changes, not current
credential health, source freshness or effective deployment settings. Read those
from the dashboard's timestamped operating evidence and the
[production-pause runbook](docs/runbooks/production-pause.md). Do not infer
activation from an old handoff or a configured workflow schedule.

- The non-US world temperature half (`provider=both`) is backed by an in-run
  threshold cache (`world_threshold_cache.json`) since 2026-06-26, mirroring the US
  GHCN cache: a warm path caches each city's 30-year thresholds (paced under
  Open-Meteo's rate limit), a hot path does a cheap daily forecast compare, and an
  Open-Meteo 429 marks the source `degraded` instead of failing silently. The cache
  warms over ~10 days after deploy. See `PIPELINE.md` and the 2026-06-26 handoff.
- The regional-heatwave signal (`reanalysis_anomaly`) is **active** since 2026-06-26
  (`THEHEAT_REGANOM_ENABLED=1`, `manual_only`): it fires when a curated region's
  sampled cities run far above their 1991–2020 daily ERA5 normal for 3+ days — the
  heatwave class single-station records miss. Since [#347](https://github.com/andrewzp/theheat/pull/347)
  (2026-06-28) it also fires on a *just-ended* spell (within 2 days of the latest ERA5
  day), framed honestly in the past tense. See `PIPELINE.md` and the 2026-06-28 handoff.
- Source redundancy is live for the major flaky feeds that have verified backup
  legs. Backup-served runs record `status="degraded"` plus
  `served via <leg>`, never green, so outages stay visible while drafts can still
  flow.
- The dashboard Source Health views include a bounded troubleshooting log for
  currently degraded/external/unhealthy sources. It is derived from compact
  source-health run rows, not raw fetched payloads.
- Same-event, used-framing, peer-comparison, and shipped-text memory is
  publish-backed. A draft that is generated, killed, rejected, or left pending is
  not treated as coverage until an actual post succeeds.

## Standing Rails

- Never push directly to `main`; use branch, PR, green `test` check, squash merge.
- Keep `scripts/source_health_sentinel.py` and
  `dashboard/lib/source-health.js` classifier behavior in sync in the same PR.
- Every new top-level state key needs a `MERGE_SPEC` entry and structural test
  coverage.
- Do not weaken editorial gates: thresholds, banned patterns, fact-check, or
  critic behavior.
