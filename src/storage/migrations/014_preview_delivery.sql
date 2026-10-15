-- Fresh preview delivery only, in the same owner transaction as original012.
-- The original metadata and both migration byte identities remain in the receipt.
ALTER TABLE theheat_delivery.metadata DROP CONSTRAINT metadata_environment_check;
ALTER TABLE theheat_delivery.metadata ADD CONSTRAINT metadata_environment_check CHECK(environment='preview');
