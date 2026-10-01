-- Local/preview immutable graphic staging, never attachment or approval.
CREATE SCHEMA theheat_media;
REVOKE ALL ON SCHEMA theheat_media FROM PUBLIC;
CREATE TABLE theheat_media.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL,
  migration_sha text NOT NULL, catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL, runtime_role text NOT NULL
);
CREATE TABLE theheat_media.artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 8388608),
  byte_count integer NOT NULL CHECK(byte_count=octet_length(payload)),
  CHECK(sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_media.packages (
  proposal_sha256 text COLLATE "C" PRIMARY KEY CHECK(proposal_sha256 ~ '^[0-9a-f]{64}$'),
  capture_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_media.artifacts(sha),
  staged_at text COLLATE "C" NOT NULL CHECK(staged_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$' AND isfinite(staged_at::timestamptz))
);
CREATE FUNCTION theheat_media.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable media staging';
END;
$$;
REVOKE ALL ON FUNCTION theheat_media.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_media.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_media.refuse_mutation();
CREATE TRIGGER artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_media.artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_media.refuse_mutation();
CREATE TRIGGER packages_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_media.packages
FOR EACH STATEMENT EXECUTE FUNCTION theheat_media.refuse_mutation();
