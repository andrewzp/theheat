-- Explicit local/preview spending journal; not a production billing integration.
CREATE SCHEMA theheat_spending;
REVOKE ALL ON SCHEMA theheat_spending FROM PUBLIC;
CREATE TABLE theheat_spending.metadata (
  singleton integer PRIMARY KEY CHECK(singleton=1),
  version integer NOT NULL,
  migration_sha text NOT NULL,
  catalog_sha text NOT NULL,
  environment text NOT NULL CHECK(environment IN ('local','preview')),
  owner_role text NOT NULL,
  runtime_role text NOT NULL
);
CREATE TABLE theheat_spending.limits (
  singleton integer PRIMARY KEY CHECK(singleton=1),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 2 AND 4096),
  digest text NOT NULL CHECK(digest=encode(sha256(payload),'hex')),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz))
);
CREATE TABLE theheat_spending.intents (
  intent_id text COLLATE "C" PRIMARY KEY CHECK(intent_id ~ '^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}$'),
  job_id text COLLATE "C" NOT NULL CHECK(job_id ~ '^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}$'),
  reserve_micro_usd bigint NOT NULL CHECK(reserve_micro_usd BETWEEN 1 AND 1000000000000),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 2 AND 4096),
  digest text NOT NULL CHECK(digest=encode(sha256(payload),'hex')),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  CHECK((convert_from(payload,'UTF8')::jsonb->'intent_id') IS NOT DISTINCT FROM to_jsonb(intent_id)),
  CHECK((convert_from(payload,'UTF8')::jsonb->'job_id') IS NOT DISTINCT FROM to_jsonb(job_id)),
  CHECK((convert_from(payload,'UTF8')::jsonb->'reserve_micro_usd') IS NOT DISTINCT FROM to_jsonb(reserve_micro_usd)),
  CHECK(convert_from(payload,'UTF8')::jsonb ?& ARRAY['intent_id','job_id','reserve_micro_usd'])
);
CREATE TABLE theheat_spending.events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  intent_id text COLLATE "C" NOT NULL REFERENCES theheat_spending.intents(intent_id),
  kind text NOT NULL CHECK(kind IN ('dispatched','uncertain','released','settled')),
  recorded_at text COLLATE "C" NOT NULL CHECK(recorded_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' AND isfinite(recorded_at::timestamptz)),
  amount_micro_usd bigint CHECK(amount_micro_usd BETWEEN 0 AND 1000000000000),
  evidence_sha256 text CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
  payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 2 AND 4096),
  digest text NOT NULL CHECK(digest=encode(sha256(payload),'hex')),
  UNIQUE(intent_id,kind),
  CHECK((kind='settled' AND amount_micro_usd IS NOT NULL AND evidence_sha256 IS NOT NULL)
     OR (kind<>'settled' AND amount_micro_usd IS NULL AND evidence_sha256 IS NULL)),
  CHECK(convert_from(payload,'UTF8')::jsonb=jsonb_build_object(
    'intent_id',intent_id,'kind',kind,'recorded_at',recorded_at,
    'amount_micro_usd',amount_micro_usd,'evidence_sha256',evidence_sha256))
);
CREATE INDEX intents_recorded ON theheat_spending.intents(recorded_at DESC);
CREATE INDEX events_recorded ON theheat_spending.events(recorded_at DESC);
CREATE INDEX events_latest ON theheat_spending.events(intent_id,sequence DESC);
CREATE FUNCTION theheat_spending.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'immutable spending journal';
END;
$$;
REVOKE ALL ON FUNCTION theheat_spending.refuse_mutation() FROM PUBLIC;
CREATE TRIGGER metadata_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_spending.metadata
FOR EACH STATEMENT EXECUTE FUNCTION theheat_spending.refuse_mutation();
CREATE TRIGGER limits_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_spending.limits
FOR EACH STATEMENT EXECUTE FUNCTION theheat_spending.refuse_mutation();
CREATE TRIGGER intents_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_spending.intents
FOR EACH STATEMENT EXECUTE FUNCTION theheat_spending.refuse_mutation();
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON theheat_spending.events
FOR EACH STATEMENT EXECUTE FUNCTION theheat_spending.refuse_mutation();
CREATE FUNCTION theheat_spending.check_event() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior text; last_at text;
BEGIN
  SELECT kind,recorded_at INTO prior,last_at FROM theheat_spending.events
    WHERE intent_id=NEW.intent_id ORDER BY sequence DESC LIMIT 1;
  IF prior IS NULL THEN
    prior := 'reserved';
    SELECT recorded_at INTO last_at FROM theheat_spending.intents WHERE intent_id=NEW.intent_id;
  END IF;
  IF last_at IS NULL OR NEW.recorded_at < last_at OR NOT (
    (prior='reserved' AND NEW.kind IN ('dispatched','released')) OR
    (prior='dispatched' AND NEW.kind IN ('uncertain','settled')) OR
    (prior='uncertain' AND NEW.kind='settled')) THEN
    RAISE EXCEPTION 'invalid spending progression';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION theheat_spending.check_event() FROM PUBLIC;
CREATE TRIGGER events_progress BEFORE INSERT ON theheat_spending.events
FOR EACH ROW EXECUTE FUNCTION theheat_spending.check_event();
