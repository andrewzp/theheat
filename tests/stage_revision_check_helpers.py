"""Tests-only explicit installation; no caller-selected production protocol."""


def install_revision_protocol(owner, request=None, *, now):
    marker = request.node.get_closest_marker("revision_check_protocol") if request else None
    if marker is not None:
        assert marker.args == (1,) and not marker.kwargs, "Only explicit historical v1 is selectable"
        owner.initialize_revision_checks(now=now)
    else:
        owner.initialize_stage_revision_checks(now=now)


def assert_protocol(store, identity, expected=2):
    from src.commands.postgres_stage_revision_checks import protocol

    with store.projections._connection() as c:
        retained = c.execute(
            "SELECT check_set_id FROM theheat_checks.sets WHERE check_set_id=%s",
            (identity,),
        ).fetchone()
        # Catalog3 stores protocol1 implicitly; catalog4 records it explicitly.
        # Keep the identity existence check, then use the actual engine's rule.
        row = (protocol(c, identity),) if retained == (identity,) else None
    assert row == (expected,), (identity, row, expected)


def stage_rows(params, identity):
    from tests.test_postgres_projection import admin

    return admin(params, "SELECT stage,fence,owner,recorded_at,expires_at,capability_id "
                 "FROM theheat_checks.stage_leases WHERE check_set_id=%s ORDER BY fence", (identity,))
