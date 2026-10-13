create table tenants (
  id text primary key,
  name text not null,
  created_at timestamptz not null default now()
);

create table api_keys (
  id bigint generated always as identity primary key,
  tenant_id text not null references tenants(id),
  key_hash text not null unique,
  label text not null,
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);
create index api_keys_tenant_id_idx on api_keys(tenant_id);

create table payment_intents (
  id text primary key,
  tenant_id text not null references tenants(id),
  amount bigint not null check (amount > 0),
  amount_capturable bigint not null default 0 check (amount_capturable >= 0),
  amount_received bigint not null default 0 check (amount_received >= 0),
  amount_refunded bigint not null default 0 check (amount_refunded >= 0),
  currency text not null check (currency ~ '^[a-z]{3}$'),
  capture_method text not null check (capture_method in ('automatic','manual')),
  status text not null check (status in ('requires_confirmation','processing','authorized','succeeded','failed','partially_refunded','refunded','canceled')),
  version bigint not null default 0,
  provider_reference text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id)
);
create index payment_intents_tenant_created_idx on payment_intents(tenant_id, created_at desc, id desc);

create table refunds (
  id text primary key,
  tenant_id text not null references tenants(id),
  payment_intent_id text not null,
  amount bigint not null check (amount > 0),
  status text not null check (status in ('succeeded')),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, payment_intent_id) references payment_intents(tenant_id, id)
);
create index refunds_payment_intent_id_idx on refunds(payment_intent_id);

create table idempotency_records (
  tenant_id text not null references tenants(id),
  idempotency_key text not null,
  operation text not null,
  request_fingerprint text not null,
  response_status integer,
  api_version text not null default '2026-01-01',
  response_headers jsonb not null default '{}'::jsonb,
  response_body text,
  completed boolean not null default false,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '24 hours',
  primary key (tenant_id, idempotency_key)
);

create table ledger_transactions (
  id text primary key,
  tenant_id text not null references tenants(id),
  payment_intent_id text not null,
  effect_key text not null,
  currency text not null,
  posted boolean not null default false,
  created_at timestamptz not null default now(),
  unique (tenant_id, effect_key),
  foreign key (tenant_id, payment_intent_id) references payment_intents(tenant_id, id)
);
create index ledger_transactions_payment_idx on ledger_transactions(payment_intent_id);

create table ledger_entries (
  id bigint generated always as identity primary key,
  ledger_transaction_id text not null references ledger_transactions(id),
  account text not null,
  debit bigint not null default 0 check (debit >= 0),
  credit bigint not null default 0 check (credit >= 0),
  created_at timestamptz not null default now(),
  check ((debit > 0 and credit = 0) or (credit > 0 and debit = 0))
);
create index ledger_entries_transaction_idx on ledger_entries(ledger_transaction_id);

create function enforce_balanced_ledger() returns trigger language plpgsql as $$
declare target_id text; delta bigint; entry_count bigint; is_posted boolean;
begin
  if tg_table_name = 'ledger_transactions' then target_id := new.id; else target_id := coalesce(new.ledger_transaction_id, old.ledger_transaction_id); end if;
  select coalesce(sum(debit),0) - coalesce(sum(credit),0), count(*) into delta, entry_count from ledger_entries where ledger_transaction_id = target_id;
  select posted into is_posted from ledger_transactions where id=target_id;
  if delta <> 0 or entry_count < 2 or not is_posted then raise exception using errcode='23514', message=format('ledger transaction %s invalid: delta %s, entries %s, posted %s',target_id,delta,entry_count,is_posted); end if;
  return null;
end $$;
create constraint trigger ledger_balanced after insert or update or delete on ledger_entries deferrable initially deferred for each row execute function enforce_balanced_ledger();
create constraint trigger ledger_transaction_balanced after insert on ledger_transactions deferrable initially deferred for each row execute function enforce_balanced_ledger();

create function prevent_ledger_mutation() returns trigger language plpgsql as $$ begin raise exception using errcode='23514', message='ledger history is immutable'; end $$;
create trigger ledger_entries_immutable before update or delete on ledger_entries for each row execute function prevent_ledger_mutation();
create function guard_ledger_entry_insert() returns trigger language plpgsql as $$ begin if (select posted from ledger_transactions where id=new.ledger_transaction_id) then raise exception using errcode='23514', message='cannot append to posted ledger transaction'; end if; return new; end $$;
create trigger ledger_entries_append_guard before insert on ledger_entries for each row execute function guard_ledger_entry_insert();
create function prevent_ledger_transaction_mutation() returns trigger language plpgsql as $$ begin if tg_op='UPDATE' and old.posted=false and new.posted=true and old.id=new.id and old.tenant_id=new.tenant_id and old.payment_intent_id=new.payment_intent_id and old.effect_key=new.effect_key and old.currency=new.currency then return new; end if; raise exception using errcode='23514', message='ledger history is immutable'; end $$;
create trigger ledger_transactions_immutable before update or delete on ledger_transactions for each row execute function prevent_ledger_transaction_mutation();

create table outbox_events (
  id text primary key,
  tenant_id text not null references tenants(id),
  aggregate_type text not null,
  aggregate_id text not null,
  aggregate_sequence bigint not null,
  event_type text not null,
  payload jsonb not null,
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  lease_token text,
  lease_until timestamptz,
  published_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  unique (aggregate_id, aggregate_sequence)
);
create index outbox_ready_idx on outbox_events(available_at, created_at) where published_at is null;

create table processed_events (
  consumer_name text not null,
  event_id text not null,
  processed_at timestamptz not null default now(),
  primary key (consumer_name, event_id)
);

create table simulated_provider_operations (
  stable_key text primary key,
  provider_reference text not null unique,
  status text not null check (status in ('accepted')),
  created_at timestamptz not null default now()
);

insert into tenants(id, name) values ('tenant_demo','Demo tenant');
insert into api_keys(tenant_id,key_hash,label) values ('tenant_demo','34584a216f0fd128b947e87909498fa041a484ef20927c350ae9bd57e49cf48c','local demo key');
