"""Source runner for owner-supplied national-service observed temperature packets.

Default off: ``THEHEAT_REGIONAL_OBSERVED`` must be exactly ``"1"`` and
``THEHEAT_REGIONAL_OBSERVED_PACKETS`` must name a directory of retained packet
JSON files. Nothing is fetched. Each adapter's packet is processed on its own, so
one region's hold never stops another qualified region. Every qualified candidate
goes through the ordinary admission (``_enqueue_story_candidate``); the
operation's candidate budget applies only at the drain, so the publication cap is
never a discovery cap.
"""
from __future__ import annotations

# ruff: noqa: F403,F405
import json
from pathlib import Path

from src.data import regional_observations as regional
from src.editorial import hazard_episodes
from src.orchestrator.common import *

FLAG = "THEHEAT_REGIONAL_OBSERVED"
PACKETS_ENV = "THEHEAT_REGIONAL_OBSERVED_PACKETS"
MAX_PACKETS = 16
MAX_PACKET_BYTES = regional.MAX_PAYLOAD_BYTES + 1024 * 1024


def enabled() -> bool:
    return os.environ.get(FLAG) == "1"


def load_packets(directory: str | None) -> list[dict]:
    """Bounded read of retained packet files, sorted by name; unreadable files are holds."""
    if not directory:
        return []
    root = Path(directory)
    packets: list[dict] = []
    for path in sorted(root.glob("*.json"))[:MAX_PACKETS]:
        try:
            if path.stat().st_size > MAX_PACKET_BYTES:
                raise ValueError("packet_too_large")
            packets.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            packets.append({"schema": "unreadable", "adapter": path.stem.split("-")[0]})
    return packets


def run_regional_observed(bot_state: BotState, current_run: dict | None, packets: list[dict] | None = None) -> None:
    """Parse, admit and enqueue each region independently; details ride the source-run record."""
    if packets is None:
        if not enabled():
            return
        packets = load_packets(os.environ.get(PACKETS_ENV))
    started = time.perf_counter()
    regions: dict[str, dict] = {}
    observed = promoted = 0
    for packet in packets:
        adapter = str(packet.get("adapter")) if isinstance(packet, dict) else "unknown"
        try:
            result = regional.parse_packet(packet)
        except regional.RegionalHold as hold:
            regions[hold.adapter] = {"status": "held", **hold.as_dict(),
                                     "owner_action": regional.ADAPTERS[hold.adapter].owner_action
                                     if hold.adapter in regional.ADAPTERS else None}
            continue
        except Exception as exc:  # noqa: BLE001 - one adapter's defect never stops other regions
            regions[adapter if adapter in regional.ADAPTERS else "unknown"] = {
                "status": "failed", "hold": "adapter_error", "text": type(exc).__name__}
            continue
        reasons: dict[str, int] = {}
        admitted = 0
        for observation in result["observations"]:
            observed += 1
            bundle, reason = regional.build_candidate(observation)
            if bundle is None:
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
                continue
            if state.is_duplicate(bot_state, bundle.event_id):
                reasons["duplicate"] = reasons.get("duplicate", 0) + 1
                continue
            raw = bundle.raw_signal_dump
            score = score_absolute_extreme(raw["today_temp_c"], raw["lat"], raw["band_label"], raw["threshold_c"],
                                           kind=raw["kind"])
            if not _should_draft(score, bundle.event_id, summary=bundle.where):
                reasons["below_editorial_gate"] = reasons.get("below_editorial_gate", 0) + 1
                continue
            evidence = bundle.raw_signal_dump["evidence"]  # carries the comparison warrant
            station = observation["station"]
            review_context = _review_context(
                source=f"{observation['adapter'].upper()} observed station (owner-supplied packet)",
                source_key="regional_observed",
                headline=f"{bundle.where}: observed {raw['today_temp_c']:.1f} C on its source reporting day",
                current_run=current_run,
                facts=[
                    _fact("Source product", evidence["source_product"]),
                    _fact("Source station", f"{station['source_station_name']} ({station['station_id']})"),
                    _fact("Place join", station["join"]),
                    _fact("Source reporting day", evidence["valid_date"]),
                    _fact("Time support", evidence["time_support"]["limit"]),
                    _fact("Comparator", ", ".join(evidence["comparison_warrant"]["reasons"]) or "scoped warrant"),
                    _fact("Claim scope", evidence["comparison_warrant"]["claim_scope"]),
                    _fact("Packet digest", evidence["source_payload_sha256"]),
                ],
            )
            # W07: bind the source-scoped physical episode (station-day heat) beside the evidence.
            review_context["physical_episode"] = {
                "episode_id": hazard_episodes.episode_key({
                    "hazard": "heat", "issuer": observation["adapter"],
                    "country_code": station["place"]["country_code"], "place_id": evidence["place_id"],
                    "start_date": evidence["valid_date"]}),
                "source_revision": evidence["revision_id"],
            }
            out: dict = {}
            if _enqueue_story_candidate(
                bot_state, bundle=bundle, score=score, source="regional_observed", legacy_type=bundle.signal_kind,
                event_id=bundle.event_id, review_context=review_context, city=bundle.where,
                tweet_date=evidence["valid_date"], admission_out=out,
            ):
                admitted += 1
                promoted += 1
            else:
                key = f"admission_{out.get('disposition', 'refused')}"
                reasons[key] = reasons.get(key, 0) + 1
        exclusions: dict[str, int] = {}
        for row in result["exclusions"]:
            exclusions[row["reason"]] = exclusions.get(row["reason"], 0) + 1
        regions[result["adapter"]] = {
            "status": "processed", "region": result["region"], "source_product": result["source_product"],
            **result["denominators"], "candidates_admitted": admitted, "not_candidate": reasons,
            "exclusions": exclusions, "scope": result["scope"],
        }
    for adapter_id in regional.ADAPTERS:
        regions.setdefault(adapter_id, {"status": "held", "adapter": adapter_id, "hold": "no_packet_supplied",
                                        "text": regional.ADAPTERS[adapter_id].access_hold,
                                        "owner_action": regional.ADAPTERS[adapter_id].owner_action})
    processed = [row for row in regions.values() if row["status"] == "processed"]
    status = "success" if processed and len(processed) == len(regions) else "degraded" if processed else "skipped"
    details = {"regional_observed": {
        "regions": dict(sorted(regions.items())),
        "scope": "Owner-supplied named-station packets; not national, regional or global coverage.",
        "discovery_cap": None, "publication_cap": "operation candidate budget at the drain",
    }}
    _record_source_run(current_run, bot_state, "regional_observed", started, status=status, observed=observed,
                       promoted=promoted, drafted=0, note=None if status == "success" else "regional holds present",
                       details=details)
