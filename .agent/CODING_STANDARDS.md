# Coding standards

Use focused classes, explicit types and constructor injection. Separate HTTP
validation, business behavior, SQL access and external delivery. Reuse existing
types and helpers rather than adding parallel abstractions.

Java uses the pinned formatter in `pom.xml`. Classes use PascalCase, methods
and fields use camelCase, constants use UPPER_SNAKE_CASE, SQL names use lower
snake_case and environment names use UPPER_SNAKE_CASE.

Prefer methods of at most 30 lines and at most three explicit arguments.
Extract coherent operations, not arbitrary fragments. Constructor injection,
records, framework endpoint signatures, declarative SQL text and test setup
may exceed those limits when splitting would hide the contract; explain material
exceptions in review. Do not compress statements to evade readability limits.

Validate at public boundaries. Use typed request and response structures.
Use specific exceptions and explicit retry policy. Preserve interrupted-thread
state and never silently discard a failed event. Catch broad exceptions only at
a boundary with a documented recovery action.

Money uses checked integer minor units. Every tenant-owned query and relation
must include tenant scope. Never weaken a unique key or commit constraint to
make a test pass. Never call external services while holding a money transaction.

Comments explain decisions or invariants. Do not add authoring-tool attribution,
em dashes or en dashes in prose. Do not suppress checks without explaining why.
Never log tokens, peppers, full sensitive request bodies or customer data.

Test behavior at its owning boundary. Use real PostgreSQL for SQL semantics,
concurrent races for idempotency, adversarial cases for authorization, and negative
controls for published evidence. Formatting-only changes need the existing suite,
not tests that restate formatting.
