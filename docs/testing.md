# Test coverage and acceptance

The separately retained [2026-10-14 GCP campaign](gcp-qualification-results.md)
adds a fully reconciled 100M synthetic history and one million observed HTTP
fault actions. Its 25K/s probes and strict migration foreground gate failed;
production and broad fault qualification remain open. Local results below
retain their original workload and resource limits.

The acceptance scope is the implemented simulated API and playground. Passing
these checks does not establish every possible distributed failure, production
readiness, or the qualification-scale figures in the project plan.

## Automated boundary coverage

| Flow | Verification | Result |
| --- | --- | --- |
| Missing, invalid and disabled credentials | Real PostgreSQL HTTP tests | Pass |
| Missing, empty and malformed idempotency keys | HTTP boundary matrix | Pass |
| Unsupported contract and malformed request body | HTTP boundary matrix | Pass |
| Amount bounds, currency, capture method and metadata object | HTTP boundary matrix | Pass |
| Same-key concurrent create and canonical metadata | PostgreSQL race tests and retained negative control | Pass |
| Changed fingerprint or reused key across operations | HTTP and service tests | Pass |
| Saved wire bytes and immutable version transforms | Exact-body replay and legacy/current reads | Pass |
| Tenant get, list, inspection and mutation isolation | HTTP cross-tenant 404 and composite FK tests | Pass |
| Keyset list, second page and terminal empty page | Real PostgreSQL HTTP tests | Pass |
| Manual authorize and full capture | HTTP and ledger checks | Pass |
| Partial capture and repeated capture rejection | HTTP checks | Pass |
| Cancel before confirmation and after authorization | HTTP flow smoke and integration checks | Pass |
| Illegal confirmation or capture after cancel | HTTP and mixed workload checks | Pass |
| Partial and full refunds with exact replay | HTTP smoke and integration checks | Pass |
| Concurrent refunds exceeding remaining captured amount | Barrier-started refund race and money totals | Pass |
| Empty, unbalanced, unposted and mutable journals | Direct commit-time PostgreSQL constraint checks | Pass |
| Provider accepts but loses its response | Stable-key retry and one-journal test | Pass |
| Stale outbox publisher acknowledgement | Fenced lease takeover test | Pass |
| Inspection snapshot and sanitization | Repeatable read, tenant joins and omitted sensitive fields | Pass |
| Admin token and batch bounds | HTTP migration tests | Pass |
| Backfill resume and concurrent source writes | PostgreSQL checkpoint/reconciliation tests | Pass |
| Diverged migration target and read gate fallback | Gate rejection and full response comparison | Pass |
| Redis concurrent quota, TTL and 429 header | Real Redis HTTP tests | Pass |
| Redis outage and recovery | Paused test-owned Redis plus real HTTP checks | Pass |
| Currency minor-unit display, including JPY | Native browser-module tests | Pass |
| Evidence validator detects corrupted financial observations | Nine adversarial validator tests | Pass |

The Java suite contains 27 PostgreSQL integration tests, 2 real Redis tests,
2 production-configuration tests, 1 dispatcher test and 2 quarantine tests.
Several tests cover a matrix of request outcomes, so test count is not flow count.
The Redis test checks the configured TTL; it does not wait a full minute to
prove refill at the next window. The filename/format guard is not a full-history
credential scanner.

## Real-stack and browser acceptance

`python3 scripts/flow-smoke.py` exercises the actual HTTP service, saved bytes,
manual capture, rejection paths, both cancellation points, partial/full refund,
balanced inspection, pagination and Kafka-driven automatic JPY payment completion.
It retains observed status codes and timings under `evidence/flows/`.

The playground was exercised for create, eight saved-request replays, fingerprint
conflict, automatic processing, manual authorization/capture, refund journals,
version comparison, migration token entry, backfill, reconciliation and gate.
A paused local app produced an uncertain refund outcome; the page retained its
key and blocked new mutations, then recovered through eight agreeing retries.
Desktop and compact geometry were checked without horizontal overflow. A full
accessibility audit and automated cross-browser matrix have not been performed.

The final browser check rendered a 1000-minor-unit JPY payment and its capture
journal as ¥1,000, with a ¥0 ledger difference. See
[the recorded JPY view](assets/playground-jpy.png).

`python3 scripts/kafka-recovery.py` stops only the named local broker, verifies
that a committed processing intent waits without a ledger effect, restores the
broker in a finally block and checks one provider operation and one balanced
journal after recovery. This is an explicit local transport experiment, not a
million-fault campaign.

## Commands

```sh
npm ci --ignore-scripts
npm run check
mvn --batch-mode verify
python3 scripts/check_style.py --self-test
python3 scripts/validate_concurrency_evidence.py --self-test
python3 -m unittest discover -s scripts/performance -p 'test_*.py'
python3 scripts/performance/validate.py --allow-unqualified
python3 scripts/flow-smoke.py
```

The performance validator accepts failed capacity observations only with
`--allow-unqualified`; monetary invariant failures always fail. Its normal mode
also fails on missed load, latency or recovery budgets. See `docs/performance.md`.

## Remaining qualification

The local studies do not prove 25K mutating requests/s, a 100M-object migration,
a million recorded faults, a real payment-provider contract, full network
partition behavior, rolling multi-region deployments, or production role/RLS
isolation. Those remain separately sized and reviewed qualification work.

## Production-hardening additions

Docker tests exercise concurrent independent-head claiming, pipelined delivery
failure handling, 10,000 historical rows with checkpoint rollback/resume and live
dual writes, 10,000 provider completion redeliveries, real restricted-role payment
operations, production configuration rejection and the Prometheus endpoint.
These counts refer to specific deterministic cases, not a broad million-fault
campaign. See `docs/production-readiness.md` for the complete Docker command path.

Additional acceptance rejects fractional minor units for both API versions,
capture and refund instead of truncating them. Malformed JSON returns a sanitized
contract error. A forced historical-insert/foreground-update race reproduced a
PostgreSQL deadlock before the source-first locking fix; the corrected race and
full suite pass. The million-call case is documented with its narrower scope
in `docs/production-readiness.md`. The two qualification-validator tests reject
corrupted counts, duplicate effects and non-overlapping worker observations.

## Isolated Docker recovery

After building the runtime and verification images, run:

```sh
bash scripts/recovery-docker.sh
```

The wrapper creates a unique `payrail-recovery-*` project with fresh synthetic
PostgreSQL, Redis, Kafka and application services. It removes only that project's
containers and volumes on exit. It never resets the playground database.

The drill stops its broker, commits an asynchronous confirmation, SIGKILLs its
application and PostgreSQL, and restarts the database before the application.
It requires settlement, complete outbox drain, one balanced journal and one
provider effect, then checks exact confirmation response replay.

With its application stopped, it takes an in-memory custom-format logical dump.
A truncated copy must fail restoration into a separate scratch database. A full
restore into a fresh test database must match hashes of every row and column in
all public tables and replay saved create/confirm HTTP status and response bytes.
Only sanitized observations and hashes are retained; no SQL dump is published.
CI runs this drill against its newly built runtime. Local evidence is retained
in `evidence/flows/docker-recovery.json`; default output is ignored under
`artifacts/recovery.json`.

This is one synthetic payment and one combined crash schedule. A stopped-writer
logical restore is separate from online backup, WAL/PITR, failover and recovery
at production data volumes. Those gates remain open.

The subsequent physical/WAL drill uses `bash scripts/pitr-docker.sh` and a
separate restored API with delivery fenced. It verifies live payment writes
during backup, named-point recovery, exact table/response comparison, a missing
WAL negative control and a balanced post-restore reversal. See
`docs/postgres-recovery.md` for the commands, evidence and production boundary.
