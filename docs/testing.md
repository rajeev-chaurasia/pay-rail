# Test coverage and acceptance

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

The Java suite contains 18 PostgreSQL integration tests and 2 real Redis tests.
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
