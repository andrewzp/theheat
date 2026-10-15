"""Real PostgreSQL platform-description gates; inherited assertions unchanged."""
import pytest

from src.media import platform_description as d
from tests import test_postgres_editor_media as editor, test_postgres_delivery as delivery_tests
from tests.test_postgres_editor_media import admitted as admitted, offline_connections as offline_connections
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.radar_editor_helpers import radar_case as radar_case


def review_exact(case):
    from src.media.published_radar import EXTRA_CONFIRMATIONS
    current = editor.view(case)
    checks = editor.CONFIRMATIONS | {d.CONFIRMATION}
    if current["packet"]["schema_version"] == 2:
        checks |= EXTRA_CONFIRMATIONS
    payload = dict(proposal_sha256=current["preparation"]["proposal_sha256"],
        expected_policy_sha256=current["expected_policy_sha256"], expected_packet_sha256=current["packet"]["packet_sha256"],
        review=dict(decision="accept", confirmations={k:True for k in checks},
            expected_platform_description_sha256=current["platform_description"]["record"]["description_sha256"],
            reason="Invented full description and fixed destination set reviewed; no fit or API waiver."))
    result = editor.action(case, "review_media_revision", payload)[1]
    assert result["status"] == "applied", result
    return payload


def test_genuine_long_scientific_packages_refuse_atomically_before_any_transport(admitted, core, tmp_path, monkeypatch):
    from src.commands import postgres_media, postgres_delivery
    case = admitted
    prepared, image = editor.prepare_and_attach(case)
    core[2].initialize_delivery(now=editor.AT)
    with delivery_tests.fixture_server(image, case["text"]) as (cfg, trace, accepted):
        delivery_tests.configure(case["store"], tmp_path, cfg)
        with case["store"].projections._connection() as c:
            original = postgres_media.read(c, prepared["preparation"]["proposal_sha256"], "local")
        assert len(original["assets"]["alt.txt"]) > 1000
        assert editor.view(case)["platform_description"]["status"] == "platform_description_x_house_limit"
        review_exact(case)
        editor.complete_revision(case, monkeypatch)
        before = case["store"].read()
        with case["store"].projections._connection() as c:
            costs = c.execute("SELECT * FROM theheat_spending.intents ORDER BY intent_id").fetchall()
        _, result = delivery_tests.park(case)
        assert result["status"] == "rejected" and result["code"] == "platform_description_x_house_limit", result
        assert case["store"].read() == before
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.intents") == [(0,)]
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.work_items") == [(0,)]
        with case["store"].projections._connection() as c:
            assert c.execute("SELECT * FROM theheat_spending.intents ORDER BY intent_id").fetchall() == costs
            assert postgres_media.read(c, prepared["preparation"]["proposal_sha256"], "local") == original
            with pytest.raises(postgres_delivery.CommandError, match="withheld"):
                postgres_delivery.description_preflight(case["store"], c, before[1]["drafts"][-1], original)
        assert trace == [] and not accepted


def test_legacy_review_cannot_create_new_obligation_then_new_binding_cannot_resurrect(radar_case, core, tmp_path, monkeypatch):
    case = radar_case
    _, image = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    with delivery_tests.fixture_server(image, case["text"]) as (cfg, trace, _):
        delivery_tests.configure(case["store"], tmp_path, cfg)
        before = case["store"].read()
        _, refused = delivery_tests.park(case)
        assert refused["status"] == "rejected" and refused["code"] == "platform_description_required"
        assert case["store"].read() == before and not trace
        payload = review_exact(case)
        current = editor.view(case)
        assert current["review_current"] is True
        # A fresh decision cannot use the previous target-bound description.
        stale = editor.action(case, "review_media_revision", payload)[1]
        assert stale["status"] == "rejected"
        editor.complete_revision(case, monkeypatch)
        _, parked = delivery_tests.park(case)
        assert parked["status"] == "applied", parked
        assert editor.view(case)["parked"] is True
        assert editor.action(case, "cancel_approval", {"reason":"Invented explicit cancellation."})[1]["status"] == "applied"
        assert editor.action(case, "edit_revision", {"text":"A different invented statement."})[1]["status"] == "applied"
        assert editor.action(case, "edit_revision", {"text":case["text"]})[1]["status"] == "applied"
        final = editor.view(case)
        assert final["review_current"] is False and final["parked"] is False
        assert trace == []


def test_historical_v1_long_description_obligations_remain_passive(admitted, core, tmp_path, monkeypatch):
    import base64
    import json
    from src.commands import postgres_delivery as delivery
    from src.commands.schema import utc_text
    from src.posting.delivery_receipts import descriptor, digest
    from tests import legacy_description_fixtures as legacy
    case = admitted
    prepared, image = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    command, result = delivery_tests.park(case)  # Genuine old local review, no transport configured.
    assert result["status"] == "applied"
    with delivery_tests.fixture_server(image, case["text"]) as (cfg, trace, witnesses):
        # Preserve the literal old v1 configuration/intent semantics.
        cfg = {k:v for k,v in cfg.items() if k != "platform_profile"}
        cfg["schema_version"] = 1
        delivery_tests.configure(case["store"], tmp_path, cfg)
        value, package = legacy.seed_intent(case, core[3], command, result, cfg, case["store"].delivery_configuration.sha256)
        intent = value["intent_id"]
        saved, wire, body = legacy.seed_attempt(core[3], value, package)
        assert wire == descriptor("x", "upload", wire["content_type"], body)
        full = package["assets"]["alt.txt"]
        assert len(full) > 1000 and full.endswith(b"\n")
        original = case["store"].delivery_content(case["draft_id"], intent)
        assert original["media"]["alt_text"].encode() == full
        assert original["media"]["alt_text_sha256"] == value["alt_sha256"]
        assert original["proposal_sha256"] == prepared["preparation"]["proposal_sha256"]
        for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        before = case["store"].read()
        with case["store"].projections._connection() as c:
            costs = c.execute("SELECT * FROM theheat_spending.intents ORDER BY intent_id").fetchall()
            draft = next(row for row in before[1]["drafts"] if row["id"] == case["draft_id"])
            with pytest.raises(delivery.CommandError) as held:
                delivery.hold(c, draft)
            assert held.value.code == "delivery_prior_outcome_unknown"
        assert delivery_tests.run(case, intent, "x", "upload")["outcome"] == "unknown"
        assert delivery_tests.run(case, intent, "bluesky", "upload")["outcome"] == "withheld"
        assert trace == []
        response = b'{"media_id":100,"media_id_string":"100"}'
        proof = dict(kind="accepted", instance_id=cfg["instance_id"], attempt_id=saved["attempt_id"],
            request_sha256=saved["request_sha256"], status=200, body_base64=base64.b64encode(response).decode())
        # Explicit historical server witness fixture, never a claim that this
        # test made a platform POST. Current reconciliation still performs its GET.
        witnesses.journal_path.write_text(json.dumps(dict(request=wire, body_base64=base64.b64encode(body).decode(), proof=proof))+"\n")
        assert delivery_tests.run(case, intent, "x", "upload", reconcile=True)["outcome"] == "confirmed"
        assert [r["method"] for r in trace] == ["GET"]
        created, _, _ = legacy.seed_attempt(core[3], value, package, stage="create", prior={"upload":{"media_id":"100"}})
        raw = b'{"data":{"id":"200"}}'
        with case["store"].projections._connection(writing=True) as c:
            observation = dict(attempt_id=created["attempt_id"], request_sha256=created["request_sha256"], source="response",
                reason="received", http_status=200, complete=True, raw_sha256=digest(raw), recorded_at=utc_text(editor.AT))
            delivery.observe(c, value, created, observation, raw)
            assert delivery.finish(c, value, created)["status"] == "confirmed"
            with pytest.raises(delivery.CommandError) as held:
                delivery.hold(c, draft)
            assert held.value.code == "delivery_event_already_confirmed"
            assert c.execute("SELECT * FROM theheat_spending.intents ORDER BY intent_id").fetchall() == costs
        assert case["store"].read() == before
        assert case["store"].delivery_content(case["draft_id"], intent) == original
        assert [r["method"] for r in trace] == ["GET"]
