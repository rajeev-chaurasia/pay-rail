# Supported runtime with preserved wire contracts

## Decision

Use Spring Boot 4.1.1 and Springdoc 3.1.1. Pin patched Jackson 2/3 BOMs,
Tomcat and LZ4 versions where the managed defaults still have reported fixes.
The runtime image updates the two OS packages with available fixes, keeps its
non-root Java entrypoint and removes the unused
base-image Pebble service-manager binary.

The Jackson 2 compatibility module remains the explicit MVC and application
mapper for the existing domain and fingerprint code. Configuration moves to
`spring.jackson2`; MVC selects `jackson2`. This avoids mixing two JSON tree
models in idempotency, provider events or version transforms. Migrate to
Jackson 3 in a separately verified change before this deprecated compatibility
module is removed by a future Spring Boot release.

## Reason and tradeoffs

The Docker scan found high/critical findings in the original runtime. The
latest Spring Boot 3.5 patch reduced them, but Spring Framework 6.2.19 has no
published patch for the recorded MVC advisory; the supported fix is 7.0.9.
A major runtime upgrade therefore requires explicit contract, PostgreSQL,
Redis, Kafka and OpenAPI acceptance rather than a version-only edit.

The scanner's dated reports are retained, including intermediate findings.
A passing high/critical gate is not a comprehensive security audit. Review
remaining severities, base packages, broker/database images, transport policy,
authentication, RLS and infrastructure independently before release.

## Validation

The complete Docker suite covers lifecycle, races, exact saved responses,
legacy/current transforms, OpenAPI, outbox batching/fencing, provider retries,
real Redis failures, restricted database roles and historical backfill.
`scripts/compatibility-smoke.py` creates four synthetic requests against the old
running image, then replays them after cutover. It checks identical status and
wire bytes for both versions, decimal/nested metadata, a changed image identity
and four committed objects. Repeat load studies describe their own source and
image identities; old observations do not certify a later dependency snapshot.

Sources: [Spring Boot JSON compatibility](https://docs.spring.io/spring-boot/reference/features/json.html),
[Spring Boot 4.1.1](https://github.com/spring-projects/spring-boot/releases/tag/v4.1.1),
[Spring MVC advisory](https://github.com/advisories/GHSA-pc63-qcmh-9cmg).
