"""Source-scoped physical episodes for the non-cyclone hazards (W07).

Extends the accepted cyclone pattern (``storage.physical_events``: source-scoped
episode IDs, immutable revisions, expected-revision operations, retained
relationship proposals) to fire, flood, disaster, earthquake and observed heat
paths as one pure, storage-agnostic ledger document. It is not a new event
database or clustering framework, and it never selects production authority:
callers persist the ledger where they already persist retained evidence.

Identity layers stay distinct: candidate ID (queue row), source revision (hash of
one source assertion), physical episode (issuer-scoped ID) and publication
identity (draft/ledger). A display name is never identity, so a same-name event
in another country or on another date cannot collide.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
import re
from typing import Any

SCHEMA = "theheat.hazard-episode-ledger/v1"
BINDING_SCHEMA = "theheat.physical-episode-binding/v1"
# Default off: runners bind episodes and fence repeated polls only when exactly "1".
FLAG = "THEHEAT_HAZARD_EPISODES"
HAZARDS = frozenset({"fire", "flood", "disaster", "earthquake", "heat", "rainfall", "smoke", "drought", "cyclone",
                     "volcano", "severe_weather"})
GDACS_HAZARDS = {"FL": "flood", "DR": "drought", "EQ": "earthquake", "WF": "fire", "TC": "cyclone", "VO": "volcano"}
MATERIAL_FIELDS = ("value", "places", "impact_statements", "tier", "list_length", "retrieved_at")
ISSUER = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
# Incidents held by name until their missing evidence is actually supplied.
HISTORICAL_HOLDS = {
    "libya": "Libya incident separation stays held: the missing incident evidence has not been supplied.",
    "thailand": "Thailand incident separation stays held: the missing incident evidence has not been supplied.",
}
_MATERIAL_TOLERANCE = 0.05


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def empty_ledger() -> dict[str, Any]:
    return {"schema": SCHEMA, "episodes": {}, "relationships": [], "report_joins": [], "operations": []}


def episode_key(assertion: Mapping[str, Any]) -> str:
    """Issuer-scoped physical identity; anonymous events key on country+place+start day."""
    hazard, issuer = assertion.get("hazard"), assertion.get("issuer")
    if hazard not in HAZARDS or type(issuer) is not str or not ISSUER.fullmatch(issuer):
        raise ValueError("episode_identity_source")
    source_id = assertion.get("source_event_id")
    if type(source_id) is str and SOURCE_ID.fullmatch(source_id):
        return f"ep1:{hazard}:{issuer}:{source_id}"
    country, place, start = assertion.get("country_code"), assertion.get("place_id"), assertion.get("start_date")
    if not all(type(v) is str and v for v in (country, place, start)) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(start)):
        raise ValueError("episode_identity_unsupported")  # a name alone never identifies an episode
    return f"ep1:{hazard}:{issuer}:anon:{country}:{place}:{start}"


def source_revision(assertion: Mapping[str, Any]) -> str:
    return _sha({k: v for k, v in assertion.items() if k not in {"retrieved_at", "candidate_id"}})


def lineage(assertion: Mapping[str, Any], *, publication_id: str | None = None) -> dict[str, Any]:
    """The four identities, never merged into one."""
    return {"candidate_id": assertion.get("candidate_id"), "source_revision": source_revision(assertion),
            "episode_id": episode_key(assertion), "publication_id": publication_id}


def _op(ledger: dict[str, Any], kind: str, payload: Mapping[str, Any], actor: str) -> dict[str, Any]:
    entry = {"seq": len(ledger["operations"]) + 1, "kind": kind, "actor": actor, **deepcopy(dict(payload))}
    ledger["operations"].append(entry)
    return entry


def _episode(ledger: Mapping[str, Any], episode_id: str) -> dict[str, Any]:
    episode = ledger["episodes"].get(episode_id)
    if not isinstance(episode, dict):
        raise ValueError("episode_unknown")
    return episode


def _expect(episode: Mapping[str, Any], expected_revision: int) -> None:
    if type(expected_revision) is not int or episode["revision"] != expected_revision:
        raise ValueError("episode_expected_revision_mismatch")


def _held(episode: Mapping[str, Any], evidence_packet_sha256: str | None) -> None:
    hold = episode.get("historical_hold")
    if hold and not (type(evidence_packet_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", evidence_packet_sha256)):
        raise ValueError(f"historical_hold:{hold}")


def assign(ledger: dict[str, Any], assertion: Mapping[str, Any], *, actor: str = "collector") -> dict[str, Any]:
    """Record one source assertion under its episode; a changed source revision appends, never erases."""
    key = episode_key(assertion)
    revision = source_revision(assertion)
    episode = ledger["episodes"].setdefault(key, {
        "episode_id": key, "hazard": assertion["hazard"], "issuer": assertion["issuer"], "revision": 0,
        "members": [], "history": [], "status": "active", "historical_hold": assertion.get("historical_hold"),
    })
    if episode["status"] != "active":
        raise ValueError("episode_not_active")
    if any(member["source_revision"] == revision for member in episode["members"]):
        return {"episode_id": key, "source_revision": revision, "changed": False}
    previous = [m for m in episode["members"] if m["candidate_id"] == assertion.get("candidate_id")]
    episode["members"].append({"source_revision": revision, "candidate_id": assertion.get("candidate_id"),
                               "issuer": assertion["issuer"], "evidence_type": assertion.get("evidence_type"),
                               "assertion": deepcopy(dict(assertion))})
    episode["revision"] += 1
    episode["history"].append({"revision": episode["revision"], "added": revision,
                               "supersedes_member": previous[-1]["source_revision"] if previous else None})
    _op(ledger, "assign", {"episode_id": key, "source_revision": revision}, actor)
    return {"episode_id": key, "source_revision": revision, "changed": True}


def propose_join(ledger: dict[str, Any], a: str, b: str, *, shared_identifier: str | None = None,
                 geometry_overlap: bool | None = None, time_overlap: bool | None = None,
                 actor: str = "operator") -> dict[str, Any]:
    """Join only on a shared identifier, or explicit geometry AND time overlap; else a retained proposal."""
    first, second = _episode(ledger, a), _episode(ledger, b)
    if first["hazard"] != second["hazard"]:
        decision, reason = "proposed_only", "different_hazards_never_merge"
    elif type(shared_identifier) is str and shared_identifier:
        decision, reason = "joined", "shared_identifier"
    elif geometry_overlap is True and time_overlap is True:
        decision, reason = "joined", "geometry_and_time_overlap"
    else:
        decision, reason = "proposed_only", "insufficient_join_evidence"
    row = {"episodes": sorted([a, b]), "decision": decision, "reason": reason,
           "contributors": sorted({m["issuer"] for e in (first, second) for m in e["members"]}),
           # Human impacts are never summed across contributors on the strength of a join.
           "impacts_combined": False}
    ledger["relationships"].append(row)
    _op(ledger, "propose_join", row, actor)
    return row


def split(ledger: dict[str, Any], episode_id: str, revisions: Sequence[str], *, new_source_id: str,
          expected_revision: int, actor: str, evidence_packet_sha256: str | None = None) -> dict[str, Any]:
    """Move named source revisions into a new episode; history keeps their origin."""
    source = _episode(ledger, episode_id)
    _expect(source, expected_revision)
    _held(source, evidence_packet_sha256)
    moving = [m for m in source["members"] if m["source_revision"] in set(revisions)]
    if not moving or len(moving) == len(source["members"]) or len(moving) != len(set(revisions)):
        raise ValueError("episode_split_selection")
    new_id = f"ep1:{source['hazard']}:{source['issuer']}:{new_source_id}"
    if new_id in ledger["episodes"] or not SOURCE_ID.fullmatch(new_source_id):
        raise ValueError("episode_split_target")
    source["members"] = [m for m in source["members"] if m not in moving]
    source["revision"] += 1
    source["history"].append({"revision": source["revision"], "split_out": [m["source_revision"] for m in moving],
                              "to": new_id})
    ledger["episodes"][new_id] = {"episode_id": new_id, "hazard": source["hazard"], "issuer": source["issuer"],
                                  "revision": 1, "members": moving, "status": "active", "historical_hold": None,
                                  "history": [{"revision": 1, "split_from": episode_id,
                                               "origin_revision": source["revision"] - 1}]}
    _op(ledger, "split", {"episode_id": episode_id, "to": new_id,
                          "moved": [m["source_revision"] for m in moving]}, actor)
    return {"from": episode_id, "to": new_id, "affected_episodes": [episode_id, new_id]}


def reassign(ledger: dict[str, Any], revision: str, *, source_episode: str, target_episode: str,
             expected_revisions: Mapping[str, int], actor: str) -> dict[str, Any]:
    source, target = _episode(ledger, source_episode), _episode(ledger, target_episode)
    _expect(source, expected_revisions.get(source_episode, -1))
    _expect(target, expected_revisions.get(target_episode, -1))
    _held(source, None)
    if source["hazard"] != target["hazard"]:
        raise ValueError("episode_reassign_hazard")
    member = next((m for m in source["members"] if m["source_revision"] == revision), None)
    if member is None or len(source["members"]) == 1:
        raise ValueError("episode_reassign_selection")
    source["members"].remove(member)
    target["members"].append(member)
    for episode, note in ((source, {"reassigned_out": revision, "to": target_episode}),
                          (target, {"reassigned_in": revision, "from": source_episode})):
        episode["revision"] += 1
        episode["history"].append({"revision": episode["revision"], **note})
    _op(ledger, "reassign", {"revision": revision, "from": source_episode, "to": target_episode}, actor)
    return {"affected_episodes": [source_episode, target_episode]}


def supersede(ledger: dict[str, Any], old: str, new: str, *, expected_revision: int, actor: str) -> dict[str, Any]:
    episode = _episode(ledger, old)
    _expect(episode, expected_revision)
    _held(episode, None)
    _episode(ledger, new)
    episode["status"] = "superseded"
    episode["superseded_by"] = new
    episode["revision"] += 1
    episode["history"].append({"revision": episode["revision"], "superseded_by": new})
    _op(ledger, "supersede", {"old": old, "new": new}, actor)
    return {"affected_episodes": [old, new]}


def affected_drafts(state: Mapping[str, Any], episode_ids: Sequence[str]) -> list[str]:
    """Drafts bound to an affected episode (via their review_context binding)."""
    wanted = set(episode_ids)
    out = []
    for draft in state.get("drafts") or []:
        binding = (draft.get("review_context") or {}).get("physical_episode") if isinstance(draft, dict) else None
        if isinstance(binding, Mapping) and binding.get("episode_id") in wanted:
            out.append(str(draft.get("id")))
    return out


def invalidate_dependents(state: dict[str, Any], episode_ids: Sequence[str]) -> dict[str, list[str]]:
    """Revoke review/approval of pending dependents; delivered or unknown-delivery snapshots stay untouched."""
    from src.editorial.revisions import revoke_approval

    changed, preserved = [], []
    ids = set(affected_drafts(state, episode_ids))
    for draft in state.get("drafts") or []:
        if str(draft.get("id")) not in ids:
            continue
        if draft.get("status") == "posted" or draft.get("publish_outcome") == "unknown":
            preserved.append(str(draft.get("id")))
            continue
        revoke_approval(draft)
        draft.pop("review_binding", None)
        draft["episode_invalidated"] = True
        changed.append(str(draft.get("id")))
    return {"invalidated": changed, "preserved_delivered": preserved}


# --- 07.4 lifecycle / 07.5 material updates ---------------------------------------------
def poll(ledger: dict[str, Any], assertion: Mapping[str, Any]) -> dict[str, Any]:
    """A repeated poll updates source status; only a material change can open a writer opportunity."""
    key = episode_key(assertion)
    episode = ledger["episodes"].get(key)
    prior = episode["members"][-1]["assertion"] if episode and episode["members"] else None
    result = assign(ledger, assertion)
    eligibility = material_update(prior, assertion) if prior is not None else {"eligible": True,
                                                                               "reasons": ["new_episode"]}
    return {**result, "writer_opportunity": bool(result["changed"] and eligibility["eligible"]),
            "eligibility": eligibility}


def material_update(published: Mapping[str, Any] | None, current: Mapping[str, Any], *,
                    delivery: str | None = None) -> dict[str, Any]:
    """New facts only: tier, list length or retrieval time alone never qualify."""
    if delivery == "unknown":
        return {"eligible": False, "reasons": ["unknown_delivery_fence"]}
    if published is None:
        return {"eligible": True, "reasons": ["no_prior_publication"]}
    reasons = []
    old_value, new_value = published.get("value"), current.get("value")
    if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)) and old_value \
            and abs(new_value - old_value) / abs(old_value) > _MATERIAL_TOLERANCE:
        reasons.append("value_changed")
    if set(current.get("places") or []) - set(published.get("places") or []):
        reasons.append("new_place")
    if set(current.get("impact_statements") or []) - set(published.get("impact_statements") or []):
        reasons.append("new_attributed_impact")
    ignored = [field for field in ("tier", "list_length", "retrieved_at")
               if current.get(field) != published.get(field)]
    return {"eligible": bool(reasons), "reasons": reasons or ["no_new_material_facts"], "ignored_changes": ignored}


# --- 07.6 report-to-physical joins --------------------------------------------------------
def join_report(ledger: dict[str, Any], *, report_sha256: str, claim: Mapping[str, Any],
                observation: Mapping[str, Any], episode_id: str, actor: str) -> dict[str, Any]:
    """Explicit report↔physical match; unmatched report language stays a report claim."""
    from src.data.rainfall_supply import corroboration

    _episode(ledger, episode_id)
    if not re.fullmatch(r"[0-9a-f]{64}", str(report_sha256)):
        raise ValueError("report_reference")
    verdict = corroboration(claim, observation)
    row = {"join_id": _sha([report_sha256, claim, observation, episode_id])[:24], "episode_id": episode_id,
           "report_sha256": report_sha256, "claim": deepcopy(dict(claim)),
           "observation_type": observation.get("evidence_type"), "status": "matched" if verdict["corroborates"]
           else "report_claim_only", "reason": verdict["reason"], "removed": False}
    ledger["report_joins"].append(row)
    _op(ledger, "join_report", {"join_id": row["join_id"], "status": row["status"]}, actor)
    return row


def writer_statements(ledger: Mapping[str, Any], episode_id: str) -> list[dict[str, Any]]:
    """Only matched, attributed statements with their own times; never a scientific warrant."""
    return [{"statement": j["claim"].get("text"), "attribution": j["claim"].get("attribution"),
             "time": j["claim"].get("window"), "evidence_class": "report_claim_matched_to_observation"}
            for j in ledger["report_joins"] if j["episode_id"] == episode_id and j["status"] == "matched"
            and not j["removed"]]


def remove_join(ledger: dict[str, Any], join_id: str, *, actor: str) -> dict[str, Any]:
    row = next((j for j in ledger["report_joins"] if j["join_id"] == join_id and not j["removed"]), None)
    if row is None:
        raise ValueError("report_join_unknown")
    row["removed"] = True  # the report bytes/hash stay retained; only the join is withdrawn
    _op(ledger, "remove_join", {"join_id": join_id}, actor)
    return {"affected_episodes": [row["episode_id"]]}


# --- 07.2/07.6 editor projection: why records are joined or separate -------------------------
JOIN_VIEW_FIELDS = ("join_id", "report_sha256", "claim", "observation_type", "status", "reason", "removed")


def project_binding(ledger: Mapping[str, Any], episode_id: str) -> dict[str, Any]:
    """The editor-facing slice of one episode: status, relationships and report joins (hashes, not bytes)."""
    episode = _episode(ledger, episode_id)
    return {"episode_status": episode["status"], "superseded_by": episode.get("superseded_by"),
            "episode_revision": episode["revision"], "historical_hold": episode.get("historical_hold"),
            "relationships": [deepcopy(row) for row in ledger["relationships"] if episode_id in row["episodes"]],
            "report_joins": [{key: deepcopy(row.get(key)) for key in JOIN_VIEW_FIELDS}
                             for row in ledger["report_joins"] if row["episode_id"] == episode_id]}


def publish_bindings(ledger: dict[str, Any], state: dict[str, Any]) -> dict[str, list[str]]:
    """Exchange joins between the operator ledger and the drafts the normal editor reviews.

    First, a report join an editor removed on a draft is withdrawn in the ledger too, so
    later briefs (``writer_statements``) no longer use it. Then each bound draft gets
    its episode's status, relationships and report joins. A changed projection is a
    changed review context: pending dependents lose review and approval; delivered or
    unknown-delivery snapshots are never rewritten.
    """
    from src.editorial.revisions import revoke_approval

    withdrawn = []
    for draft in state.get("drafts") or []:
        binding = (draft.get("review_context") or {}).get("physical_episode") if isinstance(draft, dict) else None
        for row in binding.get("report_joins") or [] if isinstance(binding, dict) else []:
            active = next((j for j in ledger["report_joins"] if j["join_id"] == row.get("join_id") and not j["removed"]),
                          None)
            if row.get("removed") and active is not None:
                remove_join(ledger, active["join_id"], actor=f"editor:{row.get('removed_by') or 'dashboard'}")
                withdrawn.append(active["join_id"])
    changed, preserved = [], []
    for draft in state.get("drafts") or []:
        binding = (draft.get("review_context") or {}).get("physical_episode") if isinstance(draft, dict) else None
        if not isinstance(binding, dict) or binding.get("episode_id") not in ledger["episodes"]:
            continue
        projection = project_binding(ledger, binding["episode_id"])
        removed = {row.get("join_id") for row in binding.get("report_joins") or [] if row.get("removed")}
        for row in projection["report_joins"]:
            row["removed"] = bool(row["removed"] or row["join_id"] in removed)
        if all(binding.get(key) == value for key, value in projection.items()):
            continue
        if draft.get("status") == "posted" or draft.get("publish_outcome") == "unknown":
            preserved.append(str(draft.get("id")))
            continue
        binding.update(projection)
        revoke_approval(draft)
        draft.pop("review_binding", None)
        draft["episode_invalidated"] = True
        changed.append(str(draft.get("id")))
    return {"invalidated": changed, "preserved_delivered": preserved, "withdrawn_joins": withdrawn}


# --- 07.1/07.4 runner admission: stable keys on the ordinary source paths ----------------------
# The retained documents are the ones the bot already keeps: each draft's review context
# carries its episode binding (publication scope), the live triage queue carries pending
# bindings, and a refused repeat poll is a row in the existing suppression ledger. No new
# Gist state key is written.
def enabled() -> bool:
    return os.environ.get(FLAG) == "1"


def _source_id(value: Any) -> str | None:
    """A provider identifier verbatim when it fits; otherwise its digest. Never a display name."""
    if type(value) is not str or not value.strip():
        return None
    value = value.strip()
    return value if SOURCE_ID.fullmatch(value) else "sha-" + hashlib.sha256(value.encode()).hexdigest()[:40]


def _countries(value: Any) -> list[str]:
    return sorted({part.strip() for part in str(value or "").split(",") if part.strip()})


def firms_assertion(fire: Any) -> dict[str, Any]:
    """FIRMS's explicit identity is the source-day cell (fire_identity); a cell is not an incident."""
    return {"hazard": "fire", "issuer": "firms", "source_event_id": _source_id(getattr(fire, "event_id", None)),
            "candidate_id": getattr(fire, "event_id", None), "evidence_type": "thermal_detection",
            "country_code": getattr(fire, "country", None) or None, "places": [getattr(fire, "event_id", None)],
            "value": None, "frp_mw": getattr(fire, "frp", None), "tier": getattr(fire, "confidence", None),
            "source_product": getattr(fire, "source_product", None),
            "retrieved_at": getattr(fire, "acquired_at", None)}


def gdacs_assertion(event: Any) -> dict[str, Any]:
    """GDACS event type + event ID is the episode; the alert tier and episode ID are revisions."""
    provenance = getattr(event, "source_provenance", None) or {}
    code = str(provenance.get("eventtype") or "")
    raw_id = getattr(event, "source_event_id", "") or ""
    return {"hazard": GDACS_HAZARDS.get(code, "disaster"), "issuer": "gdacs",
            "source_event_id": _source_id(f"{code}-{raw_id}" if code and raw_id else raw_id),
            "candidate_id": getattr(event, "event_id", None), "evidence_type": "official_event_report",
            "value": getattr(event, "severity_value", None) or None, "unit": getattr(event, "severity_unit", None) or None,
            "places": _countries(getattr(event, "country", None)), "tier": getattr(event, "severity", None),
            "source_episode": provenance.get("episode_id"), "retrieved_at": provenance.get("source_updated_at")}


def copernicus_assertion(activation: Any) -> dict[str, Any]:
    """An EMS activation code is the flood episode; its severity tier and update time are revisions."""
    return {"hazard": "flood", "issuer": "copernicus_ems",
            "source_event_id": _source_id(getattr(activation, "activation_id", None)),
            "candidate_id": getattr(activation, "event_id", None), "evidence_type": "satellite_derived",
            "value": getattr(activation, "affected_area_km2", None) or None, "unit": "km2",
            "places": _countries(getattr(activation, "country", None)), "tier": getattr(activation, "severity", None),
            "retrieved_at": getattr(activation, "last_update", None) or None}


def nws_assertion(alert: Any) -> dict[str, Any]:
    """An NWS warning has no published storm identity: its own CAP alert ID is the episode."""
    evidence = getattr(alert, "source_evidence", None) or {}
    return {"hazard": "severe_weather", "issuer": "nws",
            "source_event_id": _source_id(evidence.get("source_alert_id") or getattr(alert, "event_id", None)),
            "candidate_id": getattr(alert, "event_id", None), "evidence_type": "official_warning",
            "value": None, "places": [getattr(alert, "area", None)], "tier": getattr(alert, "severity", None),
            "warning_event": getattr(alert, "event_type", None), "retrieved_at": evidence.get("captured_at")}


@dataclass(frozen=True)
class Admission:
    """``allowed`` False means a repeated poll bought no writer opportunity (its reason is retained)."""
    allowed: bool
    binding: dict[str, Any] | None = None
    hold: str | None = None


def _priors(bot_state: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    """Earlier bindings of this episode: retained drafts first, then this run's live queue."""
    rows = []
    for draft in bot_state.get("drafts") or []:
        binding = (draft.get("review_context") or {}).get("physical_episode") if isinstance(draft, dict) else None
        if isinstance(binding, Mapping) and binding.get("episode_id") == key:
            rows.append({**binding, "delivery": "unknown" if draft.get("publish_outcome") == "unknown"
                         else draft.get("status")})
    for row in list(bot_state.get("_triage_queue") or []):
        binding = (getattr(row, "review_context", None) or {}).get("physical_episode")
        if isinstance(binding, Mapping) and binding.get("episode_id") == key:
            rows.append({**binding, "delivery": "queued"})
    return rows


def admit(bot_state: Any, assertion: Mapping[str, Any], *, source: str, event_id: str, score: Any = None,
          summary: str | None = None) -> Admission:
    """Flag off: no change. Flag on: bind the episode; a repeat without new material facts is refused.

    Only value (>5%), a new place or a new attributed impact is material; tier, list
    length and retrieval time are recorded as a new source revision but never buy a
    writer. An earlier draft with unknown delivery fences the episode (never resent).
    """
    if not enabled():
        return Admission(True)
    try:
        key, revision = episode_key(assertion), source_revision(assertion)
    except ValueError as exc:
        return Admission(True, hold=str(exc))  # unidentifiable: today's behaviour, the gap stays visible
    priors = _priors(bot_state, key)
    if any(row.get("delivery") == "unknown" for row in priors):
        eligibility = material_update(None, assertion, delivery="unknown")
    elif priors and priors[-1].get("source_revision") == revision:
        eligibility = {"eligible": False, "reasons": ["same_source_revision"], "ignored_changes": []}
    elif priors:
        eligibility = material_update(priors[-1].get("material") or {}, assertion)
    else:
        eligibility = {"eligible": True, "reasons": ["new_episode"], "ignored_changes": []}
    if not eligibility["eligible"]:
        from src.orchestrator.suppression import _current_suppression_ctx, _record_downstream_suppression

        ignored = eligibility.get("ignored_changes") or []
        _record_downstream_suppression(
            bot_state=bot_state, source=source, run_id=(_current_suppression_ctx() or {}).get("run_id"),
            event_id=event_id, score=score, kill_stage="episode_repeat",
            kill_reason=f"{key} revision {revision[:12]}: " + ", ".join(eligibility["reasons"])
            + (f" (changed but not material: {', '.join(ignored)})" if ignored else ""), summary=summary)
        return Admission(False, hold=eligibility["reasons"][0])
    return Admission(True, {
        "schema": BINDING_SCHEMA, "episode_id": key, "source_revision": revision, "hazard": assertion["hazard"],
        "issuer": assertion["issuer"], "evidence_type": assertion.get("evidence_type"),
        "lineage": {**lineage(assertion), "candidate_id": event_id},
        "material": {field: deepcopy(assertion.get(field)) for field in MATERIAL_FIELDS},
        "update_of": priors[-1].get("source_revision") if priors else None,
        "eligibility": list(eligibility["reasons"]), "ignored_changes": list(eligibility.get("ignored_changes") or []),
    })


def bind(review_context: dict[str, Any], admission: Admission) -> dict[str, Any]:
    """Attach an admitted binding (or a visible identity gap) to the candidate's review context."""
    if admission.binding is not None:
        review_context["physical_episode"] = deepcopy(admission.binding)
    elif admission.hold is not None and admission.allowed:
        review_context["physical_episode_hold"] = admission.hold
    return review_context


__all__ = ["BINDING_SCHEMA", "FLAG", "HAZARDS", "HISTORICAL_HOLDS", "SCHEMA", "Admission", "admit",
           "affected_drafts", "assign", "bind", "copernicus_assertion", "empty_ledger", "enabled", "episode_key",
           "firms_assertion", "gdacs_assertion", "invalidate_dependents", "join_report", "lineage",
           "material_update", "nws_assertion", "poll", "project_binding", "propose_join", "publish_bindings",
           "reassign", "remove_join",
           "source_revision", "split", "supersede", "writer_statements"]
