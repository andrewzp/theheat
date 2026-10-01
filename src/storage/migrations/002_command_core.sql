-- Isolated local command authority, never selected by the production application.
CREATE SCHEMA theheat_commands;
REVOKE ALL ON SCHEMA theheat_commands FROM PUBLIC;
CREATE TABLE theheat_commands.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1),
  version integer NOT NULL,
  migration_sha text NOT NULL,
  catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL,
  runtime_role text NOT NULL
);
CREATE TABLE theheat_commands.state (
  singleton integer PRIMARY KEY CHECK(singleton=1),
  version bigint NOT NULL CHECK(version BETWEEN 0 AND 9007199254740991),
  namespace text COLLATE "C" NOT NULL CHECK(namespace='command-core-v1'),
  snapshot_id text COLLATE "C" NOT NULL CHECK(snapshot_id=version::text),
  FOREIGN KEY(namespace,snapshot_id) REFERENCES theheat_projection.versions(namespace,snapshot_id)
);
CREATE TABLE theheat_commands.intents (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  command_id text COLLATE "C" NOT NULL UNIQUE CHECK(command_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  digest text NOT NULL CHECK(digest=encode(sha256(command_bytes),'hex')),
  command_bytes bytea NOT NULL CHECK(octet_length(command_bytes) BETWEEN 2 AND 133120),
  accepted_at text NOT NULL
);
CREATE TABLE theheat_commands.results (
  command_id text COLLATE "C" PRIMARY KEY REFERENCES theheat_commands.intents(command_id),
  result_bytes bytea NOT NULL CHECK(octet_length(result_bytes) BETWEEN 2 AND 1048576),
  digest text NOT NULL CHECK(digest=encode(sha256(result_bytes),'hex')),
  state_version bigint NOT NULL CHECK(state_version BETWEEN 0 AND 9007199254740991),
  namespace text COLLATE "C" NOT NULL CHECK(namespace='command-core-v1'),
  snapshot_id text COLLATE "C" NOT NULL CHECK(snapshot_id=state_version::text),
  FOREIGN KEY(namespace,snapshot_id) REFERENCES theheat_projection.versions(namespace,snapshot_id)
);
CREATE TABLE theheat_commands.events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  command_id text COLLATE "C" NOT NULL REFERENCES theheat_commands.intents(command_id),
  event text NOT NULL CHECK(event IN ('accepted','completed')),
  recorded_at text NOT NULL,
  data_bytes bytea NOT NULL CHECK(octet_length(data_bytes) BETWEEN 2 AND 1048576),
  digest text NOT NULL CHECK(digest=encode(sha256(data_bytes),'hex')),
  UNIQUE(command_id,event)
);
CREATE FUNCTION theheat_commands.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable command journal';
END;
$$;
REVOKE ALL ON FUNCTION theheat_commands.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_commands.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_commands.refuse_mutation();
CREATE TRIGGER intents_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_commands.intents
FOR EACH STATEMENT EXECUTE FUNCTION theheat_commands.refuse_mutation();
CREATE TRIGGER results_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_commands.results
FOR EACH STATEMENT EXECUTE FUNCTION theheat_commands.refuse_mutation();
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_commands.events
FOR EACH STATEMENT EXECUTE FUNCTION theheat_commands.refuse_mutation();
CREATE TRIGGER state_retained BEFORE DELETE OR TRUNCATE ON theheat_commands.state
FOR EACH STATEMENT EXECUTE FUNCTION theheat_commands.refuse_mutation();
CREATE FUNCTION theheat_commands.check_progress() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE expected_count integer; expected_bytes integer; actual_count bigint; actual_bytes bigint;
BEGIN
  IF NEW.singleton<>OLD.singleton OR NEW.version<>OLD.version+1 OR NEW.namespace<>OLD.namespace THEN
    RAISE EXCEPTION 'invalid authority progression';
  END IF;
  SELECT field_count,byte_count INTO expected_count,expected_bytes
    FROM theheat_projection.versions WHERE namespace=NEW.namespace AND snapshot_id=NEW.snapshot_id;
  SELECT count(*),COALESCE(sum(octet_length(f.name_json)+1+a.byte_count),0)+2+greatest(count(*)-1,0)
    INTO actual_count,actual_bytes FROM theheat_projection.fields f
    JOIN theheat_projection.artifacts a ON a.sha=f.artifact_sha
    WHERE f.namespace=NEW.namespace AND f.snapshot_id=NEW.snapshot_id;
  IF expected_count IS NULL OR expected_count<>actual_count OR expected_bytes<>actual_bytes THEN
    RAISE EXCEPTION 'incomplete authority projection';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION theheat_commands.check_progress() FROM PUBLIC;
CREATE TRIGGER state_progress BEFORE UPDATE ON theheat_commands.state
FOR EACH ROW EXECUTE FUNCTION theheat_commands.check_progress();
