-- Explicit catalog4: old sets remain protocol1 forever.
ALTER TABLE theheat_checks.schema_upgrades DROP CONSTRAINT schema_upgrades_upgrade_version_check,
  ADD CONSTRAINT schema_upgrades_upgrade_version_check CHECK(upgrade_version IN (2,3,4));
ALTER TABLE theheat_checks.sets ADD COLUMN authority_protocol integer NOT NULL DEFAULT 1,
  ADD CONSTRAINT sets_authority_protocol CHECK(authority_protocol=1 OR
    (authority_protocol=2 AND origin_kind='saved_draft_revision_v1')),
  ADD CONSTRAINT sets_authority_unique UNIQUE(check_set_id,authority_protocol);
CREATE TABLE theheat_checks.stage_proof_artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 16384),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_checks.stage_leases (
  check_set_id text COLLATE "C" NOT NULL,
  authority_protocol integer NOT NULL DEFAULT 2 CHECK(authority_protocol=2),
  stage text NOT NULL CHECK(stage IN ('deterministic','safety','fact_check','critic')),
  fence integer NOT NULL CHECK(fence=CASE stage WHEN 'deterministic' THEN 1 WHEN 'safety' THEN 2 WHEN 'fact_check' THEN 3 WHEN 'critic' THEN 4 END),
  owner text NOT NULL CHECK(owner ~ '^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$'),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  expires_at text COLLATE "C" NOT NULL CHECK(expires_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(expires_at::timestamptz)),
  predecessor_prefix_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.stage_proof_artifacts(sha),
  capability_id text COLLATE "C" NOT NULL UNIQUE CHECK(capability_id ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY(check_set_id,stage), UNIQUE(check_set_id,fence),
  FOREIGN KEY(check_set_id,authority_protocol) REFERENCES theheat_checks.sets(check_set_id,authority_protocol),
  CHECK(EXTRACT(EPOCH FROM expires_at::timestamptz-recorded_at::timestamptz) BETWEEN 1 AND 180)
);
CREATE TABLE theheat_checks.stage_seals (
  check_set_id text COLLATE "C" NOT NULL,
  stage text NOT NULL,
  grant_id text COLLATE "C" NOT NULL UNIQUE REFERENCES theheat_checks.receipts(grant_id),
  capability_id text COLLATE "C" NOT NULL REFERENCES theheat_checks.stage_leases(capability_id),
  request_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.request_artifacts(sha),
  raw_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_check_executions.raw_artifacts(sha),
  receipt_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.receipt_artifacts(sha),
  completed_at text COLLATE "C" NOT NULL CHECK(completed_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(completed_at::timestamptz)),
  prefix_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_checks.stage_proof_artifacts(sha),
  PRIMARY KEY(check_set_id,stage),
  FOREIGN KEY(check_set_id,stage) REFERENCES theheat_checks.stage_leases(check_set_id,stage)
);
CREATE INDEX stage_leases_clock ON theheat_checks.stage_leases(recorded_at);
CREATE INDEX stage_seals_clock ON theheat_checks.stage_seals(completed_at);
CREATE TRIGGER stage_proof_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.stage_proof_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER stage_leases_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.stage_leases
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE TRIGGER stage_seals_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_checks.stage_seals
FOR EACH STATEMENT EXECUTE FUNCTION theheat_checks.refuse_mutation();
CREATE FUNCTION theheat_checks.check_stage_progress() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior record;
BEGIN
  IF NEW.fence>1 THEN
    SELECT l.owner,l.expires_at,s.prefix_sha256,s.completed_at INTO prior
    FROM theheat_checks.stage_leases l JOIN theheat_checks.stage_seals s USING(check_set_id,stage)
    WHERE l.check_set_id=NEW.check_set_id AND l.fence=NEW.fence-1;
    IF prior.owner IS NULL OR prior.owner<>NEW.owner OR NEW.recorded_at<prior.completed_at
       OR NEW.recorded_at>=prior.expires_at OR NEW.predecessor_prefix_sha256<>prior.prefix_sha256 THEN
      RAISE EXCEPTION 'invalid stage capability progression';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE FUNCTION theheat_checks.check_stage_seal() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE original record;
BEGIN
  SELECT a.check_set_id,a.stage,a.request_sha256,r.receipt_sha256,r.disposition,
         r.recorded_at,l.capability_id,l.expires_at INTO original
  FROM theheat_checks.attempts a JOIN theheat_checks.receipts r USING(grant_id)
  JOIN theheat_checks.stage_leases l USING(check_set_id,stage) WHERE a.grant_id=NEW.grant_id;
  IF original.check_set_id IS NULL OR original.check_set_id<>NEW.check_set_id OR original.stage<>NEW.stage
     OR original.request_sha256<>NEW.request_sha256 OR original.receipt_sha256<>NEW.receipt_sha256
     OR original.capability_id<>NEW.capability_id OR original.disposition<>'passed'
     OR NEW.completed_at<original.recorded_at OR NEW.completed_at>=original.expires_at THEN
    RAISE EXCEPTION 'invalid stage completion seal';
  END IF;
  RETURN NEW;
END;
$$;
CREATE FUNCTION theheat_checks.check_legacy_protocol() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM theheat_checks.sets
                WHERE check_set_id=NEW.check_set_id AND authority_protocol=1) THEN
    RAISE EXCEPTION 'legacy lease requires protocol1';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION theheat_checks.check_stage_progress() FROM PUBLIC;
REVOKE ALL ON FUNCTION theheat_checks.check_stage_seal() FROM PUBLIC;
REVOKE ALL ON FUNCTION theheat_checks.check_legacy_protocol() FROM PUBLIC;
CREATE TRIGGER stage_leases_progress BEFORE INSERT ON theheat_checks.stage_leases
FOR EACH ROW EXECUTE FUNCTION theheat_checks.check_stage_progress();
CREATE TRIGGER stage_seals_progress BEFORE INSERT ON theheat_checks.stage_seals
FOR EACH ROW EXECUTE FUNCTION theheat_checks.check_stage_seal();
CREATE TRIGGER draft_leases_protocol BEFORE INSERT ON theheat_checks.draft_leases
FOR EACH ROW EXECUTE FUNCTION theheat_checks.check_legacy_protocol();
