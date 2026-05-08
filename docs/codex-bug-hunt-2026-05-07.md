# Codex Bug Hunt — Silent Failures at LLM/API/State Boundaries

Repo: `~/Documents/Claude/theheat` (github.com/andrewzp/theheat).
Date prompt was authored: 2026-05-07.

## Why this hunt exists

Today, four bugs in the two-bot pipeline silently killed every GHCN draft for ~13 hours. Each bug had the same shape:

1. The bug lives at a **boundary** — process → JSON → API → text → JSON → process.
2. A blanket `try/except Exception: return None` swallows the stack.
3. The failure surfaces only as a `print()` to stdout — invisible to the dashboard, queryable state, and any observer who isn't grepping GitHub Actions logs.
4. The four-bug stack (PRs #39, #40, #41 fixed each layer):
   - **#39** `bundle.raw_signal_dump` carries a `date` object → `json.dumps()` raises `TypeError: Object of type date is not JSON serializable`.
   - **#40** Sonnet 4.6 wraps response in `` ```json ... ``` `` despite prompt forbidding it → `json.loads()` chokes.
   - **#41a** Sonnet emits chain-of-thought preamble (`"Let me think about this carefully."`) before JSON → `json.loads()` chokes again.
   - **#41b** Anthropic API exceeds 90s client timeout → `ReadTimeout`.

The *fixes* are in (suppression ledger surfaces these now). **What I missed: a comprehensive sweep for the same anti-patterns elsewhere in the codebase.** That's your job.

## The hunt

Search the entire repo (focus on `src/`, but also `dashboard/`, `scripts/`) for the six anti-patterns below. For each finding, return:

```
FINDING: <short title>
LOCATION: <file:line>
SEVERITY: blocker | high | medium | low
LIKELIHOOD: ~certain | likely | possible | edge
EVIDENCE: <2-3 lines of code, with line numbers>
WHY IT BITES: <one sentence — what user-visible failure happens>
FIX SKETCH: <one sentence — minimum surgery>
```

Sort findings: blocker × ~certain first; low × edge last.

### Pattern A — JSON serialization without a `default=` handler

`json.dumps(x)` where `x` may contain a non-JSON-native value (`date`, `datetime`, `Decimal`, `set`, `bytes`, dataclass instances, custom classes).

The `asdict()` shortcut is especially dangerous: it recursively converts a dataclass to a dict but does NOT convert leaf-level `date`/`datetime` objects.

```bash
grep -rn "json\.dumps" src/ scripts/ dashboard/lib/ | grep -v "default="
grep -rn "asdict(" src/ | grep -v test
```

For each `asdict()` site, **check the dataclass definition** — does any field have type `date`, `datetime`, `Decimal`, `set`, or another non-JSON-native type? If yes and there's no `default=` on the eventual `json.dumps()`, it's the same bug as #39.

The fix landed in `src/two_bot/writer.py::_json_default` — reuse if applicable, but do NOT copy/paste; one shared util is better than five copies.

### Pattern B — `json.loads()` on LLM responses without tolerance

Any `json.loads(response.text)` or `json.loads(raw)` that consumes output from an LLM API call (Anthropic, Gemini, OpenAI). Models routinely emit:

- Markdown fences (`` ```json ... ``` ``, `` ```JSON ... ``` ``, plain ` ``` `)
- Chain-of-thought preamble (`"Let me think..."`, `"Here is the JSON:"`, `"Looking at this signal..."`)
- Postamble explanation (`"\n\nThe reasoning is..."`)
- Trailing commas (some models)
- Comments (`// ...`, some models)

```bash
grep -rn "json\.loads" src/ scripts/ dashboard/ | grep -v test
```

The reference fix is `src/two_bot/writer.py::_extract_json_payload`. Any LLM-response parser that's *not* using something equivalent is a finding. Particular suspects:

- `src/two_bot/claim_extractor.py` — Gemini Flash response parsing.
- `src/two_bot/fact_check.py::_parse_fact_check_json` — Gemini Flash response parsing.
- `src/voice/generator.py` — slated for deletion but still on disk; flag if it's reachable from any live path (it shouldn't be per the brand-of-locked invariant).
- Any dashboard route that parses LLM output (probably none — but verify).

### Pattern C — Silent `try/except Exception: return None`

The structural sibling of pattern B: when the LLM call fails, where does the failure go? If the answer is "stdout via `print()`", that's the bug. The dashboard cannot query stdout.

```bash
grep -rn -B1 -A6 "except Exception" src/ | grep -v test | head -200
```

For each match, evaluate:
1. Is the calling context a critical path (a draft might be killed)?
2. Does the failure surface anywhere queryable (state, suppressions ledger, structured log)?
3. If only `print()`: that's a finding.

The fix is `src/main.py::_record_downstream_suppression` — it captures `kill_stage` + `kill_reason` into `bot_state["suppressions"]` so the dashboard can show it. Look for places where this hook should be applied but isn't:

- `src/voice/generator.py` (if reachable)
- `src/data/firms.py` — fire detection error paths
- `src/data/ghcn.py` — GHCN fetch error paths
- Any data source `try/except` that swallows fetch failures
- Cycle-cap and cooldown kills (called out as out-of-scope in the suppression ledger PR; flag remaining gaps)

### Pattern D — API client timeouts that are too tight

Anthropic and Gemini clients with timeouts < 180s are vulnerable to occasional response latency spikes. Today's run hit `ReadTimeout` at 90s on the Anthropic call; bumping to 180s landed in #41.

```bash
grep -rn "timeout=" src/ scripts/ | grep -iE "(anthropic|genai|httpx|requests)" | grep -v test
```

For each finding:
- What's the timeout value?
- Is it tight enough to bite under load? (90s is tight for Sonnet under any extended-thinking workload; 180s is the new floor for writer; 90s is OK for fact-check / claim-extractor on Flash but verify.)
- Is there retry logic on `ReadTimeout` / `APITimeoutError`? (We have none. That's a finding.)

### Pattern E — Prompt-strict vs model-actual mismatch

Anywhere a prompt instructs the model to "not do X" (no fences, no markdown, no preamble, no commentary, return only JSON, etc.), check that downstream parsing tolerates the model doing X anyway.

```bash
grep -rn -E "(no markdown|no code fences|no prose|return only|JSON only|no preamble|no commentary)" src/two_bot/prompts/ src/voice/ docs/ | head -30
```

For each prompt directive of this kind, find the parser that consumes the response and verify it's defensive. The writer prompt at `src/two_bot/prompts/writer_prompt.py:83` says "No markdown. No code fences. No prose outside the JSON." — Sonnet ignores this. Other prompts likely have similar instructions; verify the matching parsers are tolerant.

Especially audit:
- `src/two_bot/prompts/fact_check_prompt.py` — Gemini Flash output instructions; check `_parse_fact_check_json` tolerance.
- `src/two_bot/prompts/claim_extractor_prompt.py` — likewise for `_parse_claim_extractor_json` (or equivalent).
- Any prompt asking for structured output without using JSON-mode / tool-use schema enforcement.

### Pattern F — Observability gap: source-level "OK" hides per-item failures

The dashboard's "X of N sources healthy" tile sums `status === "success"` (now also `skipped` after #38). But within a healthy source, individual items can silently fail. Today, the `open_meteo_extreme_signals` source returned `status: success` while every monthly_low bundle inside it died — invisible at the source level.

Look for:
- Per-source loops that catch per-item exceptions and continue, without recording the per-item failure
- `_record_source_run` calls where `failure_count` is computed from source status (binary) rather than per-item kills
- Any metric-aggregation site that loses cardinality between "items observed" and "items processed successfully"

```bash
grep -rn "_record_source_run\|source_run\|source_runs" src/ | head -40
```

The dashboard funnel (PR #36) gives per-item visibility for GHCN. Audit the Open-Meteo path, fire path, and other sources for equivalent per-item logging.

## Boundaries to specifically audit (highest-leverage targets)

1. **`src/two_bot/writer.py`** — already heavily fixed today (#39, #40, #41). Verify `_json_default`, `_strip_markdown_fences`, `_extract_json_payload` are used everywhere they should be, and not just where I patched.
2. **`src/two_bot/fact_check.py`** — uses Gemini Flash, parses JSON response. Same anti-patterns likely present.
3. **`src/two_bot/claim_extractor.py`** — uses Gemini Flash, parses JSON response. Same anti-patterns likely present.
4. **`src/two_bot/intern.py`** — 23 `build_*_bundle` functions, all using `asdict(ev)` for `raw_signal_dump`. Audit each event dataclass for `date` / `datetime` / `Decimal` fields.
5. **`src/state.py::save_state` / `_normalize_state`** — Gist serialization. `json.dumps(normalized, indent=2)` at line 596 has no `default=` handler. If anything date-shaped slips into state via `review_context.two_bot.fact_check.extracted_claims`, this would explode and lose state. Check defensively.
6. **`src/voice/generator.py`** — 1730 lines slated for deletion but still importable. Verify it's NOT reachable from any live path; if it is, audit it through the same six patterns.
7. **`dashboard/lib/state-store.js`** — JS-side state serialization. JSON.stringify is more permissive than Python json.dumps but check for `Date` / `BigInt` leaks.
8. **`scripts/build_station_thresholds.py`** and friends — one-time bootstrap scripts that write SQLite + thresholds. If they fail mid-run with a swallowed exception, the threshold DB ships corrupt and the bot runs on bad data.

## What "done" looks like

A markdown report at `docs/codex-bug-hunt-findings-<DATE>.md` with:

- A summary table: count of findings by severity × likelihood.
- Each finding in the format above.
- A "no findings" note for any pattern you searched and ruled out (so we know it was actually checked).
- A "next steps" section: which findings need code changes vs. which are acceptable as-is given the suppression ledger now surfacing failures.

## Don't waste time on

- The brand identity layer (`brand/`). Locked, off-limits.
- Hot 10 leaderboard migration to GHCN. Stays on Open-Meteo.
- Dashboard CSS / visual design. Editorial Light palette is canonical.
- The `theheat/theheat/` stray subdir. Known artifact, will be removed.
- Anything in `tests/` — those are tests, not the production paths.
- Refactoring for taste. Only flag what would surface as a real failure.

## Working agreement

- Dispatch parallel grep workers if it speeds the search.
- For each finding, include the exact `git blame`-able line so I can patch fast.
- Don't propose architectural rewrites (e.g. "move to Anthropic tool-use mode for schema-enforced JSON"). That's a separate decision; flag the bug class and surface it as a recommendation, but don't gate the report on it.
- If you find something that *looks* like a bug but you're <70% sure: include it, mark `LIKELIHOOD: possible`, and let me adjudicate.
- If a fix is genuinely 1-3 lines and obvious: include the diff inline. Don't wait for me.
