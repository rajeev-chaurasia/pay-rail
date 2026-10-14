-- Run once with the schema-owner identity after Flyway migrations.
-- Provision the LOGIN identity and authentication separately, then grant this role.
\set ON_ERROR_STOP on
begin;
create role payrail_runtime nologin nosuperuser nocreatedb nocreaterole nobypassrls;
revoke create on schema public from public;
grant usage on schema public to payrail_runtime;
grant select on tenants, api_keys, payment_intents, refunds, idempotency_records,
  ledger_transactions, ledger_entries, outbox_events, processed_events,
  simulated_provider_operations, payment_intents_v2, migration_checkpoints
  to payrail_runtime;
grant insert, update on payment_intents, idempotency_records, ledger_transactions,
  outbox_events, simulated_provider_operations, payment_intents_v2
  to payrail_runtime;
grant insert on refunds, ledger_entries, processed_events to payrail_runtime;
grant update on migration_checkpoints to payrail_runtime;
grant usage, select on all sequences in schema public to payrail_runtime;
commit;
