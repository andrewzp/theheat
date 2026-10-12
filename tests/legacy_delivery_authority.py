"""Exact _validate body from reviewed parent 0d678ef1752cdb244d889fb2ef2980f042dde21c.

Only the subclass wrapper and imports are test scaffolding. Its inherited approve
and consume paths invoke this actual prior validator, which must refuse migration012.
"""
from src.commands.postgres_authority import PostgresCommandAuthority, SCHEMA, MIGRATION
from src.storage import postgres_projection as p


class LegacyAuthority(PostgresCommandAuthority):
    def _validate(self, c, *, runtime: bool = True) -> None:
        self.projections._validate(c, runtime=runtime)
        row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
        p._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()),
                   "unsupported_command_schema")
        p._require(row[2] == p._catalog(c, SCHEMA), "changed_command_schema")
        p._require(row[3] == self.environment, "command_environment_mismatch")
        roles = c.execute(f"SELECT owner_role,runtime_role FROM {p.SCHEMA}.metadata WHERE singleton=1").fetchone()
        p._require(tuple(row[4:]) == roles, "command_role_mismatch")
        if not runtime:
            p._require(row[4] == self.projections.user, "migration_owner_required")
