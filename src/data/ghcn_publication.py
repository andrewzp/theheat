"""Current station-archive agreement for retained individual GHCN records.

This is a source refusal, never review, approval or delivery authority. A live
boundary reads once; no earlier boundary's verdict or downloaded bytes are reused.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import re
import time
from types import SimpleNamespace
from typing import cast

import requests

from src.two_bot.types import StoryBundle

MAX_ARCHIVE_BYTES = 8_000_000
READ_SECONDS = 12
_SIGNALS = frozenset({"open_meteo_archive_high", "open_meteo_archive_low", "monthly_high",
                      "monthly_low", "calendar_record", "calendar_record_low"})
_TYPES = {"open_meteo_archive_high": "all_time_high", "open_meteo_archive_low": "all_time_low",
          "monthly_high": "monthly_high", "monthly_low": "monthly_low",
          "calendar_record": "record", "calendar_record_low": "record_low"}
_EVENT = re.compile(r"(?:all_time_(?:high|low)_[A-Z0-9]{11}|monthly_(?:high|low)_[A-Z0-9]{11}_\d{2}|cal_(?:high|low)_[A-Z0-9]{11})_\d{4}-\d{2}-\d{2}")


class SourceHeld(ValueError):
    """Fixed diagnostic only; never include source values or provider bodies."""


def _require(condition, code):
    if not condition:
        raise SourceHeld(code)


def _clock(now):
    value = now() if callable(now) else datetime.now(UTC) if now is None else now
    _require(isinstance(value, datetime) and value.utcoffset() == timedelta(0), "ghcn_source_clock_invalid")
    return value


def _payload(draft):
    context = draft.get("review_context")
    two = context.get("two_bot") if isinstance(context, dict) else None
    return two.get("bundle") if isinstance(two, dict) else None


def _family(draft, payload):
    """Do not let missing/relabeled record evidence evade the source boundary."""
    from src.two_bot.ghcn_readable_warrant import has_readable_marker
    if has_readable_marker(payload):
        return True
    raw = payload.get("raw_signal_dump") if isinstance(payload, dict) else None
    evidence = raw.get("evidence") if isinstance(raw, dict) else None
    history = payload.get("historical_context") if isinstance(payload, dict) else None
    candidates = [evidence, evidence.get("baseline") if isinstance(evidence, dict) else None,
                  history.get("baseline") if isinstance(history, dict) else None]
    # Match the existing station-record floor's surviving family hints. Removing
    # a product label or one comparator cannot turn a bad record into an exempt
    # anomaly. These hints identify a boundary; they never verify its evidence.
    facts = payload.get("current_facts") if isinstance(payload, dict) else None
    headline = payload.get("headline_metric") if isinstance(payload, dict) else None
    compact = isinstance(raw, dict) and "ghcn_claim_view" in raw
    ghcn = (any(isinstance(row, dict) and (row.get("station_id")
                or "ghcn" in str(row.get("source_product", "")).lower()) for row in candidates)
            or isinstance(headline, dict) and str(headline.get("label", "")).startswith("observed_")
            or isinstance(facts, list) and any(isinstance(fact, dict)
                and (fact.get("label") == "station_id" or fact.get("label") == "source_product"
                     and "ghcn" in str(fact.get("value", "")).lower()) for fact in facts))
    station_event = any(isinstance(value, str) and _EVENT.fullmatch(value) is not None
                        for value in (draft.get("event_id"), payload.get("event_id") if isinstance(payload, dict) else None,
                                      raw.get("event_id") if isinstance(raw, dict) else None))
    signal = payload.get("signal_kind") if isinstance(payload, dict) else None
    legacy_type = draft.get("type")
    record = (station_event or isinstance(signal, str) and signal in _SIGNALS
              or isinstance(legacy_type, str) and legacy_type in _TYPES.values()
              or isinstance(raw, dict) and any(key in raw for key in ("new_temp_c", "old_record_c"))
              or isinstance(history, dict) and any(key in history for key in ("prior_record_c", "prior_record_year")))
    return bool(station_event or compact or ghcn and record)


def _retained(draft, payload, clock):
    from src.two_bot.evidence_contract import audit_story_bundle

    _require(isinstance(payload, dict), "ghcn_retained_source_invalid")
    from src.two_bot.ghcn_readable_warrant import has_readable_marker, materialize_tree
    if has_readable_marker(payload):
        payload = materialize_tree(payload)
    required = {"signal_kind", "where", "when", "event_id", "headline_metric", "current_facts",
                "historical_context", "raw_signal_dump"}
    _require(required <= payload.keys()
             and payload.keys() <= required | {"country", "related_signals", "human_impact"},
             "ghcn_retained_source_invalid")
    _require(payload["signal_kind"] in _SIGNALS and draft.get("event_id") == payload["event_id"]
             and draft.get("type") == _TYPES[payload["signal_kind"]],
             "ghcn_retained_source_invalid")
    raw = payload["raw_signal_dump"]
    _require(isinstance(raw, dict) and "ghcn_claim_view" not in raw,
             "ghcn_full_source_required")
    # An adapter preserves the exact saved tree. The StoryBundle constructor
    # projects evidence and must not be used to repair a malformed saved input.
    detached = deepcopy(payload)
    attrs = {"country": "", "related_signals": [], "human_impact": [], **detached}
    bundle = cast(StoryBundle, SimpleNamespace(**attrs, to_dict=lambda: deepcopy(detached)))
    _require(audit_story_bundle(bundle).prompt_ready, "ghcn_retained_source_invalid")
    evidence = raw["evidence"]
    baseline = evidence["baseline"]
    _require(evidence["source_product"] == "noaa-ghcn-daily-v2"
             and re.fullmatch(r"[A-Z0-9]{11}", evidence["station_id"]) is not None
             and re.fullmatch(r"[a-f0-9]{64}", baseline["source_payload_sha256"]) is not None,
             "ghcn_retained_source_invalid")
    for value in (baseline.get("retrieved_at"), evidence.get("retrieved_at")):
        _require(isinstance(value, str), "ghcn_retained_source_invalid")
        retrieved = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(retrieved.utcoffset() == timedelta(0) and retrieved <= clock,
                 "ghcn_retained_source_invalid")
    return bundle, evidence, baseline


def _read(station_id):
    from src.data._http import fetch_with_retry
    from src.two_bot.call_inventory import current_cancel_token

    url = f"https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{station_id}.dly"
    started = time.monotonic()
    # A new public-source session must not discover netrc credentials, ambient
    # proxies or cookies. The shared helper still accounts for the one attempt.
    with requests.Session() as session:
        session.trust_env = False
        response = fetch_with_retry(url, request=session.get, timeout=READ_SECONDS,
            attempts=1, allow_redirects=False, stream=True,
            headers={"User-Agent": "theheat-bot (contact@theheat.app)", "Cache-Control": "no-cache",
                     "Accept-Encoding": "identity"})
        try:
            _require(response.status_code == 200 and response.url == url,
                     "ghcn_current_source_unavailable")
            _require(response.headers.get("Content-Encoding", "identity").lower() == "identity",
                     "ghcn_current_source_bound")
            declared = response.headers.get("Content-Length")
            _require(declared is None or re.fullmatch(r"[0-9]{1,10}", declared) is not None
                     and int(declared) <= MAX_ARCHIVE_BYTES,
                     "ghcn_current_source_bound")
            chunks, size = [], 0
            for chunk in response.iter_content(64 * 1024):
                token = current_cancel_token()
                _require(token is None or not token.cancelled, "ghcn_current_source_cancelled")
                size += len(chunk)
                _require(size <= MAX_ARCHIVE_BYTES and time.monotonic() - started <= READ_SECONDS,
                         "ghcn_current_source_bound")
                chunks.append(chunk)
            _require(time.monotonic() - started <= READ_SECONDS, "ghcn_current_source_bound")
            _require(declared is None or size == int(declared), "ghcn_current_source_bound")
            token = current_cancel_token()
            _require(token is None or not token.cancelled, "ghcn_current_source_cancelled")
            return b"".join(chunks)
        finally:
            response.close()


def _current(bundle, evidence, baseline):
    from src.data import ghcn
    from src.data.temperature_evidence import fingerprint

    station_id = evidence["station_id"]
    payload = _read(station_id)
    try:
        snapshot = ghcn._archive_snapshot(station_id, payload, baseline["retrieved_at"])
    except (ValueError, UnicodeError):
        raise SourceHeld("ghcn_current_source_invalid") from None
    _require(snapshot["source_revision"] == baseline["source_payload_sha256"],
             "ghcn_current_archive_changed")
    day = date.fromisoformat(evidence["valid_date"])
    element = "TMAX" if bundle.raw_signal_dump["kind"] == "high" else "TMIN"
    row = snapshot["records"].get((day, element))
    current = row.to_daily_obs() if row is not None else None
    _require(current is not None and current.value_c == bundle.raw_signal_dump["new_temp_c"],
             "ghcn_current_observation_changed")
    # The real producer can reconcile both daily extremes before choosing one
    # story. Replay that retained accepted set; rebuilding only the claimed
    # element changes candidate_accepted flags and the complete provenance hash.
    variables = evidence["variables"]
    _require(isinstance(variables, dict) and element in variables
             and variables.keys() <= {"TMAX", "TMIN"}, "ghcn_current_observation_changed")
    observations = []
    for selected in sorted(variables):
        source_row = snapshot["records"].get((day, selected))
        observed = source_row.to_daily_obs() if source_row is not None else None
        if observed is None:
            raise SourceHeld("ghcn_current_observation_changed")
        expected = {"value_c": observed.value_c, "mflag": observed.mflag, "qflag": observed.qflag,
                    "sflag": observed.sflag, "observation_time": observed.observation_time,
                    "source_payload_sha256": snapshot["source_revision"]}
        _require(fingerprint(variables[selected]) == fingerprint(expected), "ghcn_current_observation_changed")
        observations.append(observed)
    thresholds, accepted = ghcn._thresholds_from_verified_archive(station_id, observations, snapshot)
    _require(len(accepted) == len(observations) and fingerprint(thresholds.provenance) == fingerprint(baseline),
             "ghcn_current_comparator_changed")


def current_draft_hold(draft, *, live=False, now=None):
    if not isinstance(draft, dict):
        return None
    payload = _payload(draft)
    if not _family(draft, payload):
        return None
    try:
        before = _clock(now)
        bundle, evidence, baseline = _retained(draft, payload, before)
        if live:
            _current(bundle, evidence, baseline)
        _require(_clock(now) >= before, "ghcn_source_clock_changed")
        return None
    except SourceHeld as exc:
        return str(exc)
    except requests.RequestException:
        return "ghcn_current_source_unavailable"
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, OverflowError):
        return "ghcn_retained_source_invalid"
    except Exception:  # noqa: BLE001 — an unexpected validator failure never authorizes a send
        return "ghcn_source_validation_unavailable"
