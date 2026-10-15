-- Explicit owner-installed invented local delivery. No production sender binding.
-- Preserve original command metadata; old binaries reject the added catalog.
CREATE TABLE theheat_commands.delivery_upgrade (
 singleton integer PRIMARY KEY CHECK(singleton=1),
 receipt_bytes bytea NOT NULL CHECK(octet_length(receipt_bytes) BETWEEN 2 AND 16384),
 sha text NOT NULL CHECK(sha=encode(sha256(receipt_bytes),'hex'))
);
CREATE TRIGGER delivery_upgrade_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_commands.delivery_upgrade
FOR EACH STATEMENT EXECUTE FUNCTION theheat_commands.refuse_mutation();
CREATE SCHEMA theheat_delivery;
REVOKE ALL ON SCHEMA theheat_delivery FROM PUBLIC;
CREATE TABLE theheat_delivery.metadata (
 singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL CHECK(version=1),
 migration_sha text NOT NULL, catalog_sha text NOT NULL,
 environment text NOT NULL CHECK(environment='local'), owner_role text NOT NULL, runtime_role text NOT NULL
);
CREATE TABLE theheat_delivery.artifacts (
 sha text COLLATE "C" PRIMARY KEY CHECK(sha=encode(sha256(payload),'hex')),
 payload bytea NOT NULL, byte_count integer NOT NULL CHECK(byte_count=octet_length(payload) AND byte_count BETWEEN 0 AND 9437184)
);
CREATE TABLE theheat_delivery.intents (
 intent_id text COLLATE "C" PRIMARY KEY,
 command_id text COLLATE "C" NOT NULL UNIQUE REFERENCES theheat_commands.results(command_id),
 draft_id text COLLATE "C" NOT NULL, event_id text COLLATE "C" NOT NULL,
 proposal_sha256 text COLLATE "C" NOT NULL REFERENCES theheat_media.packages(proposal_sha256),
 artifact_sha text COLLATE "C" NOT NULL REFERENCES theheat_delivery.artifacts(sha)
);
CREATE TABLE theheat_delivery.work_items (
 work_id text COLLATE "C" PRIMARY KEY CHECK(work_id ~ '^[0-9a-f]{64}$'),
 intent_id text COLLATE "C" NOT NULL REFERENCES theheat_delivery.intents(intent_id),
 platform text COLLATE "C" NOT NULL CHECK(platform IN ('x','bluesky')),
 UNIQUE(intent_id,platform)
);
-- Leases are append-only, as in the saved-revision checks. No UPDATE privilege.
CREATE TABLE theheat_delivery.leases (
 work_id text COLLATE "C" NOT NULL REFERENCES theheat_delivery.work_items(work_id),
 stage text COLLATE "C" NOT NULL CHECK(stage IN ('upload','alt','create')),
 fence integer NOT NULL CHECK(fence BETWEEN 1 AND 1000),
 owner text COLLATE "C" NOT NULL CHECK(octet_length(owner) BETWEEN 1 AND 128),
 recorded_at text COLLATE "C" NOT NULL, expires_at text COLLATE "C" NOT NULL,
 PRIMARY KEY(work_id,stage,fence)
);
CREATE TABLE theheat_delivery.attempts (
 attempt_id text COLLATE "C" PRIMARY KEY CHECK(attempt_id ~ '^[0-9a-f]{64}$'),
 work_id text COLLATE "C" NOT NULL, stage text COLLATE "C" NOT NULL, fence integer NOT NULL,
 binding_sha text COLLATE "C" NOT NULL REFERENCES theheat_delivery.artifacts(sha),
 request_sha text COLLATE "C" NOT NULL REFERENCES theheat_delivery.artifacts(sha),
 FOREIGN KEY(work_id,stage,fence) REFERENCES theheat_delivery.leases(work_id,stage,fence),
 UNIQUE(work_id,stage)
);
CREATE TABLE theheat_delivery.observations (
 observation_id text COLLATE "C" PRIMARY KEY CHECK(observation_id ~ '^[0-9a-f]{64}$'),
 attempt_id text COLLATE "C" NOT NULL REFERENCES theheat_delivery.attempts(attempt_id),
 metadata_sha text COLLATE "C" NOT NULL REFERENCES theheat_delivery.artifacts(sha),
 raw_sha text COLLATE "C" NOT NULL REFERENCES theheat_delivery.artifacts(sha)
);
CREATE TABLE theheat_delivery.receipts (
 observation_id text COLLATE "C" PRIMARY KEY REFERENCES theheat_delivery.observations(observation_id),
 artifact_sha text COLLATE "C" NOT NULL REFERENCES theheat_delivery.artifacts(sha)
);
CREATE FUNCTION theheat_delivery.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'immutable local delivery evidence'; END;
$$;
REVOKE ALL ON FUNCTION theheat_delivery.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.metadata FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
CREATE TRIGGER artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.artifacts FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
CREATE TRIGGER intents_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.intents FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
CREATE TRIGGER work_items_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.work_items FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
CREATE TRIGGER leases_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.leases FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
CREATE TRIGGER attempts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.attempts FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
CREATE TRIGGER observations_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.observations FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
CREATE TRIGGER receipts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_delivery.receipts FOR EACH STATEMENT EXECUTE FUNCTION theheat_delivery.refuse_mutation();
