# PayRail backend implementation plan

Status: architecture and qualification plan, 2026-10-13. The repository was empty at initial inspection; the local reference implementation is now present. This document describes the intended architecture and larger qualification gates. See `docs/verification.md` and `docs/evidence.md` for implemented behavior, measured local evidence and remaining gaps; this plan reports no measured qualification-scale throughput, migrated object count or fault campaign result.

## Scope and evidence

Build a Java Spring Boot service backed by PostgreSQL, Kafka, and Redis. Deliver PaymentIntent operations, tenant isolation and admission control, request-fingerprint idempotency, explicit state transitions, an immutable double-entry ledger, a transactional outbox, and API-version-pinned response transforms. Include an online migration control plane and repeatable load/fault tooling.

25,000 requests/second, 100 million objects, and one million injected faults are qualification targets, not capabilities demonstrated by this plan. A local developer profile verifies behavior; a separately sized qualification environment verifies scale. Publish the workload, hardware, versions, seed, raw results, failures, and measurement intervals with every result. Define whether 25K/s means HTTP requests, accepted mutations, or end-to-end settlements; report all three separately. Target acceptance limits must be configured before a benchmark starts.

Use a simulated payment provider initially. No handling of raw card credentials and no real settlement are implied. Provider integration later requires a provider idempotency key and reconciliation API; an ambiguous provider timeout remains unresolved until reconciled.

## Runtime and boundaries

Use a modular monolith with independently runnable API, outbox dispatcher, provider worker, and migration worker roles from the same codebase. Keep domain logic separate from transports and persistence. Suggested packages: `api`, `auth`, `idempotency`, `intent`, `ledger`, `outbox`, `provider`, `ratelimit`, `versioning`, `migration`, and `observability`.

Use the installed Java 17 and Maven 3.9.11 for the first slice, Spring Boot 3.5 with an exact supported patch pinned at implementation, Maven Wrapper, Spring MVC, explicit JDBC transactions, Flyway, Spring Kafka, Redis client, Actuator/Micrometer, JUnit, and Testcontainers. Pin dependency versions and container images, then record exact versions in benchmark manifests. JDBC makes row locks, conditional writes, and bulk operations visible. Flyway is the sole DDL owner; application startup never implicitly changes schema. Use a dedicated migrator deployment for production DDL. Spring Boot supports Flyway and PostgreSQL Testcontainers integration. [Spring Boot initialization](https://github.com/spring-projects/spring-boot/blob/main/documentation/spring-boot-docs/src/docs/antora/modules/how-to/pages/data-initialization.adoc), [Spring Boot Testcontainers](https://github.com/spring-projects/spring-boot/blob/main/documentation/spring-boot-docs/src/docs/antora/modules/reference/pages/testing/testcontainers.adoc).

PostgreSQL is authoritative for intents, idempotency, ledger, and delivery progress. Redis holds only rate-limit state and optional disposable caches. Kafka carries durable domain events and commands. Do not use a Redis lock as the money correctness boundary or put network calls inside database transactions.

Authentication resolves the tenant from verified credentials. Reject conflicting caller-supplied tenant identifiers. Every business key, query, unique constraint, and foreign key includes the tenant. Use a non-owner database role with forced RLS as an additional guard, setting trusted tenant context with transaction-local configuration; verify pooled connections cannot inherit context. Worker access uses explicit restricted roles and audited tenant iteration.

## API contract and request processing

Initial endpoints:

| Operation | Contract |
| --- | --- |
| `POST /v1/payment_intents` | Validate integer minor-unit amount and supported currency; create `requires_confirmation`; require `Idempotency-Key`. |
| `GET /v1/payment_intents/{id}` | Tenant-scoped current representation; 404 for absent or other-tenant identifiers. |
| `POST /v1/payment_intents/{id}/confirm` | Accept asynchronous provider work; return 202 with `processing`; require idempotency key. |
| `POST /v1/payment_intents/{id}/cancel` | Cancel only before provider processing; require idempotency key. |
| `GET /v1/payment_intents` | Bound page size; opaque cursor over `(created_at,id)` scoped to tenant and filters. |

Resolve an explicit `PayRail-Version` or tenant default to an immutable supported contract version. Return the resolved version. Version differences are deterministic pure transforms from a canonical response DTO; the transform registry is append-only while a version is supported. Include the resolved version in the request fingerprint and save transformed response bytes before commit. Retrying a successful request returns its saved status/body and stable contract headers even after the intent changes or a deployment upgrades defaults. Transport headers such as trace ID may be fresh. GET uses its requested contract version, independently of the original mutation.

Fingerprint normalized method, route template, path identifiers, resolved API version, and validated canonical request fields. Normalize JSON object ordering and documented defaults, preserve meaningful array ordering, reject duplicate JSON keys, and exclude tracing/authentication headers. Hash with SHA-256 and version the canonicalization algorithm. Bound request/key sizes. Idempotency scope is `(tenant_id, operation, key)`; reusing a scoped key with a different fingerprint returns 409. Invalid requests rejected before admission do not reserve keys; explicitly document this behavior.

For local commands, acquire/reserve the idempotency row using its unique constraint, lock the intent if needed, validate transition, mutate intent, append ledger if applicable, insert outbox event, transform response, and store status/bytes in one short PostgreSQL transaction. Concurrent duplicates wait only up to a bounded lock timeout, then get a retryable conflict and `Retry-After`; they never execute another mutation. A duplicate that finds a committed row replays it. A pre-commit crash rolls everything back; a post-commit/pre-response crash is recovered by replay. Persist deterministic domain rejections after reserving the key; transient infrastructure failures roll back. Never cache an uncommitted success.

Retention is explicit: benchmark with indefinite retention initially. Production expiry requires a documented retry window and compact tombstone policy so an old key cannot silently recreate a monetary operation. Idempotency records are not partitioned by creation time if that would weaken their unique key.

## State machine and provider uncertainty

Legal initial transitions are `requires_confirmation -> processing`, `requires_confirmation -> canceled`, and `processing -> succeeded|failed`. Terminal states are immutable. `processing` remains pending during provider uncertainty; timeout alone is not failure. Record each transition with actor, command/event ID, timestamp, old/new state, and incremented intent version. Reject every other edge with 409.

Use `SELECT FOR UPDATE` or `UPDATE ... WHERE state = expected AND version = expected` with checked row count. Lock shared ledger accounts in stable ID order. Confirmation writes a provider command to the outbox; the worker calls the provider outside transactions with a stable key derived from tenant and intent. Provider completion records a unique provider reference, consumes the event once, changes state, posts the journal, and appends an outbox event atomically. A crash after provider acceptance requires re-query/retry with that same provider key. If the provider cannot offer idempotency or reconciliation, exactly-once monetary effects cannot be promised.

## PostgreSQL model and ledger invariants

Use integer `bigint` minor units with checked Java arithmetic, positive bounded amounts, validated currency exponent, `timestamptz` timestamps, text states with constraints, UUID public identifiers, and a bigint sequence where a monotonic scan cursor is useful. Do not use floating point for money. Initial tables:

| Table | Important keys and contents |
| --- | --- |
| `tenants` | Tenant ID, API default version, limits, active status. |
| `payment_intents` | Composite tenant/intent primary key; amount, currency, state, version, provider reference, timestamps. |
| `idempotency_records` | Unique tenant/operation/key; fingerprint and algorithm, resolved API version, committed response status/body/headers, intent reference, retention metadata. |
| `intent_transitions` | Unique tenant/intent/version; command ID, legal old/new states, actor. |
| `ledger_accounts` | Composite tenant/account key; currency, account kind; optional balance projection. |
| `ledger_journals` | Composite tenant/journal key; unique tenant/business posting key; intent reference, posting reason, currency. |
| `ledger_entries` | Tenant/journal/entry key; account reference, positive minor amount, debit/credit side. |
| `outbox_events` | Event UUID, tenant, aggregate ID/version, schema version, payload, available time, lease generation/expiry, attempts, published time. |
| `consumer_inbox` | Unique consumer/event ID, tenant, processed time; committed with consumer effects. |
| `migration_jobs`, `migration_chunks` | Target generation, cursor/ranges, lease generation, checkpoint, counts, hashes, reconciliation status. |

All cross-table references carry tenant ID. Index list paths by `(tenant_id,created_at,id)` and intent history by `(tenant_id,intent_id,version)`; index referencing FK columns. Use a partial ready-outbox index and bounded claim batches. Plan partitioning only after representative query/storage measurements. Tenant hash partitioning can retain tenant-scoped uniqueness; time partitioning needs a separate global deduplication design. Preserve ledger and deduplication guarantees through any archival scheme.

Journal posting is append-only. Every committed journal has at least two entries, equal total debits and credits, and a single currency shared by its accounts. Enforce row-level amount/side/currency checks and composite FKs; enforce cross-row balance through a deferred database constraint trigger or a database posting function with no direct application insert permission. Lock the journal while building it and forbid entry mutation after posting. Reversal means a new opposite journal, never editing historical entries. Unit tests alone are insufficient: attempt malformed journal writes through the application database role and assert database rejection at commit.

For the simulated settlement, debit provider-clearing asset and credit merchant-payable liability for the amount. Failed/canceled intents have no settlement journal. Future fees, refunds, authorization holds, and payouts need distinct business posting keys and separately reviewed state/accounting rules. Balance projections are updated in the posting transaction and reconciled against immutable entries. Prefer account groups that avoid a global hot clearing row at scale; measure any serialization bottleneck explicitly.

## Outbox, Kafka, and admission control

Claim bounded outbox batches with `FOR UPDATE SKIP LOCKED`, save a fenced expiring lease, and commit before publishing. Publish with acknowledgement, then mark published only if the lease generation still matches. A crash after Kafka acknowledgement and before marking published causes a duplicate; consumers deduplicate event UUIDs using the inbox in the same transaction as their effects. Avoid concurrent publishing of later versions for the same aggregate: lease an aggregate lane or block later versions until its predecessor is marked published. Consumers also enforce aggregate version and handle gaps. Quarantine poison events with alerting and an operator replay path; never silently discard them.

Kafka message key is tenant/intent, with event ID, aggregate version, event-schema version, correlation ID, and timestamp in an envelope. Configure producer idempotence, acknowledgements, bounded retries and delivery timeout. This reduces producer retry duplicates but does not atomically couple PostgreSQL and Kafka. Outbox plus inbox provides at-least-once delivery with deduplicated database effects. [Kafka producer configuration](https://kafka.apache.org/41/configuration/producer-configs/).

Redis token buckets use an atomic script and Redis server time, bounded TTL, and tenant/operation keys; cluster multi-key scripts use the same tenant hash tag. Maintain read, write, and retry budgets so replay storms cannot bypass admission. Return 429 with a computed retry interval when depleted. Define outages explicitly: money-mutating API calls return retryable 503 if Redis admission cannot be established; reads may use a bounded per-instance fallback whose distributed limit is weaker. Preserve PostgreSQL idempotency under every Redis failure. Atomic scripts avoid races between counter updates and expiry. [Redis rate limiter](https://redis.io/docs/latest/develop/use-cases/rate-limiter/).

## Online migration protocol

Implement a real demonstration migration, such as replacing a legacy response field with a canonical structured field, first against a small fixture and later against a 100M-object dataset. Control generation-specific per-tenant flags and record every cutover. Application schema compatibility covers both old and new binaries during rollout.

1. Expand with nullable columns/new tables and no destructive rename/type rewrite. Apply bounded lock/statement timeouts. Add check/FK constraints as `NOT VALID` where supported, validate separately, and build large indexes concurrently outside transactional Flyway migrations. Check invalid index remnants before retry. Concurrent builds still consume I/O and wait on transactions; online does not mean zero locking. [PostgreSQL ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html), [CREATE INDEX](https://www.postgresql.org/docs/current/sql-createindex.html).
2. Deploy compatibility writers. Write old and new representations in one database transaction for same-database migrations. For another store, publish durable replication work through outbox and reconcile lag; never call two stores and label it atomic. Keep old reads authoritative.
3. Start resumable backfill. Split immutable scan-ID ranges; save each chunk checkpoint in the same transaction as its writes. Claim chunks with fenced leases, batch hundreds/thousands of rows, and adapt size to measured latency. Update target only when its source version is unchanged or the target is older, so backfill never overwrites a newer dual write. New rows beyond the initial high-water mark are supplied by compatibility writers; run a final catch-up scan. Delete handling needs generation-aware tombstones if deletes are supported.
4. Shadow reads compare canonical old/new semantics from the same source version. Record mismatches and lag without putting the shadow result on the response path. Reconcile every chunk by row count, absent/extra keys, normalized hashes, source versions, and money totals per tenant/currency; sampled checks alone cannot authorize full cutover.
5. Cut over tenant cohorts only after backfill complete, zero unexplained full reconciliation mismatches, and accepted shadow/read latency results. Preserve old writes for the rollback window. Rollback flips reads back only while old data is still maintained; after stopping old writes it requires reverse synchronization and reconciliation.
6. Stop old writes after observation and rollback windows, verify no old binaries/consumers remain, then contract in a separate deployment. Keep transforms for supported API versions even when internal fields disappear. Retain checkpoints/audit evidence.

Throttle backfill on WAL growth, replica lag, lock waits, outbox age, and foreground latency. Predefine pause/resume thresholds. Restart workers mid-chunk and verify checkpoints and fencing. Never migrate 100M rows in a single transaction or claim zero downtime without observing foreground traffic throughout the migration.

## Verification harness and delivery sequence

Deliver these proposed entry points with executable scripts and documented prerequisites. They are planned interfaces, not runnable commands in the current empty repository.

| Stage | Deliverable and completion gate |
| --- | --- |
| 1. Foundation | Maven build, Compose PostgreSQL/Kafka/Redis, health checks, tenant authentication fixture, Flyway baseline; `./mvnw verify` passes with real database containers. |
| 2. Correctness | API, fingerprint/replay, state machine and ledger; races on same key/intent produce one committed effect, invalid transitions and unbalanced journals fail, tenant escape attempts fail. |
| 3. Delivery | Outbox dispatcher, simulated provider and inbox; kill at every commit/publish boundary, restart and drain; no lost committed events or duplicate ledger effects. |
| 4. Compatibility | Two immutable API transforms plus golden responses; cross-deployment retries replay saved bytes; fingerprint version changes are explicit. |
| 5. Migration | Expand/dual-write/backfill/shadow/reconcile/cutover demo; restart and stale-worker tests pass with live mutations; rollback is demonstrated. |
| 6. Qualification | Dedicated seed/load/fault profiles; publish raw results and invariant report; targets become measured results only when their gates pass. |

Proposed commands: `./scripts/dev-up.sh`, `./mvnw verify`, `./scripts/seed.sh --objects 100000000 --seed 42`, `./scripts/benchmark.sh --profile qualification --rate 25000 --duration 30m`, `./scripts/fault-campaign.sh --seed 42 --faults 1000000`, and `./scripts/reconcile.sh --run-id <id>`. Provide quick profiles with small datasets and few faults for local/CI use. Record intent counts separately from ledger/outbox/total row counts so “100M objects” is unambiguous.

Use an open-loop load generator, record offered/completed/accepted throughput, timeouts and rejected requests, and correct for coordinated omission. Workload mixes new intents, confirmations, reads, cancellations, exact retries, conflicting retries, tenant hot spots, and outbox backlog. Warm up, sustain load, then measure recovery/drain separately. Measure p50/p95/p99 latency, actual requests per second, CPU/memory/GC, DB pool waits, WAL/I/O, locks/deadlocks, Redis script latency, Kafka lag, and oldest outbox age. Record pool sizes and topology; increasing API replicas cannot bypass a database budget.

Fault cases include process termination before/after database commit, dropped HTTP replies, concurrent duplicate requests, provider acceptance followed by timeout, broker disconnect and acknowledgement ambiguity, consumer redelivery, Redis outage, PostgreSQL disconnect/restart, stale migration leases, interrupted concurrent index builds, rolling old/new deployments, and clock skew. Use Toxiproxy/container control and explicit test-only transaction hooks for repeatable schedules. Run randomized campaigns against a reference state machine and retain minimal failing seeds/traces. A million faults means counted injected fault actions with breakdowns, not a million HTTP requests or an assertion count.

After each deterministic case and each campaign batch, run independent invariants: every terminal success has exactly one settlement business key; all journals balance by currency; no terminal failures/cancellations have settlement journals; no cross-tenant relations exist; idempotency replay/fingerprint semantics hold; committed outbox events eventually appear after recovery; consumer effects are unique; no published intent sequence is missing after drain; migration representations reconcile. A run fails on any unexplained mismatch even if throughput is high. Fault recovery guarantees require restored infrastructure and bounded backlog; report outages separately from healthy-load latency.

Suggested qualification gates to agree before execution: zero invariant failures; at least 25K/s accepted traffic for the declared workload over 30 minutes; fixed documented latency/error budgets; a fully reconciled 100M-intent migration under foreground traffic; one million recorded fault actions with no unresolved discrepancy after drain. Do not quietly reduce workload mix, count 429 responses as payment throughput, or extrapolate a small test to the target.

Publish `artifacts/<run-id>/manifest.json`, raw request histograms, machine/resource inventory, fault schedule/results, migration checkpoints, invariant output, and a concise report containing measured versus target values. CI runs correctness tests and a small seeded fault suite. Full-scale campaigns are explicit resource-consuming jobs rather than default developer tests.
