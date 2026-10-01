-- Exact local check response bytes retained before any interpretation.
CREATE SCHEMA theheat_check_executions;
REVOKE ALL ON SCHEMA theheat_check_executions FROM PUBLIC;
CREATE TABLE theheat_check_executions.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL,
  migration_sha text NOT NULL, catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL, runtime_role text NOT NULL
);
CREATE TABLE theheat_check_executions.raw_artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 0 AND 131072),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_check_executions.metadata_artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 4096),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_check_executions.observations (
  grant_id text COLLATE "C" PRIMARY KEY REFERENCES theheat_checks.attempts(grant_id),
  metadata_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_check_executions.metadata_artifacts(sha),
  raw_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_check_executions.raw_artifacts(sha),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz))
);
CREATE INDEX observations_clock ON theheat_check_executions.observations(recorded_at);
CREATE FUNCTION theheat_check_executions.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable check observation';
END;
$$;
REVOKE ALL ON FUNCTION theheat_check_executions.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_check_executions.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_check_executions.refuse_mutation();
CREATE TRIGGER raw_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_check_executions.raw_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_check_executions.refuse_mutation();
CREATE TRIGGER metadata_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_check_executions.metadata_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_check_executions.refuse_mutation();
CREATE TRIGGER observations_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_check_executions.observations
FOR EACH STATEMENT EXECUTE FUNCTION theheat_check_executions.refuse_mutation();
