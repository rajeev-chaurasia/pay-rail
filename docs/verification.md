# Verification evidence

Verified locally on 2026-10-13 with Java 17.0.15, Maven 3.9.11, Docker Desktop engine 28.0.4, PostgreSQL 16.6, Kafka 3.9.0, and Redis 7.4.1.

- `mvn verify`: 11 tests, 0 failures, 0 errors, 0 skipped. Tests use a real PostgreSQL 16.6 Testcontainer.
- `docker compose -p payrail up -d --build`: PostgreSQL, Redis, Kafka, and the application became healthy/up on localhost-only high ports without stopping unrelated containers.
- `GET /actuator/health`: `{"status":"UP"}`.
- Authenticated automatic intent create returned `requires_confirmation`; confirm returned HTTP 202 with `processing`; Kafka/provider processing produced `succeeded` with `amountReceived=4242` and version 3.
- The smoke intent had one provider operation, one ledger transaction with two entries and net debit minus credit of zero, and all three aggregate outbox events marked published.
- Kafka topic `payrail.payment-events` reached end offset 3.
- A Redis counter at the configured tenant limit returned HTTP 429, `Retry-After: 60`, and `rate_limit_exceeded`; the temporary counter was removed afterward.
- The migration gate returned missing=0, extra=0, mismatched=0, source_total=1, target_total=1, cutover_ready=true.

These are correctness and local runtime checks. They are not throughput, 100-million-object migration, or million-fault qualification results.

## Contributor alignment verification

After Java formatting and service refactoring, on 2026-10-13:

- `mvn -B verify -Dpayrail.evidenceDir=evidence/concurrency`: build success,
  12 tests, zero failures/errors/skips; pinned Spotless formatting check passed.
- `python3 scripts/validate_concurrency_evidence.py --self-test`: sixteen
  overlapping samples, one guarded synthetic effect, eight unguarded effects;
  seven altered cases rejected.
- `python3 scripts/check_style.py --self-test`: style checks and negative
  controls passed.
- `bash -n scripts/*.sh` and `docker compose -p payrail config --quiet`: passed.
- Rebuilt local app: health UP, create HTTP 201, byte-identical duplicate
  response, confirm HTTP 202, Kafka/provider completion to succeeded with
  amountReceived=512. PostgreSQL, Redis and Kafka remained healthy.

The race measures the production idempotency transaction with a test-only
synthetic effect. It does not measure complete HTTP payment throughput. The
method, raw files and limitations are described in `docs/evidence.md`.
