"""Source runner for GPM IMERG precipitation extremes."""

from __future__ import annotations

# ruff: noqa: F403,F405
from datetime import datetime, timezone

from src.credentials import decode_jwt_exp
from src.data import source_access, source_incidents
from src.data._witness import degraded_via
from src.orchestrator.common import *

# W06.2 (default off): rotate the per-city legs through bounded blocks of the watchlist.
SCAN_FLAG = "THEHEAT_RAINFALL_REGIONAL_SCAN"
SCAN_DEADLINE_S = 900.0


def scan_blocks(cities: list[dict], block: int) -> tuple[list[str], list[list[int]]]:
    """Stable named blocks of the watchlist; a changed watchlist is a new region set (cursor 0)."""
    import hashlib

    keys = ["|".join(str(c.get(k, "")) for k in ("city", "country", "lat", "lon")) for c in cities]
    blocks = [list(range(i, min(i + block, len(cities)))) for i in range(0, len(cities), block)]
    names = [f"block-{n + 1:03d}-" + hashlib.sha256("\n".join(keys[j] for j in idx).encode()).hexdigest()[:12]
             for n, idx in enumerate(blocks)]
    return names, blocks


def _scanned_fetch(bot_state: BotState, cities: list[dict], *, max_cities: int, max_workers: int, trace,
                   scan: dict, access: dict | None = None) -> list:
    """One existing GPM call per run, ordered so the cursor's block gets the capped per-city legs.

    Grid downloads still inspect the whole watchlist; only the per-city order rotates. The
    checkpoint is the retained run's details.rainfall_scan (an existing seam). A failed
    region advances the cursor too, then the failure reaches the runner's usual status.
    """
    from src.data import rainfall_supply

    names, blocks = scan_blocks(cities, min(max_cities, gpm_imerg.MAX_NETWORK_CITIES))
    cursor = rainfall_supply.cursor_from_history(bot_state.get("run_history"), "gpm_imerg", names)
    readings: list = []
    errors: list[BaseException] = []

    def fetch(region: str) -> dict:
        chosen = blocks[names.index(region)]
        order = chosen + [j for j in range(len(cities)) if j not in set(chosen)]
        try:
            rows = _fetch_strict(gpm_imerg.fetch_daily_precip, cities=[cities[j] for j in order],
                                 max_cities=max_cities, max_workers=max_workers, trace=trace,
                                 network_selection=[cities[j] for j in chosen], **(access or {}))
        except Exception as exc:
            errors.append(exc)
            raise
        readings.extend(rows)
        outcome = "model_fallback" if degraded_via(rows) else "qualified" if rows else "empty_success"
        return {"outcome": outcome, "readings": len(rows), "calls": 1}

    scan.update(rainfall_supply.scan_regions(names, fetch, cursor=cursor, max_regions=1, max_calls=1,
                                             deadline_s=SCAN_DEADLINE_S))
    if errors:
        raise errors[0]
    return readings


def run_gpm_imerg(
    bot_state: BotState,
    current_run: dict | None,
    cities: list[dict],
) -> None:
    print("[alerts] Checking GPM IMERG precipitation...")
    started = time.perf_counter()
    source_promoted = 0
    # Observation only: the bounded trace rides the existing telemetry details.
    trace = gpm_imerg.RainfallOpportunityTrace(run_id=(current_run or {}).get("id"))
    packet_holds: list[dict] = []  # W06.6: named packets stopped before paid generation
    scan: dict = {}  # W06.2: the bounded regional scan, when THEHEAT_RAINFALL_REGIONAL_SCAN is "1"
    # A3: bounded backoff after a provider refusal of this exact credential (its expiry claim,
    # never its value). An expired credential is already stopped locally inside the fetch.
    token = os.environ.get("EARTHDATA_TOKEN", "")
    expiry = decode_jwt_exp(token) if token else None
    credential_expires_at = source_access.credential_identity(expiry, configured=bool(token))["expires_at"]
    now = datetime.now(timezone.utc)
    backoff = (source_access.refusal_backoff(bot_state.get("run_history"), credential_expires_at=credential_expires_at,
                                             now=now) if token else None)
    access = {"access_backoff": backoff} if backoff else {}

    def details() -> dict:
        out = {**_trace_details(trace), **({"rainfall_packet_holds": packet_holds} if packet_holds else {}),
               **({"rainfall_scan": dict(scan)} if scan else {})}
        incident = out.get("incident")
        attempts = incident.get("attempts") if isinstance(incident, dict) else None
        record = source_access.run_record(credential_expires_at=credential_expires_at,
                                          attempts=attempts if isinstance(attempts, list) else [],
                                          backoff=backoff, now=now)
        if record is not None:  # present only after a refusal or during backoff: normal rows unchanged
            out["earthdata_access"] = record
        return out
    try:
        max_cities_raw = os.environ.get("GPM_IMERG_MAX_CITIES")
        max_cities = (
            int(max_cities_raw)
            if max_cities_raw
            else gpm_imerg.DEFAULT_CITY_LIMIT
        )
        if max_cities < 1:
            raise ValueError("GPM_IMERG_MAX_CITIES must be >= 1")
        max_workers_raw = os.environ.get("GPM_IMERG_MAX_WORKERS")
        max_workers = (
            int(max_workers_raw)
            if max_workers_raw
            else gpm_imerg.DEFAULT_MAX_WORKERS
        )
        if max_workers < 1:
            raise ValueError("GPM_IMERG_MAX_WORKERS must be >= 1")
        if os.environ.get(SCAN_FLAG) == "1" and cities:
            readings = _scanned_fetch(bot_state, cities, max_cities=max_cities, max_workers=max_workers,
                                      trace=trace, scan=scan, access=access)
        else:
            readings = _fetch_strict(
                gpm_imerg.fetch_daily_precip,
                cities=cities,
                max_cities=max_cities,
                max_workers=max_workers,
                trace=trace,
                **access,
            )
        events = gpm_imerg.detect_precip_records(readings, cast(dict, bot_state))
        for event in events:
            if state.is_duplicate(bot_state, event.event_id):
                continue
            score = score_precipitation_extreme(
                event.mm_total,
                event.period_days,
                event.deviation_from_record_mm,
                event.country,
            )
            if not _should_draft(score, event.event_id, summary=event.location):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NASA GPM IMERG",
                source_key="gpm_imerg",
                headline=f"{event.location}: {event.mm_total:.0f} mm rainfall signal",
                current_run=current_run,
                facts=[
                    _fact("Location", event.location),
                    _fact("Country", event.country),
                    _fact("Rainfall", f"{event.mm_total:.1f} mm"),
                    _fact("Period", f"{event.period_days} day(s)"),
                    _fact("Previous record", (
                        f"{event.previous_record_mm:.1f} mm"
                        if event.previous_record_mm is not None
                        else None
                    )),
                    _fact("City count", event.city_count),
                ],
            )
            from src.two_bot.intern import build_precipitation_bundle
            from src.data.rainfall_supply import packet_ready

            bundle = build_precipitation_bundle(event)
            # W06: an incomplete window/footprint packet stops before any paid generation.
            incomplete = packet_ready(bundle)
            if incomplete:
                print(f"[gpm_imerg] rainfall packet incomplete, not enqueued: {','.join(incomplete)}")
                packet_holds.append({"event_id": event.event_id, "location": event.location, "holds": incomplete})
                continue
            _enqueue_story_candidate(
                bot_state,
                bundle=bundle,
                score=score,
                source="gpm_imerg",
                legacy_type="precipitation_extreme",
                event_id=event.event_id,
                review_context=review_context,
                city=event.location if event.kind != "country_precip_event" else "",
                tweet_date=event.date,
                cooldown_exempt=event.kind == "country_precip_event",
            )

        # R-01/R-03: if the Open-Meteo model witness served (GPM down), record
        # degraded + "served via open_meteo" so the sentinel + dashboard surface it.
        served = degraded_via(readings)
        if not served:
            gpm_imerg.update_precip_tracking(cast(dict, bot_state), readings)
        _record_source_run(
            current_run,
            bot_state,
            "gpm_imerg",
            started,
            status="degraded" if served else "success",
            observed=len(readings),
            promoted=source_promoted,
            drafted=0,
            note=served,
            details=details(),
        )
    except SourceSkipped as exc:
        print(f"[alerts] GPM IMERG skipped: {exc}")
        _record_source_run(
            current_run,
            bot_state,
            "gpm_imerg",
            started,
            status="skipped",
            note=str(exc),
            details=details(),
        )
    except Exception as exc:
        print(f"[alerts] GPM IMERG error: {exc}")
        state.log_error(bot_state, "gpm_imerg", str(exc))
        _record_source_run(
            current_run,
            bot_state,
            "gpm_imerg",
            started,
            status="failed",
            error=str(exc),
            details=details(),
        )
    return


def _trace_details(trace) -> dict:
    """The trace export, or an explicit capture failure; never a fabricated trace."""
    try:
        details = {"rainfall_opportunity": trace.export()}
    except Exception:  # noqa: BLE001 - telemetry capture must not change the run
        return {"rainfall_opportunity": {"schema": gpm_imerg.TRACE_SCHEMA, "trace_status": "incomplete",
                                         "incomplete_reasons": ["export_failed"]}}
    try:
        # W03: product-level incident identity derived from the same trace, no new capture.
        attempts = source_incidents.gpm_attempts(details["rainfall_opportunity"])
        if attempts:
            details["incident"] = source_incidents.run_incident("gpm_imerg", attempts)
    except ValueError:
        pass
    return details
