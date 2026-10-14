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

## Playground verification

On 2026-10-13, `mvn -B verify -Dpayrail.evidenceDir=evidence/concurrency`
passed thirteen tests with zero failures/errors/skips. The new inspection test
covers capture and refund journals, provider outcome, event records, omitted
sensitive metadata and authenticated cross-tenant 404 responses.

Manual browser checks against the full local Compose stack:

- Created a 2500-minor-unit automatic payment; eight retries returned the
  original response bytes. A changed amount under the same key returned 409.
- Confirmation returned 202 and reached succeeded through Kafka/provider work.
  A 500-minor-unit refund showed two balanced journals and a zero net difference.
- A new manual payment authorized then captured its 2500-minor-unit amount.
- Both API versions showed the same payment version with state/status transforms.
- Migration controls refused an absent token, then successfully ran a backfill,
  full reconciliation and readiness gate with the synthetic local token.
- The final interface loaded at desktop and compact widths; compact layout
  geometry showed matching document and viewport widths, with no horizontal
  overflow. A full accessibility audit is outside this check.
- Pausing only the local app caused a refund request to time out after 15
  seconds. The page retained its key and blocked new mutations. After resuming
  the app, eight replays agreed on one recovered refund response. Inspection
  showed 100 minor units refunded and one reversing journal. This verifies
  recovery from an uncertain browser outcome; it does not prove when the
  original request committed relative to its timeout.

`npm run check` passed pinned formatting and JavaScript syntax checks. Repository
style, shell syntax, Compose validation and regenerated evidence checks passed.
These are local functional checks, not a throughput or production qualification.

## Final flow and performance audit

On 2026-10-13, the expanded Java suite passed 20 tests with zero failures,
errors or skips: 18 PostgreSQL and 2 real Redis HTTP tests. The native currency
module test and nine adversarial performance-validator tests also passed.
See `docs/testing.md` for the exact covered paths and remaining boundaries.

`python3 scripts/flow-smoke.py` passed 34 real HTTP requests, including cancel
before confirmation, cancel after authorization, exact refund replay, full
refund, terminal rejection, pagination and automatic JPY completion.

`python3 scripts/kafka-recovery.py` kept a committed intent processing during
a 25-second broker outage. Recovery completed about 8.1 seconds after broker
restart, with one provider operation and one balanced journal. The broker was
restored automatically, and no unrelated service was stopped.

The retained local performance studies include smoke, two higher-rate sustained
runs, mixed lifecycles, stepped stress, two lower-rate passing baselines, an
incorrectly mapped mixed alias classified as unqualified, and its corrected
repeat. The two 25 create arrivals/s baselines and corrected two-workflow/s
mixed repeat met declared budgets. Higher-rate observations did not. Failed
runs remain published; `docs/performance.md` explains drops, response ambiguity,
latency failures and the stress drain deadline. All financial invariant checks
passed; stress delivery did not drain within its five-minute budget.

`npm run check`, repository style, SQL-backed concurrency evidence, performance
artifact recomputation, README number validation, Python harness checks, shell
syntax and Compose validation passed. Qualification-scale targets remain unmeasured.

Remote audit validation: [PR #2](https://github.com/rajeev-chaurasia/pay-rail/pull/2)
passed both push and pull-request CI on commit `ba6fe8e`, including the twenty
Java integration tests and retained evidence checks. Review and merge remain
maintainer gates.
