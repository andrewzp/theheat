# The Heat

The Heat is a climate-events Twitter/X and Bluesky bot. It polls public climate,
weather, ocean, fire, air-quality, and disaster sources; scores genuinely unusual
signals; writes draft posts through the two-bot editorial pipeline; and stores
state in a GitHub Gist-backed approval queue reviewed from the Next.js dashboard.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
python -m mypy src/
cd dashboard
npm install
npm test
```

`python -m pytest` automatically excludes `voice_replay` tests. Those live
writer replays call paid APIs and are run only by the voice-regression workflow.

## Workflows

- `theheat-bot`: hourly auto-publish at `30 * * * *`, daily leaderboard at
  `0 12 * * *`, and alert polling at `0 0,4,8,16,20 * * *`.
- `refresh-thresholds`: weekly station-threshold refresh at `0 2 * * 0`.
- `voice-regression`: daily live writer replay at `0 9 * * *` and opt-in PR
  checks via the `voice-check` label.
- `source-health-sentinel`: source-health issue reconciliation at
  `30 */4 * * *`.

## State

Production uses a GitHub Gist `state.json`; the SQLite backend remains a dormant
escape hatch and test target. Do not edit the production gist by hand. State
changes should flow through bot code and the normal merge/write path.

## Project Map

- `PIPELINE.md`: current source-to-draft flow and stage glossary.
- `BRIEFING.md`: operator-level status and context.
- `docs/handoffs/`: dated handoffs and halt notes.
- `dashboard/`: Next.js operator dashboard.
- `src/orchestrator/`: scheduled modes, source runners, triage, draft saving,
  posting, and finalize hooks.
- `src/two_bot/`: writer, fact-check, critic, prompts, and bundle builders.

## Standing Rails

- Never push directly to `main`; use branch, PR, green `test` check, squash merge.
- Keep `scripts/source_health_sentinel.py` and
  `dashboard/lib/source-health.js` classifier behavior in sync in the same PR.
- Every new top-level state key needs a `MERGE_SPEC` entry and structural test
  coverage.
- Do not weaken editorial gates: thresholds, banned patterns, fact-check, or
  critic behavior.
