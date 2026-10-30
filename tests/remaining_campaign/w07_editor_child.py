"""Produce an invented Gist state whose drafts carry runner-bound physical episodes (W07 editor).

Bindings come from the real ``hazard_episodes.admit`` (flag on), joins from the real
operator ledger (``propose_join``/``join_report``) and the projection from the real
``publish_bindings``. Prints ``{"raw_state", "ledger", "published", "report_sha256"}``.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import sys
from typing import Any

from src.editorial import hazard_episodes as he

REPORT_BYTES = "Invented civil-protection bulletin: the Ficta River left its banks at Exemplar Ford.".encode()
WINDOW = ["2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z"]


def gdacs(event_id: str, country: str, source_id: str) -> dict[str, Any]:
    return {"hazard": "flood", "issuer": "gdacs", "source_event_id": source_id, "candidate_id": event_id,
            "evidence_type": "official_event_report", "value": None, "places": [country], "tier": "Red",
            "retrieved_at": "2026-10-28T06:00:00Z"}


def draft(state: dict, draft_id: str, assertion: dict, *, status: str = "pending", **extra) -> dict[str, Any]:
    admission = he.admit(state, assertion, source=assertion["issuer"], event_id=assertion["candidate_id"])
    assert admission.allowed and admission.binding, admission
    row = {"id": draft_id, "event_id": assertion["candidate_id"], "type": "global_disaster", "status": status,
           "text": f"Invented draft text for {draft_id}.", "content_revision": 0, "decision_revision": 0,
           "tweet_date": "2026-10-28", "review_context": he.bind({"source": assertion["issuer"]}, admission), **extra}
    state["drafts"].append(row)
    return row


def build() -> dict[str, Any]:
    os.environ[he.FLAG] = "1"
    state: dict[str, Any] = {"drafts": [], "suppressions": []}
    river = gdacs("gdacs_FL_77_2026-10-28", "Fictonia", "FL-77")
    ems = {"hazard": "flood", "issuer": "copernicus_ems", "source_event_id": "EMSR977", "candidate_id": "copernicus_flood_EMSR977_red",
           "evidence_type": "satellite_derived", "value": 120.0, "places": ["Fictonia"], "tier": "Red",
           "retrieved_at": "2026-10-28T07:00:00Z"}
    namesake = gdacs("gdacs_FL_78_2026-10-28", "Exemplaria", "FL-78")  # same river name, other country and ID
    draft(state, "d-river", river)
    draft(state, "d-ems", ems)
    draft(state, "d-namesake", namesake)
    posted = {**deepcopy(river), "candidate_id": "gdacs_FL_77_2026-10-29", "retrieved_at": "2026-10-29T06:00:00Z",
              "places": ["Fictonia", "Exemplaria"]}  # a material update, already delivered
    draft(state, "d-posted", posted, status="posted", tweet_id="invented-post-1")
    ledger = he.empty_ledger()
    for assertion in (river, ems, namesake, posted):
        he.assign(ledger, assertion)
    keys = {name: he.episode_key(a) for name, a in (("river", river), ("ems", ems), ("namesake", namesake))}
    he.propose_join(ledger, keys["river"], keys["ems"], shared_identifier="GLIDE-FL-2026-000077")
    he.propose_join(ledger, keys["river"], keys["namesake"], geometry_overlap=True)  # no time overlap: proposal only
    report_sha256 = hashlib.sha256(REPORT_BYTES).hexdigest()
    he.join_report(ledger, report_sha256=report_sha256, actor="operator", episode_id=keys["river"],
                   claim={"claim_kind": "flood_occurring", "place_id": "fx-ford", "window": WINDOW,
                          "text": "The Ficta River left its banks at Exemplar Ford.", "attribution": "Invented Civil Protection"},
                   observation={"evidence_type": "official_flood_report", "place_id": "fx-ford", "window": WINDOW})
    he.join_report(ledger, report_sha256=report_sha256, actor="operator", episode_id=keys["river"],
                   claim={"claim_kind": "flood_occurring", "place_id": "fx-upper", "window": WINDOW,
                          "text": "Upstream villages were cut off.", "attribution": "Invented Civil Protection"},
                   observation={"evidence_type": "official_flood_report", "place_id": "fx-ford", "window": WINDOW})
    published = he.publish_bindings(ledger, state)
    return {"raw_state": json.dumps(state, ensure_ascii=False), "ledger": ledger, "published": published,
            "report_sha256": report_sha256}


if __name__ == "__main__":
    import socket

    def refuse(*_a, **_k):
        raise AssertionError("external connection trapped")
    socket.socket.connect = refuse  # type: ignore[method-assign]
    if len(sys.argv) > 1 and sys.argv[1] == "republish":
        value = json.load(sys.stdin)
        state, ledger = json.loads(value["raw_state"]), value["ledger"]
        published = he.publish_bindings(ledger, state)
        print(json.dumps({"published": published, "ledger": ledger, "writer": he.writer_statements(ledger, value["episode"]),
                          "raw_state": json.dumps(state, ensure_ascii=False)}))
    else:
        print(json.dumps(build()))
