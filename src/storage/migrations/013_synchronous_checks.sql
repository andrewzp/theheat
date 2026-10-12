-- Owner-only additive check origin. Original metadata and upgrade2 are untouched.
ALTER TABLE theheat_checks.schema_upgrades DROP CONSTRAINT schema_upgrades_upgrade_version_check,
  ADD CONSTRAINT schema_upgrades_upgrade_version_check CHECK(upgrade_version IN (2,3));
ALTER TABLE theheat_checks.sets
  ADD COLUMN sync_namespace text COLLATE "C",
  ADD COLUMN sync_enrollment_id text COLLATE "C",
  DROP CONSTRAINT sets_origin,
  ADD CONSTRAINT sets_origin CHECK (((origin_kind='batch_candidate'
    AND job_id IS NOT NULL AND custom_id IS NOT NULL
    AND draft_namespace IS NULL AND draft_enrollment_id IS NULL
    AND sync_namespace IS NULL AND sync_enrollment_id IS NULL)
    OR (origin_kind='saved_draft_revision_v1' AND job_id IS NULL AND custom_id IS NULL
    AND draft_namespace='draft-check-enrollment-v1'
    AND draft_enrollment_id IS NOT NULL AND draft_enrollment_id ~ '^[0-9a-f]{64}$'
    AND sync_namespace IS NULL AND sync_enrollment_id IS NULL)
    OR (origin_kind='synchronous_writer_v1' AND job_id IS NULL AND custom_id IS NULL
    AND draft_namespace IS NULL AND draft_enrollment_id IS NULL
    AND sync_namespace='synchronous-check-enrollment-v1'
    AND sync_enrollment_id IS NOT NULL AND sync_enrollment_id ~ '^[0-9a-f]{64}$')) IS TRUE),
  ADD CONSTRAINT sets_sync_projection FOREIGN KEY(sync_namespace,sync_enrollment_id)
    REFERENCES theheat_projection.versions(namespace,snapshot_id) MATCH FULL,
  ADD CONSTRAINT sets_sync_unique UNIQUE(sync_namespace,sync_enrollment_id);
ALTER TABLE theheat_checks.draft_leases DROP CONSTRAINT draft_leases_origin_kind_check,
  ADD CONSTRAINT draft_leases_origin_kind_check
    CHECK(origin_kind IN ('saved_draft_revision_v1','synchronous_writer_v1'));
