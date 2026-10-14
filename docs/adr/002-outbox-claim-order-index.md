# ADR 002: ordered pending outbox index and statistics eligibility

Status: implemented after the 2026-10-14 GCP campaign; cloud index observations
and limits are in `docs/gcp-qualification-results.md`.

The existing `(available_at,created_at)` index supports eligible retries but does
not provide the global `created_at` order used by a bounded head claim. At a large
backlog PostgreSQL chose a full pending anti-join and sort before the 100-row limit.
V4 adds a pending-only `created_at` index. Keep the existing retry and predecessor
indexes: availability, aggregate order, leases, fenced acknowledgements and
uniqueness semantics are unchanged.

An empty queue can also grow while the larger retained table changes too little
to trigger default analyze eligibility. V4 lowers the table's analyze scale factor
to 0.005, with threshold 50. This makes analysis eligible sooner; it does not
promise immediate analysis, a stable plan or a delivery SLO. Operators must monitor
actual analyzer cadence, estimate drift, index churn, long transactions and oldest
pending age. More frequent analysis and an additional index cost CPU, I/O and
write work. Measure these costs in the deployment's workload.

The concurrent index is nontransactional, with a five-second lock timeout. A failed
build can leave an invalid index. Inspect it, remove the exact invalid artifact
under an authorized operator action, repair failed migration history as required,
and retry. Never hide an invalid artifact with `IF NOT EXISTS`. A live cloud retry
needed a maintenance interval and cancellation of stale test queries, so it does
not demonstrate zero-downtime production installation. Runtime identities still
cannot run DDL. Rollback can remove the additional index and restore default table
options through a separate authorized migration; published monetary/delivery data
must remain intact.
