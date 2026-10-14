# Architecture

HTTP filters establish tenant identity and admission. Controllers validate
requests and delegate to services. Services own state transitions and transaction
boundaries. Repositories own SQL, while domain records describe canonical data.

A mutating transaction reserves its scoped idempotency key, checks the request
fingerprint, changes the intent, posts a ledger journal when applicable, dual
writes the migration target, appends an outbox event, transforms the response
and stores its exact bytes. A rollback leaves no committed partial effect.

The outbox claims an aggregate head with a fenced lease, publishes outside the
database transaction and acknowledges only its current lease. Delivery is at
least once. The provider consumer commits its inbox guard with the payment and
ledger effects. The provider adapter is simulated and reconciles stable keys
after acceptance followed by response loss.

PostgreSQL constraints enforce tenant references, journal balance and posted
journal immutability. Query predicates enforce authenticated tenant reads.
Redis provides admission control, with a retryable outage response.

The V2 migration uses additive tables, version-aware dual writes, checkpointed
backfills and full representation reconciliation. Read cutover requires a clean
gate, with divergence falling back to authoritative source data.

Maintain the detailed transaction and rollout rationale in
`docs/implementation-plan.md`; record new cross-cutting decisions with their
reason, tradeoffs, compatibility and validation in `docs/adr/`.

The playground is buildless HTML/CSS/JavaScript served by the same Spring Boot
origin. Credentials remain in page memory. A tenant-authenticated read-only
inspection controller/service/repository returns sanitized persisted journal,
event and provider observations. Admin migration requests use a separately
entered credential; browser actions never bypass existing authorization or
idempotency. See `docs/playground.md` for recovery and snapshot limitations.

Provider retry exhaustion publishes acknowledged quarantine records before
recovery can resolve the failed offset. Publication failure leaves recovery
unresolved. A quarantined payment is not marked failed or settled; operator
reconciliation decides subsequent replay. The production profile uses separate
DDL/runtime identities and private management endpoints. See
`docs/production-readiness.md` and `docs/adr/001-security-runtime-upgrade.md`.
