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


def assert_runtime_grant_refused(connection):
    """Prove no escalation: PostgreSQL may warn instead of raising for GRANT.

    A non-owner with ordinary privileges receives privilege_not_granted (01007)
    for an unavailable grant option. The real ACL and effective rights must stay
    unchanged. See https://www.postgresql.org/docs/17/sql-grant.html#SQL-GRANT-NOTES
    """
    from src.storage import postgres_projection

    profile = (
        "SELECT current_user,"
        "has_table_privilege(current_user,'theheat_checks.stage_seals','SELECT'),"
        "has_table_privilege(current_user,'theheat_checks.stage_seals','INSERT'),"
        "has_table_privilege(current_user,'theheat_checks.stage_seals','UPDATE'),"
        "has_table_privilege(current_user,'theheat_checks.stage_seals','UPDATE WITH GRANT OPTION'),"
        "(SELECT relacl::text FROM pg_class WHERE oid='theheat_checks.stage_seals'::regclass)"
    )
    before = connection.execute(profile).fetchone()
    assert before is not None and before[:5] == ("projection_runtime", True, True, False, False)
    catalog = postgres_projection._catalog(connection, "theheat_checks")
    notices = []

    def notice(value):
        notices.append(value.sqlstate)  # Diagnostics are valid only in callback.

    connection.add_notice_handler(notice)
    try:
        connection.execute("GRANT UPDATE ON theheat_checks.stage_seals TO projection_runtime")
    finally:
        connection.remove_notice_handler(notice)
    assert notices == ["01007"], notices
    assert connection.execute(profile).fetchone() == before
    assert postgres_projection._catalog(connection, "theheat_checks") == catalog
