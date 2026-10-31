"""P00c legacy-path characterization (kept deliberately): today's direct path loses an update.

Red-first receipt: this test was first written asserting that both rejections survive; it
failed on the released base (both clients answered HTTP 200, one rejection was lost). Receipt:
.gstack/implementation/results/CLAUDE-REAL-REMAINING-CLOSURE/receipts/RED-legacy-lost-update.txt
(lane notes, ignored). The serialized route closes it: see test_route_serialized_proofs.py.

OFFLINE FIXTURE: two independently started dashboard processes call the REAL drafts handler
with the route flag unset (legacy). The file-backed Gist models GitHub's whole-file GET/PATCH
with no server merge; a barrier after each client's second state read forces the interleaving
that the extra final read, the revision checks and ``_state_rev`` cannot prevent.
"""
from __future__ import annotations

import json

from tests.real_closure import route_harness as h


def test_legacy_direct_path_two_independent_clients_lose_one_update(tmp_path):
    root = h.make_root(tmp_path)
    seed = h.fixture_state(2)
    h.seed_gist(root, h.STATE_GIST, {"state.json": json.dumps(seed["state"])})
    barrier = f"{root / 'barrier'}|2|10000|2"
    clients = [h.start_client("app/api/drafts/route.js",
                              {"action": "reject", "draftId": draft_id, "expectedRevision": seed["identities"][draft_id]},
                              h.client_env(root, barrier=barrier))
               for draft_id in ("draft_route_1", "draft_route_2")]
    responses = [h.finish(client) for client in clients]
    # Both independent writers are told their change was saved ...
    assert [r["status"] for r in responses] == [200, 200]
    assert [r["body"]["action"] for r in responses] == ["rejected", "rejected"]
    # ... both passed every existing check on their own final read before PATCHing ...
    assert any(e["event"] == "barrier_passed" for e in h.events(root))
    assert [e["event"] for e in h.events(root) if e["event"] in {"get", "patch"}].count("patch") == 2
    # ... yet the second whole-file PATCH erased the first: exactly one rejection survives.
    statuses = sorted(d["status"] for d in h.gist_state(root)["drafts"])
    assert statuses == ["pending", "rejected"], "legacy characterization: the lost update is real"
