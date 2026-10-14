# Project contract

PayRail is a Java 17 payment-intent reference service using Spring Boot,
PostgreSQL, Kafka and Redis. Its supported local acceptance path creates an
intent, confirms through the simulated provider, observes a balanced ledger
posting and retries without another effect.

Amounts are integer minor units. Supported operations include create, get,
list, confirm, capture, cancel and refund. Version transforms are immutable;
mutation retries replay stored response bytes. Migration controls demonstrate
additive expansion, dual writes, resumable backfill, shadow reads and gated
read cutover.

The 25K/s and broad production fault/migration qualification remain targets.
An isolated GCP run reconciled 100M homogeneous historical objects and observed
one million successful HTTP fault actions, with narrower scopes and failed
capacity/foreground gates. See `docs/gcp-qualification-results.md`. These results
and local evidence do not establish production suitability.
See `docs/implementation-plan.md`, `docs/verification.md` and `docs/evidence.md`.
