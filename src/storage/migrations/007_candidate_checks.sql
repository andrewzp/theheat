-- Immutable local mandatory-check packets, requests, grants and receipts.
CREATE SCHEMA theheat_checks;
REVOKE ALL ON SCHEMA theheat_checks FROM PUBLIC;
CREATE TABLE theheat_checks.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL,
  migration_sha text NOT NULL, catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL, runtime_role text NOT NULL
);
CREATE TABLE theheat_checks.packet_artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 7000000),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_checks.request_artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 2000000),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_checks.binding_artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 8192),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_checks.receipt_artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 1000000),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_checks.sets (
  check_set_id text COLLATE "C" PRIMARY KEY CHECK(check_set_id ~ '^[0-9a-f]{64}$'),
  job_id text COLLATE "C" NOT NULL REFERENCES theheat_batches.registrations(job_id),
  custom_id text COLLATE "C" NOT NULL CHECK(length(custom_id) BETWEEN 1 AND 160),
  packet_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.packet_artifacts(sha),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)), UNIQUE(job_id,custom_id)
);
CREATE TABLE theheat_checks.attempts (
  grant_id text COLLATE "C" PRIMARY KEY CHECK(grant_id ~ '^[0-9a-f]{64}$'),
  check_set_id text COLLATE "C" NOT NULL REFERENCES theheat_checks.sets(check_set_id),
  stage text NOT NULL CHECK(stage IN ('deterministic','safety','fact_check','critic')),
  binding_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.binding_artifacts(sha),
  request_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.request_artifacts(sha),
  intent_id text COLLATE "C" UNIQUE REFERENCES theheat_spending.intents(intent_id),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)), UNIQUE(check_set_id,stage)
);
CREATE TABLE theheat_checks.receipts (
  grant_id text COLLATE "C" PRIMARY KEY REFERENCES theheat_checks.attempts(grant_id),
  receipt_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.receipt_artifacts(sha),
  disposition text NOT NULL CHECK(disposition IN ('passed','rejected','error','unavailable','stale')),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz))
);
CREATE INDEX sets_clock ON theheat_checks.sets(recorded_at);
CREATE INDEX attempts_clock ON theheat_checks.attempts(recorded_at);
CREATE INDEX receipts_clock ON theheat_checks.receipts(recorded_at);
CREATE FUNCTION theheat_checks.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable candidate checks';
END;
$$;
REVOKE ALL ON FUNCTION theheat_checks.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER packet_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.packet_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER request_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.request_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER binding_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.binding_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER receipt_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.receipt_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER sets_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.sets
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER attempts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.attempts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER receipts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.receipts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
