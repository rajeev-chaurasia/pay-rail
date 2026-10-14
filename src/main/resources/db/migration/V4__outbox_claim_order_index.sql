-- Match the claim order so a bounded batch need not sort the entire backlog.
-- Keep the availability index for delayed retries and the predecessor index
-- for aggregate ordering. This additive index preserves leases and fencing.
set lock_timeout = '5s';
create index concurrently outbox_pending_created_idx
  on outbox_events(created_at)
  where published_at is null;
-- A queue can grow while the much larger retained table barely changes.
-- Lower the analyze eligibility threshold; operators still monitor actual
-- analyzer cadence and refresh statistics during a backlog recovery.
alter table outbox_events set (
  autovacuum_analyze_scale_factor = 0.005,
  autovacuum_analyze_threshold = 50
);
reset lock_timeout;
