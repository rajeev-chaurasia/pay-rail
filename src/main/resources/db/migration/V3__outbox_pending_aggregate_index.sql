-- Build outside a transaction so foreground writes can continue.
set lock_timeout = '5s';
create index concurrently outbox_pending_aggregate_idx
  on outbox_events(aggregate_id, aggregate_sequence)
  where published_at is null;
reset lock_timeout;
