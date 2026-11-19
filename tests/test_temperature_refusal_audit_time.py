"""Force a long negative matrix without sleeping or relaxing delivery expiry.

The existing real PostgreSQL matrix covers the individual source refusals. This
pure control exercises its audit-time plumbing and the real final time fence.
No database, renderer, model, network or real platform is opened here.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from src.commands import postgres_delivery as delivery
from src.commands.schema import CommandError, utc_text
from tests import test_postgres_temperature_delivery as matrix


def test_slow_refusal_matrix_uses_grant_time_but_still_refuses_expired_binding(tmp_path, monkeypatch):
    at = datetime(2026, 11, 15, 12, tzinfo=UTC)
    elapsed = [0]

    class Clock:
        @staticmethod
        def now(tz):
            assert tz == UTC
            return at + timedelta(seconds=elapsed[0])

    saved = {"platform": "x", "stage": "upload", "owner": "invented-worker", "fence": 1,
             "recorded_at": utc_text(at), "expires_at": utc_text(at + timedelta(seconds=30))}
    value = {"intent_id": "invented-intent", "fixture": {"instance_id": "invented-instance"},
             "platform_description": {"description_sha256": "a" * 64}}
    state = {"drafts": [{"id": "invented-draft", "text": "Invented unchanged copy."}]}
    config = tmp_path / "generation.json"
    config.write_text('{"current_inputs": ["invented-source"]}')

    class Connection:
        @contextmanager
        def transaction(self, **kwargs):
            assert kwargs == {"force_rollback": True}
            yield

        def execute(self, *args):
            return self

        def fetchone(self):
            return saved["fence"], saved["owner"], saved["expires_at"]

    @contextmanager
    def connection(**kwargs):
        yield Connection()

    authority = SimpleNamespace(
        projections=SimpleNamespace(_connection=connection, _record=lambda *a: None),
        _validate=lambda c: None, _state=lambda *a, **k: (1, deepcopy(state)),
        ghcn_baseline=object(), editor_media_configuration=object(),
    )

    @dataclass(frozen=True)
    class Claim:
        reference: dict

    @dataclass(frozen=True)
    class Proof:
        claim: Claim
        checkpoint: dict

    proof = Proof(Claim({"selection": {}}), {"state_version": 1})
    case = {"authority": authority, "params": {}, "config": {"generation": str(config)},
            "draft_id": "invented-draft", "operators": SimpleNamespace(resolve=lambda _: object())}
    monkeypatch.setattr(matrix, "datetime", Clock)
    monkeypatch.setattr(matrix, "all_application_rows", lambda _: {"invented": "unchanged"})
    monkeypatch.setattr(delivery, "prepare_context", lambda *a, **k: proof)
    monkeypatch.setattr(delivery, "current_editorial_policy", lambda: {"invented": "policy"})
    monkeypatch.setattr(delivery, "read", lambda *a: deepcopy(value))
    monkeypatch.setattr(delivery, "attempt", lambda *a: saved)
    monkeypatch.setattr(delivery, "context", lambda *a, **k: (None, at + timedelta(hours=1)))
    actual_before_call = delivery.before_call
    times = []

    def measured_boundary(authority, c, value, retained, resolve, now, **kwargs):
        times.append(now)
        if len(times) <= 11:
            # Spend 33 seconds on independent negative probes with a 30s
            # retained lease. Those probes' fault semantics belong to the PG
            # integration test; only their elapsed cost is injected here.
            elapsed[0] += 3
            code = ("media_source_not_allowlisted" if config.read_text() == '{"current_inputs": []}'
                    else "invented_negative_probe")
            raise CommandError(code, "Invented negative probe")
        return actual_before_call(authority, c, value, retained, resolve, now, **kwargs)

    monkeypatch.setattr(delivery, "before_call", measured_boundary)
    result = matrix.source_refusal_matrix({"case": case, "intent": "invented-intent", "trace": []},
                                          boundaries=("before_call",), saved=saved)
    assert len(result) == 11
    assert elapsed[0] == 33
    assert times[:12] == [at] * 12
    assert times[12:] == [at + timedelta(seconds=30)]
