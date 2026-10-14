# Production readiness and qualification

The Docker stack is a repeatable qualification environment. It remains a
single-host simulated service, with no real provider or production release.
Production approval requires the measured gates below and an operator review.

## Implemented safeguards

- The runtime runs as a non-root user. Runtime and verification base images
  are pinned by digest. Update them deliberately after vulnerability review.
- The `prod` profile disables startup DDL, requires secrets of at least 32
  characters, verified PostgreSQL TLS, authenticated Redis TLS, Kafka TLS and
  enabled admission control. Database statements, lock acquisition and idle
  transactions have explicit production timeouts. It rejects superusers, elevated roles, schema
  creators and membership in public-table owner roles.
- Schema changes run under a separate migration identity. The concurrent V3
  index uses nontransactional execution and session advisory locking, with a
  five-second lock timeout. Inspect invalid indexes after an interrupted build;
  an authorized operator must remove the invalid artifact and repair migration
  history before retrying. Never hide invalid artifacts with `IF NOT EXISTS`.
- `deploy/postgres-runtime-role.sql` defines explicit runtime grants, without
  credentials or DDL ownership. Provision a separate authenticated login and
  grant it this role. Apply through an authorized deployment action. API-key
  provisioning uses an operator identity, not the runtime role.
- The outbox leases at most 100 independent aggregate heads, submits sends
  before waiting, and uses one acknowledgement deadline per sweep. Predecessor
  lookup has a pending-only aggregate index. Fenced acknowledgements and inbox
  deduplication remain authoritative after lease takeover or uncertain delivery.
- Historical migration copies a bounded keyset chunk in one SQL statement.
  Version guards prevent an older chunk from replacing a newer dual write;
  checkpoint updates commit with the chunk.
- Prometheus exposes pending outbox count, oldest pending age, observation
  timestamp and observation failures. Sampling has a two-second query timeout.
  The production management port is 8081 and must remain private.

The guard validates configuration and database privileges. Deployment checks
must still prove certificate validation, Kafka ACLs, network policy, secret
rotation and gateway routing. Put API traffic behind TLS termination and an
upstream request-size limit. Keep the management port and database private.
Tenant predicates remain required; RLS defense in depth remains an open gate.

## Docker verification

```sh
docker compose -p payrail --profile test build verify
docker compose -p payrail --profile test run --rm verify
docker compose -p payrail build app
docker compose -p payrail up -d app
docker compose -p payrail --profile test run --rm --entrypoint python3 verify scripts/flow-smoke.py
docker compose -p payrail --profile test run --rm --entrypoint python3 verify scripts/kafka-recovery.py
docker compose -p payrail --profile test run --rm --entrypoint python3 verify scripts/performance/run.py --profiles sustained-a,sustained-b,mixed,stress
```

The verifier needs the local Docker socket to create test-owned containers;
this socket grants host-level control and belongs only in a trusted test runner.
It is never mounted into the runtime. Tests use disposable PostgreSQL and Redis;
load/fault studies retain synthetic data and restore their named services.
The Maven dependency cache is a dedicated volume. The host workspace mapping
allows Docker-backed k6 studies to mount the correct host files on Desktop and
Linux. Run Compose from the repository root.

## Qualification gates

| Gate | Required evidence | Current boundary |
| --- | --- | --- |
| 25K/s | Dedicated load generators and deployment; accepted mutations and settlements reported separately; sustained 30 minutes with declared latency/error/drain budgets | A five-second bounded local target probe can reject this hardware profile; it cannot certify sustained capacity |
| 100M objects | Dedicated dataset with storage/WAL headroom; live traffic throughout; interrupted/resumed backfill; full reconciliation, cutover and rollback | Docker tests exercise 10,000 historical rows and live dual writes, not 100M |
| 1M faults | Seeded schedule with counted duplicate, response-loss, crash and transport actions; observed boundaries and reconciliation after recovery | 10,000 provider completion redeliveries are one tested fault class, not the complete campaign |
| Provider | Stripe sandbox adapter, pinned contracts, signed webhook validation/deduplication, declines, authentication and refunds | Simulated provider only; sandbox credentials and account setup remain separate |
| Operations | Backup restoration/PITR, failover, rolling deployments, observability/alerts, retention, key rotation, incident drills and dependency review | Single-host recovery experiments cover selected local failures |

On this shared Docker VM, about 37 GiB was free before the revised studies.
The original 38,979 source rows used roughly 22 MiB including indexes, plus
another 19 MiB for their V2 representation, before idempotency/outbox storage.
Those small-fixture sizes are sizing inputs only. Do not seed 100M objects into
this volume: a dedicated pilot must size the full dataset, indexes, WAL,
replicas, backups and temporary migration space before qualification.

Alert on outbox age above the declared recovery budget, stale observation
samples, observation errors, provider failures, API error/latency budgets,
pool exhaustion, dropped arrival work and reconciliation mismatches. Define
capacity from passing repeated runs and retain failing observations. Do not
silently relax latency or drain budgets to obtain a passing result.

The recorded Docker preflight is reproducible with:

```sh
docker compose -p payrail --profile test run --rm --entrypoint python3 verify scripts/qualification-preflight.py --objects 100000000
```

It intentionally exits unsuccessfully when the planning storage gate fails and
never seeds data. `evidence/qualification/preflight.json` retains observed pilot
sizes and free space, the declared threefold planning allowance and the result.
The allowance is a resource-planning assumption, not a measurement at 100M rows.
