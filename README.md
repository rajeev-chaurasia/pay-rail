# PayRail

PayRail is a runnable Java 17 / Spring Boot 3.5 payment-intent service. PostgreSQL is authoritative for payment state, idempotency, the immutable double-entry ledger, migration state, and the transactional outbox. Kafka carries ordered aggregate events and provider commands. Redis enforces an atomic per-tenant request limit.

This is a simulated rail: it accepts integer minor-unit amounts and never handles card data or moves real money.

Contributor setup, required checks and review conventions are in
[CONTRIBUTING.md](CONTRIBUTING.md). [AGENTS.md](AGENTS.md) is the canonical
contributor contract. [Evidence](docs/evidence.md) explains the concurrency
experiment and independent result validation; [known limits](docs/known-misses.md)
separate local behavior from remaining qualification work.

## Run locally

Prerequisites are Java 17, Maven 3.9+, Docker 28+, and Compose v2.

```bash
./scripts/dev-up.sh
curl http://localhost:18080/actuator/health
```

The local fixture API key is `pr_test_demo`. It is hashed with the local-only default pepper in Flyway. Production profile startup rejects the demo pepper and admin token; set `API_KEY_PEPPER` and `MIGRATION_ADMIN_TOKEN` to secrets before using `--spring.profiles.active=prod`.

```bash
curl -X POST http://localhost:18080/v1/payment_intents \
  -H 'Authorization: Bearer pr_test_demo' \
  -H 'Idempotency-Key: order-42-create' \
  -H 'PayRail-Version: 2026-01-01' \
  -H 'Content-Type: application/json' \
  -d '{"amount":1250,"currency":"usd","captureMethod":"manual"}'
```

API docs are at `http://localhost:18080/swagger-ui.html` and the OpenAPI document at `/v3/api-docs`. Compose defaults to the collision-resistant host ports 18080 (HTTP), 15432 (PostgreSQL), 16379 (Redis), and 19092 (Kafka); the `PAYRAIL_*_PORT` variables override them. Stop only this isolated Compose project with `./scripts/dev-down.sh`; its project name is `payrail` and it does not touch unrelated containers.

## API and correctness model

The API supports create, get, keyset list, confirm, capture, cancel, and refund under `/v1/payment_intents`. Every mutation requires `Idempotency-Key`. The database serializes a key, compares a recursively canonicalized SHA-256 request fingerprint (including API version), performs the state change, ledger posting, V2 dual write, and outbox append, then saves the exact transformed response bytes/status/version in one transaction. A post-commit lost response replays those bytes; a different request or version returns 409.

Supported immutable wire versions are `2025-01-01` (`state`) and `2026-01-01` (`status`). GET and list responses use the requested transform. Payment transitions are explicit: automatic confirmation enters `processing`; the provider worker completes it to `succeeded`. Manual confirmation enters `authorized`, followed by full capture. Cancel, partial/full refund, and terminal-state rules return 409 on illegal edges.

The simulated provider persists a stable `tenant:intent` operation before responding. An injected response loss therefore reconciles on retry without a second provider operation or ledger effect. Kafka listener failures use an unbounded fixed backoff rather than silently skipping a processing intent. In production this needs operational alerting and a durable retry topic appropriate to the broker retention policy.

Ledger effects have a unique tenant business key. Deferred PostgreSQL constraint triggers require at least two balanced entries and `posted=true` at commit. Posted transactions and entries are immutable; refunds create reversing journals. Composite tenant foreign keys prevent cross-tenant refund, ledger, and V2 references. Tenant read isolation itself is enforced by authenticated predicates in this version; PostgreSQL RLS is not enabled.

The outbox claims one aggregate head at a time with `FOR UPDATE SKIP LOCKED`, a 30-second fenced lease, a Kafka send timeout below that lease, and the intent ID as message key. A stale worker cannot acknowledge or fail a newer lease. Kafka preserves order for the normal single-key publish path, while an acknowledgement ambiguity can still produce a late duplicate predecessor; consumers must deduplicate IDs and enforce aggregate versions. Kafka delivery is at least once; `processed_events` supplies consumer-side unique event IDs in the same transaction as provider completion.

## Online V2 migration

Flyway V2 adds an additive representation. Compatibility writes update both tables atomically. `POST /v1/admin/migrations/payment-v2/backfill?batchSize=500` performs a resumable ID-keyset batch whose checkpoint commits with its writes. `/reconcile` compares missing, extra, version, money, status, metadata, and timestamps. `/gate-cutover` records readiness only when full reconciliation is clean. Deterministic tenant/intent cohorts use `MIGRATION_SHADOW_READ_PERCENT` and `MIGRATION_V2_READ_PERCENT`; V2 reads remain gated until reconciliation authorizes cutover. Keep dual writes enabled through the rollback window.

## Verification and qualification

`mvn verify` runs real PostgreSQL 16 Testcontainers tests for duplicate races, fingerprint conflicts, canonical JSON, state conflicts, tenant isolation, ledger balance/immutability, provider response loss and redelivery, pinned wire replay, migration resume/reconcile, and stale outbox fencing.

```bash
mvn verify
./scripts/seed.sh --objects 1000 --seed 42
./scripts/benchmark.sh --profile quick --rate 10 --duration 30s
./scripts/fault-campaign.sh --seed 42 --faults 20
./scripts/reconcile.sh
```

The fault script counts attempted client deadlines and stable-key duplicate retries; a short deadline does not by itself prove that the server committed. The benchmark requires k6, fails on any non-201 response or dropped iteration, uses a unique run ID in every key, and writes a manifest plus raw summary under `artifacts/`. Its offered rate must fit `RATE_LIMIT_RPM` in both the running service and benchmark environment. The provided local harness does not prove 25,000 requests/s, a 100-million-object migration, or one million fault injections. Those are qualification targets. A claim requires a separately sized environment, declared workload and hardware, sustained open-loop results, raw latency/resource data, a fully drained outbox, and zero invariant or reconciliation failures. See [the implementation plan](docs/implementation-plan.md) for the full gates and fault matrix.

Known limits of this reference service: the fixed-window Redis limiter is intentionally simple; each outbox event is claimed immediately before its serial publish within a bounded sweep; API keys are managed through SQL rather than a management API; and no external payment provider is integrated.
