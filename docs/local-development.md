# Local development

Start with fixture-based checks before configuring an external source, model or
publisher. The repository's production backend is Gist. Local SQLite and
PostgreSQL command/media workflows are separate development targets; starting a
local server does not select them for production or authorize publishing.

## Ordinary Python and dashboard checks

Use Python 3.12 and Node.js 24, the profiles exercised by required CI. From the
repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest tests/test_editorial_revisions.py tests/test_draft_save_retention.py -q
```

The two smoke modules exercise revision/approval invalidation and protected draft
retention with invented fixtures. They do not contact Gist or a provider, post to
X, start a PostgreSQL server, or qualify scientific data. Use a development shell
without production credentials or a production `.env`; do not copy production
state into a fixture workspace. Package installation needs package-registry
access. It is separate from the offline test run.

Install the dashboard from its committed lockfile:

```sh
cd dashboard
npm ci
npm test
```

`npm test` is `node --test`; use the package command rather than a hand-picked
glob that may omit tests. Conditional skips are unperformed checks, not passes.
No dashboard or Vercel login is needed for these tests. The local fixture suites
may open loopback sockets; a system permission error is an environment failure
to resolve explicitly, not permission to remove a test.

## Full ordinary validation

Back at the repository root with the Python environment active:

```sh
python -m pytest tests/ -q -m 'not voice_replay'
ruff check src/ tests/
mypy src/
python scripts/gen_source_registry.py --check
python scripts/gen_editorial_policy.py --check
python scripts/gen_dashboard_graphic_runtime.py --check
python scripts/gen_state_contract.py --check
python scripts/gen_usage_cost_contract.py --check
python scripts/gen_runtime_report_workflow.py --check
git diff --check
```

Then run `npm test` and `npm run build` from `dashboard/`. The full test collection
contains optional native/database cases; an ordinary local run may skip them.
Required CI installs those dependencies and runs its complete declared matrix.
A small local smoke run or skipped case cannot replace that gate.

Paid `voice_replay` cases are excluded by default in `pyproject.toml` as well as
the explicit command above. Do not select paid canaries, run a bot entry point or
dispatch a workflow to verify development setup. A passing offline model stub
establishes software behavior only, never actual model quality or provider access.

## Additional profiles

Graphics dependencies are separate:

```sh
python -m pip install -r requirements-graphics.txt
```

Actual native rendering also needs the executables and source-bound dependency
profile required by its test. Installing a Python package alone does not qualify
that profile. PostgreSQL tests additionally require PostgreSQL tools and their
explicit test configuration. Do not point a development test at production or a
shared hosted project. Some repository-specific diagnostic/rehearsal procedures
have stricter limits than this general guide; follow the assigned task before
starting one. No old failed diagnostic is reopened by setup instructions.

Do not change native guards, fixture timeouts, stage leases, required assertions,
model settings or checks to make setup pass. Keep original failures and report
which profile was actually exercised. Other Python/Node/native combinations need
their own verification; the CI profile is not a complete cross-platform lock.

## Generated contracts and release

The six `--check` commands verify committed artifacts without regenerating them.
If an intentional source change affects the source inventory, regenerate it first.
For policy-bound changes, regenerate the editorial policy **before** the packaged
graphic runtime; the runtime identity embeds the policy even when its archive is
unchanged. Use the corresponding scripts without `--check`, review the generated
diffs, then run all six checks again.

Use an isolated branch and retain unrelated local work. Required CI must pass at
the reviewed head before merge. Dashboard or generated dashboard-policy changes
need a manual Vercel deployment; a Git push is not a dashboard deployment.
Documentation-only changes do not need a duplicate dashboard release. Installation,
tests, merge and deployment each have separate evidence.

The [upgrade ledger](upgrade-progress.md) distinguishes those stages from runtime
observation and product acceptance. [Dated handoffs](handoffs/README.md) preserve
history. They do not establish current configuration or activation authority.
X is the first publishing destination; Bluesky rollout is deferred. Keep the
existing publication and collection/generation controls until their explicit
release protocol authorizes a change.
