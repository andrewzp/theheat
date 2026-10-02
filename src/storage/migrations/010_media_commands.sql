-- Local/preview joint-review references. Applying the draft and terminal receipt
-- is performed in the existing command authority transaction, never by a trigger.
CREATE SCHEMA theheat_media_commands;
REVOKE ALL ON SCHEMA theheat_media_commands FROM PUBLIC;
CREATE TABLE theheat_media_commands.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL,
  migration_sha text NOT NULL, catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL, runtime_role text NOT NULL
);
CREATE TABLE theheat_media_commands.reviews (
  command_id text COLLATE "C" PRIMARY KEY REFERENCES theheat_commands.intents(command_id),
  proposal_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_media.packages(proposal_sha256),
  review_sha256 text COLLATE "C" NOT NULL CHECK(review_sha256 ~ '^[0-9a-f]{64}$'),
  artifact_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_media.artifacts(sha),
  reviewed_at text COLLATE "C" NOT NULL CHECK(reviewed_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$' AND isfinite(reviewed_at::timestamptz))
);
CREATE FUNCTION theheat_media_commands.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable media command review';
END;
$$;
REVOKE ALL ON FUNCTION theheat_media_commands.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_media_commands.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_media_commands.refuse_mutation();
CREATE TRIGGER reviews_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_media_commands.reviews
FOR EACH STATEMENT EXECUTE FUNCTION theheat_media_commands.refuse_mutation();
