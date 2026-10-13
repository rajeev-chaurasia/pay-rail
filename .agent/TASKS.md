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
