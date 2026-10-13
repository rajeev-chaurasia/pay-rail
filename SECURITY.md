# Security policy

Only the current main development line is maintained. This reference service
uses a simulated provider and is not qualified for real funds or card data.

Report exploitable vulnerabilities privately through GitHub private
vulnerability reporting when enabled. If unavailable, contact the repository
owner through an established private channel before publishing exploit details.
Do not include credentials or personal information in a public issue.

## Security-relevant behavior

- Tenant escape, missing authorization and API-key disclosure.
- Duplicate ledger or provider effects, forged replay and idempotency conflicts.
- Unbalanced, mutable or cross-tenant journals.
- Stale worker effects, lost committed events and unsafe migration cutovers.
- Forged experiment artifacts or validators accepting unsupported claims.

Include the affected revision, a synthetic reproduction, expected and observed
behavior, and relevant redacted logs. Fixes must include an adversarial regression
test at the boundary that failed.

## Trust boundaries

Tenant isolation currently depends on authenticated query predicates and
composite foreign keys; PostgreSQL RLS is not implemented. The demo database
role owns its schema. Production needs least-privilege roles, secret management,
TLS, operational alerting and separately reviewed provider integration.
Local ports bind to loopback. Never reuse the demo pepper, admin token or
database credentials outside the local fixture.
