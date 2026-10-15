"""Genuine retained alternate source through native render, fresh review and restore."""

from copy import deepcopy
from uuid import uuid4

import pytest

from src.commands import postgres_important_variants as group
from src.editorial.revisions import fingerprint
from tests import test_postgres_important_variants as variants, test_postgres_editor_media as editor
from tests.test_postgres_important_variants import important as important
from tests.test_postgres_sourced_generation import sourced as sourced
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.test_postgres_editor_media import offline_connections as offline_connections


@pytest.fixture(params=["modis", "pm25"])
def important_native(important, request, core, tmp_path, monkeypatch, native_dependencies):
    if request.param == "modis":
        from tests.fire_graphic_helpers import graphic_bundle

        bundle = graphic_bundle()
        texts = [
            "MODIS detected a 500 MW thermal signal in an invented region.",
            "A 500 MW thermal signal was detected by MODIS in this invented region.",
        ]
        source_key = "firms"
    else:
        from src.data.air_quality import _parse_single_location, detect_pm25_hazard
        from src.two_bot.intern.air_quality import build_pm25_hazard_bundle
        from src.data.places import resolve_place
        from tests.air_quality_fixtures import payload

        place = resolve_place("Kathmandu", "Nepal")
        day = "2026-06-08"
        data = payload(day=day, timezone="Asia/Kathmandu", offset=20700, lat=27.75, lon=85.25)
        data["hourly"]["pm2_5"] = list(range(160, 184))
        observed = _parse_single_location(
            data,
            "Kathmandu",
            "Nepal",
            place["lat"],
            place["lon"],
            day,
            requested_at=day + "T12:00:00Z",
            retrieved_at=day + "T12:00:01Z",
        )
        bundle = build_pm25_hazard_bundle(detect_pm25_hazard(observed))
        texts = [
            "The PM2.5 forecast averages 172 micrograms per cubic metre in Kathmandu.",
            "The modeled US AQI forecast reaches 210 in Kathmandu.",
        ]
        source_key = "air_quality"
    case = variants.nominate_source(important, bundle, source_key, texts)
    variants.capture(case)
    variants.complete(variants.enroll(case, 1), monkeypatch)
    variants.complete(variants.enroll(case, 2), monkeypatch)
    result = variants.consume(case, variants.slate_command(case), at=variants.AT)
    assert result["status"] == "applied", result
    case["draft_id"] = result["candidate"]["draft_id"]
    core[2].initialize_media_staging()
    core[2].initialize_media_commands()
    core[2].initialize_revision_checks(now=variants.AT)
    case["store"].configure_editor_media(
        **native_dependencies, scratch=tmp_path / "important-native"
    )
    return case


def park(case, monkeypatch):
    current = editor.view(case)
    if current["status"] == "attached":
        # Selection preserves the retained image, but its text/image review is
        # invalidated. Perform the actual five-confirmation review anew.
        assert not current["review_current"] and not current["parked"]
        prepared = current
        png = editor.view(case, png=current["preparation"]["proposal_sha256"])
        _, reviewed = editor.action(
            case,
            "review_media_revision",
            dict(
                proposal_sha256=current["preparation"]["proposal_sha256"],
                expected_policy_sha256=current["expected_policy_sha256"],
                expected_packet_sha256=current["packet"]["packet_sha256"],
                review=dict(
                    decision="accept",
                    confirmations={key: True for key in editor.CONFIRMATIONS},
                    reason="Invented retained graphic and newly selected genuine alternate reviewed together.",
                ),
            ),
        )
        assert reviewed["status"] == "applied", reviewed
    else:
        prepared, png = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    current = editor.view(case)
    assert current["review_current"] and current["checks_status"] == "passed"
    cmd, result = editor.action(
        case,
        "approve_media_revision",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_renderer_profile_sha256=current["expected_renderer_profile_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            expected_review_sha256=current["expected_review_sha256"],
            expected_check_completion_sha256=current["expected_check_completion_sha256"],
            reason="Invented local important-event review; no sender.",
        ),
        actor=variants.candidate.PUBLISHER,
    )
    assert result["status"] == "applied" and editor.view(case)["parked"]
    return cmd, result, prepared, png


def test_slate_native_review_park_alternate_and_original_invalidation(
    important_native, monkeypatch
):
    case = important_native
    _, _, prepared, png = park(case, monkeypatch)
    from tests import test_postgres_cost_projection as old_cost

    with monkeypatch.context() as passive:
        old_cost.passive_traps(passive)
        costs = case["store"].local_cost_projection(now=variants.AT)
    assert costs["status"] == "available", costs
    assert (
        len(costs["requests"]) == 10 and costs["summary"]["commitments_micro_usd"]["held"] == "65"
    )
    assert all(row["origin"]["brief_id"] == case["refs"]["brief_id"] for row in costs["requests"])
    with case["store"].projections._connection() as c:
        before = deepcopy(group.read(c, group.ADMISSION, case["result"]["generation"]["job_id"]))
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    alternate = next(row for row in draft["candidates"] if row["rank"] == 2)
    _, selected = editor.action(
        case, "select_candidate", dict(candidate_rank=2, candidate_sha256=fingerprint(alternate))
    )
    assert selected["status"] == "applied"
    stale = editor.view(case)
    assert (
        not stale["parked"]
        and not stale["review_current"]
        and stale.get("checks_status") != "passed"
    )
    case["text"] = alternate["text"]
    park(case, monkeypatch)
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    original = next(row for row in draft["candidates"] if row["rank"] == 1)
    assert (
        editor.action(
            case, "select_candidate", dict(candidate_rank=1, candidate_sha256=fingerprint(original))
        )[1]["status"]
        == "applied"
    )
    final = editor.view(case)
    assert (
        not final["parked"]
        and not final["review_current"]
        and final.get("checks_status") != "passed"
    )
    with case["store"].projections._connection() as c:
        assert group.read(c, group.ADMISSION, case["result"]["generation"]["job_id"]) == before
    assert editor.view(case, png=prepared["preparation"]["proposal_sha256"]) == png


@pytest.mark.parametrize("important_native", ["modis"], indirect=True)
def test_restore_retains_slate_source_media_grants_and_costs(
    important_native, monkeypatch, core, cluster
):
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options

    case = important_native
    cmd, result, prepared, png = park(case, monkeypatch)
    before = editor.all_application_rows(core[3])
    state = case["store"].read()
    view = editor.view(case)
    params, run, directory = cluster
    dump = directory / ("important-" + uuid4().hex + ".dump")
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = dict(core[3], dbname=name)
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        authority = PostgresCommandAuthority(**options(restored_params))
        authority.configure_sourced_generation(lambda: case["config"])
        authority.configure_important_variants(
            lambda: dict(allowance_id=case["allowance_refs"]["allowance_id"])
        )
        authority.configure_editor_media(**case["store"].editor_media_configuration)
        restored = dict(case, store=authority)
        assert authority.read() == state and editor.all_application_rows(restored_params) == before
        assert (
            editor.view(restored) == view
            and editor.view(restored, png=prepared["preparation"]["proposal_sha256"]) == png
        )
        assert (
            authority.consume(
                variants.candidate.resolve, command_id=cmd.command_id, now=variants.AT
            )
            == result
        )
        assert editor.all_application_rows(restored_params) == before
    finally:
        admin(
            params,
            psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)),
        )
