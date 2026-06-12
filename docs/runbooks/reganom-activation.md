# Reanalysis Regional-Anomaly Activation

This runbook activates the dormant `reanalysis_anomaly` source after its code, cache, workflow passthrough, and voice safeguards are verified. This PR does not flip the flag.

## Preconditions

- Reanalysis anomaly data tests are green.

```text
$ source .venv/bin/activate && python -m pytest tests/test_reanalysis_anomaly.py -q
.......................................                                  [100%]
39 passed in 0.09s
```

- The committed daily climatology cache is present.

```text
$ ls -la data/climatology_daily_cache.json
-rw-r--r--@ 1 andrewpuschel  staff  2310315 Jun  9 09:27 data/climatology_daily_cache.json
```

- The cache has usable region, sampled-point, and day rows.

```text
$ source .venv/bin/activate && python - <<'PY'
import json
from pathlib import Path
p = Path("data/climatology_daily_cache.json")
data = json.loads(p.read_text())
region, points = next(iter(data.items()))
point, payload = next(iter(points.items()))
print(f"regions={len(data)} first_region={region} first_point={point} days={len(payload['days'])}")
PY
regions=16 first_region=Pacific_Northwest first_point=45.52,-122.68 days=366
```

- The production workflow passes the repo variable through and defaults it off.

```text
$ rg -n 'THEHEAT_REGANOM_ENABLED' .github/workflows/bot.yml
232:          # the repo variable. Activate: gh variable set THEHEAT_REGANOM_ENABLED --body 1 --repo andrewzp/theheat
233:          # Rollback: gh variable set THEHEAT_REGANOM_ENABLED --body 0 --repo andrewzp/theheat
234:          THEHEAT_REGANOM_ENABLED: ${{ vars.THEHEAT_REGANOM_ENABLED || '0' }}
```

- The voice regression fixture exists for `regional_anomaly`.

```text
$ rg -n 'regional_anomaly_bundle|test_regional_anomaly_writer_keeps_point_index_honesty' tests/voice_regression/conftest.py tests/voice_regression/test_writer_replay.py
tests/voice_regression/conftest.py:438:def regional_anomaly_bundle() -> StoryBundle:
tests/voice_regression/conftest.py:445:    from src.two_bot.intern import build_regional_anomaly_bundle
tests/voice_regression/conftest.py:459:    return build_regional_anomaly_bundle(ev)
tests/voice_regression/test_writer_replay.py:53:    "regional_anomaly_bundle",
tests/voice_regression/test_writer_replay.py:179:def test_regional_anomaly_writer_keeps_point_index_honesty(
tests/voice_regression/test_writer_replay.py:180:    regional_anomaly_bundle, fresh_memory_slice
tests/voice_regression/test_writer_replay.py:193:    bundle = regional_anomaly_bundle
tests/voice_regression/test_writer_replay.py:196:        f"Writer killed regional_anomaly_bundle: {result.kill_reason}"
```

## Activation

Andrew flips the source by setting the repo variable:

```bash
gh variable set THEHEAT_REGANOM_ENABLED --body 1 --repo andrewzp/theheat
```

Do not set or change this variable from an implementation PR. The source is intentionally dormant until Andrew runs the activation command.

## 48-Hour Watch

Watch these surfaces for the first two days after the flip:

- Source-health sentinel issues for `reanalysis_anomaly`, especially `ours` or `unknown` labels.
- Source run telemetry for `reanalysis_anomaly` status, `error_class`, observed count, and promoted count.
- Draft queue for `legacy_type="regional_anomaly"` and manual-only review behavior.
- Kill-stage telemetry for `honesty_gate`, `safety`, `fact_check`, `critic`, and editorial threshold/approval outcomes.
- `reganom_last_fired` suppression entries, confirming repeated killed attempts do not re-enter the same window indefinitely.

## Revert

Rollback is the inverse repo-variable operation:

```bash
gh variable delete THEHEAT_REGANOM_ENABLED --repo andrewzp/theheat
```

If deletion is inconvenient, setting it back to `0` also leaves the source dormant:

```bash
gh variable set THEHEAT_REGANOM_ENABLED --body 0 --repo andrewzp/theheat
```

## Honesty Defense

Regional anomaly is a point index over sampled cities, not a whole-region or area-weighted national mean. The shipped defense has five layers:

- **Layer 0: deterministic bundle-aware gate.** `src/two_bot/pipeline.py` rejects `regional_anomaly` drafts containing any bundle `historical_context.forbidden_claims` before fact-check.
- **Layer 1: bundle builder framing.** `build_regional_anomaly_bundle` sets `where` to "`N` sampled cities in `Region`", labels the headline metric as `sampled_city_mean_anomaly_c`, and carries `data_kind="point_index_not_area_weighted"`.
- **Layer 2: writer prompt.** `writer_prompt.py` requires sampled-city attribution and bans bare region/national average wording for `regional_anomaly`.
- **Layer 3: fact-check prompt.** `fact_check_prompt.py` treats bare-region aggregate claims as unverifiable and checks the draft against the forbidden-claims list.
- **Layer 4: safety regex backstop.** `src/voice/safety.py` blocks narrow bare-region average patterns before a draft can reach manual review.

The detection gate is the primary noise filter: at least `+6.0C`, at least `2 sigma`, at least `50%` sampled-point support, over at least three consecutive complete days and at least three points. The `regional_anomaly` score threshold ranks detected events; it is not the primary detector gate.

## Status

S-28 status: `DONE(awaiting-andrew-flip)`.
