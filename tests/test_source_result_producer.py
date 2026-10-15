"""Bounded command/local-only producer contracts, without source or model I/O."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.commands.reducer import reduce_command
from src.commands.schema import Command, CommandError, Principal, utc_text
from src.orchestrator.source_result_client import SourceResultClient
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import CycloneSupplyError
from tests.test_postgres_physical_events import isolated as isolated


def body():
    now = datetime.now(UTC)
    return dict(command_id=str(uuid4()), action="commit_nhc_source_run", requested_at=utc_text(now),
        expires_at=utc_text(now+timedelta(minutes=10)), targets=[], payload=dict(supply_run_id=str(uuid4()),
            supply_sha256="a"*64, runtime_input_sha256="b"*64, expected_policy_sha256="c"*64,
            expected_episode_heads={"ep1:cyclone:nhc:AL012026":None}))


@pytest.mark.parametrize("mode", ["extra", "missing", "bad_uuid", "upper_sha", "short_sha", "heads_list", "bad_id", "invest", "zero_year", "bool_head", "65", "long_window", "targets"])
def test_exact_source_command_shape(mode):
    value = body()
    payload = value["payload"]
    if mode == "extra":
        payload["source"] = "nhc"
    if mode == "missing":
        del payload["runtime_input_sha256"]
    if mode == "bad_uuid":
        payload["supply_run_id"] = "run"
    if mode == "upper_sha":
        payload["supply_sha256"] = "A"*64
    if mode == "short_sha":
        payload["runtime_input_sha256"] = "b"
    if mode == "heads_list":
        payload["expected_episode_heads"] = []
    if mode in {"bad_id", "invest", "zero_year"}:
        payload["expected_episode_heads"] = {dict(bad_id="AL012026", invest="ep1:cyclone:nhc:AL902026", zero_year="ep1:cyclone:nhc:AL010000")[mode]:None}
    if mode == "bool_head":
        payload["expected_episode_heads"] = {"ep1:cyclone:nhc:AL012026":True}
    if mode == "65":
        payload["expected_episode_heads"] = {f"ep1:cyclone:nhc:AL01{year}":None for year in range(1961,2026)}
    if mode == "long_window":
        value["expires_at"] = utc_text(datetime.now(UTC)+timedelta(hours=1))
    if mode == "targets":
        value["targets"] = [{}]
    with pytest.raises(CommandError):
        Command.from_request(value, Principal("editor", "editor", "invented"), environment="local", now=datetime.now(UTC))


def test_common_reducer_refuses_source_and_viewer_denied():
    actor = Principal("editor", "editor", "invented")
    command = Command.from_request(body(), actor, environment="local", now=datetime.now(UTC))
    state = {"drafts":[], "unowned":[1,2]}
    before = deepcopy(state)
    with pytest.raises(CommandError, match="no atomic source-result"):
        reduce_command(state, command, actor, now=datetime.now(UTC))
    assert state == before
    with pytest.raises(CommandError, match="permission"):
        Command.from_request(body(), Principal("viewer", "viewer", "invented"), environment="local", now=datetime.now(UTC))


@pytest.mark.parametrize("url", ["https://127.0.0.1:1234", "http://localhost:1234", "http://example.invalid:1234", "http://127.0.0.1", "http://127.0.0.1:1234/", "http://name@127.0.0.1:1234"])
def test_producer_refuses_nonexplicit_loopback(tmp_path, url):
    repo = p.PostgresProjectionRepository(socket_directory=tmp_path, database="invented", user="invented")
    with pytest.raises(CycloneSupplyError, match="local_source_endpoint"):
        SourceResultClient(repo, url, "http://127.0.0.1:3035", "editor", "invented").validate()
