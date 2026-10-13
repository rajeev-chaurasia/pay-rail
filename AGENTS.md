# PayRail contributor contract

This file is the canonical contributor contract. Keep project-specific detail
in the documents below rather than duplicating instructions.

## Start every task

1. Inspect the branch and working tree; preserve unrelated changes.
2. Read `.agent/TASKS.md` and its active plan, then `.agent/PROJECT.md`.
3. Read `.agent/CODING_STANDARDS.md`, relevant architecture decisions, and
   adjacent code and tests before editing.
4. Define the acceptance path and implement a coherent scoped change.
5. Run applicable checks and update the tracker and affected documentation.

## Routing

| Surface | Read | Required verification |
| --- | --- | --- |
| API and business behavior | `.agent/ARCHITECTURE.md`, service and controller tests | Maven verify; authorization and failure paths |
| Database and migration | SQL migrations, migration services, `docs/implementation-plan.md` | Real PostgreSQL tests, reconciliation and rollback behavior |
| Outbox and provider | Outbox, provider worker, evidence contract | Redelivery, response loss and stale lease tests |
| Claims and experiments | `docs/evidence.md`, raw evidence and validator | Recompute results; negative control must fail as designed |
| CI and dependencies | `CONTRIBUTING.md`, `pom.xml`, workflow | Formatting, style, tests, package and Compose validation |

## Product boundaries

- This service simulates payments; it does not process card data or move funds.
- PostgreSQL owns monetary correctness. Redis admission and Kafka delivery
  cannot replace transaction and uniqueness guarantees.
- Every tenant-owned read and relation must be scoped to the authenticated tenant.
- Publish measured claims only with reproducible evidence and stated limits.
  The 25K/s, 100M-object and 1M-fault figures are qualification targets.
- Never expose credentials, real customer information or sensitive payloads
  in code, logs, fixtures, commits or published evidence.

## Delivery

- Keep HTTP controllers thin, services focused and domain objects typed.
- Do not edit or print real environment files. Document configuration through
  `.env.example`; local demonstration credentials are explicitly synthetic.
- No destructive Git operations or force pushes without explicit authorization.
- Remote migrations, environment resets, deployments, merges and external
  configuration changes require authorization for that action.
- Use conventional commit titles and short-lived product-focused branches.
  Do not attribute source, comments, branches or product docs to authoring tools.
- Review must include commands and outcomes, manual acceptance, risk and gaps.
- A local green build is not a merged release or proof of production readiness.

## Instruction routing

Any editor-specific routing file must point here rather than copy the contract.
