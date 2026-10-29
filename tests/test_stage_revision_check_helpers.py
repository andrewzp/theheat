"""Offline SQL-shape fixtures for the protocol assertion, never engine proofs."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.commands import check_journal
from tests.stage_revision_check_helpers import assert_protocol


class Connection:
    def __init__(self, catalog, protocol, *, present=True):
        self.catalog, self.protocol, self.present = catalog, protocol, present

    def execute(self, query, params=None):
        if query.startswith("SELECT check_set_id FROM"):
            assert params == ("invented-check",)
            row = ("invented-check",) if self.present else None
        elif query == "SELECT to_regclass('theheat_checks.schema_upgrades')":
            row = ("theheat_checks.schema_upgrades",)
        elif query == "SELECT 1 FROM theheat_checks.schema_upgrades WHERE upgrade_version=4":
            row = (1,) if self.catalog == 4 else None
        elif query.startswith("SELECT authority_protocol"):
            if self.catalog != 4:
                raise AssertionError("The legacy catalog has no authority_protocol column")
            assert params == ("invented-check",)
            row = ((self.protocol, "saved_draft_revision_v1") if "origin_kind" in query
                   else (self.protocol,)) if self.present else None
        else:
            raise AssertionError(query)
        return SimpleNamespace(fetchone=lambda: row)


def store(connection):
    @contextmanager
    def opened():
        yield connection
    return SimpleNamespace(projections=SimpleNamespace(_connection=opened))


@pytest.mark.parametrize("catalog,protocol", [(3, 1), (4, 1), (4, 2)])
def test_assertion_uses_actual_engine_protocol_for_legacy_and_upgraded_catalogs(catalog, protocol):
    assert_protocol(store(Connection(catalog, protocol)), "invented-check", protocol)


@pytest.mark.parametrize("catalog,protocol", [(3, 1), (4, 2)])
def test_missing_identity_never_inherits_an_implicit_protocol(catalog, protocol):
    with pytest.raises(AssertionError):
        assert_protocol(store(Connection(catalog, protocol, present=False)), "invented-check", protocol)


def test_legacy_catalog_never_passes_as_protocol_two():
    with pytest.raises(AssertionError):
        assert_protocol(store(Connection(3, 1)), "invented-check", 2)


def test_invalid_stored_protocol_keeps_the_actual_engine_refusal():
    with pytest.raises(check_journal.CheckJournalError, match="invalid_check_authority_protocol"):
        assert_protocol(store(Connection(4, 3)), "invented-check", 1)
