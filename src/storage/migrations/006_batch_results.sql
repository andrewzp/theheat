-- Typed local batch response bytes and immutable fresh-review evidence.
CREATE SCHEMA theheat_batch_results;
REVOKE ALL ON SCHEMA theheat_batch_results FROM PUBLIC;
CREATE TABLE theheat_batch_results.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL,
  migration_sha text NOT NULL, catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL, runtime_role text NOT NULL
);
CREATE TABLE theheat_batch_results.metadata_artifacts (
  sha text COLLATE "C" NOT NULL CHECK(sha ~ '^[0-9a-f]{64}$') PRIMARY KEY,
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 0 AND 65536),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_batch_results.result_artifacts (
  sha text COLLATE "C" NOT NULL CHECK(sha ~ '^[0-9a-f]{64}$') PRIMARY KEY,
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 0 AND 3000000),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_batch_results.report_artifacts (
  sha text COLLATE "C" NOT NULL CHECK(sha ~ '^[0-9a-f]{64}$') PRIMARY KEY,
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 0 AND 4000000),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_batch_results.receipts (
  receipt_id text COLLATE "C" NOT NULL CHECK(receipt_id ~ '^[0-9a-f]{64}$') PRIMARY KEY,
  job_id text COLLATE "C" NOT NULL REFERENCES theheat_batch_work.submissions(job_id),
  grant_id text COLLATE "C" NOT NULL CHECK(grant_id ~ '^[0-9a-f]{64}$'),
  metadata_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_batch_results.metadata_artifacts(sha),
  results_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_batch_results.result_artifacts(sha),
  binding bytea NOT NULL CHECK(octet_length(binding) BETWEEN 2 AND 4096),
  binding_sha256 text COLLATE "C" NOT NULL CHECK(binding_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)), UNIQUE(job_id,receipt_id),
  CHECK(binding_sha256=encode(sha256(binding),'hex'))
);
CREATE TABLE theheat_batch_results.choices (
  job_id text COLLATE "C" PRIMARY KEY,
  receipt_id text COLLATE "C" NOT NULL,
  semantic_sha256 text COLLATE "C" NOT NULL CHECK(semantic_sha256 ~ '^[0-9a-f]{64}$'),
  FOREIGN KEY(job_id,receipt_id) REFERENCES theheat_batch_results.receipts(job_id,receipt_id)
);
CREATE TABLE theheat_batch_results.reviews (
  review_id text COLLATE "C" NOT NULL CHECK(review_id ~ '^[0-9a-f]{64}$') PRIMARY KEY,
  job_id text COLLATE "C" NOT NULL, receipt_id text COLLATE "C" NOT NULL,
  fence integer NOT NULL,
  report_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_batch_results.report_artifacts(sha),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  FOREIGN KEY(job_id,receipt_id) REFERENCES theheat_batch_results.receipts(job_id,receipt_id),
  FOREIGN KEY(job_id,fence) REFERENCES theheat_batch_work.leases(job_id,fence)
);
CREATE INDEX receipts_clock ON theheat_batch_results.receipts(recorded_at);
CREATE INDEX reviews_clock ON theheat_batch_results.reviews(recorded_at);
CREATE INDEX reviews_job ON theheat_batch_results.reviews(job_id,review_id);
CREATE FUNCTION theheat_batch_results.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable batch results';
END;
$$;
REVOKE ALL ON FUNCTION theheat_batch_results.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_results.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_results.refuse_mutation();
CREATE TRIGGER metadata_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_results.metadata_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_results.refuse_mutation();
CREATE TRIGGER result_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_results.result_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_results.refuse_mutation();
CREATE TRIGGER report_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_results.report_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_results.refuse_mutation();
CREATE TRIGGER receipts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_results.receipts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_results.refuse_mutation();
CREATE TRIGGER choices_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_results.choices
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_results.refuse_mutation();
CREATE TRIGGER reviews_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_batch_results.reviews
FOR EACH STATEMENT EXECUTE FUNCTION theheat_batch_results.refuse_mutation();
