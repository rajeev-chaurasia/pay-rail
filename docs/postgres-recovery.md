# PostgreSQL recovery drills

PayRail has separate logical-restore and physical/WAL recovery drills. Both use
unique disposable Docker projects and synthetic payments. Neither changes the
playground database or provides a production backup service.

## Online backup and named-point recovery

Build the runtime and verification images, then run:

```sh
bash scripts/pitr-docker.sh
docker compose -p payrail --profile test run --rm --no-deps --entrypoint python3 verify scripts/validate_pitr_evidence.py artifacts/pitr.json
```

The fixture enables PostgreSQL WAL archiving into a project-owned volume. It
takes a throttled `pg_basebackup` with streamed WAL while the API stays running.
The test observes `pg_stat_progress_basebackup` before and after a manual payment
create/confirm/capture, requiring an actual overlap. `pg_verifybackup` verifies
the backup manifest. An automatic payment then settles and both outboxes drain.

A named restore point is created before a later refund and sentinel create.
The test forces a WAL switch and waits for archive acknowledgement. Independent
copies of the base backup are then started: one has the required archived WAL;
the negative control has none. The negative server must exit with PostgreSQL's
target-not-reached failure. The successful server must promote at the named
point and match every public-table hash from before the later mutations.

A separate restored API starts with outbox dispatch and Kafka consumers disabled.
It must replay saved create/confirm responses byte-for-byte, retain the original
balanced settlement, and omit the later source refund. A synthetic refund tests
restored write constraints and exact replay, appending one balanced reversal.
Its new event remains unpublished because delivery is fenced.

The default sanitized result is `artifacts/pitr.json`; a retained local run is
`evidence/flows/postgres-pitr.json`. Evidence includes exact image identities,
backup/archive hashes, table comparisons, replay digests, journal entries and
negative-control outcome. The independent validator recomputes journal balances
and rejects altered tables, response digests, money entries and fault outcomes.
Hashes establish comparison consistency, not authenticity of execution.

CI repeats the physical recovery drill against its newly built runtime. The
wrapper removes only its own containers and volumes, including base backups
and WAL. It publishes no physical backup, WAL payload or credentials.

The mechanism follows the PostgreSQL 16 [continuous archiving procedure](https://www.postgresql.org/docs/16/continuous-archiving.html),
[base backup command](https://www.postgresql.org/docs/16/app-pgbasebackup.html)
and [recovery settings](https://www.postgresql.org/docs/16/runtime-config-wal.html).
The simple copy command in this test fixture is not a production archive system.

## Production recovery boundary

PITR rolls back PostgreSQL records. Kafka offsets, already published events and
external provider effects can be later than the restored point. Keep API writes,
outbox dispatch and consumers fenced until an authorized operator reconciles
provider operations and delivery history, establishes the new timeline, and
decides which original identities can safely be replayed. Do not apply this
fixture's synthetic post-restore refund procedure to real provider operations.

Choose and test a production backup manager with a dedicated backup identity,
encrypted off-host storage, durable and idempotent archive acknowledgement,
retention that preserves each backup's complete WAL chain, capacity monitoring,
immutable backups and restricted access. Alert on archive failures and lag,
backup age, missing chains, storage exhaustion and failed restore verification.
Archive timestamps and acknowledged WAL positions must support the declared
recovery point objective; observed small-fixture restore time is not a
production recovery time objective.

The local drill covers two pre-target payments, one observed backup/write
overlap and a single-host restore. It does not qualify off-host durability,
retention, concurrent backup schedules, failover, timeline divergence, production
volumes, RPO/RTO or real provider reconciliation. Deployment-specific backup
configuration and recovery actions require authorization before application.
