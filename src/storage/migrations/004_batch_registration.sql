-- Exact local batch plans joined atomically to their immutable spending holds.
CREATE SCHEMA theheat_batches;
REVOKE ALL ON SCHEMA theheat_batches FROM PUBLIC;
CREATE TABLE theheat_batches.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1),
  version integer NOT NULL,
  migration_sha text NOT NULL,
  catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL,
  runtime_role text NOT NULL
);
CREATE TABLE theheat_batches.plans (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 2 AND 2000000),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_batches.registrations (
  job_id text COLLATE "C" PRIMARY KEY CHECK(job_id ~ '^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$'),
  plan_sha text COLLATE "C" NOT NULL UNIQUE REFERENCES theheat_batches.plans(sha),
  intent_id text COLLATE "C" NOT NULL UNIQUE REFERENCES theheat_spending.intents(intent_id),
  registered_at text COLLATE "C" NOT NULL CHECK(registered_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(registered_at::timestamptz))
);
CREATE FUNCTION theheat_batches.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable batch registration';
END;
$$;
REVOKE ALL ON FUNCTION theheat_batches.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batches.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batches.refuse_mutation();
CREATE TRIGGER plans_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batches.plans
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batches.refuse_mutation();
CREATE TRIGGER registrations_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batches.registrations
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batches.refuse_mutation();
