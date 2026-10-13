create table payment_intents_v2 (
  source_id text primary key,
  tenant_id text not null references tenants(id),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code text not null check (currency_code ~ '^[a-z]{3}$'),
  capture_method text not null,
  lifecycle_status text not null,
  capturable_minor bigint not null default 0 check (capturable_minor >= 0),
  captured_minor bigint not null default 0 check (captured_minor >= 0),
  refunded_minor bigint not null default 0 check (refunded_minor >= 0),
  source_version bigint not null,
  metadata jsonb not null default '{}'::jsonb,
  source_created_at timestamptz not null,
  source_updated_at timestamptz not null,
  migrated_at timestamptz not null default now(),
  foreign key (tenant_id, source_id) references payment_intents(tenant_id, id)
);
create index payment_intents_v2_tenant_source_idx on payment_intents_v2(tenant_id, source_id);

create table migration_checkpoints (
  migration_name text primary key,
  last_key text,
  rows_processed bigint not null default 0,
  cutover_ready boolean not null default false,
  updated_at timestamptz not null default now()
);
insert into migration_checkpoints(migration_name) values ('payment_intents_v2_backfill');
