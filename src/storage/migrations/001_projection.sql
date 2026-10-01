-- Local/preview projection archive only; no live-state pointer or posting authority.
CREATE SCHEMA theheat_projection;
REVOKE ALL ON SCHEMA theheat_projection FROM PUBLIC;
CREATE TABLE theheat_projection.metadata (
  singleton integer PRIMARY KEY CHECK (singleton=1),
  version integer NOT NULL,
  migration_sha text NOT NULL,
  catalog_sha text NOT NULL,
  environment text NOT NULL CHECK (environment IN ('local','preview')),
  owner_role text NOT NULL,
  runtime_role text NOT NULL
);
CREATE TABLE theheat_projection.artifacts (
  sha text COLLATE "C" PRIMARY KEY CHECK (sha ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK (octet_length(payload) BETWEEN 1 AND 16777216),
  byte_count integer NOT NULL CHECK (byte_count=octet_length(payload)),
  CONSTRAINT artifact_identity CHECK (sha=encode(sha256(payload),'hex'))
);
CREATE TABLE theheat_projection.versions (
  namespace text COLLATE "C" NOT NULL,
  snapshot_id text COLLATE "C" NOT NULL,
  canonical_sha text NOT NULL CHECK (canonical_sha ~ '^[0-9a-f]{64}$'),
  byte_count integer NOT NULL CHECK (byte_count BETWEEN 2 AND 16777216),
  field_count integer NOT NULL CHECK (field_count BETWEEN 0 AND 512),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  PRIMARY KEY (namespace,snapshot_id),
  CHECK (namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$'),
  CHECK (snapshot_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$')
);
CREATE TABLE theheat_projection.fields (
  namespace text COLLATE "C" NOT NULL,
  snapshot_id text COLLATE "C" NOT NULL,
  name_json bytea NOT NULL CHECK (octet_length(name_json) BETWEEN 2 AND 1024),
  artifact_sha text COLLATE "C" NOT NULL REFERENCES theheat_projection.artifacts(sha),
  PRIMARY KEY (namespace,snapshot_id,name_json),
  FOREIGN KEY (namespace,snapshot_id) REFERENCES theheat_projection.versions(namespace,snapshot_id)
);
CREATE FUNCTION theheat_projection.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable projection archive';
END;
$$;
REVOKE ALL ON FUNCTION theheat_projection.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_projection.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_projection.refuse_mutation();
CREATE TRIGGER artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_projection.artifacts
FOR EACH STATEMENT EXECUTE FUNCTION theheat_projection.refuse_mutation();
CREATE TRIGGER versions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_projection.versions
FOR EACH STATEMENT EXECUTE FUNCTION theheat_projection.refuse_mutation();
CREATE TRIGGER fields_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_projection.fields
FOR EACH STATEMENT EXECUTE FUNCTION theheat_projection.refuse_mutation();
