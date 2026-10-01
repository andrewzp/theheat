-- Local fenced ownership and bounded raw response evidence; no transport.
CREATE SCHEMA theheat_batch_work;
REVOKE ALL ON SCHEMA theheat_batch_work FROM PUBLIC;
CREATE TABLE theheat_batch_work.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL,
  migration_sha text NOT NULL, catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL, runtime_role text NOT NULL
);
CREATE TABLE theheat_batch_work.leases (
  job_id text COLLATE "C" NOT NULL REFERENCES theheat_batches.registrations(job_id),
  fence integer NOT NULL CHECK(fence BETWEEN 1 AND 1000),
  owner text NOT NULL CHECK(owner ~ '^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$'),
  expires_at text COLLATE "C" NOT NULL CHECK(expires_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(expires_at::timestamptz)), recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  PRIMARY KEY(job_id,fence),
  CHECK(EXTRACT(EPOCH FROM expires_at::timestamptz-recorded_at::timestamptz) BETWEEN 1 AND 300)
);
CREATE TABLE theheat_batch_work.submissions (
  job_id text COLLATE "C" PRIMARY KEY, fence integer NOT NULL,
  grant_id text COLLATE "C" NOT NULL CHECK(grant_id ~ '^[0-9a-f]{64}$') UNIQUE, recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  FOREIGN KEY(job_id,fence) REFERENCES theheat_batch_work.leases(job_id,fence)
);
CREATE TABLE theheat_batch_work.uncertainties (
  job_id text COLLATE "C" PRIMARY KEY REFERENCES theheat_batch_work.submissions(job_id),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz))
);
CREATE TABLE theheat_batch_work.ack_artifacts (
  sha text COLLATE "C" NOT NULL CHECK(sha ~ '^[0-9a-f]{64}$') PRIMARY KEY,
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 0 AND 65536),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_batch_work.acks (
  job_id text COLLATE "C" NOT NULL REFERENCES theheat_batch_work.submissions(job_id),
  receipt_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_batch_work.ack_artifacts(sha),
  provider_id text COLLATE "C" CHECK(provider_id ~ '^msgbatch_[A-Za-z0-9_-]{1,128}$'), recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  PRIMARY KEY(job_id,receipt_sha256)
);
CREATE TABLE theheat_batch_work.adoptions (
  job_id text COLLATE "C" PRIMARY KEY, receipt_sha256 text COLLATE "C" NOT NULL,
  provider_id text COLLATE "C" CHECK(provider_id ~ '^msgbatch_[A-Za-z0-9_-]{1,128}$') NOT NULL UNIQUE, recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  FOREIGN KEY(job_id,receipt_sha256) REFERENCES theheat_batch_work.acks(job_id,receipt_sha256)
);
CREATE INDEX acks_provider_id ON theheat_batch_work.acks(provider_id,job_id);
CREATE INDEX leases_clock ON theheat_batch_work.leases(recorded_at);
CREATE INDEX submissions_clock ON theheat_batch_work.submissions(recorded_at);
CREATE INDEX uncertainties_clock ON theheat_batch_work.uncertainties(recorded_at);
CREATE INDEX acks_clock ON theheat_batch_work.acks(recorded_at);
CREATE INDEX adoptions_clock ON theheat_batch_work.adoptions(recorded_at);
CREATE FUNCTION theheat_batch_work.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable batch worker journal';
END;
$$;
REVOKE ALL ON FUNCTION theheat_batch_work.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_work.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_work.refuse_mutation();
CREATE TRIGGER leases_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_work.leases
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_work.refuse_mutation();
CREATE TRIGGER submissions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_work.submissions
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_work.refuse_mutation();
CREATE TRIGGER uncertainties_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_work.uncertainties
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_work.refuse_mutation();
CREATE TRIGGER ack_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_work.ack_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_work.refuse_mutation();
CREATE TRIGGER acks_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_work.acks
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_work.refuse_mutation();
CREATE TRIGGER adoptions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_work.adoptions
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_work.refuse_mutation();
