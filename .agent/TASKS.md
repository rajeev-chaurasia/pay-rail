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

Status: locally verified; maintainer review and scale qualification remain pending.

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
