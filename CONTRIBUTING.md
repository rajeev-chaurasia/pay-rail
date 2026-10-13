# Contributing to PayRail

Read [AGENTS.md](AGENTS.md), [.agent/TASKS.md](.agent/TASKS.md),
[.agent/PROJECT.md](.agent/PROJECT.md),
[.agent/ARCHITECTURE.md](.agent/ARCHITECTURE.md) and
[.agent/CODING_STANDARDS.md](.agent/CODING_STANDARDS.md) before changing behavior.

## Setup and checks

Use Java 17, Maven 3.9+, Python 3.10+ for repository checks, Docker and Compose v2.
`./scripts/dev-up.sh` builds the JAR and starts the isolated local stack.
Configuration names and synthetic defaults are documented in `.env.example`.
Compose reads its port variables; application environment variables must be
provided to the JVM or explicitly forwarded by the Compose service.

Before review, run the same gates as CI:

```sh
python3 scripts/check_style.py
mvn --batch-mode verify
docker compose -p payrail config --quiet
```

Maven checks Java formatting, runs tests against an ephemeral real PostgreSQL
container and packages the service. Docker must be available for tests.
Use `mvn spotless:apply` to format Java after editing. Evidence reproduction
and validation commands are documented in [docs/evidence.md](docs/evidence.md).
Inspect changed shell scripts with `bash -n`; record any additional manual
runtime checks in the task and verification document.

## Reviews and delivery

Use a task or issue with acceptance criteria. Keep each pull request focused.
Conventional commit subjects describe product changes, such as
`fix(outbox): reject acknowledgements from stale publishers`.
Use short-lived `feature/`, `fix/` or `chore/` branches based on `main`.

The PR template requires scope, task reference, validation commands, manual
acceptance, risk and outstanding work. Require green checks and a peer review
before merging; repository branch protection must be configured separately.
Do not merge or publish merely to satisfy a local completion checklist.

## Evidence and style

No em dashes, en dashes in prose, or authoring-tool attribution. Comments
explain why. No real secrets or customer data. Deterministic transforms and
validators must produce stable outputs for the same inputs; randomness in
experiments must have a recorded seed or be explicitly documented.

Correctness experiments need raw observations and an independent validator.
Concurrency experiments must show overlapping attempts, not only repeated
requests. A deliberately broken control must fail under the same harness.
Keep controls in test code; production cannot disable correctness guards.
