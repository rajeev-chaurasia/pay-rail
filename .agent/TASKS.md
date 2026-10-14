# Task tracker

Active plan: `docs/implementation-plan.md`.

## PAY-001: runnable payment service

Status: locally verified; release qualification and maintainer review remain pending.

Acceptance: authenticated intent operations, fingerprint idempotency and pinned
responses, balanced immutable ledger, Kafka provider/outbox flow, Redis limits,
resumable migration and guarded read cutover.

Evidence: `docs/verification.md`; eleven tests and local Compose smoke recorded
before the contributor-alignment task. Scale qualification remains pending.

## PAY-002: align contributor and evidence conventions

Status: locally verified; release qualification and maintainer review remain pending.

Acceptance:

- Canonical contributor contract, task routing, architecture and standards.
- Java formatting and repository style checks enforced in local verification/CI.
- Security policy, environment example and review template.
- Real concurrent correctness experiment with an unguarded negative control,
  raw attempt intervals and an independent evidence validator.
- Relevant existing tests and new evidence checks pass; measured results and
  remaining limitations are documented.

Sources and scope: `docs/contributor-conventions.md`.

Verification: `mvn -B verify -Dpayrail.evidenceDir=evidence/concurrency`
passed 12 tests with zero failures/errors/skips and the pinned format check.
The retained experiment had eight overlapping guarded attempts with one
synthetic effect and eight unguarded effects. Independent validation rejected
seven doctored artifacts. Style self-tests, shell syntax and Compose validation
passed. See `docs/evidence.md` for the exact scope and trust boundary.

Review: implementation and contributor adaptation were reviewed during the task.
Independent maintainer review and remote CI remain outstanding.

## PAY-003: live payment playground

Status: merged to main through PR #1 with passing remote CI. Scale qualification
remains separate.

Acceptance: a responsive same-origin interface for payment lifecycle actions,
concurrent idempotency retries and conflicts, API-version comparison, and
authenticated persisted ledger/outbox inspection. Migration controls require an
explicit admin credential. All screens show real responses and label simulation.
Keyboard access, visible error states, browser verification and relevant backend
tests are required. No invented throughput metrics or browser-stored credentials.

Verification: thirteen PostgreSQL integration tests passed, including tenant
isolation and sanitized inspection. Browser checks covered create, eight replays,
fingerprint conflict, automatic confirmation, refund/reversing journal, manual
authorization/capture, version comparison and explicit migration authentication,
backfill/reconciliation/gate. Compact and desktop layouts were checked.
Pinned frontend formatting/syntax, repository style and regenerated concurrency
evidence validation passed. See `docs/playground.md` and `docs/verification.md`.

## PAY-004: full flow audit and measured local performance

Status: locally verified and published in PR #2. GitHub push and pull-request
CI passed on audit commit `ba6fe8e`; merged to main with passing merge CI.
Qualification-scale targets remain separate.

Acceptance: expanded HTTP authorization, validation, lifecycle, refund race,
pagination, versioning and migration checks; explicit flow coverage matrix;
colored Mermaid architecture; reproducible open-loop smoke, sustained, stress
and mixed-workload tests with raw observations, environment provenance,
accepted/rejected request separation, latency percentiles, bounded outbox drain
and independently recomputed post-run financial/migration invariants.
Results must state local resource and workload limits. Qualification targets
remain unclaimed unless measured at the specified scale.

Evidence: twenty Java PostgreSQL/Redis tests, one native currency test and nine
adversarial performance-validator tests passed. The real HTTP smoke exercised
34 requests; broker interruption recovered one provider operation and one
balanced journal. Two 25 create arrivals/s baselines passed; a corrected two
workflow arrivals/s mixed study completed 121 workflows, 1,086 requests, 174
journals and 116 refunds with zero accounting/migration mismatch. Higher rates
did not meet declared capacity budgets and remain retained as unqualified runs.
README architecture, coverage matrix, reproducible scripts, raw observations,
independent report rendering, GitHub description and topics are updated.

## PAY-005: production safeguards and Docker qualification

Status: merged through PR #3; pull-request and merged-main CI passed. Production
release and qualification-scale gates remain open.

Acceptance: complete verification runs in Docker; bounded batched outbox lanes
retain fencing and ordered heads; pending predecessor lookup has a concurrent
index; set-based backfill preserves atomic checkpoints and version guards;
real PostgreSQL runtime-role grants are exercised; production configuration
fails closed on insecure settings; Prometheus exports actual backlog/freshness;
repeated sustained, mixed, stress and bounded target-probe evidence is retained
with unchanged budgets. Document infrastructure and provider qualification gaps.

Evidence: 34 Java, 1 currency and 11 Python validator tests; source-first lock
race after an observed deadlock negative control; byte-exact cross-runtime
replay; real poison quarantine and subsequent settlement; one million completion
calls including 999,999 duplicates; paired 100-arrivals/s and stepped stress
passes. Bounded 25K probes fail, and a 100M storage preflight prevents seeding.
Runtime high/critical vulnerability gate passes with remaining OS findings
retained. See `docs/production-readiness.md` for exact scopes and open gates.

## PAY-006: isolated Docker recovery drills

Status: merged through PR #4; pull-request and merged-main CI passed.
Production recovery qualification remains separate.

Acceptance: disposable project-owned application, PostgreSQL, Redis and Kafka;
committed processing intent survives application and database SIGKILL; restored
infrastructure drains the outbox with one balanced journal and provider effect;
stopped-writer logical backup restores every table exactly and replays saved
HTTP response bytes; a truncated backup is rejected. Preserve playground data.
Record exact images and limits. PITR, failover and larger crash campaigns remain
separate qualification gates.

Evidence: `evidence/flows/docker-recovery.json` records the repeat drill with
48.35-second combined crash recovery, 10.22-second logical restore/startup,
13 table hashes, three exact response replays and a rejected truncated backup.
The full Docker suite passed 34 Java, 1 currency and 11 Python cases. CI now
runs the isolated drill on each newly built runtime.

## PAY-007: online physical backup and point-in-time recovery

Status: locally verified; maintainer merge and production qualification remain
separate delivery gates.

Acceptance: disposable project-owned services; observed payment writes during
physical backup; manifest verification; archived WAL restores an independent
database to a named point before later source mutations; all public-table hashes
match that point; exact saved HTTP response replay; unique balanced settlement
and one post-restore reversal; missing WAL must reject incomplete recovery.
Restored outbox and Kafka consumers remain disabled. Retain sanitized evidence
and independently validate hashes, statuses and entry balances with tampering
controls. CI must run the drill against its newly built runtime.

Production retention, off-host archive durability, RPO/RTO, failover, scale and
external-provider reconciliation remain independent operator gates.

Evidence: three local PITR drills passed. The retained final run reports a
31.45-second deliberately throttled online backup and 5.26-second restore/API
verification, matching all 13 table hashes. Missing post-backup WAL makes the
negative server exit nonzero. Three HTTP response digests match; sanitized entry
data independently recomputes balanced settlement/reversal and distinct effect
keys. The full Docker verifier passed 34 Java, 1 currency and 13 Python cases,
including two new tampering tests. See `docs/postgres-recovery.md` for limits.
