-- Explicit owner-only evolution; original 007/008 metadata remains immutable.
CREATE TABLE theheat_checks.schema_upgrades (
  upgrade_version integer PRIMARY KEY CHECK(upgrade_version=2),
  receipt_bytes bytea NOT NULL CHECK(octet_length(receipt_bytes) BETWEEN 1 AND 16384),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(receipt_bytes)),
  sha text COLLATE "C" NOT NULL CHECK(sha=encode(sha256(receipt_bytes),'hex'))
);
CREATE TRIGGER schema_upgrades_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON theheat_checks.schema_upgrades FOR EACH STATEMENT
EXECUTE FUNCTION theheat_checks.refuse_mutation();

ALTER TABLE theheat_checks.sets
  ADD COLUMN origin_kind text COLLATE "C" NOT NULL DEFAULT 'batch_candidate',
  ADD COLUMN draft_namespace text COLLATE "C",
  ADD COLUMN draft_enrollment_id text COLLATE "C",
  ALTER COLUMN job_id DROP NOT NULL,
  ALTER COLUMN custom_id DROP NOT NULL,
  ADD CONSTRAINT sets_origin CHECK (((origin_kind='batch_candidate'
    AND job_id IS NOT NULL AND custom_id IS NOT NULL
    AND draft_namespace IS NULL AND draft_enrollment_id IS NULL)
    OR (origin_kind='saved_draft_revision_v1'
    AND job_id IS NULL AND custom_id IS NULL
    AND draft_namespace='draft-check-enrollment-v1'
    AND draft_enrollment_id IS NOT NULL
    AND draft_enrollment_id ~ '^[0-9a-f]{64}$')) IS TRUE),
  ADD CONSTRAINT sets_draft_projection FOREIGN KEY(draft_namespace,draft_enrollment_id)
    REFERENCES theheat_projection.versions(namespace,snapshot_id) MATCH FULL,
  ADD CONSTRAINT sets_draft_unique UNIQUE(draft_namespace,draft_enrollment_id),
  ADD CONSTRAINT sets_origin_unique UNIQUE(check_set_id,origin_kind);

CREATE TABLE theheat_checks.draft_leases (
  check_set_id text COLLATE "C" NOT NULL CHECK(check_set_id ~ '^[0-9a-f]{64}$'),
  origin_kind text COLLATE "C" NOT NULL DEFAULT 'saved_draft_revision_v1'
    CHECK(origin_kind='saved_draft_revision_v1'),
  fence integer NOT NULL CHECK(fence BETWEEN 1 AND 1000),
  owner text NOT NULL CHECK(owner ~ '^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$'),
  expires_at text COLLATE "C" NOT NULL CHECK(expires_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(expires_at::timestamptz)),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  PRIMARY KEY(check_set_id,fence),
  FOREIGN KEY(check_set_id,origin_kind) REFERENCES theheat_checks.sets(check_set_id,origin_kind),
  CHECK(EXTRACT(EPOCH FROM expires_at::timestamptz-recorded_at::timestamptz) BETWEEN 1 AND 300)
);
CREATE INDEX draft_leases_clock ON theheat_checks.draft_leases(recorded_at);
CREATE TRIGGER draft_leases_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON theheat_checks.draft_leases FOR EACH STATEMENT
EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE FUNCTION theheat_checks.check_draft_lease() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior record;
BEGIN
  SELECT fence,expires_at INTO prior FROM theheat_checks.draft_leases
  WHERE check_set_id=NEW.check_set_id ORDER BY fence DESC LIMIT 1;
  IF (prior.fence IS NULL AND NEW.fence<>1) OR
     (prior.fence IS NOT NULL AND (NEW.fence<>prior.fence+1 OR NEW.recorded_at<prior.expires_at)) THEN
    RAISE EXCEPTION 'invalid draft check lease progression';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION theheat_checks.check_draft_lease() FROM PUBLIC;
CREATE TRIGGER draft_leases_progress BEFORE INSERT ON theheat_checks.draft_leases
FOR EACH ROW EXECUTE FUNCTION theheat_checks.check_draft_lease();
