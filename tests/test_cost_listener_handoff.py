"""Pure invented listener handoff; no PostgreSQL/native/provider/platform case.

The subprocess uses the actual listener helper with a tiny HTTP responder. The
original CI journey still exercises the unchanged complete cost assertions.
"""

import json
import os
import socket
import subprocess

import pytest

from tests.cost_listener_helpers import listener_fd, reserve_dashboard_listener


CHILD = """
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createServer} from 'node:http';
import {pathToFileURL} from 'node:url';
test('invented owned listener', async () => {
const c = JSON.parse(readFileSync(process.env.THEHEAT_COST_TEST_CONFIG, 'utf8'));
const {listenOwnedCostSocket} = await import(pathToFileURL(process.cwd()+'/tests/cost-listener.mjs'));
let requests = 0;
const server = createServer((req,res)=>{ requests++; res.end('invented-owned-response'); });
try {
  await listenOwnedCostSocket(server,c);
  const address = server.address();
  const body = await (await fetch(c.origin+'/owned')).text();
  console.log('OWNED_RECEIPT '+JSON.stringify({origin:'http://'+address.address+':'+address.port,body,requests,expected:c.expected}));
} finally { if(server.listening) await new Promise(resolve=>server.close(resolve)); }
});
"""


def child_environment():
    return {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LC_ALL", "LANG", "NO_PROXY", "no_proxy"}}


def test_actual_python_handoff_and_node_listener_keep_the_same_reserved_origin(monkeypatch, tmp_path):
    from tests import test_postgres_cost_projection as costs

    run = subprocess.run
    receipts = []
    child = tmp_path / "owned-cost-child.test.mjs"
    child.write_text(CHILD)

    def responder(command, **kwargs):
        # Preserve the actual helper's descriptor/env/timeout/cleanup contract;
        # replace only the program's cost assertions with an invented responder.
        result = run([*command[:-1], str(child)], **kwargs)
        receipts.append(result)
        return result

    with reserve_dashboard_listener() as (owned, origin):
        with socket.socket() as competing:
            competing.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                competing.bind(owned.getsockname())
        monkeypatch.setattr(costs.subprocess, "run", responder)
        costs.cost_component_http({"environment": child_environment(), "origin": origin,
            "dashboard_listener": owned}, 9, {"invented": "unchanged"}, tmp_path / "config.json")
        assert owned.fileno() >= 3  # The borrowed parent is never closed by the helper.
        receipt = next(line.split("OWNED_RECEIPT ", 1)[1] for line in receipts[0].stdout.splitlines() if "OWNED_RECEIPT " in line)
        assert json.loads(receipt) == {"origin": origin, "body": "invented-owned-response",
            "requests": 1, "expected": {"invented": "unchanged"}}
    assert owned.fileno() == -1


def test_occupied_origin_is_refused_without_spawning_or_contacting_its_owner(monkeypatch, tmp_path):
    from tests import test_postgres_cost_projection as costs

    def forbidden(*args, **kwargs):
        pytest.fail("must not spawn a child after the owned reservation refuses")

    with reserve_dashboard_listener() as (unrelated, origin):
        unrelated.listen()
        monkeypatch.setattr(costs.subprocess, "run", forbidden)
        with pytest.raises(OSError):
            costs.cost_component_http({"environment": child_environment(), "origin": origin},
                9, {}, tmp_path / "config.json")
        unrelated.settimeout(0.02)
        with pytest.raises(TimeoutError):
            unrelated.accept()
        assert unrelated.fileno() >= 3


def test_borrowed_descriptor_origin_mismatch_refuses_before_spawn(monkeypatch, tmp_path):
    from tests import test_postgres_cost_projection as costs

    def forbidden(*args, **kwargs):
        pytest.fail("must not spawn with a mismatched origin")

    monkeypatch.setattr(costs.subprocess, "run", forbidden)
    with reserve_dashboard_listener() as (owned, _origin):
        with pytest.raises(ValueError, match="dashboard_listener_origin_mismatch"):
            costs.cost_component_http({"environment": child_environment(), "origin": "http://127.0.0.1:1",
                "dashboard_listener": owned}, 9, {}, tmp_path / "config.json")
        assert owned.fileno() >= 3


@pytest.mark.parametrize("failure", ["child_exits", "node_origin_mismatch"])
def test_failed_child_keeps_parent_ownership_and_context_closes_it(failure, monkeypatch, tmp_path):
    from tests import test_postgres_cost_projection as costs

    run = subprocess.run

    def failed_child(command, **kwargs):
        if failure == "child_exits":
            script = "process.exit(7)"
        else:
            script = CHILD.replace("await listenOwnedCostSocket(server,c)",
                "await listenOwnedCostSocket(server,{...c,origin:'http://127.0.0.1:1'})")
        child = tmp_path / "failed-cost-child.test.mjs"
        child.write_text(script)
        return run([*command[:-1], str(child)], **kwargs)

    monkeypatch.setattr(costs.subprocess, "run", failed_child)
    with reserve_dashboard_listener() as (owned, origin):
        with pytest.raises(AssertionError):
            costs.cost_component_http({"environment": child_environment(), "origin": origin,
                "dashboard_listener": owned}, 9, {}, tmp_path / "config.json")
        assert listener_fd(owned, origin) >= 3
    assert owned.fileno() == -1
