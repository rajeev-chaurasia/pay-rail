# Concurrency evidence

Reproduce with `./scripts/run_concurrency_evidence.sh`, then run
`python3 scripts/validate_concurrency_evidence.py --self-test`.
The test uses an ephemeral PostgreSQL Testcontainer; it never drops or weakens
production tables or disables a production guard.

Eight workers start together and call the production raw-response idempotency
service with one tenant, operation, fingerprint and key. The guarded action
inserts a synthetic side effect in the same transaction. A declared 150 ms
pause keeps the critical section open so timing overlap is observable.

The deliberately unguarded control checks for an effect before inserting.
A second barrier forces all workers to finish the read before any insert.
It therefore demonstrates the race under a deliberately widened check/insert
window. It does not estimate the probability of that race in a deployed service.

`raw.csv` records each worker's monotonic start/end interval, response effect ID
and whether its action ran. `manifest.json` records PostgreSQL version, timestamp,
source fingerprint and observed counts. The producer queries committed test
table counts; the validator separately recomputes action counts and distinct
returned IDs from raw rows, verifies all attempts overlap, checks source and
producer fingerprints, and requires duplicates in the control.

`checksums.json` binds retained artifacts byte for byte. The validator rejects
duplicate worker IDs, unknown phases, blank outcomes, serialized intervals,
changed summaries, changed source inventories and an ineffective control.
CI checks the retained result and its adversarial validation cases.

## Limits and trust

This experiment measures the idempotency transaction with a synthetic effect,
not a complete HTTP payment, provider operation or ledger journal. Those paths
have separate integration tests and local smoke observations. Eight-way overlap
is not a throughput benchmark or a million-fault qualification.

Raw responses allow independent recomputation of distinct returned effect IDs.
The table count snapshot is a producer observation, not an independently queried
database after the container exits. Checksums prove internal consistency, not
authentic execution: the artifact producer and CI environment remain trusted.
An untrusted publisher can fabricate rows and recompute hashes.

Changes to runtime sources, harness or validator invalidate retained provenance.
Reproduce and reseal the experiment rather than hand-editing its results.
