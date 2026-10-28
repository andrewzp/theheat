"""Offline counterexamples for the GRANT assertion, not PostgreSQL evidence."""
from types import SimpleNamespace

import pytest

from src.storage import postgres_projection
from tests.stage_revision_check_helpers import assert_runtime_grant_refused


class Connection:
    def __init__(self, change=None):
        self.change = change
        self.handlers = []
        self.sent = 0
        self.profile = ("projection_runtime", True, True, False, False, "invented-exact-acl")

    def add_notice_handler(self, handler):
        self.handlers.append(handler)

    def remove_notice_handler(self, handler):
        self.handlers.remove(handler)

    def execute(self, query):
        if query == "GRANT UPDATE ON theheat_checks.stage_seals TO projection_runtime":
            self.sent += 1
            if self.change == "exception":
                raise RuntimeError("invented driver error")
            if self.change != "missing_warning":
                code = "01000" if self.change == "wrong_warning" else "01007"
                for handler in self.handlers:
                    handler(SimpleNamespace(sqlstate=code))
            fields = {"role": 0, "select": 1, "insert": 2, "update": 3, "grant_option": 4, "acl": 5}
            if self.change in fields:
                row = list(self.profile)
                row[fields[self.change]] = {"role": "owner", "select": False, "insert": False,
                    "update": True, "grant_option": True, "acl": "changed-acl"}[self.change]
                self.profile = tuple(row)
            return None
        assert query.startswith("SELECT current_user,")
        assert "UPDATE WITH GRANT OPTION" in query and "relacl::text" in query
        return SimpleNamespace(fetchone=lambda: self.profile)


@pytest.fixture
def catalog(monkeypatch):
    def read(connection, schema):
        assert schema == "theheat_checks"
        return "changed" if connection.sent and connection.change == "catalog" else "invented-catalog"
    monkeypatch.setattr(postgres_projection, "_catalog", read)


def test_documented_warning_requires_unchanged_rights_acl_and_catalog(catalog):
    connection = Connection()
    assert_runtime_grant_refused(connection)
    assert connection.sent == 1 and connection.handlers == []


@pytest.mark.parametrize("change", ["role", "select", "insert", "update", "grant_option", "acl",
                                    "catalog", "missing_warning", "wrong_warning"])
def test_no_warning_or_any_privilege_catalog_or_identity_change_refuses(change, catalog):
    connection = Connection(change)
    with pytest.raises(AssertionError):
        assert_runtime_grant_refused(connection)
    assert connection.sent == 1 and connection.handlers == []


def test_wrong_initial_role_cannot_masquerade_as_runtime_refusal(catalog):
    connection = Connection()
    connection.profile = ("owner", True, True, False, False, "invented-exact-acl")
    with pytest.raises(AssertionError):
        assert_runtime_grant_refused(connection)
    assert connection.sent == 0 and connection.handlers == []


def test_sql_exception_is_not_substituted_for_the_required_warning(catalog):
    connection = Connection("exception")
    with pytest.raises(RuntimeError, match="invented driver error"):
        assert_runtime_grant_refused(connection)
    assert connection.sent == 1 and connection.handlers == []
